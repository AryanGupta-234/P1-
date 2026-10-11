"""Read-only retention inventory for local evidence, memory and task state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aie.memory.store import MemoryStore
from aie.orchestration.store import TaskRunStore
from aie.policy.ledger import PolicyLedger
from aie.store import EventStore


class RetentionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_retention_days: int
    event_count: int
    event_prune_candidates: int
    memory_count: int
    active_memory_count: int
    expired_memory_count: int
    task_run_count_sampled: int
    task_run_status_counts: dict[str, int] = Field(default_factory=dict)
    proposal_count_sampled: int
    proposal_status_counts: dict[str, int] = Field(default_factory=dict)
    task_sample_truncated: bool = False
    proposal_sample_truncated: bool = False
    evaluated_at_utc: str


def collect_retention_snapshot(
    *,
    event_store: EventStore,
    memory_store: MemoryStore,
    task_run_store: TaskRunStore,
    policy_ledger: PolicyLedger,
    event_retention_days: int = 30,
    now: datetime | None = None,
    sample_limit: int = 1000,
) -> RetentionSnapshot:
    """Count retention candidates without deleting or modifying any local data."""
    if isinstance(event_retention_days, bool) or not 1 <= event_retention_days <= 3650:
        raise ValueError("event_retention_days must be between 1 and 3650")
    if not 1 <= sample_limit <= 1000:
        raise ValueError("sample_limit must be between 1 and 1000")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("retention snapshot clock must be timezone-aware")
    current = current.astimezone(timezone.utc)
    cutoff = current - timedelta(days=event_retention_days)

    task_runs = task_run_store.list(limit=sample_limit)
    task_counts: dict[str, int] = {}
    for run in task_runs:
        task_counts[run.status] = task_counts.get(run.status, 0) + 1

    proposals = policy_ledger.list(status=None, limit=sample_limit)
    proposal_counts: dict[str, int] = {}
    for proposal in proposals:
        proposal_counts[proposal.status] = proposal_counts.get(proposal.status, 0) + 1

    return RetentionSnapshot(
        event_retention_days=event_retention_days,
        event_count=event_store.count(),
        event_prune_candidates=event_store.count_before(cutoff),
        memory_count=memory_store.count(include_superseded=True),
        active_memory_count=memory_store.count_active(now=current),
        expired_memory_count=memory_store.count_expired(now=current),
        task_run_count_sampled=len(task_runs),
        task_run_status_counts=task_counts,
        proposal_count_sampled=len(proposals),
        proposal_status_counts=proposal_counts,
        task_sample_truncated=len(task_runs) >= sample_limit,
        proposal_sample_truncated=len(proposals) >= sample_limit,
        evaluated_at_utc=current.isoformat(),
    )
