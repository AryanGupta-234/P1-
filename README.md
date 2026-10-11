# Autonomous Intelligence Ecosystem (AIE)

Windows-first, hybrid, persistent personal intelligence research platform. AGI is a research objective, not a capability claim.

## Development branch
Use `dev` as the integration branch. Create scoped `feat/*`, `fix/*`, or `integrate/*` branches from the latest `dev`; validate changes and merge via pull request. Keep `main` stable.

## Architecture spotlight
- [Architecture Spotlight](docs/ARCHITECTURE_SPOTLIGHT.md)
- [Roadmap and task tracker](docs/ROADMAP.md)
- [Video Intelligence](docs/VIDEO_INTELLIGENCE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security and Privacy](docs/SECURITY_AND_PRIVACY.md)
- [Contributing](CONTRIBUTING.md)

## Principles
- Windows 10/11 only; Linux and WSL are out of scope.
- Local-first observation and private memory; optional cloud reasoning through explicit data-egress policy.
- Autonomous actions are capability-scoped, budgeted, audited and verified.
- Collectors are read-only. Models cannot grant themselves permissions.
- No keylogging, covert screenshots, microphone capture, credentials, cookies, form content or unrestricted page surveillance.
- Supported Windows interfaces (ETW/Event Log) first; no unsigned drivers or security-control bypass.

## Windows quick start
Python 3.11+:
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
aie doctor
aie inventory
aie observe --duration 30
aie observe --duration 60 --network-interval 30
# Disable network probes when needed:
aie observe --duration 30 --no-network
python -m pytest
python -m ruff check .
```
Foundation works without models or internet. Local events are stored under `%LOCALAPPDATA%\AIE`.

## Development workflow
```powershell
git switch dev
git pull origin dev
git switch -c feat/<short-scope>
# implement, test, update ARC Spotlight + roadmap
git push -u origin feat/<short-scope>
```
Open PRs against `dev`, not `main`.

## Browser playback observer
The opt-in Chrome/Edge extension prototype is in `browser_extension/`. Load it unpacked, then register its Windows native host using `scripts/register-native-host.ps1`. See [Video Intelligence setup](docs/VIDEO_INTELLIGENCE.md). Monitoring defaults to off.

## Current limitations
Process lifecycle observation uses best-effort user-mode snapshots and may miss transient processes. Video diagnostics analyze supplied metrics only; live browser telemetry, screen perception, model gateway, persistent learning and autonomous remediation are not implemented.
