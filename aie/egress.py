"""Central remote-model egress gate with metadata-only local auditing."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aie.models.base import ChatMessage, ModelRequest

_MAX_TOTAL_CHARS = 30_000
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]{8,}"
    ),
)


class RemoteEgressDenied(RuntimeError):
    """Raised when a remote model request fails the explicit egress policy."""


@dataclass(frozen=True, slots=True)
class RemoteEgressContext:
    channel: str
    allow_egress: bool
    activity_attached: bool = False
    memory_attached: bool = False
    session_attached: bool = False
    confirm_activity: bool = False
    confirm_memory: bool = False
    confirm_session: bool = False
    sensitive_memory: bool = False


@dataclass(frozen=True, slots=True)
class RemoteEgressDecision:
    request_id: str
    request: ModelRequest
    channel: str
    redactions: int
    characters_before: int
    characters_after: int


class RemoteEgressAuditStore:
    """Metadata-only audit ledger; never stores prompt or response contents."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS egress_audit (
                    request_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    message_count INTEGER NOT NULL,
                    characters_before INTEGER NOT NULL,
                    characters_after INTEGER NOT NULL,
                    redactions INTEGER NOT NULL,
                    activity_attached INTEGER NOT NULL,
                    memory_attached INTEGER NOT NULL,
                    session_attached INTEGER NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_egress_audit_timestamp "
                "ON egress_audit(timestamp)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def record(
        self,
        *,
        request_id: str,
        channel: str,
        outcome: str,
        message_count: int,
        characters_before: int,
        characters_after: int,
        redactions: int,
        activity_attached: bool,
        memory_attached: bool,
        session_attached: bool,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO egress_audit
                (request_id,timestamp,channel,outcome,message_count,
                 characters_before,characters_after,redactions,
                 activity_attached,memory_attached,session_attached)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    request_id,
                    datetime.now(timezone.utc).isoformat(),
                    channel,
                    outcome,
                    message_count,
                    characters_before,
                    characters_after,
                    redactions,
                    int(activity_attached),
                    int(memory_attached),
                    int(session_attached),
                ),
            )


def _redact(text: str) -> tuple[str, int]:
    redactions = 0
    sanitized = text
    for pattern in _SECRET_PATTERNS:
        sanitized, count = pattern.subn("[REDACTED]", sanitized)
        redactions += count
    return sanitized, redactions


class RemoteEgressGateway:
    """Authorize, sanitize and audit one remote model request."""

    def __init__(self, audit_store: RemoteEgressAuditStore) -> None:
        self.audit_store = audit_store

    def prepare(
        self,
        request: ModelRequest,
        context: RemoteEgressContext,
    ) -> RemoteEgressDecision:
        request_id = f"egress-{uuid4()}"
        try:
            self._validate_context(context)
            characters_before = sum(len(message.content) for message in request.messages)
            if characters_before > _MAX_TOTAL_CHARS:
                raise RemoteEgressDenied(
                    f"Remote request exceeds the {_MAX_TOTAL_CHARS} character payload budget."
                )

            messages: list[ChatMessage] = []
            total_after = 0
            redactions = 0
            for message in request.messages:
                content, count = _redact(message.content)
                messages.append(ChatMessage(role=message.role, content=content))
                total_after += len(content)
                redactions += count

            prepared = request.model_copy(update={"messages": messages})
            self.audit_store.record(
                request_id=request_id,
                channel=context.channel,
                outcome="allowed",
                message_count=len(messages),
                characters_before=characters_before,
                characters_after=total_after,
                redactions=redactions,
                activity_attached=context.activity_attached,
                memory_attached=context.memory_attached,
                session_attached=context.session_attached,
            )
            return RemoteEgressDecision(
                request_id=request_id,
                request=prepared,
                channel=context.channel,
                redactions=redactions,
                characters_before=characters_before,
                characters_after=total_after,
            )
        except RemoteEgressDenied:
            self.audit_store.record(
                request_id=request_id,
                channel=context.channel,
                outcome="denied",
                message_count=len(request.messages),
                characters_before=sum(len(message.content) for message in request.messages),
                characters_after=0,
                redactions=0,
                activity_attached=context.activity_attached,
                memory_attached=context.memory_attached,
                session_attached=context.session_attached,
            )
            raise

    @staticmethod
    def _validate_context(context: RemoteEgressContext) -> None:
        if context.channel not in {"cloud", "remote_ollama"}:
            raise RemoteEgressDenied("Unknown remote egress channel.")
        if not context.allow_egress:
            raise RemoteEgressDenied(
                "Remote model egress is disabled. Explicitly authorize this request."
            )
        if context.activity_attached and not context.confirm_activity:
            raise RemoteEgressDenied(
                "Activity context requires explicit remote-egress confirmation."
            )
        if context.memory_attached and not context.confirm_memory:
            raise RemoteEgressDenied(
                "Memory context requires explicit remote-egress confirmation."
            )
        if context.session_attached and not context.confirm_session:
            raise RemoteEgressDenied(
                "Session context requires explicit remote-egress confirmation."
            )
        if context.sensitive_memory:
            raise RemoteEgressDenied(
                "Sensitive memory is never permitted in a remote model request."
            )
