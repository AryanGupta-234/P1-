# AIE Architecture Spotlight

> Current project truth. Read before implementation and update with every milestone change.

**Last updated:** 2026-10-11 | **Integration branch:** `dev` | **Active focus:** M0/M1 Windows perception + M1.5 diagnostics | **Platform:** Windows 10/11

## North star
Build persistent personal intelligence that observes explicitly permitted signals, models context, reasons about goals, learns reusable skills and executes scoped actions safely. AGI remains a research objective, not a capability claim.

## System map
```text
                    COGNITIVE CONTROL PLANE
           Goals · Context · Reasoning · Planning · Model Router
                              |
      +-----------------------+-----------------------+
      |                       |                       |
   PERCEPTION                MEMORY                LEARNING
 Screen/UIA/Browser      Working/Episodic        Feedback/Skills
 ETW/Event Log           Semantic/Procedural     Evaluation
 Network/System          Provenance/TTL          Consolidation
      |                       |                       |
      +-----------------------+-----------------------+
                              |
                        POLICY BROKER
            Identity · Capabilities · Risk · Budgets
                              |
                     CONTROLLED EXECUTION
                              |
                     OUTCOME VERIFICATION
                              |
                         AUDIT / REVIEW
     Local-first runtime <--- explicit gateway ---> Optional cloud models
```

## Hard boundaries
1. Perception providers are read-only and emit observations, never actions.
2. Every event carries source, timestamp, host, schema version, sensitivity and provenance.
3. Observed facts and inferred hypotheses remain distinct.
4. Models cannot grant themselves capabilities or alter policy.
5. All OS actions pass through a policy broker and least-privilege executor.
6. Cloud egress is opt-in per task, minimized and auditable.
7. User can pause observation and inspect/export/delete retained data.
8. Windows only. No Linux/WSL providers.
9. Browser collection is explicit and limited to needed playback/performance signals; never collect passwords, cookies, form content or arbitrary page text.
10. Destructive, privileged, externally visible or difficult-to-reverse actions require approval. Low-risk autonomous actions must be pre-authorized, allowlisted, budgeted and verified.

## Current capability state
**Foundation present:** Python package/CLI, versioned event contract, SQLite store, read-only Windows inventory, best-effort process reconciliation, provider interface, hardware/model selection utilities.

**Integrated on dev:** deterministic video-buffering triage; bounded read-only network sampling; temporal event correlation; an opt-in MV3 Chrome/Edge playback observer prototype with a strict Windows native-messaging host; and a read-only foreground-window transition observer. Window titles are not collected by default. Monitoring defaults to off and collects HTML video playback/performance counters only. The network provider is now wired into the observer CLI with a default 15-second cadence (configurable from 5–300 seconds) and a --no-network opt-out. DNS probes use a single-flight guard so a stuck resolver cannot accumulate worker threads. The network provider samples interface counters, TCP connection-establishment latency to a private gateway and two public endpoints, and DNS resolution timing; this is not packet RTT and it does not measure sustained stream throughput. The correlator preserves connect latency as distinct evidence and leaves packet loss/throughput unknown when they were not measured. These are telemetry building blocks, not a live browser monitor, and no fixes are executed.

**Not implemented:** ETW subscriptions, Event Log provider, per-process resource sampling, native-host registration/real-browser end-to-end validation on the target desktop, Windows Graphics Capture and UI Automation control tree capture, full context graph, model gateway, persistent memory layers, policy broker, sandboxed executor, autonomous remediation or assistant dashboard.

## Immediate engineering sequence
1. Verify CI after foreground observer integration on Python 3.11/3.12.
2. Add CPU, memory and I/O deltas for foreground processes.
3. Add explicit pause/retention controls and user-visible observation status.
4. Add Windows UI Automation metadata for selected controls with per-app opt-in.
5. Correlate browser, foreground-app and network events into user task context.
6. Integrate the local Ollama adapter; optional cloud only through explicit egress policy.
7. Build capability manifests, policy broker, sandbox, audit and verification.
8. Implement persistent memory, feedback and held-out generalization evaluation.

## Definition of done
Feature complete = implementation + tests + documented limits + privacy/security review + validation evidence. Never claim CI or Windows validation without an actual passing run.

## Keep this page accurate
Update this file and `docs/ROADMAP.md` in every implementation PR. Add ADRs for lasting design changes and record exact validation environment and result.
