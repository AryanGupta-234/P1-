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
]


def __getattr__(name: str):
    if name in {"ActivitySession", "ActivitySignal", "ActivityTimeline", "build_activity_timeline"}:
        module = import_module("aie.context.activity")
        return getattr(module, name)
    if name == "build_activity_prompt_context":
        module = import_module("aie.context.activity_context")
        return getattr(module, name)
    if name == "build_video_observation_context":
        module = import_module("aie.context.video")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
