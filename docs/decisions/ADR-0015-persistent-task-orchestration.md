# ADR-0015: Persistent Policy-Mediated Task Orchestration

## Status

Accepted

## Context

AIE now has typed declarative plans, local model routing, normalized local observations,
persistent memory and a default-deny capability policy. It still needs a task lifecycle
that can persist progress, coordinate bounded step handlers and recover after interruption
without replaying ambiguous work.

## Decision

Introduce a local SQLite task-run store and a one-step-at-a-time orchestrator.

- A run stores the validated plan, explicit step states, bounded summaries, at most 20
  evidence IDs per step, proposal references and lifecycle events.
- Steps are claimed transactionally only after all declared dependencies are complete.
- Model-backed plan generation is local-only and accepts only strict JSON that validates
  against the declarative plan schema and the enabled capability-ID allowlist.
- Observation handlers may return event IDs and coarse metadata summaries, not raw event
  payloads. Reasoning uses local inference over the goal and completed-step summaries.
- Missing step handlers, handler exceptions and malformed outcomes fail closed.
- Action steps create proposals in the existing policy ledger and pause for explicit
  review. A reviewed approval is recorded as authorized-but-unexecuted; the task remains
  blocked until a separately reviewed real executor is available.
- Cancellation is checked at step boundaries. A process restart that finds an in-flight
  step marks it failed for manual inspection; it is never automatically replayed.

## Consequences

Task progress becomes durable, inspectable and resumable at safe boundaries. The
orchestrator does not turn model output into arbitrary code or grant capabilities.
Verification steps require an explicit verifier handler; no LLM-generated statement is
treated as proof that a system state changed.

Real OS mutation, OS-enforced sandboxing, postcondition verification and rollback remain
separate work and are not enabled by this ADR.
