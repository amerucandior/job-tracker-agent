"""Outlook / Microsoft 365 ingestion provider using MSAL and Microsoft Graph API."""

from datetime import datetime, timezone
import logging
from typing import Any, Optional
import msal
import requests

from job_tracker_agent.config import load_tokens, save_tokens
from job_tracker_agent.ingestion.base import BaseMailProvider, clean_html_to_text
from job_tracker_agent.models import EmailMessage, IngestionProvider

logger = logging.getLogger(__name__)

# Default Microsoft Graph scopes for reading user email and profile
OUTLOOK_SCOPES = ["Mail.Read", "User.Read"]

# Default public client ID for personal desktop app integration or custom Azure AD app
DEFAULT_MICROSOFT_CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"  # Standard Microsoft Office app client or user custom
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"


class OutlookProvider(BaseMailProvider):
    """Ingests job application emails from an Outlook / Microsoft 365 account."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        authority: str = "https://login.microsoftonline.com/common",
    ) -> None:
        self.client_id = client_id or DEFAULT_MICROSOFT_CLIENT_ID
        self.authority = authority
        self._access_token: Optional[str] = None
        self._account_email: Optional[str] = None
        self._app = msal.PublicClientApplication(
            self.client_id,
            authority=self.authority,
        )

    @property
    def provider_name(self) -> str:
        return "outlook"

    def authenticate(self, interactive: bool = True) -> bool:
        """Authenticate using stored MSAL cache or interactive browser flow."""
        tokens = load_tokens()
        token_data = tokens.get("outlook", {})
        accounts = self._app.get_accounts()

        # 1. Attempt silent token acquisition
        if accounts:
            result = self._app.acquire_token_silent(OUTLOOK_SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._access_token = result["access_token"]
                self._account_email = accounts[0].get("username")
                return True

        if not interactive:
            return False

        # 2. Interactive acquisition with localhost loopback fallback
        try:
            result = self._app.acquire_token_interactive(
                scopes=OUTLOOK_SCOPES,
                port=8080,
                prompt="select_account",
            )
        except Exception as e:
            logger.warning(f"Interactive browser login on port 8080 failed: {e}. Falling back to device code.")
            flow = self._app.initiate_device_flow(scopes=OUTLOOK_SCOPES)
            if "user_code" not in flow:
                raise RuntimeError("Failed to initiate Microsoft device code authentication flow.")
            print(f"\n{flow.get('message', 'Please visit https://microsoft.com/devicelogin and enter the code.')}\n")
            result = self._app.acquire_token_by_device_flow(flow)

        if result and "access_token" in result:
            self._access_token = result["access_token"]
            tokens["outlook"] = {
                "token_type": result.get("token_type"),
                "scope": result.get("scope"),
                "expires_in": result.get("expires_in"),
            }
            save_tokens(tokens)

            # Retrieve user email profile
            self._fetch_profile()
            return True

        error_desc = result.get("error_description", "Unknown error")
        logger.error(f"Failed to acquire Microsoft Graph token: {error_desc}")
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
