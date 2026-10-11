from aie.orchestration.engine import TaskOrchestrator
from aie.orchestration.handlers import PolicyProposalHandler
from aie.orchestration.store import TaskRunStore
from aie.planning.models import PlanStep, TaskPlan
from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
from aie.policy.models import CapabilityManifest


def test_action_step_waits_for_approval_and_execution_receipt(tmp_path):
    manifest = CapabilityManifest(
        capability_id="windows.settings.open",
        description="Open a fixed Settings page.",
        risk_tier="low",
        enabled=True,
        approval_required=True,
        allow_autonomous=False,
        allowed_parameters=frozenset(),
    )
    broker = CapabilityPolicyBroker([manifest])
    ledger = PolicyLedger(tmp_path / "policy.sqlite3")
    handler = PolicyProposalHandler(broker, ledger)
    engine = TaskOrchestrator(TaskRunStore(tmp_path / "runs.sqlite3"))
    plan = TaskPlan(
        goal="Request a policy-reviewed action",
        steps=(
            PlanStep(
                step_id="request",
                kind="propose_action",
                description="Request the already-scoped no-argument action.",
                success_criteria="The proposal is approved and has an execution receipt.",
                capability_id="windows.settings.open",
            ),
        ),
    )
    run = engine.create(plan)

    awaiting = engine.advance(run.run_id, {"propose_action": handler})
    proposal_id = awaiting.steps[0].proposal_id
    assert awaiting.status == "awaiting_approval"
    assert proposal_id

    approved = PolicyProposalQueue(ledger).review(
        proposal_id, approve=True, broker=broker
    )
    assert approved.status == "approved"

    needs_execution = engine.advance(run.run_id, {"propose_action": handler})
    assert needs_execution.status == "awaiting_input"
    assert needs_execution.steps[0].proposal_id == proposal_id

    ledger.append_execution(
        proposal_id,
        status="succeeded",
        action_executed=True,
        verified=False,
        code="test_dispatch",
        summary="A test adapter dispatched the approved action.",
        elapsed_seconds=0.01,
    )
    completed = engine.advance(run.run_id, {"propose_action": handler})
    assert completed.status == "completed"
    assert completed.steps[0].verified is False
    assert completed.steps[0].proposal_id == proposal_id
