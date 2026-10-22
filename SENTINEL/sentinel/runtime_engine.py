"""Adaptive SENTINEL runtime policy.

This engine sheds SENTINEL's own workload before the monitored machine is affected.
It never changes Windows power plans, process priorities, CPU affinity, services, or
security settings. System telemetry keeps its normal cadence; expensive agent work slows.
"""
from __future__ import annotations

import time
from typing import Any

import psutil

from . import core, safeguard

_STARTED = False


def evaluate() -> dict[str, Any]:
    game = core.STATE.get("game") if isinstance(core.STATE.get("game"), dict) else None
    guard = safeguard.snapshot()
    vm = psutil.virtual_memory()
    available_gib = vm.available / (1024 ** 3)
    cpu = core.LIVE.get("cpu")
    cpu_value = float(cpu) if cpu is not None else 0.0
    valorant = bool(guard["valorant_active"])
    safety_ready = bool(guard["process_detection_complete"])
    playing = bool(game) or valorant
    pressure = available_gib < 1.8 or cpu_value >= 92.0
    if not safety_ready:
        mode = "safety_degraded"
    elif valorant:
        mode = "valorant_guarded"
    elif pressure:
        mode = "resource_pressure"
    elif playing:
        mode = "game_optimized"
    else:
        mode = "balanced"

    process_interval = 2.2 if valorant else 1.8 if playing else 1.6 if pressure else 1.0
    inventory_multiplier = 3.0 if valorant else 2.0 if playing or pressure else 1.0
    deep_allowed = safety_ready and not playing and available_gib >= 4.5 and cpu_value < 78.0
    fast_allowed = safety_ready and not valorant and available_gib >= 1.8 and cpu_value < 92.0
    return {
        "mode": mode,
        "valorant_active": valorant,
        "safety_ready": safety_ready,
        "game_active": playing,
        "cpu_percent": round(cpu_value, 1),
        "available_memory_gib": round(available_gib, 2),
        "memory_pressure": "high" if available_gib < 1.8 else "moderate" if available_gib < 3.5 else "normal",
        "process_scan_interval_s": process_interval,
        "inventory_interval_multiplier": inventory_multiplier,
        "fast_ai_allowed": fast_allowed,
        "deep_ai_allowed": deep_allowed,
        "wpr_allowed": bool(guard["kernel_trace_allowed"]),
        "auto_remediation": "internal-runtime-load-shedding-only",
        "system_mutations": "blocked during VALORANT; normal risk and approval policy otherwise",
        "changed_os_settings": False,
    }


def snapshot() -> dict[str, Any]:
    state = core.STATE.get("runtime_engine")
    if isinstance(state, dict) and time.time() - float(state.get("updated_at") or 0) < 5:
        return dict(state)
    return {**evaluate(), "updated_at": time.time()}


def process_scan_interval() -> float:
    return float(snapshot().get("process_scan_interval_s") or 1.0)


def inventory_delay(base_seconds: float) -> float:
    multiplier = float(snapshot().get("inventory_interval_multiplier") or 1.0)
    return max(5.0, float(base_seconds) * min(4.0, max(1.0, multiplier)))


def collector_interval(name: str, base_seconds: float) -> float:
    """Back off SENTINEL-owned expensive polls when games or resource pressure are detected."""
    mode = snapshot().get("mode")
    cadence = {
        "gpu": 6.0 if mode == "valorant_guarded" else 3.0 if mode in ("game_optimized", "resource_pressure") else float(base_seconds),
        "ping": 3.0 if mode == "valorant_guarded" else 2.0 if mode in ("game_optimized", "resource_pressure") else float(base_seconds),
        "network": 10.0 if mode == "valorant_guarded" else 7.0 if mode in ("game_optimized", "resource_pressure") else float(base_seconds),
    }
    return max(float(base_seconds), cadence.get(str(name), float(base_seconds)))


def loop() -> None:
    while True:
        state = evaluate()
        state["updated_at"] = time.time()
        core.STATE["runtime_engine"] = state
        core.heartbeat("adaptive runtime engine", 2, f"{state['mode']} · {state['available_memory_gib']:.1f} GiB available")
        time.sleep(2)


def start() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    core.thread(loop, "runtime-engine")
