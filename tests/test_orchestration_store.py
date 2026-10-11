import pytest

from aie.orchestration.models import new_task_run
from aie.orchestration.store import TaskRunConflict, TaskRunStore
from aie.planning.models import PlanStep, TaskPlan


def test_store_uses_compare_and_swap_versions(tmp_path):
    store = TaskRunStore(tmp_path / "runs.sqlite3")
    plan = TaskPlan(
        goal="Persist a run",
        steps=(
            PlanStep(
                step_id="observe",
                kind="observe",
                description="Observe",
                success_criteria="A bounded sample is recorded",
            ),
        ),
    )
    created = store.create(new_task_run(plan))
    stale_copy = store.get(created.run_id)
    first = store.save(
        created.model_copy(update={"status": "paused"}),
        expected_version=created.version,
        event_type="task.paused",
    )
    assert first.version == created.version + 1

    with pytest.raises(TaskRunConflict):
        store.save(
            stale_copy.model_copy(update={"status": "cancelled"}),
            expected_version=stale_copy.version,
            event_type="task.cancelled",
        )

    assert store.get(created.run_id).status == "paused"
    assert len(store.events(created.run_id)) == 2
