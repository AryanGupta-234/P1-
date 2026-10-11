"""Versioned contracts shared by all perception providers."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field


class EntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    name: str
    stable_id: str | None = None


class AIEEvent(BaseModel):
    """Normalized evidence record, never an instruction."""
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    schema_version: Literal["1.0"] = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    host_id: str
    source: str
    event_type: str
    entity: EntityRef
    data: dict[str, Any] = Field(default_factory=dict)
    sensitivity: Literal["public", "internal", "sensitive"] = "internal"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    correlation_id: str | None = None
    evidence_kind: Literal["observed", "derived"] = "observed"
