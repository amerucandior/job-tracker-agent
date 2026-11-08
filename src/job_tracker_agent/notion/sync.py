"""Notion sync reconciler for matching applications and synchronizing updates.

Adheres to docs/adr/0002-in-page-timeline-callouts.md.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional
from notion_client import Client

from job_tracker_agent.models import EmailMessage, ExtractedApplication
from job_tracker_agent.storage.checkpoint import CheckpointStore

logger = logging.getLogger(__name__)


class NotionSyncReconciler:
    """Reconciles extracted email hiring data into the Notion Job Board."""

    def __init__(
        self,
        api_key: str,
        database_id: str,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self.client = Client(auth=api_key)
        self.database_id = database_id.replace("-", "")
        self.store = checkpoint_store

    def reconcile(
        self, extracted: ExtractedApplication, email: EmailMessage
    ) -> tuple[str, bool, Optional[str]]:
        """Reconcile extracted data into Notion.

        Returns:
            (page_id, is_new_card, previous_stage_or_none)
        """
        existing_page_id, current_stage = self._find_existing_page(
            email.thread_id, extracted.company, extracted.role
        )

        stage_changed = current_stage is not None and current_stage != extracted.stage.value

        if existing_page_id:
            # Update existing application page
            self._update_application_page(
                existing_page_id, extracted, email, current_stage
            )
            # Map thread to this page in SQLite
            self.store.map_thread_to_notion_page(
                thread_id=email.thread_id,
                notion_page_id=existing_page_id,
                company=extracted.company,
                role=extracted.role,
            )
            return (existing_page_id, False, current_stage if stage_changed else None)

        # Create new application page
        new_page_id = self._create_application_page(extracted, email)
        self.store.map_thread_to_notion_page(
            thread_id=email.thread_id,
            notion_page_id=new_page_id,
            company=extracted.company,
            role=extracted.role,
        )
        return (new_page_id, True, None)

    def _find_existing_page(
        self, thread_id: str, company: str, role: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Find an existing Notion application page using thread-first matching with fallback."""
        # 1. Check local SQLite thread cache
        cached = self.store.get_notion_page_for_thread(thread_id)
        if cached:
            try:
                page = self.client.pages.retrieve(page_id=cached["notion_page_id"])
                stage_val = self._extract_stage_from_page(page)
                return (cached["notion_page_id"], stage_val)
            except Exception:
                pass

        # 2. Query Notion database by Thread IDs property
        try:
            results = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": "Thread IDs",
                    "rich_text": {"contains": thread_id},
                },
                page_size=1,
            )
            pages = results.get("results", [])
            if pages:
                page_id = pages[0]["id"]
                return (page_id, self._extract_stage_from_page(pages[0]))
        except Exception as e:
            logger.warning(f"Error querying Notion by thread ID: {e}")

        # 3. Fallback: Query Notion by Company name (exact title match)
        try:
            results = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": "Company",
                    "title": {"equals": company},
                },
                page_size=5,
            )
            pages = results.get("results", [])
            if pages:
                # If multiple roles at company, try matching role
                normalized_role = role.lower()
                for p in pages:
                    role_text = self._extract_text_property(p, "Role").lower()
                    if normalized_role in role_text or role_text in normalized_role:
                        return (p["id"], self._extract_stage_from_page(p))
                # Otherwise pick the first page for this employer
                return (pages[0]["id"], self._extract_stage_from_page(pages[0]))
        except Exception as e:
            logger.warning(f"Error querying Notion by company name: {e}")

        return (None, None)

    def _create_application_page(
        self, extracted: ExtractedApplication, email: EmailMessage
    ) -> str:
        """Create a new page in the Notion database."""
        recv_date = email.received_at.strftime("%Y-%m-%d")
        properties = {
            "Company": {
                "title": [{"type": "text", "text": {"content": extracted.company}}]
            },
            "Role": {
                "rich_text": [{"type": "text", "text": {"content": extracted.role}}]
            },
            "Stage": {
                "select": {"name": extracted.stage.value}
            },
            "Review Flag": {
                "checkbox": extracted.review_flag
            },
            "Last Activity": {
                "date": {"start": recv_date}
            },
            "Thread IDs": {
                "rich_text": [{"type": "text", "text": {"content": email.thread_id}}]
            },
        }

        callout_block = self._build_timeline_toggle_block(extracted, email, is_new=True)

        res = self.client.pages.create(
            parent={"type": "database_id", "database_id": self.database_id},
            properties=properties,
            children=[callout_block],
        )
        return res["id"]

    def _update_application_page(
        self,
        page_id: str,
        extracted: ExtractedApplication,
        email: EmailMessage,
        previous_stage: Optional[str],
    ) -> None:
        """Update properties and append a timeline block to an existing page."""
        recv_date = email.received_at.strftime("%Y-%m-%d")

        # Fetch current Thread IDs to avoid duplicate appends
        current_page = self.client.pages.retrieve(page_id=page_id)
        current_threads = self._extract_text_property(current_page, "Thread IDs")
        thread_list = [t.strip() for t in current_threads.split(",") if t.strip()]
        if email.thread_id not in thread_list:
            thread_list.append(email.thread_id)
        updated_threads = ", ".join(thread_list)

        properties = {
            "Stage": {
                "select": {"name": extracted.stage.value}
            },
            "Review Flag": {
                "checkbox": extracted.review_flag
            },
            "Last Activity": {
                "date": {"start": recv_date}
            },
            "Thread IDs": {
                "rich_text": [{"type": "text", "text": {"content": updated_threads}}]
            },
        }

        self.client.pages.update(page_id=page_id, properties=properties)

        # Append timeline callout block to body
        callout_block = self._build_timeline_toggle_block(
            extracted, email, is_new=False, prev_stage=previous_stage
        )
        self.client.blocks.children.append(block_id=page_id, children=[callout_block])

    def _build_timeline_toggle_block(
        self,
        extracted: ExtractedApplication,
        email: EmailMessage,
        is_new: bool = False,
        prev_stage: Optional[str] = None,
    ) -> dict[str, Any]:
        """Construct a collapsible toggle block documenting the email interaction."""
        date_str = email.received_at.strftime("%Y-%m-%d %H:%M")
        status_label = extracted.stage.value
        if prev_stage and prev_stage != extracted.stage.value:
            transition_text = f"{prev_stage} ➔ {status_label}"
        else:
            transition_text = status_label

        header_title = f"📩 {date_str} — {transition_text} — {email.subject}"

        children_blocks: list[dict[str, Any]] = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": f"Summary: {extracted.summary}"},
                        }
                    ]
                },
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": f"From: {email.sender_name or ''} <{email.sender_email}> (Provider: {email.provider.value})"
                            },
                        }
                    ]
                },
            },
        ]

        if extracted.action_items:
            children_blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": "Action Items:"},
                                "annotations": {"bold": True},
                            }
                        ]
                    },
                }
            )
            for item in extracted.action_items:
                children_blocks.append(
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [{"type": "text", "text": {"content": item}}]
                        },
                    }
                )

        if extracted.review_flag:
            children_blocks.append(
                {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "⚠️ Flagged for human review: Ambiguity detected during extraction."
                                },
                            }
                        ],
                        "icon": {"emoji": "⚠️"},
                    },
                }
            )

        return {
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": header_title},
                        "annotations": {"bold": True},
                    }
                ],
                "children": children_blocks,
            },
        }

    def _extract_stage_from_page(self, page: dict[str, Any]) -> Optional[str]:
        props = page.get("properties", {})
        stage_prop = props.get("Stage", {})
        # Support both 'select' and 'status'
        if stage_prop.get("select"):
            return stage_prop["select"].get("name")
        if stage_prop.get("status"):
            return stage_prop["status"].get("name")
        return None

    def _extract_text_property(self, page: dict[str, Any], prop_name: str) -> str:
        props = page.get("properties", {})
        prop = props.get(prop_name, {})
        texts = prop.get("rich_text", []) or prop.get("title", [])
        return "".join(t.get("text", {}).get("content", "") for t in texts)
