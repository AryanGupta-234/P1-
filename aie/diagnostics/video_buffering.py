"""Conservative video-buffering triage.

This module consumes already-collected telemetry. It does not inspect screens,
control browsers, change network settings, or execute remediation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class VideoMetrics:
    """A short-window snapshot from an explicitly enabled browser/system observer.

    Unknown values must be None; do not substitute zero for unavailable telemetry.
    """

    playback_stalled: bool
    stall_count: int = 0
    observation_window_seconds: float = 30.0
    throughput_mbps: float | None = None
    estimated_required_mbps: float | None = None
    rtt_ms: float | None = None
    packet_loss_pct: float | None = None
    packet_loss_scope: str | None = None
    cpu_pct: float | None = None
    dropped_frames_pct: float | None = None
    buffered_ahead_seconds: float | None = None
    playback_progress_delta_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.stall_count < 0:
            raise ValueError("stall_count cannot be negative")
        if self.observation_window_seconds <= 0:
            raise ValueError("observation_window_seconds must be positive")
        bounds = {
            "throughput_mbps": (0, None),
            "estimated_required_mbps": (0, None),
            "rtt_ms": (0, None),
            "packet_loss_pct": (0, 100),
            "cpu_pct": (0, 100),
            "dropped_frames_pct": (0, 100),
            "buffered_ahead_seconds": (0, 3600),
            "playback_progress_delta_seconds": (0, 300),
        }
        for name, (minimum, maximum) in bounds.items():
            value = getattr(self, name)
            if value is not None and (value < minimum or (maximum is not None and value > maximum)):
                raise ValueError(f"{name} must be between {minimum} and {maximum or 'unbounded'}")


@dataclass(frozen=True, slots=True)
class VideoThresholds:
    """Conservative defaults; calibrate against real device/service telemetry."""

    min_stalls: int = 2
    min_observation_seconds: float = 20.0
    packet_loss_pct: float = 2.0
    high_rtt_ms: float = 180.0
    cpu_pct: float = 90.0
    dropped_frames_pct: float = 5.0
    throughput_headroom: float = 1.15
    low_buffer_seconds: float = 0.75
    healthy_buffer_seconds: float = 5.0
    stalled_progress_seconds: float = 0.1


@dataclass(frozen=True, slots=True)
class DiagnosticFinding:
    cause: str
    severity: Severity
    confidence: float
    recommendation: str
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    status: Literal["no_stall", "insufficient_evidence", "findings"]
    findings: tuple[DiagnosticFinding, ...]
    observed_stalls: int
    observation_window_seconds: float
    disclaimer: str = "Findings are hypotheses from sampled telemetry, not proof of root cause."


def diagnose_video_buffering(
    metrics: VideoMetrics,
    thresholds: VideoThresholds = VideoThresholds(),
) -> DiagnosticReport:
    """Return ranked diagnostic hypotheses without taking action.

    A single stall or a short observation window is intentionally insufficient
    to infer a cause. Confidence values are heuristic ranking scores, not
    statistically calibrated probabilities.
    """
    if not metrics.playback_stalled:
        return DiagnosticReport("no_stall", (), metrics.stall_count,
                                metrics.observation_window_seconds)

    enough_samples = (
        metrics.stall_count >= thresholds.min_stalls
        and metrics.observation_window_seconds >= thresholds.min_observation_seconds
    )
    if not enough_samples:
        return DiagnosticReport("insufficient_evidence", (), metrics.stall_count,
                                metrics.observation_window_seconds)

    findings: list[DiagnosticFinding] = []

    if (
        metrics.packet_loss_pct is not None
        and metrics.packet_loss_pct >= thresholds.packet_loss_pct
    ):
        findings.append(DiagnosticFinding(
            "network_packet_loss", "high", 0.78,
            (
                "Packet loss was measured against the explicitly selected diagnostic targets. "
                "Compare gateway and video-path targets separately; ICMP loss is not proof "
                "that the streaming CDN dropped media packets."
            ),
            tuple(
                [f"Measured packet loss: {metrics.packet_loss_pct:.2f}%"]
                + ([f"Probe target labels: {metrics.packet_loss_scope}"] if metrics.packet_loss_scope else [])
            ),
        ))

    if (
        metrics.throughput_mbps is not None
        and metrics.estimated_required_mbps is not None
        and metrics.estimated_required_mbps > 0
        and metrics.throughput_mbps
        < metrics.estimated_required_mbps * thresholds.throughput_headroom
    ):
        findings.append(DiagnosticFinding(
            "insufficient_streaming_throughput", "high", 0.76,
            (
                "Compare sustained throughput with the stream's estimated requirement; "
                "if confirmed, offer a lower playback quality."
            ),
            (f"Measured throughput: {metrics.throughput_mbps:.2f} Mbps",
             f"Estimated requirement: {metrics.estimated_required_mbps:.2f} Mbps"),
        ))

    if (
        metrics.buffered_ahead_seconds is not None
        and metrics.buffered_ahead_seconds <= thresholds.low_buffer_seconds
    ):
        evidence = [
            f"Buffered media ahead: {metrics.buffered_ahead_seconds:.2f} seconds"
        ]
        if metrics.playback_progress_delta_seconds is not None:
            evidence.append(
                "Playback progress delta: "
                f"{metrics.playback_progress_delta_seconds:.2f} seconds"
            )
        findings.append(DiagnosticFinding(
            "stream_buffer_starvation",
            "medium",
            0.72,
            (
                "The player has little buffered media available. Compare sustained "
                "download throughput, DNS/connectivity and the streaming service; "
                "this signal alone does not prove a network fault."
            ),
            tuple(evidence),
        ))

    if (
        metrics.buffered_ahead_seconds is not None
        and metrics.buffered_ahead_seconds >= thresholds.healthy_buffer_seconds
        and metrics.playback_progress_delta_seconds is not None
        and metrics.playback_progress_delta_seconds <= thresholds.stalled_progress_seconds
    ):
        findings.append(DiagnosticFinding(
            "playback_pipeline_not_advancing_with_buffer",
            "medium",
            0.68,
            (
                "Buffered media is available but playback position is not advancing. "
                "Inspect the browser player, decoder/render path and dropped-frame trend "
                "before changing network settings."
            ),
            (
                f"Buffered media ahead: {metrics.buffered_ahead_seconds:.2f} seconds",
                f"Playback progress delta: {metrics.playback_progress_delta_seconds:.2f} seconds",
            ),
        ))

    if metrics.rtt_ms is not None and metrics.rtt_ms >= thresholds.high_rtt_ms:
        findings.append(DiagnosticFinding(
            "high_network_latency", "medium", 0.66,
            (
                "Compare gateway and external round-trip times to isolate local Wi-Fi "
                "latency from upstream latency."
            ),
            (f"Measured round-trip time: {metrics.rtt_ms:.1f} ms",),
        ))

    if (metrics.cpu_pct is not None and metrics.dropped_frames_pct is not None
            and metrics.cpu_pct >= thresholds.cpu_pct
            and metrics.dropped_frames_pct >= thresholds.dropped_frames_pct):
        findings.append(DiagnosticFinding(
            "local_decode_or_render_pressure", "medium", 0.73,
            (
                "Inspect browser/GPU process load and dropped-frame trend before changing "
                "network settings."
            ),
            (f"Foreground app CPU share of total logical capacity: {metrics.cpu_pct:.1f}%",
             f"Dropped frames: {metrics.dropped_frames_pct:.1f}%"),
        ))

    findings.sort(key=lambda item: (item.severity == "high", item.confidence), reverse=True)
    status = "findings" if findings else "insufficient_evidence"
    return DiagnosticReport(status, tuple(findings), metrics.stall_count,
                            metrics.observation_window_seconds)
