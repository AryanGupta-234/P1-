# Autonomous Intelligence Ecosystem (AIE)

Windows-first, hybrid, persistent intelligence research platform. AGI is a research objective, not a capability claim.

## Architecture spotlight
**Current focus: Windows environment observer + first diagnostic capability (M0/M1/M1.5).**
Track status and next evidence in [docs/ARCHITECTURE_SPOTLIGHT.md](docs/ARCHITECTURE_SPOTLIGHT.md) and [docs/ROADMAP.md](docs/ROADMAP.md). The first video diagnostic slice is documented in [docs/VIDEO_INTELLIGENCE.md](docs/VIDEO_INTELLIGENCE.md).

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
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -e ".[dev]"
aie doctor
aie inventory
aie observe --duration 30
python -m pytest
```
The observer is read-only and stores events under %LOCALAPPDATA%\\AIE. The video diagnostic module is currently a pure function over supplied metrics; it does not yet collect browser telemetry or apply fixes. No model or network is required for the foundation.

## Layout
- `aie/`: contracts, observer, SQLite store, CLI and diagnostic modules.
- `docs/`: architecture spotlight, roadmap, security and capability design.
- `tests/`: deterministic synthetic tests.

## Current limitations
Initial process lifecycle monitoring uses periodic user-mode snapshots and may miss short-lived processes. It is not complete kernel telemetry. ETW integration is a next milestone; a driver requires a separate threat model, signing, review, installation consent and removal plan. Browser observation, screen perception, model routing, memory consolidation and autonomous remediation are not implemented yet.

Run tests with `python -m pytest`.
