# AIE Architecture Spotlight

> Always-current project orientation. Read before coding and update in the same change as milestone progress.

**Last updated:** 2026-10-11  
**Active phase:** Windows Environment Intelligence  
**Active milestone:** M1 — Environment Observer (user-mode inventory + event pipeline)  
**Platform:** Windows 11 x64 only  
**Development target:** ASUS Vivobook X1605ZA class · 16 GB RAM · Intel Core i5-12500H class

## North star
Build persistent, adaptive intelligence that observes permitted signals, forms/revises contextual models, reasons about goals, learns reusable skills and executes scoped actions safely. AGI is a research objective, not a capability claim.

## Architecture map
```text
                   COGNITIVE CONTROL PLANE
             Goals · Context · Reasoning · Planning
                              |
       +----------------------+----------------------+
       |                      |                      |
   PERCEPTION               MEMORY                LEARNING
 Windows providers      Episodic/Semantic       Feedback/Skills
 ETW/Event Log          Procedural/Goals        Evaluation
       |                      |                      |
       +----------------------+----------------------+
                              |
                       POLICY BROKER
             Identity · Capabilities · Risk · Budgets
                              |
                    SANDBOXED EXECUTION
                              |
                     OUTCOME VERIFICATION
                              |
                            AUDIT

 Local Observer / SQLite <--- explicit gateway ---> Optional cloud reasoning
 Local Ollama: Qwen 3B / Qwen 7B / Nomic embeddings
```

## Hardware-aware operating policy
- Routine local reasoning: `qwen2.5:3b-instruct`.
- Complex local reasoning: `qwen2.5:7b-instruct` only when installed and currently available RAM is at least 7.5 GiB.
- Embeddings: `nomic-embed-text:latest`.
- Current host sample showed approximately 5.1 GB available physical RAM. The 7B path should therefore fall back to 3B until live memory headroom is higher.
- No automatic model pulls. No cloud fallback without an explicit future data-egress policy.
- One local inference at a time initially; monitor context/KV-cache memory before changing concurrency.
- Preserve VBS, HVCI, Kernel-mode Hardware-enforced Stack Protection and App Control. Do not weaken platform protections to make AIE work.

See [HARDWARE_PROFILE.md](HARDWARE_PROFILE.md) for the sanitized host baseline.

## Implemented now
- Versioned Pydantic observation events and local SQLite persistence.
- Read-only Windows host/process inventory and process baseline/delta reconciliation.
- Best-effort installed application metadata from uninstall registry keys.
- Read-only Windows service inventory.
- Network interface state inventory without IP/MAC collection.
- Scheduled-task names/status through read-only `schtasks /query`.
- Periodic CPU, memory and system-volume resource observations; batch SQLite writes and JSONL export.
- Read-only ETW provider catalog discovery through `logman query providers` (catalog only; no trace session is started).
- Hardware runtime probe and local loopback-only Ollama model discovery/model selection.
- Windows CI workflow plus synthetic tests (CI execution still needs confirmation).

## Not implemented yet
- ETW real-time subscriptions / higher-fidelity kernel-originated event ingestion (only provider catalog discovery exists).
- Windows Event Log allowlist and real-time subscriptions.
- Continuous service/network/task/application change events.
- Executable path/signature discovery and application adapter registry.
- UI Automation client, app-specific automation adapters and action execution.
- Context reasoning, actual Ollama chat/embedding invocation, memory consolidation and cloud gateway.
- Policy broker, sandboxed actions and autonomous workflows.
- Custom kernel driver (not an initial milestone; separate signed-driver research only if ETW cannot meet a demonstrated need).

## Hard architectural boundaries
1. Collectors are read-only; they emit observations, never execute proposals.
2. Events distinguish observed evidence from derived hypotheses.
3. No agent calls OS tools directly; future actions pass through a capability broker.
4. Cloud routing is opt-in per task with data minimization and explicit egress policy.
5. User can pause observation and inspect/delete local data.
6. Windows only. No Linux/WSL code paths.
7. Documented ETW/Event Log first. No unsigned driver, stealth collection, credential extraction or security-control bypass.
8. Do not capture keystrokes, screenshots, clipboard, mic/camera or arbitrary app content by default.

## Active implementation issue
[Issue #3 — Windows Observer validation and ETW process telemetry](https://github.com/AryanGupta-234/P1-/issues/3)

## Next actions — priority order
1. Run Windows CI and resolve every failure.
2. Add service/network state deltas and retention controls.
3. Prototype opt-in ETW process telemetry with bounded buffers and explicit session lifecycle.
4. Add allowlisted Windows Event Log providers.
5. Add app compatibility discovery and UIA read-only tree inspection.
6. Only then begin user-approved application actions behind a policy broker.

## Spotlight maintenance
At each implementation increment: update this file, update [ROADMAP.md](ROADMAP.md), add/adjust tests, and record actual validation. Never mark a task DONE based only on writing its interface.
