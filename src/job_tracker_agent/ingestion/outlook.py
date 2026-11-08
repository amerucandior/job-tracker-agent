"""Outlook / Microsoft 365 ingestion provider using MSAL and Microsoft Graph API."""

from datetime import datetime, timezone
import logging
import subprocess
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse
import webbrowser
import msal
import requests
from rich.console import Console

from job_tracker_agent.config import get_config_dir, load_tokens, save_tokens
from job_tracker_agent.ingestion.base import BaseMailProvider, clean_html_to_text
from job_tracker_agent.models import EmailMessage, IngestionProvider

logger = logging.getLogger(__name__)
console = Console()

# Microsoft Graph scopes for reading user email and profile
OUTLOOK_SCOPES = ["Mail.Read", "User.Read"]

DEFAULT_MICROSOFT_CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
CONSUMER_REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"


class OutlookProvider(BaseMailProvider):
    """Ingests job application emails from an Outlook / Microsoft 365 account."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        authority: str = "https://login.microsoftonline.com/consumers",
    ) -> None:
        self.client_id = client_id or DEFAULT_MICROSOFT_CLIENT_ID
        self.authority = authority
        self._access_token: Optional[str] = None
        self._account_email: Optional[str] = None

        self._cache = msal.SerializableTokenCache()
        tokens = load_tokens()
        if "outlook_cache" in tokens:
            try:
                self._cache.deserialize(tokens["outlook_cache"])
            except Exception as e:
                logger.warning(f"Could not deserialize MSAL token cache: {e}")

        self._app = msal.PublicClientApplication(
            self.client_id,
            authority=self.authority,
            token_cache=self._cache,
        )

    @property
    def provider_name(self) -> str:
        return "outlook"

    def _persist_cache(self) -> None:
        """Persist serialized MSAL token cache to tokens.json."""
        if self._cache.has_state_changed:
            tokens = load_tokens()
            tokens["outlook_cache"] = self._cache.serialize()
            tokens["outlook"] = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "account": self._account_email,
            }
            save_tokens(tokens)

    def authenticate(
        self,
        interactive: bool = True,
        mode: str = "paste",
    ) -> bool:
        """Authenticate using stored MSAL cache or interactive authorization."""
        accounts = self._app.get_accounts()

        # 1. Attempt silent token acquisition
        if accounts:
            result = self._app.acquire_token_silent(OUTLOOK_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._access_token = result["access_token"]
                self._account_email = accounts[0].get("username")
                self._persist_cache()
                return True

        if not interactive:
            return False

        # 2. Interactive acquisition
        if mode == "device":
            return self._authenticate_device_code()
        elif mode == "browser":
            return self._authenticate_browser_loopback()
        else:
            return self._authenticate_code_paste()

    def _authenticate_code_paste(self) -> bool:
        """Authorize via browser and copy-pasting the redirected URL (tailored for personal MSA)."""
        flow = self._app.initiate_auth_code_flow(
            scopes=OUTLOOK_SCOPES,
            redirect_uri=CONSUMER_REDIRECT_URI,
        )
        auth_url = flow.get("auth_uri")
        if not auth_url:
            raise RuntimeError("Failed to initiate Microsoft OAuth authorization code flow.")

        # Create local redirect launcher to ensure 100% parameter preservation
        auth_html_path = get_config_dir() / "ms_auth.html"
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Redirecting to Microsoft Sign In...</title>
    <meta http-equiv="refresh" content="0; url='{auth_url}'">
</head>
<body style="font-family: sans-serif; padding: 40px; text-align: center;">
    <h2>Redirecting to Microsoft Sign In...</h2>
    <p>If you are not redirected automatically within 3 seconds, <a href="{auth_url}">click here to sign in</a>.</p>
</body>
</html>"""
        auth_html_path.write_text(html_content, encoding="utf-8")

        console.print("\n[bold yellow]Step 1:[/bold yellow] Opening Microsoft sign-in page in your browser...")
        try:
            subprocess.run(["xdg-open", str(auth_html_path)], check=False)
        except Exception:
            try:
                webbrowser.open(f"file://{auth_html_path}")
            except Exception:
                pass

        console.print(
            "\n[bold yellow]Step 2:[/bold yellow] Sign in with your Microsoft/Outlook account and click [bold]Accept[/bold] (or [bold]Yes[/bold])."
        )
        console.print(
            "[bold yellow]Step 3:[/bold yellow] Your browser will redirect to a blank or confirmation page starting with:\n"
            "         [cyan]https://login.live.com/oauth20_desktop.srf?code=...[/cyan]\n\n"
            "         [bold]Copy the entire URL from your browser address bar[/bold] and paste it below:\n"
        )

        pasted = input("Paste redirected URL (starts with https://login.live.com/...): ").strip()
        if not pasted:
            return False

        if "?" in pasted:
            parsed = urlparse(pasted)
            auth_response = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        elif "=" in pasted:
            auth_response = {k: v[0] for k, v in parse_qs(pasted).items()}
        else:
            auth_response = {"code": pasted}

        result = self._app.acquire_token_by_auth_code_flow(flow, auth_response)
        return self._handle_token_result(result)

    def _authenticate_device_code(self) -> bool:
        flow = self._app.initiate_device_flow(scopes=OUTLOOK_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Failed to initiate Microsoft device code flow: {flow}")

        user_code = flow["user_code"]
        verify_url = flow.get("verification_uri", "https://login.microsoft.com/device")

        console.print(f"\n[bold yellow]Step 1:[/bold yellow] Open [cyan]{verify_url}[/cyan] in your browser.")
        console.print(f"[bold yellow]Step 2:[/bold yellow] Enter the code: [bold green]{user_code}[/bold green]")
        console.print(f"[bold yellow]Step 3:[/bold yellow] Sign in and click [bold]Accept[/bold] on the permissions prompt.\n")

        with console.status("[bold cyan]Waiting for you to complete authorization in browser...[/bold cyan]"):
            result = self._app.acquire_token_by_device_flow(flow)

        return self._handle_token_result(result)

    def _authenticate_browser_loopback(self) -> bool:
        try:
            console.print("[cyan]Opening browser for authentication on http://localhost:8080...[/cyan]")
            result = self._app.acquire_token_interactive(
                scopes=OUTLOOK_SCOPES,
                port=8080,
                prompt="select_account",
            )
            return self._handle_token_result(result)
        except Exception as e:
            logger.warning(f"Browser loopback failed: {e}. Falling back to copy-paste flow.")
            return self._authenticate_code_paste()

    def _handle_token_result(self, result: Optional[dict[str, Any]]) -> bool:
        if result and "access_token" in result:
            self._access_token = result["access_token"]
            self._fetch_profile()
            self._persist_cache()
            return True

        error_desc = result.get("error_description", "Unknown error") if result else "No token response"
        logger.error(f"Failed to acquire Microsoft Graph token: {error_desc}")
        console.print(f"[bold red]Authentication error:[/bold red] {error_desc}")
        return False

    def _fetch_profile(self) -> None:
        if not self._access_token:
            return
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            res = requests.get(f"{GRAPH_ENDPOINT}/me", headers=headers, timeout=10)
            if res.status_code == 200:
                profile = res.json()
                self._account_email = profile.get("mail") or profile.get("userPrincipalName")
        except Exception as e:
            logger.warning(f"Failed to fetch Microsoft user profile: {e}")

    def fetch_messages_since(self, since: datetime) -> list[EmailMessage]:
        """Fetch emails from Microsoft Graph received on or after since timestamp."""
        if not self._access_token:
            if not self.authenticate(interactive=False):
                logger.error("Outlook provider not authenticated.")
                return []

        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        headers = {"Authorization": f"Bearer {self._access_token}"}
        url = (
            f"{GRAPH_ENDPOINT}/me/messages"
            f"?$filter=receivedDateTime ge {since_iso}"
            f"&$select=id,conversationId,subject,from,receivedDateTime,body,bodyPreview"
            f"&$top=100"
        )

        results: list[EmailMessage] = []
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code != 200:
                logger.error(f"Microsoft Graph API error {res.status_code}: {res.text}")
                return []

            data = res.json()
            messages = data.get("value", [])

            for msg in messages:
                from_obj = msg.get("from", {}).get("emailAddress", {})
                sender_email = from_obj.get("address", "").lower()
                sender_name = from_obj.get("name")

                recv_str = msg.get("receivedDateTime")
                try:
                    received_at = (
                        datetime.fromisoformat(recv_str.replace("Z", "+00:00"))
                        if recv_str
                        else datetime.now(timezone.utc)
                    )
                except Exception:
                    received_at = datetime.now(timezone.utc)

                body_obj = msg.get("body", {})
                content_type = body_obj.get("contentType", "text").lower()
                content = body_obj.get("content", "")

                if content_type == "html":
                    body_text = clean_html_to_text(content)
                else:
                    body_text = content.strip()

                snippet = msg.get("bodyPreview", "")

                results.append(
                    EmailMessage(
                        account_id=self._account_email or "outlook-account",
                        message_id=msg["id"],
                        thread_id=msg.get("conversationId", msg["id"]),
                        provider=IngestionProvider.OUTLOOK,
                        sender_name=sender_name or None,
                        sender_email=sender_email,
                        subject=msg.get("subject", "(No Subject)"),
                        received_at=received_at,
                        body_text=body_text or snippet,
                        body_snippet=snippet,
                    )
                )

        except Exception as e:
            logger.error(f"Error querying Microsoft Graph messages: {e}")

        return results
