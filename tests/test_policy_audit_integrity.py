import json
import sqlite3

from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
from aie.policy.models import ActionProposal, CapabilityManifest


def make_created_ledger(path):
    ledger = PolicyLedger(path)
    proposal = ActionProposal(
        capability_id="unknown.capability",
        summary="Audit chain test proposal.",
    )
    result = PolicyProposalQueue(ledger).create(proposal, CapabilityPolicyBroker())
    return ledger, result.proposal.proposal_id


def test_policy_audit_hash_chain_verifies_created_and_review_events(tmp_path):
    ledger = PolicyLedger(tmp_path / "policy-audit.sqlite3")
    manifest = CapabilityManifest(
        capability_id="windows.open_settings",
        description="Open a named Settings page.",
        risk_tier="low",
        enabled=True,
        approval_required=True,
        allowed_parameters=frozenset({"settings_page"}),
    )
    broker = CapabilityPolicyBroker([manifest])
    proposal = ActionProposal(
        capability_id="windows.open_settings",
        summary="Create a pending proposal, then approve.",
        parameters={"settings_page": "display"},
    )
    queue = PolicyProposalQueue(ledger)
    created = queue.create(proposal, broker)
    assert created.status == "pending_review"
    approved = queue.review(proposal.proposal_id, approve=True, broker=broker)
    assert approved.status == "approved"

    report = ledger.verify_integrity()

    assert report.valid is True
    assert report.checked_entries == 2
    trail = ledger.audit_trail(proposal.proposal_id)
    assert trail[0]["previous_hash"] == "0" * 64
    assert len(trail[0]["entry_hash"]) == 64
    assert trail[1]["previous_hash"] == trail[0]["entry_hash"]
    assert len(trail[1]["entry_hash"]) == 64


def test_policy_audit_detects_payload_modification(tmp_path):
    path = tmp_path / "tampered.sqlite3"
    ledger, proposal_id = make_created_ledger(path)
    assert ledger.verify_integrity().valid is True

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE audit_events SET payload = ? WHERE proposal_id = ?",
            ('{"modified":true}', proposal_id),
        )

    report = ledger.verify_integrity()
    assert report.valid is False
    assert report.first_invalid_sequence == 1
    assert "entry hash" in report.reason


def test_policy_audit_detects_deleted_middle_record(tmp_path):
    path = tmp_path / "deleted.sqlite3"
    ledger = PolicyLedger(path)
    proposal = ActionProposal(
        capability_id="unknown.capability",
        summary="One proposal with two audit records.",
    )
    queue = PolicyProposalQueue(ledger)
    created = queue.create(proposal, CapabilityPolicyBroker())
    # Unknown capability is blocked at creation, so append another separately-created
    # proposal to exercise global chain continuity across proposal IDs.
    queue.create(
        ActionProposal(capability_id="unknown.capability", summary="Second proposal."),
        CapabilityPolicyBroker(),
    )
    assert ledger.verify_integrity().valid is True

    with sqlite3.connect(path) as db:
        db.execute(
            "DELETE FROM audit_events WHERE proposal_id = ?",
            (created.proposal.proposal_id,),
        )

    report = ledger.verify_integrity()
    assert report.valid is False
    assert report.first_invalid_sequence is not None
    assert "previous-hash" in report.reason


def test_old_ledger_schema_is_migrated_and_backfilled(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    payload = json.dumps({
        "schema_version": 1,
        "proposal": {
            "proposal_id": "legacy-proposal",
            "capability_id": "unknown.capability",
            "summary": "Legacy proposal.",
            "parameters": {},
            "source": "assistant",
        },
        "status": "blocked",
        "policy": {
            "allowed": False,
            "approval_required": False,
            "reason": "legacy",
            "risk_tier": None,
            "max_execution_seconds": None,
            "action_executed": False,
        },
        "reviewer": None,
        "action_executed": False,
    })
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_id TEXT NOT NULL UNIQUE,
                proposal_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL
            )"""
        )
        db.execute(
            """INSERT INTO audit_events
            (audit_id, proposal_id, event_type, timestamp, payload)
            VALUES (?, ?, ?, ?, ?)""",
            (
                "legacy-audit-id",
                "legacy-proposal",
                "policy.proposal.created",
                "2026-10-11T07:00:00+00:00",
                payload,
            ),
        )

    ledger = PolicyLedger(path)
    report = ledger.verify_integrity()
    assert report.valid is True
    assert report.checked_entries == 1
    assert len(ledger.audit_trail("legacy-proposal")[0]["entry_hash"]) == 64


def test_policy_audit_detects_tail_truncation_with_head_checkpoint(tmp_path):
    path = tmp_path / "truncated.sqlite3"
    ledger, proposal_id = make_created_ledger(path)
    assert ledger.verify_integrity().valid is True

    with sqlite3.connect(path) as db:
        db.execute(
            "DELETE FROM audit_events WHERE proposal_id = ?",
            (proposal_id,),
        )

    report = ledger.verify_integrity()
    assert report.valid is False
    assert report.checked_entries == 0
    assert "head checkpoint" in report.reason
