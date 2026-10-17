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

AIE bundles 219 distinct `ms-settings:` URI entries transcribed from Microsoft's official Settings URI reference. Search the bundled catalogue with `aie settings-search privacy microphone`. Import a larger local JSON or CSV catalogue with `aie settings-import .\\settings-uris.json --output .\\settings-catalog.json`, then search it with `aie settings-search bluetooth --catalog .\\settings-catalog.json`.

The bundled data lives at `aie/data/ms_settings_catalog.json` and records Microsoft's Learn page as provenance plus version/availability notes where Microsoft provides them. Entries are marked `documented`, not runtime-verified. Microsoft's reference explicitly warns that availability varies by Windows version, SKU and hardware. The importer validates the URI scheme and bounded metadata, deduplicates URIs case-insensitively, and supports up to 10,000 records / 8 MiB per input file. Fields include `uri`, `title`, `category`, `description`, `source`, `source_url`, `version_notes`, `requirements`, `validation_status`, `min_build` and `max_build`. Validation states are deliberately explicit: `unverified`, `documented`, `verified-on-host`, or `unsupported`. The 219 documented entries are not 1,500 unique documented URIs; that larger target remains open pending further authoritative sources. AIE does not open these URIs, change settings, or infer undocumented support. The catalogue is navigation metadata, not an action capability.


## Evidence-gated learning and procedural skill formation

AIE is being developed toward a progressively more autonomous learning system. The current learning loop is deliberately bounded: record task outcomes, retain evidence references, identify repeated successful task families, draft reusable human-readable procedures, and require explicit review before storing them as accepted procedural references.

```powershell
# Record outcomes (use real event/evidence IDs where available)
aie experience-add "settings.open_display" "Display page reached and visually confirmed" success --evidence "EVENT_ID_1" --verifier reviewed-evidence
aie experience-list "settings.open_display"
aie learn-report "settings.open_display"  # outcome rates, Wilson interval, evidence coverage

# Review skill drafts (all statuses, or filter by --status pending_review):
aie skill-draft-list "settings.open_display" --status pending_review

# After at least three successful episodes, including evidence references:
aie skill-draft "settings.open_display" "Open Display Settings" '["Resolve the intended Settings destination","Verify the target window identity","Confirm the expected page is visible"]'
aie skill-draft-show DRAFT_ID
aie skill-draft-accept DRAFT_ID
aie skill-publish DRAFT_ID  # freeze accepted draft as immutable version 1

# Publish a later accepted draft with the same task key/title to create version 2+
aie skill-version-list "settings.open_display" --title "Open Display Settings"

# Record outcomes from a named, evidence-backed evaluation suite:
aie skill-evaluate SKILL_ID 1 "display-settings-regression" --trials 20 --successes 18 --partials 1 --failures 1 --unknown 0 --evidence "EVAL_REPORT_ID"
aie skill-evaluation-list SKILL_ID

# Inspect duplicate/contradictory outcomes; source records are never deleted:
aie experience-relationships "settings.open_display"

# Create review-only knowledge candidates from at least three repeated,
# non-contradictory experiences:
aie knowledge-consolidate "settings.open_display" --minimum-repetitions 3
aie knowledge-draft-list "settings.open_display" --status pending_review
aie knowledge-draft-review KNOWLEDGE_ID accepted

# Only accepted, repeated successes with evidence can enter semantic memory:
aie knowledge-publish KNOWLEDGE_ID
```

An accepted skill is currently a reviewed procedural reference, not executable automation. No skill can grant itself capabilities, alter policy, modify source code, or execute OS actions. `aie learn-report TASK_KEY` reports success/partial/failure/unknown counts, a 95% Wilson interval for the descriptive success rate, evidence-backed success coverage, unique evidence references, verifier mix and repeated-summary groups. Unknown outcomes are excluded from the rate; the report explicitly warns that small samples and user-reported outcomes are not proof of reliability. `aie skill-draft-list [TASK_KEY] --status pending_review` lists drafts only after verifying each payload digest. Skill decisions now use a serialized SQLite write transaction and verify the payload in that same transaction, preventing competing reviewers from both resolving a draft. These reports are descriptive—not a promotion gate—and accepted skills remain non-executable. Accepted drafts can be frozen with `aie skill-publish` into immutable numbered versions; publishing requires prior acceptance, checks the draft digest in a serialized transaction, and retains the source draft. `aie skill-evaluate` records a complete outcome partition (success/partial/failure/unknown) and evidence references for a named suite. Version 1 establishes a baseline; later versions are compared with the latest earlier evaluation from the same suite using Wilson intervals and a configurable tolerance. Fewer than ten labeled trials is insufficient by default. Results are `baseline_only`, `insufficient_data`, `baseline_insufficient_data`, `regression_observed` or `no_regression_observed`. The last status is not a reliability certification: the suite identity and evidence are supplied by the operator, and no independent benchmark runner exists yet. Every result explicitly reports `automation_eligible=false`; evaluation cannot grant execution permissions.

Experience ingestion now computes a stable SHA-256 fingerprint over normalized task key, whitespace-normalized/case-folded summary and outcome. Exact repeats create `duplicate_of` links; the original rows and evidence remain intact. The same normalized task description with conflicting non-unknown outcomes creates `contradicts` links rather than choosing a winner. Existing experience rows receive fingerprints during database initialization. `aie experience-relationships TASK_KEY` exposes these review signals; they are heuristic text matches, not semantic equivalence proofs.

`aie knowledge-consolidate TASK_KEY` proposes knowledge drafts only when the same normalized summary/outcome repeats at least three times (configurable). Candidates with conflicting non-unknown outcomes are withheld. Drafts retain source experience IDs and evidence references, are SHA-256 checked, and require one-time human acceptance. Only accepted successful candidates with evidence can be published to semantic memory. Immediately before publication, AIE rechecks the accepted draft digest, its source experience IDs, evidence references and current contradiction state; a newly conflicting outcome blocks publication. The memory import is idempotent by knowledge ID, records bounded source/evidence provenance, and is tagged as reviewed learning. Partial/failure/unknown candidates can be inspected but cannot be promoted to semantic memory by this path. No model-generated text is silently consolidated.
