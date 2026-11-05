# ADR-0016: Unified APEX data store and model-assisted application enrichment

- **Status:** Accepted for APEX planning; implementation pending
- **Date:** 2026-11-05
- **Branch:** `feature/apex-standalone-assistant-plan`
- **Decision owners:** AIE / APEX project maintainers

## Context

APEX needs durable, real-time access to the user's approved profile, conversations, working and long-term memories, application catalogue, task context and diagnostic knowledge. The repository currently resolves separate SQLite files for events, personal memory, task runs and task sessions through `aie/config.py`. Building APEX on top of these as unrelated data silos would violate the intended unified-memory experience and complicate cross-domain retrieval and updates.

APEX also needs to discover installed applications and resolve friendly names to exact launch targets. Windows APIs, registry metadata, package registrations, shortcuts, PE version resources and Authenticode evidence can establish executable identity and path. A local model can help interpret incomplete descriptive metadata, but must not become the source of executable paths or security decisions.

## Decision

### 1. One canonical physical database

Create one canonical local SQLite file, targeted at `%LOCALAPPDATA%\\AIE\\apex-unified.sqlite3`, resolved using the existing AIE per-user data-directory helper.

The following domains share this physical database while remaining logically separated by tables, repository interfaces and access policy:

- User-approved profile and preferences.
- Conversation sessions, messages, summaries and retention metadata.
- All memory kinds: working, episodic, semantic, procedural and prospective.
- Memory embeddings, retrieval metadata, corrections, supersession and lineage.
- Installed application catalogue, executable/AUMID identities, aliases, discovery provenance, model enrichment, scan state and launch history.
- Normalized AIE observations, inventory/state projections and evidence references needed by diagnostics.
- User task sessions, plans, runs, step state and outcome summaries.
- Diagnostic incidents, reviewed hypotheses, verified fixes and approved reusable workflows.

The application catalogue is a dedicated domain in the same database. It is not automatically mixed into personal-memory prompt retrieval.

### 2. Consolidate existing AIE local data stores

The current separate event, memory, task-run and task-session database paths must converge on the canonical file. Migration must be idempotent and loss-checked:

1. Pause or quiesce writers and create verified source backups.
2. Record each source file's identity, schema version, row counts and integrity/checksum information.
3. Migrate rows through versioned adapters inside bounded transactions, retaining stable IDs and provenance.
4. Detect duplicate IDs and conflicting records deterministically; never silently overwrite.
5. Verify source/target counts, representative queries, lineage, foreign references and integrity checks.
6. Switch all repositories/config path helpers to the canonical database only after verification.
7. Keep original files read-only through a documented rollback/retention window. Do not delete them as part of automatic migration.

This consolidation is a Phase 1 foundation requirement. Later memory/profile features must not introduce separate database files.

### 3. Schema-flexible but validated records

Use stable typed envelope columns plus versioned JSON domain payloads and a validated extension/attributes object. Maintain a field/schema registry with namespace, type, validation, sensitivity, index intent, introduction version and deprecation state.

Common indexed columns include record ID, namespace, record type, schema version, status, sensitivity, source/provenance, created/updated/expiry times, confidence and optimistic version. Frequently queried properties get typed columns/indexes; optional or evolving properties live in validated JSON extensions.

Never execute SQL based on model-provided field names. Do not let arbitrary model output mutate the SQL schema. Schema upgrades are explicit, deterministic, transactional and tested. Preserve unknown extension values within bounds when forward compatibility is safe.

### 4. Live access and concurrency

Use one `UnifiedDataStore` connection/session factory and repository facade. Enable SQLite WAL, foreign keys, busy timeout and bounded transactions. SQLite still has a single-writer constraint, so serialize writes through one bounded writer queue and batch observer/scanner ingestion. Interactive readers see the latest committed snapshot.

Every transaction that changes durable records appends a monotonic sequence entry to a change journal in the same transaction. Host/provider subscribers can query changes after a sequence and receive invalidation notifications only after commit. Use optimistic record versions and idempotency keys for concurrent edits and repeat imports.

The store exposes live, bounded queries for profile, conversations, memories, app records, scan progress, task state and diagnostic evidence. It reports last-updated time, source and freshness. Database failure must produce an explicit degraded state; it must never silently initialize an empty replacement memory store.

### 5. Keep security audit boundaries separate

The append-only policy/security audit ledger and remote-egress audit remain separate protected stores where their integrity guarantees require isolation. The emergency execution kill switch remains outside the database so that it still works when SQLite is locked, corrupt or unavailable. Secrets, credentials, browser tokens, passwords and private keys are excluded from the unified store.

SENTINEL remains the owner of its private database. APEX reads SENTINEL data through a supported read-only adapter and only retains APEX-side references or permitted summaries in its unified database.

### 6. Deterministic executable discovery; model enrichment only

The executable path, file identity, package/AUMID, source provenance, version-resource values and publisher/signature evidence come from Windows/OS/file APIs and deterministic scanners.

The already-installed local APEX model can be called on minimized extracted metadata only when descriptive fields are missing or ambiguous. It may suggest normalized application/product name, vendor/product family, aliases, broad category, short purpose/description, duplicate-family candidates and confidence. It must not output or alter executable paths, AUMIDs, publisher/signature evidence, trust state, privilege, permissions, launch arguments or automation capability.

All model output is untrusted, strict-schema-validated and tied to candidate/evidence IDs, model tag, prompt version, output schema version, timestamp and review state. Local inference only; batch/deduplicate at low priority; do not make one model call per discovered EXE. Deterministic OS facts always win. Model enrichment never authorizes an executable launch.

## Consequences

### Positive

- One canonical physical database makes user context and assistant memory consistently available across APEX features.
- Application discovery records and model enrichment are queryable in real time with conversations, profile and approved memories.
- Flexible JSON extension fields support evolving record types without uncontrolled SQL schema changes.
- A single change sequence supports live invalidation and coherent host/UI updates.
- Exact executable paths remain grounded in Windows evidence; the model improves names and descriptions without controlling launch or trust.
- Existing data is migrated with backups and verifiable counts rather than discarded.

### Trade-offs

- A migration across existing SQLite files is required and must be proven lossless before switching.
- SQLite WAL supports concurrent readers but still serializes writes; a bounded writer queue and batch ingestion are required.
- Schema flexibility requires a field registry, validation and explicit migration discipline.
- Model enrichment adds local inference work, so it must be low priority, batched and resource-aware.

## Validation required

- All assistant memory domains and app catalogue records resolve to the same physical database path.
- Event, memory, task-run and task-session records migrate with stable IDs and verified counts.
- A schema extension can be added, validated, read and migrated without breaking older records.
- Concurrent readers observe committed changes; optimistic version conflicts are detected.
- The change journal is monotonic and transactionally aligned with data writes.
- Model enrichment cannot alter executable identity/path, signature state, trust or permission fields.
- Ollama absence does not block deterministic application discovery.
- Rollback restores the previous database files and configuration without data loss.
