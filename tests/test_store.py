from datetime import datetime, timedelta, timezone

import pytest

from aie.contracts import AIEEvent, EntityRef
from aie.store import EventStore


def event(event_id="stable-id", timestamp=None):
    return AIEEvent(
        event_id=event_id,
        timestamp=timestamp or datetime.now(timezone.utc),
        host_id="test",
        source="unit",
        event_type="sample",
        entity=EntityRef(type="test", name="sample"),
    )


def test_durable_store_and_deduplication(tmp_path):
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    assert store.append(event()) is True
    assert store.append(event()) is False
    reopened = EventStore(path)
    assert reopened.count() == 1
    assert reopened.recent(1)[0].event_id == "stable-id"


def test_prune_by_age_uses_timezone_aware_cutoff(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    now = datetime.now(timezone.utc)
    store.append_many([
        event("old", now - timedelta(days=10)),
        event("recent", now - timedelta(days=1)),
    ])

    assert store.prune(older_than=now - timedelta(days=5)) == 1
    assert [item.event_id for item in store.recent(10)] == ["recent"]


def test_prune_keep_latest_is_deterministic(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    now = datetime.now(timezone.utc)
    store.append_many([
        event("first", now),
        event("second", now + timedelta(seconds=1)),
        event("third", now + timedelta(seconds=2)),
    ])

    assert store.prune(keep_latest=2) == 1
    assert {item.event_id for item in store.recent(10)} == {"second", "third"}
    assert store.prune(keep_latest=0) == 2
    assert store.count() == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"older_than": datetime.now()},
        {"older_than": datetime.now(timezone.utc), "keep_latest": 1},
        {"keep_latest": -1},
    ],
)
def test_prune_rejects_ambiguous_or_invalid_policy(tmp_path, kwargs):
    store = EventStore(tmp_path / "events.sqlite3")
    with pytest.raises(ValueError):
        store.prune(**kwargs)


def test_export_jsonl_writes_all_events_in_chronological_order(tmp_path):
    import json

    store = EventStore(tmp_path / "events.sqlite3")
    now = datetime.now(timezone.utc)
    store.append_many([
        event("later", now + timedelta(seconds=1)),
        event("earlier", now),
    ])
    destination = tmp_path / "exports" / "events.jsonl"

    assert store.export_jsonl(destination) == 2
    rows = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
    assert [row["event_id"] for row in rows] == ["earlier", "later"]
