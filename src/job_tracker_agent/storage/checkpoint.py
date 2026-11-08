"""SQLite checkpoint ledger for tracking processed emails and thread-to-application mappings.

Adheres to docs/adr/0001-local-sqlite-checkpointing.md.
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Optional
from job_tracker_agent.config import get_database_path


class CheckpointStore:
    """Manages local SQLite state for email sync watermarks and processed message IDs."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or get_database_path()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_accounts (
                    account_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    email_address TEXT,
                    last_sync_time TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_messages (
                    account_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    thread_id TEXT,
                    received_at TEXT,
                    processed_at TEXT NOT NULL,
                    stage TEXT,
                    review_flag INTEGER DEFAULT 0,
                    company TEXT,
                    role TEXT,
                    PRIMARY KEY (account_id, message_id)
                );
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_application_map (
                    thread_id TEXT PRIMARY KEY,
                    notion_page_id TEXT NOT NULL,
                    company TEXT NOT NULL,
                    role TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def is_processed(self, account_id: str, message_id: str) -> bool:
        """Check if an email message ID has already been processed."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM processed_messages WHERE account_id = ? AND message_id = ?",
                (account_id, message_id),
            )
            return cursor.fetchone() is not None

    def record_processed(
        self,
        account_id: str,
        message_id: str,
        thread_id: Optional[str] = None,
        received_at: Optional[datetime] = None,
        stage: Optional[str] = None,
        review_flag: bool = False,
        company: Optional[str] = None,
        role: Optional[str] = None,
    ) -> None:
        """Record a processed message into the ledger."""
        now_str = datetime.now(timezone.utc).isoformat()
        recv_str = received_at.isoformat() if received_at else None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO processed_messages (
                    account_id, message_id, thread_id, received_at,
                    processed_at, stage, review_flag, company, role
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    message_id,
                    thread_id,
                    recv_str,
                    now_str,
                    stage,
                    1 if review_flag else 0,
                    company,
                    role,
                ),
            )
            conn.commit()

    def get_last_sync_time(self, account_id: str) -> Optional[datetime]:
        """Retrieve the last sync timestamp watermark for an account."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_sync_time FROM ingestion_accounts WHERE account_id = ?",
                (account_id,),
            )
            row = cursor.fetchone()
            if row and row["last_sync_time"]:
                return datetime.fromisoformat(row["last_sync_time"])
            return None

    def update_last_sync_time(
        self,
        account_id: str,
        timestamp: datetime,
        provider: str = "gmail",
        email_address: Optional[str] = None,
    ) -> None:
        """Update or insert the sync watermark for an ingestion account."""
        now_str = datetime.now(timezone.utc).isoformat()
        ts_str = timestamp.isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ingestion_accounts (account_id, provider, email_address, last_sync_time, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    last_sync_time = excluded.last_sync_time,
                    email_address = COALESCE(excluded.email_address, ingestion_accounts.email_address)
                """,
                (account_id, provider, email_address, ts_str, now_str),
            )
            conn.commit()

    def get_notion_page_for_thread(self, thread_id: str) -> Optional[dict[str, str]]:
        """Look up existing Notion page ID and metadata mapped to an email thread ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT notion_page_id, company, role FROM thread_application_map WHERE thread_id = ?",
                (thread_id,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "notion_page_id": row["notion_page_id"],
                    "company": row["company"],
                    "role": row["role"],
                }
            return None

    def map_thread_to_notion_page(
        self, thread_id: str, notion_page_id: str, company: str, role: str
    ) -> None:
        """Associate an email thread ID with a Notion application page."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO thread_application_map (
                    thread_id, notion_page_id, company, role, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (thread_id, notion_page_id, company, role, now_str),
            )
            conn.commit()
