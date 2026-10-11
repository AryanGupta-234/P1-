# AIE Architecture Spotlight

> Current project truth. Read before implementation and update with every milestone change.

**Last updated:** 2026-10-11 | **Integration branch:** `dev` | **Active focus:** Windows perception, live diagnostics and cognitive core | **Platform:** Windows 10/11 only

## North star
Build persistent personal intelligence that observes explicitly permitted signals, models context, reasons about goals, learns reusable skills and executes scoped actions safely. AGI remains a research objective, not a capability claim.

## Architecture
```text
                  COGNITIVE CONTROL PLANE
          Goals · Context · Reasoning · Planning · Model Router
                             |
      +----------------------+-----------------------+
      |                      |                       |
   PERCEPTION               MEMORY                LEARNING
 Screen/UIA/Browser     Working/Episodic         Feedback/Skills
 ETW/Event Log          Semantic/Procedural      Evaluation
 Network/System        Provenance/TTL            Consolidation
      |                      |                       |
      +----------------------+-----------------------+
                             |
                       POLICY BROKER
             Identity · Capabilities · Risk · Budgets
                             |
                    CONTROLLED EXECUTION
                             |
                    OUTCOME VERIFICATION
                             |
                       AUDIT / REVIEW
 Local-first inference <--- explicit egress gate ---> Optional cloud inference
```

## Hard boundaries
1. Perception providers are read-only and emit observations, never actions.
2. Events carry source, timestamp, host, schema version, sensitivity and provenance.
3. Observed facts and inferred hypotheses remain distinct.
4. Models cannot grant themselves capabilities or alter policy.
5. All OS actions must pass through a policy broker and least-privilege executor.
6. Cloud egress is opt-in per request, minimized and auditable.
7. Users can pause observation and inspect/export/delete retained data.
8. Windows only. No Linux/WSL providers.
9. Browser observation is opt-in and limited to playback/performance signals; no passwords, cookies, form values or arbitrary page text.
10. UIA is off by default, process-allowlisted and structural-only; no control text/value/password extraction.
11. Window titles are not collected by default.
12. Destructive, privileged, externally visible or difficult-to-reverse actions require approval.

## Integrated capabilities on dev

**Windows perception**
- Read-only host/process/application/service/scheduled-task/network-interface inventory.
- Best-effort process lifecycle observations.
- Foreground app transitions and throttled active-process CPU, RSS, thread and I/O samples.
- Bounded network interface counters, TCP connection-establishment latency and DNS resolution timing.
- Opt-in metadata-only Application/System Event Log reader, wired into the observer runtime. It skips historical backlog on startup and excludes message text, XML and Security logs.
- Opt-in, allowlisted UI Automation structural snapshots with node/depth/time bounds.
- Per-user pause/resume and age-based event pruning.

**Browser and diagnostics**
- Opt-in MV3 Chrome/Edge HTML-video observer and strict Windows native-messaging host.
- Local event persistence and temporal browser/foreground/network correlation.\n- Indexed time/source/type querying and privacy-safe activity sessions across all collected event categories (`aie activity`).
- Buffer starvation, buffered-but-not-advancing playback and evidence-backed resource/network hypotheses.
- Live deduplicated diagnostic suggestions with evidence references; suggestions are not actions.
- User outcome feedback linked to diagnostic event IDs.

**Cognitive core**
- Provider-independent model request/response contracts.
- Local Ollama client and hardware-aware selection of already-installed models; no implicit model pulls.
- Optional OpenAI-compatible HTTPS provider requiring explicit `--provider cloud --allow-cloud-egress`.
- Cloud requests contain only the prompt explicitly supplied to `aie ask`; observer telemetry is not automatically attached.

**Governance**
- Default-deny capability manifests, low-risk autonomy allowlists, approval gates, parameter validation and rate limits.
- Global pause/resume, local retention pruning and outcome-feedback capture.
- Policy decisions do not execute actions. No OS executor or autonomous remediation is implemented.

## Pending validation and implementation
- Full latest Windows CI run for Event Log runtime wiring and its runtime-level persistence test.
- Target-desktop Chrome/Edge extension/native-host installation and live playback validation.
- Target-desktop UIA and Application/System Event Log permission/behavior validation.
- ETW subscriptions and higher-fidelity process telemetry.
- Windows Graphics Capture (screenshots), still intentionally separate from UIA structure.
- Unified event bus, semantic task/session context and persistent semantic/procedural memory.
- Evaluated learning from user-confirmed feedback; no automatic model retraining yet.
- Cloud egress gateway/redaction policy and model request budgets.
- Sandboxed OS executor, rollback, postcondition verification and actual autonomous remediation.
- Windows tray/desktop assistant UI.

## Immediate engineering sequence
1. Validate latest Event Log runtime integration on Windows CI.
2. Validate browser/native-host, UIA and Event Log sampling on the target Windows desktop.
3. Add ETW process telemetry with coverage and buffer-loss reporting.
4. Implement a unified event/context query API and session model.
5. Add persistent memory consolidation with retrieval and forgetting evaluation.
6. Connect policy decisions to a proposal queue and append-only audit.
7. Implement an executor only after sandboxing, least privilege, kill switch, rollback and verification.
8. Add a tray/desktop interface after core APIs stabilize.

## Validation policy
Hosted CI proves code behavior on GitHub's Windows runners; it does not prove installation or runtime behavior on the user's desktop. Mark target-desktop validation complete only after running those checks on the actual Windows machine.

## Definition of done
Feature complete = implementation + tests + documented limits + privacy/security review + validation evidence. Never claim a capability is live on the user's PC based solely on hosted CI.

## Keep this page accurate
Update this file and `docs/ROADMAP.md` with every implementation increment. Add ADRs for lasting design changes and record exact validation evidence.
