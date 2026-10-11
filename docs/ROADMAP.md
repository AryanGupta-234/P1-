# AIE Roadmap and Development Tracker

Statuses: DONE / IN_PROGRESS / BLOCKED / PLANNED. Mark DONE only with code, tests and validation evidence.

**Last updated:** 2026-10-11 | **Integration branch:** `dev`

| ID | Workstream | Status | Exit criteria |
|---|---|---|---|
| M0 | Foundation and dev workflow | IN_PROGRESS | Stable package/contracts, Windows CI, reproducible setup |
| M1 | Windows environment perception | IN_PROGRESS | Inventory, process reconciliation, durable events and telemetry |
| M1.5 | First diagnostic capability | IN_PROGRESS | Video hypotheses and synthetic evaluation |
| M2 | Context intelligence | PLANNED | Temporal correlation, state model, evidence-linked hypotheses |
| M3 | Cognitive core | PLANNED | Model adapters, routing, planning and evaluation |
| M4 | Persistent memory and learning | PLANNED | Provenance-aware memory, retrieval, consolidation and feedback |
| M5 | Controlled autonomy | PLANNED | Policy broker, scoped execution, audit, verification and recovery |
| M6 | Generalization research | PLANNED | Held-out task transfer, robustness and reproducible benchmarks |
| M7 | Personal assistant experience | PLANNED | Tray app, alerts, controls and explainability |

## M0 — Foundation
- [x] Windows-only architecture and boundaries.
- [x] Versioned normalized event contract.
- [x] Python package, CLI and SQLite event store.
- [x] Read-only inventory and process reconciliation.
- [x] Architecture spotlight and roadmap.
- [ ] Live smoke test on the target Windows 11 desktop and selected installed applications.
- [x] Windows CI on Python 3.11/3.12: dependency install, optional pywinauto import, Ruff and pytest all passed on PR #4 head.
- [ ] Dependency/security checks and contributor setup.

## M1 — Windows perception
- [x] Host/process snapshot inventory.
- [x] Best-effort process start/stop reconciliation.
- [x] Read-only provider abstraction.
- [ ] ETW process telemetry with bounded buffers.
- [ ] Allowlisted Windows Event Log sources.
- [x] System CPU/RAM/system-volume resource snapshots.
- [ ] Per-process resource sampling.
- [x] Read-only network interface counters, gateway/external TCP reachability RTT and DNS resolution probes.
- [x] Wire bounded network provider into observer CLI with configurable sampling interval, event-store integration and --no-network opt-out.
- [x] Read-only Windows service inventory.
- [x] Scheduled-task name/status inventory.
- [x] Installed application metadata from uninstall registry keys.
- [ ] Executable path and Authenticode signature inventory.
- [ ] Pause/resume, retention, export/delete and observer health.
- [ ] Sampling overhead and event-loss measurements.

## M1.5 — Video diagnostics
- [x] Deterministic telemetry contract and triage function.
- [x] Hypotheses for throughput, packet loss, latency and local rendering pressure.
- [x] Insufficient-evidence behavior and unknown-value handling.
- [x] Synthetic unit tests.
- [ ] Root-cause trace corpus and false-positive/negative evaluation.
- [x] Opt-in MV3 Edge/Chrome playback observer prototype with an off-by-default control.
- [x] Strict Windows native-messaging host that validates and persists browser video events.
- [ ] Validate extension installation and native-host registration on a target Windows desktop.
- [x] Windows network sampler: interface counters, gateway/external TCP connection latency and DNS timing.
- [ ] Add configurable per-target policy and sustained throughput measurement (opt-in only).
- [x] Correlate synthetic browser playback snapshots with fresh same-host network evidence.
- [ ] Validate end-to-end browser → native host → event store → context pipeline on a target desktop.
- [ ] Confidence calibration and actionable diagnostic proposals.

## M2 — Context intelligence
- [x] Initial temporal correlator for browser-video snapshots and fresh same-host network evidence (synthetic contract; browser extension/native host prototype exists, end-to-end desktop validation remains pending).
- [ ] Unified event bus and general temporal correlation.
- [ ] Working context: foreground application, task and session state.
- [ ] Facts-versus-hypotheses model, evidence lineage and contradictions.
- [ ] User-approved profile/personalization.
- [ ] Relevance scoring and false-positive evaluation.

## M3 — Cognitive core
- [ ] Provider-independent model interface.
- [ ] Local Ollama adapter with timeouts, structured outputs and cancellation.
- [x] Local Ollama model discovery and hardware-aware model selection with an available-memory gate.
- [ ] Inference concurrency, context and runtime memory budgets.
- [ ] Optional cloud adapter behind explicit task-level egress policy.
- [ ] Context packaging, token/cost budgets and prompt-injection boundaries.
- [ ] Planner/state machine with deterministic fallback.
- [ ] Reasoning/tool-selection evaluation harness.

## M4 — Memory and learning
- [ ] Working, episodic, semantic, procedural and prospective memory.
- [ ] SQLite provenance store and optional local vector index.
- [ ] Sensitivity, TTL, correction, export and deletion.
- [ ] Retrieval benchmark and contradiction handling.
- [ ] Feedback: proposal, acceptance, execution, outcome and verification.
- [ ] Memory consolidation with regression tests.
- [ ] Reviewed/versioned skill induction.

## M5 — Controlled autonomy
- [x] Read-only UIA window metadata listing and bounded tree inspector (PR #4; metadata-only, no actions).
- [x] Synthetic tests for traversal bounds, provider errors and text-property exclusion.
- [x] Confirm optional pywinauto installation/import in Windows CI on Python 3.11/3.12.
- [ ] Validate UIA support/limitations against selected desktop applications.
- [ ] Capability manifests and least-privilege identities.
- [ ] Proposal → policy → approval → sandbox → verification.
- [ ] Allowlists, rate limits, timeouts and resource budgets.
- [ ] Reversible actions and rollback/recovery.
- [ ] Append-only audit and user-visible action history.
- [ ] Prompt-injection, malicious-page and tool-misuse tests.
- [ ] Risk tiers and approval requirements.
- [ ] Global pause/kill switch.

## M6 — Generalization
- [ ] Held-out task families and baselines.
- [ ] Transfer to unseen task variations.
- [ ] Causal/temporal reasoning separate from retrieval.
- [ ] Calibration, robustness, forgetting and recovery metrics.
- [ ] Reproducible experiment/model manifests; no benchmark claimed as proof of AGI.

## M7 — Assistant experience
- [ ] Windows tray app and lifecycle controls.
- [ ] Live state, explainable alerts and recommendations.
- [ ] Permission, pause and retention settings.
- [ ] Diagnostics/action history and memory review.
- [ ] Desktop UI after core telemetry and policy APIs stabilize.

## Immediate dev sprint
1. Confirm the latest Windows CI runs on dev and PR #4 are green.
2. Review PR #4 and merge the UIA discovery layer after validation.
3. Add trace fixtures for buffering causes and unknown evidence.
4. Add pause/retention and per-process resource controls.
5. Verify native-host registration and end-to-end browser telemetry on the target laptop.
6. Update this tracker and Architecture Spotlight in every PR.

## Risk register
| Risk | Mitigation | State |
|---|---|---|
| Snapshot polling misses short-lived events | ETW plus reconciliation; report coverage | OPEN |
| Browser telemetry exposes private data | Explicit opt-in; playback-only signals; no cookies/forms | OPEN |
| Model hallucination causes harmful changes | Model proposes; broker authorizes; verification required | CONTROLLED |
| Noisy metrics cause false diagnosis | Repeated samples, multiple signals, evaluation | OPEN |
| Memory retains sensitive data | Local-first, sensitivity labels, TTL, inspect/export/delete | OPEN |
| Agent performs unbounded actions | Capability scopes, budgets, kill switch, audit | CONTROLLED |
