import json
from datetime import datetime, timedelta, timezone

import pytest

from aie.contracts import AIEEvent, EntityRef
from aie.diagnostics.video_evaluation import TraceDatasetError, load_trace_dataset
from aie.diagnostics.video_field_export import (
    FieldTraceExportError,
    prepare_field_trace_candidates,
)


def make_event(event_type, *, timestamp, host="host-a", stable_id=None, data=None, event_id=None, sensitivity="internal"):
    return AIEEvent(
        event_id=event_id or f"{event_type}-{timestamp.timestamp()}-{host}",
        timestamp=timestamp,
        host_id=host,
        source="test",
        event_type=event_type,
        entity=EntityRef(type="test", name=event_type, stable_id=stable_id),
        data=data or {},
        sensitivity=sensitivity,
    )


def test_exports_one_sanitized_best_candidate_per_session():
    now = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    session = "private-media-session-id"
    older = make_event(
        "browser.video.snapshot",
        timestamp=now - timedelta(seconds=15),
        stable_id=session,
        event_id="raw-browser-event-old",
        data={
            "playback_state": "stalled",
            "stall_count": 1,
            "observation_window_seconds": 25,
            "buffered_ahead_seconds": 0.4,
            "media_url": "https://private.example/signed-media-token",
        },
    )
    selected = make_event(
        "browser.video.snapshot",
        timestamp=now - timedelta(seconds=10),
        stable_id=session,
        event_id="raw-browser-event-selected",
        data={
            "playback_state": "stalled",
            "stall_count": 4,
            "observation_window_seconds": 45,
            "buffered_ahead_seconds": 0.2,
            "playback_progress_delta_seconds": 0.0,
            "dropped_frames_pct": 8.0,
        },
    )
    probe = make_event(
        "network.video_probe",
        timestamp=now - timedelta(seconds=12),
        event_id="raw-probe-event",
        data={
            "packet_target_labels": ["gateway"],
            "packet_loss_by_target": [
                {"label": "gateway", "packets_sent": 4, "packets_received": 3, "packet_loss_pct": 25.0}
            ],
            "packets_sent": 4,
            "packets_received": 3,
            "packet_loss_pct": 25.0,
            "throughput_mbps": 5.5,
            "estimated_required_mbps": 8.0,
            "throughput_url": "https://private.example/test-object",
        },
    )
    foreground = make_event(
        "window.foreground_changed",
        timestamp=now - timedelta(seconds=11),
        event_id="raw-foreground-event",
        data={
            "pid": 42,
            "process_name": "msedge.exe",
            "window_title": "Confidential Watch History",
            "window_title_collected": True,
        },
        sensitivity="sensitive",
    )
    resources = make_event(
        "process.foreground_resource_sample",
        timestamp=now - timedelta(seconds=11),
        event_id="raw-resource-event",
        data={"pid": 42, "cpu_pct": 96.0, "memory_rss_bytes": 123456789},
    )

    result = prepare_field_trace_candidates(
        [older, selected, probe, foreground, resources],
        now=now,
    )

    assert result["dataset_kind"] == "field_candidate"
    assert result["case_count"] == 1
    case = result["cases"][0]
    assert case["id"] == "candidate-0001"
    assert case["expected_causes"] is None
    assert case["label_status"] == "requires_human_review"
    assert case["metrics"]["stall_count"] == 4
    assert case["metrics"]["packet_loss_pct"] == 25.0
    assert case["metrics"]["throughput_mbps"] == 5.5
    assert case["metrics"]["estimated_required_mbps"] == 8.0
    assert case["metrics"]["cpu_pct"] == 96.0

    serialized = json.dumps(result)
    for private_value in (
        "raw-browser-event",
        "raw-probe-event",
        "private-media-session-id",
        "private.example",
        "Confidential Watch History",
        "msedge.exe",
        "host-a",
        "123456789",
    ):
        assert private_value not in serialized


def test_keeps_same_session_ids_separate_across_hosts():
    now = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    events = [
        make_event(
            "browser.video.snapshot",
            timestamp=now - timedelta(seconds=4),
            host=host,
            stable_id="same-session-token",
            event_id=f"event-{host}",
            data={
                "playback_state": "playing",
                "stall_count": 0,
                "observation_window_seconds": 20,
            },
        )
        for host in ("host-a", "host-b")
    ]

    result = prepare_field_trace_candidates(events, now=now)

    assert result["case_count"] == 2
    assert [case["id"] for case in result["cases"]] == ["candidate-0001", "candidate-0002"]


def test_candidate_file_is_not_accepted_as_a_labelled_evaluation_dataset(tmp_path):
    now = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    event = make_event(
        "browser.video.snapshot",
        timestamp=now - timedelta(seconds=2),
        stable_id="session",
        data={
            "playback_state": "stalled",
            "stall_count": 3,
            "observation_window_seconds": 30,
        },
    )
    result = prepare_field_trace_candidates([event], now=now)
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(TraceDatasetError, match="dataset_kind"):
        load_trace_dataset(path)


def test_rejects_invalid_field_candidate_export_limits():
    now = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    with pytest.raises(FieldTraceExportError):
        prepare_field_trace_candidates([], now=now, limit=0)
    with pytest.raises(FieldTraceExportError):
        prepare_field_trace_candidates([], now=datetime(2026, 10, 12, 10, 0), limit=1)
