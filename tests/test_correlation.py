from datetime import datetime, timezone

import pytest

from aie.contracts import AIEEvent, EntityRef
from aie.correlation import correlate_process_starts
from aie.store import EventStore


def _event(event_id, event_type, timestamp, *, source, entity_name, pid, data):
    return AIEEvent(
        event_id=event_id,
        timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc),
        host_id="host-a",
        source=source,
        event_type=event_type,
        entity=EntityRef(type="process", name=entity_name, stable_id=str(pid)),
        data={"pid": pid, **data},
        evidence_kind="observed",
    )


def _pair(*, pid=42, create_time=1000.0, etw_time=1000.2, image="demo.exe"):
    etw = _event(
        "etw-start-1", "process.started_etw", etw_time,
        source="windows.etw.kernel_process", entity_name=image, pid=pid,
        data={"image_name": image},
    )
    snapshot = _event(
        "snapshot-start-1", "process.started_observed", 1004.0,
        source="windows.user_mode", entity_name=image, pid=pid,
        data={"create_time": create_time},
    )
    return etw, snapshot


def test_process_start_correlation_requires_matching_pid_image_and_create_time():
    etw, snapshot = _pair()
    result = correlate_process_starts([etw, snapshot])

    assert len(result) == 1
    event = result[0]
    assert event.event_type == "process.start_confirmed_by_etw"
    assert event.evidence_kind == "derived"
    assert event.confidence == 0.99
    assert event.data["pid"] == 42
    assert event.data["etw_event_id"] == etw.event_id
    assert event.data["snapshot_event_id"] == snapshot.event_id
    assert event.correlation_id == event.event_id


def test_process_start_correlation_is_deterministic():
    pair = _pair()
    first = correlate_process_starts(pair)
    second = correlate_process_starts(reversed(pair))
    assert [event.event_id for event in first] == [event.event_id for event in second]


def test_process_start_correlation_rejects_pid_reuse_and_wrong_image():
    etw, snapshot = _pair()
    reused_pid = snapshot.model_copy(update={
        "event_id": "snapshot-reused",
        "data": {"pid": 42, "create_time": 900.0},
    })
    wrong_image = snapshot.model_copy(update={
        "event_id": "snapshot-other-image",
        "entity": EntityRef(type="process", name="other.exe", stable_id="42"),
        "data": {"pid": 42, "create_time": 1000.0},
    })
    assert correlate_process_starts([etw, reused_pid, wrong_image]) == []


def test_process_start_correlation_rejects_different_host_and_out_of_window():
    etw, snapshot = _pair()
    other_host = snapshot.model_copy(update={"host_id": "host-b"})
    late = snapshot.model_copy(update={
        "event_id": "snapshot-late",
        "data": {"pid": 42, "create_time": 1010.0},
    })
    assert correlate_process_starts([etw, other_host]) == []
    assert correlate_process_starts([etw, late], tolerance_seconds=2.0) == []


def test_process_stop_events_are_not_correlated_by_pid_only():
    etw, snapshot = _pair()
    stopped = etw.model_copy(update={
        "event_id": "etw-stop",
        "event_type": "process.stopped_etw",
    })
    assert correlate_process_starts([stopped, snapshot]) == []


@pytest.mark.parametrize("tolerance", [-1, float("nan"), float("inf")])
def test_process_start_correlation_rejects_invalid_tolerance(tolerance):
    with pytest.raises(ValueError):
        correlate_process_starts([], tolerance_seconds=tolerance)


def test_correlations_persist_idempotently_from_sqlite_history(tmp_path):
    etw, snapshot = _pair()
    store = EventStore(tmp_path / "events.sqlite3")
    store.append_many([etw, snapshot])

    since = datetime.fromtimestamp(999, tz=timezone.utc)
    derived = correlate_process_starts(store.events_since(since))
    assert len(derived) == 1
    assert store.append_many(derived) == 1
    replayed = correlate_process_starts(store.events_since(since))
    assert store.append_many(replayed) == 0
    assert store.count() == 3
