"""Validated, provenance-aware local memory records."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MemoryKind = Literal["working", "episodic", "semantic", "procedural", "prospective"]
MemorySensitivity = Literal["public", "internal", "sensitive"]
_TAG = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")


class MemoryRecord(BaseModel):
    """One user-controlled memory with provenance, sensitivity and expiry metadata."""

    model_config = ConfigDict(extra="forbid")

    memory_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=80)
    kind: MemoryKind
    content: str = Field(min_length=1, max_length=8000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    sensitivity: MemorySensitivity = "internal"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_event_ids: list[str] = Field(default_factory=list, max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    supersedes_id: str | None = Field(default=None, max_length=80)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("memory content cannot be blank")
        return cleaned

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("memory tags must be strings")
            tag = value.strip().lower().replace(" ", "-")
            if not _TAG.fullmatch(tag):
                raise ValueError(f"invalid memory tag: {value!r}")
            if tag not in normalized:
                normalized.append(tag)
        return normalized

    @field_validator("source_event_ids")
    @classmethod
    def validate_source_ids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            candidate = value.strip()
            if not candidate or len(candidate) > 80:
                raise ValueError("source event IDs must be non-empty and at most 80 characters")
            if candidate not in normalized:
                normalized.append(candidate)
        return normalized

    @model_validator(mode="after")
    def validate_timestamps(self) -> "MemoryRecord":
        for name in ("created_at", "updated_at"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None:
                raise ValueError("expires_at must be timezone-aware")
            if self.expires_at <= self.created_at:
                raise ValueError("expires_at must be later than created_at")
        return self


class MemorySearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory: MemoryRecord
    score: float = Field(ge=0.0, le=2.0)
