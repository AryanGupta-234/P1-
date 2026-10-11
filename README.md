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
# Inspect cross-provider activity sessions safely:
aie activity --hours 4
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

## Persistent local memory (explicit capture)\nUse `aie remember --kind semantic --tags windows,workflow` to enter a memory interactively (hidden input with `--sensitive`), or pass text as an argument. `aie recall "query"` uses local keyword/tag overlap (not embeddings); sensitive records are excluded by default. `aie memories` lists records, `aie correct-memory <ID> "corrected text"` supersedes a record while retaining history, and `aie forget <ID> --confirm` deletes it. Optional `--ttl-days` sets expiry; `aie memory-prune --confirm` removes expired records. Memory is stored in local SQLite; the sensitivity flag is not encryption. Do not store credentials or tokens. Nothing is silently extracted from observations or model output.\n\n## Unified activity timeline\n`aie activity --hours 4` queries the local event store by time window and groups browser, foreground-app, network, process, Event Log and diagnostic signals into temporal sessions. It displays a safe projection of metadata only; it never dumps raw event payloads, window titles, UIA content or feedback notes. Grouping is time-based and does not infer user intent.\n\n## Diagnostic feedback
Use `aie events` to find a `diagnostic.video_finding` event ID, then record the outcome with `aie feedback <EVENT_ID> --outcome resolved`, `not_resolved`, or `not_attempted`. Run `aie learning-report` to see sample counts and observed resolution rates by cause. An optional `--note` is stored locally as sensitive data. This captures user feedback; it does not retrain a model or imply that AIE executed the recommendation.

## Windows Event Log metadata (optional)
Install optional Windows dependencies with `python -m pip install -e ".[dev,windows]"`. Use `aie observe --event-logs --event-log-channels Application,System --event-log-interval 30` to opt in to bounded metadata-only polling of the Windows Application/System logs. It skips historical backlog on startup and does not collect event message text or XML. The optional `windows` extra supplies pywin32.

## Observer controls
Use `aie pause` to pause all running observer loops for the current Windows user, `aie resume` to resume them, and `aie status` to inspect pause state and local event count. Pausing does not erase retained events. `aie prune --older-than-days 30` previews old records; add `--confirm` to delete only the expired local events.

## Browser playback observer
The opt-in Chrome/Edge extension prototype is in `browser_extension/`. Load it unpacked, then register its Windows native host using `scripts/register-native-host.ps1`. See [Video Intelligence setup](docs/VIDEO_INTELLIGENCE.md). Monitoring defaults to off.

## Structural screen observation (optional)
To collect bounded UI Automation structure for selected apps, install the optional Windows extra with `python -m pip install -e ".[dev,windows]"`, then run `aie observe --duration 600 --ui-tree --ui-tree-apps msedge.exe,notepad.exe`. Only allowlisted foreground apps are sampled. It records control type, class, automation ID and geometry; it does not read UI text, values, passwords or screenshots. UI Automation is off by default. Inspect the latest structural sample with `aie screen`.

## Foreground application observation
The observer emits foreground-window transition events using the Windows user32 API. Process name and window class are collected by default; window titles are omitted. Explicitly passing `--include-window-titles` collects them as sensitive data.

## Live diagnostic suggestions
While `aie observe` is running, fresh browser video events are correlated with foreground-app and network telemetry. New diagnostic hypotheses are persisted and printed once per incident/cooldown, with evidence and a recommended next step. The observer does not apply fixes automatically.

## Action policy foundation
The `aie.policy` module currently evaluates action proposals against explicit capability manifests. Unknown/disabled capabilities are denied, parameters are allowlisted, medium/high-risk proposals require approval, and critical-risk actions are blocked. This is an authorization prototype only; AIE does not yet execute operating-system actions.

## Local model runtime
A provider-neutral request/response contract and Ollama adapter are available under `aie/models/`. The router selects only installed local models using available RAM; it never pulls a model. `aie ask` is local-only by default. A remote Ollama endpoint requires an explicit `--allow-remote-ollama` flag and HTTPS.

## CI validation
Windows CI passed on the current development baseline for Python 3.11 and 3.12, including Ruff, extension JavaScript syntax checks and pytest. See [run #206](https://github.com/AryanGupta-234/P1-/actions/runs/38118517008). This does not replace testing the browser extension/native host and UI Automation against your own Windows desktop.

## Current limitations
Process lifecycle observation uses best-effort user-mode snapshots and may miss transient processes. Foreground process resource sampling is limited to the active application; it is not a systemwide per-process profiler. Video diagnostics analyze supplied metrics only; live browser telemetry, screen perception, model gateway, persistent learning and autonomous remediation are not implemented.
