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
        ledger.reserve_execution(proposal.proposal_id)
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
    ledger.reserve_execution(proposal.proposal_id)
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
        ledger.reserve_execution(proposal.proposal_id)
        ledger.append_execution(
            proposal.proposal_id,
            status="failed",
            action_executed=False,
            verified=False,
            code="duplicate",
            summary="duplicate execution attempt",
            elapsed_seconds=0.01,
        )


def test_execution_reservation_is_exclusive_and_blocks_duplicate_claims(tmp_path):
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
    queue.create(proposal, broker)
    queue.review(proposal.proposal_id, approve=True, broker=broker)

    reserved = ledger.reserve_execution(proposal.proposal_id)
    assert reserved.execution_reserved is True
    with pytest.raises(ValueError, match="already reserved"):
        ledger.reserve_execution(proposal.proposal_id)

    # A reservation without a receipt is intentionally left blocked after an
    # ambiguous attempt; callers must inspect state and cannot automatically retry.
    assert ledger.get(proposal.proposal_id).execution_status is None
    assert ledger.verify_integrity().valid is True


def test_postcondition_verification_is_append_only_and_one_time(tmp_path):
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
    queue.create(proposal, broker)
    queue.review(proposal.proposal_id, approve=True, broker=broker)
    ledger.reserve_execution(proposal.proposal_id)
    ledger.append_execution(
        proposal.proposal_id,
        status="succeeded",
        action_executed=True,
        verified=False,
        code="settings_page_dispatched",
        summary="Dispatch accepted; page state is unknown.",
        elapsed_seconds=0.02,
    )

    verified = ledger.append_postcondition_verification(
        proposal.proposal_id,
        confirmed=True,
        verifier="local_user",
        evidence_code="user_checked_settings_page",
        summary="User confirmed the Display page is visible.",
    )
    assert verified.action_executed is True
    assert verified.execution_status == "succeeded"
    assert verified.execution_verified is True
    assert [item["event_type"] for item in ledger.audit_trail(proposal.proposal_id)][-1] == (
        "policy.proposal.postcondition_verified"
    )
    assert ledger.verify_integrity().valid is True

    with pytest.raises(ValueError, match="already recorded"):
        ledger.append_postcondition_verification(
            proposal.proposal_id,
            confirmed=False,
            verifier="local_user",
            evidence_code="changed_mind",
            summary="A second result must not overwrite the first.",
        )


def test_postcondition_verification_requires_successful_execution_receipt(tmp_path):
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
    queue.create(proposal, broker)
    queue.review(proposal.proposal_id, approve=True, broker=broker)

    with pytest.raises(ValueError, match="execution receipt is required"):
        ledger.append_postcondition_verification(
            proposal.proposal_id,
            confirmed=True,
            verifier="local_user",
            evidence_code="user_checked",
            summary="Cannot verify before dispatch.",
        )

    ledger.reserve_execution(proposal.proposal_id)
    ledger.append_execution(
        proposal.proposal_id,
        status="failed",
        action_executed=True,
        verified=False,
        code="adapter_timeout",
        summary="Dispatch state is ambiguous.",
        elapsed_seconds=5.1,
    )
    with pytest.raises(ValueError, match="successfully dispatched"):
        ledger.append_postcondition_verification(
            proposal.proposal_id,
            confirmed=True,
            verifier="local_user",
            evidence_code="user_checked",
            summary="A failed attempt cannot be marked verified.",
        )
