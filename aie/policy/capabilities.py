"""Registered, least-privilege action adapters behind the policy and kill-switch gates."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from aie.policy.broker import CapabilityPolicyBroker
from aie.policy.execution_control import ExecutionBlocked, ExecutionBudget, ExecutionControl
from aie.policy.ledger import PolicyLedger
from aie.policy.models import ActionProposal, CapabilityManifest


@dataclass(frozen=True, slots=True)
class AdapterResult:
    status: Literal["succeeded", "failed"]
    executed: bool
    verified: bool
    code: str
    summary: str

    def __post_init__(self) -> None:
        if self.verified and not self.executed:
            raise ValueError("an unexecuted adapter result cannot be verified")
        if not self.code or len(self.code) > 80:
            raise ValueError("adapter result code must contain 1 to 80 characters")
        if not self.summary or len(self.summary) > 300:
            raise ValueError("adapter summary must contain 1 to 300 characters")


@dataclass(frozen=True, slots=True)
class ActionExecutionReceipt:
    proposal_id: str
    capability_id: str
    status: Literal["succeeded", "failed"]
    executed: bool
    verified: bool
    code: str
    summary: str
    elapsed_seconds: float


class CapabilityAdapter(Protocol):
    capability_id: str

    def execute(
        self,
        proposal: ActionProposal,
        *,
        budget: ExecutionBudget,
    ) -> AdapterResult:
        """Run one explicitly registered, bounded capability."""
        ...


class CapabilityRegistry:
    """Registry of application-owned adapters; manifests never import executable code."""

    def __init__(self, adapters: list[CapabilityAdapter] | tuple[CapabilityAdapter, ...] = ()) -> None:
        self._adapters: dict[str, CapabilityAdapter] = {}
        for adapter in adapters:
            capability_id = getattr(adapter, "capability_id", None)
            if not isinstance(capability_id, str) or not capability_id:
                raise ValueError("registered adapters require a capability_id")
            if capability_id in self._adapters:
                raise ValueError(f"duplicate capability adapter: {capability_id}")
            self._adapters[capability_id] = adapter

    def get(self, capability_id: str) -> CapabilityAdapter | None:
        return self._adapters.get(capability_id)

    @classmethod
    def windows_safe_defaults(cls) -> "CapabilityRegistry":
        """Return the small built-in Windows adapter set; no shell or arbitrary process."""
        return cls([WindowsSettingsOpenAdapter()])


class WindowsSettingsOpenAdapter:
    """Open one fixed Windows Settings page; it cannot change the selected setting."""

    capability_id = "windows.settings.open"
    _URIS = {
        "display": "ms-settings:display",
        "sound": "ms-settings:sound",
        "bluetooth": "ms-settings:bluetooth",
        "network": "ms-settings:network-status",
        "windows_update": "ms-settings:windowsupdate",
        "apps": "ms-settings:appsfeatures",
        "privacy": "ms-settings:privacy",
    }

    def execute(
        self,
        proposal: ActionProposal,
        *,
        budget: ExecutionBudget,
    ) -> AdapterResult:
        if os.name != "nt":
            return AdapterResult(
                status="failed",
                executed=False,
                verified=False,
                code="windows_only",
                summary="Windows Settings adapter is unavailable on this platform.",
            )
        if set(proposal.parameters) != {"setting"}:
            return AdapterResult(
                status="failed",
                executed=False,
                verified=False,
                code="invalid_parameters",
                summary="A single allowlisted setting key is required.",
            )
        setting = proposal.parameters.get("setting")
        if not isinstance(setting, str) or setting not in self._URIS:
            return AdapterResult(
                status="failed",
                executed=False,
                verified=False,
                code="setting_not_allowlisted",
                summary="The requested Settings page is not allowlisted.",
            )
        if budget.max_seconds <= 0:
            return AdapterResult(
                status="failed",
                executed=False,
                verified=False,
                code="invalid_budget",
                summary="The execution budget is invalid.",
            )
        startfile = getattr(os, "startfile", None)
        if not callable(startfile):
            return AdapterResult(
                status="failed",
                executed=False,
                verified=False,
                code="startfile_unavailable",
                summary="Windows URI dispatch is unavailable in this Python runtime.",
            )
        try:
            startfile(self._URIS[setting])
        except OSError:
            return AdapterResult(
                status="failed",
                executed=False,
                verified=False,
                code="uri_dispatch_failed",
                summary="Windows did not accept the Settings URI request.",
            )
        return AdapterResult(
            status="succeeded",
            executed=True,
            verified=False,
            code="settings_page_dispatched",
            summary=f"Requested the Windows Settings page: {setting}. Page state is not verified.",
        )


class ActionExecutionDenied(PermissionError):
    """Raised when execution lacks an approved proposal, policy or registered adapter."""


class PolicyControlledExecutor:
    """Execute only approved proposals via trusted adapters and an explicit local gate."""

    def __init__(
        self,
        *,
        broker: CapabilityPolicyBroker,
        ledger: PolicyLedger,
        manifests: list[CapabilityManifest] | tuple[CapabilityManifest, ...],
        registry: CapabilityRegistry,
        control: ExecutionControl,
        clock=time.monotonic,
    ) -> None:
        self.broker = broker
        self.ledger = ledger
        self.manifests = {item.capability_id: item for item in manifests}
        self.registry = registry
        self.control = control
        self.clock = clock

    def execute(self, proposal_id: str) -> ActionExecutionReceipt:
        snapshot = self.ledger.get(proposal_id)
        if snapshot is None:
            raise ActionExecutionDenied("proposal was not found")
        if snapshot.status != "approved":
            raise ActionExecutionDenied("proposal must be explicitly approved first")
        if snapshot.execution_status is not None:
            raise ActionExecutionDenied("proposal already has an execution attempt")
        integrity = self.ledger.verify_integrity()
        if not integrity.valid:
            raise ActionExecutionDenied("policy audit chain failed integrity verification")

        # A positive enable marker and an absent kill switch are both mandatory.
        self.control.require_mutation_allowed()

        proposal = snapshot.proposal
        manifest = self.manifests.get(proposal.capability_id)
        if manifest is None or not manifest.enabled:
            raise ActionExecutionDenied("capability has no enabled local manifest")
        adapter = self.registry.get(proposal.capability_id)
        if adapter is None:
            raise ActionExecutionDenied("no trusted adapter is registered for this capability")

        decision = self.broker.evaluate(proposal, user_approved=True)
        if not decision.allowed:
            raise ActionExecutionDenied(f"current policy denied execution: {decision.reason}")
        max_seconds = min(
            manifest.max_execution_seconds,
            decision.max_execution_seconds or manifest.max_execution_seconds,
        )
        budget = ExecutionBudget(max_seconds=max_seconds)
        started = self.clock()
        try:
            result = adapter.execute(proposal, budget=budget)
            if not isinstance(result, AdapterResult):
                raise TypeError("capability adapter must return AdapterResult")
        except Exception as exc:  # noqa: BLE001 - record bounded failure without exception payloads.
            result = AdapterResult(
                status="failed",
                executed=False,
                verified=False,
                code=f"adapter_{type(exc).__name__[:60]}",
                summary="Capability adapter failed; inspect local diagnostics.",
            )
        elapsed = max(0.0, self.clock() - started)
        # Adapters are trusted application code and must enforce their own deadline.
        # A late return is recorded as failed; it is never represented as verified.
        if elapsed > max_seconds and result.status == "succeeded":
            result = AdapterResult(
                status="failed",
                executed=result.executed,
                verified=False,
                code="execution_budget_exceeded",
                summary="Adapter returned after its declared execution budget.",
            )

        self.ledger.append_execution(
            proposal_id,
            status=result.status,
            action_executed=result.executed,
            verified=result.verified,
            code=result.code,
            summary=result.summary,
            elapsed_seconds=elapsed,
        )
        return ActionExecutionReceipt(
            proposal_id=proposal.proposal_id,
            capability_id=proposal.capability_id,
            status=result.status,
            executed=result.executed,
            verified=result.verified,
            code=result.code,
            summary=result.summary,
            elapsed_seconds=elapsed,
        )
