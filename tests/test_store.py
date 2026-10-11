from datetime import datetime, timedelta, timezone

import pytest

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




def query_event(event_id, seconds_ago, event_type, source):
    return AIEEvent(
        event_id=event_id,
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=seconds_ago),
        host_id="test",
        source=source,
        event_type=event_type,
        entity=EntityRef(type="test", name=event_id),
    )


def test_query_events_filters_by_time_type_and_source(tmp_path):
    store = EventStore(tmp_path / "query.sqlite3")
    store.append_many([
        query_event("browser-old", 3600, "browser.video.snapshot", "browser.extension"),
        query_event("browser-new", 10, "browser.video.snapshot", "browser.extension"),
        query_event("net-new", 5, "network.external_probe", "windows.network"),
    ])

    results = store.query_events(
        since=datetime.now(timezone.utc) - timedelta(minutes=5),
        event_types=("browser.video.snapshot", "network.external_probe"),
        sources=("browser.extension",),
        limit=10,
    )

    assert [item.event_id for item in results] == ["browser-new"]


def test_query_events_rejects_naive_or_inverted_time_windows(tmp_path):
    store = EventStore(tmp_path / "query-validation.sqlite3")
    naive = datetime(2026, 10, 11, 12, 0)
    aware = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="timezone-aware"):
        store.query_events(since=naive)
    with pytest.raises(ValueError, match="not be later"):
        store.query_events(since=aware, until=aware - timedelta(seconds=1))
    with pytest.raises(ValueError, match="limit"):
        store.query_events(limit=0)


def test_export_jsonl_excludes_sensitive_by_default(tmp_path):
    from aie.contracts import AIEEvent, EntityRef

    store = EventStore(tmp_path / "events.sqlite3")
    store.append_many([
        AIEEvent(
            event_id="normal-export",
            host_id="test",
            source="unit",
            event_type="sample",
            entity=EntityRef(type="test", name="normal"),
            data={"value": 1},
        ),
        AIEEvent(
            event_id="sensitive-export",
            host_id="test",
            source="unit",
            event_type="sensitive",
            entity=EntityRef(type="test", name="private"),
            data={"value": "private"},
            sensitivity="sensitive",
        ),
    ])

    destination = tmp_path / "export.jsonl"
    assert store.export_jsonl(destination) == 1
    exported = destination.read_text(encoding="utf-8")
    assert "normal-export" in exported
    assert "sensitive-export" not in exported

    assert store.export_jsonl(destination, include_sensitive=True) == 2
    assert "sensitive-export" in destination.read_text(encoding="utf-8")


def test_export_rejects_database_overwrite(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    with pytest.raises(ValueError, match="must not overwrite"):
        store.export_jsonl(store.path)


def test_delete_all_removes_every_event(tmp_path):
    store = EventStore(tmp_path / "delete-all.sqlite3")
    store.append_many([event(), AIEEvent(
        event_id="second",
        host_id="test",
        source="unit",
        event_type="sample",
        entity=EntityRef(type="test", name="second"),
    )])
    assert store.delete_all() == 2
    assert store.count() == 0
