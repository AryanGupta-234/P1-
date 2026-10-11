# AIE Architecture Spotlight

> Always-current project orientation. Read before coding and update in the same change as milestone progress.

**Last updated:** 2026-10-11 | **Active phase:** Foundation + Windows Environment Observer | **Milestones:** M0/M1 | **Platform:** Windows 10/11 only

## North star
Build persistent, adaptive intelligence that observes permitted signals, forms/revises contextual models, reasons about goals, learns reusable skills and executes scoped actions safely. AGI is a research objective, not a capability claim.

## System map
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

 Local-first runtime <--- explicit gateway ---> Optional cloud models
```

## Hard boundaries
1. Collectors are read-only; they emit observations, never execute proposals.
2. Events are versioned and include source, timestamp, host, sensitivity and provenance.
3. Observations and inferred context are separate; hypotheses never masquerade as facts.
4. No agent calls OS tools directly; future actions pass through a capability broker.
5. Cloud routing is opt-in per task with data minimization and explicit egress policy.
6. Users can pause observation and inspect/delete retained data.
7. Windows only. Do not add Linux/WSL providers.
8. Documented ETW/Event Log first. No unsigned driver, stealth collection, credential extraction or security-control bypass.

## Current spotlight: M0/M1
**In progress:** package/CLI, normalized event contract, local SQLite store, read-only inventory, process-state reconciliation, future-ETW provider boundary, deterministic tests.

**Not implemented:** ETW subscriptions, driver, application automation, context reasoning, model router, memory consolidation, autonomous execution, cloud infrastructure.

## Definition of done
- Runs without an LLM or internet.
- Best-effort process change detection; not represented as full kernel telemetry.
- Events persist across restarts.
- Inventory/status CLI, deterministic tests, privacy boundary and graceful degradation.
- Observer has no action-execution capability.

## Keep this page accurate
After every task, update this page and ROADMAP.md. Add an ADR for lasting design changes and record exact validation results.

## Next action
Validate on Windows 10/11, add CI, then prototype opt-in ETW process telemetry with bounded buffers and explicit session lifecycle.
