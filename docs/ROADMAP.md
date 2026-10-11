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
- [ ] Full tests on Windows 10/11.
- [x] Windows CI matrix on Python 3.11/3.12 with Ruff lint, browser JavaScript syntax checks and pytest.
- [ ] Dependency/security checks and contributor setup.

## M1 — Windows perception
- [x] Host/process snapshot inventory.
- [x] Best-effort process start/stop reconciliation.
- [x] Read-only provider abstraction.
- [ ] ETW process telemetry with bounded buffers.
- [ ] Allowlisted Windows Event Log sources.
- [x] Throttled CPU, resident memory, thread-count and I/O counters for the active foreground process.
- [ ] CPU/RAM/disk and resource sampling across all processes.
- [x] Read-only network interface counters, gateway/external TCP reachability RTT and DNS resolution probes.
- [x] Wire bounded network provider into observer CLI with configurable sampling interval, event-store integration and --no-network opt-out.
- [x] Read-only service and scheduled-task inventory.
- [x] Read-only installed application metadata inventory.
- [x] Global per-user pause/resume for observation loops, plus status command.
- [x] Confirmation-gated local event retention pruning by age.
- [ ] Export/delete-all and observer health.
- [ ] Sampling overhead and event-loss measurements.

## M1.5 — Video diagnostics
- [x] Deterministic telemetry contract and triage function.
- [x] Hypotheses for measured throughput/packet loss/latency (when available) and local rendering pressure.
- [x] Buffer-ahead starvation and buffered-but-not-advancing playback hypotheses.
- [x] Live observer monitor emits deduplicated diagnostic findings with evidence IDs and recommendations.
- [x] Insufficient-evidence behavior and unknown-value handling.
- [x] Synthetic unit tests.
- [ ] Root-cause trace corpus and false-positive/negative evaluation.
- [x] Opt-in MV3 Edge/Chrome playback observer prototype with an off-by-default control.
- [x] Strict Windows native-messaging host that validates and persists browser video events.
- [ ] Validate extension installation and native-host registration on a target Windows desktop.
- [x] Windows network sampler: interface counters, gateway/external TCP connection latency and DNS timing.
- [ ] Add configurable per-target policy and sustained throughput measurement (opt-in only).
- [x] Correlate browser playback snapshots with fresh same-host network and foreground-process evidence.
- [ ] Validate end-to-end browser → native host → event store → context CLI pipeline on a target desktop.
- [x] Diagnostic proposal events are persisted and surfaced in the running observer loop (recommendation only).
- [ ] Confidence calibration and actionable diagnostic proposals.
- [ ] Validate live browser → native host → SQLite → context → diagnosis on the target Windows desktop.

## M2 — Context intelligence
- [x] Read-only foreground-window transition observer with titles omitted by default.
- [x] Throttled active-foreground process CPU/memory/thread/I/O event sampling.
- [x] CLI command to inspect correlated playback, foreground-app and network evidence.
- [x] Initial temporal correlator for browser-video snapshots and fresh same-host network evidence (synthetic contract; live browser bridge remains planned).
- [ ] Unified event bus and general temporal correlation.
- [ ] Working context: correlate foreground process transitions, browser playback and session/task state.
- [ ] Facts-versus-hypotheses model, evidence lineage and contradictions.
- [ ] User-approved profile/personalization.
- [ ] Relevance scoring and false-positive evaluation.

## M3 — Cognitive core
- [x] Provider-independent model request/response contracts.
- [x] Local Ollama chat adapter with timeouts, strict loopback default and structured errors.
- [x] Hardware-aware routing to already-installed 3B/7B models; no implicit downloads.
- [ ] Structured-output modes, streaming and request cancellation.
- [ ] Inference concurrency guard and explicit memory/token budgets.
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
- [x] Default-deny capability manifest and policy decision contracts.
- [x] Low-risk-only pre-authorized autonomy, parameter allowlists and rate limits.
- [x] Explicit approval decisions for medium/high risk; critical-risk actions always blocked.
- [ ] Policy broker integration with a reviewed action proposal queue and audit store.
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
1. Verify CI for foreground observer integration.
2. Add foreground-process CPU, memory and I/O deltas.
3. Implement global pause/resume and retention controls.
4. Add opt-in Windows UI Automation metadata for selected applications.
5. Update this tracker and Architecture Spotlight in every PR.

## Risk register
| Risk | Mitigation | State |
|---|---|---|
| Snapshot polling misses short-lived events | ETW plus reconciliation; report coverage | OPEN |
| Browser telemetry exposes private data | Explicit opt-in; playback-only signals; no cookies/forms | OPEN |
| Model hallucination causes harmful changes | Model proposes; broker authorizes; verification required | CONTROLLED |
| Noisy metrics cause false diagnosis | Repeated samples, multiple signals, evaluation | OPEN |
| Memory retains sensitive data | Local-first, sensitivity labels, TTL, inspect/export/delete | OPEN |
| Agent performs unbounded actions | Capability scopes, budgets, kill switch, audit | CONTROLLED |
