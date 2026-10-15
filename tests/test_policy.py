from datetime import datetime, timedelta, timezone

from aie.policy import (
    ActionProposal,
    PolicyContext,
    evaluate_proposal,
    proposal_digest,
)


def proposal(action="system.inspect", target="host", params=None, capabilities=("system.inspect",)):
    return ActionProposal(action, target, params or {}, capabilities)


def test_read_only_proposal_allowed_with_explicit_capability():
    decision = evaluate_proposal(
        proposal(),
        PolicyContext(frozenset({"system.inspect"})),
    )
    assert decision.status == "ALLOW"
    assert decision.reason_code == "POLICY_SATISFIED"


def test_write_requires_sandbox_verified_target_capability_and_exact_approval():
    item = proposal("file.write", "C:/safe/file.txt", {"content": "x"}, ("file.write",))
    context = PolicyContext(
        frozenset({"file.write"}), target_verified=True, sandbox_available=True
    )
    pending = evaluate_proposal(item, context)
    assert pending.status == "REQUIRE_APPROVAL"
    approved = PolicyContext(
        frozenset({"file.write"}), target_verified=True, sandbox_available=True,
        approved_proposal_digest=proposal_digest(item),
        approval_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    assert evaluate_proposal(item, approved).status == "ALLOW"
    changed = proposal("file.write", "C:/safe/file.txt", {"content": "different"}, ("file.write",))
    assert evaluate_proposal(changed, approved).status == "REQUIRE_APPROVAL"


def test_missing_capability_unknown_action_and_budget_fail_closed():
    assert evaluate_proposal(
        proposal(), PolicyContext(frozenset())
    ).reason_code == "CAPABILITY_MISSING"
    assert evaluate_proposal(
        proposal("unknown.action"), PolicyContext(frozenset({"unknown.action"}))
    ).reason_code == "UNKNOWN_ACTION"
    assert evaluate_proposal(
        proposal(), PolicyContext(frozenset({"system.inspect"}), actions_used=1, max_actions=1)
    ).reason_code == "BUDGET_EXHAUSTED"


def test_write_proposal_denied_without_target_verification_or_sandbox():
    item = proposal("file.delete", "C:/temp/x", {}, ("file.delete",))
    context = PolicyContext(frozenset({"file.delete"}))
    assert evaluate_proposal(item, context).reason_code == "TARGET_UNVERIFIED"
    verified = PolicyContext(frozenset({"file.delete"}), target_verified=True)
    assert evaluate_proposal(item, verified).reason_code == "SANDBOX_UNAVAILABLE"
