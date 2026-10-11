# ADR-0003: Event-Driven Observer and Diagnostic Evidence Pipeline

- **Status:** Accepted
- **Date:** 2026-10-11

## Context
The assistant needs to correlate Windows and browser signals without turning perception into unrestricted surveillance or allowing an inference model to treat uncertain observations as facts.

## Decision
- Providers emit versioned, timestamped observations through the existing event contract.
- Providers are read-only and must not receive action execution capabilities.
- Browser integration is an explicitly enabled extension/native host that exports playback/performance counters only.
- Screen observation is event-driven/hybrid, user-pauseable and data-minimized.
- Diagnostic functions consume normalized metric snapshots and return evidence-linked hypotheses.
- Unknown measurements are represented as unknown, never silently defaulted to zero.
- Remediation is a separate future workflow: proposal, capability policy, approval when required, bounded execution, verification and audit.

## Consequences
This increases the importance of stable event schemas and correlation IDs, but supports explainability, testing and privacy. A browser telemetry bridge and a Windows network sampler must be implemented before video buffering can be diagnosed from live data.
