# ADR-0014: Bounded Declarative Plans

## Status

Accepted

## Context

AIE has explicit task sessions, model request/response contracts, capability policy and
a non-mutating dry-run path. It needs a stable representation for goals decomposed into
dependent steps. Model-produced free-form instructions must not be treated as executable
authority.

## Decision

Introduce a small, typed declarative plan contract with:
- an explicit bounded goal and 1-25 typed steps;
- stable step identifiers, success criteria and explicit dependencies;
- capability identifiers only on `propose_action` steps;
- strict rejection of unknown fields, unresolved dependencies, duplicate IDs and cycles;
- deterministic topological ordering that preserves source order among simultaneously
  ready steps.

A plan is descriptive data. It cannot include arbitrary shell commands, executable
paths, tool arguments, approval state or a capability grant. Action proposals continue
through the existing capability policy broker and human-review path. Readiness queries
do not execute or start work.

## Persisted plan-run lifecycle

A SQLite plan-run store persists the immutable plan definition, step states and
append-only transition records. Starting a step requires all declared dependencies to
have succeeded. Succeeded/failed outcomes require caller-supplied evidence IDs;
cancellation requires an explicit reason and is recorded per unfinished step. State
changes are atomic.

The store records actor labels and evidence references as supplied by its caller. It
does not authenticate actor identity or verify that evidence IDs resolve to trusted
event records; integration code must enforce those checks. It does not execute steps,
grant capabilities, retry failed work or provide rollback.

## Consequences

Planning consumers gain a validated, provider-neutral contract, deterministic dependency
order and persistent workflow bookkeeping. This is not an autonomous planner:
model-backed plan generation, tool selection, execution, postcondition verification,
recovery and learning remain separate work items.
