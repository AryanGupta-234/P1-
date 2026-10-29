# SENTINEL Implementation Plan

**Target:** Windows 11 x64 · local-first desktop runtime  
**Plan revision:** 1.4 · **Release baseline:** 1.2.35  
**Status:** `[x]` existing capability · `[~]` integration/verification in progress · `[ ]` planned

This is the single consolidated backlog for the next SENTINEL upgrade. It extends the existing collectors, SQLite store, maintenance executor, safeguard, adaptive runtime, AI council, memory engine, rollback journal and dashboard; it does not replace them.

## Product objective

Make SENTINEL a Windows-specialist, goal-driven performance and reliability assistant: observe the PC, establish evidence, explain likely causes, prepare a safe plan, obtain approval, execute only a bounded allowlisted action, verify the result and learn from measured outcomes. Keep the product GUI-first with compact status, visual system maps, animated progress, guided cards, previews and action timelines. Technical details belong in expandable evidence views.

## Non-negotiable operating contract

1. **Maintenance mutations remain manual-only in the current implementation.** Every maintenance write needs a fresh preview and explicit confirmation. Model, scheduler, goal engine and chat cannot bypass this.
2. A future low-risk autonomy tier is a separate, disabled-by-default policy gate requiring individually reviewed reversible actions and independent verification; it does not silently change today's manual-only default.
3. Medium-risk operations require approval. Dangerous, irreversible, security-sensitive or poorly reversible operations remain blocked or guided-only.
4. Steam/Epic launcher-owned game directories are never moved, renamed or rewritten by SENTINEL. Inventory and launcher-guided instructions only.
5. OEM fan profiles remain guided through signed vendor utilities. No undocumented EC, ACPI, firmware-register or fan writes.
6. BIOS/UEFI, firmware, Secure Boot, Defender/Tamper Protection and Riot Vanguard protections are outside automatic modification. Vanguard is never stopped, bypassed or inspected internally.
7. The model is advisory, never a policy authority, shell executor, privilege broker or safeguard override.
8. Every write action requires exact target identity, preconditions, bounded scope, preview, snapshot/undo strategy, verification and journal entry. If rollback is unreliable, the action is guided or blocked.
9. Evidence, models, embeddings and learning records stay local by default. External data transfer requires separate explicit opt-in.
10. Missing permissions, stale observers, uncertain identity, unsupported sensors and unknown system state fail closed.

## Existing foundation to preserve

- [x] Windows-focused Python agent, authenticated loopback API and local dashboard.
- [x] Existing collectors, performance counters, process inventory, network/system signals, hardware metadata and bounded WPR capture.
- [x] Separate Safeguard, Adaptive Runtime, AI Orchestrator, Unified Memory, Process Intelligence and action/maintenance engines.
- [x] Local Ollama routing with resource-aware FAST/DEEP selection and local embedding support.
- [x] Evidence-linked observations, persistent memory/revisions, semantic retrieval and reviewed goal-plan drafts.
- [x] Maintenance preview, expiring confirmation token, execution-time policy recheck, action budget, kill switch, journal and conditional undo.
- [x] Restore-point preflight for selected deep operations; driver export/rollback and bounded repair operations.
- [x] Read-only evidence-health report, OEM utility inventory, thermal trend alerts and Steam/Epic manifest inventory.
- [x] Launcher-safe game planner: inspection and guidance only; no direct game-folder movement.
- [x] Full-data boot hydration with bounded API concurrency, truthful module status and retry/degraded reporting.
- [~] Fix three 1.2.21 contract failures and rerun Windows CI before declaring the release green.

## P0 — Release integrity, recovery and least privilege

- [x] Preserve before/after snapshots, conditional undo metadata and revert-all journal.
- [x] Preserve manual-only maintenance preview/approval, kill switch and action budgets.
- [ ] Audit every maintenance action for precondition → snapshot → execute → verify → journal → undo.
- [ ] Verify restore-point availability and free space before deep repairs; do not imply one exists when System Protection is unavailable.
- [ ] Add action capability manifests: privilege, Windows builds, target type, reversibility, resource cost, prohibited contexts and verification probe.
- [x] Refactor the installed scheduled agent to a standard-user token and invoke a narrow elevated helper only for approved Administrator-required maintenance jobs.
- [x] Broker accepts a fixed action manifest and one-use job IDs only; it does not accept arbitrary PowerShell, command strings, executable paths or model-generated scripts.
- [x] Broker requests are one-time, expiring, principal/session-bound, auditable and Safeguard-rechecked immediately before execution. No reusable administrator token is persisted.
- [x] Show standard-user/elevated state in Maintenance and request UAC only after preview and final confirmation. Declined UAC cancels the job.
- [x] Fail closed when broker, principal/session binding, current process identity or safeguard state is unknown.
- [ ] Add a dedicated WPR/ETW UAC ticket adapter with trace ownership, provider allowlists, bounded capture and safe finalisation. Keep trace capture blocked under the standard-user task until this is implemented.

## P1 — Liquid-glass UI and data-rich boot

**Initial visual foundation and accent unification applied in 1.2.23**
- [x] Graphite `#171717`, deep forest `#06110c`, signal red `#a31c1b`, restrained green active/healthy accent.
- [x] Local Windows font stacks (Segoe UI Variable / Aptos / Bahnschrift and Cascadia Code); no remote font blocking boot.
- [x] Liquid-glass treatment for shell, nav, cards and boot console; restrained highlights.
- [x] Restyle startup reactor, progress and status surfaces while retaining DOM hooks and hydration sequence.
- [ ] Redesign every workspace with compact visual cards, signal strips, charts, contextual drawers and progressive disclosure; preserve functionality.
- [ ] Replace text walls with state labels, evidence/cause cards, timelines, confidence, action chips and expandable detail.
- [ ] Standardise icons, spacing, radii, shadows, empty/loading/error and confirmation states.
- [ ] Use transform/opacity for smooth animations; avoid continuous layout-heavy animation.
- [ ] Respect reduced motion, high contrast, keyboard navigation and focus visibility. Red indicates risk, not decoration.

**Boot performance**
- [x] Preserve complete boot hydration, bounded four-request concurrency, timeouts, retry and per-module ready/degraded reporting.
- [ ] Instrument auth, first snapshot, telemetry/history, critical workspaces, secondary workspaces, render and interactive-ready.
- [ ] Record local p50/p95 timings and display compact stage feedback.
- [ ] Add an aggregated boot snapshot endpoint to avoid repeatedly serialising identical state.
- [ ] Reuse backend snapshots/caches; browser must not start duplicate collectors.
- [ ] Defer WPR, deep inventory, model inference, ETW parsing and large disk scans outside critical boot.
- [ ] Keep splash until required workspaces are ready or honestly degraded; optional probes can load later.
- [ ] Remove artificial waits once data is ready, but never skip hydration or falsify progress.
- [ ] Establish target-laptop boot budgets and identify bottlenecks.

## P2 — Windows Knowledge Engine (version-aware RAG)

- [x] Define a Windows knowledge component taxonomy for kernel/scheduler, process, memory, storage, network, power, PnP, drivers, servicing, reliability, security and OEM sources.
- [x] Implement a local source registry and user-triggered HTTPS ingestion for approved Microsoft, Windows, Sysinternals and OEM documentation hosts.
- [x] Store URL, publisher, title, ingestion time, SHA-256, licence metadata, component, Windows build range, edition, architecture and API/command version.
- [ ] Prefer Microsoft primary sources; third-party references are corroboration with provenance.
- [ ] Do not scrape arbitrary scripts, binaries or unknown downloads; ingest documentation, not executable instructions.
- [x] Chunk and index documentation locally; provide bounded lexical retrieval filtered by component, Windows build, edition and architecture. Vector retrieval remains pending.
- [ ] Add freshness, deduplication, source retirement and re-indexing independent of fine-tuning.
- [x] Return source URL, publisher, licence, build/edition/architecture applicability, content hash and local citation identifier with each knowledge passage.
- [ ] Validate recommendations against detected Windows build, edition, architecture, device and component.

## P3 — Windows evidence and diagnosis

- [ ] Extend existing collectors; avoid duplicate polling loops.
- [ ] Bounded low-overhead CPU, memory, disk, network and process counters.
- [ ] ETW provider/session registry with ownership, bounded capture, loss counters, timestamps and schema/version metadata.
- [ ] Targeted WPR/ETW for scheduler, DPC/ISR, storage, network and process lifecycle; never stop another recorder's session.
- [x] Event Log correlation with channel allowlists, bounded windows, persisted cursors and redaction (Application/System, Diagnostics-Performance, Windows Update, Kernel-PnP and Task Scheduler).
- [ ] PnP/driver inventory with exact instance/hardware IDs, package/provider/version/date, signature and OS matching context.
- [ ] Power/battery/Modern Standby diagnostics via supported APIs and `powercfg`.
- [ ] Disk capacity/latency, filesystem and SSD TRIM diagnostics with capability checks.
- [ ] Read-only DNS, gateway, packet loss, jitter, adapter, Wi-Fi band/channel, MTU and route probes.
- [ ] Thermal correlation only for known sensor identity and units; distinguish CPU, GPU, SSD and board sensors.
- [ ] Evidence quality from freshness, source reliability, sample count and cross-source agreement; heuristic scores are not calibrated probabilities.
- [ ] Root-cause candidates include supporting/contradicting evidence and disambiguating probes.
- [ ] Redact credentials, document contents, cookies, browser history, clipboard, full command lines and unrelated personal data before storage/prompts.

## P4 — Local Windows Specialist Model and training

- [x] Separate `windows_intelligence` package; never merge the reasoner into maintenance executor.
- [ ] Start with installed small Qwen 3B candidate via loopback-only Ollama; use 7B only as optional quality comparison.
- [ ] One inference worker initially, bounded context/output, lazy loading, RAM/CPU admission, cancellation and game-session suppression.
- [x] Strict response schema: diagnosis, evidence IDs, confidence category, uncertainty, extra probes, allowed action IDs and safety notes.
- [x] Deterministic schema/evidence/action/version validation. Reject raw commands and scripts.
- [x] Ground in current evidence and local Windows documentation, not model memory alone.
- [ ] Separate datasets: public technical knowledge, synthetic diagnostic scenarios and user-approved anonymised outcomes.
- [ ] Cover CPU, memory, disk, network, thermal, driver, servicing, startup, power and device failures, including insufficient/conflicting evidence.
- [ ] Provenance/licence, schema validation, deduplication, privacy scrub and held-out splits.
- [ ] Evaluate RAG + prompting first; LoRA/PEFT only with measurable held-out gains.
- [ ] Version/checksum adapters and require independent evaluation/promotion; no online self-modification.
- [ ] Measure diagnosis accuracy, grounding, calibration, false positives, unsafe recommendations, build correctness, latency, RAM and forgetting.
- [ ] Model remains optional; all normal functionality works without Ollama.

## P4.1 — Local Windows specialist (implemented in 1.2.25)\n\n- [x] Dedicated advisory-only `windows_intelligence` module.\n- [x] Loopback Ollama inference through the existing AI resource-admission gate; cloud models are rejected.\n- [x] Context bounded to 24,000 characters and six local knowledge passages.\n- [x] Prompt-injection-resistant instruction hierarchy for retrieved documentation; sources are untrusted evidence.\n- [x] Strict JSON schema and deterministic citation, evidence-ID and action-ID validation.\n- [x] Unknown action IDs and unknown evidence citations are rejected; no raw command/script fields exist.\n- [x] GUI question/answer panel in the Windows Knowledge workspace.\n- [x] Recommendations are labelled advisory and never execute or create approvals.\n\n## P4.2 — Windows Intelligence Fusion (implemented in 1.2.32)

- [x] Cross-subsystem, privacy-filtered evidence packet for process/resource, service, startup, task, app, driver/update, event, maintenance, app-usage and prior-answer data.
- [x] Per-record evidence IDs and validation; context bounded to 24,000 characters.
- [x] SQLite Event Viewer cursors/bookmarks across restarts; 30-day retention and selective historical crash/hardware-fault backfill.
- [x] Event Viewer coverage for System, Application crashes, Diagnostics-Performance, Windows Update, Kernel-PnP and Task Scheduler.
- [x] Local AI system review on a 12-hour default cadence, configurable 6–168 hours, plus an operator-triggered review endpoint and Command control.
- [x] Review requires hydrated inventory/maintenance evidence, CPU/RAM admission and protected-game suppression; no mutations are executed.
- [x] User answers are reused as bounded local context; stopped/manual/rarely observed services are not assumed useless.
- [x] Privacy exclusions for command lines, window titles, browser content, credentials, file contents, accounts and remote addresses.
- [~] Expand service-dependency, publisher/signature and per-app user-intent evidence before any ranking of background-service changes.

## P4.3 — Longitudinal component intelligence (implemented in 1.2.33)

- [x] Separate agent-owned sampler for process identities and SCM service state; no second fast telemetry poller.
- [x] Five-minute process sampling, fifteen-minute service sampling, bounded candidate set and 30-day SQLite retention; extra process samples pause in game sessions.
- [x] Process identities stored as one-way path hashes plus binary basenames; no raw process executable paths in component tables.
- [x] In-memory bounded service executable paths for Authenticode only; persisted SCM graph strips binary paths and descriptions.
- [x] Safe-idle, resource-gated Authenticode/file-version metadata and Windows SCM dependency/dependent graph.
- [x] Seven-day minimum baseline, observed-day and sample gates; signed publisher requirement; process resource/foreground thresholds.
- [x] Review only third-party running auto-start services with no SCM dependents; this is not proof of application/user independence.
- [x] Protected Windows/security/Vanguard components excluded; no service disable or uninstall action.
- [x] Keep / Not needed / Ask later / note-only user preferences persisted and supplied to later local AI reviews.
- [x] Exact-instance visible-GUI graceful-close proposal path only; normal Actions approval required; no force termination.
- [x] Aggregation throttled to five-minute intervals and deferred enrichment retries back off for fifteen minutes.
- [x] Require low foreground and low historical visible/on-screen GUI-window sample ratios before ranking a process as a background candidate.
- [x] Separate evidence-coverage confidence, process resource impact, process review priority and service ownership-review scores; publish the formulas and caveats to UI and local AI.
- [x] Compare PE CompanyName metadata with the Authenticode certificate organization and surface mismatches.
- [x] Withhold service ownership candidates when the complete SCM dependency graph is missing, stale (>24 hours) or future-dated.
- [x] Graceful-close proposals require exactly one matching visible, on-screen, interactive process instance; ambiguous multi-instance matches fail closed.
- [x] Route registry autorun and scheduled-task executable basenames into local AI evidence; match only against the signed component catalogue, label basename matches as heuristic, omit task arguments and raw command strings, and make no startup/task changes.\n- [ ] Extend evidence with stronger signed startup-item identity and task-to-service/app relationships; keep all proposed changes preview/approval gated.

## P4.4 — Evidence-quality and ownership scoring (implemented in 1.2.34)

- [x] Persist historical visible-window and on-screen-window sample ratios; suppress candidates that are not consistently headless/background.
- [x] Publish an explicit evidence-coverage score, separate process impact score, review-priority heuristic and service ownership-coverage score.
- [x] Show PE company metadata beside the signer certificate organization and flag mismatches.
- [x] Hide service candidates unless a complete SCM dependency graph is present and no older than 24 hours.
- [x] Refuse graceful-close preparation when multiple visible process instances share the same executable identity.
- [x] Pause the supplementary process sampler during active game sessions.

## P5 — Windows action library

All new writes start manual-only and use shared preview, capability manifest, broker when elevated, Safeguard, snapshot, verification and undo. Never execute model-generated commands.

**Startup/background**
- [ ] Inventory startup registry, startup folders, tasks and service startup types with publisher/path provenance.
- [ ] Per-user startup disable/enable with exact snapshot and conditional restore.
- [ ] Delay/sequencing only through supported, restorable Windows mechanisms.
- [ ] Session pause/resume for narrowly allowlisted third-party updaters/sync clients; OneDrive only through supported UI/APIs.
- [ ] Never disable Defender, Windows Update, Vanguard, accessibility, backup or critical services for benchmark scores.
- [ ] Verify restoration on exit, crash recovery and next agent start; retain restore-pending on failure.

**Cleanup/disk analyzer**
- [ ] Read-only disk analyzer for large files, duplicate candidates, folder size, cache age and reclaimable space.
- [ ] Preview exact path, size, modified time, context, confidence, exclusion and projected reclaimed space.
- [ ] Bounded manifests for temp files and verified disposable app/shader caches.
- [ ] Windows Update leftovers only via supported servicing tools plus explicit approval; never manually delete WinSxS/package files.
- [ ] Recycle-bin emptying is a separate destructive operation with explicit confirmation.
- [ ] Exclude documents, Downloads, browser profiles, game saves, launcher folders, cloud sync and unknown app data by default.
- [ ] Duplicate/large-file deletion only after exact user selection.
- [ ] Enforce volume/age/count/byte caps and verify reclaimed capacity.

**Network**
- [ ] Read-only adapter, Wi-Fi, DNS, route, MTU, gateway, packet-loss, latency and jitter diagnostics.
- [ ] DNS benchmarking uses repeated probes and displays privacy/availability caveats.
- [ ] DNS switch only after approval and exact adapter/IP-family snapshot; conditional restore.
- [ ] Adapter reset, Wi-Fi power/band and MTU are separate previewed operations with capability checks.
- [ ] Winsock/IP reset is a high-impact manual repair with connectivity warning and recovery instructions.
- [ ] Never silently change VPN, proxy, enterprise, metered or managed networks.

**Drivers/updates**
- [ ] Stale-driver candidate scoring uses provider, version, date, hardware match, signature and build applicability; age alone is insufficient.
- [ ] Prefer Windows Update/exact OEM support source; no generic driver aggregators.
- [ ] Export previous INF and capture device state before approved update.
- [ ] Restore-point preflight where available, exact match and reboot/rollback plan.
- [ ] Rollback workflow and post-reboot device/problem-code verification.
- [ ] No automatic BIOS/firmware, Secure Boot or anti-cheat driver updates.

**Repair/services**
- [ ] Guided SFC/DISM scan and health checks with GUI progress.
- [ ] Repair only after diagnostic output and separate approval.
- [ ] Detect stuck services with state, timeout and dependency checks.
- [ ] Audio, Bluetooth and Windows Update recovery with prior-state snapshot and dependency-aware restart.
- [ ] Windows Update component repair is a guided workflow, not a blanket script.
- [ ] Verify service state and relevant events.

**Power/thermal/process**
- [ ] Recommendations for AC, battery, idle and gaming with current mode and trade-offs.
- [ ] Supported power-mode changes with snapshots/approval.
- [ ] OEM fan/performance profiles remain guided through signed tools; no undocumented firmware writes.
- [ ] Require PID + creation time + executable path before priority/affinity changes.
- [ ] High/realtime and critical/system/security/Vanguard targets remain blocked.
- [ ] Detect hung apps, offer graceful close/restart first; never force-terminate protected processes.
- [ ] Detect likely memory growth from time series; large working set alone is not a leak.
- [ ] Restore temporary tuning on session exit/recovery.

**Storage/game libraries**
- [ ] Inspect Storage Sense configuration/status and guide supported controls.
- [ ] TRIM/retrim preflight checks media, filesystem, volume support, resource state and result.
- [ ] Extend Steam/Epic manifest inventory and launcher-version-aware guided workflows.
- [ ] Package-manager-supported move only for eligible Windows packaged applications.
- [ ] Never use `shutil.move`, `os.rename` or manual manifest edits on launcher-owned game folders.
- [ ] Verify destination capacity/filesystem without starting a migration.

## P5.1 — Local workflow automation (implemented in 1.2.32)

- [x] Power Automate-style flow builder in Maintenance with persisted definitions and run history.
- [x] Event triggers for application crashes, hardware faults, driver/device failures, disk faults and Windows Update errors.
- [x] Schedule triggers at 6, 12, 24, 48 and 168 hours; sustained CPU/RAM/disk-latency/ping/GPU-temperature/packet-loss thresholds.
- [x] Fixed actions: local AI review, read-only diagnostics, read-only storage scan and Windows notification.
- [x] Typed schema validation, event cursor-at-create, 5–1440 minute cooldown, bounded 20-flow execution and run-history retention.
- [x] Enable/pause/delete controls and local-only authenticated APIs.
- [x] No shell/script/path input, arbitrary PowerShell, maintenance approval or direct mutation surface.
- [ ] Add optional user-approved Microsoft Power Automate cloud connector as a separate opt-in integration; local-only remains default.
- [ ] Extend triggers with device/app lifecycle and driver-offer matching, and add formal retry/idempotency state transitions.
- [ ] Add preview-creating workflow steps for supported maintenance actions; actual execution must still require the normal independent user approval.

## P6 — Goal loop and learning memory

- [ ] Goals: fast, cool, quiet, battery-friendly, stable network, free storage and pre-session readiness.
- [ ] Convert goals into measurable target signals, constraints, action families and observation window.
- [ ] Implement observe → diagnose → rank → preview → approval → execute → verify → keep/undo → report.
- [ ] Compare before/after under comparable workload; reject conclusions when workload changed materially.
- [ ] Keep/revert from deterministic verification and user-approved policy, never narrative confidence.
- [ ] Store action/version, target, before/after metrics, workload/session, evidence IDs, user decision and rollback result.
- [ ] Learn per-PC preferences/outcomes; invalidate or down-rank when OS/driver/hardware changes.
- [ ] Stop repeating rejected/failed recommendations for the same context; allow retry when conditions change.
- [ ] Require repeated evidence-backed outcomes before ranking promotion. Learning never creates capabilities.
- [ ] Reviewed plan steps are not executable commands.

## P7 — Scheduler and predictive maintenance

- [ ] Windows Task Scheduler integration with per-user identity, controls and auditable definitions.
- [ ] User-selected quiet hours and idle/AC preconditions.
- [ ] Pre-session checks on launcher/session detection or AC connection; start read-only.
- [ ] Weekly diagnostics/digest defaults to reporting.
- [ ] Forecast disk exhaustion and prepare cleanup recommendations.
- [ ] Forecast thermal crossings only with trusted sensor identity/units/sampling.
- [ ] Predict degradation only from corroborated trends and label prediction separately from fault.
- [ ] Scheduler prepares proposals; it does not approve maintenance mutations.

## P8 — Chat, voice, notifications and GUI operations

- [ ] Chat intents: “my PC feels slow”, “prepare for gaming”, “make it quieter”, “help free storage”.
- [ ] Diagnose first, show evidence, draft constrained plan, render preview, then request approval.
- [ ] Voice uses the same chat/policy pipeline and grants no extra authority.
- [ ] Visual plan timeline shows state, risk, privilege, impact, reversibility and evidence.
- [ ] Desktop notices for completed, blocked, degraded and approval-needed operations.
- [ ] Include direct Undo when conditional undo remains valid.
- [ ] Daily digest: observed, proposed, approved/executed, blocked, outcome and attention items.
- [ ] Action history shows before/after signals and why undo may no longer be safe.

## P9 — Validation and Windows rollout

- [ ] Keep tests lean and risk-focused: policy, preview replay, identity, rollback, no game-folder move, privacy and schema.
- [ ] Prioritise GUI acceptance and real Windows validation for animation, UAC, sensors, ETW and OEM capabilities.
- [ ] Validate idle, AC/battery, thermal load, gaming and low-memory scenarios on target Windows 11 laptop.
- [ ] Validate supported Windows/Python versions and elevated/non-elevated contexts.
- [ ] Failure injection: interrupted repair, service timeout, disk full, stale identity, UAC cancel and restart during rollback.
- [ ] Publish capability state: implemented, detected-only, guided, blocked, unsupported, target-device-verified.
- [ ] Hardware/driver features are not complete from mocks or syntax checks alone.

## Definition of done

A feature is complete when its GUI state is visible, evidence/provenance exists, policy is deterministic, errors degrade safely, resource overhead is bounded, mutations are preview/approval-gated, verification/undo are defined and docs are updated. Hardware-dependent features also require target-device validation.

## Immediate next actions

1. [x] Correct installer verification to expect the standard-user interactive observer; 1.2.26 CI and target-machine reinstallation still require validation.
2. [ ] Visually check graphite/forest/red across Command, Maintenance, Intelligence, Engine Deck and splash.
3. [ ] Instrument boot phases before changing complete hydration.
4. [x] Implement the least-privilege per-action UAC broker; validate it on the target Windows laptop next.
5. [x] Implement the first local Windows Knowledge slice: approved-source registry, build metadata, ingestion and lexical retrieval.
6. [ ] Expand read-only evidence before introducing new mutations.
7. [ ] Implement and validate the dedicated WPR/ETW trace-request broker without elevating the observer.\n8. [x] Add the first local Windows specialist endpoint and GUI card: telemetry + cited local RAG + strict action vocabulary; no execution.
