"""Deterministic diagnostic APIs, loaded lazily to avoid context import cycles."""
from __future__ import annotations

from importlib import import_module

__all__ = [
    "DiagnosticFinding",
    "DiagnosticReport",
    "VideoDiagnosticMonitor",
    "VideoMetrics",
    "diagnose_video_buffering",
]


def __getattr__(name: str):
    if name == "VideoDiagnosticMonitor":
        module = import_module("aie.diagnostics.monitor")
    elif name in {"DiagnosticFinding", "DiagnosticReport", "VideoMetrics", "diagnose_video_buffering"}:
        module = import_module("aie.diagnostics.video_buffering")
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(module, name)
