"""Consent-gated export of anonymized video trace candidates for human labeling.

This module deliberately exports no raw event IDs, host IDs, timestamps, process names,
browser URLs, media URLs, window titles, page text, or probe destinations. Candidates
are not evaluation data until a reviewer assigns expected causes.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from aie.context.video import build_video_observation_context
from aie.contracts import AIEEvent

FIELD_CANDIDATE_KIND = "field_candidate"
MAX_FIELD_CANDIDATES = 200
METRIC_FIELDS = (
    "playback_stalled",
    "stall_count",
    "observation_window_seconds",
    "throughput_mbps",
    "estimated_required_mbps",
    "rtt_ms",
    "packet_loss_pct",
    "cpu_pct",
    "dropped_frames_pct",
    "buffered_ahead_seconds",
    "playback_progress_delta_seconds",
)


class FieldTraceExportError(ValueError):
    """Invalid export parameters or candidate selection."""


def _candidate_score(event: AIEEvent) -> tuple[int, float, int, datetime]:
    data = event.data
    stalls = data.get("stall_count", 0)
    if isinstance(stalls, bool) or not isinstance(stalls, int) or stalls < 0:
        stalls = 0
    window = data.get("observation_window_seconds", 0)
    if isinstance(window, bool) or not isinstance(window, (int, float)):
        window = 0.0
    metric_count = sum(
        data.get(field) is not None
        for field in (
            "buffered_ahead_seconds",
            "playback_progress_delta_seconds",
            "dropped_frames_pct",
            "throughput_mbps",
            "estimated_required_mbps",
            "packet_loss_pct",
        )
    )
    return stalls, float(window), metric_count, event.timestamp


def prepare_field_trace_candidates(
    events: list[AIEEvent] | tuple[AIEEvent, ...],
    *,
    now: datetime,
    limit: int = 100,
    max_age_seconds: float = 45.0,
) -> dict[str, Any]:
    """Create a non-evaluable candidate file for explicit human ground-truth labeling."""
    if now.tzinfo is None:
        raise FieldTraceExportError("now must be timezone-aware")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_FIELD_CANDIDATES:
        raise FieldTraceExportError(f"limit must be between 1 and {MAX_FIELD_CANDIDATES}")
    if (
        isinstance(max_age_seconds, bool)
        or not isinstance(max_age_seconds, (int, float))
        or not 1 <= max_age_seconds <= 300
    ):
        raise FieldTraceExportError("max_age_seconds must be between 1 and 300")

    latest_by_session: dict[tuple[str, str], AIEEvent] = {}
    for event in events:
        if (
            event.event_type != "browser.video.snapshot"
            or event.timestamp.tzinfo is None
            or event.timestamp > now
            or now - event.timestamp > timedelta(hours=24 * 30)
        ):
            continue
        session_id = event.entity.stable_id or event.event_id
        key = (event.host_id, session_id)
        previous = latest_by_session.get(key)
        if previous is None or _candidate_score(event) > _candidate_score(previous):
            latest_by_session[key] = event

    selected = sorted(
        latest_by_session.values(),
        key=lambda event: event.timestamp,
        reverse=True,
    )[:limit]

    cases: list[dict[str, Any]] = []
    for candidate in selected:
        # Anchor to the selected browser snapshot. Future observations are excluded;
        # nearby same-host measurements can be correlated within the short window.
        anchor_now = candidate.timestamp + timedelta(milliseconds=1)
        context = build_video_observation_context(
            events,
            now=anchor_now,
            max_age_seconds=max_age_seconds,
        )
        if context is None or context.observed_at != candidate.timestamp:
            continue
        metrics = {
            name: getattr(context.metrics, name)
            for name in METRIC_FIELDS
        }
        cases.append({
            "id": f"candidate-{len(cases) + 1:04d}",
            "metrics": metrics,
            "expected_causes": None,
            "label_status": "requires_human_review",
        })

    return {
        "schema_version": 1,
        "dataset_name": "video-field-trace-candidates",
        "dataset_kind": FIELD_CANDIDATE_KIND,
        "description": (
            "Anonymized local diagnostic candidates. This file is not accepted by "
            "aie video-evaluate until every expected_causes field is reviewed and "
            "dataset_kind is changed to field."
        ),
        "labeling_instructions": (
            "Review each case against the real playback outcome and independent evidence. "
            "Set expected_causes to a list of verified cause IDs, or an empty list only "
            "when evidence supports no diagnostic cause. Do not infer ground truth from "
            "the AIE prediction alone. Then change dataset_kind to field and run "
            "aie video-evaluate --dataset <PATH>."
        ),
        "case_count": len(cases),
        "cases": cases,
    }
