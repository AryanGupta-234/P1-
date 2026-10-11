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
aie status
aie observe --duration 30
aie observe --duration 60 --network-interval 30
# Disable network probes when needed:
aie observe --duration 30 --no-network
# Disable foreground application transitions:
aie observe --duration 30 --no-foreground
# Window titles are sensitive; collect only after explicit opt-in:
aie observe --duration 30 --include-window-titles
# Adjust active-process metric cadence (seconds):
aie observe --duration 60 --foreground-sample-interval 10
# Inspect correlated browser, active-app and network evidence:
aie context
# Prompt an installed local Ollama model:
aie ask "Explain the latest AIE event context" --task routine
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

## Observer controls
Use `aie pause` to pause all running observer loops for the current Windows user, `aie resume` to resume them, and `aie status` to inspect pause state and local event count. Pausing does not erase retained events. `aie prune --older-than-days 30` previews old records; add `--confirm` to delete only the expired local events.

## Browser playback observer
The opt-in Chrome/Edge extension prototype is in `browser_extension/`. Load it unpacked, then register its Windows native host using `scripts/register-native-host.ps1`. See [Video Intelligence setup](docs/VIDEO_INTELLIGENCE.md). Monitoring defaults to off.

## Foreground application observation
The observer emits foreground-window transition events using the Windows user32 API. Process name and window class are collected by default; window titles are omitted. Explicitly passing `--include-window-titles` collects them as sensitive data.

## Live diagnostic suggestions
While `aie observe` is running, fresh browser video events are correlated with foreground-app and network telemetry. New diagnostic hypotheses are persisted and printed once per incident/cooldown, with evidence and a recommended next step. The observer does not apply fixes automatically.

## Action policy foundation
The `aie.policy` module currently evaluates action proposals against explicit capability manifests. Unknown/disabled capabilities are denied, parameters are allowlisted, medium/high-risk proposals require approval, and critical-risk actions are blocked. This is an authorization prototype only; AIE does not yet execute operating-system actions.

## Local model runtime
A provider-neutral request/response contract and Ollama adapter are available under `aie/models/`. The router selects only installed local models using available RAM; it never pulls a model. `aie ask` is local-only by default. A remote Ollama endpoint requires an explicit `--allow-remote-ollama` flag and HTTPS.

## Current limitations
Process lifecycle observation uses best-effort user-mode snapshots and may miss transient processes. Foreground process resource sampling is limited to the active application; it is not a systemwide per-process profiler. Video diagnostics analyze supplied metrics only; live browser telemetry, screen perception, model gateway, persistent learning and autonomous remediation are not implemented.
