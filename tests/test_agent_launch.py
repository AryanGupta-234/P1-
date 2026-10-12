import json

from aie.models.base import ModelResponse
from aie.orchestration.agent import start_agent_run
from aie.orchestration.engine import TaskOrchestrator
from aie.orchestration.store import TaskRunStore


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload
        self.requested_model = None

    def chat(self, request, *, model):
        self.requested_model = model
        return ModelResponse(
            model=model,
            content=json.dumps(self.payload),
            elapsed_seconds=0.01,
            local_inference=True,
            provider="fake-local",
        )


def test_agent_launch_drafts_validates_and_persists_without_advancing(tmp_path):
    payload = {
        "goal": "Inspect desktop playback health",
        "steps": [
            {
                "step_id": "observe",
                "kind": "observe",
                "description": "Review bounded local playback diagnostics.",
                "success_criteria": "A local diagnostic summary is available.",
                "depends_on": [],
            },
            {
                "step_id": "reason",
                "kind": "reason",
                "description": "Reason over the observation summary.",
                "success_criteria": "A bounded explanation is recorded.",
                "depends_on": ["observe"],
            },
        ],
    }
    provider = FakeProvider(payload)
    engine = TaskOrchestrator(TaskRunStore(tmp_path / "task-runs.sqlite3"))

    launch = start_agent_run(
        "Inspect desktop playback health",
        provider=provider,
        model="already-installed-local-model",
        orchestrator=engine,
        allowed_capability_ids=set(),
        explicit_context="Only this user-selected context is available.",
    )

    assert provider.requested_model == "already-installed-local-model"
    assert launch.plan.goal == payload["goal"]
    assert launch.run.status == "queued"
    assert [step.status for step in launch.run.steps] == ["pending", "pending"]
    assert engine.get(launch.run.run_id) == launch.run


def test_agent_launch_rejects_model_goal_changes_before_persisting(tmp_path):
    payload = {
        "goal": "An altered goal",
        "steps": [
            {
                "step_id": "observe",
                "kind": "observe",
                "description": "Observe.",
                "success_criteria": "An observation exists.",
                "depends_on": [],
            }
        ],
    }
    provider = FakeProvider(payload)
    engine = TaskOrchestrator(TaskRunStore(tmp_path / "task-runs.sqlite3"))

    from aie.planning.generator import PlanGenerationError
    import pytest

    with pytest.raises(PlanGenerationError, match="changed the requested goal"):
        start_agent_run(
            "Inspect desktop playback health",
            provider=provider,
            model="already-installed-local-model",
            orchestrator=engine,
        )
    assert engine.store.list() == []
