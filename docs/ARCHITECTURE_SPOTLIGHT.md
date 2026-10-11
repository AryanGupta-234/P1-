# AIE Architecture Spotlight

> Current project truth. Read before implementation and update with every milestone change.

**Last updated:** 2026-10-11 | **Current feature branch:** `feat/agent-orchestration-core` | **Target integration:** `dev` | **Platform:** Windows 10/11 only

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

## Existing dev baseline and current feature-branch additions

**Windows perception**
- Read-only host/process/application/service/scheduled-task/network-interface inventory.
- Best-effort process lifecycle observations.
- Foreground app transitions and throttled active-process CPU, RSS, thread and I/O samples.
- Opt-in bounded systemwide process CPU/RSS/thread/I/O snapshots, reporting top consumers only.
- Opt-in kernel ETW process start/stop/rundown observer with bounded queue and explicit elevated-token requirement.
- Bounded network interface counters, TCP connection-establishment latency and DNS resolution timing.
- Opt-in metadata-only Application/System Event Log reader, wired into the observer runtime. It skips historical backlog on startup and excludes message text, XML and Security logs.
- Privacy-safe observer health telemetry with per-provider latency, success/error, consecutive-failure and event-loss accounting; health records exclude exception text and provider payloads.
- User-controlled privacy controls: `aie health` inspection, JSONL export with sensitive-data opt-in, and confirm-only delete-all after observation pause.
- Opt-in, allowlisted UI Automation structural snapshots with node/depth/time bounds.
- Per-user pause/resume and age-based event pruning.

**Browser and diagnostics**
- Opt-in MV3 Chrome/Edge HTML-video observer and strict Windows native-messaging host.
- Local event persistence and temporal browser/foreground/network correlation.
- Indexed time/source/type querying and privacy-safe activity sessions across all collected event categories (`aie activity`).
- Buffer starvation, buffered-but-not-advancing playback and evidence-backed resource/network hypotheses.
- Live deduplicated diagnostic suggestions with evidence references; suggestions are not actions.
- User outcome feedback linked to diagnostic event IDs.

**Cognitive core**
- Provider-independent model request/response contracts.
- Explicit per-request context packaging from user memories and safe activity timelines; no automatic context injection.
- Local Ollama client and hardware-aware selection of already-installed models; no implicit model pulls.
- Optional OpenAI-compatible HTTPS provider requiring explicit `--provider cloud --allow-cloud-egress`.
- Cloud/remote-Ollama requests pass through a centralized local egress gateway. Only explicitly selected context is attached; activity, memory and session context require separate confirmation, sensitive memory is blocked, high-confidence credential patterns are redacted, payload size is bounded, and a metadata-only local audit record is written. Observer telemetry is never automatically attached.
- Bounded declarative plans use typed steps, explicit success criteria and dependencies; model-backed drafting is optional, local-Ollama by default, exact-goal preserving, schema-validated and restricted to caller-allowlisted capability IDs.
- Persisted task orchestration uses SQLite compare-and-swap versions and append-only lifecycle events. The engine advances dependency-ready steps through injected handlers, pauses for approval/input, and requires an explicit positive assertion for verify steps. Local model reasoning receives only the plan and bounded completed-step summaries; no tools are exposed to the model.

**Context and memory**
- A bounded synchronous unified event bus fans normalized observations to the durable SQLite store and optional JSONL sink before downstream diagnostics/correlation.
- Generic rule-driven temporal correlation can relate explicit event types within bounded time/host windows without asserting causality.
- Freshness-weighted evidence assessment and a narrow explicit contradiction detector are available as context-layer primitives; heuristic weights are not calibrated probabilities.
- Explicit user-controlled working sessions persisted locally; session metadata can be attached to model requests only on request.
- Separate local SQLite memory store for explicit user-authored working/episodic/semantic/procedural/prospective records.
- Source-event provenance validation, TTL, supersession history, deletion, lexical retrieval and optional local Ollama embedding/cosine retrieval.
- Embeddings are keyed by memory ID and model; deletion/expiry removes associated vectors.
- Sensitive memories are excluded from listing, retrieval and embedding by default; explicit indexing is available with a warning. Review-only consolidation proposals are generated from bounded lexical/tag similarity. A separate confirmed two-source merge creates a new record, retains both lineage links and every source-event/source-task-run reference, cannot lower sensitivity, raise confidence or extend expiry, and leaves source versions superseded.
- Completed task runs with a positive explicit verification step can produce deterministic procedural-skill candidates. Action-bearing candidates require successful audited execution receipts and a verification step dependent on each action. The user must preview and separately confirm a save; procedural-skill records are sensitive by default and do not train a model. Memory text and vectors are local SQLite data, not encrypted at the application layer; credentials must not be stored.

**Governance**
- Default-deny user-managed capability manifests, low-risk autonomy declarations, approval gates, bounded flat parameters and rate limits.
- Typed dry-run executor remains available for non-mutating policy checks.
- A registered adapter executor now requires an approved ledger proposal, valid audit-chain integrity, current policy re-evaluation, the positive execution-enable marker, an absent kill switch and a matching trusted adapter.
- The only built-in mutating adapter is `windows.settings.open`, which dispatches one of seven fixed `ms-settings:` URIs. It cannot alter settings, invoke a shell, launch arbitrary processes, write files or use the network. It is disabled unless a user creates and enables its manifest.
- Each attempted execution is recorded once in the SHA-256 chained policy ledger. URI dispatch is not treated as postcondition verification; a separate verify step requires an explicit user assertion.
- The task engine persists plan/run/step state and its event journal locally. Pause/cancel apply between handler invocations; in-flight external handlers are not force-killed and interrupted running steps fail closed for manual review.
- Approval and execution are separate operations. The execution gate remains disabled by default; no autonomous remediation is enabled.
- These orchestration/execution additions currently live on `feat/agent-orchestration-core`; they are not represented as merged into `dev` until the pull request is reviewed and integrated.

## Pending validation and implementation
- Windows CI run [#581](https://github.com/AryanGupta-234/P1-/actions/runs/38123875398) passed on Python 3.11 and 3.12, including the current observer-health, ETW lifecycle/loss, task-session, dry-run governance and privacy-control tests.
- Target-desktop Chrome/Edge extension/native-host installation and live playback validation.
- Target-desktop UIA and Application/System Event Log permission/behavior validation.
- Higher-fidelity ETW telemetry beyond process lifecycle events (optional thread/file/network categories and provider-specific coverage reporting).
- Windows Graphics Capture (screenshots), still intentionally separate from UIA structure.
- Unified event bus and semantic task/session interpretation.
- Embedding retrieval quality evaluation, semantic contradiction resolution and forgetting/regression evaluation.
- Evaluation of procedural-skill quality and transfer; skill induction currently creates reviewed local records only and never retrains a model.
- Cloud egress gateway/redaction policy and model request budgets.
- OS-process sandboxing, rollback and automatic recovery for interrupted handlers.
- Postcondition verification beyond explicit human checks; the fixed Settings URI adapter reports dispatch, not verified application state.
- Tool-selection/plan-quality evaluation and held-out task-family benchmarks.
- Windows tray/desktop assistant UI.

## Immediate engineering sequence
1. Validate browser/native-host, UIA, Event Log and ETW elevation/behavior on the target Windows desktop.
2. Extend ETW from process lifecycle into explicitly selected thread/file/network categories with provider-specific coverage reporting.
3. Add evidence freshness, contradiction handling and calibrated confidence to context/session interpretation.
4. Add persistent memory consolidation with retrieval/forgetting evaluation and reviewed skill induction.
5. Add process isolation and adapter-specific postcondition verifiers before expanding the narrow Windows Settings adapter.
6. Evaluate planner quality, task outcomes and memory integration without learning from unverified or model-generated success claims.
7. Add tray/desktop controls after the core APIs stabilize.

## Validation policy
Hosted CI proves code behavior on GitHub's Windows runners; it does not prove installation or runtime behavior on the user's desktop. Mark target-desktop validation complete only after running those checks on the actual Windows machine.

## Definition of done
Feature complete = implementation + tests + documented limits + privacy/security review + validation evidence. Never claim a capability is live on the user's PC based solely on hosted CI.

## Keep this page accurate
Update this file and `docs/ROADMAP.md` with every implementation increment. Add ADRs for lasting design changes and record exact validation evidence.
