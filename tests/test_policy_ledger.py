import json

import pytest
from pydantic import ValidationError

from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
from aie.policy.manifests import CapabilityManifestLoadError, load_capability_manifests
from aie.policy.models import ActionProposal, CapabilityManifest


def make_manifest(**overrides):
    values = {
        "capability_id": "windows.open_settings",
        "description": "Open a named Windows Settings page.",
        "risk_tier": "low",
        "enabled": True,
        "allow_autonomous": False,
        "approval_required": True,
        "allowed_parameters": frozenset({"settings_page"}),
    }
    values.update(overrides)
    return CapabilityManifest(**values)


def test_unknown_capability_is_blocked_and_audited(tmp_path):
    ledger = PolicyLedger(tmp_path / "policy-audit.sqlite3")
    queue = PolicyProposalQueue(ledger)
    proposal = ActionProposal(
        capability_id="windows.restart_unknown_service",
        summary="Request a service restart.",
    )

    result = queue.create(proposal, CapabilityPolicyBroker())

    assert result.status == "blocked"
    assert result.policy_allowed is False
    assert result.action_executed is False
    trail = ledger.audit_trail(proposal.proposal_id)
    assert len(trail) == 1
    assert trail[0]["event_type"] == "policy.proposal.created"


def test_high_risk_proposal_waits_for_explicit_review(tmp_path):
    manifest = make_manifest(
        capability_id="windows.restart_service",
        risk_tier="high",
        allowed_parameters=frozenset({"service_name"}),
    )
    broker = CapabilityPolicyBroker([manifest])
    ledger = PolicyLedger(tmp_path / "policy-audit.sqlite3")
    queue = PolicyProposalQueue(ledger)
    proposal = ActionProposal(
        capability_id="windows.restart_service",
        summary="Restart the print spooler after user approval.",
        parameters={"service_name": "Spooler"},
    )

    pending = queue.create(proposal, broker)
    assert pending.status == "pending_review"
    assert pending.approval_required is True
    assert pending.action_executed is False

    approved = queue.review(proposal.proposal_id, approve=True, broker=broker)
    assert approved.status == "approved"
    assert approved.policy_allowed is True
    assert approved.reviewer == "local_user"
    assert approved.action_executed is False
    assert [row["event_type"] for row in ledger.audit_trail(proposal.proposal_id)] == [
        "policy.proposal.created",
        "policy.proposal.reviewed",
    ]


def test_user_rejection_is_a_final_append_only_transition(tmp_path):
    broker = CapabilityPolicyBroker([make_manifest()])
    ledger = PolicyLedger(tmp_path / "policy-audit.sqlite3")
    queue = PolicyProposalQueue(ledger)
    proposal = ActionProposal(
        capability_id="windows.open_settings",
        summary="Open Windows display settings.",
        parameters={"settings_page": "display"},
    )

    pending = queue.create(proposal, broker)
    assert pending.status == "pending_review"
    rejected = queue.review(proposal.proposal_id, approve=False, broker=broker)

    assert rejected.status == "rejected"
    assert rejected.action_executed is False
    with pytest.raises(ValueError, match="no longer awaiting review"):
        queue.review(proposal.proposal_id, approve=True, broker=broker)

    trail = ledger.audit_trail(proposal.proposal_id)
    assert [item["sequence"] for item in trail] == sorted(item["sequence"] for item in trail)
    assert len(trail) == 2


def test_policy_change_can_block_a_previously_pending_proposal(tmp_path):
    initial = CapabilityPolicyBroker([make_manifest()])
    ledger = PolicyLedger(tmp_path / "policy-audit.sqlite3")
    queue = PolicyProposalQueue(ledger)
    proposal = ActionProposal(
        capability_id="windows.open_settings",
        summary="Open Windows display settings.",
        parameters={"settings_page": "display"},
    )
    assert queue.create(proposal, initial).status == "pending_review"

    now_disabled = CapabilityPolicyBroker([make_manifest(enabled=False)])
    blocked = queue.review(proposal.proposal_id, approve=True, broker=now_disabled)

    assert blocked.status == "blocked"
    assert blocked.policy_allowed is False
    assert blocked.action_executed is False


def test_critical_capability_is_blocked_even_when_reviewed(tmp_path):
    broker = CapabilityPolicyBroker([
        make_manifest(
            capability_id="security.disable_protection",
            risk_tier="critical",
            allowed_parameters=frozenset(),
        )
    ])
    ledger = PolicyLedger(tmp_path / "policy-audit.sqlite3")
    queue = PolicyProposalQueue(ledger)
    proposal = ActionProposal(
        capability_id="security.disable_protection",
        summary="This must remain unsupported.",
    )

    result = queue.create(proposal, broker)

    assert result.status == "blocked"
    assert "always blocked" in result.reason.lower()


def test_duplicate_proposal_id_cannot_be_inserted_twice(tmp_path):
    ledger = PolicyLedger(tmp_path / "policy-audit.sqlite3")
    queue = PolicyProposalQueue(ledger)
    proposal = ActionProposal(
        proposal_id="proposal-stable-1",
        capability_id="unknown.capability",
        summary="Duplicate check.",
    )
    broker = CapabilityPolicyBroker()
    queue.create(proposal, broker)

    with pytest.raises(ValueError, match="already exists"):
        queue.create(proposal, broker)


def test_proposal_rejects_credential_like_and_nested_parameters():
    with pytest.raises(ValidationError, match="credential-like"):
        ActionProposal(
            capability_id="windows.open_settings",
            parameters={"api_token": "do-not-store"},
        )

    with pytest.raises(ValidationError, match="scalar"):
        ActionProposal(
            capability_id="windows.open_settings",
            parameters={"settings_page": {"nested": "not allowed"}},
        )


def test_capability_manifests_load_from_user_directory_and_fail_closed(tmp_path):
    directory = tmp_path / "capabilities"
    directory.mkdir()
    manifest = make_manifest()
    (directory / "open-settings.json").write_text(
        json.dumps(manifest.model_dump(mode="json")),
        encoding="utf-8",
    )

    loaded = load_capability_manifests(directory)
    assert len(loaded) == 1
    assert loaded[0].capability_id == "windows.open_settings"

    (directory / "bad.json").write_text('{"capability_id": "incomplete"}', encoding="utf-8")
    with pytest.raises(CapabilityManifestLoadError):
        load_capability_manifests(directory)
