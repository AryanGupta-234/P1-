"""Operational event contract between the SENTI host and any presentation surface.

The host emits plain JSON-serialisable dicts through an ``EventSink`` callback. A UI (or a
log) subscribes; it never drives policy. Every event carries ``type``, ``ts`` (UTC ISO-8601)
and ``conversation_id`` when one is active.

Event types
-----------
``state``      ``{"state": <State>, "detail": str}`` - lifecycle of one request.
``thinking``   ``{"enabled": bool, "reason": str}`` - whether deliberate reasoning is on.
``tool``       ``{"tool": str, "phase": "proposed"|"simulated"|"executed", "status": str,
                 "summary": str, "risk": str}``.
``approval``   ``{"approval_id": str, "tool": str, "risk": str, "preview": dict,
                 "status": "pending"|"approved"|"denied"|"expired"}``.
``memory``     ``{"action": "recalled"|"learned"|"forgotten", "count": int, "summary": str}``.
``reply``      ``{"text": str, "model": str, "usage": dict}`` - the final answer.
``error``      ``{"message": str}``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Literal

State = Literal[
    "idle", "listening", "processing", "investigating", "planning",
    "awaiting_authorization", "executing", "verifying", "completed", "failed",
    "requires_attention",
]
STATES: tuple[str, ...] = (
    "idle", "listening", "processing", "investigating", "planning",
    "awaiting_authorization", "executing", "verifying", "completed", "failed",
    "requires_attention",
)

EventSink = Callable[[dict[str, Any]], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def make_event(event_type: str, conversation_id: str | None = None, **fields: Any) -> dict[str, Any]:
    if event_type == "state" and fields.get("state") not in STATES:
        raise ValueError(f"unknown SENTI state: {fields.get('state')!r}")
    return {"type": event_type, "ts": utc_now(), "conversation_id": conversation_id, **fields}


def emit(sink: EventSink | None, event_type: str, conversation_id: str | None = None,
         **fields: Any) -> None:
    """Deliver an event; a failing sink must never break the host."""
    if sink is None:
        return
    try:
        sink(make_event(event_type, conversation_id, **fields))
    except Exception:  # noqa: BLE001 - presentation failures are isolated from execution.
        pass
