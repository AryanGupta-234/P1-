# APEX — Standalone Windows Assistant Implementation Plan

**Status:** Architecture proposed; implementation not started  
**Planning branch:** `feature/apex-standalone-assistant-plan`  
**Base:** `dev`  
**Target platform:** Windows 11 x64 (Windows 10 compatibility is not in the initial acceptance target)  
**Initial local model:** Existing Ollama model tag `APEX`, built from the user's Qwen3.5 4B Modelfile  
**Application boundary:** A separate Windows desktop assistant; not a workspace, panel, route or embedded chat inside the SENTINEL dashboard

## 1. Product definition

APEX is the user's primary, conversational Windows assistant: a local-first, Friday/Jarvis-style interface for questions, personal context, whole-PC diagnostics, planning and controlled automation.

SENTINEL is a Windows observation and diagnostics capability that APEX can consult. It is not APEX's user interface and it does not own APEX's identity, conversation, profile or orchestration.

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
- Remain useful when Ollama, SENTINEL or an optional provider is unavailable; clearly report degraded capabilities.

### Non-goals for the first release

- Training a new foundation model from scratch.
- Replacing or rewriting the existing SENTINEL dashboard.
- Adding APEX chat to the SENTINEL UI.
- Kernel drivers, kernel memory access, process injection or anti-cheat interference.
- Unrestricted shell execution, unrestricted administrator access or hidden system changes.
- Keylogging, covert screenshots, microphone recording, credential harvesting, browser-cookie/form capture or arbitrary personal-file indexing.
- Automatic cloud inference or silent model downloads.

## 2. Repository baseline and reuse strategy

The implementation must start from the existing AIE `dev` branch and reuse its tested contracts and infrastructure rather than build parallel subsystems.

### Existing components to evaluate and reuse

| Existing repository component | APEX use |
|---|---|
| `aie/models/base.py`, `aie/models/ollama.py`, `aie/models/router.py` | Model request/response contract, loopback Ollama transport and hardware-aware local routing |
| `aie/prixon/identity.py` | Reference for separating assistant identity from foundation-model weights; APEX gets its own identity module and must not silently rename PRIXON |
| `aie/memory/store.py`, `aie/memory/prompt_context.py` | Existing local memory records, provenance, sensitivity and bounded context retrieval |
| `aie/orchestration/` and `aie/planning/` | Validated plans, task runs, dependencies, lifecycle and recovery |
| `aie/policy/` | Capability manifests, default-deny policy broker, approval controls, executor and audit ledger |
| AIE event contracts, observer, SQLite store and Windows providers | Read-only whole-machine observations and normalized evidence |
| `aie/desktop/tray.py` | Reference for native Windows tray lifecycle controls, not a mandate to reuse its UI |
| SENTINEL's documented local API, telemetry and diagnostics | Optional provider adapter for SENTINEL-owned observations and domain diagnostics |

Before implementation, inspect the exact `dev` versions and tests of every reused component. The plan does not assume every existing feature is complete or production-validated.

### No duplication rule

- Do not create a second model router if the AIE router can be extended through a backward-compatible interface.
- Do not create a second durable memory database if the AIE MemoryStore can host APEX-scoped records.
- Do not create a second policy broker, approval ledger or executor.
- Do not recreate Windows sensors already supplied by AIE or SENTINEL.
- Do not import SENTINEL's private module globals as an integration contract. Prefer a versioned provider interface or authenticated local API.
- Do not modify `SENTINEL/ui/`, `SENTINEL/sentinel/server.py` or the SENTINEL dashboard to host APEX.

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
  +--> AIE shared model, memory, planning and policy adapters
  |
  +--> AIE Windows observation provider
  |
  +--> SENTINEL provider (optional, independent process)
  |
  +--> Ollama loopback API (Qwen/Apex model)
```

The APEX host must run without a console window during normal use. The user should launch APEX from a Start Menu shortcut, desktop shortcut, notification-area entry or configured sign-in startup. A command-line developer mode may exist for diagnostics, but it is not the normal product experience.

### Runtime startup

1. Start or connect to the installed Ollama local service using a documented Windows launch/service integration.
2. Verify the loopback API is reachable; never assume it is running.
3. Discover installed models through Ollama's model-list API; never pull a model silently.
4. Verify that the configured APEX model tag exists and can answer a small health request.
5. Start or connect to the AIE observer/provider without opening the SENTINEL UI.
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
- **SENTINEL** is the observation/diagnostics provider and specialist capability.
- **Qwen3.5 4B** is the current foundation model used by the user's Ollama tag `APEX`.
- **PRIXON** remains the separately documented AIE model/adapter research identity until an explicit architecture decision changes that relationship. Do not silently merge identities or replace PRIXON files.
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
- Current inference mode (fast/deep), thinking setting and resource-admission state.
- Connected providers: AIE observer, SENTINEL provider, Windows native providers and optional services.
- Registered tools with identifier, description, schema version, source provider, availability, permission tier and last health check.
- Capabilities currently enabled, disabled, approval-gated or unavailable.
- Memory store status, active profile and retention state.
- Data collection and cloud-egress settings.
- Evidence freshness/coverage and known limitations.

A tool is considered connected only after a real health check. A registered-but-unavailable tool must be shown as unavailable. APEX must not say it has kernel access, full OS access or a capability that is not present in the manifest.

## 6. Whole-Windows perception and telemetry

APEX should consume normalized AIE observations first, then add provider adapters for missing Windows coverage. SENTINEL remains a separate provider, not the APEX UI.

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

### Initial model

Use the user's existing local Ollama model tag `APEX`, which is based on Qwen3.5 4B, as the first integration target. Preserve the current Modelfile as the initial user baseline; do not rewrite it as part of host integration.

APEX must call Ollama's local HTTP API, not depend on `ollama run` or a visible terminal session. The CLI remains useful for developer diagnostics only.

### Runtime requirements

- Use the existing AIE `ModelProvider` contract and Ollama adapter where compatible.
- Discover installed model tags; do not auto-download or silently switch to a remote model.
- Support streaming conversational responses and structured tool-call turns.
- Send a request-level thinking setting: thinking off for ordinary conversation; allow a deliberate deep-reasoning mode only when the task warrants it and host resource policy admits it.
- Use one local inference slot initially to avoid RAM/CPU contention.
- Keep the model warm only within configured memory budgets; unload or defer optional work under pressure.
- Apply bounded timeouts, response sizes, context budgets and cancellation.
- Record prompt tokens, output tokens, time-to-first-token, tokens/second, total duration, model load time and failures.
- Keep tool selection, action policy and memory retrieval outside the Modelfile.

### Dynamic prompt assembly

Build each request from clearly separated, versioned inputs:

1. APEX identity and communication principles.
2. Relevant specialist profile (Windows, performance, network, security or automation).
3. Current user request and bounded conversation history.
4. Relevant user-approved profile preferences.
5. Fresh evidence and selected memories with source/provenance labels.
6. Only the tool schemas relevant to the current task.
7. Execution policy reminder and available action tier.

Do not put the whole Windows inventory, full memory database or every tool schema into every prompt. Retrieved observations, user files and memory are untrusted reference data, not higher-priority instructions.

## 8. Unified profile and memory

Use the existing AIE memory store and data contracts where they meet requirements. APEX must not create a parallel durable memory database or directly write to SENTINEL's internal database.

Memory categories:

- **Profile:** user-approved identity and preferences.
- **Working:** current conversation/task context with a short TTL.
- **Episodic:** reviewed events, incidents, task outcomes and user decisions.
- **Semantic:** stable user-approved facts and validated Windows knowledge.
- **Procedural:** reviewed workflows and reusable task patterns; these are references, not executable privileges.
- **Prospective:** user-directed goals, reminders and pending task steps.

Each memory item needs provenance, creation/updated time, sensitivity, verification state, confidence where meaningful, expiry/retention and revision history.

Rules:

- Do not silently save every conversation or raw telemetry stream as personal memory.
- Save profile facts and long-term memories through explicit onboarding, explicit save actions or narrowly configured consent.
- Automatically retain operational observations only under the configured telemetry policy and existing retention controls.
- Retrieve only relevant, non-sensitive memories by default.
- Show the source and freshness of retrieved memories.
- Provide inspect, edit, correct, export and delete workflows.
- Keep user profile data separate from machine observations.
- If AIE and SENTINEL currently have separate stores, integrate through adapters and a reviewed migration plan; do not assume their schemas can be merged directly.

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

### Initial capability groups

**Read-only first**
- Host/system overview.
- Process inventory and process details by PID plus creation time.
- Service and driver state.
- Startup and scheduled-task inventory.
- Network interface/DNS/route diagnostics.
- Storage and volume status.
- Windows event evidence.
- Bounded ETW session status/catalog and approved trace collection.
- AIE/SENTINEL provider health.
- APEX runtime manifest and capability status.
- Profile/memory search with sensitivity filtering.

**Controlled automation later**
- Open allowlisted applications and Windows settings pages.
- Manage explicitly registered user workflows.
- Restart a narrowly allowlisted noncritical service after approval.
- Apply reversible configuration actions with a before-state snapshot.
- Run named, versioned diagnostic scripts through an approved adapter.

Do not expose an unrestricted `execute_powershell(command)`, arbitrary `cmd.exe`, arbitrary file deletion or generic administrator tool to the model. A generated script is a proposal until a separate validator, policy gate and explicit approval authorize a specific operation.

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

Reuse AIE's capability manifests, default-deny policy broker, approval, execution-control and audit components. Extend them only through reviewed, backward-compatible contracts.

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

Voice, wake-word, screen understanding and expanded UI Automation are later opt-in capabilities, not MVP assumptions.

## 13. Proposed repository layout

The final layout must be reconciled with existing AIE package conventions before files are added.

```text
apex/                         # standalone assistant runtime
  identity/                   # APEX identity and prompt versions
  runtime/                    # host lifecycle, sessions, model requests
  context/                    # bounded context and evidence composition
  registry/                   # capability manifests and tool dispatch
  providers/                  # AIE, SENTINEL and native Windows adapters
  profile/                    # user profile and consent
  memory/                     # adapter to unified AIE MemoryStore
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

### Phase 1 — Headless APEX host foundation
- Add APEX package/configuration and versioned identity.
- Implement lifecycle, settings, structured logging and local session model.
- Reuse the AIE Ollama adapter/router; connect to installed `APEX` model via loopback API.
- Implement request-level thinking-off default, cancellation, streaming and inference metrics.
- Implement `apex_get_runtime_manifest` and truthful capability inventory.
- Provide a developer test harness, not the final desktop UI.

**Exit:** APEX answers through its own host without `ollama run`; reports exact model/provider status and never invents tools.

### Phase 2 — Read-only Windows provider integration
- Define stable provider contracts and evidence schema.
- Connect to AIE observation state/event store.
- Add SENTINEL provider adapter through a supported API/contract.
- Add targeted Windows native collectors only for coverage gaps.
- Implement freshness, permission, provider-health and coverage reporting.

**Exit:** APEX can answer bounded, evidence-backed questions across supported Windows domains while SENTINEL UI remains closed.

### Phase 3 — Profile and unified memory
- Add explicit first-run profile setup and editable salutation/display-name preferences.
- Default salutation to `sir`.
- Reuse existing AIE MemoryStore with APEX namespaces and provenance.
- Implement explicit save/review/correct/export/delete and relevant-memory retrieval.
- Implement retention and privacy controls.

**Exit:** APEX remembers approved user preferences and relevant validated facts across app restarts, with user controls and no duplicate memory DB.

### Phase 4 — Whole-Windows diagnostic intelligence
- Add request/task classification and bounded specialist profiles.
- Add deterministic evidence correlation and incident records.
- Add model-generated hypotheses and next-step suggestions grounded in evidence IDs.
- Add self-introspection: model, tool, provider, permission and memory status.
- Add benchmark corpus and factuality/grounding evaluation.

**Exit:** repeatable Windows diagnostic tasks show evidence provenance, limitations and measured quality.

### Phase 5 — Capability registry and assisted automation
- Register read-only tools with typed schemas.
- Add multi-turn Ollama tool calling and host-side dispatch.
- Connect policy broker, approval and audit.
- Add a small allowlist of reversible, low-risk/controlled actions.
- Implement before/after verification and compensation.

**Exit:** invalid/unknown tools are denied; every state-changing action is policy-approved, auditable and verified.

### Phase 6 — Adaptive autonomy and background operation
- Add goal/task lifecycle and bounded agent loop.
- Add resource-aware admission, sampling and inference budgets.
- Add proactive findings only for configured, high-signal conditions.
- Add pause/stop controls and notification delivery.
- Validate behavior during gaming/foreground workloads.

**Exit:** autonomous behavior remains bounded, explainable, reversible where possible and does not degrade foreground use.

### Phase 7 — Standalone desktop UI and Windows packaging
- Select native UI technology after host/API contracts stabilize.
- Build an independent APEX window, tray controller and startup integration.
- Launch/connect to Ollama and APEX host without requiring a command prompt.
- Provide status, chat, evidence, memory, approvals and settings workspaces.
- Package and test install, update, uninstall and rollback.

**Exit:** user can install, launch, use and remove APEX as an independent Windows app; SENTINEL UI is untouched.

### Phase 8 — Evaluation and optional model adaptation
- Benchmark base Qwen/APEX prompt against any candidate adapter on the same tasks.
- Build reviewed, licensed and consented data only.
- Fine-tune only if measurable behavior gaps remain after prompts, tools, retrieval and deterministic logic.
- Keep base model and adapters independently addressable and reversible.

**Exit:** adapter promotion requires held-out quality, capability-preservation, privacy and safety gates.

## 15. Performance and resource policy

Target the current 16 GB RAM / Core i5-12500H-class Windows laptop. This is a design constraint, not a performance guarantee.

- Start with the installed Qwen3.5 4B APEX tag.
- One local inference request at a time initially; serialize requests across APEX and shared AIE model consumers.
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
4. Whether APEX is allowed to auto-start the existing AIE/SENTINEL providers or only connect when they are already running.
5. How SENTINEL exposes its read-only data contract without coupling APEX to its dashboard or private modules.
6. Exact model tag/prompt version management and whether the current user Modelfile is copied into repository configuration unchanged.
7. Retention durations and user controls for each memory/event class.
8. Voice and additional perception opt-ins.

No implementation phase may silently resolve these choices by introducing a new UI, data store, model router or policy engine.

## 19. First implementation milestone

The first coding milestone after this planning branch should be **Phase 1 — Headless APEX host foundation**.

It should deliver a small, testable local host with:
- APEX identity/profile contract.
- Ollama API connection to the already-installed `APEX` model tag.
- Thinking disabled by default at request level.
- Streaming chat/session handling.
- Runtime self-inspection and truthful capability manifest.
- Existing AIE model adapter/router reuse.
- No SENTINEL UI changes, no new desktop UI, no action execution and no parallel memory store.

Only after Phase 1 passes should Phase 2 connect live Windows observations.
