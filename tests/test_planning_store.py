from datetime import datetime, timezone

import pytest

from aie.planning import PlanStep, TaskPlan
from aie.planning.store import PlanRunError, PlanRunStore


def make_plan():
    return TaskPlan(
        plan_id="store-test-plan",
        goal="Inspect a desktop application safely",
        steps=(
            PlanStep(
                step_id="observe",
                kind="observe",
                description="Collect structural metadata",
                success_criteria="Metadata snapshot is recorded",
            ),
            PlanStep(
                step_id="reason",
                kind="reason",
                description="Review evidence",
                success_criteria="Evidence review is complete",
                depends_on=("observe",),
            ),
            PlanStep(
                step_id="inform",
                kind="inform",
                description="Summarize findings",
                success_criteria="Summary is available",
                depends_on=("reason",),
            ),
        ),
    )


def test_create_persists_plan_and_pending_steps(tmp_path):
    store = PlanRunStore(tmp_path / "plans.sqlite3")
    now = datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc)

    run = store.create(make_plan(), now=now)

    assert run.status == "active"
    assert run.plan.plan_id == "store-test-plan"
    assert [step.status for step in run.steps] == ["pending", "pending", "pending"]
    assert run.created_at == now


def test_step_cannot_start_before_dependencies_succeed(tmp_path):
    store = PlanRunStore(tmp_path / "plans.sqlite3")
    run = store.create(make_plan())

    with pytest.raises(PlanRunError, match="requires successful dependency"):
        store.transition(run.run_id, "reason", "running", actor="user")


def test_transitions_require_evidence_for_success_and_failure(tmp_path):
    store = PlanRunStore(tmp_path / "plans.sqlite3")
    run = store.create(make_plan())
    store.transition(run.run_id, "observe", "running", actor="user")

    with pytest.raises(PlanRunError, match="require at least one evidence ID"):
        store.transition(run.run_id, "observe", "succeeded", actor="user")

    updated = store.transition(
        run.run_id,
        "observe",
        "succeeded",
        actor="user",
        evidence_ids=("event:123",),
    )
    assert updated.steps[0].status == "succeeded"


def test_successful_run_requires_ordered_evidence_backed_transitions(tmp_path):
    store = PlanRunStore(tmp_path / "plans.sqlite3")
    run = store.create(make_plan())

    for step_id, evidence_id in (
        ("observe", "event:observe"),
        ("reason", "event:reason"),
        ("inform", "event:inform"),
    ):
        store.transition(run.run_id, step_id, "running", actor="user")
        updated = store.transition(
            run.run_id,
            step_id,
            "succeeded",
            actor="user",
            evidence_ids=(evidence_id,),
        )

    assert updated.status == "completed"
    assert all(step.status == "succeeded" for step in updated.steps)
    history = store.transitions(run.run_id)
    assert len(history) == 6
    assert history[-1].evidence_ids == ("event:inform",)
    assert history[-1].actor == "user"


def test_failed_or_cancelled_steps_cannot_be_retried_implicitly(tmp_path):
    store = PlanRunStore(tmp_path / "plans.sqlite3")
    run = store.create(make_plan())
    store.transition(run.run_id, "observe", "running", actor="system")
    failed = store.transition(
        run.run_id,
        "observe",
        "failed",
        actor="system",
        evidence_ids=("event:error",),
    )

    with pytest.raises(PlanRunError, match="invalid step transition"):
        store.transition(run.run_id, "observe", "running", actor="user")
    assert failed.status == "active"


def test_cancel_records_all_unfinished_steps_atomically(tmp_path):
    store = PlanRunStore(tmp_path / "plans.sqlite3")
    run = store.create(make_plan())
    store.transition(run.run_id, "observe", "running", actor="user")

    cancelled = store.cancel(run.run_id, actor="user", reason="User stopped the plan")

    assert cancelled.status == "cancelled"
    assert [step.status for step in cancelled.steps] == [
        "cancelled",
        "cancelled",
        "cancelled",
    ]
    history = store.transitions(run.run_id)
    assert len(history) == 4
    assert all(item.to_status == "cancelled" for item in history[-3:])
    assert all(item.note == "User stopped the plan" for item in history[-3:])


def test_transition_history_is_append_only(tmp_path):
    store = PlanRunStore(tmp_path / "plans.sqlite3")
    run = store.create(make_plan())

    import sqlite3

    with sqlite3.connect(store.path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM plan_transitions")
