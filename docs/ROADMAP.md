# AIE Roadmap and Task Tracker

Status vocabulary: DONE / IN_PROGRESS / BLOCKED / PLANNED. A task is DONE only when code exists and its tests or documented validation support the claim.

**Last updated:** 2026-10-15

| ID | Milestone | Status | Current evidence / exit criteria |
|---|---|---|---|
| M0 | Architecture and foundation | IN_PROGRESS | Contracts, package, CLI, docs and Windows CI workflow; CI must execute successfully |
| M1 | Windows environment observer | IN_PROGRESS | Host/process baseline, app/service/network/task inventory, SQLite and explicit retention API |
| M2 | Context intelligence | IN_PROGRESS | Process correlation, durable incremental state projection and bounded factual context packets are implemented; Windows validation, compaction policy and evaluation remain |
| M3 | Cognitive core | IN_PROGRESS | Hardware-aware model discovery plus bounded local Ollama chat/embedding adapters and `aie ask`; planning and evaluation remain |
| M4 | Persistent intelligence | PLANNED | Provenance-aware memory, consolidation and retrieval evaluation |
| M5 | Controlled autonomy | PLANNED | UIA/app adapters, capability broker, policy, sandbox, audit and recovery |
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
- [ ] Add snapshot compaction/size policy and recovery evaluation for corrupted or pruned histories.
- [x] Add bounded deterministic context packets with explicit coverage, observation timestamps and evidence references; no inferred facts or implicit absence-as-removal semantics.
- [ ] Evidence-backed relevance scoring and confidence calibration.
- [ ] Privacy-safe project/session context.
- [ ] Synthetic evaluation corpus and false-positive/negative metrics.
- [ ] Predictive state-change evaluation.

## M3 — Cognitive Core and local model routing
- [x] Discover installed models through local loopback Ollama `/api/tags`.
- [x] Select routine Qwen 2.5 3B, complex Qwen 2.5 7B with 7.5 GiB free-memory gate, and Nomic embeddings.
- [x] Never automatically pull models; reject non-loopback Ollama endpoints.
- [x] Add local-only Ollama chat and embedding adapters with non-streaming structured-output support, bounded responses, timeouts, cooperative cancellation checks, redirect/proxy isolation and dimension validation; expose `aie ask` and `aie embed`.
- [x] Add a local-only Ollama embedding adapter with finite-vector, batch-count and caller-specified dimension validation; Nomic live-dimension confirmation remains pending.
- [ ] Add task complexity classification and model selection evaluation.
- [ ] Add optional cloud adapter behind an explicit per-task data-egress policy.
- [ ] Add context budgets, latency/cost metrics and deterministic fallback.
- [ ] Add goal/planning state machine; models cannot change security policy.

## M4 — Persistent Intelligence
- [ ] Working, episodic, semantic, procedural and prospective memory schemas.
- [ ] Provenance, confidence, sensitivity, TTL and verification state.
- [ ] Retrieval benchmark, contradiction handling and memory decay.
- [ ] User review, correction, export and deletion controls.
- [ ] Experience consolidation with regression tests.

## M5 — Windows application automation and controlled autonomy
- [ ] Windows UI Automation (UIA) client and bounded tree inspector.
- [ ] App compatibility registry: API / COM / UIA_FULL / UIA_PARTIAL / CLI_ONLY / MANUAL_ONLY.
- [ ] Adapter SDK for per-application APIs, COM, CLI and UIA.
- [ ] Window/process identity verification before every UI action.
- [ ] Capability manifests and least-privilege action identities.
- [ ] Proposal → policy → approval → sandbox → verification workflow.
- [ ] Timeouts, rate limits, resource budgets, rollback and audit.
- [ ] Approval gates for delete/send/purchase/submit/install/security/privileged actions.
- [ ] Prompt-injection and tool-misuse adversarial tests.

## M6 — Generalization Research
- [ ] Held-out task families and baseline systems.
- [ ] Transfer to unseen task variations.
- [ ] Causal/temporal reasoning evaluated separately from retrieval.
- [ ] Calibration, robustness, forgetting and recovery metrics.
- [ ] Reproducible experiment logs; benchmark progress is not proof of AGI.

## Active GitHub work item
- [Issue #3 — Validate Windows Observer and implement ETW process telemetry](https://github.com/AryanGupta-234/P1-/issues/3)

## Current sprint — target hardware: Windows 11 x64, 16 GB RAM
1. Confirm Windows CI; run `python -m pytest` and `ruff check .` locally.
2. Validate pause/resume, collector recovery and export on the target Windows host.
3. Validate the ETW decoder against real Windows traces, confirm available loss counters and correlate ETW events with snapshot reconciliation.
4. Validate the fixed Event Log allowlist and persisted-cursor recovery on Windows, then add real-time subscriptions and process/image correlation.
5. Build UIA read-only inspector before any app-control actions.
6. Validate incremental `aie state` checkpoints against real observer history; add snapshot compaction and a synthetic environmental-state evaluation corpus.

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
