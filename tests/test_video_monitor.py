from datetime import datetime, timezone

from aie.context.video import build_video_observation_context
from aie.contracts import AIEEvent, EntityRef
from aie.diagnostics.monitor import VideoDiagnosticMonitor
from aie.store import EventStore


def test_independent_browser_hosts_share_persisted_diagnostic_cooldown(tmp_path):
    now = datetime.now(timezone.utc)
    store = EventStore(tmp_path / "events.sqlite3")
    store.append(AIEEvent(
        event_id="playback-shared-1",
        timestamp=now,
        host_id="shared-host",
        source="browser.extension",
        event_type="browser.video.snapshot",
        entity=EntityRef(type="browser_video", name="video_playback"),
        data={
            "playback_state": "waiting",
            "stall_count": 3,
            "observation_window_seconds": 60,
            "buffered_ahead_seconds": 0.25,
            "playback_progress_delta_seconds": 0.0,
        },
        sensitivity="internal",
        confidence=1.0,
        evidence_kind="observed",
    ))

    first_host = VideoDiagnosticMonitor(store, clock=lambda: now)
    second_host = VideoDiagnosticMonitor(store, clock=lambda: now)

    first_findings = first_host.poll()
    assert len(first_findings) == 1
    assert store.append_many(first_findings) == 1

    # This simulates another browser's independent native-host process. It refreshes
    # the persisted cooldown before evaluating the same active incident.
    assert second_host.poll() == []
    assert store.count() == 2
