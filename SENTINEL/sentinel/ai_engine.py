"""AI orchestration and inference policy for SENTINEL.

Model transport stays in ai.py. This engine owns admission control, task routing,
gaming/latency safeguards, bounded prompt composition, and the reason for deferrals.
"""
from __future__ import annotations

import time
from typing import Any

from . import core, memory_engine, runtime_engine, safeguard


def inference_allowed(model: str, *, cloud: bool = False, pause_when_gaming: bool = True, slot: str = "fast") -> tuple[bool, str]:
    guard = safeguard.snapshot()
    runtime = runtime_engine.snapshot()
    memory = memory_engine.pressure()
    if not guard["process_detection_complete"]:
        return False, "game/process state is unknown; inference is paused until the process observer is healthy"
    if guard["valorant_active"]:
        return False, "all inference paused during VALORANT to preserve CPU/GPU/network headroom"
    if pause_when_gaming and runtime["game_active"]:
        return False, "all model inference paused during the active game session to preserve CPU/GPU/network headroom"
    if slot == "deep" and (not runtime["deep_ai_allowed"] or not memory["deep_inference_allowed"]):
        return False, "DEEP inference deferred by live CPU/RAM budget"
    if slot == "fast" and not runtime["fast_ai_allowed"]:
        return False, "FAST inference deferred by host resource pressure"
    return True, "admitted by live resource and game policy"


def triage_allowed() -> tuple[bool, str]:
    runtime = runtime_engine.snapshot()
    memory = memory_engine.pressure()
    if runtime["game_active"]:
        return False, "periodic local triage paused while a game is running"
    if not runtime["fast_ai_allowed"] or not memory["fast_inference_allowed"]:
        return False, "periodic triage deferred by resource pressure"
    return True, "periodic triage admitted"


def compose_context(payload: dict[str, Any], query: str = "", purpose: str = "triage") -> dict[str, Any]:
    return memory_engine.compose(payload, query=query, purpose=purpose)


def route(slot: str = "fast") -> dict[str, Any]:
    memory = memory_engine.status()
    runtime = runtime_engine.snapshot()
    slot_name = "deep" if slot == "deep" and runtime["deep_ai_allowed"] and memory["deep_inference_allowed"] else "fast"
    return {
        "requested_slot": slot,
        "selected_slot": slot_name,
        "reason": "live resource budget",
        "runtime_mode": runtime["mode"],
        "memory_pressure": memory["level"],
        "updated_at": time.time(),
    }


def status() -> dict[str, Any]:
    fast, fast_reason = triage_allowed()
    deep, deep_reason = inference_allowed("", slot="deep")
    return {
        "fast_triage_allowed": fast,
        "fast_triage_reason": fast_reason,
        "deep_allowed": deep,
        "deep_reason": deep_reason,
        "runtime": runtime_engine.snapshot(),
        "memory": memory_engine.status(),
        "safety": safeguard.snapshot(),
        "model_transport": "ai.py / Ollama or explicitly configured cloud provider",
        "authority": "AI proposes explanations; deterministic safeguards and action engine decide execution",
    }
