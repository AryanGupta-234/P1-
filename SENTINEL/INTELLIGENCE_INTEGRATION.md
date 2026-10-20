# SENTINEL + selected AIE intelligence capabilities

SENTINEL remains the host application and source of truth. This integration adds selected AIE capabilities inside SENTINEL; it does **not** replace SENTINEL's collectors, diagnostics, action engine, API contract, startup behavior, dashboard, or visual theme. All new persistence is additive in the existing `%ProgramData%\\Sentinel\\sentinel.db` database on Windows.

## Capability comparison

| Capability | SENTINEL before integration | Result |
|---|---|---|
| Hardware/process/service/network monitoring, inventory and diagnostic history | Already present | Preserved; reused as evidence sources |
| Allowlisted remediation, approval queue and per-action autopilot | Already present | Preserved; no second action executor or duplicate policy broker |
| Local AI council and optional explicit cloud provider | Already present | Preserved; local DEEP slot now has a live RAM guard |
| Provenance-linked environment observations and ranked state | Not present as a separate layer | Added, using a strict field allowlist and bounded evidence references |
| Explicit persistent memory, revision history and semantic retrieval | Not present | Added; semantic embeddings use loopback Ollama only |
| User-directed goals, dependencies and reviewed plan drafts | Not present | Added; accepted plans become steps, never commands or actions |
| Hardware-aware local-model routing | Existing model auto-selection was based mainly on installed model size | Added to the active AI council with a RAM fallback and recovery hysteresis |
| Read-only Windows UI Automation structure inspection | Not present | Added with strict resource limits and no text/value/password/screenshot collection |
| Structured ETW process-provider decoder and event correlation | Existing process spawn/exit watcher and WPR trace capture already present, but not an ETW event decoder | Not copied; requires a separate Windows ETW provider/schema implementation and live-trace validation |
| Full AIE learning/skill-experience and state recovery/compaction subsystems | Not present as equivalent SENTINEL components | Not copied wholesale; these require separate designs and evaluation rather than a blind code transplant |

The existing SENTINEL action layer already provides allowlisting, user approval, audit history and opt-in autopilot. A second generic AIE policy broker would duplicate that control path, so it was not added. No new action kinds or command-execution surfaces are introduced by this integration.

## Added features

### 1. Evidence-linked environment model

SENTINEL's existing process snapshot and inventory records feed a separate projection. New rows retain the observed entity, a change event, and up to 64 recent evidence IDs. The current evidence payload allowlist includes process PID, process creation time and image name; application name/version/publisher; service and task metadata; driver metadata; and network-interface name/link state/speed. IP addresses, MAC addresses, command lines, window titles, document text and credentials are excluded from this projection.

The state endpoint labels the result as observed-only. A missing entity is **not** interpreted as removal. A row means that the entity was last observed; stale rows remain until a reliable removal source is added. Repeated identical snapshots refresh `last_observed` without generating duplicate change events. Evidence references are capped at 64 per entity, and snapshot writes use a bounded batch transaction.

### 2. Persistent memory

Memory lives in `intel_memories`, `intel_memory_revisions` and `intel_memory_embeddings` within the existing database. Records include type, provenance references, confidence, sensitivity, verification, tags and optional expiry. Memory capture, revision and deletion are explicit. Revision snapshots preserve the previous record. Ordinary search excludes `sensitive`; the dashboard can include such records only after the operator enables the explicit sensitive-search toggle. Semantic indexing and semantic retrieval always exclude sensitive memories.

Semantic embeddings use an already-installed `nomic-embed-text:latest` model. The new intelligence adapter accepts loopback Ollama endpoints only, disables proxy use and redirects, and applies request/response bounds. It does not pull models or fall back to a cloud endpoint. Use the **INDEX NON-SENSITIVE** button before **SEMANTIC** search; if the local embedding model is absent or Ollama is offline, semantic operations report an unavailable/error state rather than switching providers.

### 3. Goals and reviewed plans

Goals and their steps are local, user-directed records. Step dependencies must resolve to existing steps, and a step cannot enter progress/completed state before its dependencies are completed. Goal/step transitions are recorded in history.

A plan suggestion is requested from an already-installed local chat model. The response is validated against a strict JSON schema, with at most 12 steps and dependencies restricted to earlier steps. Draft JSON is stored with a SHA-256 integrity digest. A pending draft must be explicitly accepted or rejected; acceptance is one-time and creates goal steps only. No plan is executed, no shell command is run, and no SENTINEL action is proposed or triggered.

### 4. Hardware-aware AI council

The active SENTINEL DEEP slot is re-evaluated before deep inference. When available RAM falls below 7.5 GiB, DEEP falls back to the FAST model. It returns to the requested DEEP model only after available RAM reaches 8.0 GiB, avoiding rapid switching around a single threshold. FAST remains the smallest installed local model unless explicitly configured. An explicitly enabled SENTINEL cloud provider remains governed by the existing cloud settings and is not silently enabled by this feature.

The Intelligence panel also displays the current hardware profile, installed-model availability and the AIE-style Qwen 3B/7B recommendation where those exact model tags are installed. Recommendations never download models.

### 5. Read-only UI Automation inspection

The Windows UIA adapter has hard limits for windows, nodes, depth, timeout and output size. It collects only structural metadata (control type, automation/class/framework identifiers, enabled/offscreen/password-control flags, process metadata for top-level windows and bounding rectangles). It never reads a control's name/text/value pattern, password content, clipboard, screenshot, or invokes a UI control.

**Interactive-session limitation:** the standard SENTINEL installer registers the main agent as a `SYSTEM` scheduled task. Windows isolates that task in Session 0, which cannot inspect the signed-in user's interactive desktop. In that installed configuration the inspector returns `interactive_user_session_required`. A real interactive-session companion is a separate deployment/security task; this integration does not silently downgrade SENTINEL's SYSTEM task or create a second privileged service. Running the agent directly in an interactive user session is required for a live UIA inspection.

## API additions

All endpoints below use SENTINEL's existing `X-Sentinel-Token` authentication and loopback HTTP listener.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/intelligence/context` | Build a bounded context packet from SENTINEL's current state and inventory |
| GET | `/api/intelligence/state` | Ranked, evidence-linked environment state |
| GET | `/api/intelligence/observations` | Recent observations; optional `ids=` fetches selected referenced evidence |
| GET | `/api/intelligence/runtime` | Hardware and model-routing recommendation |
| GET | `/api/intelligence/memories` | Ranked lexical memory search; `include_sensitive=1` is explicit opt-in |
| GET | `/api/intelligence/memory/history?id=...` | Revision history for one memory |
| GET | `/api/intelligence/memory/semantic?q=...` | Local embedding-based search; sensitive records remain excluded |
| GET | `/api/intelligence/goals?status=active` | User goals |
| GET | `/api/intelligence/goal/history?id=...` | Goal and step history |
| GET | `/api/intelligence/goal/plan-drafts?goal_id=...` | Pending or reviewed plan drafts |
| POST | `/api/intelligence/memory/add` | Explicit memory creation |
| POST | `/api/intelligence/memory/revise` | Update a memory while preserving its previous revision |
| POST | `/api/intelligence/memory/delete` | Explicit deletion |
| POST | `/api/intelligence/memory/index` | Index non-sensitive memories in local Ollama |
| POST | `/api/intelligence/goal/create` | Create a goal |
| POST | `/api/intelligence/goal/step/add` | Add a dependency-aware step |
| POST | `/api/intelligence/goal/step/status` | Update step bookkeeping status |
| POST | `/api/intelligence/goal/status` | Pause, resume or close a goal |
| POST | `/api/intelligence/goal/suggest-plan` | Create a local model plan draft for review |
| POST | `/api/intelligence/goal/plan-draft/resolve` | Accept/reject a draft; acceptance adds steps only |
| POST | `/api/intelligence/uia/inspect` | Run bounded read-only UIA inspection in an interactive session |

## Persistence and compatibility

The new tables are created with `CREATE TABLE IF NOT EXISTS` in SENTINEL's existing SQLite database. Existing telemetry, actions, configuration and inventory tables are not dropped, renamed or rewritten. Existing routes and the original UI sections remain present. The Intelligence workspace is an additive navigation view using SENTINEL's existing color system, panel styling and navigation.

## Validation performed

Run from the project root:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --check ui/app.js
python -m py_compile agent.py sentinel/*.py tests/*.py
```

The combined 33-test regression suite exercises memory privacy/revisions/deletion, sensitive-memory exclusion from embedding, goal dependency and completion gates/history, plan validation/integrity/one-time review, bounded evidence retention and missing-data semantics, authenticated evidence lookup, RAM-gated model routing, loopback-only Ollama access and the read-only/platform guard for UIA. These checks do not replace a live Windows validation pass: UIA, actual Ollama inference, Windows inventory providers, interactive scheduled-task installation, DPAPI key protection, display-window enumeration and ETW/WPR behavior must be validated on the target Windows machine. See [AUDIT_AND_LIMITATIONS.md](AUDIT_AND_LIMITATIONS.md) for a wider reliability and provenance review.