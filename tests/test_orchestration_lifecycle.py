import pytest

from aie.orchestration.engine import TaskOrchestrator
from aie.orchestration.models import StepRun
from aie.orchestration.store import TaskRunStore
from aie.planning.models import PlanStep, TaskPlan


def test_pause_and_cancel_refuse_an_active_handler(tmp_path):
    store = TaskRunStore(tmp_path / "runs.sqlite3")
    engine = TaskOrchestrator(store)
    plan = TaskPlan(
        goal="Do not interrupt a live handler",
        steps=(
            PlanStep(
                step_id="observe",
                kind="observe",
                description="Observe",
                success_criteria="Record an observation summary",
            ),
        ),
    )
    run = engine.create(plan)
    active = engine._replace_step(
        run,
        StepRun(step_id="observe", status="running", attempts=1),
    ).model_copy(update={"status": "running"})
    active = store.save(
        active,
        expected_version=run.version,
        event_type="task.step.started",
    )

    with pytest.raises(ValueError, match="during a handler invocation"):
        engine.pause(active.run_id)
    with pytest.raises(ValueError, match="during a handler invocation"):
        engine.cancel(active.run_id)

    assert store.get(active.run_id).steps[0].status == "running"
