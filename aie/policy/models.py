"""Validated action proposals, capability manifests and policy decisions."""
from __future__ import annotations

from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

RiskTier = Literal["low", "medium", "high", "critical"]


class CapabilityManifest(BaseModel):
    """Administrator/user-authored declaration of one narrowly scoped capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str = Field(min_length=3, max_length=100, pattern=r"^[a-z0-9][a-z0-9_.-]+$")
    description: str = Field(min_length=1, max_length=500)
    risk_tier: RiskTier
    enabled: bool = False
    allow_autonomous: bool = False
    approval_required: bool = True
    allowed_parameters: frozenset[str] = frozenset()
    max_invocations_per_minute: int = Field(default=3, ge=1, le=60)
    max_execution_seconds: float = Field(default=10.0, gt=0.0, le=300.0)

    @model_validator(mode="after")
    def validate_autonomy_rules(self) -> Self:
        if self.allow_autonomous and self.risk_tier != "low":
            raise ValueError("Only low-risk capabilities may be pre-authorized for autonomy.")
        if self.allow_autonomous and self.approval_required:
            raise ValueError("Autonomous capabilities cannot also require per-action approval.")
        return self



class ActionProposal(BaseModel):
    """Untrusted request for an action; it is not an instruction to execute."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    capability_id: str = Field(min_length=3, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="assistant", min_length=1, max_length=80)


class PolicyDecision(BaseModel):
    """Policy result only; an allowed result is not execution confirmation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str
    capability_id: str
    allowed: bool
    approval_required: bool
    reason: str
    risk_tier: RiskTier | None
    max_execution_seconds: float | None = None
