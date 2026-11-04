# APEX — Follow-up TODOs

**Owner:** AIE / APEX workstream  
**Branch:** `feature/apex-standalone-assistant-plan`  
**Base:** `dev`  
**Source plan:** [APEX Standalone Implementation Plan](APEX_STANDALONE_IMPLEMENTATION_PLAN.md)  
**Status convention:** TODO / IN_PROGRESS / BLOCKED / DONE. Mark DONE only with code, tests and validation evidence.

This is the implementation backlog. The current branch is documentation-only: no APEX runtime, UI or SENTINEL dashboard changes have been made.

## Phase 0 — Planning and repository alignment

- [x] APEX standalone product boundary documented.
- [x] Existing AIE, PRIXON and SENTINEL reuse boundaries documented.
- [x] Standalone lifecycle and future UI separation documented.
- [x] Architecture decision record created.
- [x] Follow-up backlog created.
- [ ] Review this plan against the current `dev` branch before implementation.
- [ ] Confirm APEX branch will integrate to `dev` only through a reviewed PR.
- [ ] Confirm no changes are required to the existing SENTINEL UI/API for the first APEX milestone.

**Exit criteria:** product boundary and integration ownership accepted; no duplicated model/memory/policy/runtime subsystem.

## Phase 1 — Headless APEX host foundation (first coding milestone)

### Repository and contracts
- [ ] Inspect current `aie.models.base.ModelRequest/ModelResponse` contracts and tests.
- [ ] Inspect current Ollama adapter, router and runtime memory admission behavior.
- [ ] Define `apex/` package boundary without moving or renaming existing AIE/SENTINEL packages.
- [ ] Define versioned APEX config schema and migration behavior.
- [ ] Define APEX identity module and prompt version; keep PRIXON identity separate.
- [ ] Define APEX session/message models and bounded conversation history.

### Ollama runtime
- [ ] Connect to loopback Ollama API through the existing AIE adapter.
- [ ] Discover installed model tags; select the user's existing `APEX` tag when available.
- [ ] Never auto-pull models or silently use cloud inference.
- [ ] Apply request-level thinking-off for normal chat.
- [ ] Add explicit/adaptive deep-reasoning mode behind memory/CPU admission.
- [ ] Add streaming responses, cancellation, timeout and bounded output.
- [ ] Serialize local inference with existing AIE model consumers.
- [ ] Record prompt tokens, output tokens, load duration, time-to-first-token, generation time and failures.

### Identity and truthful self-knowledge
- [ ] Add profile contract with editable preferred salutation; initialize salutation to `sir`.
- [ ] Add explicit owner/display-name onboarding; do not infer identity from Windows usernames or paths.
- [ ] Add `apex_get_runtime_manifest`.
- [ ] Report model identity/provenance from Ollama/build metadata.
- [ ] Report connected providers, their health/freshness and actual permissions.
- [ ] Report registered tools and unavailable tools from the live registry.
- [ ] Test “who made you?”, “what model are you?”, “what tools are connected?” and “can you see my processes?” for grounded answers.

### Phase 1 tests / exit criteria
- [ ] Unit tests for identity, prompt composition, config and profile validation.
- [ ] Integration tests for Ollama online/offline, model missing, timeout and cancellation.
- [ ] Verify normal greeting does not emit visible thinking when request setting is off.
- [ ] Verify APEX never claims access to a tool absent from the live manifest.
- [ ] Verify no visible command prompt is required for the host's normal runtime (developer harness is allowed).
- [ ] Measure first-token latency and warm/cold response time on target Windows device.
- [ ] Phase 1 review and ADR updates.

## Phase 2 — Read-only Windows intelligence

- [ ] Define a versioned provider interface and normalized evidence envelope.
- [ ] Connect the existing AIE Windows observer/event store.
- [ ] Build a SENTINEL read-only provider adapter using a documented API/contract.
- [ ] Add source health, timestamp, freshness, coverage and permission metadata.
- [ ] Implement process/service/driver/application/startup/task inventory queries.
- [ ] Implement hardware/CPU/RAM/GPU/storage/network evidence queries.
- [ ] Implement Windows Event Log queries with allowlists and bounded windows.
- [ ] Implement ETW catalog/session status and bounded diagnostic capture adapter.
- [ ] Add per-tool schema, timeout, response-size and cancellation limits.
- [ ] Ensure missing telemetry is reported as unknown, not zero/healthy.
- [ ] Validate read-only operation while the SENTINEL dashboard is closed.
- [ ] Confirm no direct writes to SENTINEL's private SQLite database.

**Exit criteria:** APEX answers whole-Windows questions using real evidence and states unavailable/stale provider coverage honestly.

## Phase 3 — Profile and unified memory

- [ ] Reuse AIE MemoryStore; avoid a parallel APEX database.
- [ ] Add APEX namespace/source tags to memory records.
- [ ] Separate user profile, conversation history, system observations and memories.
- [ ] Implement explicit onboarding for owner name, salutation, locale and preferences.
- [ ] Implement explicit memory capture and user review.
- [ ] Implement relevant, non-sensitive memory retrieval with bounded prompt budget.
- [ ] Preserve provenance, confidence, sensitivity, verification and expiry.
- [ ] Add inspect/edit/correct/export/delete flows.
- [ ] Define retention for conversations, profile facts, incidents and telemetry.
- [ ] Design an adapter/migration path if SENTINEL memory must later be unified.
- [ ] Test restart persistence, conflicting facts, stale memory and deletion.

**Exit criteria:** user-approved profile and memories persist across restarts; the user can inspect and control stored information.

## Phase 4 — Diagnostic intelligence

- [ ] Implement request/task classification (chat, explain, inspect, diagnose, plan, automate).
- [ ] Implement specialist profiles loaded only when relevant.
- [ ] Build bounded evidence/context composer with evidence IDs.
- [ ] Add process/service/network/storage/event correlation tools.
- [ ] Add incident records and repeat-incident retrieval.
- [ ] Separate observations, hypotheses, missing evidence and recommendations.
- [ ] Require supporting evidence IDs for machine-specific findings.
- [ ] Add diagnostic task benchmark and human-reviewed expected outcomes.
- [ ] Measure grounding, accuracy, false positives and false negatives.

**Exit criteria:** diagnostics are repeatable, evidence-backed and calibrated; correlation is not presented as proof of causation.

## Phase 5 — Capability registry and assisted automation

- [ ] Implement typed capability manifests and registry discovery.
- [ ] Implement multi-turn Ollama tool-call dispatch through the host.
- [ ] Add argument validation, target identity checks and provider health checks.
- [ ] Reuse AIE policy broker, capability manifests and audit ledger.
- [ ] Add a narrow initial allowlist (launch allowlisted app; open approved Windows settings page).
- [ ] Add one controlled reversible operation only after review.
- [ ] Bind approvals to exact action, arguments, target and expiry.
- [ ] Add rate limits, duplicate-action protection, timeouts and cancellation.
- [ ] Capture before/after state and verify using a fresh provider read.
- [ ] Add rollback/compensation path and test failure/recovery.
- [ ] Add global stop/kill switch.
- [ ] Test unknown tool, invalid schema, expired approval and protected target denial.

**Exit criteria:** model output cannot bypass authorization; every executed write has approval/policy evidence, audit and verification.

## Phase 6 — Adaptive autonomy and proactive operation

- [ ] Reuse AIE planning/task orchestration and durable run lifecycle.
- [ ] Add bounded planning loop with max step, time, token and tool budgets.
- [ ] Add runtime load shedding based on RAM, CPU, foreground activity and game state.
- [ ] Add anomaly-triggered diagnostic jobs; do not call LLM on every sample.
- [ ] Add user-configured proactive notification preferences.
- [ ] Add pause/resume, per-provider disable and per-capability disable.
- [ ] Add recovery after crash/restart and stale task reconciliation.
- [ ] Validate game/VALORANT protected behavior with the existing SENTINEL/AIE guard contracts.
- [ ] Measure idle/background overhead and impact during real gaming sessions.

**Exit criteria:** adaptive background behavior remains bounded and stops/degrades safely when runtime evidence or resource headroom is unavailable.

## Phase 7 — Standalone desktop experience (UI intentionally later)

- [ ] Choose UI technology after host API contracts stabilize.
- [ ] Create an independent APEX desktop application; do not embed in SENTINEL UI.
- [ ] Add a separate APEX notification-area/tray controller.
- [ ] Add Start Menu/desktop shortcuts and optional per-user sign-in startup.
- [ ] Start/connect to Ollama and APEX host without a visible terminal.
- [ ] Add model/provider health and capability status.
- [ ] Add chat, diagnostic report, memory/profile and approval surfaces.
- [ ] Add accessible keyboard navigation and reduced-motion handling.
- [ ] Add installer, updater, uninstaller and rollback.
- [ ] Verify background host remains usable when the APEX window is closed, if enabled.
- [ ] Verify SENTINEL UI and existing AIE desktop surfaces remain unchanged.

**Exit criteria:** APEX installs and runs as an independent Windows app without requiring the user to type Ollama CLI commands.

## Phase 8 — Evaluation and optional fine-tuning

- [ ] Establish prompt-only APEX baseline before adapter experiments.
- [ ] Create consented/licensed conversation-style and tool-selection dataset.
- [ ] Keep private telemetry, credentials and arbitrary desktop logs out of training data.
- [ ] Run held-out base-versus-adapter evaluation.
- [ ] Add reasoning, coding, Windows, networking, security and tool-schema regression tests.
- [ ] Train a separate LoRA adapter only if prompt/runtime improvements are insufficient.
- [ ] Preserve immutable base model and adapter rollback.

**Exit criteria:** any adapter improves measured outcomes without unacceptable regression or privacy/safety failure.

## Cross-phase quality gates

- [ ] Windows CI tests cover all new APEX modules.
- [ ] Ruff/type/static checks pass where configured.
- [ ] Local Ollama tests never contact non-loopback endpoints by default.
- [ ] No model pulls occur automatically.
- [ ] No direct shell execution surface is exposed to the model.
- [ ] No direct UI coupling to SENTINEL is introduced.
- [ ] No duplicate durable memory, model router or policy broker is created.
- [ ] No credential/browser secret collection is added.
- [ ] Architecture Spotlight and Roadmap are updated with each milestone.
- [ ] Every DONE item has a test or target-machine validation reference.

## First next action

Start with Phase 1 repository/contract inspection, then implement the headless APEX host. Do not begin the desktop UI, modify the SENTINEL dashboard or add autonomous write actions before the host, identity, model and self-inspection contracts pass their tests.
