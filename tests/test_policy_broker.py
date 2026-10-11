import pytest
from pydantic import ValidationError

from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.models import ActionProposal, CapabilityManifest


def manifest(**overrides):
    values = {
        "capability_id": "browser.set_quality",
        "description": "Change the current video's playback quality.",
        "risk_tier": "low",
        "enabled": True,
        "allow_autonomous": True,
        "approval_required": False,
        "allowed_parameters": frozenset({"quality"}),
        "max_invocations_per_minute": 3,
        "max_execution_seconds": 4.0,
    }
    values.update(overrides)
    return CapabilityManifest(**values)


def test_unknown_capabilities_are_denied_by_default():
    broker = CapabilityPolicyBroker()
    decision = broker.evaluate(ActionProposal(capability_id="system.reboot"))

    assert decision.allowed is False
    assert decision.approval_required is False
    assert "default deny" in decision.reason.lower()


def test_disabled_capability_is_denied():
    broker = CapabilityPolicyBroker([manifest(enabled=False)])
    decision = broker.evaluate(
        ActionProposal(capability_id="browser.set_quality", parameters={"quality": "720p"})
    )

    assert decision.allowed is False
    assert "disabled" in decision.reason.lower()


def test_allowlisted_low_risk_capability_can_be_pre_authorized():
    broker = CapabilityPolicyBroker([manifest()])
    decision = broker.evaluate(
        ActionProposal(capability_id="browser.set_quality", parameters={"quality": "720p"})
    )

    assert decision.allowed is True
    assert decision.approval_required is False
    assert decision.max_execution_seconds == 4.0
    assert "no action was executed" in decision.reason.lower()


def test_unknown_parameters_are_denied():
    broker = CapabilityPolicyBroker([manifest()])
    decision = broker.evaluate(
        ActionProposal(
            capability_id="browser.set_quality",
            parameters={"quality": "720p", "url": "https://untrusted.example"},
        )
    )

    assert decision.allowed is False
    assert "outside the capability allowlist" in decision.reason


def test_medium_and_high_risk_require_explicit_approval():
    broker = CapabilityPolicyBroker([
        manifest(
            capability_id="windows.restart_service",
            risk_tier="high",
            allow_autonomous=False,
            approval_required=True,
            allowed_parameters=frozenset({"service_name"}),
        )
    ])
    proposal = ActionProposal(
        capability_id="windows.restart_service",
        parameters={"service_name": "Spooler"},
    )

    without_approval = broker.evaluate(proposal)
    with_approval = broker.evaluate(proposal, user_approved=True)

    assert without_approval.allowed is False
    assert without_approval.approval_required is True
    assert with_approval.allowed is True


def test_critical_capabilities_are_always_blocked():
    broker = CapabilityPolicyBroker([
        manifest(
            capability_id="security.disable_defender",
            risk_tier="critical",
            allow_autonomous=False,
            approval_required=True,
            allowed_parameters=frozenset(),
        )
    ])
    decision = broker.evaluate(
        ActionProposal(capability_id="security.disable_defender"),
        user_approved=True,
    )

    assert decision.allowed is False
    assert decision.approval_required is False
    assert "always blocked" in decision.reason


def test_rate_limit_applies_to_allowed_policy_decisions():
    now = [100.0]
    broker = CapabilityPolicyBroker(
        [manifest(max_invocations_per_minute=2)],
        clock=lambda: now[0],
    )
    proposal = ActionProposal(
        capability_id="browser.set_quality",
        parameters={"quality": "720p"},
    )

    assert broker.evaluate(proposal).allowed is True
    assert broker.evaluate(proposal).allowed is True
    limited = broker.evaluate(proposal)
    assert limited.allowed is False
    assert "rate limit" in limited.reason.lower()

    now[0] += 61.0
    assert broker.evaluate(proposal).allowed is True


def test_autonomous_permission_is_limited_to_low_risk():
    with pytest.raises(ValidationError):
        manifest(risk_tier="medium", allow_autonomous=True)

    with pytest.raises(ValidationError):
        manifest(approval_required=True)
