# ADR-0021: One-time execution reservation in the policy ledger

## Status

Accepted

## Context

The registered capability executor must prevent two workers from dispatching the same approved proposal. A receipt appended only after dispatch leaves a crash window: the operating-system side effect may have started while the ledger still looks unexecuted. Cancellation must also distinguish an approved-but-not-started proposal from an execution that has crossed the dispatch boundary.

## Decision

Before invoking an adapter, the executor atomically calls `PolicyLedger.reserve_execution`. The reservation is appended as `policy.proposal.execution_reserved` to the existing SHA-256 hash chain within a `BEGIN IMMEDIATE` SQLite transaction.

A reservation is a one-time claim. A second reservation is rejected even when no execution receipt exists. The later execution receipt is accepted only for an approved proposal with a durable reservation and no prior receipt. A crash after reservation leaves an intentionally ambiguous, non-replayable state; the application must not guess whether the adapter crossed the side-effect boundary.

Proposal revocation checks the complete append-only history and refuses to revoke a proposal once a reservation or receipt exists. Task cancellation derives the deterministic proposal ID for each declared action step when a task checkpoint may be missing the ID; it inspects only those IDs and never sweeps unrelated ledger entries.

Execution enablement is represented by a regular local marker file. Symlink or non-file enable markers never enable mutation. Any existing kill-switch filesystem object, including a symlink or directory, is treated as active. Marker creation is exclusive and does not follow existing symlinks.

## Consequences

A process crash after reservation but before a receipt leaves the proposal reserved and non-revocable. It does not cause automatic replay or a second adapter dispatch. The operator must inspect possible side effects and cancel/replace the task as appropriate. This favors duplicate-action prevention over automatic recovery. The reservation is an audit boundary, not proof that the adapter actually dispatched an operation.
