# ADR-0006: Explicit Local Memory and Privacy Boundary

- **Status:** Accepted
- **Date:** 2026-10-11

## Context
AIE needs persistent context across runs, but automatically promoting observations or model outputs into durable memory risks retaining sensitive or incorrect information. Memory must have provenance, expiry, correction and deletion semantics before retrieval is used for planning.

## Decision
- Memory writes require an explicit user command or a reviewed application call. No sensor, browser collector or model response silently creates a memory.
- Memory records are typed as working, episodic, semantic, procedural or prospective and may carry tags, sensitivity, confidence, source-event IDs, TTL and a supersession pointer.
- Source-event IDs are validated against the local event store at write time.
- Corrections create a new record and mark the prior record superseded; prior versions remain inspectable until deleted or expired.
- Retrieval uses deterministic local keyword/tag overlap in this phase. It is not semantic embedding retrieval and is not described as such.
- Sensitive records are excluded from listing/search by default. Interactive hidden input is available for sensitive CLI entry.
- The sensitivity label is not encryption. The SQLite database is plaintext at the application layer; do not store credentials, tokens, recovery codes or secrets in AIE memory.
- Expired records can be previewed and explicitly pruned. Individual records can be permanently forgotten.

## Consequences
The foundation supports provenance-aware local retrieval and user-controlled retention. Automatic extraction, vector embeddings, consolidation, contradiction resolution, export and learning from verified outcomes remain future work and require evaluation.
