from datetime import datetime, timedelta, timezone

from aie.contracts import AIEEvent, EntityRef
from aie.diagnostics.monitor import VideoDiagnosticMonitor
from aie.store import EventStore


def browser_event(event_id, now, state="stalled", stalls=3, buffer_ahead=0.2):
    return AIEEvent(
        event_id=event_id,
        timestamp=now,
        host_id="test-host",
        source="browser.extension",
        event_type="browser.video.snapshot",
        entity=EntityRef(type="browser_video", name="video_playback"),
        data={
            "playback_state": state,
            "stall_count": stalls,
            "observation_window_seconds": 30,
            "buffered_ahead_seconds": buffer_ahead,
            "playback_progress_delta_seconds": 0.0,
        },
    )


def test_monitor_emits_one_finding_per_active_incident(tmp_path):
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    store = EventStore(tmp_path / "monitor.sqlite3")
    store.append(browser_event("browser-1", now))
    monitor = VideoDiagnosticMonitor(
        store,
        max_age_seconds=45,
        alert_cooldown_seconds=0,
        clock=lambda: now,
    )

    first = monitor.poll()
    assert len(first) == 1
    assert first[0].event_type == "diagnostic.video_finding"
    assert first[0].data["cause"] == "stream_buffer_starvation"
    assert first[0].data["action_executed"] is False
    assert first[0].data["evidence_event_ids"] == ["browser-1"]

    store.append_many(first)
    assert monitor.poll() == []


def test_monitor_resets_incident_after_playback_recovers(tmp_path):
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    current = [now]
    store = EventStore(tmp_path / "recovery.sqlite3")
    store.append(browser_event("browser-stall-1", current[0]))
    monitor = VideoDiagnosticMonitor(
        store,
        max_age_seconds=45,
        alert_cooldown_seconds=0,
        clock=lambda: current[0],
    )

    first = monitor.poll()
    assert len(first) == 1
    store.append_many(first)

    current[0] += timedelta(seconds=2)
    store.append(browser_event("browser-playing", current[0], state="playing", stalls=0))
    assert monitor.poll() == []

    current[0] += timedelta(seconds=2)
    store.append(browser_event("browser-stall-2", current[0]))
    second = monitor.poll()

    assert len(second) == 1
    assert second[0].data["cause"] == "stream_buffer_starvation"
    assert second[0].correlation_id == "browser-stall-2"


def test_monitor_deduplicates_recent_alert_across_restart(tmp_path):
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    store = EventStore(tmp_path / "restart.sqlite3")
    store.append(browser_event("browser-1", now))

    first_monitor = VideoDiagnosticMonitor(
        store,
        alert_cooldown_seconds=120,
        clock=lambda: now,
    )
    alerts = first_monitor.poll()
    assert len(alerts) == 1
    store.append_many(alerts)

    restarted_monitor = VideoDiagnosticMonitor(
        store,
        alert_cooldown_seconds=120,
        clock=lambda: now + timedelta(seconds=5),
    )
    assert restarted_monitor.poll() == []


def test_monitor_ignores_stale_browser_snapshots(tmp_path):
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    store = EventStore(tmp_path / "stale.sqlite3")
    store.append(browser_event("browser-old", now - timedelta(minutes=5)))
    monitor = VideoDiagnosticMonitor(store, clock=lambda: now)

    assert monitor.poll() == []
