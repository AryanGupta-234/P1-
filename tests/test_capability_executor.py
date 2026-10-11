from types import SimpleNamespace

import pytest

import aie.policy.capabilities as capabilities
from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.capabilities import (
    ActionExecutionDenied,
    CapabilityRegistry,
    PolicyControlledExecutor,
)
from aie.policy.execution_control import ExecutionControl
from aie.policy.ledger import PolicyLedger, PolicyProposalQueue
from aie.policy.models import ActionProposal, CapabilityManifest


def setup_approved_proposal(tmp_path):
    manifest = CapabilityManifest(
        capability_id="windows.settings.open",
        description="Open one fixed Windows Settings page.",
        risk_tier="low",
        enabled=True,
        allow_autonomous=False,
        approval_required=True,
        allowed_parameters=frozenset({"setting"}),
        max_execution_seconds=5.0,
    )
    broker = CapabilityPolicyBroker([manifest])
    ledger = PolicyLedger(tmp_path / "policy.sqlite3")
    proposal = ActionProposal(
        capability_id="windows.settings.open",
        summary="Open Display settings.",
        parameters={"setting": "display"},
        source="test",
    )
    queue = PolicyProposalQueue(ledger)
    created = queue.create(proposal, broker)
    assert created.status == "pending_review"
    approved = queue.review(proposal.proposal_id, approve=True, broker=broker)
    assert approved.status == "approved"
    control = ExecutionControl(
        enabled_path=tmp_path / "execution.enabled",
        kill_switch_path=tmp_path / "execution.kill",
    )
    return manifest, broker, ledger, proposal, control


def test_execution_requires_gate_and_explicit_approval(tmp_path, monkeypatch):
    manifest, broker, ledger, proposal, control = setup_approved_proposal(tmp_path)
    called = []
    monkeypatch.setattr(
        capabilities,
        "os",
        SimpleNamespace(name="nt", startfile=lambda uri: called.append(uri)),
    )
    executor = PolicyControlledExecutor(
        broker=broker,
        ledger=ledger,
        manifests=[manifest],
        registry=CapabilityRegistry.windows_safe_defaults(),
        control=control,
    )

    with pytest.raises(ActionExecutionDenied):
        executor.execute(proposal.proposal_id)
    assert called == []
    assert ledger.get(proposal.proposal_id).execution_status is None

    control.set_enabled(True)
    receipt = executor.execute(proposal.proposal_id)
    assert receipt.status == "succeeded"
    assert receipt.executed is True
    assert receipt.verified is False
    assert called == ["ms-settings:display"]
    snapshot = ledger.get(proposal.proposal_id)
    assert snapshot.action_executed is True
    assert snapshot.execution_status == "succeeded"
    assert snapshot.execution_verified is False

    with pytest.raises(ActionExecutionDenied, match="already has an execution attempt"):
        executor.execute(proposal.proposal_id)


def test_kill_switch_overrides_positive_enable_marker(tmp_path):
    manifest, broker, ledger, proposal, control = setup_approved_proposal(tmp_path)
    control.set_enabled(True)
    control.set_kill_switch(True)
    executor = PolicyControlledExecutor(
        broker=broker,
        ledger=ledger,
        manifests=[manifest],
        registry=CapabilityRegistry.windows_safe_defaults(),
        control=control,
    )
    with pytest.raises(RuntimeError, match="kill switch"):
        executor.execute(proposal.proposal_id)


def test_unallowlisted_setting_is_not_dispatched_and_is_audited(tmp_path, monkeypatch):
    manifest, broker, ledger, proposal, control = setup_approved_proposal(tmp_path)
    bad = ActionProposal(
        proposal_id=proposal.proposal_id,
        capability_id=proposal.capability_id,
        summary=proposal.summary,
        parameters={"setting": "unknown"},
        source=proposal.source,
    )
    # The immutable ledger is the source of truth; a different in-memory proposal
    # cannot be substituted after review.
    called = []
    monkeypatch.setattr(
        capabilities,
        "os",
        SimpleNamespace(name="nt", startfile=lambda uri: called.append(uri)),
    )
    control.set_enabled(True)
    registry = CapabilityRegistry.windows_safe_defaults()
    adapter = registry.get(manifest.capability_id)
    from aie.policy.capabilities import AdapterResult

    class InvalidAdapter:
        capability_id = manifest.capability_id

        def execute(self, proposal, *, budget):
            return adapter.execute(bad, budget=budget)

    executor = PolicyControlledExecutor(
        broker=broker,
        ledger=ledger,
        manifests=[manifest],
        registry=CapabilityRegistry([InvalidAdapter()]),
        control=control,
    )
    receipt = executor.execute(proposal.proposal_id)
    assert receipt.status == "failed"
    assert receipt.executed is False
    assert called == []
    assert ledger.get(proposal.proposal_id).execution_status == "failed"


def test_registry_rejects_duplicate_adapters():
    class Adapter:
        capability_id = "sample.capability"

    with pytest.raises(ValueError, match="duplicate capability adapter"):
        CapabilityRegistry([Adapter(), Adapter()])
