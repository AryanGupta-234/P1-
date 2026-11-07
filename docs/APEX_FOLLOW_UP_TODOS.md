# APEX — Follow-up TODOs

**Owner:** APEX implementation  
**Branch:** `feature/apex-phase-1-runtime`  
**Base:** `feature/apex-standalone-assistant-plan`  
**Source plan:** [APEX Standalone Implementation Plan](APEX_STANDALONE_IMPLEMENTATION_PLAN.md)  
**Status convention:** TODO / IN_PROGRESS / BLOCKED / DONE. Mark DONE only with code, tests and validation evidence.

**Implementation status (2026-11-07):** The standalone runtime now registers 71 APEX capability IDs: the original 57 Windows/runtime tools plus nine Phase 1 extensions for power-plan inspection/selection, read-only Defender and Windows Update diagnostics, explicit memory search/save/forget, bounded UIA wait-for, trusted runtime-manifest introspection, and native per-interface Wi-Fi software-radio inspection/toggle, and Windows Bluetooth radio inspection/control through PyWinRT, and fixed allowlisted Windows 11 shell/virtual-desktop shortcuts. Direct loopback Ollama HTTP always sends `think: false`; a deterministic lexical router supplies only task-relevant tool schemas (bounded to 18) rather than the full registry on every request. No Ollama CLI, CMD, PowerShell or subprocess inference path exists. The APEX-only SQLite schema is version 2 and includes memory APIs, audit/change records and a persistent emergency-stop flag. A temporary approval-gated smoke-test console and Windows quickstart are included. Lint has passed on the latest run; the full test suite exposed an outdated APEX process-termination expectation and two pre-existing PRIXON identity-test mismatches. Windows 11 target-machine validation is still pending. The standalone desktop UI remains deferred to Phase 6. Phase 1 is expanded but not yet marked complete.

## Phase 0 — Planning and repository alignment

- [x] APEX standalone product boundary documented.
- [x] APEX independence from AIE and SENTINEL documented.
- [x] Standalone lifecycle and future UI separation documented.
- [x] Architecture decision record created.
- [x] Follow-up backlog created.
- [ ] Review this plan against the current `dev` branch before implementation.
- [ ] Confirm APEX branch will integrate to `dev` only through a reviewed PR.
- [ ] Confirm no changes are required to the existing SENTINEL UI/API for the first APEX milestone.

**Exit criteria:** product boundary and integration ownership accepted; no duplicated model/memory/policy/runtime subsystem.

## Phase 1 — APEX runtime + whole-Windows automation engine (first coding milestone)

### Runtime, identity and model
- [ ] Inspect APEX's own model request/response contracts and tests.
- [ ] Inspect current Ollama adapter, router, locking and runtime memory-admission behavior.
- [ ] Capture the currently applied APEX model definition with `ollama show --modelfile APEX`; compare it with the source Modelfile before editing. Keep an immutable baseline copy in the user's local project artifacts (do not commit local absolute paths or private machine data).
- [ ] Make only a targeted Modelfile `SYSTEM` correction if needed: APEX identity, creator attribution policy, model/host distinction, no false Microsoft claim, no unsupported Windows/kernel-access claims, honest bare-CLI limitations, conversational style and default `sir` salutation.
- [ ] Preserve the existing `FROM`, model-specific `TEMPLATE`, tokenizer/stop settings and working parameters unless an isolated regression proves a defect; do not fine-tune or replace Qwen for identity issues.
- [ ] Define a versioned runtime system-prompt composer that appends trusted build metadata, live manifest, current user profile, relevant memory/evidence and only task-relevant tool schemas; never bake live system facts or executable permissions into the Modelfile.
- [ ] Add host-side deterministic self-description for identity/model/provider/capability questions so the LLM cannot invent current connected tools, owner identity or Windows visibility.
- [ ] Define the `apex/` package boundary without moving or renaming existing AIE/SENTINEL packages.
- [ ] Define versioned APEX-owned configuration, identity, prompt and schema-migration contracts; do not couple to other model research identities.
- [ ] Implement the local APEX host lifecycle, structured logging, bounded sessions and request lifecycle controls; streaming remains a follow-up.
- [ ] Connect to the loopback Ollama API through APEX's own Python HTTP adapter; select the installed `APEX` model tag when available. Optionally launch the installed Windows `ollama app.exe` directly at host startup when the API is not responding.
- [ ] Never auto-pull a model or silently use cloud inference.
- [ ] Keep thinking disabled for all Phase 1 inference; Python always sends `think: false` and no runtime override is exposed.
- [ ] Extend `ModelRequest` with an explicit `think` field and send `think: false` in ordinary `/api/chat` calls; do not rely on a terminal `--think=false` flag once the APEX host owns inference.
- [ ] Extend `ChatMessage` with Ollama's `tool` role and validated tool-name metadata; extend `ModelRequest` with typed tool schemas and bounded tool-call policy.
- [ ] Extend `ModelResponse` and Ollama response parsing to retain `message.tool_calls` rather than dropping them and returning only text content.
- [ ] Send registered tools in Ollama `/api/chat` requests, execute calls only through APEX's validated host dispatcher and APEX-owned policy broker, append sanitized tool results and continue a bounded multi-turn tool loop.
- [ ] Add request/response contract tests for no-think propagation, tool-call parsing, tool-role round-trips, multiple calls, malformed arguments, unknown tools, timeout and tool-loop budget exhaustion.
- [ ] Add bounded timeouts/output/context and one local inference slot within the standalone APEX runtime; do not share AIE model consumers.
- [ ] Record model/provider health, token counts, load time, time-to-first-token, generation time and failures.
- [ ] Add `apex_get_runtime_manifest` with actual model, provider, tool, permission and availability state.
- [ ] Ensure normal runtime does not require a visible CMD/PowerShell window or manual `ollama run`; the host must connect to or start the installed Ollama service through a documented Windows mechanism, while developer mode may use a console.
- [ ] Add regression tests for the exact transcript failures: no false Microsoft creator claim; distinguish APEX host identity from Qwen foundation-model provenance; answer configured creator/operator attribution from metadata; use the approved profile for the user's name; default to `sir`; never claim live access/kernel access without a healthy provider.
- [ ] Run the pasted identity/conversation regression suite through the Python APEX host: identity, operator attribution and model provenance come from the runtime manifest; process questions invoke the actual process provider; other Windows questions invoke registered tools or honestly report unavailable providers. No CLI inference path is used.
- [ ] Assert direct CLI mode never says Microsoft created APEX, never claims sandbox/physical-PC/kernel access, and never claims it can see the user's name or processes without host context.
- [ ] Assert host mode answers `who made you`, `what model are you`, `what tools are connected`, `who is your user`, and `can you see my processes` from build/profile/provider metadata with provenance.
- [ ] Ensure “Can you see my running processes?” calls a real process-inventory capability and returns a timestamped bounded snapshot, or clearly reports why the provider is unavailable.

### Intent interpretation and tool orchestration
- [ ] Classify each request as chat, explain, inspect, diagnose, plan or automate without forcing every message into a tool call.
- [ ] Implement structured multi-turn tool calling and host-side dispatch; never execute model-supplied code directly.
- [ ] Build a typed capability registry with schema version, source, health check, risk tier, privilege, approval rule, timeout, rate limit, verifier and compensation metadata.
- [ ] Implement the canonical UnifiedDataStore connection factory and one-writer/multi-reader access layer, with WAL, foreign keys, busy timeout, bounded transactions and an append-only change-sequence journal.
- [ ] Add database schema/field registry, versioned JSON payloads and validated extension fields so optional fields can evolve without ad-hoc SQL schema mutation.
- [ ] Put application catalogue, discovery sources, aliases, model enrichment, scan state and launch history in dedicated tables inside the same unified database.
- [ ] Initialize and migrate only APEX-owned schema into apex-unified.sqlite3 with backup, migration journal, integrity checks and rollback. Do not read or migrate any AIE databases.
- [ ] Route every APEX repository (profile, conversation, memory, app catalogue and task context) through the exact APEX canonical database path; assert resolved paths are identical in tests.
- [ ] Do not allow APEX profile, conversation, application-catalogue or memory writes until the canonical DB has completed migration/integrity checks.
- [ ] Implement multi-step workflow plans with preconditions, dependencies, progress, cancellation and per-step policy checks.
- [ ] Ask one focused clarification when a target or operation is materially ambiguous; do not guess destructive targets.
- [ ] Report unsupported, disabled, unavailable and approval-gated capabilities distinctly.

### Desktop interaction and everyday automation — required Phase 1 coverage
- [ ] Implement a general desktop-interaction tool family with target window/control identity, typed arguments, bounds, timeouts and structured receipts.
- [ ] Implement pointer actions: move, left/right/middle click, double-click, hover, drag/drop and coordinate targeting only against a freshly resolved target.
- [ ] Implement vertical and horizontal wheel scrolling; prefer UIA ScrollPattern/semantic container scrolling and use real wheel input only when needed.
- [ ] Implement keyboard actions: key down/up, shortcuts/hotkeys, safe text entry, navigation keys and app-specific keystrokes; ensure held keys are released after cancellation/error.
- [ ] Implement window controls: list windows, resolve process/window identity, focus, restore, minimize, maximize, move, resize, snap, close and switch between apps/windows.
- [ ] Implement common desktop-shell actions: Start menu, taskbar launch/switch, notification/quick-settings surfaces and supported virtual-desktop operations.
- [ ] Implement UIA tree/control inspection for allowlisted apps: invoke, set value, select, toggle, expand/collapse, select tab, wait-for, scroll, inspect enabled/disabled state and verify postconditions.
- [ ] Implement a desktop interaction lease: verify foreground target, serialize injected input, detect user mouse/keyboard/focus activity, pause/abort promptly and never fight for control.
- [ ] Enforce interactive-desktop and integrity boundaries: no input injection on locked/sign-in/UAC secure desktop; respect UIPI and elevation; do not bypass application protection.
- [ ] Implement master volume read/set/mute and endpoint selection through Windows Core Audio; implement per-app session volume only where the OS exposes a reliable session.
- [ ] Implement supported media actions (play/pause/next/previous, mute, volume) through session APIs or bounded multimedia-key fallback.
- [ ] Implement explicit clipboard set/get/copy/cut/paste tools scoped to a user-requested task; never watch or harvest clipboard contents in the background.
- [ ] Implement non-sensitive text entry into a verified active control; sensitive password/credential/payment fields must be blocked from model-provided text entry.
- [ ] Add application-specific adapters for selected apps; keep the general UIA path for accessible controls and report unsupported controls honestly.
- [ ] Keep screenshot/vision-based coordinate interaction opt-in and separate from baseline UIA/input tools; require fresh screen evidence, explicit scope and retention limits before adding it.
- [ ] Ensure browser/video observation does not imply general browser automation; any tab/navigation/action bridge requires a separate documented browser adapter and user opt-in.

### Live Windows baseline and built-in command knowledge — required Phase 1 coverage
- [ ] Implement live OS/build and device summary, current-session facts from documented APIs, process inventory/details, foreground-window/application metadata, service/startup/task state, adapter/DNS/route state, volume/free-space state and CPU/RAM load.
- [ ] Return source/provider, observed timestamp, freshness, permission level and coverage for every live result; missing/denied/stale values must never be represented as healthy or zero.
- [ ] Add a versioned OS-aware catalogue for known `ms-settings:` page URIs, Control Panel `.cpl` applets, MMC `.msc` consoles and approved Windows management entry points.
- [ ] Add validated lookups/openers for common targets such as Device Manager, Power Options, Network Connections, Programs and Features and other documented applets; check target existence and OS availability before dispatch.
- [ ] Test exact user questions about Settings URIs, CPL/MSC commands and the difference between opening a page and changing a setting.

### Dynamic installed-application catalogue — required Phase 1 coverage
- [ ] Define a normalized app record: display name, aliases, executable path or AUMID, package family, version, publisher, source provenance, signature/trust state, install root, file identity/timestamps, last-seen time, confidence and launch availability.
- [ ] Enumerate App Paths registrations under HKCU/HKLM in 32-bit and 64-bit registry views; expand environment variables and validate resolved executable paths.
- [ ] Enumerate Uninstall registry metadata under HKCU/HKLM and both views; use DisplayName/Publisher/DisplayVersion/InstallLocation/DisplayIcon as hints only, never assume a display icon or install directory is an executable.
- [ ] Enumerate current-user and all-users Start Menu shortcuts; resolve Shell Link target, working directory, icon and arguments as untrusted metadata.
- [ ] Enumerate packaged apps from package manifests and AUMIDs; consume Get-StartApps as one source only because it omits apps not represented in Start; do not crawl protected WindowsApps directories.
- [ ] Correlate live process executable paths with catalogue records but do not automatically trust every running binary for future launch.
- [ ] Implement full application-discovery scan for accessible fixed local volumes to locate apps installed in custom folders, including per-user application directories; scan only executable/shortcut/package metadata, never document/browser/email contents.
- [ ] Skip reparse points by default and report inaccessible volumes/paths as coverage gaps; exclude large Windows component/servicing stores, caches, restore points and Recycle Bin internals; use package metadata for WindowsApps.
- [ ] Keep full-volume scanning cancellable, low priority and resource-aware; throttle/pause during gaming, high foreground load, low battery or memory pressure.
- [ ] Use existing Windows Search metadata as an optional accelerator only; never silently enable Enhanced indexing or change user indexing/privacy settings.
- [ ] Add incremental refresh from registry/package change signals, file-system notifications on known roots and scheduled bounded reconciliation; no continuous full-volume scan.
- [ ] Store the rebuildable app catalogue in separate tables inside the canonical UnifiedDataStore; do not mix app catalogue records into personal-memory retrieval or index file contents.
- [ ] Build alias/name resolution across display name, product/file description, executable basename, shortcut name, package name and user-confirmed aliases.
- [ ] Rank candidates by source confidence, path existence, package identity, publisher/signature and user trust; a valid signature alone does not prove safety, and unsigned apps may be explicitly approved.
- [ ] Reject deleted paths, path/reparse escapes and temporary/download/cache candidates under default launch policy; ask the user when multiple stable/beta/portable matches remain.
- [ ] Launch desktop applications via validated canonical executable paths and packaged apps via validated AUMIDs; do not accept model-generated arbitrary command-line arguments.
- [ ] Verify launch using fresh process/window/package evidence and distinguish process creation from a ready/usable window.
- [ ] Mark moved/updated/uninstalled executables stale and re-resolve them; expose source, resolved target, trust and last scan in the app catalogue.
- [ ] Add a local model-enrichment queue for incomplete/ambiguous app metadata; send only minimized extracted metadata, never file contents or binaries.
- [ ] Request only normalized app/product identity, vendor/product family, alias suggestions, broad category, short purpose and confidence; schema-validate outputs and allow unknown.
- [ ] Never allow model enrichment to write/alter EXE paths, AUMIDs, package IDs, signature/publisher evidence, trust decisions, permissions or launch arguments.
- [ ] Store model tag, prompt version, output schema version, candidate/evidence IDs, timestamp, confidence and review state with the suggestion in the unified database.
- [ ] Batch/deduplicate enrichment by file identity/version, run local-only at low priority and re-enrich only when source metadata changes or the user asks.

- [ ] **Applications/windows:** enumerate supported app/window metadata; launch registered applications; activate, minimize, maximize and close user-owned windows; test exact-target protection for process/window actions.
- [ ] **Files/folders:** browse/search user-approved roots; inspect metadata; create folders; copy, move and rename; support Recycle Bin deletion; block permanent deletion, bulk deletion and protected paths by default.
- [ ] **Settings/personalization:** implement typed read/write handlers for supported volume, brightness, display, power, Wi-Fi, Bluetooth, night-light, focus/notification and accessibility settings. Distinguish opening a Settings page from successfully changing a setting.
- [ ] **Processes/apps:** inspect process state; launch registered executables; close through supported application/window paths; permit termination only for specifically allowlisted non-protected targets after PID plus creation-time revalidation and approval.
- [ ] **Services/startup/tasks:** inspect services/startup entries/scheduled tasks; enable/disable registered startup items; run/manage named tasks; start/stop only approved noncritical services; protect critical Windows, security, networking, storage and anti-cheat services.
- [ ] **Networking:** inspect adapters, DNS, routes, proxy and connectivity; implement supported adapter toggles, DNS configuration, DHCP renew/release and bounded repair recipes; require approval and recovery planning for network resets, proxy/firewall changes and disconnecting actions.
- [ ] **Devices/peripherals:** inspect PnP identity and device problem codes; implement only validated enable/disable operations using exact device instance IDs, elevation boundaries, approval and a recovery path; do not add generic driver/firmware installation.
- [ ] **Audio/display/power:** implement master/per-session volume where supported, mute, endpoint selection, media controls, brightness/display/power-plan operations; require direct immediate confirmation for lock, sleep, shutdown, restart and sign-out.
- [ ] **Maintenance/security:** expose status and named bounded workflows such as Defender scan requests, update checks and selected built-in repair diagnostics; do not weaken security controls or silently install updates.
- [ ] **UI Automation:** implement a first-class, process-allowlisted and bounded UIA adapter. Prefer semantic patterns over coordinates. Never extract passwords, browser secrets or sensitive form values.
- [ ] **Named command recipes:** use fixed, versioned PowerShell/CIM handlers with typed parameters; never expose arbitrary `execute_powershell(command)`, arbitrary `cmd.exe`, or a generic elevated terminal.
- [ ] **Cross-domain workflows:** implement representative end-to-end workflows that combine multiple Windows capabilities, show the plan, enforce per-step permissions, verify each result and stop safely on partial failure.
- [ ] Mark every catalogue entry available only when its concrete handler and health check are implemented; do not claim a whole category is supported because one action exists.

### Policy, safety, verification and recovery
- [ ] Use APEX-owned policy broker, capability manifests, approval queue, execution-control, registered adapter executor and audit ledger.
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
- [ ] Interactive desktop integration tests for move/click/double-click/right-click/drag, vertical/horizontal scroll, keyboard shortcuts, targeted text input, focus/window switching, UIA invoke/set/select/toggle/scroll and cancellation.
- [ ] Audio tests for master volume read/set/mute, endpoint changes and supported per-app media sessions; verify actual post-state rather than trusting dispatch.
- [ ] Test user interruption: moving the mouse, typing, changing focus or cancelling must stop an injected-input sequence immediately and release held keys/buttons.
- [ ] Test that input injection fails safely on locked/secure desktop or when blocked by Windows integrity/UIPI; no bypass or elevation escalation.
- [ ] Test clipboard actions are explicit, scoped and never run as a passive collector; test sensitive text fields are excluded.
- [ ] Windows integration tests for real state changes and independent postcondition verification on the target Windows 11 machine.
- [ ] Test migration of events.sqlite3, memory.sqlite3, task-runs.sqlite3 and task-sessions.sqlite3: source/target row counts, stable IDs, lineage/references, checksums, duplicate handling and post-migration integrity.
- [ ] Test migration interruption and restart, migration journal idempotency, backup restoration and rollback without deleting original source files.
- [ ] Assert EventStore, MemoryStore, TaskRunStore and TaskSessionStore all resolve to the same canonical apex-unified.sqlite3 file after migration.
- [ ] Test permission denial, UAC cancellation, protected targets, PID reuse, stale device IDs, network loss, timeout, cancellation and partial workflow failure.
- [ ] Test that opening a Settings URI is not reported as a successful setting mutation.
- [ ] Test that known app names resolve through App Paths/Uninstall/Start Menu/AUMID sources and that non-Start apps remain discoverable through other sources.
- [ ] Test full-volume executable discovery, cancellation, inaccessible folders, reparse-point protection, exclusion rules, stale records and incremental refresh without reading file contents.
- [ ] Test ambiguous app names, invalid/moved executable paths, untrusted download/temp binaries, signed/unsigned publisher states and user-approved exceptions.
- [ ] Test packaged-app activation by AUMID and desktop-app launch by exact canonical executable path; verify the resulting process/window.
- [ ] Test local model enrichment is skipped when Ollama is unavailable while deterministic executable discovery still completes.
- [ ] Test enrichment batches are deduplicated by executable identity/version and are not invoked once per scanned file.
- [ ] Test strict enrichment schema, unknown values, confidence bounds and provenance; reject attempts to alter EXE paths, AUMIDs, publisher/signature evidence, trust, privilege or launch arguments.
- [ ] Test a new validated extension field can be stored/read without a destructive table rewrite and remains compatible with older record schema versions.
- [ ] Test audit-chain integrity, duplicate-action prevention, approval expiry, kill switch and rollback/compensation.
- [ ] Verify no arbitrary shell/code execution path is reachable from model output.
- [ ] Verify APEX never claims a capability absent from the live manifest.
- [ ] Verify normal operation does not require typing Ollama commands or opening a terminal.
- [ ] Measure first-token latency, warm/cold response time, host RAM/CPU and action latency on the target device.
- [ ] Phase 1 review and ADR updates.

**Exit criteria:** APEX can understand a natural-language request for either a tiny interaction or a multi-step Windows workflow, select and execute a registered typed capability under policy, verify the resulting state and report the result honestly. Phase 1 tests must explicitly include opening apps, volume changes/mute, window switching, clicks, keyboard shortcuts, targeted text entry, scrolling and semantic UIA operations as well as system/file/network workflows; chat-only operation or a tiny Settings-URI allowlist is not sufficient.

## Phase 2 — Expanded real-time Windows perception
- [ ] Formalize and extend Phase 1 provider contracts and normalized evidence envelopes.
- [ ] Implement APEX-owned Windows provider and evidence contracts; do not connect AIE stores.
- [ ] [OUT OF PHASE 1] Any future SENTINEL connection requires a separately approved read-only protocol and is not an APEX dependency.
- [ ] Expand beyond Phase 1 baseline into richer GPU/sensor coverage, per-process resource deltas, storage I/O, bounded Windows Event Log metadata and validated ETW event families.
- [ ] Add deeper source health, timestamp, freshness, coverage, permission and event-loss metadata.
- [ ] Add adaptive sampling and resource/game-aware load shedding without LLM polling.
- [ ] Confirm APEX code has no direct SENTINEL database, module or UI dependency.
- [ ] Make automation handlers consume the same read-only provider contracts for preconditions and verification.

**Exit criteria:** APEX can answer whole-Windows questions using fresh evidence from its own providers; the same evidence providers support automation preconditions and verification.

## Phase 3 — Unified profile and memory workflows
- [ ] Extend the already-migrated Phase 1 canonical SQLite database; do not create any additional APEX memory or application-catalogue database.
- [ ] Add profile, conversation/session, diagnostic incident and reviewed workflow tables to the same file; application catalogue/enrichment tables are already established in Phase 1.
- [ ] Verify policy and egress audit stores remain separated only where their tamper-evidence/integrity boundary requires it; do not treat them as alternate memory stores.
- [ ] Extend the Phase 1 schema registry with profile/memory fields, per-record schema versions and backward-compatible migrations/deprecation handling.
- [ ] Ensure strict validation of extension values; no arbitrary field names/SQL identifiers or untrusted model-defined schemas.
- [ ] Implement explicit onboarding for owner/preferred name, salutation, locale, communication style, device aliases and preferences; initialize salutation to `sir`.
- [ ] Add optional local indexing of explicitly selected user folders/documents with inspectable paths, retention and deletion; exclude credentials, browser secrets, protected/system folders and unselected locations.
- [ ] Implement explicit memory capture, review, correction, export, deletion and relevant non-sensitive retrieval.
- [ ] Preserve provenance, confidence, sensitivity, verification, lineage and expiry across profile/memory updates and corrections.
- [ ] Extend the Phase 1 real-time change journal/subscription and optimistic-concurrency contracts to profile and memory updates; keep all reads/writes on the shared repository layer.
- [ ] Test that two feature modules reading/writing profile, memories, app catalogue and task context share the same physical database file and consistent sequence.
- [ ] Test profile/memory persistence, corrections, expiry, conflict handling, data export/deletion and backward-compatible schema extension upgrades.

**Exit criteria:** all APEX durable memory/profile/conversation/application knowledge/task context is in one physical database, live-readable through one access layer, extensible through validated versioned fields and migrated without data loss. No AIE or SENTINEL data is accessed or merged.

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
- [ ] Implement APEX-owned planning/task orchestration and durable run lifecycle.
- [ ] Add bounded goal loop with max step, time, token and tool budgets.
- [ ] Add runtime load shedding based on RAM, CPU, foreground activity and game state.
- [ ] Add anomaly-triggered diagnostic jobs; do not call LLM on every sample.
- [ ] Add user-configured proactive notification preferences.
- [ ] Add pause/resume, per-provider disable, per-capability disable and stale-task reconciliation.
- [ ] Permit bounded autopilot only for individually enabled, reversible, low-risk Phase 1 capabilities with strong verification.
- [ ] Validate protected-game behavior with APEX-owned anti-cheat and protected-process guards.
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
- [ ] Verify the independent APEX product has no UI coupling to AIE or SENTINEL.

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

Continue the remaining Phase 1 capability work and Windows validation on `feature/apex-phase-1-runtime`. Keep the desktop UI deferred. Do not integrate APEX into AIE or SENTINEL, and do not enable autonomous mutations without a host-owned approval/verification flow.
