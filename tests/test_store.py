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


def test_events_since_orders_mixed_timezone_offsets_by_instant(tmp_path):
    from datetime import timedelta

    store = EventStore(tmp_path / "events.sqlite3")
    # 12:00 UTC is later than 12:00 at UTC+02:00 (10:00 UTC).
    later_utc = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    earlier_plus_two = datetime(
        2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=2))
    )
    store.append_many([
        event("later-utc", later_utc),
        event("earlier-plus-two", earlier_plus_two),
    ])
    result = store.events_since(datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc))
    assert [item.event_id for item in result] == [
        "earlier-plus-two", "later-utc"
    ]


def test_ingest_sequence_is_monotonic_across_pruning_and_late_imports(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    now = datetime.now(timezone.utc)
    store.append_many([event("first", now), event("second", now + timedelta(seconds=1))])
    first_batch = store.events_after_sequence(0, limit=10)
    assert [item.event_id for _, item in first_batch] == ["first", "second"]
    first_watermark = first_batch[-1][0]

    store.prune(keep_latest=0)
    reopened = EventStore(store.path)
    reopened.append(event("late-import", now - timedelta(days=2)))
    next_batch = reopened.events_after_sequence(first_watermark, limit=10)
    assert len(next_batch) == 1
    assert next_batch[0][1].event_id == "late-import"
    assert next_batch[0][0] > first_watermark


def test_state_snapshot_round_trip_and_rebuild_delete(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.save_state_snapshot("aie.environment.v1", 42, '{"coverage":{}}')
    assert store.load_state_snapshot("aie.environment.v1") == (
        1, 42, '{"coverage":{}}'
    )
    store.delete_state_snapshot("aie.environment.v1")
    assert store.load_state_snapshot("aie.environment.v1") is None



def test_oversized_state_snapshot_is_rejected_without_replacing_last_good_copy(tmp_path):
    from aie.store import MAX_STATE_SNAPSHOT_BYTES

    store = EventStore(tmp_path / "events.sqlite3")
    store.save_state_snapshot("aie.environment.v1", 12, '{"stable":true}')
    oversized = "x" * (MAX_STATE_SNAPSHOT_BYTES + 1)
    with pytest.raises(ValueError, match="previous snapshot was left unchanged"):
        store.save_state_snapshot("aie.environment.v1", 99, oversized)
    assert store.load_state_snapshot("aie.environment.v1") == (
        1, 12, '{"stable":true}'
    )
