"""CLI command surface for Job Tracker Agent.

Implements unified commands: auth, setup-notion, sync, service, and config.
"""

from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table

from job_tracker_agent.config import (
    AppConfig,
    get_config_dir,
    get_config_path,
    get_database_path,
    get_tokens_path,
    load_config,
    save_config,
)
from job_tracker_agent.ingestion.gmail import GmailProvider
from job_tracker_agent.ingestion.outlook import OutlookProvider
from job_tracker_agent.notion.provisioner import NotionProvisioner, normalize_notion_id
from job_tracker_agent.sync_coordinator import SyncCoordinator
from job_tracker_agent.systemd import generate_service_units, run_systemctl_user

app = typer.Typer(
    name="job-tracker",
    help="AI agent that ingests job application emails and synchronizes a Notion board.",
    add_completion=False,
)
auth_app = typer.Typer(help="Authenticate email provider accounts.")
service_app = typer.Typer(help="Manage background systemd timer and service.")

app.add_typer(auth_app, name="auth")
app.add_typer(service_app, name="service")

console = Console()


@auth_app.command("gmail")
def auth_gmail(
    secret_file: Optional[Path] = typer.Option(
        None,
        "--secret-file",
        "-s",
        help="Path to Google Cloud OAuth client secret JSON file.",
    )
) -> None:
    """Authenticate a Gmail account via Google OAuth2."""
    target_secret = secret_file or (get_config_dir() / "gmail_client_secret.json")
    if secret_file and secret_file != target_secret:
        target_secret.write_bytes(secret_file.read_bytes())
        target_secret.chmod(0o600)

    try:
        provider = GmailProvider(client_secret_path=target_secret)
        console.print("[cyan]Initiating Gmail OAuth authentication...[/cyan]")
        success = provider.authenticate(interactive=True)
        if success:
            console.print("[bold green]✓ Gmail successfully authenticated![/bold green]")
        else:
            console.print("[bold red]✗ Gmail authentication failed.[/bold red]")
    except Exception as e:
        console.print(f"[bold red]Error authenticating Gmail:[/bold red] {e}")


@auth_app.command("outlook")
def auth_outlook(
    client_id: Optional[str] = typer.Option(
        None,
        "--client-id",
        "-c",
        help="Azure AD / Microsoft Entra Application (Client) ID.",
    ),
    mode: str = typer.Option(
        "paste",
        "--mode",
        "-m",
        help="Authentication mode: 'paste' (recommended for personal accounts), 'device', or 'browser'.",
    ),
) -> None:
    """Authenticate an Outlook / Microsoft 365 account via Microsoft Graph."""
    config = load_config()
    target_client_id = client_id or config.outlook.client_id

    if not target_client_id:
        console.print(
            "[bold yellow]Azure Application (client) ID Required:[/bold yellow]\n"
            "Microsoft requires an Azure App Registration for Microsoft Graph Mail access.\n"
            "1. Visit [cyan]https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade[/cyan]\n"
            "2. Click [bold]New registration[/bold] (Name: 'Job Tracker').\n"
            "3. Select [bold]'Accounts in any organizational directory and personal Microsoft accounts'[/bold].\n"
            "4. Under [bold]Authentication[/bold] > [bold]Advanced settings[/bold], set [bold]'Allow public client flows'[/bold] to [bold]Yes[/bold].\n"
            "5. Copy the [bold]Application (client) ID[/bold] from the Overview page.\n"
        )
        target_client_id = typer.prompt("Enter your Azure Application (client) ID").strip()

    config.outlook.client_id = target_client_id
    save_config(config)

    try:
        provider = OutlookProvider(client_id=target_client_id)
        console.print(f"[cyan]Initiating Microsoft Graph OAuth authentication (mode: {mode})...[/cyan]")
        success = provider.authenticate(interactive=True, mode=mode)
        if success:
            console.print("[bold green]✓ Outlook successfully authenticated![/bold green]")
        else:
            console.print("[bold red]✗ Outlook authentication failed.[/bold red]")
    except Exception as e:
        console.print(f"[bold red]Error authenticating Outlook:[/bold red] {e}")


@app.command("setup-notion")
def setup_notion(
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k", help="Notion Integration Token / API Key"),
    parent_page: Optional[str] = typer.Option(
        None, "--parent-page", "-p", help="Parent Notion Page ID to automatically provision database under"
    ),
    database_id: Optional[str] = typer.Option(
        None, "--database-id", "-d", help="Existing Notion Database ID if not auto-provisioning"
    ),
) -> None:
    """Set up or provision the Notion Job Applications board."""
    config = load_config()

    if not api_key:
        api_key = config.notion.api_key or typer.prompt("Enter Notion Integration Token / Secret", hide_input=True)

    config.notion.api_key = api_key

    if database_id:
        config.notion.database_id = normalize_notion_id(database_id)
        save_config(config)
        console.print(f"[bold green]✓ Configured existing Notion database ID:[/bold green] {config.notion.database_id}")
        return

    if not parent_page:
        parent_page = config.notion.parent_page_id or typer.prompt(
            "Enter parent Notion Page ID (from URL) where database will be created"
        )

    clean_parent_id = normalize_notion_id(parent_page)
    config.notion.parent_page_id = clean_parent_id

    console.print(f"[cyan]Provisioning standardized Job Applications database under page {clean_parent_id}...[/cyan]")
    try:
        provisioner = NotionProvisioner(api_key=api_key)
        new_db_id = provisioner.create_database(parent_page_id=clean_parent_id)
        config.notion.database_id = new_db_id
        save_config(config)
        console.print(f"[bold green]✓ Successfully provisioned Notion database:[/bold green] {new_db_id}")
    except Exception as e:
        err_msg = str(e)
        console.print(f"[bold red]Error provisioning Notion database:[/bold red] {err_msg}")
        if "Could not find page with ID" in err_msg or "ObjectNotFound" in err_msg:
            console.print(
                "\n[bold yellow]Notion Permission Required:[/bold yellow]\n"
                "Your Notion page must be explicitly shared with your integration:\n"
                "1. Open the page in Notion in your browser.\n"
                "2. Click the [bold]...[/bold] button in the top right corner.\n"
                "3. Scroll down to [bold]Connections[/bold] (or [bold]Add connections[/bold]).\n"
                "4. Search for your integration and click [bold]Connect[/bold].\n"
                "5. Re-run this command."
            )


@app.command("sync")
def sync_emails(
    backfill_days: Optional[int] = typer.Option(
        None, "--backfill-days", "-b", help="Number of past days to scan on first sync."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Scan emails and preview LLM extraction without writing to Notion."
    ),
) -> None:
    """Ingest emails, extract hiring updates, and synchronize the Notion board."""
    coordinator = SyncCoordinator()
    console.print("[bold]Starting Job Tracker synchronization cycle...[/bold]")

    metrics = coordinator.run_sync(backfill_days=backfill_days, dry_run=dry_run)

    table = Table(title="Sync Summary", border_style="cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Total Scanned Emails", str(metrics["scanned"]))
    table.add_row("Matched Heuristic Filter", str(metrics["prefiltered"]))
    table.add_row("Job Application Emails", str(metrics["job_emails"]))
    table.add_row("New Cards Created", str(metrics["new_cards"]))
    table.add_row("Cards Updated", str(metrics["updated_cards"]))
    table.add_row("Items Flagged for Review", str(metrics["review_flags"]))

    console.print(table)


@service_app.command("install")
def service_install(
    interval_minutes: int = typer.Option(30, "--interval", "-i", help="Polling interval in minutes")
) -> None:
    """Generate and install user systemd service and timer units."""
    working_dir = Path(__file__).resolve().parent.parent.parent
    service_file, timer_file = generate_service_units(working_dir, interval_minutes=interval_minutes)
    console.print(f"[green]✓ Wrote service unit:[/green] {service_file}")
    console.print(f"[green]✓ Wrote timer unit:[/green] {timer_file}")

    run_systemctl_user(["daemon-reload"])
    console.print("[bold green]✓ systemd daemon reloaded.[/bold green]")
    console.print("Run [bold cyan]job-tracker service enable[/bold cyan] to activate the timer.")


@service_app.command("enable")
def service_enable() -> None:
    """Enable and start the user systemd timer."""
    res = run_systemctl_user(["enable", "--now", "job-tracker.timer"])
    if res.returncode == 0:
        console.print("[bold green]✓ job-tracker.timer enabled and running.[/bold green]")
    else:
        console.print(f"[bold red]Failed to enable timer:[/bold red] {res.stderr}")


@service_app.command("status")
def service_status() -> None:
    """Check the status of the job-tracker timer and service."""
    res = run_systemctl_user(["status", "job-tracker.timer"])
    console.print(res.stdout or res.stderr)


@service_app.command("logs")
def service_logs(
    lines: int = typer.Option(30, "--lines", "-n", help="Number of journal log lines to display")
) -> None:
    """View recent systemd journal logs."""
    import subprocess
    subprocess.run(["journalctl", "--user", "-u", "job-tracker.service", f"-n{lines}", "--no-pager"])


@app.command("config")
def show_config() -> None:
    """Display current paths and configuration settings."""
    config = load_config()
    table = Table(title="Job Tracker Configuration", border_style="cyan")
    table.add_column("Item", style="bold")
    table.add_column("Value")

    table.add_row("Config Directory", str(get_config_dir()))
    table.add_row("Config File", str(get_config_path()))
    table.add_row("Tokens File", str(get_tokens_path()))
    table.add_row("SQLite Database", str(get_database_path()))
    table.add_row("Notion Configured", "Yes" if config.notion.api_key else "No")
    table.add_row("Notion Database ID", config.notion.database_id or "(none)")
    table.add_row("LLM Provider", config.llm.provider)
    table.add_row("LLM Model", config.llm.model_name)
    table.add_row("Backfill Days", str(config.sync.backfill_days))
    table.add_row("Polling Interval", f"{config.sync.polling_interval_minutes}m")
    table.add_row("Desktop Alerts", "Enabled" if config.sync.desktop_alerts else "Disabled")

    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
