"""Non-executing capability and approval policy broker foundation.

This module evaluates proposals only. It has no OS, shell, filesystem or UI executor.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ActionRule:
    risk: str
    write: bool
    approval_required: bool
    verify_target: bool


ACTION_RULES = {
    "system.inspect": ActionRule("low", False, False, False),
    "process.list": ActionRule("low", False, False, False),
    "file.read": ActionRule("low", False, False, True),
    "window.inspect": ActionRule("low", False, False, True),
    "file.write": ActionRule("moderate", True, True, True),
    "app.launch": ActionRule("moderate", True, True, True),
    "file.delete": ActionRule("high", True, True, True),
    "process.terminate": ActionRule("high", True, True, True),
    "message.send": ActionRule("high", True, True, True),
    "purchase": ActionRule("critical", True, True, True),
    "submit": ActionRule("high", True, True, True),
    "install": ActionRule("critical", True, True, True),
    "security.modify": ActionRule("critical", True, True, True),
    "shell.execute": ActionRule("critical", True, True, True),
}


@dataclass(frozen=True)
class ActionProposal:
    action: str
    target: str
    parameters: dict[str, Any]
    requested_capabilities: tuple[str, ...]


@dataclass(frozen=True)
class PolicyContext:
    granted_capabilities: frozenset[str]
    target_verified: bool = False
    sandbox_available: bool = False
    actions_used: int = 0
    max_actions: int = 1
    approved_proposal_digest: str | None = None
    approval_expires_at: datetime | None = None


@dataclass(frozen=True)
class PolicyDecision:
    status: str
    reason_code: str
    reason: str
    proposal_digest: str
    risk: str


def proposal_digest(proposal: ActionProposal) -> str:
    """Stable approval binding: changing any parameter invalidates prior approval."""
    if not isinstance(proposal, ActionProposal):
        raise ValueError("proposal must be an ActionProposal")
    try:
        encoded = json.dumps(
            {
                "action": proposal.action,
                "target": proposal.target,
                "parameters": proposal.parameters,
                "requested_capabilities": sorted(proposal.requested_capabilities),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("proposal must contain finite JSON parameters") from exc
    return hashlib.sha256(encoded).hexdigest()


def evaluate_proposal(
    proposal: ActionProposal,
    context: PolicyContext,
    *,
    now: datetime | None = None,
) -> PolicyDecision:
    """Evaluate capability, target, sandbox, budget and approval gates; never execute."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(proposal.action, str) or not isinstance(proposal.target, str):
        raise ValueError("proposal action and target must be strings")
    if not proposal.action or not proposal.target or not isinstance(proposal.parameters, dict):
        raise ValueError("proposal action, target and parameters are required")
    if not isinstance(context, PolicyContext):
        raise ValueError("context must be a PolicyContext")
    if (
        not isinstance(proposal.requested_capabilities, (tuple, list))
        or any(not isinstance(item, str) or not item for item in proposal.requested_capabilities)
    ):
        raise ValueError("requested_capabilities must be a sequence of non-empty strings")
    if (
        not isinstance(context.granted_capabilities, (set, frozenset))
        or any(not isinstance(item, str) or not item for item in context.granted_capabilities)
    ):
        raise ValueError("granted_capabilities must be a set of non-empty strings")
    if not isinstance(context.target_verified, bool) or not isinstance(context.sandbox_available, bool):
        raise ValueError("target_verified and sandbox_available must be booleans")
    digest = proposal_digest(proposal)
    rule = ACTION_RULES.get(proposal.action)
    if rule is None:
        return PolicyDecision("DENY", "UNKNOWN_ACTION", "Action is not in the reviewed allowlist.", digest, "unknown")
    if not isinstance(context.max_actions, int) or isinstance(context.max_actions, bool) or context.max_actions < 1:
        raise ValueError("max_actions must be a positive integer")
    if not isinstance(context.actions_used, int) or isinstance(context.actions_used, bool) or context.actions_used < 0:
        raise ValueError("actions_used must be a non-negative integer")
    if context.actions_used >= context.max_actions:
        return PolicyDecision("DENY", "BUDGET_EXHAUSTED", "Action budget is exhausted.", digest, rule.risk)
    required = set(proposal.requested_capabilities)
    if (
        not required
        or any(not isinstance(item, str) or not item for item in required)
        or proposal.action not in required
    ):
        return PolicyDecision("DENY", "INVALID_CAPABILITY", "The exact action capability must be explicitly requested.", digest, rule.risk)
    if not required.issubset(context.granted_capabilities):
        return PolicyDecision("DENY", "CAPABILITY_MISSING", "One or more requested capabilities were not granted.", digest, rule.risk)
    if rule.verify_target and not context.target_verified:
        return PolicyDecision("DENY", "TARGET_UNVERIFIED", "Target identity must be verified before this action.", digest, rule.risk)
    if rule.write and not context.sandbox_available:
        return PolicyDecision("DENY", "SANDBOX_UNAVAILABLE", "Write-capable actions require an available sandbox.", digest, rule.risk)
    if rule.approval_required:
        approved = context.approved_proposal_digest == digest
        expiry = context.approval_expires_at
        if not approved or expiry is None:
            return PolicyDecision("REQUIRE_APPROVAL", "APPROVAL_REQUIRED", "This proposal requires explicit approval bound to its exact parameters.", digest, rule.risk)
        if (
            not isinstance(expiry, datetime)
            or expiry.tzinfo is None or expiry.utcoffset() is None or expiry <= now
        ):
            return PolicyDecision("DENY", "APPROVAL_EXPIRED", "The proposal approval is expired or invalid.", digest, rule.risk)
    return PolicyDecision("ALLOW", "POLICY_SATISFIED", "Proposal passed policy checks; no action was executed.", digest, rule.risk)
