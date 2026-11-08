"""Provisioner for creating the standardized Notion Job Applications database."""

import logging
import re
from typing import Any, Optional
from notion_client import Client

logger = logging.getLogger(__name__)


def normalize_notion_id(raw_input: str) -> str:
    """Normalize a Notion page ID, database ID, or URL into standard 32-char hex string."""
    cleaned = raw_input.split("?")[0].rstrip("/")
    if "/" in cleaned:
        cleaned = cleaned.split("/")[-1]
    cleaned = cleaned.replace("-", "")
    match = re.search(r"([a-f0-9]{32})$", cleaned, re.IGNORECASE)
    if match:
        return match.group(1)
    return cleaned


class NotionProvisioner:
    """Provisions a standardized Notion database for job tracking."""

    def __init__(self, api_key: str) -> None:
        self.client = Client(auth=api_key)

    def create_database(self, parent_page_id: str, title: str = "Job Applications") -> str:
        """Create a new database with canonical properties under parent_page_id."""
        clean_parent_id = normalize_notion_id(parent_page_id)

        properties: dict[str, Any] = {
            "Company": {
                "title": {}
            },
            "Role": {
                "rich_text": {}
            },
            "Stage": {
                "select": {
                    "options": [
                        {"name": "Applied", "color": "blue"},
                        {"name": "Screening", "color": "yellow"},
                        {"name": "Interview", "color": "purple"},
                        {"name": "Offer", "color": "green"},
                        {"name": "Rejected", "color": "red"},
                        {"name": "Archived", "color": "gray"},
                    ]
                }
            },
            "Review Flag": {
                "checkbox": {}
            },
            "Last Activity": {
                "date": {}
            },
            "Thread IDs": {
                "rich_text": {}
            },
        }

        response = self.client.databases.create(
            parent={"type": "page_id", "page_id": clean_parent_id},
            title=[{"type": "text", "text": {"content": title}}],
            properties=properties,
        )

        db_id = response.get("id")
        logger.info(f"Successfully provisioned Notion database: {db_id}")
        return db_id
