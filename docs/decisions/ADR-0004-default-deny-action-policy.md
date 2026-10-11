# ADR-0004: Default-Deny Capability Policy Broker

- **Status:** Accepted
- **Date:** 2026-10-11

## Context
P1- is intended to become an autonomous Windows personal assistant. Perception and model reasoning must not directly execute operating-system actions or infer their own permissions.

## Decision
- All future actions are represented as structured proposals separate from observations.
- Capabilities are explicitly declared in manifests. Missing and disabled capabilities are denied.
- Parameters must match a capability-specific allowlist.
- Only explicitly configured low-risk actions may be pre-authorized for autonomous execution.
- Medium/high-risk actions require an explicit approval signal.
- Critical-risk actions are unsupported and always blocked.
- Capability decisions have bounded rates and maximum execution budgets.
- The initial broker returns a policy decision only; it has no process, PowerShell, UI automation or network mutation executor.

## Consequences
This establishes a policy boundary before the executor is implemented. It also means an allowed policy decision is not proof that an action was executed or verified. Future executor integration requires a separate audit event, least-privilege process boundary, timeout, postcondition check, and recovery design.
