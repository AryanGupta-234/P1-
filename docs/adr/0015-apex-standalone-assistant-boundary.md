# ADR-0015: APEX as a standalone Windows assistant

- **Status:** Accepted for planning; implementation pending
- **Date:** 2026-11-05
- **Branch:** `feature/apex-standalone-assistant-plan`
- **Decision owners:** AIE project maintainers

## Context

The project needs a user-facing assistant named APEX that combines natural conversation, user profile and memory, whole-Windows diagnostics, system observation and controlled automation. The current repository contains separate AIE cognitive/perception/policy foundations and a distinct SENTINEL Windows diagnostics/performance application. SENTINEL already has its own UI and background runtime. APEX must not become a new panel or chat mode inside that UI.

The user also runs an Ollama model tag named `APEX`, based on Qwen3.5 4B. That tag and its Modelfile configure local inference; they do not provide desktop lifecycle, Windows telemetry or tool execution by themselves.

The repository already has reusable model contracts/adapters/router, memory, planning/orchestration, policy and audit components, Windows observers, and a Windows tray implementation. A new APEX application must avoid duplicating those capabilities.

## Decision

1. APEX is a separate Windows desktop product and assistant identity.
2. SENTINEL remains an independent observation/diagnostics provider. Its dashboard and UI are not modified to host APEX.
3. APEX uses the existing AIE `dev` infrastructure through stable contracts/adapters wherever compatible: model routing, Ollama transport, event/observation providers, memory, planning, policy, execution and audit.
4. APEX receives its own host lifecycle, conversational session layer, profile, identity prompt and future desktop shell.
5. APEX's self-knowledge comes from a live runtime/capability manifest, not from prompt claims.
6. The preferred user salutation defaults to `sir` because the user explicitly requested it. The user's display name and other personal profile fields are gathered through explicit onboarding or editing, not inferred by scraping Windows.
7. The user's installed Ollama model tag `APEX` is the initial local inference target. The application uses Ollama's loopback API and request-level thinking controls; normal conversation defaults to thinking off. The app does not require `ollama run` in a terminal.
8. Unified memory reuses AIE's existing memory store and provenance/sensitivity contracts. No parallel durable APEX memory database is created. SENTINEL data is consumed through a provider adapter; direct writes to SENTINEL's private database are prohibited.
9. All Windows mutation remains behind the existing AIE capability policy, approval, executor, audit and verification path. The model cannot grant itself permissions or call unrestricted PowerShell.
10. Desktop UI implementation is intentionally deferred until the headless host and IPC/API contracts are stable.

## Architecture

```text
APEX Desktop (future, independent)
        |
        | authenticated local IPC
        v
APEX Host / Conversation / Context / Self-inspection
        |
        +--> AIE model contract + local Ollama router
        +--> AIE memory/profile adapter
        +--> AIE observation/event providers
        +--> SENTINEL read-only provider adapter
        +--> AIE planning/orchestration
        +--> AIE policy / approval / executor / audit
```

## Consequences

### Positive

- APEX can evolve as a distinct assistant without coupling to SENTINEL's dashboard.
- Existing AIE investments are reused rather than copied.
- The assistant can truthfully report which tools and providers are connected.
- Unified memory avoids parallel databases and inconsistent user facts.
- Local-first operation and explicit policy remain consistent with AIE architecture.
- Desktop UI choices can be made later without changing the assistant core.

### Trade-offs

- Provider contracts and compatibility work are required before tool integration.
- APEX needs its own host lifecycle, IPC boundary, profile and desktop packaging.
- Existing SENTINEL data may require a read-only API adapter and migration review.
- Model latency and memory budgets must be measured on the target 16 GB Windows system.

## Rejected alternatives

- **Embed APEX into the SENTINEL dashboard:** rejected because APEX is a separate assistant/product and must have its own lifecycle and future UI.
- **Build a second full Windows observer:** rejected because it duplicates AIE/SENTINEL sensors and causes inconsistent evidence.
- **Create a second memory database:** rejected because it fragments user profile, history and learned preferences.
- **Give the model unrestricted PowerShell/admin access:** rejected because prompts and model outputs are not an authorization boundary.
- **Treat the Modelfile as the complete assistant:** rejected because it only configures the model; host runtime, telemetry, tools, memory and execution must be implemented in application code.
- **Build the UI before the runtime:** rejected because UI should consume stable host contracts, not define system architecture.

## Validation required

- Verify APEX host functions without opening SENTINEL UI.
- Verify Ollama API connection and thinking-off behavior.
- Verify live capability manifest matches registered and healthy tools.
- Verify unified memory reuses existing AIE store.
- Verify read-only Windows evidence has timestamps, provenance and freshness.
- Verify unknown tools and unauthorized mutations are denied.
- Verify desktop launch does not require a visible command prompt.
