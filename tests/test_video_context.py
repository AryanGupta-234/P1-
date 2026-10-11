from datetime import datetime, timedelta, timezone

from aie.context.video import build_video_observation_context
from aie.contracts import AIEEvent, EntityRef


def make_event(event_type, *, seconds_ago=0, host="host-a", data=None, event_id=None):
    return AIEEvent(
        event_id=event_id or f"{event_type}-{seconds_ago}-{host}",
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=seconds_ago),
        host_id=host,
        source="test",
        event_type=event_type,
        entity=EntityRef(type="test", name=event_type),
        data=data or {},
    )


def test_correlates_fresh_browser_snapshot_and_network_evidence():
    browser = make_event(
        "browser.video.snapshot",
        data={
            "playback_state": "stalled",
            "stall_count": 3,
            "observation_window_seconds": 30,
            "buffered_ahead_seconds": 0.4,
            "playback_progress_delta_seconds": 0.0,
            "cpu_pct": 45,
            "dropped_frames_pct": 1,
        },
        event_id="browser-1",
    )
    network = make_event(
        "network.external_probe",
        seconds_ago=4,
        data={"connect_latency_ms": 85, "host": "example.test"},
        event_id="network-1",
    )
    stale = make_event(
        "network.dns_probe",
        seconds_ago=90,
        data={"resolution_ms": 700, "resolved": True},
        event_id="stale-1",
    )
    other_host = make_event(
        "network.gateway_probe",
        seconds_ago=2,
        host="host-b",
        data={"connect_latency_ms": 10},
        event_id="other-host-1",
    )

    context = build_video_observation_context([browser, network, stale, other_host])

    assert context is not None
    assert context.metrics.playback_stalled is True
    assert context.metrics.stall_count == 3
    assert context.metrics.throughput_mbps is None
    assert context.metrics.packet_loss_pct is None
    assert context.buffered_ahead_seconds == 0.4
    assert context.playback_progress_delta_seconds == 0.0
    assert len(context.network_evidence) == 1
    assert context.network_evidence[0].connect_latency_ms == 85
    assert context.evidence_event_ids == ("browser-1", "network-1")


def test_unknown_browser_metrics_remain_unknown():
    browser = make_event(
        "browser.video.snapshot",
        data={"playback_state": "waiting", "stall_count": 2,
              "observation_window_seconds": 20},
    )
    context = build_video_observation_context([browser])

    assert context is not None
    assert context.metrics.throughput_mbps is None
    assert context.metrics.estimated_required_mbps is None
    assert context.metrics.cpu_pct is None
    assert context.metrics.dropped_frames_pct is None


def test_rejects_invalid_or_stale_browser_snapshot():
    invalid = make_event(
        "browser.video.snapshot",
        data={"playback_state": "buffering", "stall_count": 2,
              "observation_window_seconds": 20},
    )
    stale = make_event(
        "browser.video.snapshot",
        seconds_ago=60,
        data={"playback_state": "stalled", "stall_count": 2,
              "observation_window_seconds": 20},
    )

    assert build_video_observation_context([invalid]) is None
    assert build_video_observation_context([stale]) is None


def test_requires_positive_freshness_window():
    import pytest

    with pytest.raises(ValueError):
        build_video_observation_context([], max_age_seconds=0)


def test_rejects_untyped_playback_state():
    malformed = make_event(
        "browser.video.snapshot",
        data={"playback_state": ["stalled"], "stall_count": 2,
              "observation_window_seconds": 20},
    )
    assert build_video_observation_context([malformed]) is None
