# ADR-0017: Reviewed Memory Merge and Lineage

## Status

Accepted

## Context

The local memory consolidator can identify likely duplicate records, but automatic merging risks erasing distinctions, reducing sensitivity labels, extending retention unexpectedly, or losing source provenance.

## Decision

Memory consolidation remains proposal-only. A separate explicit user command may merge exactly two active records after review. The user supplies the resulting content and passes a confirmation flag. The merge transaction:

- requires both records to exist, be active, and share a memory kind;
- refuses to lower sensitivity or raise confidence above the weaker source;
- preserves every source event ID and requires the corresponding event store for provenance validation;
- retains the earliest source expiry and cannot extend retention;
- marks both sources superseded, removes their embeddings and inserts a new active record atomically;
- writes two parent links in a dedicated lineage table so the resulting memory retains both source IDs.

Sensitive sources require a separate explicit CLI opt-in. The merge content is user-authored; no model-generated consolidation is silently accepted.

## Consequences

The memory history remains inspectable through the lineage API and superseded source records. Retrieval continues to exclude superseded and expired records by default. A merge failure leaves all source records unchanged. This is a reviewed data-maintenance operation, not autonomous learning or model retraining.
