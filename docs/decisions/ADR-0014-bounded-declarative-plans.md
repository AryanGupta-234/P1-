# ADR-0014: Bounded Declarative Plans

## Status

Accepted

## Context

AIE has explicit task sessions, model request contracts, capability policy and a
non-mutating dry-run path. It does not yet have a stable representation for a goal
decomposed into dependent steps. Model-produced free-form instructions must not be
treated as executable authority.

## Decision

Introduce a small, typed declarative plan contract with:
- an explicit bounded goal and 1-25 typed steps;
- stable step identifiers, success criteria and explicit dependencies;
- optional capability identifiers only on `propose_action` steps;
- strict rejection of unknown fields, unresolved dependencies, duplicate IDs and cycles;
- deterministic topological ordering that preserves source order among simultaneously
  ready steps.

A plan is descriptive data. It cannot include arbitrary shell commands, executable
paths, tool arguments, approval state or a capability grant. Action proposals continue
through the existing capability policy broker and human-review path. Readiness queries
do not execute or start work.

## Consequences

Planning consumers gain a validated, provider-neutral contract and deterministic
dependency order. This is a foundation, not an autonomous planner: model-backed plan
generation, plan persistence, step-state transitions, tool selection, execution,
verification and learning remain separate work items.
