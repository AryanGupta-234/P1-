"""Temporal and activity context projections, loaded lazily to avoid import cycles."""
from __future__ import annotations

from importlib import import_module

__all__ = [
    "ActivitySession",
    "ActivitySignal",
    "ActivityTimeline",
    "build_activity_timeline",
    "build_activity_prompt_context",
    "build_video_observation_context",
    "EvidenceAssessment",
    "EvidenceContradiction",
    "assess_evidence",
    "find_explicit_contradictions",
    "TaskSession",
    "TaskSessionStore",
    "new_task_session",
    "TaskSessionPromptContext",
    "build_task_session_prompt_context",
    "CorrelationRule",
    "CorrelatedEvidence",
    "correlate_events",
]


def __getattr__(name: str):
    if name in {"ActivitySession", "ActivitySignal", "ActivityTimeline", "build_activity_timeline"}:
        module = import_module("aie.context.activity")
        return getattr(module, name)
    if name == "build_activity_prompt_context":
        module = import_module("aie.context.activity_context")
        return getattr(module, name)
    if name in {"EvidenceAssessment", "EvidenceContradiction", "assess_evidence", "find_explicit_contradictions"}:
        module = import_module("aie.context.evidence")
        return getattr(module, name)
    if name in {"TaskSession", "TaskSessionStore", "new_task_session"}:
        module = import_module("aie.context.task_session")
        return getattr(module, name)
    if name in {"TaskSessionPromptContext", "build_task_session_prompt_context"}:
        module = import_module("aie.context.task_session.context")
        return getattr(module, name)
    if name in {"CorrelationRule", "CorrelatedEvidence", "correlate_events"}:
        module = import_module("aie.context.temporal")
        return getattr(module, name)
    if name == "build_video_observation_context":
        module = import_module("aie.context.video")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
