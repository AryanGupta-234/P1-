import pytest

from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
from aie.policy.models import ActionProposal, CapabilityManifest


def test_execution_receipt_is_single_attempt_and_part_of_hash_chain(tmp_path):
    manifest = CapabilityManifest(
        capability_id="windows.settings.open",
        description="Open one fixed Windows Settings page.",
        risk_tier="low",
        enabled=True,
        approval_required=True,
        allowed_parameters=frozenset({"setting"}),
    )
    broker = CapabilityPolicyBroker([manifest])
    ledger = PolicyLedger(tmp_path / "policy.sqlite3")
    proposal = ActionProposal(
        capability_id=manifest.capability_id,
        summary="Open Display.",
        parameters={"setting": "display"},
    )
    queue = PolicyProposalQueue(ledger)
    created = queue.create(proposal, broker)
    assert created.status == "pending_review"

    with pytest.raises(ValueError, match="only approved proposals"):
        ledger.append_execution(
            proposal.proposal_id,
            status="succeeded",
            action_executed=True,
            verified=False,
            code="test",
            summary="must not record",
            elapsed_seconds=0.01,
        )

    queue.review(proposal.proposal_id, approve=True, broker=broker)
    executed = ledger.append_execution(
        proposal.proposal_id,
        status="succeeded",
        action_executed=True,
        verified=False,
        code="test_dispatch",
        summary="Dispatched but not postcondition-verified.",
        elapsed_seconds=0.02,
    )
    assert executed.action_executed is True
    assert executed.execution_status == "succeeded"
    assert executed.execution_verified is False
    assert ledger.verify_integrity().valid is True

    with pytest.raises(ValueError, match="already has an execution receipt"):
        ledger.append_execution(
            proposal.proposal_id,
            status="failed",
            action_executed=False,
            verified=False,
            code="duplicate",
            summary="duplicate execution attempt",
            elapsed_seconds=0.01,
        )
