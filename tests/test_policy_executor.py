from aie.policy.executor import DryRunExecutor
from aie.policy.models import ActionProposal, PolicyDecision


def test_dry_run_never_executes():
    proposal = ActionProposal(
        proposal_id="p1",
        capability_id="browser.set_quality",
        summary="Set playback quality",
        parameters={"quality": "720p"},
    )
    decision = PolicyDecision(
        proposal_id="p1",
        capability_id="browser.set_quality",
        allowed=True,
        approval_required=False,
        reason="approved",
        risk_tier="low",
        max_execution_seconds=5,
    )

    result = DryRunExecutor().execute(proposal, decision)

    assert result.status == "dry_run"
    assert result.executed is False
    assert result.verified is True


def test_dry_run_rejects_denied_policy():
    proposal = ActionProposal(
        proposal_id="p2",
        capability_id="browser.set_quality",
        summary="Set playback quality",
    )
    decision = PolicyDecision(
        proposal_id="p2",
        capability_id="browser.set_quality",
        allowed=False,
        approval_required=True,
        reason="approval required",
        risk_tier="low",
    )

    result = DryRunExecutor().execute(proposal, decision)

    assert result.status == "rejected"
    assert result.executed is False
    assert result.verified is False


def test_dry_run_rejects_mismatched_decision():
    proposal = ActionProposal(
        proposal_id="p3",
        capability_id="browser.set_quality",
    )
    decision = PolicyDecision(
        proposal_id="different",
        capability_id="browser.set_quality",
        allowed=True,
        approval_required=False,
        reason="approved",
        risk_tier="low",
    )

    try:
        DryRunExecutor().execute(proposal, decision)
    except ValueError as exc:
        assert "proposal ID" in str(exc)
    else:
        raise AssertionError("expected mismatched decision to be rejected")
