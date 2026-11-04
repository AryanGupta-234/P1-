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

## Phase 1 — APEX runtime + whole-Windows automation engine (first coding milestone)

### Runtime, identity and model
- [ ] Inspect current `aie.models.base.ModelRequest/ModelResponse` contracts and tests.
- [ ] Inspect current Ollama adapter, router, locking and runtime memory-admission behavior.
- [ ] Define the `apex/` package boundary without moving or renaming existing AIE/SENTINEL packages.
- [ ] Define versioned APEX config, identity, prompt and migration contracts; keep PRIXON identity separate.
- [ ] Implement the local APEX host lifecycle, structured logging, bounded sessions, streaming and cancellation.
- [ ] Connect to the loopback Ollama API through the existing AIE adapter; select the installed `APEX` model tag when available.
- [ ] Never auto-pull a model or silently use cloud inference.
- [ ] Apply request-level thinking-off for normal conversation; gate deep reasoning behind resource admission.
- [ ] Add bounded timeouts/output/context, a single initial local inference slot and serialization with existing AIE consumers.
- [ ] Record model/provider health, token counts, load time, time-to-first-token, generation time and failures.
- [ ] Add `apex_get_runtime_manifest` with actual model, provider, tool, permission and availability state.
- [ ] Ensure normal runtime does not require a visible CMD/PowerShell window or manual `ollama run`; developer mode may use a console.

### Intent interpretation and tool orchestration
- [ ] Classify each request as chat, explain, inspect, diagnose, plan or automate without forcing every message into a tool call.
- [ ] Implement structured multi-turn tool calling and host-side dispatch; never execute model-supplied code directly.
- [ ] Build a typed capability registry with schema version, source, health check, risk tier, privilege, approval rule, timeout, rate limit, verifier and compensation metadata.
- [ ] Implement multi-step workflow plans with preconditions, dependencies, progress, cancellation and per-step policy checks.
- [ ] Ask one focused clarification when a target or operation is materially ambiguous; do not guess destructive targets.
- [ ] Report unsupported, disabled, unavailable and approval-gated capabilities distinctly.

### Whole-Windows automation adapters — required Phase 1 coverage
- [ ] **Applications/windows:** enumerate supported app/window metadata; launch registered applications; activate, minimize, maximize and close user-owned windows; test exact-target protection for process/window actions.
- [ ] **Files/folders:** browse/search user-approved roots; inspect metadata; create folders; copy, move and rename; support Recycle Bin deletion; block permanent deletion, bulk deletion and protected paths by default.
- [ ] **Settings/personalization:** implement typed read/write handlers for supported volume, brightness, display, power, Wi-Fi, Bluetooth, night-light, focus/notification and accessibility settings. Distinguish opening a Settings page from successfully changing a setting.
- [ ] **Processes/apps:** inspect process state; launch registered executables; close through supported application/window paths; permit termination only for specifically allowlisted non-protected targets after PID plus creation-time revalidation and approval.
- [ ] **Services/startup/tasks:** inspect services/startup entries/scheduled tasks; enable/disable registered startup items; run/manage named tasks; start/stop only approved noncritical services; protect critical Windows, security, networking, storage and anti-cheat services.
- [ ] **Networking:** inspect adapters, DNS, routes, proxy and connectivity; implement supported adapter toggles, DNS configuration, DHCP renew/release and bounded repair recipes; require approval and recovery planning for network resets, proxy/firewall changes and disconnecting actions.
- [ ] **Devices/peripherals:** inspect PnP identity and device problem codes; implement only validated enable/disable operations using exact device instance IDs, elevation boundaries, approval and a recovery path; do not add generic driver/firmware installation.
- [ ] **Audio/display/power:** implement supported audio endpoint/volume, display and power-plan operations; require direct immediate confirmation for lock, sleep, shutdown, restart and sign-out.
- [ ] **Maintenance/security:** expose status and named bounded workflows such as Defender scan requests, update checks and selected built-in repair diagnostics; do not weaken security controls or silently install updates.
- [ ] **UI Automation:** add an opt-in, process-allowlisted, bounded UIA adapter as a fallback; never extract passwords, arbitrary form values, browser content or sensitive control text.
- [ ] **Named command recipes:** use fixed, versioned PowerShell/CIM handlers with typed parameters; never expose arbitrary `execute_powershell(command)`, arbitrary `cmd.exe`, or a generic elevated terminal.
- [ ] **Cross-domain workflows:** implement representative end-to-end workflows that combine multiple Windows capabilities, show the plan, enforce per-step permissions, verify each result and stop safely on partial failure.
- [ ] Mark every catalogue entry available only when its concrete handler and health check are implemented; do not claim a whole category is supported because one action exists.

### Policy, safety, verification and recovery
- [ ] Reuse AIE policy broker, capability manifests, approval queue, execution-control, registered adapter executor and audit ledger.
- [ ] Apply risk tiers and default-deny to every mutating tool.
- [ ] Bind approval to exact capability, arguments, target identity, expiry and one execution attempt.
- [ ] Keep the normal APEX process unelevated; use narrowly scoped Windows UAC/broker operations when needed.
- [ ] Add dry-run/preview, preconditions, target revalidation, before-state capture and independent postcondition verification.
- [ ] Add cancellation, timeouts, rate limits, duplicate-action protection, per-capability disable and global kill switch.
- [ ] Add rollback/compensation for reversible operations; block actions without an acceptable recovery story where risk is high.
- [ ] Protect Windows security controls, protected processes, critical services, anti-cheat software and user data from generic automation.
- [ ] Audit request, selected tool, normalized arguments, policy decision, approval, execution receipt, verification and failure without logging secrets.

### Phase 1 tests and exit criteria
- [ ] Unit tests for identity, config, capability manifests, schemas, routing, policy and prompt composition.
- [ ] Adapter tests for every supported action domain with valid/invalid parameters and unavailable providers.
- [ ] Windows integration tests for real state changes and independent postcondition verification on the target Windows 11 machine.
- [ ] Test permission denial, UAC cancellation, protected targets, PID reuse, stale device IDs, network loss, timeout, cancellation and partial workflow failure.
- [ ] Test that opening a Settings URI is not reported as a successful setting mutation.
- [ ] Test audit-chain integrity, duplicate-action prevention, approval expiry, kill switch and rollback/compensation.
- [ ] Verify no arbitrary shell/code execution path is reachable from model output.
- [ ] Verify APEX never claims a capability absent from the live manifest.
- [ ] Verify normal operation does not require typing Ollama commands or opening a terminal.
- [ ] Measure first-token latency, warm/cold response time, host RAM/CPU and action latency on the target device.
- [ ] Phase 1 review and ADR updates.

**Exit criteria:** APEX can understand a natural-language Windows request, select and execute a registered typed capability under policy, verify the resulting OS state and report the result honestly. Tested operations must span the Section 9 Windows automation domains; chat-only operation or a tiny Settings-URI allowlist is not sufficient.

## Phase 2 — Expanded real-time Windows perception
- [ ] Define versioned provider contracts and normalized evidence envelopes.
- [ ] Connect the existing AIE Windows observer/event store.
- [ ] Build a SENTINEL read-only provider adapter using a documented API/contract.
- [ ] Expand hardware, CPU/RAM/GPU, process, service/driver, startup/task, storage, network, event and bounded ETW evidence.
- [ ] Add source health, timestamp, freshness, coverage, permission and event-loss metadata.
- [ ] Add adaptive sampling and resource/game-aware load shedding without LLM polling.
- [ ] Confirm no direct writes to SENTINEL's private SQLite database and no SENTINEL UI dependency.
- [ ] Make automation handlers consume the same read-only provider contracts for preconditions and verification.

**Exit criteria:** APEX can answer whole-Windows questions using fresh evidence while the SENTINEL dashboard remains closed; the same evidence providers support automation preconditions and verification.

## Phase 3 — Profile and unified memory
- [ ] Reuse AIE MemoryStore; avoid a parallel APEX database.
- [ ] Add APEX namespace/source tags to memory records.
- [ ] Separate user profile, conversation history, system observations and memories.
- [ ] Implement explicit onboarding for owner name, salutation, locale and preferences; initialize salutation to `sir`.
- [ ] Implement explicit memory capture, review, correction, export and deletion.
- [ ] Implement relevant, non-sensitive memory retrieval with bounded prompt budget.
- [ ] Preserve provenance, confidence, sensitivity, verification and expiry.
- [ ] Define retention for conversations, profile facts, incidents and telemetry.
- [ ] Test restart persistence, conflicting facts, stale memory and deletion.

**Exit criteria:** user-approved profile and memories persist across restarts; the user can inspect and control stored information without a duplicate memory database.

## Phase 4 — Advanced Windows diagnostic intelligence
- [ ] Implement specialist profiles and request/task classification for complex diagnostics.
- [ ] Build bounded evidence/context composition with evidence IDs.
- [ ] Add deterministic process/service/network/storage/event correlation and incident records.
- [ ] Add model-generated hypotheses, alternative explanations and next checks grounded in evidence.
- [ ] Separate observations, hypotheses, missing evidence and recommendations.
- [ ] Require supporting evidence IDs for machine-specific findings.
- [ ] Add diagnostic benchmarks and human-reviewed expected outcomes.
- [ ] Measure grounding, accuracy, false positives, false negatives and confidence calibration.

**Exit criteria:** diagnostics are repeatable, evidence-backed and calibrated; correlation is not presented as proof of causation.

## Phase 5 — Adaptive autonomy and background operation
- [ ] Reuse AIE planning/task orchestration and durable run lifecycle.
- [ ] Add bounded goal loop with max step, time, token and tool budgets.
- [ ] Add runtime load shedding based on RAM, CPU, foreground activity and game state.
- [ ] Add anomaly-triggered diagnostic jobs; do not call LLM on every sample.
- [ ] Add user-configured proactive notification preferences.
- [ ] Add pause/resume, per-provider disable, per-capability disable and stale-task reconciliation.
- [ ] Permit bounded autopilot only for individually enabled, reversible, low-risk Phase 1 capabilities with strong verification.
- [ ] Validate protected-game behavior with existing SENTINEL/AIE guard contracts.
- [ ] Measure idle/background overhead and impact during real gaming sessions.

**Exit criteria:** background automation remains bounded and stops/degrades safely when evidence, permissions or resource headroom are unavailable. This phase extends Phase 1 automation; it does not introduce it.

## Phase 6 — Standalone desktop experience (UI intentionally later)
- [ ] Choose UI technology after host/API contracts stabilize.
- [ ] Create an independent APEX desktop application; do not embed it in SENTINEL UI.
- [ ] Add a separate APEX notification-area/tray controller.
- [ ] Add Start Menu/desktop shortcuts and optional per-user sign-in startup.
- [ ] Start/connect to Ollama and APEX host without a visible terminal.
- [ ] Add model/provider health, capability status and automation controls.
- [ ] Add chat, diagnostic report, memory/profile, approval queue and action timeline surfaces.
- [ ] Add accessible keyboard navigation and reduced-motion handling.
- [ ] Add installer, updater, uninstaller and rollback.
- [ ] Verify the background host remains usable when the APEX window is closed, if enabled.
- [ ] Verify SENTINEL UI and existing AIE desktop surfaces remain unchanged.

**Exit criteria:** APEX installs and runs as an independent Windows app without requiring the user to type Ollama CLI commands.

## Phase 7 — Evaluation and optional fine-tuning
- [ ] Establish prompt-only APEX baseline before adapter experiments.
- [ ] Create consented/licensed conversation-style, Windows automation and tool-selection datasets.
- [ ] Keep private telemetry, credentials and arbitrary desktop logs out of training data.
- [ ] Run held-out base-versus-adapter evaluation across reasoning, coding, Windows and tool-use tasks.
- [ ] Test that model adaptation cannot bypass policy or create unsupported capabilities.
- [ ] Train a separate LoRA adapter only if prompt/runtime/tool improvements are insufficient.
- [ ] Preserve immutable base model and adapter rollback.

**Exit criteria:** any adapter improves measured outcomes without unacceptable capability regression or privacy/safety failure.

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
