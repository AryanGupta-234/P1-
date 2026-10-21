"""Unified bounded working-memory coordinator for SENTINEL's AI subsystems.

Durable user memories remain in the existing SQLite intelligence store. This engine
coordinates retrieval, prompt budgets, short-lived recall caching and memory-pressure
backoff so collectors and local inference do not compete for scarce RAM.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any

import psutil

from . import core

_LOCK = threading.RLock()
_CACHE: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
_CACHE_LIMIT = 64
_CACHE_TTL = 90.0
_STARTED = False


def pressure() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    available = max(0, int(vm.available))
    gib = available / (1024 ** 3)
    level = "critical" if gib < 0.9 else "high" if gib < 1.8 else "moderate" if gib < 3.5 else "normal"
    return {
        "level": level,
        "available_bytes": available,
        "available_gib": round(gib, 2),
        "used_percent": round(float(vm.percent), 1),
        "deep_inference_allowed": level == "normal" and gib >= 4.5,
        "fast_inference_allowed": level not in ("critical", "high"),
    }


def budgets() -> dict[str, Any]:
    state = pressure()
    if state["level"] == "critical":
        return {"triage_chars": 900, "investigation_chars": 0, "memory_results": 0, "process_rows": 2, "deep_allowed": False}
    if state["level"] == "high":
        return {"triage_chars": 1600, "investigation_chars": 0, "memory_results": 2, "process_rows": 3, "deep_allowed": False}
    if state["level"] == "moderate":
        return {"triage_chars": 2600, "investigation_chars": 4200, "memory_results": 4, "process_rows": 4, "deep_allowed": False}
    return {"triage_chars": 4200, "investigation_chars": 7600, "memory_results": 8, "process_rows": 6, "deep_allowed": True}


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.strip().casefold().encode("utf-8", errors="replace")).hexdigest()


def relevant_memories(query: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Retrieve non-sensitive durable memories and cache only the bounded result."""
    q = str(query or "").strip()[:600]
    if not q:
        return []
    cap = budgets()["memory_results"] if limit is None else max(0, min(12, int(limit)))
    if cap <= 0:
        return []
    key = _cache_key(q + "|" + str(cap))
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] <= _CACHE_TTL:
            _CACHE.move_to_end(key)
            return list(cached[1])
        _CACHE.pop(key, None)
    try:
        from . import intelligence
        rows = intelligence.STORE.memory_search(q, include_sensitive=False, limit=cap)
        safe_rows = []
        for item in rows if isinstance(rows, list) else []:
            if not isinstance(item, dict):
                continue
            safe_rows.append({
                "id": str(item.get("id") or ""),
                "kind": str(item.get("kind") or ""),
                "content": str(item.get("content") or "")[:700],
                "verification": str(item.get("verification") or "unknown"),
                "confidence": item.get("confidence"),
                "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
            })
        result = safe_rows[:cap]
    except Exception:
        result = []
    with _LOCK:
        _CACHE[key] = (now, result)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return list(result)


def compact(payload: Any, purpose: str = "triage") -> dict[str, Any]:
    """Bound serialized context and remove high-cost fields under memory pressure."""
    limit = budgets()["triage_chars"] if purpose == "triage" else budgets()["investigation_chars"]
    if limit <= 0:
        return {"context_deferred": "memory pressure", "memory_pressure": pressure()["level"]}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    result = dict(payload)
    if isinstance(result.get("top_processes"), list):
        result["top_processes"] = result["top_processes"][:budgets()["process_rows"]]
    for key in ("recent_etw_events", "thermal_events", "session_reports"):
        if isinstance(result.get(key), list):
            result[key] = result[key][:3]
    if isinstance(result.get("live"), dict):
        result["live"] = {k: v for k, v in result["live"].items() if v is not None}
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    while len(encoded) > limit and isinstance(result.get("top_processes"), list) and result["top_processes"]:
        result["top_processes"].pop()
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(encoded) > limit:
        encoded = encoded[:limit]
        return {"context_truncated": True, "memory_pressure": pressure()["level"], "payload_excerpt": encoded}
    result["memory_pressure"] = pressure()["level"]
    return result


def compose(payload: dict[str, Any], query: str = "", purpose: str = "triage") -> dict[str, Any]:
    """Attach relevant explicit memory, then apply the active context budget."""
    result = dict(payload)
    if query and budgets()["memory_results"]:
        result["relevant_user_memory"] = relevant_memories(query)
    return compact(result, purpose)


def clear_working_cache() -> dict[str, int]:
    """Clear only the in-memory retrieval cache; durable user memories are untouched."""
    with _LOCK:
        count = len(_CACHE)
        _CACHE.clear()
    return {"cleared": count, "persistent_memory_changed": 0}


def status() -> dict[str, Any]:
    with _LOCK:
        cache_size = len(_CACHE)
    return {**pressure(), "budgets": budgets(), "cache_entries": cache_size,
            "durable_store": "existing SQLite intelligence memory store",
            "working_store": "bounded process-local LRU; 64 entries; 90 second TTL"}


def loop() -> None:
    while True:
        now = time.monotonic()
        with _LOCK:
            expired = [key for key, (stamp, _) in _CACHE.items() if now - stamp > _CACHE_TTL]
            for key in expired:
                _CACHE.pop(key, None)
        state = status()
        core.STATE["memory_engine"] = state
        core.heartbeat("unified memory engine", 5, f"{state['level']} pressure · {state['cache_entries']} cached retrieval(s)")
        time.sleep(5)


def start() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    core.thread(loop, "memory-engine")
