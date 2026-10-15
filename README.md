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

`aie state` incrementally updates a durable partial process/inventory projection; use `aie state --rebuild` to replay currently retained events. The first process baseline records only a count, so pre-existing process instances remain unknown until a lifecycle event is observed. Missing entities in a query window are never treated as removals. `aie prioritize` ranks projected records using transparent recency, active-state and ETW-confirmation features; its score is retrieval priority, not truth or calibrated confidence. Each state record retains at most 64 evidence references and reports when older references were truncated; persisted projection writes are capped at 16 MiB and fail without overwriting the last valid snapshot. New snapshots carry SHA-256 integrity metadata and are verified when loaded; corrupted snapshots fail closed; `aie state --recover` restores the previous verified snapshot and replays later retained events, while `aie state --rebuild` replays all currently retained events.

## Current limitations
Default process lifecycle monitoring uses periodic user-mode snapshots and may miss short-lived processes. An opt-in bounded ETW capture command is now available and writes a raw .etl trace; an offline `aie etw-decode` path now converts tracerpt XML process start/stop records into normalized JSONL. Validate the XML schema and event coverage against real Windows ETL captures before relying on it operationally. A driver requires a separate threat model, signing, review, installation consent and removal plan.

Run tests with `python -m pytest`. The Windows CI workflow runs tests and Ruff on pushes and pull requests.
