"""Temporal correlation of browser playback, foreground-app and network evidence.

The browser event contract is intentionally small and privacy-minimizing. This module
does not inspect page content; it consumes normalized events from an explicitly
enabled browser telemetry bridge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from aie.contracts import AIEEvent
from aie.diagnostics.video_buffering import VideoMetrics

NetworkEvidenceKind = Literal["gateway_probe", "external_probe", "dns_probe", "video_probe"]


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
    throughput_mbps: float | None = None
    packet_loss_pct: float | None = None
    target_labels: tuple[str, ...] = ()
    packet_loss_by_target: tuple[tuple[str, float, int, int], ...] = ()
    estimated_required_mbps: float | None = None


@dataclass(frozen=True, slots=True)
class ApplicationEvidence:
    """Foreground application metadata and its latest bounded resource sample."""

    process_name: str
    pid: int
    window_class: str | None
    cpu_pct: float | None
    memory_rss_bytes: int | None
    thread_count: int | None
    age_seconds: float
    window_title_collected: bool
    evidence_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VideoObservationContext:
    """Correlated playback metrics plus nearby application and network observations."""

    host_id: str
    playback_state: str
    metrics: VideoMetrics
    active_application: ApplicationEvidence | None
    network_evidence: tuple[NetworkEvidence, ...]
    buffered_ahead_seconds: float | None
    playback_progress_delta_seconds: float | None
    evidence_event_ids: tuple[str, ...]
    observed_at: datetime
    generated_at: datetime


def _number(
    data: dict,
    key: str,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float | None:
    value = data.get(key)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(result) or result < minimum:
        return None
    if maximum is not None and result > maximum:
        return None
    return result


def _nonnegative_integer(data: dict, key: str) -> int | None:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _network_evidence(event: AIEEvent, age_seconds: float) -> NetworkEvidence | None:
    data = event.data
    if event.event_type == "network.gateway_probe":
        return NetworkEvidence(
            "gateway_probe",
            event.entity.name,
            _number(data, "connect_latency_ms", minimum=0),
            None,
            None,
            age_seconds,
            event.event_id,
        )

    if event.event_type == "network.external_probe":
        return NetworkEvidence(
            "external_probe",
            event.entity.name,
            _number(data, "connect_latency_ms", minimum=0),
            None,
            None,
            age_seconds,
            event.event_id,
        )

    if event.event_type == "network.dns_probe":
        resolved_value = data.get("resolved")
        resolved = resolved_value if isinstance(resolved_value, bool) else None
        return NetworkEvidence(
            "dns_probe",
            event.entity.name,
            None,
            _number(data, "resolution_ms", minimum=0),
            resolved,
            age_seconds,
            event.event_id,
        )

    if event.event_type == "network.video_probe":
        raw_rows = data.get("packet_loss_by_target")
        safe_rows: list[tuple[str, float, int, int]] = []
        seen_labels: set[str] = set()
        if isinstance(raw_rows, list):
            for item in raw_rows[:2]:
                if not isinstance(item, dict):
                    continue
                label = item.get("label")
                loss = item.get("packet_loss_pct")
                sent = item.get("packets_sent")
                received = item.get("packets_received")
                if (
                    not isinstance(label, str)
                    or not 1 <= len(label) <= 24
                    or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in label)
                    or label in seen_labels
                    or isinstance(loss, bool)
                    or not isinstance(loss, (int, float))
                    or not math.isfinite(float(loss))
                    or not 0 <= loss <= 100
                    or isinstance(sent, bool)
                    or not isinstance(sent, int)
                    or not 1 <= sent <= 4
                    or isinstance(received, bool)
                    or not isinstance(received, int)
                    or not 0 <= received <= sent
                ):
                    continue
                seen_labels.add(label)
                safe_rows.append((label, float(loss), sent, received))
        safe_labels = tuple(item[0] for item in safe_rows)
        target_loss = safe_rows[0][1] if len(safe_rows) == 1 else None
        return NetworkEvidence(
            "video_probe",
            "user-selected diagnostic targets",
            None,
            None,
            None,
            age_seconds,
            event.event_id,
            _number(data, "throughput_mbps", minimum=0),
            target_loss,
            safe_labels,
            tuple(safe_rows),
            _number(data, "estimated_required_mbps", minimum=0),
        )
    return None


def _temporally_relevant(
    event: AIEEvent,
    *,
    host_id: str,
    anchor: datetime,
    current: datetime,
    max_age_seconds: float,
) -> bool:
    if event.host_id != host_id or event.timestamp.tzinfo is None:
        return False
    age_now = (current - event.timestamp).total_seconds()
    age_anchor = abs((anchor - event.timestamp).total_seconds())
    return 0 <= age_now <= max_age_seconds and age_anchor <= max_age_seconds


def _application_evidence(
    events: list[AIEEvent] | tuple[AIEEvent, ...],
    *,
    host: str,
    anchor: datetime,
    current: datetime,
    max_age_seconds: float,
) -> ApplicationEvidence | None:
    foreground_events = [
        event for event in events
        if event.event_type == "window.foreground_changed"
        and _temporally_relevant(
            event,
            host_id=host,
            anchor=anchor,
            current=current,
            max_age_seconds=max_age_seconds,
        )
    ]
    if not foreground_events:
        return None

    foreground = max(foreground_events, key=lambda event: event.timestamp)
    process_name = foreground.data.get("process_name")
    pid = _nonnegative_integer(foreground.data, "pid")
    if not isinstance(process_name, str) or not process_name or pid is None:
        return None

    samples = [
        event for event in events
        if event.event_type == "process.foreground_resource_sample"
        and event.data.get("pid") == pid
        and _temporally_relevant(
            event,
            host_id=host,
            anchor=anchor,
            current=current,
            max_age_seconds=max_age_seconds,
        )
    ]
    sample = max(samples, key=lambda event: event.timestamp) if samples else None
    sample_data = sample.data if sample else {}
    window_class = foreground.data.get("window_class")
    if not isinstance(window_class, str):
        window_class = None
    title_collected = foreground.data.get("window_title_collected") is True

    evidence_ids = [foreground.event_id]
    if sample is not None:
        evidence_ids.append(sample.event_id)

    return ApplicationEvidence(
        process_name=process_name,
        pid=pid,
        window_class=window_class,
        cpu_pct=_number(sample_data, "cpu_pct", minimum=0, maximum=10000),
        memory_rss_bytes=_nonnegative_integer(sample_data, "memory_rss_bytes"),
        thread_count=_nonnegative_integer(sample_data, "thread_count"),
        age_seconds=max(0.0, (current - foreground.timestamp).total_seconds()),
        window_title_collected=title_collected,
        evidence_event_ids=tuple(evidence_ids),
    )


def build_video_observation_context(
    events: list[AIEEvent] | tuple[AIEEvent, ...],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 30.0,
) -> VideoObservationContext | None:
    """Build a fresh playback context from browser, foreground and network events.

    Expected browser event:
      event_type = "browser.video.snapshot"
      data = {
        "playback_state": "playing|waiting|stalled|paused|ended",
        "stall_count": 0,
        "observation_window_seconds": 30,
        "buffered_ahead_seconds": null,
        "playback_progress_delta_seconds": null,
        "throughput_mbps": null,
        "estimated_required_mbps": null,
        "cpu_pct": null,
        "dropped_frames_pct": null
      }

    Missing metrics remain None. TCP connect latency is never treated as packet RTT.
    Window titles are not copied into the context, even when separately opted in.
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
    if not isinstance(playback_state, str) or playback_state not in allowed_states:
        return None

    playback_stalled = playback_state in {"waiting", "stalled"}
    stall_count = data.get("stall_count", 1 if playback_stalled else 0)
    if isinstance(stall_count, bool) or not isinstance(stall_count, int) or stall_count < 0:
        return None

    observation_window = _number(data, "observation_window_seconds", minimum=0.001)
    if observation_window is None:
        return None

    application = _application_evidence(
        events,
        host=browser_event.host_id,
        anchor=browser_event.timestamp,
        current=current,
        max_age_seconds=max_age_seconds,
    )
    browser_cpu = _number(data, "cpu_pct", minimum=0, maximum=100)
    if (
        browser_cpu is None
        and application is not None
        and application.process_name.casefold() in {"chrome.exe", "msedge.exe"}
    ):
        browser_cpu = application.cpu_pct

    network_evidence: list[NetworkEvidence] = []
    evidence_ids = [browser_event.event_id]
    for event in events:
        if not _temporally_relevant(
            event,
            host_id=browser_event.host_id,
            anchor=browser_event.timestamp,
            current=current,
            max_age_seconds=max_age_seconds,
        ):
            continue
        evidence = _network_evidence(event, (current - event.timestamp).total_seconds())
        if evidence is not None:
            network_evidence.append(evidence)
            evidence_ids.append(event.event_id)

    network_evidence.sort(key=lambda item: item.age_seconds)
    video_probes = [item for item in network_evidence if item.kind == "video_probe"]
    latest_video_probe = video_probes[0] if video_probes else None
    browser_throughput = _number(data, "throughput_mbps", minimum=0)
    browser_packet_loss = _number(data, "packet_loss_pct", minimum=0, maximum=100)
    packet_scope = (
        ", ".join(latest_video_probe.target_labels)
        if latest_video_probe is not None and latest_video_probe.target_labels
        else None
    )
    browser_required_mbps = _number(data, "estimated_required_mbps", minimum=0)
    probe_required_mbps = (
        latest_video_probe.estimated_required_mbps
        if latest_video_probe is not None
        else None
    )
    metrics = VideoMetrics(
        playback_stalled=playback_stalled,
        stall_count=stall_count,
        observation_window_seconds=observation_window,
        throughput_mbps=(
            browser_throughput
            if browser_throughput is not None
            else latest_video_probe.throughput_mbps if latest_video_probe is not None else None
        ),
        estimated_required_mbps=(
            browser_required_mbps
            if browser_required_mbps is not None
            else probe_required_mbps
        ),
        packet_loss_pct=(
            browser_packet_loss
            if browser_packet_loss is not None
            else latest_video_probe.packet_loss_pct if latest_video_probe is not None else None
        ),
        packet_loss_scope=packet_scope,
        cpu_pct=browser_cpu,
        dropped_frames_pct=_number(data, "dropped_frames_pct", minimum=0, maximum=100),
        buffered_ahead_seconds=_number(data, "buffered_ahead_seconds", minimum=0, maximum=3600),
        playback_progress_delta_seconds=_number(
            data, "playback_progress_delta_seconds", minimum=0, maximum=300
        ),
    )
    if application is not None:
        evidence_ids.extend(application.evidence_event_ids)

    return VideoObservationContext(
        host_id=browser_event.host_id,
        playback_state=playback_state,
        metrics=metrics,
        active_application=application,
        network_evidence=tuple(network_evidence),
        buffered_ahead_seconds=_number(data, "buffered_ahead_seconds", minimum=0, maximum=3600),
        playback_progress_delta_seconds=_number(
            data, "playback_progress_delta_seconds", minimum=0, maximum=300
        ),
        evidence_event_ids=tuple(dict.fromkeys(evidence_ids)),
        observed_at=browser_event.timestamp,
        generated_at=current,
    )
