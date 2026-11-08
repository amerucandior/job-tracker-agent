"""Mail ingestion package."""

from job_tracker_agent.ingestion.base import BaseMailProvider, clean_html_to_text
from job_tracker_agent.ingestion.gmail import GmailProvider
from job_tracker_agent.ingestion.outlook import OutlookProvider

__all__ = ["BaseMailProvider", "GmailProvider", "OutlookProvider", "clean_html_to_text"]
