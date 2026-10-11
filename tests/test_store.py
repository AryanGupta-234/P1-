from aie.contracts import AIEEvent, EntityRef
from aie.store import EventStore


def event():
    return AIEEvent(event_id="stable-id", host_id="test", source="unit",
                    event_type="sample", entity=EntityRef(type="test", name="sample"))


def test_durable_store_and_deduplication(tmp_path):
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    assert store.append(event()) is True
    assert store.append(event()) is False
    reopened = EventStore(path)
    assert reopened.count() == 1
    assert reopened.recent(1)[0].event_id == "stable-id"


def test_retention_count_and_prune_only_delete_older_records(tmp_path):
    from datetime import datetime, timedelta, timezone

    old_event = AIEEvent(
        event_id="old-event",
        timestamp=datetime.now(timezone.utc) - timedelta(days=40),
        host_id="test",
        source="unit",
        event_type="old",
        entity=EntityRef(type="test", name="old"),
    )
    recent_event = AIEEvent(
        event_id="recent-event",
        timestamp=datetime.now(timezone.utc) - timedelta(days=2),
        host_id="test",
        source="unit",
        event_type="recent",
        entity=EntityRef(type="test", name="recent"),
    )
    store = EventStore(tmp_path / "retention.sqlite3")
    store.append_many([old_event, recent_event])
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    assert store.count_before(cutoff) == 1
    assert store.delete_before(cutoff) == 1
    assert store.count() == 1
    assert store.recent(1)[0].event_id == "recent-event"


def test_retention_rejects_naive_cutoff(tmp_path):
    from datetime import datetime

    import pytest

    store = EventStore(tmp_path / "retention.sqlite3")
    with pytest.raises(ValueError):
        store.count_before(datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        store.delete_before(datetime(2026, 1, 1))
