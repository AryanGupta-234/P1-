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
| resource_pressure | Slower detailed polling and inventory; DEEP inference is deferred |
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
