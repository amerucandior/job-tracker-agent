"""Sync coordinator orchestrating mail ingestion, pre-filtering, extraction, and Notion sync."""

from datetime import datetime, timedelta, timezone
import logging
from typing import Optional
from rich.console import Console

from job_tracker_agent.config import AppConfig, load_config, load_tokens
from job_tracker_agent.engine.extractor import LLMExtractor
from job_tracker_agent.engine.filter import HeuristicPreFilter
from job_tracker_agent.ingestion.base import BaseMailProvider
from job_tracker_agent.ingestion.gmail import GmailProvider
from job_tracker_agent.ingestion.outlook import OutlookProvider
from job_tracker_agent.notion.sync import NotionSyncReconciler
from job_tracker_agent.storage.checkpoint import CheckpointStore
from job_tracker_agent.systemd import send_desktop_notification

logger = logging.getLogger(__name__)
console = Console()


class SyncCoordinator:
    """Coordinates the end-to-end sync cycle."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        checkpoint_store: Optional[CheckpointStore] = None,
    ) -> None:
        self.config = config or load_config()
        self.store = checkpoint_store or CheckpointStore()
        self.screener = HeuristicPreFilter()
        self.extractor = LLMExtractor(self.config.llm)

    def run_sync(
        self,
        backfill_days: Optional[int] = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Execute synchronization across configured accounts.

        Returns:
            Dictionary of metrics (scanned, prefiltered, processed, new_cards, updated_cards, review_flags)
        """
        metrics = {
            "scanned": 0,
            "prefiltered": 0,
            "job_emails": 0,
            "new_cards": 0,
            "updated_cards": 0,
            "review_flags": 0,
        }

        # Validate Notion configuration
        notion_key = self.config.notion.api_key
        notion_db_id = self.config.notion.database_id
        if not dry_run and (not notion_key or not notion_db_id):
            console.print(
                "[bold red]Error:[/bold red] Notion API key or database ID not configured.\n"
                "Run [bold cyan]job-tracker setup-notion[/bold cyan] to configure your board."
            )
            return metrics

        reconciler = (
            NotionSyncReconciler(
                api_key=notion_key,
                database_id=notion_db_id,
                checkpoint_store=self.store,
            )
            if not dry_run
            else None
        )

        providers: list[BaseMailProvider] = self._get_configured_providers()
        if not providers:
            console.print(
                "[yellow]No email accounts authenticated.[/yellow] "
                "Run [bold cyan]job-tracker auth gmail[/bold cyan] or [bold cyan]job-tracker auth outlook[/bold cyan] first."
            )
            return metrics

        effective_backfill = backfill_days or self.config.sync.backfill_days

        for provider in providers:
            self._sync_provider(
                provider=provider,
                reconciler=reconciler,
                backfill_days=effective_backfill,
                dry_run=dry_run,
                metrics=metrics,
            )

        return metrics

    def _get_configured_providers(self) -> list[BaseMailProvider]:
        """Instantiate providers that have stored token credentials."""
        tokens = load_tokens()
        active: list[BaseMailProvider] = []

        if "gmail" in tokens:
            try:
                gmail = GmailProvider()
                if gmail.authenticate(interactive=False):
                    active.append(gmail)
            except Exception as e:
                logger.warning(f"Could not load Gmail provider: {e}")

        if "outlook" in tokens:
            try:
                outlook = OutlookProvider(client_id=self.config.outlook.client_id)
                if outlook.authenticate(interactive=False):
                    active.append(outlook)
            except Exception as e:
                logger.warning(f"Could not load Outlook provider: {e}")

        return active

    def _sync_provider(
        self,
        provider: BaseMailProvider,
        reconciler: Optional[NotionSyncReconciler],
        backfill_days: int,
        dry_run: bool,
        metrics: dict[str, int],
    ) -> None:
        """Process messages for a single provider."""
        provider_name = provider.provider_name
        console.print(f"[cyan]Checking {provider_name.capitalize()} inbox...[/cyan]")

        # Determine sync window
        account_id = f"{provider_name}-account"
        last_sync = self.store.get_last_sync_time(account_id)
        if last_sync:
            since = (
                last_sync.replace(tzinfo=timezone.utc)
                if last_sync.tzinfo is None
                else last_sync.astimezone(timezone.utc)
            )
        else:
            since = datetime.now(timezone.utc) - timedelta(days=backfill_days)

        messages = provider.fetch_messages_since(since)
        metrics["scanned"] += len(messages)

        newest_timestamp = since

        for msg in messages:
            account_id = msg.account_id
            msg_time = (
                msg.received_at.replace(tzinfo=timezone.utc)
                if msg.received_at.tzinfo is None
                else msg.received_at.astimezone(timezone.utc)
            )
            if msg_time > newest_timestamp:
                newest_timestamp = msg_time

            # 1. Skip if already processed in SQLite
            if self.store.is_processed(account_id, msg.message_id):
                continue

            # 2. Heuristic pre-filter
            if not self.screener.is_candidate_email(msg):
                # Mark as processed with no stage to prevent re-filtering
                if not dry_run:
                    self.store.record_processed(
                        account_id=account_id,
                        message_id=msg.message_id,
                        thread_id=msg.thread_id,
                        received_at=msg.received_at,
                        stage=None,
                        review_flag=False,
                    )
                continue

            metrics["prefiltered"] += 1
            console.print(f"  [green]Candidate email found:[/green] '{msg.subject}' from {msg.sender_email}")

            # 3. LLM Extraction
            extracted = self.extractor.extract(msg)
            if not extracted or not extracted.is_job_application:
                if not dry_run:
                    self.store.record_processed(
                        account_id=account_id,
                        message_id=msg.message_id,
                        thread_id=msg.thread_id,
                        received_at=msg.received_at,
                        stage=None,
                        review_flag=False,
                    )
                continue

            metrics["job_emails"] += 1
            if extracted.review_flag:
                metrics["review_flags"] += 1

            console.print(
                f"    [bold]Extracted:[/bold] {extracted.company} — {extracted.role} "
                f"([magenta]{extracted.stage.value}[/magenta])"
            )

            # 4. Notion Reconcile
            if not dry_run and reconciler:
                page_id, is_new, prev_stage = reconciler.reconcile(extracted, msg)
                if is_new:
                    metrics["new_cards"] += 1
                    console.print(f"    [green]+ Created new Notion card[/green] for {extracted.company}")
                else:
                    metrics["updated_cards"] += 1
                    transition_str = f" ({prev_stage} ➔ {extracted.stage.value})" if prev_stage else ""
                    console.print(f"    [blue]↻ Updated Notion card[/blue] for {extracted.company}{transition_str}")

                # Record in local SQLite
                self.store.record_processed(
                    account_id=account_id,
                    message_id=msg.message_id,
                    thread_id=msg.thread_id,
                    received_at=msg.received_at,
                    stage=extracted.stage.value,
                    review_flag=extracted.review_flag,
                    company=extracted.company,
                    role=extracted.role,
                )

                # 5. Desktop Alert if review flag or stage change
                if self.config.sync.desktop_alerts:
                    if extracted.review_flag:
                        send_desktop_notification(
                            title=f"Job Tracker: Review Flagged ({extracted.company})",
                            message=f"{extracted.role}: {extracted.summary}",
                            urgency="critical",
                        )
                    elif prev_stage and prev_stage != extracted.stage.value:
                        send_desktop_notification(
                            title=f"Job Tracker: {extracted.company} Update",
                            message=f"Stage moved to {extracted.stage.value} ({extracted.role})",
                            urgency="normal",
                        )

        # Update checkpoint watermark
        if not dry_run and newest_timestamp > since:
            self.store.update_last_sync_time(
                account_id=account_id,
                timestamp=newest_timestamp,
                provider=provider_name,
            )
