# AIE Roadmap and Task Tracker

Status vocabulary: DONE / IN_PROGRESS / BLOCKED / PLANNED. Do not mark DONE without code/tests or documented research evidence.

**Last updated:** 2026-10-11

| ID | Milestone | Status | Exit criteria |
|---|---|---|---|
| M0 | Architecture and foundation | IN_PROGRESS | Contracts, package, CLI, tests, docs, Windows CI |
| M1 | Windows environment observer | IN_PROGRESS | Inventory, process reconciliation, durable local event store, richer telemetry |
| M1.5 | First diagnostic capability | IN_PROGRESS | Video-buffering triage, evidence-backed hypotheses, synthetic evaluation |
| M2 | Context intelligence | PLANNED | Temporal correlation, state model, evidence-linked hypotheses |
| M3 | Cognitive core | PLANNED | Model-independent reasoning/planning and router |
| M4 | Persistent intelligence | PLANNED | Provenance-aware memory, consolidation, retrieval evaluation |
| M5 | Controlled autonomy | PLANNED | Capability broker, policy, sandbox, audit, recovery |
| M6 | Generalization research | PLANNED | Held-out transfer and novel-task benchmarks |

## M0 — Foundation
- [x] Windows-only scope and architecture boundaries.
- [x] Normalized event contract, package, CLI and local SQLite persistence.
- [x] Architecture spotlight, roadmap and security documentation.
- [ ] Run tests on Windows 10/11 and record results.
- [ ] Add Windows CI.

## M1 — Windows Environment Observer
- [x] Read-only host/process inventory.
- [x] Best-effort process-state reconciliation with deduplication.
- [x] Local SQLite persistence and optional JSONL export.
- [x] Provider abstraction for ETW/Event Log.
- [ ] ETW process telemetry provider.
- [ ] Allowlisted Windows Event Log sources.
- [ ] Service inventory and opt-in service state monitoring.
- [ ] Network interface/connectivity change provider.
- [ ] Scheduled-task inventory.
- [ ] Executable/application inventory with signer/installation metadata.
- [ ] Measure CPU, memory, latency and event loss.
- [ ] Pause/resume and retention controls.
- [ ] Opt-in browser playback-state/performance telemetry bridge.
- [ ] Hybrid screen observation with explicit pause and capture boundaries.

## M1.5 — First Diagnostic Capability
- [x] Deterministic video-buffering triage function.
- [x] Separate throughput, packet-loss, latency and local rendering hypotheses.
- [x] Require repeated stalls and a minimum observation window.
- [x] Preserve unknown metrics as unknown; include evidence and caveats.
- [x] Synthetic tests for core branches.
- [ ] Add representative synthetic traces and false-positive/negative evaluation.
- [ ] Add Windows network sampling with gateway/external separation.
- [ ] Correlate browser media counters with OS telemetry.
- [ ] Calibrate confidence against measured outcomes.
- [ ] Produce remediation proposals without executing them.

## M2 — Context Intelligence
- [ ] Temporal correlation and host state snapshots.
- [ ] Separate observed facts from inferred hypotheses.
- [ ] Evidence-backed relevance scoring and calibrated confidence.
- [ ] Privacy-safe session/project context.
- [ ] Synthetic evaluation corpus and false-positive/negative metrics.

## M3 — Cognitive Core
- [ ] Provider-independent model adapter.
- [ ] Local Ollama adapter with timeouts and structured output.
- [ ] Optional cloud adapter behind data-egress policy.
- [ ] Context packaging and token/cost budgets.
- [ ] Planning state machine and deterministic fallback.
- [ ] Reasoning evaluation; models cannot change policy/permissions.

## M4 — Persistent Intelligence
- [ ] Working, episodic, semantic, procedural and prospective schemas.
- [ ] Provenance, confidence, sensitivity, TTL and verification state.
- [ ] Retrieval benchmark and contradiction handling.
- [ ] User review, correction, export and deletion controls.
- [ ] Consolidation with regression tests.

## M5 — Controlled Autonomy
- [ ] Tool capability manifests and least-privilege identities.
- [ ] Proposal → policy → approval → sandbox → verification.
- [ ] Command allowlists, resource budgets and timeouts.
- [ ] Rollback/recovery interfaces and audit.
- [ ] Prompt-injection/tool-misuse adversarial tests.
- [ ] Approval gates for destructive, privileged, financial and external actions.
- [ ] Autonomy tiers and user-configurable permissions.

## M6 — Generalization Research
- [ ] Held-out task families and baselines.
- [ ] Transfer to unseen task variations.
- [ ] Causal/temporal reasoning evaluation separate from retrieval.
- [ ] Calibration, robustness, forgetting and recovery metrics.
- [ ] Reproducible experiments; benchmark progress is not proof of AGI.

## Current sprint
1. Add GitHub Actions Windows CI and run the full test suite.
2. Review diagnostic module on Windows and add trace fixtures.
3. Prototype an opt-in Edge/Chrome playback telemetry bridge.
4. Add bounded network sampling and evidence correlation.
5. Keep remediation proposal-only until the policy broker and audit path exist.

## Risk register
| Risk | Mitigation | State |
|---|---|---|
| User-mode APIs lack complete kernel visibility | ETW/Event Log first; signed driver only if justified | OPEN |
| Transient process events are missed | ETW plus snapshot reconciliation | OPEN |
| Telemetry privacy exposure | Local-first, filtering, retention, pause controls | OPEN |
| Model hallucination becomes action | Observer read-only; policy broker mandatory | CONTROLLED |
| Misdiagnosed stream stalls | Multi-signal evidence, uncertainty, trace evaluation | OPEN |
| Unwanted browser observation | Explicit extension permission and playback-only collection | OPEN |
