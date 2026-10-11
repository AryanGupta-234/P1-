"""Validated action proposals, capability manifests and policy decisions."""
from __future__ import annotations

import json
import math
import re
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

RiskTier = Literal["low", "medium", "high", "critical"]
_SAFE_PARAMETER_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_FORBIDDEN_PARAMETER_PARTS = (
    "password", "passwd", "secret", "token", "credential", "cookie",
    "authorization", "api_key", "apikey", "private_key", "access_key",
)


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
        for parameter in self.allowed_parameters:
            if not _SAFE_PARAMETER_KEY.fullmatch(parameter):
                raise ValueError(f"invalid capability parameter name: {parameter!r}")
            lowered = parameter.lower()
            if any(part in lowered for part in _FORBIDDEN_PARAMETER_PARTS):
                raise ValueError("capabilities cannot accept credential-like parameter names")
        return self


class ActionProposal(BaseModel):
    """Untrusted request for a scoped action; it is not an instruction to execute."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=80)
    capability_id: str = Field(min_length=3, max_length=100)
    summary: str = Field(default="Review requested action.", min_length=1, max_length=500)
    parameters: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="assistant", min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_bounded_non_secret_parameters(self) -> Self:
        if len(self.parameters) > 20:
            raise ValueError("a proposal may contain at most 20 parameters")
        for key, value in self.parameters.items():
            if not _SAFE_PARAMETER_KEY.fullmatch(key):
                raise ValueError(f"invalid proposal parameter name: {key!r}")
            lowered = key.lower()
            if any(part in lowered for part in _FORBIDDEN_PARAMETER_PARTS):
                raise ValueError("credential-like parameters cannot be stored in proposals")
            values = value if isinstance(value, list) else [value]
            if isinstance(value, list) and len(value) > 20:
                raise ValueError("list parameters may contain at most 20 values")
            for item in values:
                if item is None or isinstance(item, (bool, int)):
                    continue
                if isinstance(item, float):
                    if not math.isfinite(item):
                        raise ValueError("numeric proposal parameters must be finite")
                    continue
                if isinstance(item, str) and len(item) <= 500:
                    continue
                raise ValueError("proposal parameters must be short scalar values or scalar lists")
        encoded = json.dumps(self.parameters, ensure_ascii=True, allow_nan=False).encode("utf-8")
        if len(encoded) > 8192:
            raise ValueError("serialized proposal parameters exceed 8 KiB")
        return self


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
