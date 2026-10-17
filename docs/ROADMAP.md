# AIE Roadmap and Task Tracker

Status vocabulary: DONE / IN_PROGRESS / BLOCKED / PLANNED. A task is DONE only when code exists and its tests or documented validation support the claim.

**Last updated:** 2026-10-17

| ID | Milestone | Status | Current evidence / exit criteria |
|---|---|---|---|
| M0 | Architecture and foundation | IN_PROGRESS | Contracts, package, CLI, docs and Windows CI workflow; CI must execute successfully |
| M1 | Windows environment observer | IN_PROGRESS | Host/process baseline, app/service/network/task inventory, SQLite and explicit retention API |
| M2 | Context intelligence | IN_PROGRESS | Process correlation, durable incremental state projection and bounded factual context packets and per-entity evidence-reference caps are implemented; Windows validation, state-aware compaction/recovery and evaluation remain |
| M3 | Cognitive core | IN_PROGRESS | Hardware-aware model discovery, bounded local Ollama chat/embedding, and `aie think` context integration; planning and evaluation remain |
| M4 | Persistent intelligence | IN_PROGRESS | Provenance-aware experiences, contradiction adjudication, reviewed knowledge consolidation, local embedding retrieval, recency weighting, immutable skills and integrity-checked evaluations; independent held-out benchmarks and promotion gates remain |
| M5 | Controlled autonomy | IN_PROGRESS | Non-executing policy evaluator plus bounded read-only UIA structure inspector; app adapters, approvals orchestration, sandbox and execution remain unimplemented |
| M6 | Generalization research | PLANNED | Held-out transfer and novel-task benchmarks |

## M0 — Foundation
- [x] Define Windows-only scope and architecture boundaries.
- [x] Define normalized Pydantic event contract.
- [x] Add installable Python package and CLI.
- [x] Add local SQLite event store with batched transactional writes.
- [x] Add architecture spotlight, hardware profile, automation strategy and security docs.
- [x] Add Windows GitHub Actions workflow.
- [ ] Confirm Windows CI has passed.
- [ ] Add coverage and type-checking gates.

## M1 — Windows Environment Observer
- [x] Read-only host and process inventory.
- [x] Process baseline/delta reconciliation, PID-reuse detection and deduplication semantics.
- [x] Local SQLite persistence and optional JSONL export.
- [x] Installed application metadata via uninstall registry keys.
- [x] Windows service inventory (name, display name, status, start type).
- [x] Network interface status inventory without IP/MAC addresses.
- [x] Scheduled task name/status inventory using read-only query.
- [x] Emit periodic CPU/memory/system-volume usage observations.
- [x] Add read-only ETW provider catalog discovery (no session control).
- [x] Add explicit SQLite event retention by age or newest-N count, with validation tests and CLI.
- [x] Detect service additions, removals and field changes from periodic snapshots.
- [x] Detect network interface, scheduled-task and installed-application inventory deltas.
- [x] Add deterministic snapshot reconciliation with synthetic add/remove/change tests and baseline semantics.
- [x] Add provider integration tests for four inventory baselines and service-state transition emission.
- [x] Sample low-frequency inventory every 30 seconds separately from process/resource polling.
- [x] Detect service, network-interface, scheduled-task and application metadata changes through 30-second snapshot reconciliation.
- [ ] Add native event-driven service/network/task subscriptions where supported.
- [ ] Complete ETW process telemetry validation: opt-in bounded capture, streaming tracerpt-XML normalization, deterministic event IDs and batched SQLite import are implemented; real Windows schema validation, confirmation of available loss counters, and snapshot reconciliation are pending.
- [x] Add a fixed, read-only System Event Log allowlist for service state changes, sleep transitions and OS start/stop; sample it every 30 seconds with collector fault isolation.
- [x] Persist the System Event Log record-ID cursor in SQLite; commit it only after the event batch is stored, allowing deterministic replay after interruption.
- [ ] Add real-time Event Log subscriptions and validate event coverage/permissions on Windows; validate persisted-cursor recovery on the target host.
- [ ] Executable path discovery and Authenticode publisher/signature inventory.
- [x] Add cooperative pause/resume via an operator-controlled pause file; record pause/resume events.
- [x] Isolate process/state collector exceptions and persist sanitized error/recovery events.
- [x] Add chronological JSONL event export API and `aie export-events PATH` CLI command.
- [x] Retain explicit event-retention controls through the `aie prune` CLI.
- [ ] Measure CPU, memory, event latency and event loss on the target laptop; collector exception reporting is implemented but needs Windows validation.

## M2 — Context Intelligence
- [x] Add conservative ETW-to-snapshot process-start correlation using host, PID, normalized image name and process creation time; emit deterministic derived evidence with both source event IDs.
- [x] Add bounded chronological SQLite history queries and an idempotent `aie correlate --since-minutes N` CLI workflow for derived process-start confirmations.
- [ ] Add stop-event correlation only when process-instance identity is sufficient.
- [x] Emit entity-level `present_observed` evidence for service/network/task/application inventory baselines (collection baseline counts remain explicitly count-only).
- [x] Add an event-sourced environment projector for process instances and inventory entities, with exact host+PID+creation-time process identity, ETW evidence attachment, explicit removals and coverage/unknown-state reporting.
- [x] Expose incremental retained-evidence projections through `aie state`; absence from the evidence stream never implies removal.
- [x] Persist versioned compact environment projections separately from raw observations; incremental replay uses a monotonic SQLite ingestion sequence so late-imported ETW/derived events are not skipped.
- [x] Bound per-process/per-entity evidence references to the latest 64 unique IDs; mark truncation in persisted state/context and defensively cap context output from legacy oversized snapshots.
- [x] Enforce a 16 MiB UTF-8 snapshot payload ceiling; reject oversized writes before SQLite mutation and preserve the last valid snapshot.
- [x] Add SHA-256 integrity metadata, one verified previous generation and explicit `aie state --recover`; corruption fails closed, recovery replays later events, and pre-integrity legacy snapshots remain readable.
- [x] Add explicit age-gated projection compaction: only excess old terminal process/entity records are removed, recent/live state is retained, cumulative compaction metadata is recorded, and raw event history plus the ingest watermark are preserved.
- [ ] Evaluate recovery and rebuild behavior across corrupted or pruned histories.
- [x] Add bounded deterministic context packets with explicit coverage, observation timestamps and evidence references; no inferred facts or implicit absence-as-removal semantics.
- [x] Deterministic, explainable state relevance ranking using recency, active/present status and ETW confirmation; `aie prioritize` exposes ranked records and reason strings. Scores are retrieval priority, not calibrated confidence.
- [ ] Calibrate ranking weights against a labeled retrieval/evaluation corpus and measure ranking quality.
- [ ] Privacy-safe project/session context.
- [ ] Synthetic evaluation corpus and false-positive/negative metrics.
- [ ] Predictive state-change evaluation.

## M3 — Cognitive Core and local model routing
- [x] Discover installed models through local loopback Ollama `/api/tags`.
- [x] Select routine Qwen 2.5 3B, complex Qwen 2.5 7B with 7.5 GiB free-memory gate, and Nomic embeddings.
- [x] Never automatically pull models; reject non-loopback Ollama endpoints.
- [x] Add local-only Ollama chat and embedding adapters with non-streaming structured-output support, bounded responses, timeouts, cooperative cancellation checks, redirect/proxy isolation and dimension validation; expose `aie ask` and `aie embed`.
- [x] Add a local-only Ollama embedding adapter with finite-vector, batch-count and caller-specified dimension validation; Nomic live-dimension confirmation remains pending.
- [x] Add a bounded read-only cognitive context bridge: `aie think` passes provenance-bearing observed facts to local Ollama, treats observation strings as untrusted data, bounds context/question/output and does not expose tools or actions.
- [x] Add opt-in retrieval of matching non-sensitive user-created memories into `aie think`; prompt contract distinguishes observed facts from stored, potentially stale/unverified memory.
- [ ] Add task complexity classification and model selection evaluation.
- [ ] Add optional cloud adapter behind an explicit per-task data-egress policy.
- [ ] Add context budgets, latency/cost metrics and deterministic fallback.
- [x] Add persistent user-directed goals, ordered steps, dependency gates, goal/step state transitions and append-only history; expose CLI and opt-in bounded goal context to `aie think`.
- [x] Add local model-generated plan suggestions with strict JSON/schema validation, bounded context and dependency ordering; validated drafts are persisted for review but never added as goal steps or executed without explicit acceptance.
- [x] Persist bounded model plan drafts with SHA-256 integrity metadata, pending-review/accepted/rejected states, audit history and explicit CLI acceptance/rejection. Acceptance atomically creates ordered goal steps and dependencies; it does not execute actions.
- [ ] Add plan-quality evaluation; models cannot change security policy.

## M4 — Persistent Intelligence
- [x] Add explicit working, episodic, semantic, procedural and prospective memory record kinds in local SQLite.
- [x] Persist provenance IDs, confidence, sensitivity, verification state, tags, access count and optional TTL; exclude sensitive records from retrieval by default.
- [x] Add explicit memory add/search/delete/expired-prune CLI workflows; memory is never generated or consolidated automatically.
- [x] Provenance, confidence, sensitivity, TTL and verification state.
- [x] Add configurable exponential recency weighting to lexical memory retrieval; recency influences rank but never deletes old memories.
- [x] Add local Ollama embedding indexing, cosine-similarity retrieval and content-hash invalidation; sensitive memories remain excluded by default.
- [x] Add semantic near-duplicate candidate discovery with explicit human review; no automatic merge or deletion.
- [x] Add one-time, evidence-backed contradiction adjudication with append-only audit; original experience outcomes remain unchanged.
- [x] Add SHA-256 integrity checks for skill evaluation records and verify prior baselines before regression comparisons.
- [ ] Build independent held-out benchmark execution, calibration and promotion criteria; add retrieval-quality benchmark suites and statistical promotion gates.
- [x] User review/search, correction with immutable prior-version history, JSONL export, explicit deletion and TTL cleanup; sensitive records are excluded from search/export unless explicitly opted in.
- [x] Persist user-directed goals and dependency-ordered steps with auditable transitions as the prospective/planning memory substrate.
- [x] Add persistent task-experience records with outcome labels, verifier class, bounded evidence references and task-family indexing.
- [x] Add evidence-gated procedural skill drafts: require repeated success, at least one evidence-backed episode, payload integrity, explicit review and append-only decision audit; accepted skills remain non-executable references.
- [x] Add descriptive task-family evaluation reports: outcome counts, Wilson 95% interval, evidence-backed success fraction, verifier mix, unique evidence references and repeated-summary indicators; unknown outcomes are excluded from the success-rate denominator.
- [x] Add integrity-checked skill-draft listing and serialize review decisions with SQLite `BEGIN IMMEDIATE`; verify the payload inside the same transaction and require exactly one pending-to-final transition.
- [x] Add immutable numbered skill versions sourced only from accepted, digest-verified drafts; preserve source-draft lineage and verify version payloads on listing.
- [x] Add evidence-referenced skill evaluation records with exact outcome partitions, same-suite baseline comparisons, Wilson intervals, minimum labeled-sample checks, regression flags and atomic audit writes; evaluations never grant execution eligibility.
- [x] Add deterministic experience fingerprints and provenance-preserving duplicate links; retain all original experience rows and backfill fingerprints for existing databases.
- [x] Flag same-description, conflicting non-unknown outcomes as contradictions; never auto-select a winning outcome. Expose relationships for review.
- [x] Add repeated-experience knowledge drafts that withhold contradictory clusters, retain source/evidence provenance, use payload integrity checks and require one-time human review.
- [x] Publish only accepted, repeated, evidence-backed successful knowledge into semantic memory through an idempotent import ledger; partial/failure/unknown candidates remain review-only.
- [x] Add semantic near-duplicate memory candidates through local embedding similarity; preserve source records and require human review.
- [x] Add recency-weighted lexical and semantic retrieval with configurable exponential half-life.
- [x] Add evidence-backed human contradiction adjudication; decisions are immutable per pair, audited, and do not rewrite original experiences.
- [x] Add SHA-256 integrity checks for skill evaluation records and reject tampered baselines before regression comparisons.
- [ ] Add independently-run held-out benchmark execution, retrieval-quality measurement, calibrated promotion criteria and adapter eligibility gates.
- [ ] Add controlled self-improvement experiments: propose changes in isolated branches/worktrees, run independent evaluation, require human approval for merge; no self-modifying production runtime.

## M5 — Windows application automation and controlled autonomy
- [x] Add a bounded read-only Windows UI Automation inspector with strict window/node/depth/output/time limits; collect structural metadata only and exclude text/value/password contents and all interaction patterns. Native Windows runtime validation remains pending.
- [ ] App compatibility registry: API / COM / UIA_FULL / UIA_PARTIAL / CLI_ONLY / MANUAL_ONLY.
- [ ] Adapter SDK for per-application APIs, COM, CLI and UIA.
- [ ] Window/process identity verification before every UI action.
- [ ] Capability manifests and least-privilege action identities.
- [x] Add a non-executing policy evaluator with reviewed action allowlist, exact action capabilities, target verification, sandbox requirement for writes, bounded action budget and SHA-256 proposal-bound expiring approvals.
- [ ] Proposal → policy → approval → sandbox → verification workflow (end-to-end orchestration and execution are not implemented).
- [ ] Bind reviewed procedural skills to versioned app adapters with least-privilege manifests; a learned procedure must never create or expand its own capabilities.
- [ ] Timeouts, rate limits, resource budgets, rollback and audit.
- [ ] Approval gates for delete/send/purchase/submit/install/security/privileged actions.
- [ ] Prompt-injection and tool-misuse adversarial tests.

## M6 — Generalization Research
- [ ] Held-out task families and baseline systems.
- [ ] Transfer to unseen task variations.
- [ ] Causal/temporal reasoning evaluated separately from retrieval.
- [ ] Calibration, robustness, forgetting and recovery metrics.
- [ ] Reproducible experiment logs; benchmark progress is not proof of AGI.
- [ ] Continual-learning evaluation: retention, catastrophic forgetting, transfer, calibration, recovery and regression across held-out task families.
- [ ] Autonomy ladder evaluation: observe → recommend → draft → supervised action → narrowly delegated action, with explicit gates at every transition.

## Active GitHub work item
- [Issue #3 — Validate Windows Observer and implement ETW process telemetry](https://github.com/AryanGupta-234/P1-/issues/3)

## Current sprint — target hardware: Windows 11 x64, 16 GB RAM
1. Confirm Windows CI; run `python -m pytest` and `ruff check .` locally.
2. Validate pause/resume, collector recovery and export on the target Windows host.
3. Validate the ETW decoder against real Windows traces, confirm available loss counters and correlate ETW events with snapshot reconciliation.
4. Validate the fixed Event Log allowlist and persisted-cursor recovery on Windows, then add real-time subscriptions and process/image correlation.
5. Validate `aie uia-inspect` on Windows across elevated/non-elevated apps, multi-monitor layouts and common UI frameworks; retain observation-only semantics.
6. Validate incremental `aie state` checkpoints and `aie compact-state` behavior against real observer history; build a synthetic environmental-state evaluation corpus.
7. Evaluate `aie prioritize` against labeled retrieval scenarios; calibrate weights only from measured results.
8. Validate `aie think` against prompt-injection fixtures and target-host Ollama latency, memory and output quality.
9. Exercise goal dependency gates, pause/resume, history integrity and bounded `--include-goals` context on Windows.
10. Evaluate local `goal-suggest` output quality and adversarial goal-text handling; exercise draft integrity checks, one-time resolution and atomic step creation.
11. Exercise `aie learn-report` against synthetic task histories; validate Wilson intervals, evidence coverage and unknown-outcome handling. Test concurrent skill-review attempts and tampered-draft rejection.
12. Exercise immutable skill publication, version sequencing, payload tampering, same-suite baseline comparisons, minimum-sample behavior and regression detection; independently validate that evaluation records never unlock action execution.
13. Exercise legacy experience fingerprint backfill, duplicate-link idempotency, contradictory outcome detection, knowledge candidate conflict withholding, one-time review, tamper rejection and idempotent semantic-memory publication.
14. Verify that a contradiction recorded after knowledge acceptance blocks publication; verify task reports include duplicate/contradiction counts and that imported semantic memory retains the bounded source and evidence references.
15. Validate local embedding indexing with an already-installed Ollama model, sensitive-record exclusion, content-hash invalidation after memory edits, dimension mismatch handling, corrupt-vector rejection and repeatable re-indexing.
16. Validate recency half-life ranking and semantic cosine retrieval with labeled relevance fixtures; confirm candidate-only near-duplicate search never mutates or merges records.
17. Exercise contradiction adjudication decisions, evidence requirements, one-time review, audit records and proof that source outcomes remain unchanged; tamper with skill evaluation rows and ensure integrity checks reject them.

## Hardware/model constraints
- Routine: `qwen2.5:3b-instruct`.
- Complex: `qwen2.5:7b-instruct` only with >=7.5 GiB currently available RAM; otherwise fall back to 3B.
- Embeddings: `nomic-embed-text:latest`.
- Start with one inference at a time; do not assume the model's disk size equals runtime RAM.
- Keep VBS, HVCI, kernel stack protection and App Control enabled.
- No Linux/WSL target and no untrusted/unsigned kernel driver.

## Risk register
| Risk | Mitigation | State |
|---|---|---|
| User-mode APIs do not capture every transient event | ETW plus periodic reconciliation | OPEN |
| 7B inference can starve a 16 GB desktop | Live memory gate, single inference, 3B fallback | CONTROLLED |
| Telemetry may expose private identifiers | Field allowlists, no IP/MAC/command line by default | CONTROLLED |
| Custom driver conflicts with enforced code integrity | ETW first; signed driver only after separate review | AVOIDED FOR NOW |
| Model hallucination becomes an action | Observer remains read-only; future policy broker is mandatory | CONTROLLED |
