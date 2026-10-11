import json

import pytest

from aie.orchestration import InformHandler, StepOutcome, TaskOrchestrator, TaskRunStore
from aie.planning.generator import PlanGenerationError, generate_task_plan
from aie.planning.models import PlanStep, TaskPlan
from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
from aie.policy.models import CapabilityManifest


def make_step(step_id, *, kind="observe", depends_on=(), capability_id=None):
    return PlanStep(
        step_id=step_id,
        kind=kind,
        description=f"Handle {step_id}",
        success_criteria=f"Confirm {step_id}",
        depends_on=tuple(depends_on),
        capability_id=capability_id,
    )


def make_plan(*steps):
    return TaskPlan(goal="Inspect the local application safely", steps=tuple(steps))


def test_task_run_persists_plan_and_completes_dependency_order(tmp_path):
    store = TaskRunStore(tmp_path / "runs.sqlite3")
    plan = make_plan(
        make_step("report", kind="inform", depends_on=("observe",)),
        make_step("observe"),
    )
    runner = TaskOrchestrator(
        store,
        handlers={"observe": lambda step, run: StepOutcome(
            True, "Observed local metadata.", ("event-1",)
        ), "inform": InformHandler()},
    )

    created = runner.start(plan)
    assert created.status == "ready"
    completed = runner.advance(created.run_id)

    assert completed.status == "completed"
    assert [step.step_id for step in completed.steps] == ["report", "observe"]
    by_id = {step.step_id: step for step in completed.steps}
    assert by_id["observe"].status == "completed"
    assert by_id["observe"].evidence_ids == ("event-1",)
    assert by_id["report"].status == "completed"
    assert by_id["report"].attempts == 1
    assert store.get(created.run_id).plan.plan_id == plan.plan_id


def test_missing_handler_fails_closed_without_claiming_completion(tmp_path):
    store = TaskRunStore(tmp_path / "runs.sqlite3")
    runner = TaskOrchestrator(store)
    created = runner.start(make_plan(make_step("observe")))

    result = runner.advance(created.run_id)

    assert result.status == "failed"
    assert result.steps[0].status == "failed"
    assert "No handler is registered" in result.steps[0].summary


def test_action_step_waits_for_review_and_approval_never_means_execution(tmp_path):
    manifest = CapabilityManifest(
        capability_id="windows.display.test",
        description="Test-only no-op capability",
        risk_tier="medium",
        enabled=True,
        approval_required=True,
        allowed_parameters=frozenset(),
    )
    broker = CapabilityPolicyBroker([manifest])
    ledger = PolicyLedger(tmp_path / "policy.sqlite3")
    queue = PolicyProposalQueue(ledger)
    store = TaskRunStore(tmp_path / "runs.sqlite3")
    runner = TaskOrchestrator(store, proposal_queue=queue, broker=broker)
    created = runner.start(
        make_plan(make_step(
            "request-change",
            kind="propose_action",
            capability_id="windows.display.test",
        ))
    )

    waiting = runner.advance(created.run_id)
    action_step = waiting.steps[0]
    assert waiting.status == "waiting_approval"
    assert action_step.status == "waiting_approval"
    assert action_step.proposal_id

    reviewed = queue.review(action_step.proposal_id, approve=True, broker=broker)
    assert reviewed.status == "approved"
    refreshed = runner.refresh_action_review(created.run_id, action_step.step_id, ledger)

    assert refreshed.status == "blocked"
    assert refreshed.steps[0].status == "authorized"
    assert "No real capability executor" in refreshed.steps[0].error
    assert "completed" not in {step.status for step in refreshed.steps}


def test_action_step_is_blocked_when_capability_is_unknown(tmp_path):
    broker = CapabilityPolicyBroker([])
    queue = PolicyProposalQueue(PolicyLedger(tmp_path / "policy.sqlite3"))
    store = TaskRunStore(tmp_path / "runs.sqlite3")
    runner = TaskOrchestrator(store, proposal_queue=queue, broker=broker)
    created = runner.start(
        make_plan(make_step(
            "unknown-action",
            kind="propose_action",
            capability_id="windows.unknown.operation",
        ))
    )

    result = runner.advance(created.run_id)

    assert result.status == "failed"
    assert result.steps[0].status == "failed"
    assert "blocked by policy" in result.steps[0].summary.lower()


def test_cancel_and_interrupted_recovery_are_fail_closed(tmp_path):
    store = TaskRunStore(tmp_path / "runs.sqlite3")
    cancelled = store.create(make_plan(make_step("one")))
    result = store.request_cancel(cancelled.run_id)
    assert result.status == "cancelled"
    assert result.steps[0].status == "cancelled"

    interrupted = store.create(make_plan(make_step("in-flight")))
    claimed = store.claim_next_ready(interrupted.run_id)
    assert claimed is not None
    assert store.recover_interrupted() == 1
    recovered = store.get(interrupted.run_id)
    assert recovered.status == "failed"
    assert recovered.steps[0].status == "failed"
    assert "automatic replay is disabled" in recovered.steps[0].error


def test_step_outcomes_are_bounded_and_require_unique_evidence_ids():
    with pytest.raises(ValueError, match="1-500"):
        StepOutcome(True, "   ")
    with pytest.raises(ValueError, match="unique"):
        StepOutcome(True, "done", ("event-1", "event-1"))
    with pytest.raises(ValueError, match="at most 20"):
        StepOutcome(True, "done", tuple(f"event-{i}" for i in range(21)))


class FakeRouter:
    def __init__(self, content):
        self.content = content
        self.last_request = None

    def generate(self, request):
        self.last_request = request

        class Response:
            pass

        response = Response()
        response.content = self.content
        return response


def test_local_plan_generator_validates_model_output():
    goal = "Inspect the local application safely"
    payload = {
        "goal": goal,
        "steps": [
            {
                "step_id": "observe",
                "kind": "observe",
                "description": "Collect local event metadata",
                "success_criteria": "Event IDs are recorded",
                "depends_on": [],
            },
            {
                "step_id": "inform",
                "kind": "inform",
                "description": "Summarize the observation",
                "success_criteria": "A summary is produced",
                "depends_on": ["observe"],
            },
        ],
        "constraints": ["Do not mutate the system"],
    }
    router = FakeRouter(json.dumps(payload))

    plan = generate_task_plan(goal, router)

    assert plan.goal == goal
    assert len(plan.steps) == 2
    assert router.last_request.messages[0].role == "system"


def test_local_plan_generator_rejects_unknown_fields_and_action_capability():
    goal = "Inspect the local application safely"
    payload = {
        "goal": goal,
        "steps": [
            {
                "step_id": "action",
                "kind": "propose_action",
                "description": "Change a setting",
                "success_criteria": "Setting is changed",
                "depends_on": [],
                "capability_id": "windows.display.unknown",
                "command": "arbitrary command",
            }
        ],
    }
    with pytest.raises(PlanGenerationError):
        generate_task_plan(goal, FakeRouter(json.dumps(payload)), available_capabilities=())
