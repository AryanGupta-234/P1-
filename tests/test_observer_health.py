from aie.observer_health import ObserverHealthTracker


def test_health_tracker_records_success_and_average_latency():
    now = [10.0]
    tracker = ObserverHealthTracker(clock=lambda: now[0])

    tracker.record_sample(
        "windows.user_mode",
        elapsed_seconds=0.010,
        emitted_events=3,
    )
    now[0] += 2.0
    tracker.record_sample(
        "windows.user_mode",
        elapsed_seconds=0.030,
        emitted_events=1,
    )

    snapshot = tracker.snapshot()
    provider = snapshot["providers"]["windows.user_mode"]

    assert snapshot["runtime_seconds"] == 2.0
    assert provider["state"] == "ok"
    assert provider["samples_attempted"] == 2
    assert provider["samples_succeeded"] == 2
    assert provider["events_emitted"] == 4
    assert provider["errors"] == 0
    assert provider["average_latency_ms"] == 20.0


def test_health_tracker_redacts_error_details_and_recovers():
    now = [0.0]
    tracker = ObserverHealthTracker(clock=lambda: now[0])

    tracker.record_sample(
        "windows.uia",
        elapsed_seconds=0.25,
        emitted_events=0,
        error_type="PermissionError",
    )
    tracker.record_event_loss("windows.uia", 2)
    snapshot = tracker.snapshot()
    degraded = snapshot["providers"]["windows.uia"]

    assert degraded["state"] == "degraded"
    assert degraded["errors"] == 1
    assert degraded["consecutive_errors"] == 1
    assert degraded["event_loss"] == 2
    assert degraded["last_error_type"] == "PermissionError"
    assert "private" not in str(degraded).lower()

    now[0] = 1.0
    tracker.record_sample(
        "windows.uia",
        elapsed_seconds=0.05,
        emitted_events=1,
    )
    recovered = tracker.snapshot()["providers"]["windows.uia"]

    assert recovered["state"] == "ok"
    assert recovered["consecutive_errors"] == 0
    assert recovered["last_error_type"] is None


def test_health_event_is_normalized_and_derived():
    tracker = ObserverHealthTracker()
    tracker.record_sample(
        "windows.user_mode",
        elapsed_seconds=0.005,
        emitted_events=1,
    )

    event = tracker.to_event("host-pseudonym")
    assert event.source == "aie.observer"
    assert event.event_type == "observer.health"
    assert event.evidence_kind == "derived"
    assert event.data["providers"]["windows.user_mode"]["events_emitted"] == 1
