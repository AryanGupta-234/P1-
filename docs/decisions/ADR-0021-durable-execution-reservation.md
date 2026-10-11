# ADR-0021: Durable execution reservation in the policy ledger

## Status

Accepted

## Context

The registered capability executor must prevent two workers from dispatching the same approved proposal. A receipt appended only after dispatch leaves a crash window: the operating-system side effect may have started while the ledger still looks unexecuted. Cancellation must also distinguish an approved-but-not-started proposal from an execution that has crossed the dispatch boundary.

## Decision

Before invoking an adapter, the executor atomically calls `PolicyLedger.reserve_execution`. The reservation is appended as `policy.proposal.execution_reserved` to the existing SHA-256 hash chain within a `BEGIN IMMEDIATE` SQLite transaction. The reservation is idempotent while no receipt exists, but a receipt prevents another reservation. The later execution receipt is accepted only for an approved proposal with a durable reservation and no prior receipt.

Proposal revocation checks the complete append-only history and refuses to revoke a proposal once a reservation or receipt exists. Task cancellation derives the deterministic proposal ID for each declared action step when a task checkpoint may be missing the ID; it inspects only those IDs and never sweeps unrelated ledger entries.

## Consequences

A process crash after reservation but before a receipt leaves the proposal reserved and non-revocable. It does not cause automatic replay. An operator must inspect possible side effects and resolve the task manually. This favors duplicate-action prevention over automatic recovery. The reservation is an audit boundary, not proof that the adapter actually dispatched an operation.
