"""Default-deny authorization broker; intentionally contains no execution tools."""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterable

from aie.policy.models import (
    ActionProposal,
    CapabilityManifest,
    PolicyDecision,
)


class CapabilityPolicyBroker:
    """Authorize narrowly declared actions using least-privilege capability manifests.

    The broker does not execute actions. It provides an auditable policy decision for
    a future executor. Manifests default to disabled; unknown capabilities are denied.
    """

    def __init__(
        self,
        manifests: Iterable[CapabilityManifest] = (),
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._manifests: dict[str, CapabilityManifest] = {}
        self._recent_decisions: dict[str, deque[float]] = {}
        for manifest in manifests:
            if manifest.capability_id in self._manifests:
                raise ValueError(f"Duplicate capability manifest: {manifest.capability_id}")
            self._manifests[manifest.capability_id] = manifest

    def evaluate(
        self,
        proposal: ActionProposal,
        *,
        user_approved: bool = False,
    ) -> PolicyDecision:
        """Return a policy decision. Does not run a process, API call or OS mutation."""
        capability_id = proposal.capability_id
        manifest = self._manifests.get(capability_id)

        if manifest is None:
            return self._decision(
                proposal, allowed=False, approval_required=False,
                reason="No capability manifest is registered; default deny.",
                risk_tier=None,
            )

        if not manifest.enabled:
            return self._decision(
                proposal, allowed=False, approval_required=False,
                reason="Capability is disabled.",
                risk_tier=manifest.risk_tier,
            )

        unknown_parameters = set(proposal.parameters) - set(manifest.allowed_parameters)
        if unknown_parameters:
            names = ", ".join(sorted(unknown_parameters))
            return self._decision(
                proposal, allowed=False, approval_required=False,
                reason=f"Proposal contains parameters outside the capability allowlist: {names}.",
                risk_tier=manifest.risk_tier,
            )

        if manifest.risk_tier == "critical":
            return self._decision(
                proposal, allowed=False, approval_required=False,
                reason="Critical-risk capabilities are unsupported and always blocked.",
                risk_tier=manifest.risk_tier,
            )

        approval_required = (
            manifest.approval_required
            or manifest.risk_tier in {"medium", "high"}
            or not manifest.allow_autonomous
        )
        if approval_required and not user_approved:
            return self._decision(
                proposal, allowed=False, approval_required=True,
                reason="Explicit user approval is required for this action.",
                risk_tier=manifest.risk_tier,
            )

        with self._lock:
            now = self._clock()
            decisions = self._recent_decisions.setdefault(capability_id, deque())
            while decisions and now - decisions[0] >= 60.0:
                decisions.popleft()
            if len(decisions) >= manifest.max_invocations_per_minute:
                return self._decision(
                    proposal, allowed=False, approval_required=False,
                    reason="Capability rate limit exceeded; retry after the rolling window.",
                    risk_tier=manifest.risk_tier,
                )
            decisions.append(now)

        return self._decision(
            proposal, allowed=True, approval_required=False,
            reason="Authorized by the registered capability policy; no action was executed.",
            risk_tier=manifest.risk_tier,
            max_execution_seconds=manifest.max_execution_seconds,
        )

    @staticmethod
    def _decision(
        proposal: ActionProposal,
        *,
        allowed: bool,
        approval_required: bool,
        reason: str,
        risk_tier,
        max_execution_seconds: float | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            proposal_id=proposal.proposal_id,
            capability_id=proposal.capability_id,
            allowed=allowed,
            approval_required=approval_required,
            reason=reason,
            risk_tier=risk_tier,
            max_execution_seconds=max_execution_seconds,
        )
