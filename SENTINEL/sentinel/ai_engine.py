"""AI orchestration and inference policy for SENTINEL.

Model transport stays in ai.py. This engine owns admission control, task routing,
gaming/latency safeguards, bounded prompt composition, and the reason for deferrals.
"""
from __future__ import annotations

import json
import time
from collections import OrderedDict
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
        return False, ("cloud inference paused during the active game session"
                       if cloud else "local inference paused during the active game session")
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


_STARTED = False
_DEFERRED_LIMIT = 64
_COOLDOWN_SECONDS = 300
_TRIAGE_SECONDS = 60


def _remember_deferred(queue: OrderedDict, insight: dict) -> None:
    """Deduplicate and bound deferred model work while a game is active."""
    key = str(insight.get("key") or insight.get("id") or insight.get("title") or "")
    if not key:
        return
    queue.pop(key, None)
    queue[key] = dict(insight)
    while len(queue) > _DEFERRED_LIMIT:
        queue.popitem(last=False)


def _runtime_pause_reason() -> str:
    guard = safeguard.snapshot()
    if not guard["process_detection_complete"]:
        return "process observer unavailable; AI inference fail-closed"
    if guard["valorant_active"]:
        return "VALORANT detected; all AI inference paused"
    runtime = runtime_engine.snapshot()
    if runtime["game_active"] and bool(core.CFG.get("pause_ai_when_gaming", True)):
        return "game session active; AI inference paused to protect frame-time headroom"
    memory = memory_engine.pressure()
    if not memory["fast_inference_allowed"]:
        return f"AI inference deferred by {memory['level']} memory pressure"
    return ""


def loop() -> None:
    """Orchestrate FAST/DEEP work with strict admission, cooldown and bounded deferrals."""
    from . import ai as transport

    events = core.subscribe()
    last_triage = 0.0
    cooldown: dict[str, float] = {}
    deferred: OrderedDict[str, dict] = OrderedDict()
    last_model_refresh = 0.0

    while True:
        state = core.STATE.setdefault("ai", {})
        if not core.CFG.get("ai_enabled", True):
            state["status"] = "AI Orchestrator disabled in settings"
            state["scheduler"] = {"state": "disabled", "deferred": len(deferred)}
            core.heartbeat("AI Orchestrator", 15, "disabled in settings")
            time.sleep(5)
            continue

        pause_reason = _runtime_pause_reason()
        if pause_reason:
            state["status"] = pause_reason
            state["scheduler"] = {"state": "deferred", "reason": pause_reason, "deferred": len(deferred)}
            core.heartbeat("AI Orchestrator", 5, pause_reason)
            try:
                message = events.get(timeout=3)
                payload = json.loads(message)
                if payload.get("t") == "insight":
                    insight = payload.get("d") or {}
                    if insight.get("sev") in ("high", "warn"):
                        _remember_deferred(deferred, insight)
            except Exception:
                pass
            continue

        if not state.get("online") or not state.get("fast"):
            if time.time() - last_model_refresh >= 15:
                last_model_refresh = time.time()
                try:
                    available = transport.refresh_models()
                    if available:
                        core.log("ai", f"models ready · FAST={state.get('fast')} · DEEP={state.get('deep')}", "ok")
                    else:
                        core.heartbeat("AI Orchestrator", 15, "no model provider available")
                except Exception as exc:
                    state["online"] = False
                    core.log("ai", f"model discovery failed: {type(exc).__name__}: {str(exc)[:120]}", "warn")
            if not state.get("online"):
                time.sleep(2)
                continue

        try:
            message = events.get(timeout=2)
            payload = json.loads(message)
            if payload.get("t") == "insight":
                insight = payload.get("d") or {}
                severity = insight.get("sev")
                key = str(insight.get("key") or insight.get("id") or insight.get("title") or "")
                now = time.time()
                if severity in ("high", "warn") and key and now - cooldown.get(key, 0.0) >= _COOLDOWN_SECONDS:
                    cooldown[key] = now
                    allowed, reason = inference_allowed(state.get("deep") or state.get("fast") or "", cloud=str(state.get("deep") or "").startswith("☁ "), slot="deep")
                    if allowed and state.get("deep"):
                        transport.investigate(insight)
                    else:
                        _remember_deferred(deferred, insight)
                        state["scheduler"] = {"state": "deferred", "reason": reason, "deferred": len(deferred)}
        except Exception as exc:
            # Queue may be empty, malformed, or an insight may be temporarily inadmissible.
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise

        if deferred and state.get("deep"):
            allowed, reason = inference_allowed(
                state.get("deep") or state.get("fast") or "",
                cloud=str(state.get("deep") or "").startswith("☁ "),
                slot="deep",
            )
            if allowed:
                count = min(3, len(deferred))
                for _ in range(count):
                    _key, insight = deferred.popitem(last=False)
                    try:
                        transport.investigate(insight)
                    except Exception as exc:
                        _remember_deferred(deferred, insight)
                        core.log("ai", f"deferred investigation paused: {type(exc).__name__}: {str(exc)[:100]}", "warn")
                        break
            else:
                state["scheduler"] = {"state": "deferred", "reason": reason, "deferred": len(deferred)}

        now = time.time()
        triage, triage_reason = triage_allowed()
        if now - last_triage >= _TRIAGE_SECONDS and state.get("fast") and triage:
            allowed, reason = inference_allowed(
                state["fast"], cloud=str(state["fast"]).startswith("☁ "), slot="fast"
            )
            if allowed:
                last_triage = now
                try:
                    output = transport.gen(
                        state["fast"],
                        "Telemetry: " + json.dumps(transport.snapshot(), default=str)[:3500],
                        transport.SYS_FAST,
                        timeout=60,
                        slot="fast",
                    )
                    state["status"] = output
                    core.publish("ai_status", {"text": output, "ts": now})
                    core.heartbeat("AI Orchestrator", 60, f"FAST={state['fast']} · DEEP={state.get('deep') or 'not selected'}")
                except Exception as exc:
                    state["online"] = False if "connect" in str(exc).casefold() else state.get("online", False)
                    core.log("ai", f"FAST triage failed: {type(exc).__name__}: {str(exc)[:140]}", "warn")
            else:
                state["scheduler"] = {"state": "deferred", "reason": reason, "deferred": len(deferred)}
        elif not triage:
            state["scheduler"] = {"state": "idle", "reason": triage_reason, "deferred": len(deferred)}

        # Bound stale cooldown keys over long agent lifetimes.
        if len(cooldown) > 512:
            cutoff = time.time() - _COOLDOWN_SECONDS * 2
            cooldown = {key: stamp for key, stamp in cooldown.items() if stamp >= cutoff}
        state.setdefault("scheduler", {}).update({
            "state": state.get("scheduler", {}).get("state", "ready"),
            "deferred": len(deferred),
            "deferred_limit": _DEFERRED_LIMIT,
            "last_triage_at": last_triage or None,
            "cooldown_keys": len(cooldown),
        })


def start() -> None:
    """Start the AI incubation/orchestration loop once."""
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    core.thread(loop, "ai-incubator")
