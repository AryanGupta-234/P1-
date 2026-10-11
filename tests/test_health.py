from datetime import datetime, timezone

from aie.contracts import AIEEvent, EntityRef
from aie.health import ObserverHealthTracker


def sample_event(event_type="test.snapshot", data=None):
    return AIEEvent(
        timestamp=datetime.now(timezone.utc),
        host_id="host-test",
        source="test.provider",
        event_type=event_type,
        entity=EntityRef(type="test", name="sample"),
        data=data or {},
    )


def test_health_tracker_records_healthy_degraded_and_recovery_transitions():
    clock = [0.0]
    tracker = ObserverHealthTracker(
        host_id="host-test",
        monotonic=lambda: clock[0],
    )

    healthy = tracker.collect("windows.test", lambda: [sample_event()])
    assert healthy[-1].event_type == "observer.provider_health"
    assert healthy[-1].data["status"] == "healthy"

    clock[0] += 0.025
    degraded = tracker.collect(
        "windows.test",
        lambda: [sample_event(
            "windows.test.provider_error",
            {"error_type": "PermissionError"},
        )],
    )
    assert degraded[-1].event_type == "observer.provider_health"
    assert degraded[-1].data["status"] == "degraded"
    assert degraded[-1].data["consecutive_failures"] == 1

    recovered = tracker.collect("windows.test", lambda: [])
    assert recovered[-1].data["status"] == "healthy"
    assert recovered[-1].data["consecutive_failures"] == 0

    summary = tracker.summary_events()
    assert len(summary) == 1
    assert summary[0].event_type == "observer.provider_health_summary"
    assert summary[0].data["collections"] == 3
    assert summary[0].data["failures"] == 1


def test_health_tracker_never_persists_exception_messages_or_tracebacks():
    tracker = ObserverHealthTracker(host_id="host-test")

    def fail():
        raise PermissionError("SECRET PATH AND USER DATA")

    events = tracker.collect("windows.test", fail)
    rendered = " ".join(event.model_dump_json() for event in events)

    assert "PermissionError" in rendered
    assert "SECRET PATH AND USER DATA" not in rendered
    assert "traceback" not in rendered.lower()


def test_health_tracker_counts_event_log_loss_and_unknown_reset():
    tracker = ObserverHealthTracker(host_id="host-test")
    events = tracker.collect(
        "windows.eventlog",
        lambda: [
            sample_event(
                "windows.eventlog.records_lost",
                {"dropped_records": 7},
            ),
            sample_event("windows.eventlog.sequence_reset"),
        ],
    )

    health = events[-1]
    assert health.data["status"] == "degraded"
    assert health.data["dropped_records"] == 7
    assert health.data["unknown_loss_incidents"] == 1


def test_health_tracker_does_not_emit_duplicate_state_transitions():
    tracker = ObserverHealthTracker(host_id="host-test")

    first = tracker.collect("windows.test", lambda: [])
    second = tracker.collect("windows.test", lambda: [])
    assert sum(e.event_type == "observer.provider_health" for e in first) == 1
    assert sum(e.event_type == "observer.provider_health" for e in second) == 0
