"""Non-mutating executor contract for the autonomy boundary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from aie.policy.models import ActionProposal, PolicyDecision


ExecutionStatus = Literal["dry_run", "rejected"]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    proposal_id: str
    capability_id: str
    status: ExecutionStatus
    executed: bool
    verified: bool
    reason: str


class DryRunExecutor:
    """Validate an approved policy decision without performing any OS mutation."""

    def execute(
        self,
        proposal: ActionProposal,
        decision: PolicyDecision,
    ) -> ExecutionResult:
        if decision.proposal_id != proposal.proposal_id:
            raise ValueError("policy decision does not match proposal ID")
        if decision.capability_id != proposal.capability_id:
            raise ValueError("policy decision does not match capability ID")
        if not decision.allowed:
            return ExecutionResult(
                proposal_id=proposal.proposal_id,
                capability_id=proposal.capability_id,
                status="rejected",
                executed=False,
                verified=False,
                reason="Policy did not authorize execution; no action was performed.",
            )
        return ExecutionResult(
            proposal_id=proposal.proposal_id,
            capability_id=proposal.capability_id,
            status="dry_run",
            executed=False,
            verified=True,
            reason=(
                "Policy authorization is valid for this proposal, but the current "
                "executor is non-mutating dry-run only."
            ),
        )
