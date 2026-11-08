"""Base mail provider contract and utility functions."""

from abc import ABC, abstractmethod
from datetime import datetime
import re
from typing import Optional
from job_tracker_agent.models import EmailMessage


def clean_html_to_text(html_content: str) -> str:
    """Convert raw HTML email body into clean plain text."""
    if not html_content:
        return ""
    # Strip script and style blocks
    cleaned = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", "", html_content, flags=re.IGNORECASE)
    # Replace block tags and br with newlines
    cleaned = re.sub(r"<(p|br|div|tr|li)[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
    # Strip all remaining tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Clean whitespace and HTML entities
    cleaned = re.sub(r"&nbsp;", " ", cleaned)
    cleaned = re.sub(r"&amp;", "&", cleaned)
    cleaned = re.sub(r"&lt;", "<", cleaned)
    cleaned = re.sub(r"&gt;", ">", cleaned)
    cleaned = re.sub(r"&quot;", '"', cleaned)
    cleaned = re.sub(r"&#39;", "'", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned)
    return cleaned.strip()


class BaseMailProvider(ABC):
    """Abstract interface for email ingestion providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g., 'gmail', 'outlook')."""
        pass

    @abstractmethod
    def authenticate(self, interactive: bool = True) -> bool:
        """Authenticate or refresh credentials."""
        pass

    @abstractmethod
    def fetch_messages_since(self, since: datetime) -> list[EmailMessage]:
        """Fetch incoming messages received on or after the specified datetime."""
        pass
