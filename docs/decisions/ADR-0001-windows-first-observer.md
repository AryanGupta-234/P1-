# ADR-0001: Windows-first read-only observer

- **Status:** Accepted
- **Date:** 2026-10-11

## Context
The initial target is a Windows desktop. Environmental understanding is the first dependency; unrestricted monitoring and actions create avoidable risk.

## Decision
Build a Windows-only, read-only observer. Normalize observations into versioned events and persist locally in SQLite. Start with supported user-mode APIs and process-state reconciliation. Define a provider boundary for future ETW/Event Log sources.

## Consequences
- No Linux/WSL collectors.
- No LLM or cloud dependency for observation.
- No action execution capability in the observer.
- Snapshot reconciliation is best-effort and can miss short-lived processes until ETW is integrated.
- Driver work requires a separate threat model, code signing and security review.
