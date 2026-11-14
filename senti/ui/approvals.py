"""Thread-safe bridge between the host's blocking approval callback and the console UI.

The host calls :meth:`ApprovalBroker.handler` from its worker thread. The broker records a
pending item, announces it through the event sink and blocks that worker until the operator
decides in the UI or the timeout passes. An expired request is a denial. Each item can be
decided exactly once.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from senti.events import EventSink, make_event

DEFAULT_TIMEOUT_SECONDS = 120.0
_HISTORY_LIMIT = 200


class ApprovalError(Exception):
    """Base class for operator decision errors."""


class UnknownApproval(ApprovalError):
    """No approval with that id exists."""


class ApprovalAlreadyDecided(ApprovalError):
    """The approval was already approved, denied or expired."""

    def __init__(self, status: str):
        super().__init__(f"approval already {status}")
        self.status = status


def _json_safe(value: Any, *, limit: int = 16_000) -> Any:
    """Return a JSON-serialisable, size-bounded copy of ``value`` for the UI."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
    except (TypeError, ValueError):
        encoded = json.dumps(str(value), ensure_ascii=False)
    if len(encoded) > limit:
        return {"truncated": True, "text": encoded[:limit]}
    return json.loads(encoded)


class _Pending:
    __slots__ = (
        "approval_id",
        "arguments",
        "conversation_id",
        "created",
        "deadline",
        "decided",
        "expires_at",
        "preview",
        "reason",
        "risk",
        "status",
        "tool",
    )

    def __init__(self, approval_id: str, tool: str, arguments: Any, risk: str, preview: Any,
                 timeout: float, now: float, conversation_id: str | None):
        self.approval_id = approval_id
        self.tool = tool
        self.arguments = arguments
        self.risk = risk
        self.preview = preview
        self.status = "pending"
        self.created = now
        self.deadline = now + timeout
        self.expires_at = (datetime.now(UTC) + timedelta(seconds=timeout)).isoformat(
            timespec="milliseconds")
        self.decided = threading.Event()
        self.conversation_id = conversation_id
        self.reason = ""


class ApprovalBroker:
    """Queue of pending operator authorisations; safe to use from many threads."""

    def __init__(self, event_sink: EventSink | None = None, *,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.event_sink = event_sink
        self.timeout = float(timeout)
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, _Pending] = {}
        self._order: list[str] = []
        self.conversation_id: str | None = None

    # -- host side -------------------------------------------------------------------------
    def handler(self, tool_name: str, arguments: dict[str, Any], risk: str,
                preview: dict[str, Any] | None = None) -> bool:
        """Approval callback for the host. Blocks until decided; ``True`` only on approval."""
        item = _Pending(uuid4().hex, str(tool_name)[:100], _json_safe(arguments), str(risk)[:40],
                        _json_safe(preview or {}), self.timeout, self._clock(),
                        self.conversation_id)
        with self._lock:
            self._items[item.approval_id] = item
            self._order.append(item.approval_id)
            self._trim_locked()
        self._emit(item)
        while not item.decided.is_set():
            remaining = item.deadline - self._clock()
            if remaining <= 0:
                break
            item.decided.wait(min(remaining, 0.5))
        expired = False
        with self._lock:
            if item.status == "pending":
                item.status = "expired"
                item.reason = "timeout"
                item.decided.set()
                expired = True
            approved = item.status == "approved"
        if expired:
            self._emit(item)
        return approved

    # -- UI side ---------------------------------------------------------------------------
    def decide(self, approval_id: str, decision: str, *, reason: str = "operator") -> dict[str, Any]:
        if decision not in {"approve", "deny"}:
            raise ValueError("decision must be 'approve' or 'deny'")
        with self._lock:
            item = self._items.get(approval_id)
            if item is None:
                raise UnknownApproval(approval_id)
            if item.status != "pending":
                raise ApprovalAlreadyDecided(item.status)
            if self._clock() >= item.deadline:
                item.status = "expired"
                item.reason = "timeout"
            else:
                item.status = "approved" if decision == "approve" else "denied"
                item.reason = reason[:80]
            item.decided.set()
            snapshot = self._public(item)
        self._emit(item)
        if snapshot["status"] == "expired":
            raise ApprovalAlreadyDecided("expired")
        return snapshot

    def deny_all(self, reason: str = "emergency_stop") -> int:
        """Deny every pending item (used when the emergency stop engages)."""
        with self._lock:
            items = [item for item in self._items.values() if item.status == "pending"]
            for item in items:
                item.status = "denied"
                item.reason = reason[:80]
                item.decided.set()
        for item in items:
            self._emit(item)
        return len(items)

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public(self._items[i]) for i in self._order
                    if self._items[i].status == "pending"]

    def get(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(approval_id)
            return self._public(item) if item else None

    # -- internals -------------------------------------------------------------------------
    def _public(self, item: _Pending) -> dict[str, Any]:
        remaining = max(0.0, item.deadline - self._clock()) if item.status == "pending" else 0.0
        return {
            "approval_id": item.approval_id, "tool": item.tool, "risk": item.risk,
            "arguments": item.arguments, "preview": item.preview, "status": item.status,
            "reason": item.reason, "expires_at": item.expires_at,
            "expires_in": round(remaining, 1), "timeout_seconds": self.timeout,
        }

    def _emit(self, item: _Pending) -> None:
        if self.event_sink is None:
            return
        with self._lock:
            fields = self._public(item)
        # Presentation failures never affect the decision.
        with contextlib.suppress(Exception):
            self.event_sink(make_event("approval", item.conversation_id, **fields))

    def _trim_locked(self) -> None:
        while len(self._order) > _HISTORY_LIMIT:
            for index, key in enumerate(self._order):
                if self._items[key].status != "pending":
                    del self._order[index]
                    del self._items[key]
                    break
            else:
                return
