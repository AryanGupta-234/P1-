# AIE Architecture Spotlight

> Always-current project orientation. Read before coding and update in the same change as milestone progress.

**Last updated:** 2026-10-17  
**Active phase:** Environment Intelligence + Cognitive Foundations  
**Active milestone:** M2 — Context Intelligence (durable evidence-backed environment projection; Windows validation remains open)  
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
- Explicit SQLite retention APIs: delete events older than a timezone-aware cutoff or retain only the newest N events; deterministic ordering and validation tests.
- Generic in-memory snapshot delta engine with baseline, added, removed and changed evidence events; duplicate identities fail closed.
- Synthetic unit and Windows-provider integration tests cover baseline creation and service-state transition emission.
- Windows service, network interface, scheduled-task and installed-application state deltas; low-frequency inventory sampling is bounded to 30-second intervals, independently of process/resource polling.
- Fixed Windows System Event Log allowlist: Service Control Manager 7036, Kernel-Power 42, and Kernel-General 12/13. Seeds from the newest 100 allowlisted events, then pages forward by System log record ID (up to 500 new events per 30-second poll). It stores record IDs/timestamps and limited service state fields, discards rendered messages, and uses deterministic IDs for idempotent replay. The latest System record ID is checkpointed in SQLite only after the event batch is persisted; an interruption before checkpoint commit causes safe replay rather than cursor advancement. Cursor state therefore survives observer restarts.
- CLI retention command: `aie prune --older-than-days N` or `aie prune --keep-latest N`.
- Complete chronological JSONL export: `aie export-events PATH`; live observation can also write JSONL with `aie observe --jsonl PATH`.
- Cooperative pause/resume: `aie observe --pause-file PATH` pauses while the file exists; removing it resumes without consuming active observation duration.
- Collector failures are isolated and persisted as sanitized health events; recovery is recorded after a later successful sample.
- Fault-isolated observer loop: process and low-frequency state collector failures are persisted as sanitized `observer.collector_error` events; a later successful sample emits `observer.collector_recovered`.
- Cooperative pause/resume through `aie observe --pause-file PATH`: while the file exists sampling pauses; removing it resumes observation, and paused time does not consume the requested active duration.
- Read-only ETW provider catalog discovery through `logman query providers`.
- Opt-in `aie etw-capture PATH.etl --duration N` starts a bounded `Microsoft-Windows-Kernel-Process` trace using Windows `logman`, refuses output overwrite, caps the ETL file at 256 MB by default, bounds ETW buffers (64 KB × 16–64 buffers by default), and always attempts to stop the named session on context exit. `tracerpt` XML can then be normalized with `aie etw-decode INPUT.xml OUTPUT.jsonl`; the streaming decoder clears parsed XML nodes to bound memory, accepts only Kernel-Process event IDs 1/2, records PID/parent PID and image basename, and deliberately discards command lines. Decoded events are assigned deterministic IDs and batch-imported into SQLite, so reprocessing the same trace is idempotent. `aie etw-decode` also reports `EventsLost` and buffer-loss counters when the tracerpt XML header exposes them; confirm those fields on real Windows traces. Schema validation and snapshot reconciliation remain pending.
- Entity-level baseline evidence for service, network-interface, scheduled-task and installed-application inventories; first-sample collection counts are not misrepresented as per-entity observations.
- Event-sourced environment projection (`aie/state_model.py`, `aie state`) replays retained observations into process-instance and inventory state. `aie context` renders a bounded factual packet with provenance, coverage and omission counts for downstream reasoning; it performs no inference. Versioned snapshots are stored separately from raw events; monotonic SQLite ingestion sequence ensures late imports are replayed. Process identity is `(host_id, PID, creation_time)`; PID reuse cannot close or mutate another instance. ETW start confirmation attaches only to an existing exact process instance. Explicit inventory removals are preserved, while absent evidence remains unknown. Coverage limitations and ignored malformed/ambiguous events are reported. Each process/entity retains at most the latest 64 unique evidence IDs; older references are dropped with an explicit `evidence_truncated` marker that survives snapshot serialization and is surfaced in context packets. Older snapshots without the marker load as not truncated. SQLite snapshot writes also enforce a 16 MiB UTF-8 payload ceiling; an oversized update is rejected before mutation and leaves the last valid snapshot intact. New writes store a SHA-256 digest in a companion integrity table; loads verify it and fail closed on corruption. Pre-integrity snapshots remain readable for migration compatibility. Each successful update retains one prior verified generation. `aie state --recover` restores that generation and incrementally replays later retained events; `--rebuild` remains the explicit full replay path.
- Conservative ETW process-start correlation: `aie correlate --since-minutes N` reads a bounded chronological SQLite history window, matches only same-host, same-PID, same-image observations whose process creation time is within a bounded tolerance of the ETW start timestamp, and persists deterministic derived evidence with both source event IDs. Re-running is idempotent. PID-only stop correlation is deliberately excluded because PID reuse makes it ambiguous.
- Hardware runtime probe and local loopback-only Ollama model discovery/model selection.
- `aie/ollama.py`: local-only synchronous Ollama `/api/chat` and `/api/embed` adapters; non-streaming chat, optional JSON/schema format, no tool-call execution, 1 MiB request and 4 MiB response caps, bounded timeout, cooperative cancellation checks, redirect blocking, proxy bypass, finite-JSON enforcement, embedding batch/count/finiteness/dimension validation. `aie ask` selects an already-installed routine/complex model through the live-memory policy; `aie embed` validates the installed embedding model and reports dimensions without exposing vectors. No model pulls or remote endpoints.
- Windows CI workflow plus synthetic tests (CI execution still needs confirmation).

## Not implemented yet
- Real-capture validation of the ETW XML schema, trace-loss accounting and reconciliation against user-mode snapshots.
- Windows-host validation of the persisted Event Log cursor, allowlist coverage and permissions.
- Real-time Windows Event Log subscriptions (current implementation is a bounded 30-second query of the fixed allowlist); validate the exact event payload schema on Windows.
- Native event-driven service/network/task/application subscriptions (current implementation uses 30-second snapshot reconciliation, not native event subscriptions).
- Dedicated end-to-end runtime tests and Windows-host validation for pause/resume, collector recovery, CPU overhead and event latency.
- Executable path/signature discovery and application adapter registry.
- App-specific automation adapters and action execution remain unimplemented. `aie uia-inspect` now provides a bounded, read-only Windows UIA tree inspection path: default 12 windows/250 nodes/depth 5/12 seconds, hard caps 40/1000/8/30 seconds, structural metadata only, no control names/text/values/password contents/screenshots/patterns, and no interaction methods. Native Windows framework/privilege validation remains open.
- Recovery evaluation across pruning/corruption edge cases, broader environmental state semantics, relationship modeling and synthetic projection evaluation. Explicit `aie compact-state --older-than-days N --max-terminal-records N` removes only excess old terminal process/entity records from the saved projection, retains recent/live records, records cumulative compaction metadata, and preserves the raw event log and ingest watermark. Per-entity evidence references are bounded at 64 IDs with explicit truncation metadata, and snapshot writes have a fail-safe 16 MiB payload ceiling. `aie state` persists a versioned projection and resumes by monotonic SQLite ingestion sequence; `aie context` emits bounded facts with provenance but does not reason over them. Initial process baseline coverage remains count-only.
- End-to-end local Ollama invocation against the target installation, Nomic live dimension confirmation, memory consolidation and cloud gateway.
- Full proposal orchestration, sandbox implementation, UIA adapters and autonomous workflows; a non-executing policy evaluator foundation is implemented.
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
1. Run Windows CI and resolve every failure; execute the observer and ETW synthetic tests.
2. Validate observer pause/resume, collector recovery, JSONL export and resource overhead on the target Windows host.
3. Validate ETW decoding against real Windows captures; confirm trace-loss counters and reconcile ETW events with process snapshots.
4. Validate the fixed Event Log allowlist and SQLite cursor recovery on Windows, then add real-time subscriptions and process/image correlation.
5. Add app compatibility discovery and UIA read-only tree inspection.
6. Validate incremental `aie state` checkpoint recovery and explicit `aie compact-state` behavior against real observer history; add environmental-state evaluation (a 16 MiB hard write ceiling is implemented). Validate local Ollama inference and Nomic dimensions before expanding the cognitive runtime.

## Spotlight maintenance
At each implementation increment: update this file, update [ROADMAP.md](ROADMAP.md), add/adjust tests, and record actual validation. Never mark a task DONE based only on writing its interface.


## Additional foundations implemented — 2026-10-16

- **Context ranking:** `aie prioritize` ranks projected state with deterministic recency, active/present and ETW-confirmation features. The score is retrieval priority, not calibrated confidence or truth.
- **Read-only cognition:** `aie think` assembles a bounded JSON evidence packet and calls only an eligible loopback Ollama model. `--include-memory` optionally adds matching non-sensitive user-created memories, explicitly distinguished from live observations. All packet strings are untrusted data; there is no tool/action channel.
- **Persistent memory:** explicit working/episodic/semantic/procedural/prospective records in SQLite, with provenance IDs, confidence, sensitivity, verification, tags, access count and optional TTL. Search excludes sensitive records by default. Corrections preserve immutable previous versions; JSONL export is explicit and sensitive export requires opt-in. TTL cleanup removes revision history too.
- **Policy foundation:** `aie.policy` is a non-executing evaluator. It requires exact action capabilities, verified targets, sandbox availability for writes, bounded action budgets and expiring approvals bound to the exact proposal digest. No UIA or OS action executor exists.

**Validation still outstanding:** all new tests are authored but have not been run. Windows-host validation, Ollama quality/latency, memory retrieval evaluation, policy adversarial evaluation and end-to-end recovery remain open.


## Persistent goal runtime — 2026-10-16

- `aie/goals.py` stores explicit user-directed goals and dependency-ordered steps in SQLite. The dependency graph is acyclic by construction because a new step can only depend on existing steps in the same goal.
- Step transitions enforce prerequisite completion. Completed/cancelled steps are terminal. A goal is automatically completed only when every step is completed; manual completion is rejected while work remains.
- Goal and step transitions are written to append-only `goal_history` for auditability. Pause/resume and abandonment are explicit state transitions.
- CLI supports `goal-add`, `goal-list`, `goal-show`, `goal-step-add`, `goal-step-update`, `goal-status`, and `goal-history`.
- `aie think --include-goals` optionally adds at most six active/paused goals and at most ten steps per goal to its bounded local context. The prompt explicitly distinguishes user plans from observations and memories. Planner drafts may be persisted for review, but no suggested step is added to the goal without explicit acceptance and no goal step is executed.

**Plan suggestions:** `aie/planning.py` builds a bounded prompt from user goal data and validates Ollama JSON against a strict schema. Dependencies can only point to earlier suggested steps, preventing cycles. `aie goal-suggest GOAL_ID` persists a bounded draft with `pending_review` status and SHA-256 integrity metadata. `aie goal-draft-list/show` expose drafts; `aie goal-draft-accept/reject` provide explicit one-time resolution. Acceptance creates ordered goal steps and dependency links in one SQLite transaction and records the transition in goal history. Rejection leaves goal steps unchanged. Draft integrity is checked before display/resolution; storage is capped at 100 drafts and 20 pending reviews per goal. This is plan persistence only: no commands or OS actions execute. Plan-quality evaluation remains open, and goal execution remains prohibited until the separate policy/sandbox/action-verification pipeline exists.

- Cognitive context applies a second-stage prompt budget: at most 12 processes and 12 entities with the latest eight evidence IDs each, five non-sensitive memory matches with 1,000-character content caps, and six active/paused goals with ten steps each. Truncation remains explicit; oversized packets fail closed rather than silently dropping arbitrary fields.


## Windows Settings URI catalogue

The repository now bundles 219 distinct URI records transcribed from Microsoft's official [Launch Windows Settings reference](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings) in `aie/data/ms_settings_catalog.json`. Each record retains its Microsoft Learn source URL, category, and applicable version/availability notes. `aie settings-search` searches this bundled catalogue by default; `aie settings-import` accepts additional bounded JSON/CSV sources. Entries are labelled `documented`, not runtime-verified. Microsoft notes that availability varies by Windows version, SKU and hardware. The catalogue is metadata only: it does not launch Settings or modify configuration.

**Open work:** reach the 1,500+ target only by discovering and auditing further authoritative first-party sources; keep internal/undocumented protocol identifiers in a separate evidence tier. Validate destinations on the target Windows 11 edition/build. Navigation and any future mutation capability must remain separate and policy-gated.


## Learning and autonomy trajectory

AIE's long-term objective is a highly capable, continuously improving, increasingly autonomous system. The implementation must earn each autonomy increase through measured reliability rather than assume it. Current learning foundation:

- Task experiences are stored separately from raw observations and include outcome, verifier class and evidence IDs.
- Reusable procedural drafts require repeated successful episodes and at least one evidence-backed episode.
- Draft payloads are SHA-256 checked; acceptance/rejection is one-time and audited.
- `aie learn-report TASK_KEY` reports outcome distributions, a descriptive Wilson interval, evidence-backed success coverage, verifier mix, unique evidence references and repeated-summary groups. Unknown outcomes are excluded from the success-rate denominator; the report is not a reliability certification.
- `aie skill-draft-list` verifies payload integrity before listing. Review uses a serialized SQLite write transaction and verifies the exact draft payload before the one-time state transition.
- Accepted skills remain non-executable procedural references. They do not receive capabilities, alter the policy broker, modify production code or invoke OS operations.
- Accepted drafts can be frozen into immutable numbered skill versions with source-draft lineage and payload-digest verification. Revisions with the same task key/title advance the version number; prior versions remain available.
- Skill evaluation records require a complete success/partial/failure/unknown outcome partition plus evidence references. The first version establishes a suite baseline; later versions compare against the latest earlier evaluation from the same named suite, using Wilson intervals, a minimum labeled sample (default 10) and a configurable tolerance.
- Evaluation outcomes distinguish insufficient data, baseline establishment, observed regression and no observed regression. Evaluation audit writes are atomic with evaluation records. Every result has `automation_eligible=false`; a caller-supplied suite name and evidence references are not a substitute for an independently-run benchmark.
- Experience records receive deterministic fingerprints over normalized task key, summary and outcome. Exact repeats are linked as duplicates; source records are never deleted. Same-description, different non-unknown outcomes are linked as contradictions. Legacy rows are fingerprinted on database initialization.
- Relationship detection is deliberately lexical and conservative: it can identify normalized exact-summary matches, but it does not claim semantic equivalence or resolve conflicts. Operators inspect links with `aie experience-relationships TASK_KEY`.
- `aie knowledge-consolidate TASK_KEY` groups repeated same-outcome summaries, withholds clusters containing conflicting non-unknown outcomes, and creates digest-verified review-only knowledge candidates retaining bounded experience and evidence provenance.
- A knowledge candidate has a one-time audited accept/reject lifecycle. Only an accepted successful candidate with evidence can be imported into semantic memory. Memory imports use a source-key ledger so retries with the same knowledge ID return the existing memory record instead of creating duplicates.
- Partial/failure/unknown candidates remain review-only; no automatic inference or model-generated memory write is enabled. This is an evidence-preserving consolidation primitive, not autonomous truth discovery.
- Next: semantic near-duplicate detection with human review, recency/decay, explicit contradiction adjudication, independently executed held-out benchmark harness, calibrated promotion criteria, adapter bindings, sandboxed execution and outcome verification.

**Autonomy progression:** observe → reason → recommend → draft → human-approved action → narrowly delegated action. Each stage requires separate evidence, capability scope, resource budget, audit trail and rollback/stop behavior. High-impact actions remain explicitly approved. Production self-modification is out of scope; future self-improvement experiments must occur in isolated branches with independent evaluation and human merge approval.
