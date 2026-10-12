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
    assert context.metrics.buffered_ahead_seconds == 0.4
    assert context.metrics.playback_progress_delta_seconds == 0.0
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


def test_correlates_foreground_process_resources_without_copying_window_title():
    browser = make_event(
        "browser.video.snapshot",
        data={
            "playback_state": "stalled",
            "stall_count": 3,
            "observation_window_seconds": 30,
        },
        event_id="browser-stall",
    )
    foreground = make_event(
        "window.foreground_changed",
        seconds_ago=1,
        data={
            "pid": 4001,
            "process_name": "msedge.exe",
            "window_class": "Chrome_WidgetWin_1",
            "window_title_collected": True,
            "window_title": "Sensitive document title",
        },
        event_id="foreground-edge",
    )
    resource = make_event(
        "process.foreground_resource_sample",
        seconds_ago=1,
        data={
            "pid": 4001,
            "process_name": "msedge.exe",
            "cpu_pct": 67.5,
            "memory_rss_bytes": 512 * 1024 * 1024,
            "thread_count": 42,
            "io_read_bytes": 1000,
            "io_write_bytes": 2000,
        },
        event_id="edge-resource",
    )
    other_process = make_event(
        "process.foreground_resource_sample",
        seconds_ago=1,
        data={"pid": 5002, "process_name": "unrelated.exe", "cpu_pct": 99.0},
        event_id="unrelated-resource",
    )

    context = build_video_observation_context(
        [browser, foreground, resource, other_process]
    )

    assert context is not None
    assert context.active_application is not None
    assert context.active_application.process_name == "msedge.exe"
    assert context.active_application.pid == 4001
    assert context.active_application.cpu_pct == 67.5
    assert context.active_application.memory_rss_bytes == 512 * 1024 * 1024
    assert context.active_application.thread_count == 42
    assert context.active_application.window_title_collected is True
    assert not hasattr(context.active_application, "window_title")
    assert "foreground-edge" in context.evidence_event_ids
    assert "edge-resource" in context.evidence_event_ids
    assert "unrelated-resource" not in context.evidence_event_ids


def test_browser_cpu_falls_back_to_fresh_foreground_browser_process():
    browser = make_event(
        "browser.video.snapshot",
        data={
            "playback_state": "stalled",
            "stall_count": 4,
            "observation_window_seconds": 45,
            "dropped_frames_pct": 8.0,
        },
        event_id="browser-cpu-fallback",
    )
    foreground = make_event(
        "window.foreground_changed",
        seconds_ago=1,
        data={"pid": 4001, "process_name": "msedge.exe", "window_class": "Chrome_WidgetWin_1"},
        event_id="edge-active",
    )
    resource = make_event(
        "process.foreground_resource_sample",
        seconds_ago=1,
        data={"pid": 4001, "cpu_pct": 96.0},
        event_id="edge-cpu",
    )

    context = build_video_observation_context([browser, foreground, resource])

    assert context is not None
    assert context.metrics.cpu_pct == 96.0


def test_non_browser_foreground_process_does_not_supply_browser_cpu():
    browser = make_event(
        "browser.video.snapshot",
        data={
            "playback_state": "stalled",
            "stall_count": 4,
            "observation_window_seconds": 45,
            "dropped_frames_pct": 8.0,
        },
        event_id="browser-no-fallback",
    )
    foreground = make_event(
        "window.foreground_changed",
        seconds_ago=1,
        data={"pid": 5001, "process_name": "notepad.exe", "window_class": "Notepad"},
        event_id="notepad-active",
    )
    resource = make_event(
        "process.foreground_resource_sample",
        seconds_ago=1,
        data={"pid": 5001, "cpu_pct": 99.0},
        event_id="notepad-cpu",
    )

    context = build_video_observation_context([browser, foreground, resource])

    assert context is not None
    assert context.metrics.cpu_pct is None

def test_correlates_opt_in_video_network_probe_without_retaining_endpoints():
    browser = make_event(
        "browser.video.snapshot",
        data={
            "playback_state": "stalled",
            "stall_count": 4,
            "observation_window_seconds": 45,
        },
        event_id="browser-video-stall",
    )
    probe = make_event(
        "network.video_probe",
        seconds_ago=2,
        data={
            "packet_target_labels": ["gateway", "stream_endpoint"],
            "packet_loss_by_target": [
                {"label": "gateway", "packets_sent": 4, "packets_received": 3, "packet_loss_pct": 25.0},
                {"label": "stream_endpoint", "packets_sent": 4, "packets_received": 3, "packet_loss_pct": 25.0},
            ],
            "packets_sent": 8,
            "packets_received": 6,
            "packet_loss_pct": 25.0,
            "throughput_mbps": 7.25,
            "throughput_bytes": 524288,
            "throughput_duration_seconds": 0.58,
            "estimated_required_mbps": 8.0,
            "throughput_url": "https://private.example/signed-token",
        },
        event_id="video-probe-1",
    )

    context = build_video_observation_context([browser, probe])

    assert context is not None
    assert context.metrics.packet_loss_pct is None
    assert context.metrics.packet_loss_scope is None
    assert context.metrics.throughput_mbps == 7.25
    assert context.metrics.estimated_required_mbps == 8.0
    assert "video-probe-1" in context.evidence_event_ids
    assert "private.example" not in str(context.metrics)
    assert context.network_evidence[0].target == "user-selected diagnostic targets"
    assert len(context.network_evidence[0].packet_loss_by_target) == 2
    assert context.network_evidence[0].packet_loss_by_target[0] == ("gateway", 25.0, 4, 3)

def test_single_probe_target_can_supply_a_scoped_packet_loss_hypothesis():
    browser = make_event(
        "browser.video.snapshot",
        data={
            "playback_state": "stalled",
            "stall_count": 4,
            "observation_window_seconds": 45,
        },
        event_id="browser-single-target-stall",
    )
    probe = make_event(
        "network.video_probe",
        seconds_ago=2,
        data={
            "packet_target_labels": ["gateway"],
            "packet_loss_by_target": [
                {"label": "gateway", "packets_sent": 4, "packets_received": 3, "packet_loss_pct": 25.0}
            ],
            "packets_sent": 4,
            "packets_received": 3,
            "packet_loss_pct": 25.0,
        },
        event_id="video-probe-single",
    )

    context = build_video_observation_context([browser, probe])

    assert context is not None
    assert context.metrics.packet_loss_pct == 25.0
    assert context.metrics.packet_loss_scope == "gateway"
    assert "video-probe-single" in context.evidence_event_ids

