"""Privacy-safe, read-only video intelligence dashboard snapshot builder."""
from __future__ import annotations

from collections import Counter
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from aie.context.video import build_video_observation_context
from aie.diagnostics.video_buffering import diagnose_video_buffering
from aie.learning.analytics import summarize_feedback
from aie.model_policy import choose_local_model
from aie.models.ollama import OllamaClient, OllamaError
from aie.hardware import runtime_profile
from aie.store import EventStore


def _number(value: Any, digits: int = 2) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return round(number, digits) if math.isfinite(number) else None


def _safe_event(event) -> dict[str, Any]:
    """Expose only reviewed event metadata; never return raw event payloads."""
    data = event.data if isinstance(event.data, dict) else {}
    item: dict[str, Any] = {
        "id": event.event_id,
        "timestamp": event.timestamp.isoformat(),
        "type": event.event_type,
        "source": event.source,
        "entity": event.entity.type,
        "sensitivity": event.sensitivity,
        "evidence_kind": event.evidence_kind,
    }
    if event.event_type == "browser.video.snapshot":
        item["entity"] = "video_playback"
        item.update({
            "playback_state": data.get("playback_state"),
            "stall_count": data.get("stall_count"),
            "buffered_ahead_seconds": _number(data.get("buffered_ahead_seconds")),
            "progress_delta_seconds": _number(data.get("playback_progress_delta_seconds")),
            "dropped_frames_pct": _number(data.get("dropped_frames_pct")),
        })
    elif event.event_type == "diagnostic.video_finding":
        item["entity"] = data.get("cause", "diagnostic_finding")
        item.update({
            "cause": data.get("cause"),
            "severity": data.get("severity"),
            "confidence": _number(data.get("confidence"), 3),
            "recommendation": data.get("recommendation"),
            "evidence": list(data.get("evidence", []))[:12],
            "evidence_event_ids": list(data.get("evidence_event_ids", []))[:20],
            "action_executed": data.get("action_executed") is True,
        })
    elif event.event_type == "diagnostic.user_feedback":
        item.update({
            "cause": data.get("cause"),
            "outcome": data.get("outcome"),
            "target_event_id": data.get("target_event_id"),
        })
    elif event.event_type == "network.video_probe":
        item["entity"] = "user_selected_diagnostic_targets"
        item.update({
            "packet_loss_by_target": [
                {
                    "label": row.get("label"),
                    "sent": row.get("packets_sent"),
                    "received": row.get("packets_received"),
                    "loss_pct": _number(row.get("packet_loss_pct")),
                }
                for row in (data.get("packet_loss_by_target", [])[:2]
                            if isinstance(data.get("packet_loss_by_target", []), list) else [])
                if isinstance(row, dict)
            ],
            "throughput_mbps": _number(data.get("throughput_mbps"), 3),
            "samples_completed": data.get("throughput_samples_completed"),
            "action_executed": data.get("action_executed") is True,
        })
    elif event.event_type == "window.foreground_changed":
        item["entity"] = "foreground_application"
        item.update({
            "process_name": data.get("process_name"),
            "pid": data.get("pid"),
            "window_title_collected": data.get("window_title_collected") is True,
        })
    elif event.event_type == "process.foreground_resource_sample":
        item["entity"] = "foreground_process_resource_sample"
        item.update({
            "process_name": data.get("process_name"),
            "pid": data.get("pid"),
            "cpu_pct": _number(data.get("cpu_pct"), 1),
            "memory_rss_bytes": data.get("memory_rss_bytes"),
            "thread_count": data.get("thread_count"),
        })
    elif event.event_type == "observer.health":
        item["entity"] = "observer_provider_health"
        providers = data.get("providers", {})
        item["providers"] = {
            str(name): {
                "state": value.get("state"),
                "samples_attempted": value.get("samples_attempted"),
                "errors": value.get("errors"),
                "events_emitted": value.get("events_emitted"),
                "event_loss": value.get("event_loss"),
                "average_latency_ms": _number(value.get("average_latency_ms"), 2),
            }
            for name, value in providers.items()
            if isinstance(value, dict)
        } if isinstance(providers, dict) else {}
    return item


def build_video_dashboard_snapshot(
    store: EventStore,
    *,
    now: datetime | None = None,
    lookback_hours: int = 24,
    event_limit: int = 500,
) -> dict[str, Any]:
    """Build a bounded dashboard view without exposing raw or sensitive event payloads."""
    if not 1 <= lookback_hours <= 720:
        raise ValueError("lookback_hours must be between 1 and 720")
    if not 1 <= event_limit <= 1000:
        raise ValueError("event_limit must be between 1 and 1000")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    since = current - timedelta(hours=lookback_hours)
    events = store.query_events(since=since, until=current, limit=event_limit)
    newest_first = events
    counts = Counter(event.event_type for event in events)
    browser_events = [event for event in events if event.event_type == "browser.video.snapshot"]
    finding_events = [event for event in events if event.event_type == "diagnostic.video_finding"]
    feedback_events = [event for event in events if event.event_type == "diagnostic.user_feedback"]
    probe_events = [event for event in events if event.event_type == "network.video_probe"]
    context = build_video_observation_context(
        events,
        now=current,
        max_age_seconds=300.0,
    )
    diagnosis = diagnose_video_buffering(context.metrics) if context else None

    feedback_by_target: dict[str, str] = {}
    for feedback_event in feedback_events:
        target_id = feedback_event.data.get("target_event_id")
        outcome = feedback_event.data.get("outcome")
        if isinstance(target_id, str) and isinstance(outcome, str):
            feedback_by_target.setdefault(target_id, outcome)
    findings = []
    for event in finding_events[:100]:
        data = event.data
        findings.append({
            "id": event.event_id,
            "timestamp": event.timestamp.isoformat(),
            "cause": data.get("cause", event.entity.name),
            "severity": data.get("severity", "unknown"),
            "confidence": _number(data.get("confidence"), 3),
            "recommendation": data.get("recommendation", "Review the supporting evidence."),
            "evidence": list(data.get("evidence", []))[:12],
            "evidence_event_ids": list(data.get("evidence_event_ids", []))[:20],
            "feedback": feedback_by_target.get(event.event_id, "not_recorded"),
            "action_executed": data.get("action_executed") is True,
        })

    live = None
    if context is not None:
        metrics = context.metrics
        app = context.active_application
        live = {
            "playback_state": context.playback_state,
            "observed_at": context.observed_at.isoformat(),
            "age_seconds": round(max(0.0, (current - context.observed_at).total_seconds()), 1),
            "stall_count": metrics.stall_count,
            "observation_window_seconds": _number(metrics.observation_window_seconds, 1),
            "buffered_ahead_seconds": _number(context.buffered_ahead_seconds),
            "playback_progress_delta_seconds": _number(context.playback_progress_delta_seconds),
            "dropped_frames_pct": _number(metrics.dropped_frames_pct),
            "throughput_mbps": _number(metrics.throughput_mbps, 3),
            "estimated_required_mbps": _number(metrics.estimated_required_mbps, 3),
            "packet_loss_pct": _number(metrics.packet_loss_pct),
            "packet_loss_scope": metrics.packet_loss_scope,
            "cpu_pct": _number(metrics.cpu_pct, 1),
            "active_application": None if app is None else {
                "process_name": app.process_name,
                "pid": app.pid,
                "cpu_pct": _number(app.cpu_pct, 1),
                "memory_rss_mib": (
                    None if app.memory_rss_bytes is None
                    else round(app.memory_rss_bytes / (1024 ** 2), 1)
                ),
                "thread_count": app.thread_count,
                "age_seconds": round(app.age_seconds, 1),
                "window_title_collected": app.window_title_collected,
            },
            "network_evidence": [
                {
                    "kind": item.kind,
                    "age_seconds": round(item.age_seconds, 1),
                    "connect_latency_ms": _number(item.connect_latency_ms, 1),
                    "resolution_ms": _number(item.resolution_ms, 1),
                    "resolved": item.resolved,
                    "throughput_mbps": _number(item.throughput_mbps, 3),
                    "packet_loss_pct": _number(item.packet_loss_pct),
                    "packet_loss_by_target": [
                        {"label": row[0], "loss_pct": row[1], "sent": row[2], "received": row[3]}
                        for row in item.packet_loss_by_target
                    ],
                }
                for item in context.network_evidence
            ],
            "evidence_event_ids": list(context.evidence_event_ids),
        }

    live_findings = []
    if diagnosis is not None:
        live_findings = [
            {
                "cause": item.cause,
                "severity": item.severity,
                "confidence": item.confidence,
                "recommendation": item.recommendation,
                "evidence": list(item.evidence),
            }
            for item in diagnosis.findings
        ]

    feedback_summary = [
        {
            "cause": item.cause,
            "resolved": item.resolved,
            "not_resolved": item.not_resolved,
            "not_attempted": item.not_attempted,
            "resolution_rate": item.resolution_rate,
        }
        for item in summarize_feedback(feedback_events)
    ]
    try:
        models = OllamaClient(default_timeout=2.0).list_models(timeout=2.0)
        model_discovery_error = None
    except (OllamaError, ValueError) as exc:
        models = []
        model_discovery_error = str(exc)
    profile = runtime_profile()
    routine = choose_local_model("routine", models, profile["memory_available_gib"])
    complex_model = choose_local_model("complex", models, profile["memory_available_gib"])
    embedding = choose_local_model("embedding", models, profile["memory_available_gib"])

    return {
        "schema_version": 1,
        "generated_at": current.isoformat(),
        "lookback_hours": lookback_hours,
        "overview": {
            "total_events_in_window": len(events),
            "total_events_in_store": store.count(),
            "playback_snapshots": len(browser_events),
            "diagnostic_findings": len(finding_events),
            "network_probes": len(probe_events),
            "user_feedback_records": len(feedback_events),
            "latest_playback_at": browser_events[0].timestamp.isoformat() if browser_events else None,
            "event_types": [{"type": name, "count": count} for name, count in counts.most_common()],
        },
        "live_context": live,
        "live_hypotheses": live_findings,
        "findings": findings,
        "feedback_summary": feedback_summary,
        "probes": [_safe_event(event) for event in probe_events[:50]],
        "events": [_safe_event(event) for event in newest_first[:event_limit]],
        "models": {
            "installed": models,
            "discovery_error": model_discovery_error,
            "routine": {"model": routine.selected_model, "available": routine.available, "reason": routine.reason},
            "complex": {"model": complex_model.selected_model, "available": complex_model.available, "reason": complex_model.reason},
            "embedding": {"model": embedding.selected_model, "available": embedding.available, "reason": embedding.reason},
            "memory_available_gib": profile["memory_available_gib"],
            "cpu_logical": profile.get("cpu_logical"),
            "cpu_physical": profile.get("cpu_physical"),
        },
        "disclaimer": (
            "Heuristic hypotheses are not calibrated probabilities. "
            "Unknown measurements remain unknown; recommendations never execute automatically."
        ),
    }
