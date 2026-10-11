import pytest

from aie.orchestration.engine import TaskOrchestrator
from aie.orchestration.handlers import PolicyProposalHandler
from aie.orchestration.store import TaskRunStore
from aie.planning.models import PlanStep, TaskPlan
from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
from aie.policy.models import CapabilityManifest


def setup(tmp_path):
    manifest = CapabilityManifest(
        capability_id="windows.settings.open",
        description="Open a fixed Settings page.",
        risk_tier="low",
        enabled=True,
        approval_required=True,
        allow_autonomous=False,
        allowed_parameters=frozenset({"setting"}),
    )
    broker = CapabilityPolicyBroker([manifest])
    ledger = PolicyLedger(tmp_path / "policy.sqlite3")
    engine = TaskOrchestrator(
        TaskRunStore(tmp_path / "runs.sqlite3"),
        policy_ledger=ledger,
    )
    handler = PolicyProposalHandler(
        broker,
        ledger,
        proposal_parameters={"windows.settings.open": {"setting": "display"}},
    )
    plan = TaskPlan(
        goal="Open a reviewed Settings page",
        steps=(
            PlanStep(
                step_id="open",
                kind="propose_action",
                description="Open Display Settings.",
                success_criteria="A dispatch receipt is available.",
                capability_id="windows.settings.open",
            ),
        ),
    )
    return engine, broker, ledger, handler, plan


def test_cancel_revokes_pending_approval_request(tmp_path):
    engine, _, ledger, handler, plan = setup(tmp_path)
    run = engine.create(plan)
    waiting = engine.advance(run.run_id, {"propose_action": handler})
    proposal_id = waiting.steps[0].proposal_id
    assert ledger.get(proposal_id).status == "pending_review"

    cancelled = engine.cancel(run.run_id, reason="user cancelled task")

    assert cancelled.status == "cancelled"
    assert ledger.get(proposal_id).status == "revoked"
    assert ledger.verify_integrity().valid is True


def test_cancel_revokes_approved_but_unexecuted_proposal(tmp_path):
    engine, broker, ledger, handler, plan = setup(tmp_path)
    run = engine.create(plan)
    waiting = engine.advance(run.run_id, {"propose_action": handler})
    proposal_id = waiting.steps[0].proposal_id
    approved = PolicyProposalQueue(ledger).review(
        proposal_id,
        approve=True,
        broker=broker,
    )
    assert approved.status == "approved"

    cancelled = engine.cancel(run.run_id)

    assert cancelled.status == "cancelled"
    assert ledger.get(proposal_id).status == "revoked"
    assert ledger.get(proposal_id).execution_status is None


def test_cancel_preserves_already_executed_action_receipt(tmp_path):
    engine, broker, ledger, handler, plan = setup(tmp_path)
    run = engine.create(plan)
    waiting = engine.advance(run.run_id, {"propose_action": handler})
    proposal_id = waiting.steps[0].proposal_id
    PolicyProposalQueue(ledger).review(proposal_id, approve=True, broker=broker)
    ledger.append_execution(
        proposal_id,
        status="succeeded",
        action_executed=True,
        verified=False,
        code="test_dispatch",
        summary="Action dispatched; state not verified.",
        elapsed_seconds=0.01,
    )

    cancelled = engine.cancel(run.run_id)

    assert cancelled.status == "cancelled"
    snapshot = ledger.get(proposal_id)
    assert snapshot.status == "approved"
    assert snapshot.execution_status == "succeeded"
    assert snapshot.action_executed is True
    assert ledger.verify_integrity().valid is True
