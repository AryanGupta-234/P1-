"""Explicit user-controlled working session contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class TaskSession:
    session_id: str
    label: str
    started_at: datetime
    ended_at: datetime | None
    status: str

    @property
    def active(self) -> bool:
        return self.status == "active" and self.ended_at is None


def new_task_session(label: str, *, now: datetime) -> TaskSession:
    cleaned = " ".join(label.split())
    if not 1 <= len(cleaned) <= 120:
        raise ValueError("session label must be between 1 and 120 characters")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return TaskSession(
        session_id=str(uuid4()),
        label=cleaned,
        started_at=now,
        ended_at=None,
        status="active",
    )
