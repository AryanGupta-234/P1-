from datetime import datetime, timedelta, timezone

import pytest

from aie.orchestration.engine import TaskOrchestrator
from aie.orchestration.models import StepRun
from aie.orchestration.store import TaskRunStore
from aie.planning.models import PlanStep, TaskPlan


def test_recovery_refuses_recent_handlers_and_moves_stale_steps_to_review(tmp_path):
    store = TaskRunStore(tmp_path / "runs.sqlite3")
    engine = TaskOrchestrator(store)
    now = datetime.now(timezone.utc)
    plan = TaskPlan(
        goal="Recover interrupted local reasoning",
        steps=(
            PlanStep(
                step_id="reason",
                kind="reason",
                description="Reason over explicit local evidence.",
                success_criteria="A bounded reasoning summary is recorded.",
            ),
        ),
    )
    run = engine.create(plan)
    running = engine._replace_step(
        run,
        StepRun(
            step_id="reason",
            status="running",
            attempts=1,
            started_at=now - timedelta(seconds=30),
        ),
    ).model_copy(update={"status": "running"})
    active = store.save(
        running,
        expected_version=run.version,
        event_type="task.step.started",
    )

    with pytest.raises(ValueError, match="handler may still be active"):
        engine.recover_interrupted(
            active.run_id,
            minimum_age_seconds=300,
            now=now,
        )

    recovered = engine.recover_interrupted(
        active.run_id,
        minimum_age_seconds=20,
        now=now,
    )
    assert recovered.status == "awaiting_input"
    assert recovered.steps[0].status == "awaiting_input"
    assert recovered.steps[0].attempts == 1
    assert recovered.steps[0].error_type == "interrupted_requires_review"
    assert "will not be replayed" in recovered.steps[0].summary


def test_recovery_requires_an_interrupted_task_and_running_step(tmp_path):
    engine = TaskOrchestrator(TaskRunStore(tmp_path / "runs.sqlite3"))
    plan = TaskPlan(
        goal="Do not recover a completed task",
        steps=(
            PlanStep(
                step_id="observe",
                kind="observe",
                description="Observe",
                success_criteria="Observation is available",
            ),
        ),
    )
    run = engine.create(plan)

    with pytest.raises(ValueError, match="only a running or interrupted task run"):
        engine.recover_interrupted(run.run_id, minimum_age_seconds=1)

    with pytest.raises(ValueError, match="minimum_age_seconds"):
        engine.recover_interrupted(run.run_id, minimum_age_seconds=0)
