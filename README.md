# Autonomous Intelligence Ecosystem (AIE)

Windows-first, hybrid, persistent intelligence research platform. AGI is a research objective, not a capability claim.

## Architecture spotlight
**Current focus: AIE Foundation + Windows Environment Observer (M0/M1).**
Track status and next evidence in [docs/ARCHITECTURE_SPOTLIGHT.md](docs/ARCHITECTURE_SPOTLIGHT.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## Principles
- Windows 10/11 only. Linux and WSL are out of scope.
- Local-first observation and private memory; optional cloud reasoning through an explicit policy-controlled gateway.
- High but bounded autonomy. All future execution is mediated by identity, capabilities, risk policy, budgets, approval and audit.
- Model-independent, event-driven architecture.
- Privacy by design: no keylogging, covert screenshots, microphone capture, credential collection or unrestricted content surveillance.
- Deep telemetry uses supported Windows interfaces (ETW/Event Log). Kernel drivers are separate signed, reviewed work—not unrestricted access.

## Quick start (Windows)
Python 3.11+:
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
aie doctor
aie hardware
aie models
aie inventory --output inventory.json
aie etw-catalog --contains Kernel
# Optional, bounded ETW process trace (writes a new .etl file):
aie etw-capture .\\traces\\process.etl --duration 60
tracerpt .\\traces\\process.etl -o .\\traces\\process.xml -of XML -y
aie etw-decode .\\traces\\process.xml .\\traces\\process-events.jsonl  # imports into SQLite; reports loss counters if present
aie observe --duration 30 --jsonl observations.jsonl
aie export-events archived-events.jsonl
# Create .\\aie-pause to pause; remove it to resume:
aie observe --duration 300 --pause-file .\\aie-pause
```
The first release is read-only, local-only and stores events under %LOCALAPPDATA%\AIE. No model or network is required.

## Layout
- `aie/`: contracts, observer, SQLite store and CLI.
- `docs/`: architecture spotlight, roadmap, hardware profile, Windows automation strategy and security.
- `tests/`: deterministic synthetic tests.

## Current limitations
Default process lifecycle monitoring uses periodic user-mode snapshots and may miss short-lived processes. An opt-in bounded ETW capture command is now available and writes a raw .etl trace; an offline `aie etw-decode` path now converts tracerpt XML process start/stop records into normalized JSONL. Validate the XML schema and event coverage against real Windows ETL captures before relying on it operationally. A driver requires a separate threat model, signing, review, installation consent and removal plan.

Run tests with `python -m pytest`. The Windows CI workflow runs tests and Ruff on pushes and pull requests.
