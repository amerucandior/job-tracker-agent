from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest
from job_tracker_agent.models import ApplicationStage, EmailMessage, ExtractedApplication, IngestionProvider
from job_tracker_agent.notion.sync import NotionSyncReconciler
from job_tracker_agent.storage.checkpoint import CheckpointStore


def test_build_timeline_toggle_block(tmp_path):
    store = CheckpointStore(db_path=tmp_path / "sync.db")
    reconciler = NotionSyncReconciler(
        api_key="mock_secret",
        database_id="mock_db_id",
        checkpoint_store=store,
    )

    msg = EmailMessage(
        account_id="test@test.com",
        message_id="msg-1",
        thread_id="thread-abc",
        provider=IngestionProvider.GMAIL,
        sender_email="recruiter@figma.com",
        sender_name="Figma Recruiting",
        subject="Invitation to Figma interview",
        received_at=datetime(2026, 11, 8, 14, 30, tzinfo=timezone.utc),
        body_text="Hi! We want to interview you.",
    )

    extracted = ExtractedApplication(
        is_job_application=True,
        company="Figma",
        role="Product Designer",
        stage=ApplicationStage.INTERVIEW,
        confidence=0.98,
        review_flag=False,
        summary="Invitation to interview for Product Designer.",
        action_items=["Select time slot on Calendly"],
    )

    block = reconciler._build_timeline_toggle_block(extracted, msg, prev_stage="Screening")
    assert block["object"] == "block"
    assert block["type"] == "toggle"
    title = block["toggle"]["rich_text"][0]["text"]["content"]
    assert "Screening ➔ Interview" in title
    assert "Invitation to Figma interview" in title

    children = block["toggle"]["children"]
    assert len(children) >= 3
    # Check action items are included
    action_items = [c for c in children if c["type"] == "bulleted_list_item"]
    assert len(action_items) == 1
    assert action_items[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "Select time slot on Calendly"


def test_find_existing_page_with_data_source(tmp_path):
    store = CheckpointStore(db_path=tmp_path / "sync.db")
    reconciler = NotionSyncReconciler(
        api_key="mock_secret",
        database_id="mock_db_id",
        checkpoint_store=store,
    )
    reconciler.client = MagicMock()
    reconciler.client.data_sources.query.return_value = {
        "results": [
            {
                "id": "page-123",
                "properties": {
                    "Stage": {"select": {"name": "Screening"}},
                    "Role": {"rich_text": [{"plain_text": "Software Engineer"}]},
                },
            }
        ]
    }
    page_id, stage = reconciler._find_existing_page("thread-xyz", "Acme", "Software Engineer")
    assert page_id == "page-123"
    assert stage == "Screening"

