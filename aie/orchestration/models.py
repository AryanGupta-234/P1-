"""Validated durable state for a bounded plan execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aie.planning.models import TaskPlan

TaskRunStatus = Literal[
    "queued", "running", "paused", "awaiting_approval",
    "awaiting_input", "completed", "failed", "cancelled",
]
StepRunStatus = Literal[
    "pending", "running", "awaiting_approval", "awaiting_input",
    "completed", "failed", "skipped",
]


class StepRun(BaseModel):
    """Local execution state for one declarative plan step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(min_length=1, max_length=40)
    status: StepRunStatus = "pending"
    attempts: int = Field(default=0, ge=0, le=100)
    summary: str | None = Field(default=None, max_length=1000)
    proposal_id: str | None = Field(default=None, max_length=80)
    verified: bool = False
    error_type: str | None = Field(default=None, max_length=120)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_wait_states(self) -> "StepRun":
        if self.status == "awaiting_approval" and not self.proposal_id:
            raise ValueError("awaiting_approval steps must retain a proposal_id")
        if self.verified and self.status != "completed":
            raise ValueError("only completed steps may be marked verified")
        for value in (self.started_at, self.completed_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("step timestamps must be timezone-aware")
        return self


class TaskRun(BaseModel):
    """Versioned snapshot of one task plan's lifecycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=80)
    plan: TaskPlan
    status: TaskRunStatus = "queued"
    steps: tuple[StepRun, ...]
    version: int = Field(default=1, ge=1)
    failure_type: str | None = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_step_alignment(self) -> "TaskRun":
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("task run timestamps must be timezone-aware")
        expected = tuple(step.step_id for step in self.plan.steps)
        actual = tuple(step.step_id for step in self.steps)
        if actual != expected:
            raise ValueError("task run step state must match the plan's step order exactly")
        if self.status == "completed" and any(
            step.status != "completed" for step in self.steps
        ):
            raise ValueError("completed task runs require every step to be completed")
        if self.status == "awaiting_approval" and not any(
            step.status == "awaiting_approval" for step in self.steps
        ):
            raise ValueError("awaiting_approval task runs require an approval-waiting step")
        if self.status == "awaiting_input" and not any(
            step.status == "awaiting_input" for step in self.steps
        ):
            raise ValueError("awaiting_input task runs require an input-waiting step")
        return self


def new_task_run(plan: TaskPlan) -> TaskRun:
    """Create a queued run with one pending state record per validated plan step."""

    now = datetime.now(timezone.utc)
    return TaskRun(
        plan=plan,
        steps=tuple(StepRun(step_id=step.step_id) for step in plan.steps),
        created_at=now,
        updated_at=now,
    )
