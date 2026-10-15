# AIE Architecture Spotlight

> Always-current project orientation. Read before coding and update in the same change as milestone progress.

**Last updated:** 2026-10-16  
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
- UI Automation client, app-specific automation adapters and action execution.
- State-aware compaction and recovery evaluation across pruning/corruption edge cases, broader environmental state semantics, relationship modeling and synthetic projection evaluation. Per-entity evidence references are bounded at 64 IDs with explicit truncation metadata, and snapshot writes have a fail-safe 16 MiB payload ceiling. `aie state` persists a versioned projection and resumes by monotonic SQLite ingestion sequence; `aie context` emits bounded facts with provenance but does not reason over them. Initial process baseline coverage remains count-only.
- End-to-end local Ollama invocation against the target installation, Nomic live dimension confirmation, memory consolidation and cloud gateway.
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
1. Run Windows CI and resolve every failure; execute the observer and ETW synthetic tests.
2. Validate observer pause/resume, collector recovery, JSONL export and resource overhead on the target Windows host.
3. Validate ETW decoding against real Windows captures; confirm trace-loss counters and reconcile ETW events with process snapshots.
4. Validate the fixed Event Log allowlist and SQLite cursor recovery on Windows, then add real-time subscriptions and process/image correlation.
5. Add app compatibility discovery and UIA read-only tree inspection.
6. Validate incremental `aie state` checkpoint recovery against real observer history; add state-aware compaction/recovery and environmental-state evaluation (a 16 MiB hard write ceiling is implemented). Validate local Ollama inference and Nomic dimensions before expanding the cognitive runtime.

## Spotlight maintenance
At each implementation increment: update this file, update [ROADMAP.md](ROADMAP.md), add/adjust tests, and record actual validation. Never mark a task DONE based only on writing its interface.
