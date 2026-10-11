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

**Foundation:** Python package/CLI, versioned event contract, SQLite store, read-only Windows host/process inventory, snapshot reconciliation, provider interface, hardware profile and model policy.

**Perception providers:** bounded network telemetry; privacy-aware foreground-window/process sampling; opt-in allowlisted UI Automation structure; opt-in metadata-only Application/System Event Log reader. The latter two are disabled by default. The browser MV3 extension and native-messaging host report HTML video playback/performance counters only.

**Intelligence:** temporal browser/foreground/network correlation, buffered-ahead/playback-progress video diagnosis, deduplicated live diagnostic suggestions, local user feedback, local Ollama model routing and explicitly enabled OpenAI-compatible HTTPS inference.

**Governance:** global observer pause/resume, retention pruning, and a default-deny capability policy prototype. Policy decisions do not execute actions.

**Still pending:** target-desktop Chrome/Edge/native-host/UIA/Event Log validation; ETW and richer system telemetry; Windows Graphics Capture; centralized event/context bus; evaluated memory consolidation; cloud egress gateway; executor, sandbox, rollback and verified autonomous remediation; desktop/tray UI.

## Immediate engineering sequence
1. Verify CI after foreground observer integration on Python 3.11/3.12.
2. Add CPU, memory and I/O deltas for foreground processes.
3. Add explicit pause/retention controls and user-visible observation status.
4. Add Windows UI Automation metadata for selected controls with per-app opt-in.
5. Correlate browser, foreground-app and network events into user task context.
6. Integrate the local Ollama adapter; optional cloud only through explicit egress policy.
7. Build capability manifests, policy broker, sandbox, audit and verification.
8. Implement persistent memory, feedback and held-out generalization evaluation.

## Latest validation evidence
- GitHub Actions Windows CI run [#206](https://github.com/AryanGupta-234/P1-/actions/runs/38118517008) passed on commit `8ea5f937` with Python 3.11 and 3.12, Ruff, browser JavaScript syntax checks and pytest.
- This CI validates code on hosted Windows runners. It does not validate installation/permissions against the user's actual Chrome/Edge profile or local desktop UIA tree.

## Definition of done
Feature complete = implementation + tests + documented limits + privacy/security review + validation evidence. Never claim CI or Windows validation without an actual passing run.

## Keep this page accurate
Update this file and `docs/ROADMAP.md` in every implementation PR. Add ADRs for lasting design changes and record exact validation environment and result.
