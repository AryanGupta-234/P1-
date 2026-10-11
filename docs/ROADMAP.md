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
- [ ] CI matrix on Python 3.11/3.12 and lint.
- [ ] Dependency/security checks and contributor setup.

## M1 — Windows perception
- [x] Host/process snapshot inventory.
- [x] Best-effort process start/stop reconciliation.
- [x] Read-only provider abstraction.
- [ ] ETW process telemetry with bounded buffers.
- [ ] Allowlisted Windows Event Log sources.
- [ ] CPU/RAM/disk and per-process resource sampling.
- [x] Read-only network interface counters, gateway/external TCP reachability RTT and DNS resolution probes.
- [x] Wire bounded network provider into observer CLI with configurable sampling interval, event-store integration and --no-network opt-out.
- [ ] Service and scheduled-task inventory.
- [ ] Installed application/executable metadata inventory.
- [ ] Pause/resume, retention, export/delete and observer health.
- [ ] Sampling overhead and event-loss measurements.

## M1.5 — Video diagnostics
- [x] Deterministic telemetry contract and triage function.
- [x] Hypotheses for throughput, packet loss, latency and local rendering pressure.
- [x] Insufficient-evidence behavior and unknown-value handling.
- [x] Synthetic unit tests.
- [ ] Root-cause trace corpus and false-positive/negative evaluation.
- [ ] Opt-in Edge/Chrome playback/performance extension.
- [x] Windows network sampler: interface counters, gateway/external TCP reachability RTT and DNS timing.
- [ ] Add configurable per-target policy and sustained throughput measurement (opt-in only).
- [ ] Browser + OS telemetry correlation.
- [ ] Confidence calibration and actionable diagnostic proposals.

## M2 — Context intelligence
- [ ] Unified event bus and temporal correlation.
- [ ] Working context: foreground application, task and session state.
- [ ] Facts-versus-hypotheses model, evidence lineage and contradictions.
- [ ] User-approved profile/personalization.
- [ ] Relevance scoring and false-positive evaluation.

## M3 — Cognitive core
- [ ] Provider-independent model interface.
- [ ] Local Ollama adapter with timeouts, structured outputs and cancellation.
- [ ] Hardware-aware model selection, concurrency and memory budgets.
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
1. Run and verify the CI matrix on dev.
2. Add trace fixtures for buffering causes and unknown evidence.
3. Add service/process resource samples and pause/retention controls.
4. Design opt-in browser extension with minimal permissions.
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
