# ADR-0011: Fail-Closed Execution Control

## Status

Accepted

## Context

AIE's policy broker and dry-run executor establish authorization without mutation.
Before a real executor can exist, there must be an independent runtime gate that fails
closed even if policy evaluation succeeds.

## Decision

Provide an execution control surface with:

- a positive local enable marker; absence means mutation is disabled;
- a global kill-switch marker that overrides enablement;
- bounded execution budgets for wall-clock time, output bytes and process count;
- network and filesystem write permissions defaulting to false;
- privileged execution rejected by the budget contract.

The current dry-run executor does not require the enable marker because it performs no
OS mutation. A future mutating executor must call the gate before dispatching any action.

## Consequences

This separates authorization from runtime availability. Approval alone cannot make a
future executor run when the global gate is disabled or killed. Resource budgets become
a typed boundary for sandbox/resource enforcement rather than unbounded executor options.

The control markers themselves do not execute actions. A future user interface must make
enable/disable/kill-switch changes explicit and auditable.
