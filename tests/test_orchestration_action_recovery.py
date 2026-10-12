from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from aie.orchestration.engine import TaskOrchestrator
from aie.orchestration.handlers import PolicyProposalHandler
from aie.orchestration.models import StepRun
from aie.orchestration.store import TaskRunStore
from aie.planning.models import PlanStep, TaskPlan
from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
from aie.policy.models import ActionProposal, CapabilityManifest


def test_crash_between_proposal_creation_and_task_checkpoint_is_idempotent(tmp_path):
    manifest = CapabilityManifest(
        capability_id="windows.settings.open",
        description="Open one fixed Windows Settings page.",
        risk_tier="low",
        enabled=True,
        approval_required=True,
        allow_autonomous=False,
        allowed_parameters=frozenset({"setting"}),
    )
    broker = CapabilityPolicyBroker([manifest])
    ledger = PolicyLedger(tmp_path / "policy.sqlite3")
    task_store = TaskRunStore(tmp_path / "runs.sqlite3")
    engine = TaskOrchestrator(task_store)

    plan_step = PlanStep(
        step_id="open-settings",
        kind="propose_action",
        description="Open the Display Settings page.",
        success_criteria="A successful dispatch receipt is recorded.",
        capability_id="windows.settings.open",
    )
    run = engine.create(
        TaskPlan(
            goal="Open the reviewed Display Settings page",
            steps=(plan_step,),
        )
    )

    deterministic_id = str(
        uuid5(
            NAMESPACE_URL,
            f"aie-task-proposal:{run.run_id}:{plan_step.step_id}",
        )
    )
    proposal = ActionProposal(
        proposal_id=deterministic_id,
        capability_id=plan_step.capability_id,
        summary=plan_step.description,
        parameters={"setting": "display"},
        source=f"task:{run.run_id}",
    )
    created = PolicyProposalQueue(ledger).create(proposal, broker)
    assert created.status == "pending_review"

    now = datetime.now(timezone.utc)
    running = engine._replace_step(
        run,
        StepRun(
            step_id=plan_step.step_id,
            status="running",
            attempts=1,
            started_at=now - timedelta(minutes=10),
        ),
    ).model_copy(update={"status": "running"})
    task_store.save(
        running,
        expected_version=run.version,
        event_type="task.step.started",
    )

    recovered = engine.recover_interrupted(
        run.run_id,
        minimum_age_seconds=300,
        now=now,
    )
    assert recovered.status == "awaiting_input"

    handler = PolicyProposalHandler(
        broker,
        ledger,
        proposal_parameters={"windows.settings.open": {"setting": "display"}},
    )
    advanced = engine.advance(run.run_id, {"propose_action": handler})
    assert advanced.status == "awaiting_approval"
    assert advanced.steps[0].proposal_id == deterministic_id
    assert len(ledger.audit_trail(deterministic_id)) == 1
