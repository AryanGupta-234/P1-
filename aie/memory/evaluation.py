"""Reproducible retrieval evaluation for a user-supplied local memory query set."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aie.memory.store import MemoryStore


class MemoryEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=500)
    relevant_memory_ids: tuple[str, ...] = Field(min_length=1, max_length=50)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("evaluation query cannot be blank")
        return cleaned

    @field_validator("relevant_memory_ids")
    @classmethod
    def normalize_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("relevant memory IDs cannot contain duplicates")
        if any(not item.strip() or len(item) > 80 for item in values):
            raise ValueError("relevant memory IDs must be non-empty and at most 80 characters")
        return tuple(values)


class MemoryEvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    cases: tuple[MemoryEvaluationCase, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_case_ids(self) -> "MemoryEvaluationDataset":
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation case IDs must be unique")
        return self


class MemoryCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    relevant_count: int
    returned_count: int
    relevant_returned: int
    recall_at_k: float
    precision_at_k: float
    reciprocal_rank: float
    first_relevant_rank: int | None
    ranked_memory_ids: tuple[str, ...]


class MemoryEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    retrieval: Literal["lexical", "semantic"]
    embedding_model: str | None = None
    k: int
    cases: tuple[MemoryCaseResult, ...]
    mean_recall_at_k: float
    mean_precision_at_k: float
    mean_reciprocal_rank: float
    hit_rate_at_k: float
    evaluated_at_utc: str


class MemoryEvaluationError(ValueError):
    """Raised when the evaluation dataset or requested retrieval provider is invalid."""


def load_memory_evaluation_dataset(path: Path) -> MemoryEvaluationDataset:
    """Load a small user-selected JSON benchmark; do not traverse directories or symlinks."""
    if path.is_symlink() or not path.is_file():
        raise MemoryEvaluationError("dataset path must be a regular local file")
    if path.stat().st_size > 256 * 1024:
        raise MemoryEvaluationError("dataset file exceeds 256 KiB")
    try:
        return MemoryEvaluationDataset.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise MemoryEvaluationError(
            f"dataset could not be validated ({type(exc).__name__})"
        ) from exc


def evaluate_memory_retrieval(
    dataset: MemoryEvaluationDataset,
    store: MemoryStore,
    *,
    k: int = 5,
    include_sensitive: bool = False,
    embedding_provider=None,
    embedding_model: str | None = None,
) -> MemoryEvaluationReport:
    """Evaluate ranked retrieval without changing memory, embeddings or model parameters."""
    if not 1 <= k <= 20:
        raise MemoryEvaluationError("k must be between 1 and 20")
    semantic = embedding_model is not None
    if semantic and embedding_provider is None:
        raise MemoryEvaluationError("semantic evaluation requires an explicit embedding provider")
    if not semantic and embedding_provider is not None:
        raise MemoryEvaluationError("embedding_provider requires embedding_model")

    eligible = store.list_memories(
        include_sensitive=include_sensitive,
        include_superseded=False,
        include_expired=False,
        limit=1000,
    )
    eligible_ids = {item.memory.memory_id for item in eligible}
    expected_ids = {
        memory_id
        for case in dataset.cases
        for memory_id in case.relevant_memory_ids
    }
    missing = sorted(expected_ids - eligible_ids)
    if missing:
        raise MemoryEvaluationError(
            "relevant memory is missing, expired, superseded or sensitivity-filtered: "
            + missing[0]
        )

    results: list[MemoryCaseResult] = []
    for case in dataset.cases:
        if semantic:
            vectors = embedding_provider.embed(
                [case.query],
                model=embedding_model,
            )
            if len(vectors) != 1:
                raise MemoryEvaluationError(
                    "embedding provider must return exactly one query vector"
                )
            hits = store.search_semantic(
                vectors[0],
                model=embedding_model,
                include_sensitive=include_sensitive,
                limit=k,
            )
        else:
            hits = store.search(
                case.query,
                include_sensitive=include_sensitive,
                limit=k,
            )

        ranked = tuple(hit.memory.memory_id for hit in hits)
        relevant = set(case.relevant_memory_ids)
        positions = [
            index for index, memory_id in enumerate(ranked, start=1)
            if memory_id in relevant
        ]
        found = len(positions)
        first_rank = min(positions) if positions else None
        results.append(
            MemoryCaseResult(
                case_id=case.case_id,
                relevant_count=len(relevant),
                returned_count=len(ranked),
                relevant_returned=found,
                recall_at_k=found / len(relevant),
                precision_at_k=found / k,
                reciprocal_rank=(1.0 / first_rank) if first_rank else 0.0,
                first_relevant_rank=first_rank,
                ranked_memory_ids=ranked,
            )
        )

    total = len(results)
    return MemoryEvaluationReport(
        dataset_id=dataset.dataset_id,
        retrieval="semantic" if semantic else "lexical",
        embedding_model=embedding_model,
        k=k,
        cases=tuple(results),
        mean_recall_at_k=sum(item.recall_at_k for item in results) / total,
        mean_precision_at_k=sum(item.precision_at_k for item in results) / total,
        mean_reciprocal_rank=sum(item.reciprocal_rank for item in results) / total,
        hit_rate_at_k=sum(item.relevant_returned > 0 for item in results) / total,
        evaluated_at_utc=datetime.now(timezone.utc).isoformat(),
    )
