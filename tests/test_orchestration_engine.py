from aie.orchestration.engine import HandlerResult, TaskOrchestrator
from aie.orchestration.store import TaskRunStore
from aie.planning.models import PlanStep, TaskPlan


def step(step_id, kind="observe", depends_on=(), capability_id=None):
    return PlanStep(
        step_id=step_id,
        kind=kind,
        description=f"Perform {step_id}",
        success_criteria=f"Confirm {step_id}",
        depends_on=tuple(depends_on),
        capability_id=capability_id,
    )


class QueueHandler:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def execute(self, plan_step, context):
        self.calls.append((plan_step.step_id, context.attempt, context.proposal_id))
        return self.results.pop(0)


def test_task_run_advances_in_dependency_order_and_persists(tmp_path):
    store = TaskRunStore(tmp_path / "runs.sqlite3")
    engine = TaskOrchestrator(store)
    plan = TaskPlan(
        goal="Inspect a local application",
        steps=(
            step("observe"),
            step("reason", "reason", ("observe",)),
            step("verify", "verify", ("reason",)),
        ),
    )
    run = engine.create(plan)
    handler = QueueHandler(
        HandlerResult.completed("Observed local metadata."),
        HandlerResult.completed("Reasoned over the explicit summary."),
        HandlerResult.completed("Postcondition manually checked.", verified=True),
    )

    result = engine.advance(
        run.run_id,
        {"observe": handler, "reason": handler, "verify": handler},
        max_steps=3,
    )

    assert result.status == "completed"
    assert [call[0] for call in handler.calls] == ["observe", "reason", "verify"]
    assert all(item.status == "completed" for item in result.steps)
    assert result.steps[-1].verified is True
    assert store.get(run.run_id).version == result.version
    assert [item["event_type"] for item in store.events(run.run_id)][-1] == "task.completed"


def test_action_step_waits_for_proposal_and_can_resume_from_a_receipt(tmp_path):
    engine = TaskOrchestrator(TaskRunStore(tmp_path / "runs.sqlite3"))
    plan = TaskPlan(
        goal="Open a reviewed Windows settings page",
        steps=(
            step(
                "open-settings",
                "propose_action",
                capability_id="windows.settings.open",
            ),
        ),
    )
    run = engine.create(plan)
    handler = QueueHandler(
        HandlerResult.awaiting_approval("proposal-123", "Waiting for review."),
        HandlerResult.completed("Action receipt recorded.", verified=False),
    )

    waiting = engine.advance(run.run_id, {"propose_action": handler})
    assert waiting.status == "awaiting_approval"
    assert waiting.steps[0].proposal_id == "proposal-123"

    completed = engine.advance(run.run_id, {"propose_action": handler})
    assert completed.status == "completed"
    assert completed.steps[0].proposal_id == "proposal-123"
    assert handler.calls[1][2] == "proposal-123"


def test_verification_cannot_be_completed_without_positive_confirmation(tmp_path):
    engine = TaskOrchestrator(TaskRunStore(tmp_path / "runs.sqlite3"))
    plan = TaskPlan(
        goal="Verify the result",
        steps=(step("verify", "verify"),),
    )
    run = engine.create(plan)
    handler = QueueHandler(HandlerResult.awaiting_input("Check the postcondition."))

    waiting = engine.advance(run.run_id, {"verify": handler})
    assert waiting.status == "awaiting_input"

    failed = engine.complete_input(
        run.run_id,
        "verify",
        summary="Could not confirm the expected result.",
        verified=False,
    )
    assert failed.status == "failed"
    assert failed.steps[0].verified is False
    assert failed.failure_type == "verification_not_confirmed"


def test_action_steps_cannot_be_manually_marked_complete(tmp_path):
    engine = TaskOrchestrator(TaskRunStore(tmp_path / "runs.sqlite3"))
    plan = TaskPlan(
        goal="Request an action",
        steps=(step("action", "propose_action", capability_id="windows.settings.open"),),
    )
    run = engine.create(plan)
    waiting = engine.advance(
        run.run_id,
        {"propose_action": QueueHandler(
            HandlerResult.awaiting_input("Execute only through the policy executor.")
        )},
    )
    try:
        engine.complete_input(
            run.run_id, "action", summary="I say it is done.", verified=True
        )
    except ValueError as exc:
        assert "policy-ledger execution receipt" in str(exc)
    else:
        raise AssertionError("manual input must not complete action steps")
    assert waiting.status == "awaiting_input"


def test_pause_resume_and_cancel_are_durable(tmp_path):
    engine = TaskOrchestrator(TaskRunStore(tmp_path / "runs.sqlite3"))
    plan = TaskPlan(goal="Wait for an input", steps=(step("manual", "reason"),))
    run = engine.create(plan)

    paused = engine.pause(run.run_id)
    assert paused.status == "paused"
    resumed = engine.resume(run.run_id)
    assert resumed.status == "queued"
    cancelled = engine.cancel(run.run_id, reason="user requested stop")
    assert cancelled.status == "cancelled"
    assert cancelled.steps[0].status == "skipped"
