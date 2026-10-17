# Autonomous Intelligence Ecosystem (AIE)

Windows-first, hybrid, persistent intelligence research platform. AGI is a research objective, not a capability claim.

## Architecture spotlight
**Current focus: M2 Context Intelligence — evidence-backed environment projection over the Windows observer.**
Track status and next evidence in [docs/ARCHITECTURE_SPOTLIGHT.md](docs/ARCHITECTURE_SPOTLIGHT.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## Principles
- Windows 10/11 only. Linux and WSL are out of scope.
- Local-first observation and private memory; optional cloud reasoning through an explicit policy-controlled gateway.
- High but bounded autonomy. All future execution is mediated by identity, capabilities, risk policy, budgets, approval and audit.
- Model-independent, event-driven architecture.
- Privacy by design: no keylogging, covert screenshots, microphone capture, credential collection or unrestricted content surveillance.
- Deep telemetry uses supported Windows interfaces (ETW/Event Log) with a fixed System-log provider/event-ID allowlist. Kernel drivers are separate signed, reviewed work—not unrestricted access.

## Quick start (Windows)
Python 3.11+:
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
aie doctor
aie hardware
aie models
# Optional local inference after Ollama + a supported model are installed:
aie ask "Summarize the current system state"
aie embed "AIE local embedding smoke test"
aie inventory --output inventory.json
aie etw-catalog --contains Kernel
# Optional, bounded ETW process trace (writes a new .etl file):
aie etw-capture .\\traces\\process.etl --duration 60
tracerpt .\\traces\\process.etl -o .\\traces\\process.xml -of XML -y
aie etw-decode .\\traces\\process.xml .\\traces\\process-events.jsonl  # imports into SQLite; reports loss counters if present
aie correlate --since-minutes 1440  # correlate ETW starts with matching process snapshots
aie state                            # update durable environment projection
aie context                          # emit bounded facts with evidence references
aie prioritize                       # rank observed state with explainable heuristics
aie observe --duration 30 --jsonl observations.jsonl
aie export-events archived-events.jsonl
# Create .\\aie-pause to pause; remove it to resume:
aie observe --duration 300 --pause-file .\\aie-pause
```
The observer is read-only and stores events under %LOCALAPPDATA%\AIE. Event collection does not require a model or network. Optional inference uses only a loopback Ollama endpoint; AIE does not pull models or send prompts to remote services. The fixed System Event Log cursor is checkpointed in SQLite after each event batch is persisted, so observer restarts replay safely instead of skipping an uncommitted page.

## Layout
- `aie/`: contracts, observer, SQLite store and CLI.
- `docs/`: architecture spotlight, roadmap, hardware profile, Windows automation strategy and security.
- `tests/`: deterministic synthetic tests.

`aie state` incrementally updates a durable partial process/inventory projection; use `aie state --rebuild` to replay currently retained events. The first process baseline records only a count, so pre-existing process instances remain unknown until a lifecycle event is observed. Missing entities in a query window are never treated as removals. `aie prioritize` ranks projected records using transparent recency, active-state and ETW-confirmation features; its score is retrieval priority, not truth or calibrated confidence. Each state record retains at most 64 evidence references and reports when older references were truncated; persisted projection writes are capped at 16 MiB and fail without overwriting the last valid snapshot. New snapshots carry SHA-256 integrity metadata and are verified when loaded; corrupted snapshots fail closed; `aie state --recover` restores the previous verified snapshot and replays later retained events, while `aie state --rebuild` replays all currently retained events. `aie compact-state --older-than-days 90 --max-terminal-records 1000` explicitly compacts excess old stopped/replaced processes and removed entities from the projection only; recent/live state and raw event history are preserved.

## Current limitations
Default process lifecycle monitoring uses periodic user-mode snapshots and may miss short-lived processes. An opt-in bounded ETW capture command is now available and writes a raw .etl trace; an offline `aie etw-decode` path now converts tracerpt XML process start/stop records into normalized JSONL. Validate the XML schema and event coverage against real Windows ETL captures before relying on it operationally. A driver requires a separate threat model, signing, review, installation consent and removal plan.

Run tests with `python -m pytest`. The Windows CI workflow runs tests and Ruff on pushes and pull requests.


## Cognitive, memory and policy foundations

- `aie think "Why is memory usage high?"` builds a bounded provenance-bearing context packet and sends it only to an eligible loopback Ollama model. Add `--include-memory` to retrieve matching non-sensitive user-created memories; stored memories are distinguished from live observations. No tools or OS actions are exposed.
- `aie memory-add "A manually reviewed fact" --kind semantic --provenance EVENT_ID` creates an explicit local memory record.
- `aie memory-search "reviewed fact"` searches unexpired records; sensitive records are excluded by default.
- `aie memory-correct MEMORY_ID --verification verified` revises a record while preserving its prior version and provenance.
- `aie memory-history MEMORY_ID` reviews prior versions.
- `aie memory-export .\\memory.jsonl` exports active records to a new file; sensitive records require `--include-sensitive`.
- `aie memory-delete MEMORY_ID` explicitly deletes a record and its revision history; `aie memory-prune` removes expired records and their history.
- `aie uia-inspect` enumerates a bounded Windows UI Automation control tree (default 12 windows, 250 nodes, depth 5, 12-second timeout). It reports structural metadata only: control type, automation ID, class/framework, enabled/offscreen state and bounds. It intentionally excludes control names, typed text, values, password contents, screenshots and interaction patterns. It never clicks, types or changes settings.
- `aie.policy` currently evaluates proposals only. It checks a reviewed action allowlist, exact action capabilities, verified target identity, sandbox availability for writes, action budgets and expiring approvals bound to the exact proposal digest. It never executes a proposal.

Memory writes are user-directed; no automatic model-generated consolidation is enabled. Memory is stored in the local SQLite database and is not encrypted by this implementation. Protect the database with the Windows account's filesystem permissions and do not store secrets in it.


## Persistent goal runtime

AIE now stores user-authored goals and dependency-ordered steps in local SQLite. Step dependencies are checked before starting or completing work. Goal completion requires all steps to be completed. Every goal/step transition is recorded in append-only history. Nothing is executed automatically.

Commands: `aie goal-add`, `aie goal-list`, `aie goal-show`, `aie goal-step-add`, `aie goal-step-update`, `aie goal-status`, and `aie goal-history`. Use `aie think QUESTION --include-goals --include-memory` to optionally provide bounded active/paused goal state and non-sensitive memories to local analysis. These are planning context, not evidence of completed work or permission to act.


`aie goal-suggest GOAL_ID` generates and persists a structured local-model draft in `pending_review`. Use `aie goal-draft-list GOAL_ID`, `aie goal-draft-show DRAFT_ID`, then explicitly choose `aie goal-draft-accept DRAFT_ID` or `aie goal-draft-reject DRAFT_ID`. Acceptance adds the ordered steps and dependency links in one SQLite transaction; it does not execute commands or OS actions. Draft payloads are SHA-256 checked when read or resolved. Retention is bounded to 100 drafts per goal and 20 pending reviews. Only pending drafts on active goals can be resolved.


## Windows Settings URI catalogue

AIE includes a conservative starter catalogue for common `ms-settings:` destinations. Search it with `aie settings-search privacy microphone`. Import a larger locally held JSON or CSV catalogue with `aie settings-import .\\settings-uris.json --output .\\settings-catalog.json`, then search it with `aie settings-search bluetooth --catalog .\\settings-catalog.json`.

The importer validates the URI scheme and bounded metadata, deduplicates URIs case-insensitively, and supports up to 10,000 records / 8 MiB per input file. Fields are `uri`, `title`, optional `category`, `description`, `source`, `validation_status`, `min_build` and `max_build`. Validation states are deliberately explicit: `unverified`, `documented`, `verified-on-host`, or `unsupported`. Starter entries are all `unverified`; a syntactically valid URI is not proof that it works on this Windows edition/build. AIE does not open these URIs, change settings, or infer undocumented support. The catalogue is navigation metadata, not an action capability.
