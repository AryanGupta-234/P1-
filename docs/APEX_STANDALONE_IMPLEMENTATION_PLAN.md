# APEX — Standalone Windows Assistant Implementation Plan

> **Implementation boundary correction (ADR-0017):** This is the original planning draft. For implementation on `feature/apex-phase-1-runtime`, ADR-0017 and `docs/APEX_PHASE_1_IMPLEMENTATION.md` are authoritative wherever older text below proposes reuse of AIE model, memory, observer, orchestration, policy or database internals. APEX owns its `apex/` Python package, Ollama HTTP client, runtime, tool registry, approval interface, Windows providers and `%LOCALAPPDATA%\\APEX\\apex-unified.sqlite3`. Do not import `aie/` or `SENTINEL/`, migrate AIE databases, modify SENTINEL, invoke Ollama CLI, or use CMD/PowerShell subprocesses for model inference. Normal Python inference always sends `think: false`. Desktop UI remains deferred to Phase 6.


**Status:** Initial Phase 1 runtime and Windows adapters implemented; target Windows validation and remaining Phase 1 coverage are pending  
**Implementation branch:** `feature/apex-phase-1-runtime` (planning baseline: `feature/apex-standalone-assistant-plan`)  
**Base:** `dev`  
**Target platform:** Windows 11 x64 (Windows 10 compatibility is not in the initial acceptance target)  
**Initial local model:** Existing Ollama model tag `APEX`, built from the user's Qwen3.5 4B Modelfile  
**Application boundary:** A separate Windows desktop assistant; not a workspace, panel, route or embedded chat inside the SENTINEL dashboard

## 1. Product definition

APEX is the user's primary, conversational Windows assistant: a local-first, Friday/Jarvis-style interface for questions, personal context, whole-PC diagnostics, planning and controlled automation.

SENTINEL is a separate product. APEX does not depend on it, embed its UI, import its code or access its private data. Any future connection requires a separately approved, documented provider contract.

The APEX desktop experience will be designed and implemented later. This document defines the runtime, integration boundaries, data contracts, memory, capabilities, policy and delivery sequence first. No UI redesign or SENTINEL dashboard modification is in scope for this planning milestone.

### Product responsibilities

- Talk naturally and adapt to the user's preferred conversational style.
- Address the user as **"sir"** by default, because this is an explicit preference; do not insert it into every sentence unnaturally.
- Maintain a user-approved profile and a unified, reviewable memory.
- Know its own version, selected model, connected providers, registered tools, permission levels and provider health.
- Gather live Windows information through real, observable providers.
- Diagnose system, application, hardware, process, service, storage, network, startup, event and performance issues.
- Plan and perform approved automation through typed capabilities.
- Verify operations using fresh evidence and keep an auditable history.
- Remain useful when Ollama or an optional APEX provider is unavailable; clearly report degraded capabilities.

### Non-goals for the first release

- Training a new foundation model from scratch.
- Replacing or rewriting the existing SENTINEL dashboard.
- Adding APEX chat to the SENTINEL UI.
- Kernel drivers, kernel memory access, process injection or anti-cheat interference.
- Unrestricted shell execution, unrestricted administrator access or hidden system changes.
- Keylogging, covert screenshots, microphone recording, credential harvesting, browser-cookie/form capture or arbitrary personal-file indexing.
- Automatic cloud inference or silent model downloads.

## 2. Repository baseline and ownership

The implementation branch is based on the APEX planning branch. APEX is a separate assistant product with its own runtime and release boundary. Its code may coexist in this Git repository during development, but it must not depend on AIE or SENTINEL internals.

### APEX-owned implementation

APEX owns and maintains the following components under the `apex/` package:

- Python host lifecycle, configuration, identity, prompt composition and model contracts.
- Direct loopback Ollama HTTP transport, inference scheduling and structured tool-call handling.
- Typed capability registry, policy decisions, approval interface, executor and audit records.
- Windows inventory, desktop interaction, UI Automation, application catalogue, file, audio, network and system adapters.
- The canonical APEX SQLite store, profile, memories, conversations, application metadata, task context and change journal.
- Future APEX IPC, desktop UI, installer and lifecycle management.

### Independence requirements

- No imports from `aie/` or `SENTINEL/` in the APEX package.
- No calls to AIE or SENTINEL command-line entry points or private APIs.
- No reads, writes or migrations of AIE or SENTINEL databases.
- No dependency on the SENTINEL dashboard or its lifecycle.
- Tests enforce the import boundary and absence of arbitrary shell/subprocess model execution.
- Any future cross-product integration must be optional, read-only by default, versioned, explicitly approved and backed by a documented external provider contract. It is not a Phase 1 dependency.

## 3. Product and process boundaries

APEX is a standalone application with its own lifecycle.

Proposed process topology:

```text
APEX Desktop Client (future standalone UI)
        |
        | authenticated local IPC
        v
APEX Host / Assistant Runtime
  |       |          |            |
  |       |          |            +--> Profile and unified memory
  |       |          +---------------> Capability registry / tool dispatcher
  |       +--------------------------> APEX orchestration and conversation
  |
  +--> Ollama loopback API (Qwen/Apex model)
```

The APEX host must run without a console window during normal use. The user should launch APEX from a Start Menu shortcut, desktop shortcut, notification-area entry or configured sign-in startup. A command-line developer mode may exist for diagnostics, but it is not the normal product experience.

### Runtime startup

1. Start or connect to the installed Ollama local service using a documented Windows launch/service integration.
2. Verify the loopback API is reachable; never assume it is running.
3. Discover installed models through Ollama's model-list API; never pull a model silently.
4. Verify that the configured APEX model tag exists and can answer a small health request.
5. Initialize APEX-owned Windows providers independently; each provider reports its own health and permission status.
6. Initialize profile, memory and capability metadata.
7. Start the APEX host and expose a local authenticated IPC endpoint.
8. Open the desktop experience when requested; keep the background host available when the UI is closed if the user enabled it.

If a dependency is unavailable, APEX must show a precise degraded status and preserve the ability to chat or use remaining providers where possible.

### Local IPC and trust boundary

- Desktop-to-host communication must be local-only.
- Prefer Windows named pipes with an ACL scoped to the current user; a loopback HTTP API with a high-entropy per-user token is an acceptable alternative if named-pipe integration proves disproportionate.
- Reject remote bind addresses, untrusted origins and unauthenticated requests.
- Ollama calls must use a loopback endpoint by default.
- The host must authenticate IPC clients and expose only documented APEX operations, never a general-purpose remote shell.

## 4. Identity, personality and user profile

### Identity separation

- **APEX** is the user-facing assistant and product identity.
- **SENTINEL** is a separate product and is not an APEX runtime dependency.
- **Qwen3.5 4B** is the current foundation model used by the user's Ollama tag `APEX`.
- The assistant must never invent its creator, model provenance, installed tools or permissions. These facts come from build metadata, model metadata and the operator profile.

### Profile setup

APEX must gather profile information through an explicit first-run setup and later profile-edit controls. It must not scrape arbitrary files, browser data, credentials or account stores to infer a user identity.

Initial profile fields:

| Field | Initial behavior |
|---|---|
| Preferred salutation | Default to `sir` per user instruction; editable |
| Display/owner name | Ask or accept explicit user entry; never infer from account folders |
| Interaction style | Conversational by default; technical depth adapts to task |
| Language and locale | User-selected or Windows locale suggestion, confirmed by user |
| Time zone | Read OS setting and allow correction |
| Technical preferences | Local-first, Windows-only, concise routine answers, detailed diagnostics when useful |
| Consent choices | Telemetry scope, memory capture, optional UIA, optional voice and optional cloud egress |
| Device profile | Read permitted OS/hardware facts and label their source/freshness |

Store profile fields separately from diagnostic memories. Give the user inspect, edit, export and delete controls.

### Conversation behavior

- Be natural, context-aware and able to understand informal language.
- Use `sir` naturally, not as a forced prefix on every reply.
- Distinguish casual chat, explanation, diagnosis, planning and action.
- Answer simple questions without launching a diagnostic workflow.
- For machine-specific questions, state whether evidence is live, cached, stale or unavailable.
- Never claim to see the machine, know the user's identity or have executed a tool unless the host provides evidence.
- For “who made you?” or “what are you connected to?”, answer from the profile/build manifest/capability registry, not model guesswork.

## 5. APEX self-awareness and capability inventory

APEX must have an authoritative runtime manifest that it can inspect. The prompt alone is not a source of truth.

Add a read-only self-inspection capability, conceptually `apex_get_runtime_manifest`, returning:

- APEX product version and build ID.
- Assistant identity and active prompt/profile version.
- Foundation model tag, model family and quantization metadata when available.
- Ollama endpoint status and model availability.
- Current inference mode (normal), fixed thinking-off state and resource-admission state.
- Connected providers: APEX-owned Win32, WMI, COM, Core Audio, UI Automation and other registered Windows providers, each with its own health check.
- Registered tools with identifier, description, schema version, source provider, availability, permission tier and last health check.
- Capabilities currently enabled, disabled, approval-gated or unavailable.
- Memory store status, active profile and retention state.
- Data collection and cloud-egress settings.
- Evidence freshness/coverage and known limitations.

A tool is considered connected only after a real health check. A registered-but-unavailable tool must be shown as unavailable. APEX must not say it has kernel access, full OS access or a capability that is not present in the manifest.

## 6. Whole-Windows perception and telemetry

APEX collects normalized evidence through its own Windows providers. AIE and SENTINEL are not sources or dependencies in this phase.

Initial read-only domains:

| Domain | Evidence |
|---|---|
| Host and OS | Windows edition/build, boot time, hardware inventory, firmware facts where supported |
| CPU and memory | CPU utilization, memory pressure, commit/pagefile, per-process resource samples |
| GPU and sensors | Supported GPU metadata, temperature/power where provider exists, provider health |
| Processes | PID plus creation time, image metadata, parent relation, CPU/RSS/I/O; no arbitrary command-line collection by default |
| Services and drivers | State, startup mode, dependencies, signed PnP metadata, device problem codes |
| Applications/startup | Installed application metadata, startup entries and scheduled-task metadata |
| Storage | Volumes, free space, disk health where supported, I/O latency and activity |
| Networking | Adapters, interface state/counters, DNS, routes, TCP metadata and bounded diagnostics |
| Events | Explicitly allowlisted Windows System/Application event metadata; event messages and sensitive channels require a separate review |
| Performance | Bounded ETW/WPR sessions with provider/permission checks, loss reporting and no interference with external tracing sessions |
| User activity | Only explicitly enabled, minimized signals; window titles/UIA are opt-in and bounded |

Every observation must carry source/provider, observed timestamp, host identity, schema version, sensitivity classification, freshness and provenance. Missing data means unknown/unavailable, not zero or healthy.

### Adaptive collection

- Use deterministic collectors for routine observation.
- Use event-driven or low-frequency sampling where available.
- Increase collection detail only during a user-requested investigation or a detected, explainable anomaly.
- Decrease APEX-owned work during gaming, foreground load, low battery or memory pressure.
- Do not invoke the LLM for each sensor sample.
- Keep an explicit pause switch and per-provider enable/disable controls.

## 7. Model runtime and prompt architecture

### Initial model and Modelfile policy

Use the user's existing local Ollama model tag `APEX`, based on Qwen3.5 4B, as the first integration target. Preserve the current base model, template and working Modelfile as the initial baseline. Do not replace the foundation model, alter model weights, add an adapter or perform a large prompt rewrite as a prerequisite for building the host.

The Modelfile has a deliberately narrow role: static assistant identity, voice and non-negotiable truthfulness/interaction principles. It is not the place for live Windows data, current user identity, application lists, available tool schemas, permissions, memory contents or current provider status.

After reviewing the exact current Modelfile, make only a targeted `SYSTEM` instruction correction if needed:
- Identify the assistant as APEX, a user-configured local Windows assistant; explicitly prohibit claiming that Microsoft created or owns APEX.
- State the known foundation model/host provenance only from configured metadata; otherwise answer unknown.
- Do not claim Windows, registry, process, file, kernel or network access unless a live host capability/provider is supplied for this request.
- In bare `ollama run` mode, explain that no APEX Windows host/tools are connected and therefore no live machine inspection/action can be performed.
- Never claim to be running in a sandbox, on the user's physical PC, or in any other execution environment unless the host runtime manifest explicitly reports it.
- Use the configured user profile and preferred salutation; default to `sir` only when no different user preference is stored.
- Speak naturally and conversationally; adapt concise or detailed responses to the task without forced catchphrases.

Do not attempt to solve tool access by adding tool definitions or executable paths to the Modelfile. The Modelfile's SYSTEM instruction can guide model behavior, but it is not an authorization boundary and cannot grant operating-system access. Keep the original `FROM` and model-specific `TEMPLATE` intact unless a separate compatibility test proves the template itself is malformed. Ollama's documented Modelfile instructions separate `SYSTEM`, `TEMPLATE` and generation `PARAMETER` settings; runtime tool definitions are sent through the chat API, not embedded as executable capabilities in the Modelfile.

### Runtime and model transport requirements

- APEX must call Ollama's local HTTP API, not depend on `ollama run` or a visible terminal session. The CLI remains useful for developer diagnostics only.
- Use the APEX-owned model request/response contracts and direct Ollama HTTP adapter. Do not import or extend the AIE model stack.
- Discover installed model tags; do not auto-download or silently switch to a remote model.
- Extend the model request contract with explicit `think` control, optional typed tool definitions and bounded tool-call settings. All Phase 1 inference sends `think: false` from Python in the Ollama HTTP request. No thinking override is exposed in the current runtime.
- Extend message/response contracts to preserve assistant tool calls and tool results: allow the provider's tool message role and tool name, parse `message.tool_calls`, and retain the assistant tool-call turn followed by corresponding tool-result messages. APEX's own `ChatMessage` and Ollama client must preserve tool-call turns and tool-result messages; normal `/api/chat` calls explicitly include `think: false`.
- Use Ollama `/api/chat` tool schemas for model-requested function calls. A model tool call is only a proposal: the APEX host validates tool name/schema/arguments, checks the live capability manifest and APEX policy, executes through the registered adapter and sends a sanitized result back to the model. The model never executes a tool itself.
- Support bounded non-streaming multi-turn tool-call loops and structured tool errors. Reject malformed, unknown, repeated or over-budget calls. The initial runtime sends `stream: false`; streaming and interactive cancellation remain follow-up work.
- Use one local inference slot initially to avoid RAM/CPU contention.
- Keep the model warm only within configured memory budgets; unload or defer optional work under pressure.
- Apply bounded timeouts, response sizes, context budgets and cancellation.
- Record prompt tokens, output tokens, time-to-first-token, tokens/second, total duration, model load time and failures.

### Runtime identity and context precedence

Build each request from versioned and separately labelled sources. The host-supplied runtime context is authoritative for dynamic facts:
1. Static APEX identity and non-negotiable truthfulness principles.
2. Build metadata: APEX host/product version, configured creator/operator attribution and foundation-model tag/provider.
3. Live runtime manifest: current Ollama/provider health, connected providers, registered tools, permission state and capability availability.
4. Explicit user profile: preferred name/salutation, locale, communication preferences and approved device aliases.
5. Relevant specialist profile for the current task.
6. Current user request and bounded conversation history.
7. Fresh Windows evidence and selected memories with source, timestamp and provenance.
8. Only the tool schemas relevant to this request.
9. A concise execution-policy reminder and currently permitted autonomy tier.

If these sources conflict, fresh host metadata/provider evidence wins over model prior knowledge. User profile values are never inferred from Windows folder names. Unknown fields remain explicitly unknown. Provider facts must include freshness/health; a stale cached manifest cannot prove a tool is currently connected.

Do not put the whole Windows inventory, full memory database or every tool schema into every prompt. Retrieved observations, user files and memory are untrusted reference data, not higher-priority instructions.

### Deterministic answers for identity and capability questions

For high-risk factual questions such as "who made you?", "what model are you?", "what are you connected to?", "can you see my processes?" and "what can you do?", the host must supply a structured, read-only self-inspection result. The application may answer stable identity/provider fields deterministically before using the model for natural phrasing. It must never rely on the foundation model's parametric memory to invent current provider connectivity, current Windows visibility or owner identity.

The user-facing assistant must distinguish APEX product identity, its explicitly configured operator attribution, foundation model metadata, Ollama as model-serving runtime, and every APEX-registered tool/provider with live health. It must not claim AIE or SENTINEL is part of its runtime.

## 8. Unified profile, memory and canonical data store

APEX must have one canonical local database file for its durable assistant memory and knowledge, not separate databases for profile, chat history, memory types, application discovery and task context. This is a single physical SQLite database with logically separated, typed tables and repository interfaces.

**Canonical database target:** %LOCALAPPDATA%\\APEX\\apex-unified.sqlite3 (resolved through APEX-owned `apex_data_dir()`, not an AIE helper). A portable/configurable data-root override may be supported for development and backup/restore.

This is an APEX-owned data store. Do not consolidate, migrate, open or write AIE database files. APEX initializes and migrates only its own versioned schema with integrity checks, transaction journals and backups.

**The canonical database owns these persistent domains:**

- **User profile:** preferred salutation/name, locale, interaction preferences, device aliases, approved technical preferences and explicit consent settings.
- **Conversations:** session metadata, messages, summaries, references and user-controlled retention.
- **All memory kinds:** working, episodic, semantic, procedural and prospective records, including confidence, sensitivity, verification, TTL, corrections, supersession and lineage.
- **Embeddings and retrieval metadata:** local vectors keyed by record/model/version, lexical search indexes and retrieval evaluation metadata.
- **Application knowledge:** discovered app records, EXE/AUMID identities, aliases, versions, publisher/signature evidence, source provenance, model enrichment results, user corrections, scan state and launch history.
- **Windows observations and state references:** normalized event records, inventory snapshots, process-instance state, source IDs, and evidence references needed for memory/diagnostics, subject to explicit retention and sensitivity policy.
- **Task and workflow context:** user-directed task sessions, plans, runs, step state, outcome summaries and references to execution receipts.
- **Diagnostic knowledge:** reviewed incidents, hypotheses, verified fixes, follow-up notes and linked evidence references. Raw telemetry is not automatically promoted to personal memory.

The policy/security audit ledger and remote-egress audit remain separately protected append-only stores if required by their integrity boundary. They are not alternate memory stores. Secrets, credentials, browser tokens, raw passwords and private keys are never placed in the unified database. Implement an APEX-owned independent emergency kill switch that remains effective if SQLite is unavailable; do not reuse AIE control files. SENTINEL remains a separate product; any future read-only connection requires a separately approved provider contract and is not a Phase 1 dependency.

### Dynamic, adaptable record schema

Do not alter the SQL schema every time a memory type needs a new optional field. Use a stable typed envelope plus versioned JSON payload/extension fields:

- Stable indexed columns: record_id, namespace, record_type, schema_version, status, sensitivity, created_at, updated_at, expires_at, source/provider, confidence and version.
- Domain payload: validated JSON for typed content, with an explicit extensions/attributes object for new optional fields.
- A field/schema registry records each extension's namespace, type, validation rules, sensitivity, index intent, introduction version and deprecation status.
- Unknown fields are preserved only in the bounded extension object; arbitrary SQL identifiers, unvalidated model keys and schema mutations are prohibited.
- Frequently queried fields get typed columns or explicit indexes; less common fields remain JSON. New fields require a schema-registry update and tests, not an ad-hoc ALTER TABLE on a live user database.
- Every record carries a schema version; migrations are transactional, deterministic, idempotent and backward-compatible where possible. Deprecations use a transition window and do not erase old values until migration/backup validation.
- Use SQLite JSON support and optional FTS5 where available; vector embeddings remain local and model-versioned. Never silently pull an embedding model.

### Real-time access and consistency

- All APEX features use one UnifiedDataStore connection/session factory and repository facade; no feature opens its own memory database path.
- Enable SQLite WAL, foreign keys, busy timeout and bounded transactions. Use one serialized writer queue with batched writes for observer/scanner traffic; multiple readers may query the latest committed snapshot.
- Commit a monotonic change sequence to a store_changes journal in the same transaction as each update. Local subscribers/IPC clients can request changes after a sequence and receive invalidation notifications after commit.
- Use optimistic record versions/compare-and-swap for simultaneous edits, and idempotency keys for repeated discovery/import/enrichment events.
- Expose live read APIs for profile, memories, application records, scan progress, diagnostic state and recent changes. Responses include updated_at, source and freshness.
- Bound event ingestion, JSON payload size, query limits, FTS rebuilds, embedding work and maintenance/checkpoint operations. SQLite has a single-writer constraint; the writer queue and batching prevent background telemetry from competing with interactive requests.
- Provide backup, integrity check, recovery, schema version and size/retention reporting. Database unavailability must degrade clearly; do not invent or silently recreate an empty memory store.

### Memory categories and behavior

- **Profile:** user-approved identity and preferences.
- **Working:** current conversation/task context with a short TTL.
- **Episodic:** reviewed events, incidents, task outcomes and user decisions.
- **Semantic:** stable user-approved facts and validated Windows knowledge.
- **Procedural:** reviewed workflows and reusable task patterns; these are references, not executable privileges.
- **Prospective:** user-directed goals, reminders and pending task steps.

Each record needs provenance, creation/updated time, sensitivity, verification state, confidence where meaningful, expiry/retention, schema version and revision history.

Rules:

- Do not silently save every conversation or raw telemetry stream as personal memory.
- Save profile facts and long-term memories through explicit onboarding, explicit save actions or narrowly configured consent.
- Automatically retain operational observations only under configured telemetry policy and existing retention controls.
- Retrieve only relevant, non-sensitive memories by default.
- Show the source and freshness of retrieved memories.
- Provide inspect, edit, correct, export and delete workflows.
- Keep profile data logically separated from machine observations even though both reside in the same database.
- Unified storage means one database file, not one unstructured blob: use domain tables, typed models, provenance and access controls.

## 9. Capability registry and tool execution

The registry is the authoritative catalogue of what APEX can actually do.

Each tool manifest must define:

- Stable capability ID and version.
- Name, purpose and user-facing description.
- Typed JSON input schema and bounded output schema.
- Provider/handler and health check.
- Read/write classification and risk tier.
- Required identity/privilege, approval rule and rate limit.
- Timeout, cancellation and resource budget.
- Evidence provenance and verification contract.
- Rollback/compensation contract when applicable.

### Phase 1 — Whole-Windows automation coverage

Whole-Windows automation is a **Phase 1 deliverable**, not a later add-on. Phase 1 must establish the host, typed capability registry, tool dispatcher, Windows action adapters, policy/approval integration, audit trail, verification and a broad initial capability catalogue together.

The target is broad coverage of supported Windows workflows through explicit adapters. It does not mean unrestricted shell access, arbitrary administrator rights, or a promise that every third-party application exposes automatable controls. Every capability must be reported as available, unavailable, disabled, approval-gated or unsupported based on a live provider check.

**Phase 1 action domains**

- **Desktop input and interaction (first-class, not optional):** provide bounded mouse movement, left/right/middle click, double-click, drag/drop, vertical and horizontal wheel scrolling, keyboard key presses, hotkeys/shortcuts, text entry into an explicitly targeted and focused control, and orderly key/button release. Each action must target a verified window/control, use bounded coordinates/timeouts, and stop on user interruption. Do not implement keylogging or passive capture of typed input.
- **Window and desktop management:** enumerate top-level windows; identify title/process/handle metadata within privacy limits; focus, restore, minimize, maximize, move, resize, snap, close and switch windows; launch apps; use task switching and supported virtual desktop operations; interact with supported Start/taskbar/notification-area surfaces. Never close protected/system/security/anti-cheat processes through generic window operations.
- **UI Automation control plane:** inspect an allowlisted application's UIA tree and supported control properties; invoke buttons; set values; select list/combo items; toggle checkboxes; expand/collapse; select tabs; wait for controls; scroll containers; and verify control state. Prefer semantic UIA control patterns over coordinate clicking. UIA exposes most, not all, desktop UI elements and depends on the application's provider support. See [Microsoft UI Automation](https://learn.microsoft.com/en-us/windows/desktop/winauto/entry-uiauto-win32) and its [control/tree specification](https://learn.microsoft.com/en-us/windows/win32/winauto/ui-automation-specification).
- **Input simulation fallback:** use Windows input injection for interactions that cannot be performed through UIA or a native adapter, including pointer movement/clicks, wheel scrolling, drag gestures, keyboard shortcuts and text entry. Resolve the target window immediately before dispatch. Respect Windows integrity/UIPI restrictions: input injection is not a way to bypass elevation, the secure desktop, a locked workstation or protected applications. See [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput).
- **Audio, media and volume:** read/set master output volume and mute, select an available output endpoint, inspect supported audio endpoints, and control per-application audio sessions where Windows exposes them. Add play/pause/next/previous and mute/volume media actions for supported sessions. Prefer Windows Core Audio endpoint/session APIs rather than clicking the volume flyout; use multimedia keys only as a bounded fallback. See [EndpointVolume API](https://learn.microsoft.com/en-us/windows/win32/coreaudio/endpointvolume-api).
- **Clipboard and text workflows:** perform explicit copy, cut, paste and clipboard set/get actions only when requested and scoped to the active task; support non-sensitive text entry and ordinary form controls. Never read clipboard contents in the background or collect passwords, authentication codes, payment data or other secrets.
- **Applications and windows:** discover installed/running applications; launch registered applications and approved URI/file targets; manage known app workflows. Any process-ending operation must bind to PID plus process creation time and protect Windows, security, anti-cheat and other protected processes.
- **Files and folders:** browse and search user-approved roots; inspect metadata; create folders; copy, move and rename; send items to the Recycle Bin. Permanent deletion, bulk cleanup, protected locations and recursive destructive operations remain blocked or require a separately reviewed capability and explicit confirmation.
- **Windows settings and personalization:** open the relevant Settings page and use typed adapters for supported settings such as volume, brightness, display, power, Wi-Fi, Bluetooth, night light, focus/notification behavior and accessibility. Each setting must have a concrete read/write handler and postcondition check; merely opening a Settings URI is not reported as changing a setting.
- **Processes and applications:** inspect process identity/resource state; launch registered executables; close an app through its supported application/window path; allow termination only for explicitly supported, non-protected targets with exact target revalidation and approval.
- **Services, startup and scheduled tasks:** inspect services, startup entries and tasks; enable/disable registered startup items; run or manage named tasks; start/stop only approved noncritical services. Critical Windows, security, networking, storage and anti-cheat services are protected.
- **Networking:** inspect adapters, DNS, routes, proxy and connectivity; provide typed operations for supported adapter toggles, DNS configuration, DHCP renew/release and bounded repair workflows. Network resets, firewall changes, proxy changes and operations that can disconnect the session require explicit approval and a recovery path.
- **Devices and peripherals:** inspect PnP/device health and expose only individually validated device actions. Device disable/enable requires elevation where Windows demands it, exact device identity, approval and a recovery path. Driver installation/removal and firmware changes are not general-purpose Phase 1 actions.
- **Display, power and session controls:** provide typed controls for supported brightness, resolution/scaling, refresh rate where available, power plans and sleep/display timeouts. Lock/sleep/restart/shutdown/sign-out actions require a direct, immediate user confirmation and must not be initiated by background autonomy.
- **Windows maintenance and security:** expose status and named, bounded workflows such as Defender scan requests, update checks and selected built-in repair diagnostics. Security-control weakening, silent update installation, broad cleanup and repair commands with uncertain side effects are not autonomous actions.
- **Browser and app-specific workflows:** add adapters only for explicitly supported apps and user-enabled integrations. Browser navigation/tab controls may use a dedicated extension/native-host bridge; do not infer that the video-observation extension grants general browser-control access. Never collect cookies, passwords, tokens, private form values or arbitrary browsing content.
- **Multi-step workflows:** compose supported capabilities into plans with preconditions, dependencies, progress, cancellation, per-step policy evaluation, verification and compensating actions. APEX must explain unsupported steps instead of improvising shell commands.

### Dynamic installed-application discovery and executable resolution

APEX must not rely on a hardcoded list of executable paths. It maintains a rebuildable, provenance-aware **Installed Application Catalogue** that discovers desktop and packaged apps, resolves friendly names to the correct launch target, and refreshes as software is installed, updated or removed.

**Discovery sources, merged in order of confidence**

1. **Windows App Paths registration:** enumerate per-user and machine registrations under `HKCU/HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths`, including both 32-bit and 64-bit registry views. Resolve the default executable path and optional per-app `Path` value. Microsoft documents App Paths as the recommended registration for mapping an executable filename to its fully qualified path. See [Application Registration — App Paths](https://learn.microsoft.com/en-us/windows/win32/shell/app-registration).
2. **Installed-program registry:** inspect the machine and current-user Uninstall registry keys in both registry views. Use `DisplayName`, `Publisher`, `DisplayVersion`, `InstallLocation` and `DisplayIcon` as metadata; do not assume that `DisplayIcon` or `InstallLocation` is itself the launch executable. Resolve a candidate executable by corroborating other sources.
3. **Start Menu and shortcut inventory:** enumerate current-user and all-users Start Menu `.lnk` entries, plus explicitly included desktop shortcuts. Resolve shortcut target, arguments, working directory and icon using the Windows Shell Link API; treat shortcut arguments as untrusted metadata and never blindly replay them.
4. **Packaged applications:** collect installed MSIX/AppX package family names, application IDs and AUMIDs from package manifests and Windows app registration. Use `Get-StartApps` as one source of display-name/AppID pairs, but never treat it as the complete installed-app list: Microsoft documents that apps absent from Start do not appear there. Resolve packaged launch targets through their AUMID/package identity, not by recursively crawling protected `WindowsApps` folders. See [Get-StartApps](https://learn.microsoft.com/en-us/powershell/module/startlayout/get-startapps) and [Find an installed app's AUMID](https://learn.microsoft.com/en-us/windows/configuration/store/find-aumid).
5. **Live process observations:** learn executable paths for currently running processes from the Phase 1 process provider, then correlate them with installed-app records. A running process alone does not prove that its executable should be trusted for future launch.
6. **Full local-volume application scan:** provide a user-visible initial and on-demand scan of accessible fixed local volumes to find unregistered desktop applications installed in custom directories. Scan executable/shortcut metadata only (`.exe`, supported shortcut formats and package/activation metadata); do not read document contents, browser profiles, credentials or unrelated file contents. Read PE version resources and Authenticode publisher/signature metadata when available; do not compute full-file hashes for every file by default.

**Full-PC scan policy**

- The full application scan covers all selected accessible fixed local volumes, including custom install folders and per-user application install roots, not merely `Program Files`.
- Skip reparse points by default to prevent loops and path escapes. Report access-denied paths and inaccessible volumes as coverage gaps; do not silently claim a complete scan.
- Exclude Windows component stores and servicing/cache areas that contain large volumes of system binaries rather than user-installed apps (for example WinSxS, Windows Installer/servicing caches, SoftwareDistribution, restore points and Recycle Bin internals). Discover packaged apps via Windows package metadata rather than crawling protected `WindowsApps`.
- Keep scanning bounded, cancellable, low-priority and resource-aware. Pause or throttle during gaming, high foreground load, low battery or memory pressure.
- Prefer an existing Windows Search metadata index as an optional accelerator only when available. Do not enable Enhanced indexing, alter the user's Search privacy settings, or index document/email contents on APEX's behalf. Windows Search's Enhanced mode can index all user folders and files and may use more resources; APEX's application catalogue must remain executable/shortcut metadata-only. See [Windows Search indexing](https://support.microsoft.com/en-us/windows/experience/performance-optimization/search-indexing-in-windows).
- Maintain the catalogue incrementally using registry/package change signals, file-system change notifications on known roots and bounded scheduled reconciliation scans. A full-volume rescan must not run continuously.
- Store app-discovery records in dedicated tables inside the same canonical APEX Unified Data Store used for all persistent APEX memory. The app catalogue remains a logically separate, rebuildable domain (name, aliases, path or AUMID, source, version, publisher, signature state, file identity/timestamps, last-seen time and confidence), not a general file-content index. Rebuilding the catalogue must not delete or rewrite user memories.

**Name resolution, trust and launching**

- Normalize names and build searchable aliases from display name, product name, file description, original filename, executable basename, shortcut name, package display name and user-confirmed aliases.
- Rank candidates using source reliability, path existence, install metadata, package identity, publisher/signature status and user trust decisions. Keep discovery provenance so APEX can explain why it selected a target.
- Never launch a binary merely because a filename matched. Reject missing paths, reparse/path escapes, temporary/download/cache locations and candidates that fail configured trust policy. An unsigned app may still be user-approved; a valid signature alone is not a guarantee of safety.
- If multiple candidates remain plausible (for example stable/beta/portable copies), ask which one to use or apply a saved user preference. Do not guess.
- Launch desktop apps by their resolved canonical executable path using a typed launch handler; use packaged-app activation by validated AUMID. Do not accept model-generated arbitrary command-line strings or unvalidated arguments. URI/file opening is a separate typed operation with scheme/extension policy and target validation.
- Verify launch by observing the expected process/window/package activation after dispatch. Report process creation separately from a usable window being ready.
- Detect removed/moved/updated executables and mark stale catalogue entries unavailable until re-resolved. Provide a user-inspectable app catalogue with source, resolved path/AUMID, trust status, last scan and launch availability.



**Model-assisted executable metadata enrichment (local and evidence-bound)**

The model may enrich missing or ambiguous descriptive metadata, but it is not the source of executable facts and must never invent or choose an executable path.

- The deterministic scanner and Windows APIs establish executable path, file identity, package/AUMID, registry/shortcut source, version resources, publisher/signature status and timestamps. These fields are authoritative only with their original OS/file provenance.
- When descriptive metadata is incomplete or ambiguous, send a bounded, minimized JSON record to the already-installed local APEX Ollama model. Candidate fields include display/product name, file description, original filename, executable basename, package display name, publisher text, version and discovery-source labels. Do not send file contents or binaries.
- Ask the model only for schema-defined enrichment such as normalized product/app name, likely vendor/product family, aliases, broad app category, concise purpose/description, duplicate-family suggestions and a confidence estimate. The model may return an unknown value; it must not return an executable path, signature verdict, privilege level or permission decision.
- Treat every model result as an untrusted suggestion. Validate against a strict JSON schema, allowed categories, length limits and candidate IDs. Preserve the deterministic source fields unchanged. Never allow model output to change the path, AUMID, publisher/signature evidence or launch trust state.
- Persist the enrichment beside the source record in the same Unified Data Store with model tag, provider, prompt version, output-schema version, timestamp, evidence/candidate IDs, confidence and review status. Keep raw prompts/responses only when needed for a bounded audit/debug policy; default to storing normalized output and provenance.
- Use local inference only. Enrichment is queued, batched and low priority; deduplicate by file identity/version and run only when resource policy permits. Do not call the LLM once per file or during every scanner pass.
- Deterministic metadata always wins over contradictory model suggestions. Low-confidence aliases, app-family merges or uncertain classifications require user review. A model suggestion never authorizes launch or enables an automation adapter.
- Cache the result and re-enrich only when the executable identity/version or relevant source metadata changes, or when the user explicitly requests refresh.

This division keeps executable discovery deterministic and lets the model improve the catalogue's human understanding without becoming a fabricated source of truth.

### Windows Settings, CPL and MMC target catalogue

- Store documented `ms-settings:` URIs in a versioned catalogue with friendly aliases, supported Windows build/SKU constraints and known prerequisites. Validate the target against the current OS and handle launch failure; do not invent a URI. Use Microsoft's [Launch Windows Settings URI reference](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings).
- Maintain a separate allowlist of Control Panel `.cpl` applets and MMC `.msc` consoles (for example Device Manager, Services, Event Viewer, Task Scheduler, Disk Management, Network Connections and Power Options). Resolve each through its documented Windows host and verify the target file/console exists on the current installation.
- When a user asks to "open sound settings", "open Device Manager" or "show app settings for [app]", resolve to a known URI/console; for app-specific default-app settings, use a validated registration/AUMID where supported. Opening a settings page is not the same as changing the underlying setting.
- Keep custom application URI schemes in a separate registry-derived catalogue. Only allow schemes with a known handler and explicit policy; never pass arbitrary user/model URLs directly to a privileged shell handler.

**Interaction priority and desktop ownership**

1. Prefer a documented native Windows API or app-specific API for deterministic actions (for example, Core Audio for master volume).
2. Prefer UI Automation semantic patterns for controls, text/value operations, selection, invoke and container scrolling.
3. Use mouse/keyboard input simulation only when semantic APIs are unavailable or insufficient.
4. Use visual/screen-grounded coordinate actions only when an explicit, opt-in screen-perception provider is available; never guess coordinates from stale or absent screenshots.
5. Treat injected mouse/keyboard activity as taking the interactive desktop temporarily. Obtain a short interaction lease, verify the target is foreground, stop on detected user input/focus change, and allow immediate user cancellation. Do not run competing UI-control jobs in the background.
6. UIA semantic operations may work without taking foreground focus, but input injection requires an unlocked interactive desktop and is subject to Windows integrity/UIPI restrictions. UAC secure desktop, sign-in/lock screens and protected app surfaces are out of scope for bypass.

**Execution adapters and hard limits**

- Prefer documented Windows APIs, CIM/WMI, registered application protocols and narrow PowerShell cmdlet adapters with typed parameters.
- PowerShell may be used behind named, versioned handlers whose command and parameter set are fixed in code/configuration. The model must never submit an arbitrary command string.
- No unrestricted `execute_powershell(command)`, arbitrary `cmd.exe`, generic administrator terminal, arbitrary file deletion or unbounded script generation.
- Every mutating capability declares risk, privilege, target identity, approval requirements, timeout, rate limit, preconditions, before-state capture, postcondition verifier and rollback/compensation support.
- Unknown or unsupported actions fail closed. A model-generated plan is not permission to execute it.
- Elevated operations use a narrowly scoped broker and normal Windows UAC; the normal APEX host remains unelevated.
- Every capability has an enable/disable switch and appears in the runtime manifest with actual provider health and permission state.

**Automation coverage acceptance matrix**

Phase 1 is not complete with only chat, Settings-page opening or a toy two-command allowlist. It must include tested, documented operations across the action domains above. For each supported operation, tests must cover valid input, invalid input, unavailable provider, permission denial, protected target, cancellation, timeout, audit record, postcondition verification and rollback/compensation where applicable. Operations not yet implemented must be explicitly marked unavailable rather than implied by a broad category name.

## 10. Diagnostics and reasoning workflow

A diagnostic request should use a bounded loop:

1. Classify the request and determine whether live system evidence is necessary.
2. Select relevant providers and verify their health/freshness.
3. Collect a minimal evidence window.
4. Retrieve relevant user-approved memories and prior incidents.
5. Normalize and correlate observations deterministically.
6. Ask the model for hypotheses, alternative explanations, missing evidence and next checks.
7. If needed, request additional read-only tools through the registry.
8. Score evidence coverage and confidence separately from model certainty.
9. Present observed facts, hypotheses, limitations and recommended actions distinctly.
10. For an approved action, execute and independently re-observe the target.
11. Record the incident, evidence, decision, approval and outcome.

The agent must not treat a correlation as a proven cause. If telemetry is stale or missing, it must say so and request a targeted collection rather than fabricate a diagnosis.

## 11. Controlled autonomy and verification

Use APEX-owned capability manifests, default-deny policy broker, approval, execution-control and audit components.

Initial autonomy levels:

| Level | Behavior |
|---|---|
| Observe | Collect/read-only tools only |
| Recommend | Diagnose and prepare a plan; no state changes |
| Assisted | Execute a specific controlled action after explicit approval |
| Bounded autopilot | Only individually enabled, reversible, low-risk capabilities with limits, a kill switch and audit |

Enforcement rules:

- The model never grants itself capability or permission.
- Validate tool names, parameter schemas, target identity and preconditions outside the model.
- Approval binds to the exact capability, target, arguments, expiry and one execution attempt.
- Recheck policy and target identity immediately before execution.
- Use least privilege; routine host and UI processes run as the signed-in user.
- Elevation is a separate, narrowly scoped broker action with Windows UAC where required.
- Every write has before/after evidence, timeout, cancellation and audit.
- Verify using a fresh independent provider read, not the command's exit code alone.
- A rollback is a compensating action where exact reversal is impossible.
- Critical/destructive/security-sensitive actions remain blocked from autonomous execution.
- Maintain a global stop/disable control and per-capability kill switches.

## 12. Desktop experience — deliberately deferred

The APEX desktop UI is a separate product surface. It must not be added to the SENTINEL dashboard.

UI design starts only after the headless host contracts are stable. A later UI decision may evaluate a native Windows shell (including WPF/.NET, already present elsewhere in this repository) against a Python-native shell. Reuse visual assets or patterns only after review; do not embed or modify `SENTINEL/ui/`.

The future standalone experience should support:

- APEX chat and streaming answers.
- Live connection/status view for model, providers and capabilities.
- System overview and diagnostic reports.
- Profile and unified-memory review.
- Approval queue, action timeline and verification results.
- Background/tray lifecycle and configured sign-in launch.
- Keyboard accessibility and reduced-motion support.

Voice and wake-word remain later opt-in capabilities. Core desktop interaction—mouse, keyboard, clicks, scrolling, UIA control patterns, volume/media and window management—is required in Phase 1. Advanced visual screen understanding and screenshot-grounded coordinate reasoning may be introduced as an opt-in extension after the baseline interaction engine is stable.

## 13. Proposed repository layout

The final layout follows the standalone `apex/` package and must not depend on AIE package conventions.

```text
apex/                         # standalone assistant runtime
  store/                       # one UnifiedDataStore, repositories, migrations and field registry
  identity/                   # APEX identity and prompt versions
  runtime/                    # host lifecycle, sessions, model requests
  context/                    # bounded context and evidence composition
  registry/                   # capability manifests and tool dispatch
  providers/                  # APEX-owned native Windows providers and optional external adapters
  profile/                    # user profile and consent
  memory/                     # APEX-owned repositories over UnifiedDataStore
  diagnostics/                # investigation and evidence correlation
  autonomy/                   # plan, approval bridge, execution, verification
  ipc/                        # local desktop-to-host protocol
  telemetry/                  # APEX runtime/performance instrumentation
configs/apex/                 # versioned APEX model/prompt/tool configuration
desktop/APEX/                 # future independent desktop shell; UI milestone
tests/apex/                   # unit, integration and Windows-host tests
docs/APEX_STANDALONE_IMPLEMENTATION_PLAN.md
docs/APEX_FOLLOW_UP_TODOS.md
```

Do not create the full directory tree until the corresponding phase is implemented. Keep the initial milestone documentation-only.

## 14. Implementation phases and exit gates

### Phase 0 — Architecture and repository mapping
- Document product boundary, architecture, data flows, existing component reuse and TODO backlog.
- Confirm branch and integration policy.
- Inspect existing contracts and tests before choosing extension points.

**Exit:** reviewed plan and ADR; no application code or UI changes.

### Phase 1 — APEX runtime + whole-Windows automation engine
This is the first coding milestone. Build the assistant host and the actual Windows automation capability layer together.

- Add the APEX package, configuration, versioned identity, lifecycle, structured logging, local sessions and cancellation.
- Connect to the installed `APEX` Ollama model through APEX's direct Python loopback HTTP client; no Ollama CLI or subprocess is used for inference.
- Implement bounded non-streaming inference, fixed `think: false` in the Python `/api/chat` request, context/timeouts, inference metrics and a single local inference slot.
- Implement the live capability registry, `apex_get_runtime_manifest`, typed tool schemas and host-side multi-turn tool dispatcher.
- Establish the canonical UnifiedDataStore path, schema registry, versioned migrations, shared connection factory, change journal and one-writer/multi-reader access pattern. The app catalogue is stored in this same database.
- Complete the idempotent, loss-checked migration of existing events.sqlite3, memory.sqlite3, task-runs.sqlite3 and task-sessions.sqlite3 into apex-unified.sqlite3 before APEX begins writing profile, conversation or app-catalogue records. Verify counts/checksums, references and integrity; preserve verified backups and rollback path. Route EventStore, MemoryStore, TaskRunStore and TaskSessionStore through the same physical database path.
- Implement the complete Phase 1 interaction surface in Section 9: mouse movement/click/double-click/right-click/drag, vertical/horizontal scrolling, keyboard shortcuts and targeted text entry; window focus/restore/minimize/maximize/move/resize/switch; semantic UIA inspect/invoke/set/select/toggle/expand/scroll/wait operations; master/per-session volume, mute, audio endpoint and media controls; explicit clipboard operations; plus files, applications, settings, processes, services, startup/tasks, networking, devices, display/power and maintenance workflows.
- Implement a live Windows baseline provider set in Phase 1, not just action handlers: OS/build and device summary; current session identity as exposed by documented Windows APIs; process inventory/details; foreground windows and registered application metadata; service/startup/task state; network adapters/DNS/routes; volume/free-space status; CPU/RAM load; and the specific setting values required by supported setting actions. Every response carries source, observed time, freshness, privilege and coverage. This baseline must answer “Can you see my running processes?” with a real bounded snapshot when the provider is healthy.
- Add versioned Settings URI, CPL/MSC and custom protocol catalogues; resolve known Windows targets with OS-build validation.
- Implement the dynamic installed-application catalogue from App Paths, Uninstall registry metadata, Start Menu Shell Links, packaged app/AUMID metadata and live processes.
- Add an opt-in/on-demand full fixed-volume scan for executable and shortcut metadata only, plus incremental reconciliation; never index file contents or silently enable Windows Search Enhanced indexing.
- Add confidence-ranked application name/alias resolution, exact-path/AUMID validation, trust classification, ambiguity handling, launch verification and stale-entry refresh.
- Add self-knowledge and identity regression cases for “what is your name?”, “who made/configured you?”, “what model are you?”, “what tools/providers are connected?”, “can you see my processes?” and Windows settings/CPL lookups. APEX must distinguish its own assistant/host identity, the configured operator/creator attribution, the foundation model and live provider capabilities. If a provenance field is unknown, say unknown; never fabricate Microsoft authorship, kernel access, local visibility or user identity.
- Add local model-assisted application metadata enrichment for incomplete/ambiguous EXE candidates; model output is schema-validated descriptive metadata only, never path/signature/trust/permission truth.
- Implement APEX-owned policy broker, capability manifests, approval, execution-control, executor and audit ledger.
- Implement a desktop-interaction lease and user-interruption detector for input-injection sequences; never fight the user's mouse/keyboard or steal focus repeatedly.
- Apply per-action risk tiers and approvals, UAC boundary handling, dry-run/preview, cancellation, rate limits, before-state snapshots, audit and rollback/compensation where feasible.
- Use fixed typed Windows handlers and reviewed/versioned command recipes. Do not let the model create arbitrary PowerShell/CMD strings or gain a generic administrator terminal.
- Provide a developer harness and Windows integration tests; the final desktop UI remains deferred.

**Exit:** APEX can receive natural-language requests for both tiny desktop actions and large system workflows, select registered typed capabilities, obtain required approvals, execute and independently verify supported actions, and report unsupported/unavailable operations honestly. Demonstrated Phase 1 coverage must include volume up/down/mute, window switching, app launch, clicking/invoking controls, keyboard shortcuts, text entry into non-sensitive controls, vertical/horizontal scrolling, file operations and system/network settings. It must also prove safe interruption when the user takes control. It runs through its own host without `ollama run`, and SENTINEL UI remains untouched. All durable APEX memory, observation/evidence, task-context and app-catalogue data use the same verified canonical SQLite file; no parallel memory database remains.

### Phase 2 — Expanded real-time Windows perception
- Formalize and extend Phase 1 provider contracts and normalized evidence envelopes.
- Expand APEX-owned Windows observation providers and normalized evidence contracts. Optional external integrations require separate future approval and do not affect baseline operation.
- Expand beyond the Phase 1 live baseline into richer hardware/sensor coverage (GPU and supported temperature/power sensors), per-process resource deltas, detailed storage/I/O, bounded Windows Event Log metadata and validated ETW event families.
- Add richer provenance, freshness, permission, provider-health, coverage and event-loss reporting; distinguish unavailable sensors from zero values.
- Add adaptive/event-driven collection and gaming/resource-aware sampling without LLM polling.

**Exit:** APEX has broad, fresh, provenance-aware Windows telemetry from its own providers. Phase 2 deepens telemetry fidelity; it does not postpone basic process, service, network, storage and system visibility, which are required in Phase 1.

### Phase 3 — Profile and unified memory
- Add an explicit onboarding interview for display/preferred name, salutation (default `sir`), locale, communication style, device aliases, technical preferences and user-approved goals; never guess a person's name from a Windows folder path.
- Extend the Phase 1 canonical UnifiedDataStore with the full profile, conversation, all memory-kind, embedding, lineage, approved workflow knowledge and diagnostic knowledge workflows. Do not create additional persistent APEX memory databases.
- Keep policy/egress audit stores segregated where their append-only integrity boundary requires it; keep SENTINEL's private database separate and read-only from APEX.
- Ensure onboarding and memory APIs read/write the same canonical database as the Phase 1 app catalogue and Windows evidence.
- Add user-controlled, local-only indexing of explicitly selected folders/documents as an optional knowledge source. Exclude credentials, browser secrets, protected/system locations and unselected folders; make source paths, indexing state, retention and removal inspectable.
- Implement explicit save/review/correct/export/delete and relevant-memory retrieval.
- Add memory conflict/staleness handling and user controls for retention, consent and data deletion.

**Exit:** APEX can recall the user's explicitly supplied profile and approved information across app restarts, can answer personal-profile questions from that profile, and gives the user inspect/edit/export/delete controls without a duplicate memory DB.

### Phase 4 — Advanced Windows diagnostic intelligence
- Add request/task classification and bounded specialist profiles.
- Add deterministic evidence correlation and incident records.
- Add model-generated hypotheses and next-step suggestions grounded in evidence IDs.
- Add self-introspection: model, tool, provider, permission and memory status.
- Add benchmark corpus and factuality/grounding evaluation.

**Exit:** repeatable Windows diagnostic tasks show evidence provenance, limitations and measured quality.

### Phase 5 — Adaptive autonomy and background operation
- Add goal/task lifecycle and bounded agent loop.
- Add resource-aware admission, sampling and inference budgets.
- Add proactive findings only for configured, high-signal conditions.
- Add pause/stop controls, per-capability controls and notification delivery.
- Allow bounded autopilot only for individually enabled, reversible, low-risk capabilities with strong verification.
- Validate behavior during gaming/foreground workloads.

**Exit:** proactive behavior remains bounded, explainable, reversible where possible and does not degrade foreground use. It extends Phase 1 automation; it does not introduce automation for the first time.

### Phase 6 — Standalone desktop UI and Windows packaging
- Select native UI technology after host/API contracts stabilize.
- Build an independent APEX window, tray controller and startup integration.
- Launch/connect to Ollama and APEX host without requiring a command prompt.
- Provide status, chat, evidence, memory, approvals and automation workspaces.
- Package and test install, update, uninstall and rollback.

**Exit:** user can install, launch, use and remove APEX as an independent Windows app; SENTINEL UI is untouched.

### Phase 7 — Evaluation and optional model adaptation
- Benchmark base Qwen/APEX prompt against any candidate adapter on the same tasks.
- Build reviewed, licensed and consented data only.
- Fine-tune only if measurable behavior gaps remain after prompts, tools, retrieval and deterministic logic.
- Keep base model and adapters independently addressable and reversible.

**Exit:** adapter promotion requires held-out quality, capability-preservation, privacy and safety gates.

## 15. Performance and resource policy

Target the current 16 GB RAM / Core i5-12500H-class Windows laptop. This is a design constraint, not a performance guarantee.

- Start with the installed Qwen3.5 4B APEX tag.
- One local inference request at a time initially; serialize requests within the APEX runtime only.
- Use request-level thinking disabled for ordinary conversation; deep reasoning is explicit/adaptive and resource-gated.
- Keep the system prompt and context concise; retrieve only relevant tools and memories.
- Do not send full inventories or raw event history into the model.
- Do not use continuous LLM polling for telemetry.
- Collect with deterministic workers; invoke inference only for user requests or meaningful findings.
- Defer embedding, deep reasoning and large scans under memory pressure or active gaming.
- Measure cold/warm latency, time-to-first-token, tokens/second, peak working set, prompt/output tokens and host CPU usage before tuning.
- Never weaken Defender, VBS, HVCI, Secure Boot, Vanguard or other protections to improve APEX performance.

## 16. Security, privacy and governance

- Local-first by default; remote/cloud inference is disabled unless a separate, explicit egress policy permits a specific request.
- No hidden data collection. Show provider status and collection scope.
- No credential, password, cookie, private-key or authentication-token collection.
- No keylogging, covert screenshots, microphone/wake-word capture without explicit opt-in, or arbitrary page/form/document surveillance.
- UI Automation and window metadata remain disabled by default, allowlisted, bounded and inspectable.
- Treat model output, tool output, retrieved documents and memory as untrusted data.
- Separate user profile, machine telemetry and conversation history.
- Use local data encryption where supported by Windows user protection; do not invent a custom cryptographic scheme.
- Provide pause, export, deletion and retention controls.
- Log capability use, policy decision, approvals, execution, verification and failures.
- Do not run the normal APEX UI/host as Administrator.

## 17. Test and evaluation strategy

Required test groups:

- Identity and prompt composition: salutation, slang, concise chat, truthful creator/model identity, no unsupported capability claims.
- Model transport: Ollama unavailable, missing model, malformed response, timeout, cancellation, thinking-off behavior, streaming and context limits.
- Runtime introspection: every reported model/provider/tool/permission matches the live manifest.
- Windows providers: schema validation, freshness, permission denied, missing source, event loss and degraded state.
- Memory: persistence across restart, provenance, sensitivity exclusion, conflict, expiry, revision, export and deletion.
- Tool registry: unknown function, invalid arguments, oversized input/output, timeout, duplicate call and provider failure.
- Policy: default deny, expired approval, target change, protected target, rate limit and kill switch.
- Execution: before/after capture, independent verification, failure, compensation and audit integrity.
- Desktop: no console flash, normal-user launch, sign-in start, tray lifecycle, offline mode, update/uninstall.
- Performance: cold start, warm response, time-to-first-token, tokens/second, RAM/CPU during idle, conversation and diagnostic workloads.
- Windows-host integration tests on the target OS; hosted CI alone is not proof of real ETW/provider/desktop behavior.

Core metrics:
- First-token latency and full response latency.
- Prompt and output token counts.
- Correct tool-selection rate and invalid-tool rate.
- Diagnostic evidence coverage and root-cause quality.
- False-positive/false-negative rates for proactive findings.
- Memory retrieval relevance and stale-memory handling.
- Unauthorized action rejection rate (must be 100% in test cases).
- Verification accuracy and recovery success.
- Idle CPU/RAM overhead and gaming-session impact.

## 18. Decisions required before implementation

The following are intentionally deferred to Phase 1 or later design review:

1. Exact standalone UI technology (WPF/.NET versus Python-native); choose after backend contracts.
2. Exact local IPC mechanism (Windows named pipes preferred; authenticated loopback HTTP fallback).
3. APEX profile schema and explicit first-run questions.
4. Whether an optional, read-only external provider protocol should be introduced in a later release (not required for Phase 1).
6. Exact model tag/prompt version management and whether the current user Modelfile is copied into repository configuration unchanged.
7. Retention durations and user controls for each memory/event class.
8. Voice and additional perception opt-ins.

No implementation phase may silently resolve these choices by introducing a new UI, data store, model router or policy engine.

## 19. First implementation milestone

The first coding milestone after this planning branch is **Phase 1 — APEX runtime + whole-Windows automation engine**.

It must deliver an end-to-end local host and action layer, not a chat-only skeleton:
- APEX identity/runtime contract and local background host lifecycle.
- Ollama API connection to the already-installed `APEX` model tag, with thinking disabled by default and no visible Ollama CLI dependency.
- Bounded Python-owned inference, request lifecycle controls and resource metrics; streaming is a follow-up.
- Live runtime/capability manifest and typed multi-turn tool dispatch.
- A broad, documented Windows automation catalogue covering applications/windows, files/folders, settings, process lifecycle, services/startup/tasks, networking, devices, audio/display/power and selected maintenance/security workflows.
- Native/typed Windows handlers, bounded UI Automation fallback for explicitly allowlisted apps, and reviewed command recipes with fixed parameters.
- APEX-owned policy/approval/execution/audit, risk tiers, preconditions, target revalidation, before/after evidence, independent verification and rollback/compensation where feasible.
- Windows tests for every supported action family, including protected-target denial, permission denial, invalid arguments, timeout, cancellation and provider failure.
- No arbitrary shell access, no generic Administrator mode, no AIE/SENTINEL runtime or database dependency, and no new desktop UI in this milestone.

Phase 2 expands real-time Windows perception and evidence coverage; Phase 1 already provides the actual automation engine.
