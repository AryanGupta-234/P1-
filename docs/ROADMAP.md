# AIE Roadmap and Development Tracker

Statuses: DONE / IN_PROGRESS / BLOCKED / PLANNED. Mark DONE only with code, tests and validation evidence.

**Last updated:** 2026-10-11 | **Integration branch:** `dev`

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
| M7 | Personal assistant experience | PLANNED | Tray app, alerts, controls and explainability |

## M0 — Foundation
- [x] Windows-only architecture and boundaries.
- [x] Versioned normalized event contract.
- [x] Python package, CLI and SQLite event store.
- [x] Read-only inventory and process reconciliation.
- [x] ARC Architecture Spotlight, roadmap and contribution guide.
- [x] Hosted Windows CI on Python 3.11/3.12 with Ruff, optional Windows imports, PowerShell syntax, JS syntax and pytest.
- [x] Event Log runtime integration, ETW lifecycle/loss accounting, systemwide process telemetry and privacy controls validated in hosted Windows CI run #581 (Python 3.11/3.12).
- [ ] Dependency/security scanning and reproducible release packaging.

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
- [ ] Rich observer health desktop UI.
- [ ] Validate ETW elevation, Event Log/UIA permissions and data collection on the target Windows desktop.

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
- [ ] Unified event bus and general temporal correlation.
- [x] Initial temporal activity session model with explicit time-gap boundaries.
- [x] Explicit user-controlled task/session state with opt-in model-context packaging and CLI lifecycle controls.
- [ ] Semantic task/session state and evidence contradiction handling.
- [ ] Evidence freshness, contradiction handling and calibrated confidence.
- [ ] User-approved profile and personalization controls.

## M3 — Cognitive core
- [x] Provider-independent model request/response contracts.
- [x] Local Ollama adapter with timeouts, loopback default and no implicit model pulls.
- [x] RAM-aware routing to already-installed local models.
- [x] Explicit OpenAI-compatible HTTPS adapter and per-request cloud egress opt-in.
- [x] CLI to invoke local or explicitly enabled cloud inference.
- [x] Explicit activity/memory context attachment controls, safe payload budgets and independent remote-egress confirmation.
- [ ] Structured output modes, streaming and cancellation.
- [ ] Inference concurrency, memory/token budgets and latency metrics.
- [ ] Central cloud egress gateway, redaction and audit.
- [ ] Planner/state machine with deterministic fallback.
- [ ] Reasoning and tool-selection evaluation harness.

## M4 — Persistent memory and learning
- [x] Capture user-reported diagnostic outcomes: resolved, not resolved, not attempted.
- [x] Typed local memory schema: working, episodic, semantic, procedural and prospective.
- [x] Source-event provenance validation, sensitivity labels, TTL, correction/supersession and explicit deletion.
- [x] Interactive hidden input for sensitive memory entry; explicitly document that sensitivity labels are not encryption.
- [x] Local keyword/tag retrieval with sensitive memories excluded by default.
- [x] Optional local Ollama embedding index and cosine-similarity memory retrieval; no automatic model pulls.
- [x] Optional local Ollama embedding index with cosine retrieval, model-specific vector storage and deletion/expiry cleanup.
- [x] CLI for memory indexing and semantic recall; sensitive indexing requires an explicit flag and warning.
- [ ] Embedding retrieval quality evaluation, export, contradiction resolution and consolidation.
- [ ] Retrieval benchmark, contradiction handling and consolidation.
- [ ] Evaluated learning from verified outcomes; do not learn unverified fixes.
- [ ] Reviewed and versioned reusable skill induction.
- [ ] Forgetting, retention and regression evaluation.

## M5 — Controlled autonomy
- [x] Default-deny capability manifests and policy decision contracts.
- [x] Low-risk-only pre-authorized autonomy, parameter allowlists and rate limits.
- [x] Explicit approval decisions for medium/high risk; critical-risk actions blocked.
- [x] Policy broker integration with a reviewed proposal queue and separate append-only SQLite audit ledger (approval never executes).
- [x] Typed non-mutating dry-run executor validates proposal/policy alignment without OS mutation.
- [x] CLI dry-run path for reviewed proposals; it reports `executed=False`.
- [ ] Least-privilege real executor and restricted tool manifests.
- [ ] Sandbox, command/time/resource budgets and global execution kill switch.
- [ ] Rollback/recovery and postcondition verification.
- [ ] Prompt-injection and tool-misuse red-team tests.
- [ ] Enable any autonomous remediation only after end-to-end verification.

## M6 — Generalization research
- [ ] Held-out task families and deterministic baselines.
- [ ] Transfer to unseen task variations.
- [ ] Causal/temporal reasoning measured separately from retrieval.
- [ ] Calibration, robustness, forgetting and recovery metrics.
- [ ] Reproducible experiment manifests; no benchmark presented as proof of AGI.

## M7 — Personal assistant experience
- [ ] Windows tray process and lifecycle controls.
- [ ] Native notifications with user-configurable quiet/pause controls.
- [ ] Permission and retention settings.
- [ ] Diagnostics/action history and memory review.
- [ ] Desktop UI after core telemetry and policy APIs stabilize.

## Immediate dev sprint
1. Keep target-desktop validation for browser/native-host, UIA, Event Log and ETW elevation as the primary validation gate.
2. Extend ETW from process lifecycle into explicitly selected thread/file/network categories with coverage reporting.
3. Add evidence freshness, contradiction handling and calibrated confidence to the context layer.
4. Add memory consolidation with evaluated retrieval/forgetting and reviewed skill induction.
5. Update this tracker and Architecture Spotlight with each implementation increment.

## Risk register
| Risk | Mitigation | State |
|---|---|---|
| Snapshot polling misses short-lived processes | ETW plus reconciliation and coverage reporting | OPEN |
| Browser telemetry exposes private page data | Explicit opt-in; playback-only fields; strict native host | CONTROLLED |
| Event Log access denied or logs roll over | Allowlisted classic channels, record cursors, bounded error events | OPEN |
| Model hallucination causes harmful actions | Default-deny policy; no executor yet; approval/audit required | CONTROLLED |
| Noisy metrics cause false diagnosis | Repeated samples, multiple signals and evaluation | OPEN |
| Memory retains sensitive data | Local-first, sensitivity labels, TTL and user deletion | CONTROLLED |
| Agent performs unbounded actions | Capability scopes, budgets, kill switch, audit and verification | CONTROLLED |
