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
5. stops only the recording this capture path started;
6. archives the ETL and attempts tracerpt decoding;
7. uses Xperf only as an optional additional DPC/ISR decoder.

A missing Xperf installation does not require an ADK download to record with WPR. Existing WPR sessions are never stopped, cancelled, or replaced by SENTINEL.

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
