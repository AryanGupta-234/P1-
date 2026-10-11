"""Temporal correlation of browser playback observations and Windows network evidence.

The browser event contract is intentionally small and privacy-minimizing. This module
does not inspect page content; it consumes normalized events from an explicitly
enabled future browser telemetry bridge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from aie.contracts import AIEEvent
from aie.diagnostics.video_buffering import VideoMetrics

NetworkEvidenceKind = Literal["gateway_probe", "external_probe", "dns_probe"]


@dataclass(frozen=True, slots=True)
class NetworkEvidence:
    """A recent network measurement retained as evidence, not mislabelled as RTT."""

    kind: NetworkEvidenceKind
    target: str
    connect_latency_ms: float | None
    resolution_ms: float | None
    resolved: bool | None
    age_seconds: float
    event_id: str


@dataclass(frozen=True, slots=True)
class VideoObservationContext:
    """Correlated playback metrics plus nearby network observations."""

    host_id: str
    playback_state: str
    metrics: VideoMetrics
    network_evidence: tuple[NetworkEvidence, ...]
    evidence_event_ids: tuple[str, ...]
    observed_at: datetime
    generated_at: datetime


def _number(data: dict, key: str, *, minimum: float, maximum: float | None = None) -> float | None:
    value = data.get(key)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        return None
    if maximum is not None and result > maximum:
        return None
    return result


def _network_evidence(event: AIEEvent, age_seconds: float) -> NetworkEvidence | None:
    data = event.data
    if event.event_type == "network.gateway_probe":
        kind: NetworkEvidenceKind = "gateway_probe"
        target = event.entity.name
        connect_latency = _number(data, "connect_latency_ms", minimum=0)
        return NetworkEvidence(
            kind, target, connect_latency, None, None, age_seconds, event.event_id
        )

    if event.event_type == "network.external_probe":
        kind = "external_probe"
        target = event.entity.name
        connect_latency = _number(data, "connect_latency_ms", minimum=0)
        return NetworkEvidence(
            kind, target, connect_latency, None, None, age_seconds, event.event_id
        )

    if event.event_type == "network.dns_probe":
        kind = "dns_probe"
        target = event.entity.name
        resolution = _number(data, "resolution_ms", minimum=0)
        resolved_value = data.get("resolved")
        resolved = resolved_value if isinstance(resolved_value, bool) else None
        return NetworkEvidence(
            kind, target, None, resolution, resolved, age_seconds, event.event_id
        )
    return None


def build_video_observation_context(
    events: list[AIEEvent] | tuple[AIEEvent, ...],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 30.0,
) -> VideoObservationContext | None:
    """Build a playback context from the latest fresh browser snapshot and nearby evidence.

    Expected browser event:
      event_type = "browser.video.snapshot"
      data = {
        "playback_state": "playing|waiting|stalled|paused|ended",
        "stall_count": 0,
        "observation_window_seconds": 30,
        "throughput_mbps": null,
        "estimated_required_mbps": null,
        "cpu_pct": null,
        "dropped_frames_pct": null
      }

    Missing metrics remain None. Network connect latency is retained separately
    from VideoMetrics.rtt_ms because a TCP connect duration is not a packet RTT.
    """
    if not 0 < max_age_seconds <= 300:
        raise ValueError("max_age_seconds must be greater than 0 and no more than 300")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    browser_events = [
        event for event in events
        if event.event_type == "browser.video.snapshot"
        and event.timestamp.tzinfo is not None
        and timedelta(0) <= current - event.timestamp <= timedelta(seconds=max_age_seconds)
    ]
    if not browser_events:
        return None

    browser_event = max(browser_events, key=lambda event: event.timestamp)
    data = browser_event.data
    playback_state = data.get("playback_state")
    allowed_states = {"playing", "waiting", "stalled", "paused", "ended"}
    if playback_state not in allowed_states:
        return None

    playback_stalled = playback_state in {"waiting", "stalled"}
    stall_count = data.get("stall_count", 1 if playback_stalled else 0)
    if isinstance(stall_count, bool) or not isinstance(stall_count, int) or stall_count < 0:
        return None

    observation_window = _number(
        data, "observation_window_seconds", minimum=0.001
    )
    if observation_window is None:
        return None

    metrics = VideoMetrics(
        playback_stalled=playback_stalled,
        stall_count=stall_count,
        observation_window_seconds=observation_window,
        throughput_mbps=_number(data, "throughput_mbps", minimum=0),
        estimated_required_mbps=_number(data, "estimated_required_mbps", minimum=0),
        cpu_pct=_number(data, "cpu_pct", minimum=0, maximum=100),
        dropped_frames_pct=_number(data, "dropped_frames_pct", minimum=0, maximum=100),
    )

    network_evidence: list[NetworkEvidence] = []
    evidence_ids = [browser_event.event_id]
    for event in events:
        if event.host_id != browser_event.host_id:
            continue
        if event.timestamp.tzinfo is None:
            continue
        age = (current - event.timestamp).total_seconds()
        if age < 0 or age > max_age_seconds:
            continue
        evidence = _network_evidence(event, age)
        if evidence is not None:
            network_evidence.append(evidence)
            evidence_ids.append(event.event_id)

    network_evidence.sort(key=lambda item: item.age_seconds)
    return VideoObservationContext(
        host_id=browser_event.host_id,
        playback_state=playback_state,
        metrics=metrics,
        network_evidence=tuple(network_evidence),
        evidence_event_ids=tuple(dict.fromkeys(evidence_ids)),
        observed_at=browser_event.timestamp,
        generated_at=current,
    )
