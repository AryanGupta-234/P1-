from datetime import datetime, timedelta, timezone

import pytest

from aie.contracts import AIEEvent, EntityRef
from aie.memory.models import MemoryRecord
from aie.memory.store import MemoryStore
from aie.orchestration.models import new_task_run
from aie.orchestration.store import TaskRunStore
from aie.planning.models import PlanStep, TaskPlan
from aie.policy.ledger import PolicyLedger
from aie.retention import collect_retention_snapshot
from aie.store import EventStore


def add_event(store, *, timestamp, event_type):
    event = AIEEvent(
        timestamp=timestamp,
        host_id="retention-test-host",
        source="test",
        event_type=event_type,
        entity=EntityRef(type="test", name=event_type),
        data={},
    )
    store.append(event)
    return event


def test_retention_snapshot_counts_candidates_without_deleting(tmp_path):
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    event_store = EventStore(tmp_path / "events.sqlite3")
    memory_store = MemoryStore(tmp_path / "memory.sqlite3")
    task_store = TaskRunStore(tmp_path / "tasks.sqlite3")
    ledger = PolicyLedger(tmp_path / "policy.sqlite3")

    old_event = add_event(
        event_store,
        timestamp=now - timedelta(days=40),
        event_type="test.old",
    )
    add_event(
        event_store,
        timestamp=now - timedelta(days=2),
        event_type="test.recent",
    )
    active = memory_store.save(
        MemoryRecord(kind="semantic", content="Active memory.")
    )
    expired = memory_store.save(
        MemoryRecord(
            kind="episodic",
            content="Expired memory.",
            created_at=now - timedelta(days=5),
            expires_at=now - timedelta(days=1),
        )
    )
    plan = TaskPlan(
        goal="Inspect a local desktop state",
        steps=(
            PlanStep(
                step_id="observe",
                kind="observe",
                description="Inspect local metadata.",
                success_criteria="A bounded summary is recorded.",
            ),
        ),
    )
    run = task_store.create(new_task_run(plan))

    report = collect_retention_snapshot(
        event_store=event_store,
        memory_store=memory_store,
        task_run_store=task_store,
        policy_ledger=ledger,
        event_retention_days=30,
        now=now,
        sample_limit=100,
    )

    assert report.event_count == 2
    assert report.event_prune_candidates == 1
    assert report.memory_count == 2
    assert report.active_memory_count == 1
    assert report.expired_memory_count == 1
    assert report.task_run_status_counts == {"queued": 1}
    assert report.proposal_count_sampled == 0
    assert report.task_sample_truncated is False
    assert event_store.get(old_event.event_id) is not None
    assert memory_store.get(active.memory_id) is not None
    assert memory_store.get(expired.memory_id) is not None
    assert task_store.get(run.run_id) is not None


def test_retention_snapshot_validates_bounds_and_timezone(tmp_path):
    event_store = EventStore(tmp_path / "events.sqlite3")
    memory_store = MemoryStore(tmp_path / "memory.sqlite3")
    task_store = TaskRunStore(tmp_path / "tasks.sqlite3")
    ledger = PolicyLedger(tmp_path / "policy.sqlite3")

    kwargs = {
        "event_store": event_store,
        "memory_store": memory_store,
        "task_run_store": task_store,
        "policy_ledger": ledger,
    }
    with pytest.raises(ValueError, match="event_retention_days"):
        collect_retention_snapshot(**kwargs, event_retention_days=0)
    with pytest.raises(ValueError, match="sample_limit"):
        collect_retention_snapshot(**kwargs, sample_limit=0)
    with pytest.raises(ValueError, match="timezone-aware"):
        collect_retention_snapshot(
            **kwargs,
            now=datetime(2026, 10, 11, 12, 0),
        )
