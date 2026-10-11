from datetime import datetime, timedelta, timezone

from aie.contracts import AIEEvent, EntityRef
from aie.context.activity import build_activity_timeline


def make_event(event_id, seconds_ago, event_type, *, host="host-a", sensitivity="internal", data=None, entity_name="entity"):
    return AIEEvent(
        event_id=event_id,
        timestamp=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc) - timedelta(seconds=seconds_ago),
        host_id=host,
        source="test",
        event_type=event_type,
        entity=EntityRef(type="test", name=entity_name),
        sensitivity=sensitivity,
        data=data or {},
    )


def test_activity_groups_related_cross_provider_observations():
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    events = [
        make_event("foreground", 25, "window.foreground_changed",
                   data={"process_name": "msedge.exe", "window_title": "private title"}),
        make_event("video", 20, "browser.video.snapshot",
                   data={"playback_state": "stalled", "stall_count": 3, "buffered_ahead_seconds": 0.2}),
        make_event("network", 10, "network.external_probe",
                   data={"connect_latency_ms": 72.0}),
        make_event("eventlog", 5, "windows.eventlog.record",
                   data={"channel": "System", "event_id": 1001, "message": "secret"}),
        make_event("diagnostic", 1, "diagnostic.video_finding",
                   data={"cause": "stream_buffer_starvation", "severity": "medium", "recommendation": "private text"}),
    ]

    timeline = build_activity_timeline(events, now=now)

    assert timeline.event_count == 5
    assert len(timeline.sessions) == 1
    session = timeline.sessions[0]
    assert set(session.kinds) == {"application", "browser", "network", "system", "diagnostic"}
    assert session.applications == ("msedge.exe",)
    rendered = " ".join(signal.title for signal in session.signals)
    assert "msedge.exe" in rendered
    assert "stalled" in rendered
    assert "72.0 ms" in rendered
    assert "private" not in rendered
    assert "secret" not in rendered


def test_activity_sessions_split_by_host_and_time_gap():
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    events = [
        make_event("a1", 600, "window.foreground_changed", host="host-a"),
        make_event("a2", 590, "network.external_probe", host="host-a"),
        make_event("a3", 30, "browser.video.snapshot", host="host-a"),
        make_event("b1", 20, "window.foreground_changed", host="host-b"),
    ]

    timeline = build_activity_timeline(
        events,
        now=now,
        session_gap_seconds=120,
    )

    assert len(timeline.sessions) == 3
    assert {session.host_id for session in timeline.sessions} == {"host-a", "host-b"}
    assert timeline.current_session_id is not None
    assert timeline.sessions[0].event_count == 1


def test_activity_ignores_stale_future_naive_and_sensitive_events_by_default():
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    stale = make_event("stale", 10_000, "host.snapshot")
    future = AIEEvent(
        event_id="future",
        timestamp=now + timedelta(seconds=10),
        host_id="host-a",
        source="test",
        event_type="host.snapshot",
        entity=EntityRef(type="test", name="future"),
    )
    sensitive = make_event(
        "sensitive", 5, "window.foreground_changed",
        sensitivity="sensitive",
        data={"process_name": "password-manager.exe", "window_title": "secret"},
    )
    timeline = build_activity_timeline([stale, future, sensitive], now=now)

    assert timeline.event_count == 0
    included = build_activity_timeline(
        [sensitive],
        now=now,
        include_sensitive=True,
    )
    assert included.event_count == 1
    assert "secret" not in included.sessions[0].signals[0].title


def test_activity_deduplicates_event_ids_and_bounds_signals():
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    first = make_event("same", 3, "host.snapshot")
    second = make_event("same", 2, "host.snapshot")

    timeline = build_activity_timeline(
        [first, second],
        now=now,
        max_signals_per_session=1,
    )

    assert timeline.event_count == 1
    assert timeline.sessions[0].event_count == 1
    assert len(timeline.sessions[0].signals) == 1


def test_activity_rejects_naive_clock_and_invalid_budgets():
    import pytest

    with pytest.raises(ValueError):
        build_activity_timeline([], now=datetime(2026, 10, 11, 12, 0))
    with pytest.raises(ValueError):
        build_activity_timeline([], max_age_seconds=0)
    with pytest.raises(ValueError):
        build_activity_timeline([], session_gap_seconds=1)
