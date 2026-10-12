# ADR-0016: Persisted Task Orchestration

## Status

Accepted

## Context

A bounded plan validator can establish a deterministic dependency order, but it cannot preserve progress, coordinate human approval or distinguish handler output from verified postconditions.

## Decision

Introduce a persistent task-run state machine backed by local SQLite. A run stores the validated plan, one state record per step, a monotonically increasing version and an append-only lifecycle event journal. Updates use compare-and-swap version checks to prevent concurrent writers from silently overwriting state.

The engine advances at most a caller-bounded number of ready steps and invokes only application-injected handlers. The model planner returns declarative JSON that is validated locally; capability IDs must come from a caller-supplied allowlist. Model reasoning receives the goal, current step and bounded summaries from completed steps; it receives no tools and cannot approve or verify an action.

Approval-waiting action steps retain the corresponding policy proposal ID. They cannot be manually marked complete: a successful execution receipt must first exist in the policy ledger. Verification steps require an explicit positive postcondition assertion. A missing handler pauses for user input.

Pause and cancellation take effect between handler invocations. In-flight application code is not force-killed. An interrupted step is treated as requiring operator review rather than automatically replayed.

## Consequences

Task progress survives process restarts, and state conflicts are explicit. Execution is still capability-gated and the task engine itself has no shell or general-purpose tool access. Model-backed drafting uses only the provider explicitly passed by the caller; the CLI uses local Ollama and does not pull models or attach ambient context.

Automatic recovery/replay, general sandboxing, rollback, desktop notifications, learning from verified outcomes and tool-selection evaluation remain future work.
