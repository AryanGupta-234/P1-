"""Typed snapshots and bounded outcomes for durable task runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from aie.planning.models import TaskPlan

RunStatus = Literal[
    "ready", "running", "waiting_approval", "blocked",
    "completed", "failed", "cancelled",
]
StepStatus = Literal[
    "pending", "running", "waiting_approval", "authorized",
    "completed", "failed", "blocked", "cancelled",
]


@dataclass(frozen=True, slots=True)
class TaskStepRecord:
    step_id: str
    status: StepStatus
    attempts: int
    summary: str | None = None
    evidence_ids: tuple[str, ...] = ()
    proposal_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRun:
    run_id: str
    plan: TaskPlan
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    steps: tuple[TaskStepRecord, ...]
    cancel_requested: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """A small, auditable handler result; arbitrary tool payloads are not persisted."""

    success: bool
    summary: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("success must be a boolean")
        if not isinstance(self.summary, str) or not 1 <= len(self.summary.strip()) <= 500:
            raise ValueError("summary must contain 1-500 non-whitespace characters")
        if len(self.evidence_ids) > 20:
            raise ValueError("at most 20 evidence IDs may be attached to a step outcome")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence IDs must be unique")
        if any(not isinstance(item, str) or not 1 <= len(item) <= 120 for item in self.evidence_ids):
            raise ValueError("each evidence ID must contain 1-120 characters")
