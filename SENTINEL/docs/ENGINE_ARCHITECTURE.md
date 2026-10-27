# SENTINEL Engine Architecture

**Platform:** Windows 11  
**Runtime:** Python agent + authenticated local dashboard  
**Policy:** Local-first, reversible actions, fail-closed protection for VALORANT/Riot Vanguard

This document defines the engine boundaries and the order in which policy decisions are made. The engines are independent modules, but share the existing core state, SQLite store, collector heartbeats, and authenticated local API.

## Runtime topology

~~~text
Windows telemetry sources
  ├─ psutil process inventory / PID + creation-time identity
  ├─ PDH counters, GPU metadata, network and service metadata
  └─ WPR status / bounded ETW trace
          │
          ▼
Collectors ───────────────► core.STATE / LIVE / HIST / SQLite
          │                              │
          │ process-start delta           │ sampled runtime state
          ▼                              ▼
Process Intelligence                 Adaptive Runtime
          │                              │
          ├─ explainable risk hints       ├─ process/GPU/network cadence
          ├─ signature/hash on demand    ├─ inventory backoff
          └─ user-reviewed controls      └─ AI admission/load shedding
                                         │
                 ┌───────────────────────┘
                 ▼
           AI Orchestrator ◄────► Unified Memory
                 │                  ├─ explicit non-sensitive recall
                 │                  ├─ bounded prompt budgets
                 │                  └─ short-lived LRU cache
                 ▼
          diagnosis / proposal
                 │
                 ▼
        Safeguard Policy Gate
          ├─ action proposal gate
          ├─ approval/risk-tier gate
          ├─ execution-time recheck
          └─ WPR trace preflight
                 │
                 ▼
        Reversible Action Journal
          ├─ before/after snapshots
          ├─ rate limits and undo metadata
          └─ conditional rollback
                 │
                 ▼
          authenticated local API
                 │
                 ▼
          Engine Deck / HUD
~~~

## Engine contracts

### 1. Safeguard — policy authority

**Module:** 'sentinel/safeguard.py'

The Safeguard is deterministic. It is not an AI classifier and does not accept model-generated overrides.

Responsibilities:
- Identify protected executable basenames (Windows critical processes, Riot client/Vanguard, and VALORANT).
- Establish whether the process observer is healthy and recent.
- Apply a strict VALORANT read-only mode.
- Reject a protected process target regardless of action origin.
- Reject state-changing actions when the process observer is disabled, stale, or unavailable.
- Recheck policy immediately before the action executes.
- Gate WPR/ETW capture on operating system, process state, and elevation.

**VALORANT invariant:** only bounded passive telemetry and dashboard display are permitted. Process tuning, timer changes, power-plan changes, updater-service control, DNS changes, WPR/ETW capture, and game profiles are blocked. VALORANT game profiles cannot be saved or applied.

SENTINEL does not install a kernel driver, open game memory, inject code, inspect Vanguard internals, stop Vanguard services, or modify anti-cheat configuration. This is a conservative design boundary, not a Riot compatibility or account-safety guarantee.

### 2. Adaptive Runtime — workload governor

**Module:** 'sentinel/runtime_engine.py'

The Runtime engine controls SENTINEL's own sampling cadence and optional compute work. It does not set Windows process priorities, affinity, power plans, or services.

| Runtime mode | Agent behavior |
|---|---|
| balanced | Normal telemetry cadence; AI admission subject to memory/CPU headroom |
| game_optimized | Slower detailed process scans; inventory, GPU and network polling back off; periodic AI triage is paused |
| valorant_guarded | Strict read-only policy; slower SENTINEL polling; model inference and deep trace capture are blocked |
| resource_pressure | Slower detailed polling and inventory; optional storage and AI work defer |
| telemetry_degraded | CPU telemetry is missing or invalid; optional work is not admitted until a valid sample returns |
| safety_degraded | The process observer is not trustworthy; mutation and model admission fail closed |

System-wide CPU/RAM telemetry remains available at its normal lightweight cadence. Expensive per-process sampling and optional diagnostics are reduced first.

### 3. AI Orchestrator — model admission and task routing

**Module:** 'sentinel/ai_engine.py'  
**Transport:** 'sentinel/ai.py'

The Orchestrator owns deterministic admission, FAST/DEEP routing, game-session suppression, and context composition. ai.py remains responsible for Ollama and explicitly configured cloud transport.

Rules:
- AI output is explanatory and proposal-only.
- Risk tiers and the Safeguard decide whether a proposed action is eligible.
- FAST and DEEP tasks have separate host-resource budgets.
- No model inference is admitted while VALORANT is detected.
- Local model inference is deferred during active games when the gaming pause setting is enabled.
- CPU or memory pressure can defer DEEP before it affects the foreground workload.

The model is never a security authority and cannot authorize itself to run a mutation.

### 4. Unified Memory — context and retrieval budget

**Module:** 'sentinel/memory_engine.py'

The Memory engine coordinates the existing SQLite intelligence memory store. It does not replace durable memories with a second database.

Responsibilities:
- Search only non-sensitive memory records for automatic context retrieval.
- Cache bounded retrieval results in a process-local LRU (64 entries, 90-second TTL).
- Apply prompt-size, process-row, and evidence-list budgets based on available RAM.
- Defer large investigation contexts under critical pressure.
- Offer a working-cache clear operation that leaves durable memory records untouched.

User-created durable memories retain their existing verification, confidence, tags, provenance and expiry metadata.

### 5. Process Intelligence — lifecycle observation

**Module:** 'sentinel/security_engine.py'

The process engine consumes process-start deltas from the collector. It scores explainable context, such as:
- executable launched from a user-writable or temporary location;
- executable path unavailable or inconsistent with the reported image name;
- a script/command host appearing as the parent process;
- missing or inaccessible executable metadata.

A score is a **review signal**, not a malware verdict. Signature status is not guessed. Authenticode verification, SHA-256 and Explorer location are performed only on an explicit user request, with process identity revalidated using PID, creation time and executable path.

There is no automatic termination, suspension, quarantine, deletion, memory inspection, or forced close. An eligible visible user application may receive a user-reviewed WM_CLOSE; there is no TerminateProcess fallback.

### 6. WPR / ETW capture

**Implementation:** 'sentinel/advanced.py'

WPR is the primary recorder when Windows provides wpr.exe. A capture is bounded to 5–15 seconds using GeneralProfile.Light. The capture path:
1. checks the Safeguard;
2. checks WPR status and refuses unknown ownership;
3. rechecks Safeguard immediately before starting;
4. starts only when no external WPR session is active;
5. stops the WPR session through the normal bounded owner path;
6. archives the ETL and attempts tracerpt decoding;
7. uses Xperf only as an optional additional DPC/ISR decoder.

If WPR stop/finalization fails, its current session ownership can no longer be proven. SENTINEL records the unknown state and deliberately does **not** issue a global stop or cancel during exception cleanup or shutdown. This may leave a trace session for the operator to inspect, but avoids disrupting another recorder. A missing Xperf installation does not require an ADK download to record with WPR. Existing or unknown WPR sessions are never stopped, cancelled, or replaced by SENTINEL.


## 7. Proactive Agent Assistant and Storage Intelligence (1.2.30)

**Modules:** `sentinel/agent_assist.py`, `sentinel/storage_intelligence.py`

These are agent-owned background workers. The HUD is a renderer and configuration client; it is not required to remain open for detection, diagnosis, storage measurement or notification delivery.

### Proactive diagnosis
- The assistant consumes new warning/error/critical events and high-severity insights from the local SQLite event stream using durable cursors.
- Structured event fields are bounded and filtered before they are used as diagnostic evidence. Secret-like keys are excluded; per-device, service, process and volume identity participates in deduplication.
- Deterministic Windows fault classes include device/driver, network, storage and disk latency, memory, CPU, DPC/ISR, thermal/GPU, application crashes/hangs, boot/startup, Windows Update, audio, Bluetooth/USB, power/sleep, WHEA and Defender/security events.
- Each finding retains evidence, a contextual question and a conservative first check. Unknown events remain explicit review items rather than being labeled as a confirmed cause.
- Native Windows notifications include both the next question and the first safe check. The agent delivers them while the HUD is closed; suppressed alerts remain in SQLite for later delivery.
- Optional local-specialist diagnosis is advisory-only, with a two-attempt/hour budget and a two-job pending cap. It is admitted only with valid runtime telemetry and idle CPU/RAM headroom. Failed local inference does not erase the deterministic finding.
- User answers, dismissals, AI results, notification state and worker cursors are stored in SQLite.

### Storage intelligence
- The scanner inventories all mounted-volume capacity and performs bounded metadata walks of curated user/cache/project roots. Secondary data drives contribute top-level data folders and shallow project artifact discovery; the Windows OS volume is not recursively swept.
- It reports file extensions and counts, largest files, hidden-file footprint, directory sizes, and package/environment footprints for Python, Node.js/Bun/Deno, Rust, .NET/NuGet, Java, Go, PHP/Composer and Ruby ecosystems.
- Common project workspaces include Downloads, Documents, Desktop, OneDrive Documents and developer directories. Common generated/dependency trees are scanned through dedicated roots so broad parent walks do not double-count them.
- Root selection rotates through SQLite-backed state. The worker checks the shared Runtime gate during a scan and yields when game, CPU, memory, safety or telemetry conditions change; the next pass resumes at the interrupted root.
- Last-access timestamps are weak usage hints on Windows and are never treated as proof of disuse. Large/old/hidden items and package footprints are review candidates only. The scanner does not open file contents, delete files, uninstall packages, or move game libraries.

### Runtime and persistence contract
- Storage and optional local AI work share `runtime_engine.admit_optional_work`. Unknown CPU telemetry is not represented as zero load.
- Game and VALORANT guard modes have priority over optional work. SENTINEL slows or defers its own workers instead of changing another process's priority/affinity, Windows power plan, services or security configuration.
- Assistant settings, storage settings, findings, feedback, cursors, scan snapshots and scan history are persisted in the existing local SQLite database. UI settings changes are written by the agent API and survive restarts.


## HUD presentation preferences and Simple Mode (1.2.31)

**Module:** `sentinel/ui_preferences.py`  
**API:** `GET/POST /api/ui/preferences`

The operator HUD starts in Simple Mode. It exposes the Command, Agent, System and Maintenance workspaces, while All Tools reveals the complete technical navigation. The command palette continues to route to any existing workspace, including when the side navigation is simplified.

The Command home provides a compact agent inbox, answer/dismiss controls, an optional local Windows specialist question, and a queued read-only storage scan action. It reads findings from the persistent agent queue and refreshes the small inbox only while the home view is visible. It does not detect Windows events, run AI, scan directories, send native notifications or execute maintenance.

Only the navigation presentation choice is stored in `ui_preferences` within the existing SQLite database. A settings change does not alter collection cadence, AI policy, alert policy, maintenance approval, Safeguard or any Windows configuration. The full toolset remains available; Simple Mode is a navigation and information-density preference, not a feature lockout.

## Windows Intelligence Fusion and Event Viewer (1.2.32)

**Modules:** `sentinel/windows_intelligence.py`, `sentinel/collectors.py`, `sentinel/agent_assist.py`  
**API:** `POST /api/agent-assist/system-review`  
**Persistence:** local SQLite event bookmarks, agent findings, AI jobs/results and feedback

The Windows specialist composes a bounded evidence packet from existing collectors and inventories rather than adding a parallel poller. Sources include performance metrics; resource-ranked process instances with session/GUI visibility; service state/start metadata; startup registrations; scheduled tasks; installed applications; signed PnP drivers and available Windows Update driver offers; seven-day Event Viewer/insight records; 30-day aggregate foreground application usage; maintenance findings; source-health metadata; and prior user answers. Every evidence record has a stable, locally validated evidence ID. The context limit is 18,000 characters and the specialist rejects evidence IDs that were not supplied.

Privacy projection is allowlist-based. The model does not receive process command lines, window titles, browser contents, credentials, file contents, user/account names, executable paths, or external connection addresses. App usage is aggregate app name/session/foreground-duration data; it does not include title or URL history. The model is local-only and subject to AI Orchestrator admission. Output remains a strict JSON schema with citations, bounded probes, known action IDs and an explicit no-execution field.

### Event Viewer collector

The Event Viewer collector parses XML from bounded `wevtutil qe` queries for System, Application crash IDs 1000/1001/1002/1026, Diagnostics-Performance, WindowsUpdateClient, Kernel-PnP and TaskScheduler. It keeps only an allowlist of crash/device/update metadata and discards the raw XML. A SQLite primary key over channel + EventRecordID deduplicates events across agent restarts; seen-record retention is 30 days. The initial baseline imports historical application crashes and high-value hardware/driver faults while marking the history as historical; it does not flood the finding inbox with every old generic warning. Later events are correlated by the existing agent assistant and may enter local AI triage. Missing channels and query errors remain explicit source-health errors.

### Scheduled and operator-triggered AI review

A durable cursor schedules one broad review every 12 hours by default, configurable between 6 and 168 hours. The worker waits until inventory, service catalogue and read-only maintenance/driver diagnostics have completed. It also requires the shared runtime gate (at least 5 GiB available RAM and below 40% host CPU), suppresses optional inference during protected game sessions, and never performs a Windows mutation. The Command home offers a manual review request; the same resource and game gates still apply. Review findings, diagnosis output, user answers and cadence are persisted in SQLite. User answers are context for future suggestion ranking only; they cannot change action permissions or Safeguard rules.

**Service and process interpretation:** stopped/manual/trigger-started state, low foreground use, or absence from a short sample is not proof of disuse. The specialist must state dependencies/coverage limits and ask the operator about required helper apps or services before suggesting closure, startup changes or service changes. Windows core, security, Defender, firewall, update, accessibility, backup, storage, network, hardware and Riot Vanguard/VALORANT components remain protected.

### Automation boundary

**Module:** `sentinel/workflow_engine.py`  
**API:** `GET/POST /api/automation/flows` plus enable/delete operations  
**Persistence:** `automation_flows` and `automation_runs` in local SQLite

The Maintenance workspace includes a local Power Automate-style flow builder. Supported triggers are new Windows application-crash, hardware, driver, disk or Windows Update events; fixed intervals (6/12/24/48/168 hours); and sustained CPU, memory, disk-latency, ping, GPU-temperature or packet-loss thresholds over 2–20 consecutive samples. Supported actions are a local Windows AI review, refresh of read-only diagnostics, a queued read-only storage scan, or a Windows notification. Event flows bookmark the current event ID at creation, preventing old event history from firing a newly configured flow. Cooldowns, enable state, trigger cursors and up to 100 recent runs per flow are persisted. The engine evaluates at most 20 flows and polls on a low-cost 30-second interval.

The workflow schema is closed and typed. It rejects unknown trigger fields, actions, command strings, scripts, arbitrary paths and model-authored code. A flow can request analysis/scans/alerts but cannot approve a repair, change services/startup, install/rollback drivers, terminate processes or bypass the maintenance kill switch. Any future mutating workflow step must create a normal preview and require operator approval through the existing action lifecycle. No Microsoft cloud Power Automate connection is configured; flows execute inside the local Windows agent.

## Action lifecycle

All state-changing actions follow this sequence:

~~~text
detect evidence → create proposal → Safeguard check → risk tier
    → explicit approval when required → fresh identity/evidence check
    → snapshot → execute → verify → journal result → conditional undo
~~~

- **Safe:** only explicitly allowlisted low-risk operations can be considered for autopilot.
- **Medium:** explicit operator approval is required.
- **Dangerous:** blocked unless a future implementation meets the reversible-action contract; no blind process termination or destructive file operation is allowed.

A proposal created before a game launches is rechecked at execution time. An approval does not override a newly activated protection lock.

## UI and API

The **Engine Deck** reads /api/engines and exposes status for Safeguard, Runtime, AI, Memory, Process Intelligence, and WPR. It provides:
- runtime policy re-evaluation;
- volatile memory-cache cleanup;
- user-requested process signature/hash/location inspection;
- a WPR proposal that is blocked automatically during VALORANT.

The local API remains authenticated and loopback-bound. The UI is an operator surface, not a policy boundary; enforcement remains in Python.

## Validation boundary

CI validates Python behavior across supported Python versions, Python compilation, JavaScript syntax, and the existing AIE suite. A green CI run does not test live Vanguard compatibility, WPR permission on every Windows build, hardware performance, or the absence of anti-cheat false positives. Those are separate target-machine validation items.


**Elevation (1.2.24):** the installed observer/dashboard runs with the interactive user's limited token. Maintenance action IDs in the broker manifest use a per-action UAC helper. WPR/ETW still has an Administrator requirement and is not yet connected to that helper; trace capture remains fail-closed under the standard-user task until a dedicated trace-ticket broker is implemented. Performance Log Users-only operation is not enabled by the Safeguard.


## Windows Specialist Intelligence — planned extension

The existing AI Orchestrator remains the model-admission and resource-governance authority. A separate Windows Specialist Intelligence package combines local, version-aware documentation retrieval; current telemetry and bounded ETW/Event Log/PnP/power/network evidence; a loopback-only local model adapter; and deterministic output validation. Knowledge records retain publisher, URL, licence, retrieval date, content hash, Windows-build applicability and component/API metadata. LoRA fine-tuning is considered only after held-out evaluation demonstrates measurable benefit over retrieval plus prompting.

The model may generate hypotheses, request read-only probes and recommend existing action IDs. It cannot execute commands, select arbitrary paths, create capabilities, change approval requirements, grant elevation or override Safeguard. Structured outputs are schema-checked and evidence/action references must resolve locally.

## Goal-driven maintenance loop — planned extension

The target loop is observe → diagnose → propose → policy → preview → explicit approval → execute → verify → journal → conditional undo → outcome memory. Maintenance mutations remain manual-only in the current implementation. Any future low-risk autonomy tier is a separate, disabled-by-default policy requiring independent review and a narrow reversible allowlist. Schedulers can prepare recommendations and previews; they do not approve maintenance mutations.

Outcome records are tied to exact action versions, target identity, Windows build, workload/session context and before/after evidence. Learned preferences affect recommendation ranking only and cannot alter risk tiers or action capabilities.

## Privilege model — planned least-privilege refactor

The current installer/agent has an elevated-session assumption for Windows operations. The target design separates ordinary observation/UI from privileged execution. A narrow broker accepts known action IDs and schema-bound parameters, issues one-time expiring approvals, verifies the signed-in user/session and rechecks Safeguard before execution. Arbitrary shell strings, model-generated scripts, persistent administrator tokens and generic run-as-admin endpoints are prohibited. UAC is requested when an approved operation requires elevation.

## Boot and design system

The splash remains a real data-hydration phase with bounded concurrency and truthful ready/degraded module states. Optimisation is based on instrumentation, shared boot snapshots, cache reuse, duplicate-work elimination and moving expensive optional diagnostics outside critical startup—not skipping workspace data. The graphite/forest/red liquid-glass palette is defined in `SENTINEL/ui/app.css`; accessibility and reduced-motion preferences remain first-class.


## Least-privilege privilege broker — implemented foundation (1.2.24)

The scheduled interactive agent now uses the limited Windows token. The shared ProgramData store grants the signed-in account Modify rights and preserves SYSTEM/Administrators Full Control.

For an administrator-required maintenance action, the operator creates a preview and gives explicit final confirmation. SENTINEL stores the exact action, arguments and original snapshot in a one-use ticket expiring with the preview (no more than 180 seconds), bound to the interactive principal and Windows session. The standard process launches only its own fixed `agent.py --privileged-job <32-hex-id>` entry point through the Windows `runas` consent UI. The helper checks principal/session, request state, fixed action manifest, kill switch, Safeguard and a fresh snapshot, then reuses the existing maintenance executor and journal. No arbitrary command or script is accepted and no administrator token is persisted. Declined UAC cancels the job.

The guard in the child uses the Safeguard's own live metadata-only process probe; it does not trust a parent-process cached "game absent" result. It remains fail-closed if the process probe is unavailable. Windows UAC and account/session behavior still require validation on the target machine.

## Windows Knowledge Engine — implemented initial slice (1.2.24)

`sentinel/windows_knowledge.py` owns a local SQLite source/document/chunk index. Source registration is restricted to an explicit Microsoft, Windows and OEM allowlist over HTTPS. Ingestion is user-triggered, allows at most one same-host redirect, accepts HTML/plain text only, bounds response time/bytes, removes script/style/navigation/form payloads and preserves SHA-256 document revisions.

Each source may carry a minimum/maximum Windows build, edition, architecture, component, licence metadata and API/command version. Retrieval is bounded local lexical search with build/edition/architecture/component filters when the local platform information is available. Every result carries the source URL, publisher, provenance metadata, content hash and local citation identifier. Retrieved text is treated as untrusted reference content and cannot create or execute maintenance actions.

This release slice does not yet provide vector retrieval, continuous crawling, ranking calibration, model fine-tuning or automated source refresh. Those remain separate backlog items.


## Trace elevation follow-up

WPR/ETW capture currently remains blocked when the observer runs as a standard user. Before re-enabling capture, add a dedicated trace request type to the same privilege-broker model: one-use ticket, explicit user preview/confirmation, current user/session binding, exact provider/profile allowlist, WPR ownership check, bounded duration/output, process/game-state revalidation, and safe stop/finalization. Do not route this through arbitrary command execution or elevate the observer.


## Installer/runtime privilege verification correction (1.2.26)

The scheduled observer is expected to report `is_elevated=false`, `desktop_access_expected=true`, a non-zero Windows session ID, the signed-in interactive username, the installed release version and expected `pythonw.exe` path. Installer completion validates this runtime identity; it must not require the observer itself to be an Administrator. Installation and removal remain elevated, while each privileged maintenance helper still receives a separate one-use UAC consent request bound to the user/session and approved action ID.

The normal shortcut opener accepts the validated standard-user process. It never elevates the long-running observer because its token is standard-user. If an explicit runtime mismatch is found, it attempts a graceful stop and restarts the registered Limited interactive task; if identity cannot be read, it fails closed without terminating an unknown process.


## Release-scoped observer runtime correction (1.2.27)

The installer process may be invoked by the machine's bootstrap Python, but that interpreter must never be registered as the observer. `_release_runtime()` is the single resolver for the immutable release and returns only `versions/<APP_VERSION>/.venv/Scripts/pythonw.exe`, that release's `agent.py`, and the release directory. A missing runtime or entrypoint is a hard failure; there is no fallback to `sys.executable` or another globally installed Python.

The scheduled task, Desktop/Start Menu shortcuts, installer identity check, normal opener validation, and detached fallback launcher all use this release-scoped path. The observer remains a Limited, standard-user process in the signed-in interactive session. This change does not modify previous version folders or ProgramData settings, SQLite history, and traces.



## Windows virtual-environment identity correction (1.2.28)

Windows venv launchers can expose the base Python executable image through the operating-system process API while the running interpreter remains bound to the release venv. Runtime identity therefore distinguishes three values: `sys.executable` (the interpreter runtime path), `sys.prefix` (the active environment), and the OS process image returned by psutil. The API reports all three. Installer and opener validation require both the release-scoped `sys.executable` and the exact release `.venv` prefix; the OS process image is diagnostic and is not used as a substitute for Python environment identity.

This preserves fail-closed validation: missing or mismatched interpreter/environment identity still blocks installation completion. It does not relax user, session, elevation, version, or desktop-session checks, and it does not change prior release directories or ProgramData state.


## Agent-owned proactive assistant (1.2.29)

**Module:** sentinel/agent_assist.py

The agent assistant consumes new warning/error events and high/warning insights from the existing SQLite event stream. It does not create a second telemetry collector or run from the dashboard. It creates durable findings containing the detected category, short explanation, one contextual question, a conservative first fix and bounded evidence metadata.

- Detection runs in an agent-owned worker; its cursor is persisted so restarts do not replay the entire event history.
- Repeated events are deduplicated and notification delivery is rate-limited.
- Native Windows tray notifications are emitted by the signed-in agent process. The dashboard only reads the persistent queue, saves preferences and records the operator's answer or dismissal.
- Alerts suppressed during game/resource pressure stay queued with a retry timestamp and are delivered once the Adaptive Runtime returns to a safe idle mode, subject to the hourly alert cap.
- The default category map covers device/driver failures, network/DNS, CPU, memory/pagefile, disk latency, thermal/GPU throttling, Windows services, process review signals, local AI runtime, storage pressure, application crashes and persistence errors. Unknown signals remain explicitly uncertain.
- A high-severity finding may enter the local-AI queue. The worker reuses sentinel/windows_intelligence.py, the installed local FAST model and local documentation retrieval. It runs one diagnosis at a time only when runtime mode is balanced, no game is active, available memory is at least 5 GiB and CPU use is below 40%. If those conditions do not hold, work waits. If local inference is unavailable, the deterministic finding remains usable.
- Model output is advisory and stored separately from the deterministic event. Commands and execution are not part of the accepted specialist schema; any action ID remains tied to the fixed preview-gated maintenance vocabulary.

Persistent settings and records are stored in the existing sentinel.db: agent_assist_settings, agent_notifications, agent_assist_cursors, agent_assist_feedback, agent_assist_ai_jobs and agent_assist_ai_results. Answered/dismissed notifications are retained for 90 days; feedback is retained for one year. Open notifications remain available until answered or dismissed.

## Storage Intelligence (1.2.29)

**Module:** sentinel/storage_intelligence.py

Storage Intelligence is a separate read-only agent service. It measures whole-volume capacity and bounded metadata footprints in common user folders, Python package caches/environments, Node/npm/pnpm/Yarn caches and node_modules, Cargo, NuGet, Gradle/Maven, known build outputs and top-level folders on secondary data volumes.

The report includes:
- Volume capacity, free/used bytes and a low-capacity state.
- File-extension mix and hidden-file count/bytes.
- Directory-level size, file/directory counts, recent-write age and weak last-access signals.
- Package-level size buckets under Python site-packages, virtual environments and Node node_modules (including @scope/package).
- Ranked review candidates for large caches/build outputs, large Downloads content, hidden-heavy folders, large secondary-drive folders, and oversized dependency components with weak old-access signals. Package candidates require manifest/lockfile review; a timestamp is never treated as proof that a dependency is unused.

**Resource policy:** one bounded storage worker; default budget 15,000 metadata entries and 18 seconds per scan, with a 1.5-second per-root cap. Scans are deferred unless the runtime governor reports balanced, at least 4 GiB available memory and CPU below 45%. The default repeat interval is 72 hours. Manual scan requests are queued by the agent and still wait for a safe resource window. This work is deliberately serialized: storage metadata enumeration is I/O-bound, and parallel crawling would compete with foreground applications.

**Coverage limit:** this is not yet a full recursive crawl of every directory on the Windows system volume. On the OS volume it uses curated personal/developer/cache roots to avoid sweeping Windows and Program Files; secondary data volumes contribute bounded top-level folder scans. A partial flag and entry/root counters are returned rather than implying complete coverage.

**Usage limit:** Windows last-access timestamps may be disabled, coarse or updated by background services. Age is a weak review signal, not proof of disuse. Hidden status is also not evidence that a file is junk. The module never opens file contents, follows directory symlinks, deletes files or uninstalls packages. It has no cleanup API. Recommendations instruct the operator to review the candidate and use the owning package manager/build tool where appropriate.

Settings are persisted in storage_intelligence_settings; the latest scan and metadata-only report are held in storage_scan_history and the bounded storage_intelligence runtime snapshot. The history keeps the latest 12 reports.

## HUD boundary for the new services

The Maintenance view is a client for the authenticated local API. It can display stored findings/reports, change SQLite-backed feature settings, queue a scan, and submit a response to an agent-generated question. It does not scan directories, classify events, perform AI inference, generate desktop notifications or execute cleanup. Opening the HUD causes read requests only.
