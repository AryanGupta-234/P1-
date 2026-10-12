# ADR-0015: Registered Capability Executor

## Status

Accepted

## Context

The policy broker and review ledger previously stopped at authorization and dry-run validation. AIE needs a narrow bridge from a reviewed proposal to a real operation without exposing a generic command runner or allowing model output to select arbitrary executables.

## Decision

Introduce an application-owned capability registry. A proposal can execute only when all of the following hold:

1. Its immutable policy-ledger state is explicitly approved.
2. The complete SHA-256 audit chain verifies.
3. The current manifest is present and enabled.
4. The policy broker re-evaluates the proposal and allows it under the current manifest.
5. The positive execution-enable marker exists and the global kill switch is absent.
6. A trusted in-process adapter is registered for the exact capability ID.
7. The adapter validates its own fixed argument schema and receives a bounded execution budget.

The initial built-in adapter is `windows.settings.open`. It can dispatch only seven fixed Windows Settings URIs. It cannot edit settings, invoke a shell, launch arbitrary executables, write files, access the network or elevate privileges.

Each proposal receives at most one execution attempt. The result is appended to the existing SHA-256 chained ledger. A URI dispatch receipt is not considered proof that the intended settings page or postcondition was reached.

## Consequences

The execution gate is disabled by default and requires a separate user confirmation to enable. Approval and execution remain distinct actions. Additional adapters must be reviewed, explicitly registered in application code, and tested for argument validation, budgets, failure behavior and postconditions.

This adapter framework is not an OS-process sandbox. Adapter code executes in-process and is trusted application code. Arbitrary command execution and autonomous remediation remain out of scope until process isolation, recovery and verification are implemented.
