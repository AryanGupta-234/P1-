# AIE Roadmap and Development Tracker

Statuses: DONE / IN_PROGRESS / BLOCKED / PLANNED. Mark DONE only with code, tests and validation evidence.

Development ownership and branch rules are defined in [Development Streams](DEVELOPMENT_STREAMS.md). M1.5 browser/video work is tracked independently on `browser-video-intelligence`; ecosystem and shared-integration work remains on `dev`. The existing browser/video foundation is present in the integrated baseline, but new browser/video progress must stay isolated until a reviewed milestone is ready.

**Last updated:** 2026-10-19 | **Ecosystem branch:** `dev` | **Browser/video branch:** `browser-video-intelligence` | **Stable release:** `main`

| ID | Workstream | Status | Exit criteria |
|---|---|---|---|
| M0 | Foundation and development workflow | IN_PROGRESS | Stable package/contracts, Windows CI, reproducible setup |
| M1 | Windows environment perception | IN_PROGRESS | Inventory, process/event observation, retention and health telemetry |
| M1.5 | Video intelligence | IN_PROGRESS | Live playback telemetry, correlated diagnosis and evaluation |
| M2 | Context intelligence | IN_PROGRESS | Temporal evidence correlation, working context and session model |
| M3 | Cognitive core | IN_PROGRESS | Local/cloud model adapters, routing, planning and evaluation |
| M4 | Persistent memory and learning | IN_PROGRESS | Provenance-aware memory, retrieval, consolidation and feedback |
| M5 | Controlled autonomy | IN_PROGRESS | Capability policy, audit, executor, sandbox and recovery |
| M6 | Generalization research | PLANNED | Held-out task transfer, robustness and reproducible benchmarks |
| M7 | Persistent Sentinel experience | IN_PROGRESS | Per-user worker, multi-workspace Titan boot experience, deep system intelligence, searchable event/audit vault, specialist local AI, advanced collector opt-ins and configurable posture automation |

## M0 — Foundation
- [x] Windows-only architecture and boundaries.
- [x] Versioned normalized event contract.
- [x] Python package, CLI and SQLite event store.
- [x] Read-only inventory and process reconciliation.
- [x] ARC Architecture Spotlight, roadmap and contribution guide.
- [x] Hosted Windows CI on Python 3.11/3.12 with Ruff, optional Windows imports, PowerShell syntax, JS syntax and pytest.
- [x] Hosted Windows CI also compiles the .NET 8 WPF dashboard; this verifies the build, not interactive behavior on the target desktop.
- [x] Event Log runtime integration, ETW lifecycle/loss accounting, systemwide process telemetry and privacy controls validated in hosted Windows CI run #581 (Python 3.11/3.12).
- [x] Installed-dependency vulnerability audit in Windows CI with `pip-audit`; weekly Dependabot checks for Python and GitHub Actions updates.
- [x] Windows CI builds wheel and source distributions, validates metadata with Twine, and uploads short-lived artifacts.
- [ ] Pinned/hash-verified dependency lock and signed, reproducible release provenance.

## M1 — Windows perception
- [x] Host/process snapshot inventory and best-effort process lifecycle observations.
- [x] Read-only installed application, service and scheduled-task inventory.
- [x] Foreground app transitions and throttled active-process CPU, RSS, thread and I/O samples.
- [x] Bounded network interface counters, TCP connection-establishment latency and DNS resolution timing.
- [x] Opt-in metadata-only Application/System Event Log provider; startup backlog skipped, message text/XML/Security excluded.
- [x] Event Log provider wired into observer runtime with bounded polling and per-pass record cap.
- [x] Opt-in allowlisted UI Automation structural tree sampler with node/depth/time bounds.
- [x] Global per-user observer pause/resume, status and age-based retention pruning.
- [x] Opt-in ETW process lifecycle telemetry with bounded queue and provider-reported loss accounting.
- [x] Opt-in bounded systemwide process CPU/RSS/thread/I/O snapshots; top consumers only, no command lines or executable paths.
- [ ] Disk/network per-process deltas and higher-fidelity provider coverage.
- [x] Privacy-safe observer health telemetry with provider latency/error counters and event-loss hooks.
- [x] `aie health` CLI view for provider errors, latency and event-loss counters.
- [x] Explicit JSONL export and confirm-only delete-all controls; sensitive export requires an explicit opt-in.
- [x] Rich live Sentinel command-deck UI with live resource telemetry, provider matrix, event vault, model fusion and pause/resume/stop controls.
- [x] Periodic bounded system inventory event for processes, applications, services, scheduled tasks and interfaces, with local event inspection in the Sentinel dashboard.
- [x] Allowlisted read-only registry configuration snapshots with service/driver registration and Run/RunOnce name-change detection.
- [x] Deeper CIM inventory for OS/CPU/firmware, Secure Boot, system and signed PnP drivers, fixed/physical disks, BitLocker status, battery, Defender, Firewall and device health.
- [x] Local rule-based posture watch for Defender, Firewall, physical-disk health, PnP errors and BitLocker/Secure Boot status; new high/critical findings can request a deduplicated local AI review.
- [x] Titan dashboard includes an animated boot sequence and Cockpit/System/Telemetry/Evidence/AI/Autonomy/Knowledge workspaces.
- [x] Dashboard includes filterable signed-PnP inventory, storage/BitLocker/battery/firmware details, local Ollama discovery and six local AI specialist modes.
- [x] Autonomy profile includes adjustable low-disk/low-battery thresholds, configurable registry/posture review triggers, advanced explicit Event Log/ETW/title/UIA settings and a local command/automation audit timeline.
- [x] Searchable local catalogs for bounded process, installed-application, service, scheduled-task and network-interface records.
- [x] One-click Deep Watch, Balanced and Low Impact autonomy presets with save-before-commit behavior.
- [x] Local Microsoft Learn and Microsoft-owned GitHub Markdown crawler with bounded sources, local SQLite indexing and dashboard search.
- [ ] Validate registry ACLs, CIM/Defender/PnP visibility, Learn crawler compatibility and inventory accuracy on the target Windows desktop.

## M1.5 — Video intelligence
- [x] Opt-in Chrome/Edge MV3 HTML-video observer, disabled by default.
- [x] Strict Windows native-messaging host and local SQLite persistence.
- [x] Stall, buffered-ahead, playback-progress and available dropped-frame telemetry.
- [x] Correlate playback snapshots with same-host foreground-app and network evidence.
- [x] Conservative hypotheses for buffer starvation, buffered-but-not-advancing playback and measured resource/network signals.
- [x] Unknown throughput/packet-loss values remain unknown; TCP connect latency is not mislabeled packet RTT.
- [x] Live deduplicated diagnostic suggestions with evidence IDs; no action execution.
- [x] User-reported outcome feedback linked to diagnostic event IDs.
- [ ] Validate browser extension/native-host installation and live player behavior on the target desktop.
- [ ] Build trace corpus, evaluate false positives/negatives and calibrate confidence.
- [ ] Add opt-in bounded sustained throughput and packet-loss measurements.
- [ ] Validate diagnosis across different streaming players/CDNs.

## M2 — Context intelligence
- [x] Temporal correlator for browser video, foreground app and fresh same-host network evidence.
- [x] CLI for inspecting correlated video context and evidence.
- [x] UIA structural snapshot inspection without control text.
- [x] Indexed event-store queries by time window, source and event type.
- [x] Unified privacy-safe activity timeline grouping browser, application, network, process, Event Log and diagnostic metadata.
- [x] Safe activity-summary context packager for explicit per-request model inclusion; remote inclusion requires separate confirmation.
- [x] Unified bounded synchronous event bus wired to durable SQLite and optional JSONL sinks.
- [x] Rule-driven bounded temporal evidence correlation across normalized event types.
- [ ] General evidence graph with richer provenance/causal hypothesis handling.
- [x] Initial temporal activity session model with explicit time-gap boundaries.
- [x] Explicit user-controlled task/session state with opt-in model-context packaging and CLI lifecycle controls.
- [x] Freshness-weighted evidence assessment plus narrow near-simultaneous contradiction detection for allowlisted state fields.
- [ ] Semantic task/session state and evidence contradiction handling beyond the explicit detector.
- [ ] Calibrated confidence and evidence-quality evaluation.
- [ ] User-approved profile and personalization controls.

## M3 — Cognitive core
- [x] Provider-independent model request/response contracts.
- [x] Local Ollama adapter with timeouts, loopback default and no implicit model pulls.
- [x] RAM-aware routing to already-installed local models.
- [x] Explicit OpenAI-compatible HTTPS adapter and per-request cloud egress opt-in.
- [x] CLI to invoke local or explicitly enabled cloud inference.
- [x] Explicit activity/memory/session context attachment controls, safe payload budgets and independent remote-egress confirmation.
- [x] Central remote egress gateway for cloud/remote-Ollama requests with high-confidence credential redaction and metadata-only local audit.
- [x] Provider-level structured JSON generation for local Ollama and explicitly authorized OpenAI-compatible inference; plans are still validated locally against strict schema and capability allowlists.
- [ ] Streaming responses, inference cancellation, and structured tool-result streaming.
- [ ] Inference concurrency, memory/token budgets and latency metrics.
- [x] Central remote-model egress gateway, high-confidence credential redaction and metadata-only audit.
- [x] Bounded declarative task-plan contract with strict fields, typed steps, explicit dependencies, cycle rejection, deterministic topological ordering and readiness queries; no step execution. Validated by Windows CI run [#590](https://github.com/AryanGupta-234/P1-/actions/runs/38131262921) on Python 3.11 and 3.12.
- [x] Optional local-Ollama plan drafting with strict schema, exact-goal preservation, capability allowlist validation and deterministic graph validation.
- [x] SQLite task-run persistence with compare-and-swap versions, append-only lifecycle events, bounded step advancement, pause/resume/cancel and manual verification gates.
- [x] Local-only model reasoning handler using bounded completed-step summaries; unavailable local inference falls back to explicit user input.
- [x] Fail-closed recovery of interrupted in-flight handlers to manual review; automatic replay remains intentionally disabled and pending.
- [x] Planner benchmark harness and deterministic metrics for user-authored cases; held-out task families, corpus quality and performance evaluation remain pending.
- [ ] Held-out task families, tool-selection utility, latency/cost calibration and human-rated reasoning quality.

## M4 — Persistent memory and learning
- [x] Preserve `updated_at >= created_at` when imported/source timestamps are ahead of the local clock; save/reload regression coverage added on 2026-10-12.
- [x] Capture user-reported diagnostic outcomes: resolved, not resolved, not attempted.
- [x] Typed local memory schema: working, episodic, semantic, procedural and prospective.
- [x] Source-event provenance validation, sensitivity labels, TTL, correction/supersession and explicit deletion.
- [x] Interactive hidden input for sensitive memory entry; explicitly document that sensitivity labels are not encryption.
- [x] Local keyword/tag retrieval with sensitive memories excluded by default.
- [x] Optional local Ollama embedding index and cosine-similarity memory retrieval; no automatic model pulls.
- [x] Optional local Ollama embedding index with cosine retrieval, model-specific vector storage and deletion/expiry cleanup.
- [x] CLI for memory indexing and semantic recall; sensitive indexing requires an explicit flag and warning.
- [ ] Embedding retrieval quality evaluation and benchmark.
- [x] Review-only duplicate/near-duplicate consolidation proposals; no automatic merge/rewrite.
- [x] Explicit two-source memory merge after review, with two-parent lineage, source provenance preservation, sensitivity monotonicity, conservative confidence and earliest-expiry enforcement.
- [ ] Embedding retrieval quality evaluation and semantic contradiction resolution.
- [x] Experimental deterministic skill-candidate generation from completed runs with positive verification and action-receipt checks; explicit user confirmation before save. Quality, transfer and end-to-end hosted CI validation remain pending.
- [ ] Evaluated skill quality/transfer and learning from verified outcomes; no automatic model retraining or capability induction.
- [ ] Forgetting, retention and regression evaluation.

## M5 — Controlled autonomy
- [x] Default-deny capability manifests and policy decision contracts.
- [x] Low-risk-only pre-authorized autonomy, parameter allowlists and rate limits.
- [x] Explicit approval decisions for medium/high risk; critical-risk actions blocked.
- [x] Policy broker integration with a reviewed proposal queue and separate append-only SQLite audit ledger (approval never executes).
- [x] Typed non-mutating dry-run executor validates proposal/policy alignment without OS mutation.
- [x] CLI dry-run path for reviewed proposals; it reports `executed=False`.
- [x] Fail-closed execution gate, kill switch and bounded execution-budget contract consumed by a registered adapter executor.
- [x] Restricted in-process adapter registry with a single fixed Windows Settings URI opener; no shell, arbitrary process, filesystem-write or network adapter. This is not process sandboxing.
- [x] Durable execution reservations and immutable execution receipts appended to the SHA-256 policy audit ledger; duplicate reservations/receipts are rejected and successful URI dispatch remains unverified until a separate postcondition check.
- [x] Append-only, one-time postcondition verification records; only a successful dispatch can be verified, and both confirmed and not-confirmed outcomes are retained without overwriting history.
- [ ] OS-process sandbox enforcement and isolated adapter execution; current built-in adapter is a narrow in-process URI dispatcher, not a sandbox.
- [ ] Rollback and automatic recovery after an execution reservation.
- [ ] Adapter-specific non-interactive postcondition verifiers; current verification is an explicit human-recorded outcome, not independent OS-state inspection.
- [ ] Prompt-injection and tool-misuse red-team tests.
- [ ] Enable any autonomous remediation only after end-to-end verification.

## M6 — Generalization research
- [x] User-authored retrieval benchmark with Recall@k, Precision@k, MRR and Hit Rate for lexical or local semantic search; sensitive records require explicit inclusion.
- [x] Conservative lexical polarity-conflict proposals for manual review; no automatic rewrite or resolution.
- [x] Planner contract benchmark reports deterministic schema/allowlist metrics over a user-authored dataset.
- [ ] Held-out task families and deterministic baselines with curated ground truth.
- [ ] Transfer to unseen task variations and evaluate procedural-skill quality.
- [ ] Causal/temporal reasoning measured separately from retrieval.
- [ ] Calibration, robustness, forgetting and recovery metrics.
- [ ] Reproducible experiment manifests; no benchmark presented as proof of AGI.

## M7 — Persistent Sentinel experience
- [x] Detached per-user worker with duplicate-process protection, stop marker, heartbeat and bounded rotating log.
- [x] Current-user ONLOGON Task Scheduler registration using interactive-only, LIMITED permissions; no SYSTEM service.
- [x] Local loopback dashboard with token-protected API, live host resource chart, provider health, event stream and pause/resume/stop controls.
- [x] Expandable event inspection and periodic Windows metadata inventory snapshots.
- [x] Live Windows-internals dashboard panel and local Microsoft knowledge search.
- [x] Local two-stage Ollama 4B/6B evidence triage/review with memory checks, sequential model use and no auto-pull or cloud fallback.
- [ ] Exercise sign-in startup, dashboard controls, registry/CIM inventory, Microsoft crawler refresh and Ollama inference on the target Windows 11 desktop.
- [ ] Validate the Sentinel Prime operator console, eight-workspace navigation, Task Manager job history, direct feature switches and staged Maintenance Advisor suggestions on the target Windows 11 desktop.
- [ ] Add signed installer/shortcut and polished native desktop shell after validating the local dashboard prototype.
- [x] User-started Windows tray prototype with pause/resume and minimal local status dialog; target-desktop usability/runtime validation remains pending.
- [x] Generic local notification prototype with explicit opt-in, quiet hours, pause suppression and no event details in the balloon. Target-desktop behavior and full notification categories remain pending.
- [x] Capability permission inspection and enable/disable controls for registered adapters; enabling cannot remove required review or enable autonomy.
- [x] Read-only retention inventory for evidence, memories, task runs and policy proposals, alongside explicit event/memory pruning commands.
- [x] CLI diagnostics/action history and local memory review through events, proposals, memories, recall, conflict review, merge and verified-skill review.
- [ ] Native desktop history and memory-review interface with pagination and user-controlled filters.
- [ ] Full desktop dashboard and memory/action history UI after core telemetry and policy APIs stabilize.
- [x] One-command local agent entry point combining local planning, validation, durable run creation and bounded advancement; policy/input gates stop progression.

## Immediate dev sprint
1. Validate the native tray, balloon notification behavior, browser/native-host, UIA, Event Log, registry, CIM and elevated ETW on the actual target desktop; hosted CI cannot validate interactive desktop behavior.
2. Validate the Sentinel Prime dashboard and Task Manager on the target Windows 11 desktop, including repeated feature enable/disable cycles, graceful worker pause/stop, Ollama maintenance suggestions and task-history persistence.
2. Verify Microsoft Learn search response stability, Microsoft GitHub repository refreshes, local indexing and dashboard retrieval.
3. Extend ETW only after validating the pinned provider's real category support and event coverage; do not mark thread/file/network/registry ETW complete based on API surface alone.
3. Evaluate freshness/contradiction signals and add calibrated confidence metrics without treating heuristics as probabilities.
4. Evaluate semantic memory retrieval, reviewed merges, retention and temporal contradiction handling on held-out queries.
5. Add process isolation and adapter-specific postcondition verifiers before expanding the narrow Windows Settings adapter.
6. Evaluate planner quality, skill quality/transfer and verified outcome utility without learning from unverified or model-generated success claims.

## Risk register
| Risk | Mitigation | State |
|---|---|---|
| Snapshot polling misses short-lived processes | ETW plus reconciliation and coverage reporting | OPEN |
| Browser telemetry exposes private page data | Explicit opt-in; playback-only fields; strict native host | CONTROLLED |
| Event Log access denied or logs roll over | Allowlisted classic channels, record cursors, bounded error events | OPEN |
| Model hallucination causes harmful actions | Default-deny broker, audited approval, explicit execution gate and fixed adapter allowlist | CONTROLLED |
| Noisy metrics cause false diagnosis | Repeated samples, multiple signals and evaluation | OPEN |
| Memory retains sensitive data | Local-first, sensitivity labels, TTL and user deletion | CONTROLLED |
| Agent performs unbounded actions | Capability scopes, budgets, kill switch, audit and verification | CONTROLLED |
