from datetime import datetime, timedelta, timezone

from aie.context.temporal import (
    CorrelationRule,
    correlate_events,
)
from aie.contracts import AIEEvent, EntityRef


BASE = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def event(event_id, event_type, seconds_offset, host="host-a"):
    return AIEEvent(
        event_id=event_id,
        timestamp=BASE + timedelta(seconds=seconds_offset),
        host_id=host,
        source="test",
        event_type=event_type,
        entity=EntityRef(type="test", name=event_id),
    )


def test_temporal_correlation_matches_explicit_rule_and_same_host():
    rule = CorrelationRule(
        name="video-with-network",
        anchor_event_type="browser.video.snapshot",
        related_event_types=frozenset({"network.gateway_probe"}),
        max_gap_seconds=5,
    )
    results = correlate_events(
        [
            event("video", "browser.video.snapshot", 0),
            event("network", "network.gateway_probe", 3),
            event("unrelated", "network.gateway_probe", 20),
        ],
        [rule],
        now=BASE + timedelta(seconds=20),
        max_input_age_seconds=60,
    )

    assert len(results) == 1
    assert results[0].anchor_event_id == "video"
    assert results[0].related_event_ids == ("network",)
    assert results[0].observed_event_types == (
        "browser.video.snapshot",
        "network.gateway_probe",
    )
    assert results[0].time_span_seconds == 3.0


def test_temporal_correlation_blocks_cross_host_by_default():
    rule = CorrelationRule(
        name="foreground-with-process",
        anchor_event_type="window.foreground_changed",
        related_event_types=frozenset({"process.foreground_resource_sample"}),
        max_gap_seconds=5,
    )
    results = correlate_events(
        [
            event("foreground", "window.foreground_changed", 0, "host-a"),
            event("process", "process.foreground_resource_sample", 1, "host-b"),
        ],
        [rule],
        now=BASE + timedelta(seconds=2),
    )

    assert results == ()


def test_temporal_correlation_can_explicitly_cross_hosts():
    rule = CorrelationRule(
        name="cross-host",
        anchor_event_type="host.snapshot",
        related_event_types=frozenset({"host.snapshot.remote"}),
        max_gap_seconds=2,
        same_host_only=False,
    )
    results = correlate_events(
        [
            event("left", "host.snapshot", 0, "host-a"),
            event("right", "host.snapshot.remote", 1, "host-b"),
        ],
        [rule],
        now=BASE + timedelta(seconds=2),
    )

    assert results[0].related_event_ids == ("right",)


def test_temporal_correlation_drops_future_and_stale_inputs():
    rule = CorrelationRule(
        name="future-stale",
        anchor_event_type="a",
        related_event_types=frozenset({"b"}),
        max_gap_seconds=5,
    )
    results = correlate_events(
        [
            event("anchor", "a", -100),
            event("stale", "b", -99),
            event("future", "b", 2),
        ],
        [rule],
        now=BASE,
        max_input_age_seconds=60,
    )
    assert results == ()
