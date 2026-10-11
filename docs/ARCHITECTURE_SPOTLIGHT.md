# AIE Architecture Spotlight

> Always-current project orientation. Read before coding and update in the same change as milestone progress.

**Last updated:** 2026-10-11 | **Active phase:** Foundation + first diagnostic slice | **Milestones:** M0/M1, diagnostic prototype | **Platform:** Windows 10/11 only

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
 Browser opt-in         Evidence/provenance      Benchmarks
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
4. No agent calls OS tools directly; all future actions pass through a capability broker.
5. Cloud routing is opt-in per task with data minimization and explicit egress policy.
6. Users can pause observation and inspect/delete retained data.
7. Windows only. Do not add Linux/WSL providers.
8. Documented ETW/Event Log first. No unsigned driver, stealth collection, credential extraction or security-control bypass.
9. Browser observation must be explicitly enabled and limited to playback/performance signals; never collect passwords, cookies, form contents or arbitrary page text.
10. Autonomous mode is bounded by capabilities, risk policy, budgets, audit and post-action verification.

## Current spotlight
**Foundation present on main:** normalized event contract, local SQLite event store, read-only host/process snapshot observer, CLI, package and initial tests.

**Current feature branch:** `feat/video-intelligence-foundation`. Added a deterministic video-buffering triage module and synthetic tests. It distinguishes insufficient throughput, packet loss, latency and local decode/render pressure when enough telemetry is supplied. It returns hypotheses only; no browser observer, screen capture, model reasoning or remediation executor is implemented yet.

## Not implemented
ETW subscriptions, Event Log provider, browser extension/native bridge, continuous screen perception, network sampler, context reasoning, model router, memory consolidation, policy broker, autonomous execution and cloud infrastructure.

## Definition of done for the current diagnostic slice
- Runs as a pure function without an LLM, network or Windows APIs.
- Does not infer a cause from a single stall or missing telemetry.
- Keeps unknown metrics distinct from measured zero.
- Returns evidence and clearly caveated heuristic confidence.
- Has deterministic synthetic tests.
- Has no action-execution capability.

## Keep this page accurate
After every task, update this page and ROADMAP.md. Add an ADR for lasting design changes and record exact validation results. Do not mark validation complete until run on the target Windows environment or CI.

## Next action
Add Windows CI and run the full suite. Then implement an opt-in browser playback telemetry bridge and bounded Windows network sampler; keep all collectors read-only. Design the policy broker before enabling any remediation.
