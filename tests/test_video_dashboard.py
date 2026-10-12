from datetime import datetime, timezone
import json

from aie.contracts import AIEEvent, EntityRef
from aie.diagnostics.video_dashboard import build_video_dashboard_snapshot
from aie.store import EventStore


def _event(event_id: str, event_type: str, data: dict, *, source: str = "test") -> AIEEvent:
    return AIEEvent(
        event_id=event_id,
        timestamp=datetime.now(timezone.utc),
        host_id="dashboard-test-host",
        source=source,
        event_type=event_type,
        entity=EntityRef(type="test", name=event_id),
        data=data,
        sensitivity="internal",
        confidence=1.0,
        evidence_kind="observed",
    )


def test_video_dashboard_includes_playback_diagnostics_and_model_inventory(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.append(_event(
        "playback-1",
        "browser.video.snapshot",
        {
            "playback_state": "waiting",
            "stall_count": 3,
            "observation_window_seconds": 60,
            "buffered_ahead_seconds": 0.4,
            "playback_progress_delta_seconds": 0.0,
            "dropped_frames_pct": 2.0,
        },
        source="browser.extension",
    ))
    store.append(_event(
        "finding-1",
        "diagnostic.video_finding",
        {
            "cause": "stream_buffer_starvation",
            "severity": "medium",
            "confidence": 0.72,
            "recommendation": "Compare sustained throughput and DNS/connectivity.",
            "evidence": ["Buffered media ahead: 0.40 seconds"],
            "evidence_event_ids": ["playback-1"],
            "action_executed": False,
        },
        source="aie.diagnostics.video",
    ))
    store.append(_event(
        "probe-1",
        "network.video_probe",
        {
            "packet_loss_by_target": [
                {"label": "gateway", "packets_sent": 4, "packets_received": 3, "packet_loss_pct": 25.0}
            ],
            "throughput_mbps": 12.5,
            "throughput_samples_completed": 2,
            "action_executed": False,
        },
        source="aie.video.network_probe",
    ))

    snapshot = build_video_dashboard_snapshot(store, lookback_hours=24, event_limit=100)

    assert snapshot["schema_version"] == 1
    assert snapshot["overview"]["playback_snapshots"] == 1
    assert snapshot["overview"]["diagnostic_findings"] == 1
    assert snapshot["live_context"]["playback_state"] == "waiting"
    assert snapshot["live_context"]["buffered_ahead_seconds"] == 0.4
    assert snapshot["findings"][0]["cause"] == "stream_buffer_starvation"
    assert snapshot["probes"][0]["packet_loss_by_target"][0]["label"] == "gateway"
    assert "installed" in snapshot["models"]


def test_video_dashboard_never_exposes_window_title_or_raw_browser_url(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.append(_event(
        "playback-private",
        "browser.video.snapshot",
        {
            "playback_state": "playing",
            "stall_count": 0,
            "observation_window_seconds": 30,
            "url": "https://private.example/watch",
            "page_text": "private page contents",
        },
    ))
    store.append(_event(
        "foreground-private",
        "window.foreground_changed",
        {
            "process_name": "brave.exe",
            "pid": 1234,
            "window_title": "Private browsing title",
            "window_title_collected": False,
        },
    ))

    snapshot = build_video_dashboard_snapshot(store)
    serialized = json.dumps(snapshot)

    assert "private.example" not in serialized
    assert "private page contents" not in serialized
    assert "Private browsing title" not in serialized


def test_video_dashboard_validates_bounds_and_timezone(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    try:
        build_video_dashboard_snapshot(store, lookback_hours=0)
    except ValueError as exc:
        assert "lookback_hours" in str(exc)
    else:
        raise AssertionError("invalid lookback must be rejected")

    try:
        build_video_dashboard_snapshot(store, now=datetime(2026, 10, 12))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive timestamp must be rejected")
