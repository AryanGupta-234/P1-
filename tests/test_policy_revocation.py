import pytest

from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
from aie.policy.models import ActionProposal, CapabilityManifest


def prepared(tmp_path):
    manifest = CapabilityManifest(
        capability_id="windows.settings.open",
        description="Open a fixed Windows Settings page.",
        risk_tier="low",
        enabled=True,
        approval_required=True,
        allowed_parameters=frozenset({"setting"}),
    )
    broker = CapabilityPolicyBroker([manifest])
    ledger = PolicyLedger(tmp_path / "policy.sqlite3")
    proposal = ActionProposal(
        capability_id=manifest.capability_id,
        summary="Open Display Settings.",
        parameters={"setting": "display"},
        source="task-cancel-test",
    )
    queue = PolicyProposalQueue(ledger)
    queue.create(proposal, broker)
    return broker, ledger, queue, proposal


def test_pending_and_approved_proposals_can_be_immutably_revoked(tmp_path):
    broker, ledger, queue, proposal = prepared(tmp_path)
    pending = ledger.append_revocation(
        proposal.proposal_id,
        reason="task cancelled before review",
    )
    assert pending.status == "revoked"
    assert "task cancelled" in pending.reason
    with pytest.raises(ValueError, match="only pending or approved"):
        queue.review(proposal.proposal_id, approve=True, broker=broker)

    _, ledger2, queue2, proposal2 = prepared(tmp_path / "approved")
    approved = queue2.review(proposal2.proposal_id, approve=True, broker=broker)
    assert approved.status == "approved"
    revoked = ledger2.append_revocation(
        proposal2.proposal_id,
        reason="task cancelled before execution",
    )
    assert revoked.status == "revoked"
    assert revoked.policy_allowed is False
    assert ledger2.verify_integrity().valid is True


def test_execution_attempt_cannot_be_revoked(tmp_path):
    broker, ledger, queue, proposal = prepared(tmp_path)
    queue.review(proposal.proposal_id, approve=True, broker=broker)
    ledger.append_execution(
        proposal.proposal_id,
        status="succeeded",
        action_executed=True,
        verified=False,
        code="test_dispatch",
        summary="The action was dispatched.",
        elapsed_seconds=0.01,
    )
    with pytest.raises(ValueError, match="execution attempt cannot be revoked"):
        ledger.append_revocation(
            proposal.proposal_id,
            reason="too late",
        )
    assert ledger.get(proposal.proposal_id).execution_status == "succeeded"
