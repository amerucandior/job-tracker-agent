"""Gmail ingestion provider using Google OAuth2 and Gmail REST API."""

import base64
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
import logging
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from job_tracker_agent.config import get_config_dir, load_tokens, save_tokens
from job_tracker_agent.ingestion.base import BaseMailProvider, clean_html_to_text
from job_tracker_agent.models import EmailMessage, IngestionProvider

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailProvider(BaseMailProvider):
    """Ingests job application emails from a Gmail account."""

    def __init__(self, client_secret_path: Optional[Path] = None) -> None:
        self.client_secret_path = (
            client_secret_path or get_config_dir() / "gmail_client_secret.json"
        )
        self._credentials: Optional[Credentials] = None
        self._service: Optional[Any] = None
        self._account_email: Optional[str] = None

    @property
    def provider_name(self) -> str:
        return "gmail"

    def authenticate(self, interactive: bool = True) -> bool:
        """Authenticate with Gmail using stored tokens or interactive browser flow."""
        tokens = load_tokens()
        gmail_token_data = tokens.get("gmail")

        if gmail_token_data:
            try:
                self._credentials = Credentials.from_authorized_user_info(
                    gmail_token_data, GMAIL_SCOPES
                )
            except Exception as e:
                logger.warning(f"Failed to load stored Gmail credentials: {e}")
                self._credentials = None

        if self._credentials and self._credentials.expired and self._credentials.refresh_token:
            try:
                self._credentials.refresh(Request())
                tokens["gmail"] = self._creds_to_dict(self._credentials)
                save_tokens(tokens)
            except Exception as e:
                logger.warning(f"Failed to refresh Gmail credentials: {e}")
                self._credentials = None

        if (not self._credentials or not self._credentials.valid) and interactive:
            if not self.client_secret_path.exists():
                raise FileNotFoundError(
                    f"Gmail client secret file not found at {self.client_secret_path}. "
                    f"Please place your Google Cloud OAuth 2.0 client secret JSON file there."
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.client_secret_path), GMAIL_SCOPES
            )
            try:
                self._credentials = flow.run_local_server(port=8080, prompt="consent")
            except Exception as e:
                logger.warning(f"Localhost loopback server failed ({e}), falling back to console.")
                # Fallback to copy-paste redirect flow
                flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
                auth_url, _ = flow.authorization_url(prompt="consent")
                print(f"\nPlease visit this URL to authorize Gmail:\n{auth_url}\n")
                code = input("Enter the authorization code: ").strip()
                flow.fetch_token(code=code)
                self._credentials = flow.credentials

            tokens["gmail"] = self._creds_to_dict(self._credentials)
            save_tokens(tokens)

        if self._credentials and self._credentials.valid:
            self._service = build("gmail", "v1", credentials=self._credentials)
            profile = self._service.users().getProfile(userId="me").execute()
            self._account_email = profile.get("emailAddress", "unknown@gmail.com")
            return True

        return False

    def _creds_to_dict(self, creds: Credentials) -> dict[str, Any]:
        return {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }

    def fetch_messages_since(self, since: datetime) -> list[EmailMessage]:
        """Fetch emails from Gmail received on or after since timestamp."""
        if not self._service:
            if not self.authenticate(interactive=False):
                logger.error("Gmail service not authenticated.")
                return []

        epoch_seconds = int(since.timestamp())
        query = f"after:{epoch_seconds}"
        results: list[EmailMessage] = []

        try:
            response = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, maxResults=100)
                .execute()
            )
            messages = response.get("messages", [])

            for msg_meta in messages:
                msg_id = msg_meta["id"]
                full_msg = (
                    self._service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="full")
                    .execute()
                )
                parsed = self._parse_gmail_message(full_msg)
                if parsed:
                    results.append(parsed)

        except Exception as e:
            logger.error(f"Error fetching Gmail messages: {e}")

        return results

    def _parse_gmail_message(self, message_data: dict[str, Any]) -> Optional[EmailMessage]:
        payload = message_data.get("payload", {})
        headers_list = payload.get("headers", [])
        headers = {h["name"].lower(): h["value"] for h in headers_list}

        subject = headers.get("subject", "(No Subject)")
        from_header = headers.get("from", "")
        sender_name, sender_email = parseaddr(from_header)

        date_header = headers.get("date")
        if date_header:
            try:
                received_at = parsedate_to_datetime(date_header)
            except Exception:
                received_at = datetime.now(timezone.utc)
        else:
            internal_date_ms = int(message_data.get("internalDate", 0))
            received_at = (
                datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc)
                if internal_date_ms
                else datetime.now(timezone.utc)
            )

        body_text = self._extract_body(payload)
        snippet = message_data.get("snippet", "")

        return EmailMessage(
            account_id=self._account_email or "gmail-account",
            message_id=message_data["id"],
            thread_id=message_data.get("threadId", message_data["id"]),
            provider=IngestionProvider.GMAIL,
            sender_name=sender_name or None,
            sender_email=sender_email.lower(),
            subject=subject,
            received_at=received_at,
            body_text=body_text or snippet,
            body_snippet=snippet,
        )

    def _extract_body(self, payload: dict[str, Any]) -> str:
        """Recursively extract plain text or sanitized HTML body from MIME parts."""
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data")

        if mime_type == "text/plain" and body_data:
            try:
                return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
            except Exception:
                pass

        if mime_type == "text/html" and body_data:
            try:
                raw_html = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
                return clean_html_to_text(raw_html)
            except Exception:
                pass

        parts = payload.get("parts", [])
        text_parts: list[str] = []
        for part in parts:
            extracted = self._extract_body(part)
            if extracted:
                text_parts.append(extracted)

        return "\n\n".join(text_parts).strip()
