# AIE Architecture Spotlight

> Current project truth. Read before implementation and update with every milestone change.

**Last updated:** 2026-11-02 | **Current integration branch:** `dev` | **Platform:** Windows 10/11 only

## North star
Build persistent personal intelligence that observes explicitly permitted signals, models context, reasons about goals, learns reusable skills and executes scoped actions safely. AGI remains a research objective, not a capability claim.

## Architecture
```text
                  COGNITIVE CONTROL PLANE
          Goals · Context · Reasoning · Planning · Model Router
                             |
      +----------------------+-----------------------+
      |                      |                       |
   PERCEPTION               MEMORY                LEARNING
 Screen/UIA/Browser     Working/Episodic         Feedback/Skills
 ETW/Event Log          Semantic/Procedural      Evaluation
 Network/System        Provenance/TTL            Consolidation
      |                      |                       |
      +----------------------+-----------------------+
                             |
                       POLICY BROKER
             Identity · Capabilities · Risk · Budgets
                             |
                    CONTROLLED EXECUTION
                             |
                    OUTCOME VERIFICATION
                             |
                       AUDIT / REVIEW
 Local-first inference <--- explicit egress gate ---> Optional cloud inference
```

## Hard boundaries
1. Perception providers are read-only and emit observations, never actions.
2. Events carry source, timestamp, host, schema version, sensitivity and provenance.
3. Observed facts and inferred hypotheses remain distinct.
4. Models cannot grant themselves capabilities or alter policy.
5. All OS actions must pass through a policy broker and least-privilege executor.
6. Cloud egress is opt-in per request, minimized and auditable.
7. Users can pause observation and inspect/export/delete retained data.
8. Windows only. No Linux/WSL providers.
9. Browser observation is opt-in and limited to playback/performance signals; no passwords, cookies, form values or arbitrary page text.
10. UIA is off by default, process-allowlisted and structural-only; no control text/value/password extraction.
11. Window titles are not collected by default.
12. Destructive, privileged, externally visible or difficult-to-reverse actions require approval.

## Existing dev baseline and current feature-branch additions

**Windows perception**
- Read-only host/process/application/service/scheduled-task/network-interface inventory.
- Best-effort process lifecycle observations.
- Foreground app transitions and throttled active-process CPU, RSS, thread and I/O samples.
- Opt-in bounded systemwide process CPU/RSS/thread/I/O snapshots, reporting top consumers only.
- Opt-in kernel ETW process start/stop/rundown observer with bounded queue and explicit elevated-token requirement.
- Bounded network interface counters, TCP connection-establishment latency and DNS resolution timing.
- Opt-in metadata-only Application/System Event Log reader, wired into the observer runtime. It skips historical backlog on startup and excludes message text, XML and Security logs.
- Privacy-safe observer health telemetry with per-provider latency, success/error, consecutive-failure and event-loss accounting; health records exclude exception text and provider payloads.
- User-controlled privacy controls: `aie health` inspection, JSONL export with sensitive-data opt-in, and confirm-only delete-all after observation pause.
- Opt-in, allowlisted UI Automation structural snapshots with node/depth/time bounds.
- Per-user pause/resume and age-based event pruning.

**Browser and diagnostics**
- Opt-in MV3 Chrome/Edge HTML-video observer and strict Windows native-messaging host.
- Local event persistence and temporal browser/foreground/network correlation.
- Indexed time/source/type querying and privacy-safe activity sessions across all collected event categories (`aie activity`).
- Buffer starvation, buffered-but-not-advancing playback and evidence-backed resource/network hypotheses.
- Live deduplicated diagnostic suggestions with evidence references; suggestions are not actions.
- User outcome feedback linked to diagnostic event IDs.

**Cognitive core**
- Provider-independent model request/response contracts.
- Explicit per-request context packaging from user memories and safe activity timelines; no automatic context injection.
- Local Ollama client and hardware-aware selection of already-installed models; no implicit model pulls.
- Optional OpenAI-compatible HTTPS provider requiring explicit `--provider cloud --allow-cloud-egress`.
- Cloud/remote-Ollama requests pass through a centralized local egress gateway. Only explicitly selected context is attached; activity, memory and session context require separate confirmation, sensitive memory is blocked, high-confidence credential patterns are redacted, payload size is bounded, and a metadata-only local audit record is written. Observer telemetry is never automatically attached.
- Bounded declarative plans use typed steps, explicit success criteria and dependencies; model-backed drafting is optional, local-Ollama by default, exact-goal preserving, schema-validated and restricted to caller-allowlisted capability IDs.
- `aie agent run` provides a single-command local path from the user's goal through plan validation, durable run creation and bounded step advancement. It stops at approval/input/verification gates and does not execute proposals.
- A user-authored planner benchmark reports validity, goal preservation, required step-kind coverage and capability precision/recall, including an explicit forbidden-capability rate. It uses an already-selected local provider and does not update model weights or create task runs.
- Persisted task orchestration uses SQLite compare-and-swap versions and append-only lifecycle events. The engine advances dependency-ready steps through injected handlers, pauses for approval/input, and requires an explicit positive assertion for verify steps. Local model reasoning receives only the plan and bounded completed-step summaries; no tools are exposed to the model.

**Context and memory**
- A bounded synchronous unified event bus fans normalized observations to the durable SQLite store and optional JSONL sink before downstream diagnostics/correlation.
- Generic rule-driven temporal correlation can relate explicit event types within bounded time/host windows without asserting causality.
- Freshness-weighted evidence assessment and a narrow explicit contradiction detector are available as context-layer primitives; heuristic weights are not calibrated probabilities.
- Explicit user-controlled working sessions persisted locally; session metadata can be attached to model requests only on request.
- Separate local SQLite memory store for explicit user-authored working/episodic/semantic/procedural/prospective records.
- Source-event provenance validation, TTL, supersession history, deletion, lexical retrieval and optional local Ollama embedding/cosine retrieval.
- Embeddings are keyed by memory ID and model; deletion/expiry removes associated vectors.
- Sensitive memories are excluded from listing, retrieval and embedding by default; explicit indexing is available with a warning. Review-only consolidation proposals are generated from bounded lexical/tag similarity. A separate confirmed two-source merge creates a new record, retains both lineage links and every source-event/source-task-run reference, cannot lower sensitivity, raise confidence or extend expiry, and leaves source versions superseded.
- Completed task runs with a positive explicit verification step can produce deterministic procedural-skill candidates. Action-bearing candidates require successful audited execution receipts and a verification step dependent on each action. The user must preview and separately confirm a save; procedural-skill records are sensitive by default and do not train a model. Memory text and vectors are local SQLite data, not encrypted at the application layer; credentials must not be stored.

**Governance**
- Default-deny user-managed capability manifests, low-risk autonomy declarations, approval gates, bounded flat parameters and rate limits.
- Typed dry-run executor remains available for non-mutating policy checks.
- A registered adapter executor now requires an approved ledger proposal, valid audit-chain integrity, current policy re-evaluation, the positive execution-enable marker, an absent kill switch and a matching trusted adapter.
- The only built-in mutating adapter is `windows.settings.open`, which dispatches one of seven fixed `ms-settings:` URIs. It cannot alter settings, invoke a shell, launch arbitrary processes, write files or use the network. It is disabled unless a user creates and enables its manifest.
- Each attempted execution is recorded once in the SHA-256 chained policy ledger. URI dispatch is not treated as postcondition verification; a separate verify step requires an explicit user assertion.
- The task engine persists plan/run/step state and its event journal locally. Pause/cancel apply between handler invocations; in-flight external handlers are not force-killed and interrupted running steps fail closed for manual review.
- Capability manifests can be inspected and enabled/disabled with dedicated CLI commands. Enabling is limited to an application-registered adapter and preserves mandatory approval/no-autonomy fields; the executor enable marker and kill switch remain separate.
- A read-only retention inventory reports event-age deletion candidates, expired memories and bounded task/proposal status counts. It never deletes records. Pruning remains a separate explicit confirmation path.
- Approval and execution are separate operations. The execution gate remains disabled by default; no autonomous remediation is enabled.
- These orchestration/execution additions currently live on `feat/agent-orchestration-core`; they are not represented as merged into `dev` until the pull request is reviewed and integrated.

## Sentinel background runtime

The first persistent Sentinel prototype is integrated on `dev`. It reuses AIE read-only Windows collectors and the local SQLite event store rather than introducing a second observation stack.

- A detached per-user worker supports manual start/stop and an ONLOGON Task Scheduler entry using LIMITED, interactive-only permissions.
- A named mutex prevents duplicate worker instances. Pause/resume reuse the global AIE observer pause marker; graceful stop is a worker stop file.
- A local-only dashboard binds to 127.0.0.1. Its API requires a random per-user token and exposes provider health, system resources, event history and explicit pause/resume/stop controls.
- Periodic Windows inventory snapshots include bounded process identity, installed application metadata, service metadata, scheduled-task names/status and network-interface metadata.
- The registry sensor reads a curated allowlist of Windows configuration values, service/driver registrations and autorun value names. It compares fingerprints in memory; it does not persist autorun commands or full binary paths and never reads credential hives.
- The deeper CIM pass reads OS/CPU/firmware, UEFI Secure Boot, system and signed PnP driver, fixed/physical disk health, BitLocker volume status (never recovery keys), battery, Defender, Firewall and device-health metadata. Optional Windows modules/cmdlets degrade to unavailable fields rather than blocking other sensors.
- The Titan command deck adds animated live resource charts, deep hardware/security panels, filterable signed-PnP inventory, a rule-based posture alert watchtower, local Ask Sentinel, on-demand diagnostic/knowledge/AI commands and a validated live profile editor. Its API remains loopback-only, token-protected and read-only with respect to system configuration.
- The rebuilt dashboard is organized into Cockpit, System, Telemetry, Evidence Vault, AI Lab, Autonomy and Knowledge workspaces, with a boot splash, model discovery, six specialist Ask Sentinel modes, browser-notification opt-in and advanced collector configuration (Event Log metadata, ETW process lifecycle, window titles and executable-scoped UIA; restart required). Low-disk and low-battery thresholds feed the rule-based posture layer. Manual commands and automatic review triggers are persisted as local audit events. The System workspace exposes bounded process/application/service/task/interface catalogs; Deep Watch, Balanced and Low Impact presets only alter the form until the user explicitly saves.
- New high/critical rule findings can queue a deduplicated local AI review. Ask Sentinel uses an installed 3B/4B model for one-shot evidence-grounded Q&A; it shares the same inference lock as scheduled 4B/6B triage/review so requests do not compete for local model memory. AI outputs remain advisory and cannot invoke commands or remediation.
- The Microsoft knowledge crawler searches fixed Windows topics on Learn and fetches selected Markdown from MicrosoftDocs/win32, MicrosoftDocs/windows-driver-docs and microsoft/Windows-classic-samples. It caches content in local SQLite, validates HTTPS source hosts and exposes local dashboard search. The 4B/6B reasoning cycle can retrieve up to three local Microsoft excerpts as untrusted reference context. It does not upload machine data.
- Scheduled local Ollama inference uses an installed 4B triage model and a separate installed 6B reviewer when memory headroom permits. Ask Sentinel uses an installed 3B or 4B model when at least 3.5 GiB RAM is available. All model operations are serialized by one lock and models are released after each turn. No unrelated-size substitution or model download occurs. Model results are derived advisory evidence, not actions or policy.
- ETW process lifecycle capture remains opt-in. The standard background task is deliberately least-privilege; it does not install a custom driver or promise always-on elevated kernel tracing. Other kernel categories are not claimed as implemented until the pinned ETW provider's actual event coverage is validated.
- The browser/video observer remains separately opt-in and uses its existing extension/native-host pipeline.

Reference: [Sentinel Runtime](SENTINEL.md).

## Pending validation and implementation
- Windows CI run [#581](https://github.com/AryanGupta-234/P1-/actions/runs/38123875398) passed on Python 3.11 and 3.12, including the current observer-health, ETW lifecycle/loss, task-session, dry-run governance and privacy-control tests.
- Target-desktop Chrome/Edge extension/native-host installation and live playback validation.
- Target-desktop UIA and Application/System Event Log permission/behavior validation.
- Higher-fidelity ETW telemetry beyond process lifecycle events (optional thread/file/network categories and provider-specific coverage reporting).
- Windows Graphics Capture (screenshots), still intentionally separate from UIA structure.
- Unified event bus and semantic task/session interpretation.
- A user-authored retrieval benchmark reports Recall@k, Precision@k, Mean Reciprocal Rank and Hit Rate for lexical and local semantic retrieval without modifying memory or model weights. Sensitive target memories require explicit inclusion.
- A conservative polarity-conflict review queue flags explicit opposing lexical markers only when records share context; it does not prove semantic contradiction or modify records.
- Remaining evaluation: held-out task families, semantic retrieval quality, temporal contradiction resolution and forgetting/regression.
- Evaluation of procedural-skill quality and transfer; skill induction currently creates reviewed local records only and never retrains a model.
- Cloud egress gateway/redaction policy and model request budgets.
- OS-process sandboxing, rollback and automatic recovery for interrupted handlers.
- Postcondition verification beyond explicit human checks; the fixed Settings URI adapter reports dispatch, not verified application state.
- Tool-selection/plan-quality evaluation and held-out task-family benchmarks.
- Validate the Sentinel worker, loopback console, Task Scheduler behavior, ETW privilege boundary, Windows inventory refresh and Ollama model residency on the target Windows 11 desktop.

## Immediate engineering sequence
1. Validate browser/native-host, UIA, Event Log and ETW elevation/behavior on the target Windows desktop.
2. Extend ETW from process lifecycle into explicitly selected thread/file/network categories with provider-specific coverage reporting.
3. Add evidence freshness, contradiction handling and calibrated confidence to context/session interpretation.
4. Add persistent memory consolidation with retrieval/forgetting evaluation and reviewed skill induction.
5. Add process isolation and adapter-specific postcondition verifiers before expanding the narrow Windows Settings adapter.
6. Evaluate planner quality, task outcomes and memory integration without learning from unverified or model-generated success claims.
7. Add tray/desktop controls after the core APIs stabilize.

## Validation policy
Hosted CI proves code behavior on GitHub's Windows runners; it does not prove installation or runtime behavior on the user's desktop. Mark target-desktop validation complete only after running those checks on the actual Windows machine.

## Definition of done
Feature complete = implementation + tests + documented limits + privacy/security review + validation evidence. Never claim a capability is live on the user's PC based solely on hosted CI.

## Keep this page accurate
Update this file and `docs/ROADMAP.md` with every implementation increment. Add ADRs for lasting design changes and record exact validation evidence.


## Sentinel Prime operator console and task manager

The Sentinel loopback dashboard now has eight operator workspaces: Command, System Intelligence, Telemetry, Evidence Vault, AI Laboratory, Feature Control, Task Manager and Knowledge Base. The visual layer is a self-contained HTML/CSS/JavaScript interface served by the authenticated loopback worker; it does not require a remote UI service or external font/image host.

Feature Control separates:
- The scheduled-work master switch from per-job enable switches.
- Continuous sensor switches and sampling cadence (collector reinitialization requires a worker restart).
- Scheduled inventory, registry, deep inventory, Microsoft knowledge and local AI jobs.
- Event-triggered AI review rules.
- Explicit opt-in Event Log, ETW, window-title and allowlisted UI Automation collection.
- Local Ollama model selection and bounded knowledge crawler settings.

The Task Manager reports real managed worker jobs, trigger origin, start/finish timestamps, duration and a rolling 60-entry run history. The history is preserved between worker starts. Provider-health metrics are shown as expandable internal tool records. The Windows process panel is a bounded inventory snapshot exposing process name, PID and start time only; it is not a process termination console. In-flight Python threads are allowed to finish. Disabling a feature prevents future scheduled runs, while Pause Watch gates observer-driven scheduling and Stop Worker performs a graceful worker shutdown.

Ask Sentinel has a Maintenance & Settings Advisor mode. It receives the same bounded local evidence projection used by other Ask modes: internal/public events only, private fields recursively filtered, at most 20 records, and local Ollama inference. It may return proposed changes only for an allowlist of Sentinel profile booleans. Suggestions are evidence-ID filtered and staged into Feature Control for user review; they are not saved automatically. The advisor may explain manual Windows remediation but cannot emit shell scripts/registry edits or execute arbitrary operating-system actions. Privacy-sensitive collectors are not suggested for automatic enablement.

Validation boundary: source-level wiring has been inspected. Target Windows 11 desktop runtime, visual usability, Ollama response quality and end-to-end feature-toggle behavior remain pending; do not infer those outcomes from this implementation alone.

## Sentinel Prime interface redesign — 19 October 2026

The dashboard presentation layer has been consolidated into one coherent design system while restoring the original gunmetal/steel palette with its lime and orange accents. This replaces the prior stacked stylesheet overrides rather than adding another theme layer.

The operator experience now includes:
- A grouped workspace rail for Workspace, Intelligence and Operations.
- A consistent page header and responsive layout across all eight views.
- Larger typography, rounded layered surfaces, clearer spacing and stronger information hierarchy.
- Restrained motion for screen transitions, interactive cards and the animated system-core graphic; the interface honors `prefers-reduced-motion`.
- A searchable command palette opened with `Ctrl+K`. It can navigate to any workspace or dispatch the existing five allowlisted Sentinel jobs. Disabled jobs remain unavailable in the palette when Feature Control has disabled them.
- Keyboard workspace shortcuts `Ctrl+Shift+1` through `Ctrl+Shift+8`.
- Keyboard-accessible cockpit metric drill-downs to Telemetry, Evidence Vault, Feature Control and System Intelligence.

The palette dispatches through the existing dashboard command handlers and authenticated loopback API; it introduces no new operating-system execution capability or remote UI dependency. Feature switches, task scheduling and AI settings retain their existing approval and privacy boundaries.

Validation boundary: source-level navigation, DOM-ID, command-target and CSS-balance checks were inspected after the change. Browser/WebView rendering, animation smoothness, keyboard operation and full interaction checks still require validation on the target Windows 11 desktop.

## Sentinel agent auto-restart and dashboard reconnection — 19 October 2026

Sentinel has a default-enabled, user-configurable `auto_restart_enabled` setting. The worker hashes the installed `aie/**/*.py` source tree (and a project `pyproject.toml`, when present) on a 1-second interval. A detected change must produce three consecutive identical source snapshots before restart is scheduled; transient or partially replaced files are ignored. The watcher never downloads or installs updates: it reacts only after an update is already present on disk (for example, after a user-controlled repository pull or package update).

A saved Feature Control change or a direct local profile-file edit to a continuous or explicitly opt-in sensor setting also schedules an automatic restart when auto-restart is enabled. The same two-snapshot debounce is applied to the selected restart-sensitive profile fields. Scheduled job switches and other settings that are read live continue to take effect without restarting. When auto-restart is disabled, a sensor change is still saved and marked as restart-required; the operator can use the dashboard's manual **RESTART** action.

Restart handoff:
- The worker records the reason and sets a restart marker.
- The observer is asked to stop and the dashboard server shuts down cleanly.
- The worker writes restart state, releases the named single-instance mutex, removes its stop/restart markers and launches a detached replacement process.
- The new worker reads the persisted profile and reinitializes its collector graph. Existing task history continues to be preserved across worker starts.
- The dashboard polls worker status, detects a PID change and reloads itself from the replacement worker so updated embedded HTML/JavaScript is loaded.

The Feature Control page exposes the auto-restart switch and watcher status; the global header exposes a manual restart action. Manual Stop removes a pending restart marker so a stop request is not unintentionally converted into a restart.

Limits: this is process self-restart after local source/config updates, not an automatic `git pull`, package installation, dependency upgrade or OS reboot. A failed replacement launch is recorded as `restart_failed` in the local worker state and requires operator intervention. Target Windows 11 behaviour still needs desktop validation.

## PRIXON assistant and immutable foundation — 2 November 2026

PRIXON is implemented as an assistant identity and an AIE-integrated model lifecycle, not as a claim that a new foundation model has been trained. The upstream Qwen2.5-7B-Instruct checkpoint, architecture, tokenizer/vocabulary and original chat template are the immutable capability baseline. Every training experiment must pin the exact model commit SHA and save a separate adapter.

**Preserve from Qwen**
- General reasoning, multi-step problem solving, coding, mathematics, language understanding, planning and structured outputs.
- Existing Windows internals, networking, cybersecurity and troubleshooting knowledge.
- Architecture, original checkpoint weights, tokenizer/vocabulary and chat template.
- An untouched foundation artifact for evaluation, fallback and rollback.

**Replace/build for PRIXON**
- Assistant name, identity prompt, personality and response conventions.
- Provenance-aware dataset factory, train/validation/test splits, experiment manifests and adapter lifecycle.
- PRIXON-specific memory/context composition and integration with existing AIE memory and knowledge stores.
- Model routing, planning, tools and verification by reusing existing AIE model contracts, orchestration and policy engines.
- Context-sensitive language understanding: profanity, vulgarity, slang and offensive words may be discussed in legitimate linguistic, educational, analytical, quoted or fictional contexts without blanket word-based refusal.

**First training phase**
- Only identity, conversation_style and contextual_language examples are eligible.
- General reasoning, coding, maths and Windows/networking/cybersecurity/troubleshooting are holdout/regression domains.
- Dataset rows require source, licence, approval status and data classification. User-contributed records require explicit consent. Private/sensitive records and credentials are rejected before Kaggle upload.
- QLoRA produces a standalone LoRA adapter; it does not update the original foundation checkpoint.

**Independent execution policy**
Language freedom is not execution authority. Existing AIE capability manifests, approvals, audit ledger, execution gate, kill switch and rollback remain independent of the model. Discussion, quotation or analysis of a subject is not treated as permission to perform an action.

**First rebuild commit:** `f6e1c2b07bec7169d31f3b83526b14301dc93ead` on `dev`. The exact prior PRIXON prototype head is retained on `archive/dev-before-prixon-rebuild-20261102`. Kaggle execution, Windows CI tests and target-machine validation remain pending.


## SENTI standalone Windows assistant — planning branch

**Status:** Architecture and implementation plan documented; application implementation has not started.  
**Branch:** `feature/senti-standalone-assistant-plan` (created from `dev`).

SENTI is planned as a separate Windows desktop assistant with its own host lifecycle, conversational identity, user profile, unified memory adapter, capability registry and future desktop shell. It is **not** being added to the SENTINEL dashboard.

SENTI will reuse existing AIE model contracts/router, memory, planning/orchestration, policy and audit foundations wherever compatible. AIE Windows observation and SENTINEL diagnostics will be consumed through provider contracts; SENTI must not duplicate collectors or write directly into SENTINEL's private database. The current Ollama model tag `SENTI` is the initial local model target, not the entire assistant runtime.

Planning documents:
- [SENTI standalone implementation plan](SENTI_STANDALONE_IMPLEMENTATION_PLAN.md)
- [SENTI follow-up TODO backlog](SENTI_FOLLOW_UP_TODOS.md)
- [ADR-0015: standalone SENTI boundary](adr/0015-senti-standalone-assistant-boundary.md)

The first coding milestone is a headless SENTI host and runtime manifest. Desktop UI work is deliberately deferred until the host contracts stabilize. No SENTI implementation code or SENTINEL UI changes are included in this planning milestone.

## SENTI Phase 1 commitment — whole-Windows automation first

**Status:** Planned only; no SENTI implementation code is present in this planning branch.

SENTI is a separate Windows assistant, not a SENTINEL dashboard feature. Its first coding phase must include the Windows automation engine rather than postponing action execution to a later milestone.

Phase 1 includes:
- The standalone local SENTI host, existing Ollama model integration, truthful runtime/capability manifest and structured multi-turn tool dispatch.
- A typed Windows capability catalogue spanning applications/windows, files/folders, supported settings, process lifecycle, services/startup/scheduled tasks, networking, devices/peripherals, audio/display/power and selected maintenance/security workflows.
- Native Windows/API adapters first, fixed-parameter PowerShell/CIM recipes where needed, and opt-in bounded UI Automation for explicitly allowlisted applications.
- AIE policy/approval/execution/audit reuse, risk tiers, exact target revalidation, least privilege, before/after evidence, independent postcondition verification and rollback/compensation where feasible.
- Windows integration tests across each supported action family. A capability is advertised only when its concrete handler and health check are present.

“Whole-Windows automation” means broad, explicit coverage through registered and testable capabilities. It does not mean arbitrary shell strings, unrestricted Administrator access, hidden changes or blanket automation of every third-party application's UI. Unsupported or unavailable actions must be reported as such.

Phase 2 expands live Windows perception and telemetry coverage. It does not introduce the automation engine: Phase 1 already establishes that engine and its initial action coverage. Later phases add memory, advanced diagnostics, bounded background autonomy and the independent SENTI desktop UI.

Planning source: [SENTI standalone implementation plan](SENTI_STANDALONE_IMPLEMENTATION_PLAN.md) and [SENTI follow-up TODOs](SENTI_FOLLOW_UP_TODOS.md).

### Dynamic application discovery and launch resolution

SENTI Phase 1 includes a dynamic, rebuildable Installed Application Catalogue. It must resolve friendly app names without hardcoded executable paths by merging:
- HKCU/HKLM App Paths registrations in both registry views.
- Uninstall registry metadata as discovery hints, not direct executable truth.
- User/all-users Start Menu Shell Link targets.
- Packaged app package manifests, AppIDs/AUMIDs and `Get-StartApps`; the latter is not a complete installed-program inventory.
- Executable paths observed from live process inventory.
- An explicit full fixed-local-volume scan for `.exe` and supported shortcut metadata to find custom install locations.

The full scan examines application metadata only, not file contents. It skips reparse points and protected OS servicing/cache stores, discovers packaged apps through package metadata, reports ACL/volume gaps, and runs cancellably at low priority. Windows Search is an optional metadata accelerator only; SENTI does not turn on Enhanced indexing or index document/email content. Registry/package/root notifications and scheduled reconciliation maintain the cache without continuous full-volume scans.

The resolver ranks candidates using provenance, path existence, publisher/signature and user trust. It rejects temporary/download/cache executables by default, asks when stable/beta/portable copies are ambiguous, launches only validated canonical paths or AUMIDs, and verifies the resulting process/window. The catalogue is a replaceable app-metadata cache, not user memory.

Settings destinations live in versioned OS-aware catalogues: documented `ms-settings:` URIs, validated `.cpl` applets and `.msc` consoles. URI availability can vary by Windows build/SKU, so target support is checked before launch.

### First-class desktop interaction contract

The Phase 1 automation engine must handle both ordinary hands-on desktop actions and larger system workflows:

- Mouse/pointer: move, left/right/middle click, double-click, hover, drag/drop and vertical/horizontal scrolling.
- Keyboard: shortcuts/hotkeys, navigation keys and targeted text entry into verified non-sensitive controls; no keylogging or passive input capture.
- Windows desktop: open/launch apps, enumerate and switch windows, focus/restore/minimize/maximize/move/resize/snap/close windows, and operate supported Start/taskbar/notification/virtual-desktop surfaces.
- UI Automation: inspect allowlisted application controls and use semantic invoke, set-value, select, toggle, expand/collapse, wait-for and scroll patterns before coordinate input.
- Audio/media: master volume and mute, endpoint selection and supported per-app session/media controls.
- Clipboard: explicit task-scoped copy/cut/paste and clipboard set/get; no background clipboard harvesting.
- Files, settings, processes, services, tasks, networking, devices, display, power and bounded maintenance actions remain part of the same typed capability model.

Interaction order: native/app APIs first, UIA semantic patterns second, bounded SendInput fallback third, and opt-in screen-grounded coordinates only when fresh visual evidence is available. Input injection is serialized under a short desktop interaction lease; detected user input or focus changes stop the action. Locked/secure desktops, UAC secure desktop, logon screens and UIPI/elevation boundaries are not bypassed.

Official implementation references:
- [Microsoft UI Automation](https://learn.microsoft.com/en-us/windows/desktop/winauto/entry-uiauto-win32)
- [Windows SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
- [Core Audio EndpointVolume API](https://learn.microsoft.com/en-us/windows/win32/coreaudio/endpointvolume-api)

### Model-assisted app metadata enrichment

Windows discovery is deterministic and model enrichment is advisory. Registry, Start Menu, package/AUMID, process and file metadata produce the executable path and package identity. The installed local SENTI model may receive minimized extracted metadata to suggest normalized app/product names, aliases, vendor/product family, category and a short description. Strict schema validation, candidate IDs, confidence and provenance are required. The model cannot create or alter executable paths, AUMIDs, publisher/signature evidence, trust state, launch arguments or permission decisions. Batch/deduplicate enrichment at low priority; do not invoke the LLM per executable. Store model tag, prompt/schema version and review state with the app record.

### One canonical SENTI Unified Data Store

SENTI durable memory and knowledge use one physical SQLite database file, targeted at the existing per-user AIE data directory as senti.sqlite3. It contains logically separated tables for profile, conversation history, all five memory kinds, embeddings/lineage, application discovery and model enrichment, task/session context, normalized observations/state references and diagnostic knowledge. The application catalogue is a separate table domain in this same file; it is not injected into personal-memory retrieval by default.

The current separate AIE events.sqlite3, memory.sqlite3, task-runs.sqlite3 and task-sessions.sqlite3 sources are migrated with an idempotent, loss-checked migration, source backups and post-migration verification. One UnifiedDataStore factory/repository layer owns connections for every domain. Profile, memories, app records and task context are live-readable from the latest committed transaction.

Use stable typed columns plus versioned JSON payloads/extension fields and a schema registry for adaptable fields. Each record has a schema version; migrations are transactional and backward-compatible where possible. SQLite WAL, foreign keys, busy timeout, a serialized/batched writer queue, bounded transactions, optimistic versions and a monotonic change journal support real-time access without allowing the scanner to monopolize writes. Dynamic fields are validated, not arbitrary schema mutation.

Separate append-only policy and remote-egress audit databases remain isolated when their integrity model requires it; the emergency execution kill-switch remains independent of database health. SENTINEL's private database is never merged or written by SENTI.

