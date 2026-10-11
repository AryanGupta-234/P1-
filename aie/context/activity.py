"""Privacy-safe, cross-provider activity timeline and session grouping."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from aie.contracts import AIEEvent

ActivityKind = Literal[
    "application",
    "browser",
    "network",
    "process",
    "diagnostic",
    "system",
    "feedback",
    "other",
]
_PROCESS_NAME = re.compile(r"^[A-Za-z0-9_. -]{1,120}$")
_SAFE_STATES = {"playing", "waiting", "stalled", "paused", "ended"}


@dataclass(frozen=True, slots=True)
class ActivitySignal:
    """Safe display projection of one raw evidence event; no raw payload is retained."""

    event_id: str
    timestamp: datetime
    kind: ActivityKind
    title: str
    source: str
    event_type: str
    confidence: float
    evidence_kind: str
    sensitivity: str
    correlation_id: str | None


@dataclass(frozen=True, slots=True)
class ActivitySession:
    """Time-clustered observations from one host; not a claim about user intent."""

    session_id: str
    host_id: str
    started_at: datetime
    ended_at: datetime
    event_count: int
    kinds: tuple[str, ...]
    applications: tuple[str, ...]
    signals: tuple[ActivitySignal, ...]


@dataclass(frozen=True, slots=True)
class ActivityTimeline:
    """A bounded, read-only projection over normalized event evidence."""

    generated_at: datetime
    event_count: int
    sessions: tuple[ActivitySession, ...]
    current_session_id: str | None


def _kind(event_type: str) -> ActivityKind:
    if event_type.startswith(("window.",)):
        return "application"
    if event_type.startswith(("browser.",)):
        return "browser"
    if event_type.startswith(("network.",)):
        return "network"
    if event_type.startswith(("process.",)):
        return "process"
    if event_type.startswith(("diagnostic.",)):
        return "diagnostic"
    if event_type.startswith(("windows.eventlog.", "host.")):
        return "system"
    if event_type.startswith(("user.",)):
        return "feedback"
    return "other"


def _safe_process_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not _PROCESS_NAME.fullmatch(candidate):
        return None
    return candidate


def _safe_number(data: dict, key: str, *, minimum: float = 0.0, maximum: float = 1_000_000.0) -> float | None:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        return None
    return number


def _signal_title(event: AIEEvent) -> tuple[str, str | None]:
    """Render an allowlisted one-line description and optional app identity."""
    data = event.data
    event_type = event.event_type

    if event_type == "window.foreground_changed":
        app = _safe_process_name(data.get("process_name"))
        return (f"Foreground application: {app}" if app else "Foreground application changed", app)

    if event_type == "window.uia_tree_snapshot":
        app = _safe_process_name(data.get("process_name"))
        count = data.get("node_count")
        count_text = str(count) if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 200 else "unknown"
        prefix = f"{app}: " if app else ""
        return f"UI structure sampled ({count_text} controls) — {prefix.rstrip()}", app

    if event_type == "process.system_resource_snapshot":
        processes = data.get("processes")
        summaries: list[str] = []
        if isinstance(processes, list):
            for process in processes[:3]:
                if not isinstance(process, dict):
                    continue
                name = _safe_process_name(process.get("process_name"))
                if name is None:
                    continue
                cpu = _safe_number(
                    process,
                    "cpu_pct_total_capacity",
                    maximum=100,
                )
                memory = process.get("memory_rss_bytes")
                details = []
                if cpu is not None:
                    details.append(f"CPU {cpu:.1f}%")
                if (
                    isinstance(memory, int)
                    and not isinstance(memory, bool)
                    and 0 <= memory <= 2**53
                ):
                    details.append(f"memory {memory / (1024 * 1024):.0f} MiB")
                summaries.append(
                    name + (f" ({', '.join(details)})" if details else "")
                )
        sampled = data.get("sampled_processes")
        sampled_text = (
            str(sampled)
            if isinstance(sampled, int) and not isinstance(sampled, bool) and 0 <= sampled <= 512
            else "unknown"
        )
        suffix = "; top: " + ", ".join(summaries) if summaries else ""
        return f"System process snapshot ({sampled_text} sampled){suffix}", None

    if event_type == "process.foreground_resource_sample":
        app = _safe_process_name(data.get("process_name"))
        cpu = _safe_number(data, "cpu_pct", maximum=100)
        memory = data.get("memory_rss_bytes")
        parts = []
        if cpu is not None:
            parts.append(f"CPU {cpu:.1f}%")
        if isinstance(memory, int) and not isinstance(memory, bool) and 0 <= memory <= 2**53:
            parts.append(f"memory {memory / (1024 * 1024):.0f} MiB")
        name = app or "Foreground process"
        return f"{name} resource sample" + (f" ({', '.join(parts)})" if parts else ""), app

    if event_type == "browser.video.snapshot":
        state = data.get("playback_state")
        state = state if isinstance(state, str) and state in _SAFE_STATES else "unknown"
        stalls = data.get("stall_count")
        stall_text = f", {stalls} stalls" if isinstance(stalls, int) and not isinstance(stalls, bool) and 0 <= stalls <= 10000 else ""
        buffer = _safe_number(data, "buffered_ahead_seconds", maximum=3600)
        buffer_text = f", {buffer:.1f}s buffered" if buffer is not None else ""
        return f"Video playback {state}{stall_text}{buffer_text}", None

    if event_type.startswith("network."):
        latency = _safe_number(data, "connect_latency_ms", maximum=300_000)
        resolution = _safe_number(data, "resolution_ms", maximum=300_000)
        if latency is not None:
            return f"Network TCP connect measured ({latency:.1f} ms)", None
        if resolution is not None:
            return f"DNS resolution measured ({resolution:.1f} ms)", None
        return "Network observation recorded", None

    if event_type == "windows.eventlog.record":
        channel = data.get("channel")
        channel = channel if channel in {"Application", "System"} else "Windows"
        event_id = data.get("event_id")
        id_text = f" event {event_id}" if isinstance(event_id, int) and not isinstance(event_id, bool) else ""
        return f"{channel} Event Log metadata{id_text}", None

    if event_type == "windows.eventlog.provider_error":
        channel = data.get("channel")
        channel = channel if channel in {"Application", "System"} else "Windows"
        error_type = data.get("error_type")
        error_text = f" ({error_type})" if isinstance(error_type, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,60}", error_type) else ""
        return f"{channel} Event Log provider unavailable{error_text}", None

    if event_type == "diagnostic.video_finding":
        cause = data.get("cause")
        cause = cause if isinstance(cause, str) and re.fullmatch(r"[a-z0-9_]{1,80}", cause) else "video_diagnostic"
        severity = data.get("severity")
        severity = severity.upper() if isinstance(severity, str) and severity.lower() in {"low", "medium", "high"} else "UNKNOWN"
        return f"Video diagnostic: {cause} ({severity})", None

    if event_type == "diagnostic.user_feedback":
        outcome = data.get("outcome")
        outcome = outcome if outcome in {"resolved", "not_resolved", "not_attempted"} else "recorded"
        return f"User feedback recorded: {outcome}", None

    safe_type = re.sub(r"[^A-Za-z0-9_. -]", "", event_type)[:80] or "event"
    return f"Observation: {safe_type}", None


def _to_signal(event: AIEEvent) -> tuple[ActivitySignal, str | None]:
    title, application = _signal_title(event)
    return ActivitySignal(
        event_id=event.event_id,
        timestamp=event.timestamp.astimezone(timezone.utc),
        kind=_kind(event.event_type),
        title=title[:180],
        source=event.source[:80],
        event_type=event.event_type[:100],
        confidence=event.confidence,
        evidence_kind=event.evidence_kind,
        sensitivity=event.sensitivity,
        correlation_id=event.correlation_id,
    ), application


def build_activity_timeline(
    events: list[AIEEvent] | tuple[AIEEvent, ...],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 86_400,
    session_gap_seconds: float = 300,
    max_sessions: int = 25,
    max_signals_per_session: int = 100,
    include_sensitive: bool = False,
) -> ActivityTimeline:
    """Cluster recent observations into host-local time sessions.

    Session grouping is purely temporal; it does not infer tasks, intent or causality.
    Sensitive raw payloads are never included in the result, even when their event
    metadata is allowed via include_sensitive=True.
    """
    if not 1 <= max_age_seconds <= 604_800:
        raise ValueError("max_age_seconds must be between 1 second and 7 days")
    if not 10 <= session_gap_seconds <= 3600:
        raise ValueError("session_gap_seconds must be between 10 seconds and 1 hour")
    if not 1 <= max_sessions <= 100:
        raise ValueError("max_sessions must be between 1 and 100")
    if not 1 <= max_signals_per_session <= 500:
        raise ValueError("max_signals_per_session must be between 1 and 500")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    cutoff = current - timedelta(seconds=max_age_seconds)

    accepted: list[AIEEvent] = []
    seen: set[str] = set()
    for event in events:
        if event.event_id in seen or event.timestamp.tzinfo is None:
            continue
        timestamp = event.timestamp.astimezone(timezone.utc)
        if timestamp < cutoff or timestamp > current:
            continue
        if event.sensitivity == "sensitive" and not include_sensitive:
            continue
        accepted.append(event)
        seen.add(event.event_id)

    accepted.sort(key=lambda item: (item.host_id, item.timestamp, item.event_id))
    grouped: list[list[AIEEvent]] = []
    for event in accepted:
        if (
            not grouped
            or grouped[-1][-1].host_id != event.host_id
            or (event.timestamp.astimezone(timezone.utc) - grouped[-1][-1].timestamp.astimezone(timezone.utc)).total_seconds() > session_gap_seconds
        ):
            grouped.append([event])
        else:
            grouped[-1].append(event)

    sessions: list[ActivitySession] = []
    for group in grouped:
        signals_and_apps = [_to_signal(event) for event in group]
        signals = tuple(item[0] for item in signals_and_apps[-max_signals_per_session:])
        applications = tuple(dict.fromkeys(
            item[1] for item in signals_and_apps if item[1] is not None
        ))
        kinds = tuple(dict.fromkeys(item.kind for item in signals))
        sessions.append(ActivitySession(
            session_id=f"activity-{group[0].event_id}",
            host_id=group[0].host_id,
            started_at=group[0].timestamp.astimezone(timezone.utc),
            ended_at=group[-1].timestamp.astimezone(timezone.utc),
            event_count=len(group),
            kinds=kinds,
            applications=applications,
            signals=signals,
        ))

    sessions.sort(key=lambda item: item.ended_at, reverse=True)
    sessions = sessions[:max_sessions]
    latest = sessions[0] if sessions else None
    active_id = None
    if latest is not None and (current - latest.ended_at).total_seconds() <= session_gap_seconds:
        active_id = latest.session_id

    return ActivityTimeline(
        generated_at=current,
        event_count=len(accepted),
        sessions=tuple(sessions),
        current_session_id=active_id,
    )
