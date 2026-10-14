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


def test_export_refuses_to_overwrite_sqlite_database(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    with pytest.raises(ValueError, match="must not be the SQLite database"):
        store.export_jsonl(store.path)
    assert store.count() == 0



def test_checkpoint_round_trip_survives_store_reopen(tmp_path):
    path = tmp_path / "events.sqlite3"
    store = EventStore(path)
    assert store.get_checkpoint("windows.eventlog.system.record_id") is None
    store.set_checkpoint("windows.eventlog.system.record_id", "1234")

    reopened = EventStore(path)
    assert reopened.get_checkpoint("windows.eventlog.system.record_id") == "1234"
    reopened.set_checkpoint("windows.eventlog.system.record_id", "1235")
    assert EventStore(path).get_checkpoint("windows.eventlog.system.record_id") == "1235"


@pytest.mark.parametrize("key", ["", "x" * 129])
def test_checkpoint_rejects_invalid_key(tmp_path, key):
    store = EventStore(tmp_path / "events.sqlite3")
    with pytest.raises(ValueError):
        store.get_checkpoint(key)


def test_checkpoint_rejects_oversized_value(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    with pytest.raises(ValueError):
        store.set_checkpoint("collector", "x" * 4097)


def test_events_since_returns_chronological_bounded_window(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    now = datetime.now(timezone.utc)
    store.append_many([
        event("later", now + timedelta(seconds=2)),
        event("middle", now + timedelta(seconds=1)),
        event("earlier", now),
    ])

    result = store.events_since(now, limit=2)
    assert [item.event_id for item in result] == ["earlier", "middle"]


@pytest.mark.parametrize(
    "since,limit",
    [
        (datetime.now(), 10),
        (datetime.now(timezone.utc), 0),
        (datetime.now(timezone.utc), 10001),
    ],
)
def test_events_since_rejects_invalid_window(since, limit, tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    with pytest.raises(ValueError):
        store.events_since(since, limit=limit)
