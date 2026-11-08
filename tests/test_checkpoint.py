from datetime import datetime, timezone
import pytest
from job_tracker_agent.storage.checkpoint import CheckpointStore


def test_checkpoint_store_lifecycle(tmp_path):
    db_file = tmp_path / "test_sync.db"
    store = CheckpointStore(db_path=db_file)

    # 1. Check account last sync time
    assert store.get_last_sync_time("user@gmail.com") is None

    sync_time = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    store.update_last_sync_time("user@gmail.com", sync_time, provider="gmail")
    retrieved = store.get_last_sync_time("user@gmail.com")
    assert retrieved == sync_time

    # 2. Check message processed state
    assert not store.is_processed("user@gmail.com", "msg-123")
    store.record_processed(
        account_id="user@gmail.com",
        message_id="msg-123",
        thread_id="thread-456",
        received_at=sync_time,
        stage="Applied",
        review_flag=False,
        company="Acme Corp",
        role="Backend Engineer",
    )
    assert store.is_processed("user@gmail.com", "msg-123")

    # 3. Thread mapping
    assert store.get_notion_page_for_thread("thread-456") is None
    store.map_thread_to_notion_page(
        thread_id="thread-456",
        notion_page_id="notion-page-abc",
        company="Acme Corp",
        role="Backend Engineer",
    )
    mapping = store.get_notion_page_for_thread("thread-456")
    assert mapping is not None
    assert mapping["notion_page_id"] == "notion-page-abc"
    assert mapping["company"] == "Acme Corp"
