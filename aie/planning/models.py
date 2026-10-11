"""Validated declarative task-plan contracts.

Plans describe work. They are not executable instructions and cannot grant capabilities.
Action-related steps may name a capability ID for later policy review, but they cannot
carry shell commands, executable paths, arbitrary tool arguments, or approval decisions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

StepKind = Literal["observe", "reason", "propose_action", "verify", "inform"]

_STEP_ID_PATTERN = r"^[a-z][a-z0-9_-]{0,39}$"
_CAPABILITY_ID_PATTERN = r"^[a-z0-9][a-z0-9_.-]{2,99}$"


class PlanStep(BaseModel):
    """One declarative step with explicit dependencies and a completion condition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(min_length=1, max_length=40, pattern=_STEP_ID_PATTERN)
    kind: StepKind
    description: str = Field(min_length=1, max_length=300)
    success_criteria: str = Field(min_length=1, max_length=300)
    depends_on: list[str] = Field(default_factory=list, max_length=24)
    capability_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=100,
        pattern=_CAPABILITY_ID_PATTERN,
    )

    @model_validator(mode="after")
    def validate_capability_reference(self) -> Self:
        if self.kind == "propose_action" and self.capability_id is None:
            raise ValueError("propose_action steps must reference a capability_id")
        if self.kind != "propose_action" and self.capability_id is not None:
            raise ValueError("capability_id is only valid for propose_action steps")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("depends_on cannot contain duplicate step IDs")
        for dependency in self.depends_on:
            if not _STEP_ID_PATTERN.fullmatch(dependency):
                raise ValueError(f"invalid dependency step ID: {dependency!r}")
        return self


class TaskPlan(BaseModel):
    """A small, explicit plan envelope suitable for deterministic validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=80)
    goal: str = Field(min_length=1, max_length=500)
    steps: list[PlanStep] = Field(min_length=1, max_length=25)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_plan_references(self) -> Self:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")

        by_id: dict[str, PlanStep] = {}
        for step in self.steps:
            if step.step_id in by_id:
                raise ValueError(f"duplicate step_id: {step.step_id}")
            by_id[step.step_id] = step

        for step in self.steps:
            if step.step_id in step.depends_on:
                raise ValueError(f"step {step.step_id!r} cannot depend on itself")
            missing = sorted(set(step.depends_on) - by_id.keys())
            if missing:
                raise ValueError(
                    f"step {step.step_id!r} references unknown dependencies: {', '.join(missing)}"
                )

        for constraint in self.constraints:
            if not constraint.strip() or len(constraint) > 300:
                raise ValueError("constraints must contain 1-300 non-empty characters")
        return self
