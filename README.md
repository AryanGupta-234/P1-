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

## Persistent local memory (explicit capture)
Use `aie remember --kind semantic --tags windows,workflow` to enter a memory interactively (hidden input with `--sensitive`), or pass text as an argument. `aie recall "query"` uses local keyword/tag overlap by default. Run `aie memory-index --model nomic-embed-text:latest` after installing that model yourself, then use `aie recall "query" --semantic --embedding-model nomic-embed-text:latest` for cosine retrieval. `aie ask --with-memory --semantic-memory` can use the same local index. Sensitive records are excluded by default. `aie memories` lists records, `aie correct-memory <ID> "corrected text"` supersedes a record while retaining history, and `aie forget <ID> --confirm` deletes it. Optional `--ttl-days` sets expiry; `aie memory-prune --confirm` removes expired records. Memory is stored in local SQLite; the sensitivity flag is not encryption. Do not store credentials or tokens. Nothing is silently extracted from observations or model output.

## Unified activity timeline
`aie activity --hours 4` queries the local event store by time window and groups browser, foreground-app, network, process, Event Log and diagnostic signals into temporal sessions. It displays a safe projection of metadata only; it never dumps raw event payloads, window titles, UIA content or feedback notes. Grouping is time-based and does not infer user intent.

## Diagnostic feedback
Use `aie events` to find a `diagnostic.video_finding` event ID, then record the outcome with `aie feedback <EVENT_ID> --outcome resolved`, `not_resolved`, or `not_attempted`. Run `aie learning-report` to see sample counts and observed resolution rates by cause. An optional `--note` is stored locally as sensitive data. This captures user feedback; it does not retrain a model or imply that AIE executed the recommendation.

## Systemwide process resource snapshots (optional)
Run `aie observe --process-resources --process-resource-interval 10 --process-resource-max-processes 256` to opt in to bounded process CPU/RSS/thread/I/O metadata. It samples at most 256 processes each pass and reports the top 20 CPU consumers (or memory consumers during CPU warm-up). Command lines, executable paths and window content are never collected. The sensor is off by default.

## ETW process telemetry (optional)
Install the optional Windows extra, then run `aie observe --etw --duration 600`. Kernel ETW process tracing requires an elevated Windows token. P1- stores only process lifecycle metadata (PID, parent PID, image basename and event kind), not command lines or executable paths. ETW collection is paused with `aie pause`; a bounded consumer queue reports its own drops as health events.

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

## Proposal review and policy audit (no executor yet)\nCapability manifests are loaded only from `%LOCALAPPDATA%\\AIE\\capabilities\\*.json`; the directory is user-managed and empty by default. `aie capabilities` lists them. `aie propose <CAPABILITY_ID> <SUMMARY> --parameters '{"name":"value"}'` records a bounded proposal, `aie proposals` lists review states, and `aie approve-proposal <ID>` / `aie reject-proposal <ID>` record your explicit decision. `aie proposal-audit <ID>` shows the append-only review trail. Proposal parameters are bounded flat scalar values; credential-like parameter names are rejected. Approval is policy authorization only—there is no action executor and nothing is executed.\n\n## Proposal review and policy audit (no executor yet)
Capability manifests are loaded only from `%LOCALAPPDATA%\AIE\capabilities\*.json`; the directory is user-managed and empty by default. See [Capability Manifest Guide](docs/CAPABILITY_MANIFESTS.md). `aie capabilities` lists manifests. `aie propose <CAPABILITY_ID> <SUMMARY> --parameters '{"name":"value"}'` records a bounded proposal, `aie proposals` lists review states, and `aie approve-proposal <ID>` / `aie reject-proposal <ID>` record your explicit decision. `aie proposal-audit <ID>` shows the audit trail and checks its hash chain and stored head checkpoint; `aie policy-audit-check` verifies the complete ledger. Approval only records policy authorization—nothing is executed.

## Action policy foundation
The `aie.policy` module evaluates action proposals against explicit capability manifests. Unknown/disabled capabilities are denied, parameters are allowlisted, medium/high-risk proposals require approval, and critical-risk actions are blocked. A restricted registry executor is now available for the fixed Windows Settings URI adapter only; it requires a separate enable marker and explicit per-proposal confirmation.

## Explicit task sessions
Use `aie session-start "Build the ETW observer"`, `aie session-status`, `aie session-end`, and `aie sessions`. Sessions are explicit user labels; AIE does not infer or auto-create task intent. `aie ask --with-session` can attach the current session metadata, and remote models require `--confirm-session-egress`.

## Local model runtime
`aie ask` does not attach memories or activity by default. Add `--with-activity` to attach a bounded recent activity summary. Remote/cloud inclusion requires `--confirm-activity-egress`; the activity package contains safe event summaries only, never window titles, Event Log message text, UIA control contents or feedback notes.\n\n`aie ask` does not attach memories by default. Add `--with-memory` to retrieve matching non-sensitive local records for that request. `--include-sensitive-memory` is available only for local inference. Attaching memory to a cloud or remote Ollama endpoint also requires `--confirm-memory-egress`; sensitive records are never attached to remote requests. The memory block is bounded JSON reference data marked untrusted, not instructions.

A provider-neutral request/response contract and Ollama adapter are available under `aie/models/`. The router selects only installed local models using available RAM; it never pulls a model. `aie ask` is local-only by default. A remote Ollama endpoint requires an explicit `--allow-remote-ollama` flag and HTTPS.

## Latest CI validation
The current integrated Windows build passed [GitHub Actions run #448](https://github.com/AryanGupta-234/P1-/actions/runs/38122160376) on Python 3.11 and 3.12. It includes lint, Windows-only optional imports, PowerShell parsing, browser JavaScript checks and the complete pytest suite, including Event Log runtime wiring, systemwide process telemetry, context packaging and audit integrity.

## CI validation
Windows CI passed on the current development baseline for Python 3.11 and 3.12, including Ruff, extension JavaScript syntax checks and pytest. See [run #206](https://github.com/AryanGupta-234/P1-/actions/runs/38118517008). This does not replace testing the browser extension/native host and UI Automation against your own Windows desktop.

## Windows tray controls

Start the user-controlled notification-area controller with:

```powershell
aie tray
```

Right-click the P1- icon to pause/resume the existing observer or open the local status dialog. Double-click the icon to show status. The tray does not start observation, change provider settings, enable capabilities, or create an auto-start service. Exit closes only the tray process. Provider configuration and full diagnostics remain in the CLI.

Generic local diagnostic balloons are disabled by default. Enable them explicitly and configure quiet hours:

```powershell
aie notifications-status
aie notifications-enable --confirm
aie notifications-quiet-hours 22:00 07:00
aie notifications-disable
```

The tray displays at most two generic playback-diagnostic notices per poll. It never places a process name, window title, URL, event payload or recommendation in the balloon. New events observed while notifications are disabled, the observer is paused, or quiet hours are active are not queued for later delivery.

## Current limitations
Process lifecycle observation uses best-effort user-mode snapshots and may miss transient processes. Foreground process resource sampling is limited to the active application; it is not a systemwide per-process profiler. Video diagnostics analyze supplied metrics only. The project has a restricted Windows Settings URI adapter, but general autonomous remediation, OS-process sandboxing, rollback, automated recovery, evaluated learning and a full desktop assistant dashboard are not implemented.


## Validated planning and task orchestration

Plans are declarative data, not executable instructions. Draft one using an already-installed local Ollama model, validate a JSON plan, then create and advance a durable local run:

```powershell
aie plan draft "Inspect why a desktop application is slow" --model qwen2.5:7b-instruct --output task-plan.json
aie plan validate task-plan.json
aie task start task-plan.json
aie task advance <RUN_ID> --max-steps 3
aie task show <RUN_ID>
aie task events <RUN_ID>
```

Plan drafting does not pull models, attach observations automatically or select a remote provider. Optional context must be supplied explicitly with `--context-file`. The local reasoning handler receives only the plan and bounded summaries from completed steps. If local inference is unavailable, the run pauses for explicit user input. Verification steps cannot complete without `aie task complete <RUN_ID> <STEP_ID> --summary "..." --verified`. Use `aie task pause`, `resume` and `cancel` for lifecycle controls. Cancellation and pause apply between handler invocations; an in-flight external handler is not force-killed.

Action steps queue policy proposals. Review them with `aie approve-proposal <PROPOSAL_ID>`; approval alone never executes anything. A separate `aie execute-proposal` command is required and the execution gate is disabled by default.

## Memory retrieval and conflict evaluation

Create a small JSON benchmark whose expected memory IDs are reviewed by you:

```json
{
  "dataset_id": "desktop-memory-v1",
  "description": "Queries for explicitly reviewed desktop workflow memories",
  "cases": [
    {
      "case_id": "browser-playback",
      "query": "browser playback troubleshooting",
      "relevant_memory_ids": ["<ACTIVE_MEMORY_ID>"]
    }
  ]
}
```

Evaluate local lexical retrieval or an already-installed local embedding model:

```powershell
aie memory-evaluate .\memory-eval.json --k 5
aie memory-evaluate .\memory-eval.json --k 5 --semantic-model nomic-embed-text:latest
```

The report includes mean Recall@k, Precision@k, Mean Reciprocal Rank and Hit Rate. It checks that every expected memory is active, unexpired and visible under the selected sensitivity policy. It does not change memories, embeddings or model weights. Use `--include-sensitive` only when the benchmark intentionally includes sensitive records.

Review possible lexical polarity conflicts separately:

```powershell
aie memory-conflicts
aie memory-conflicts --include-sensitive
```

These candidates are not semantic contradiction proofs. The tool flags a small, explicit list of opposing words with shared context and prints IDs/terms only; inspect the underlying records and timestamps before correcting anything.

## Reviewed memory consolidation and verified procedural skills

`aie memory-consolidate` identifies likely duplicate pairs but never changes memory. Review both records locally, then provide the resulting content explicitly to the separate merge command:

```powershell
aie memory-merge <MEMORY_ID_A> <MEMORY_ID_B> "User-reviewed combined procedure"
# Preview only. To commit the merge:
aie memory-merge <MEMORY_ID_A> <MEMORY_ID_B> "User-reviewed combined procedure" --confirm
# Sensitive source records require a separate opt-in:
aie memory-merge <MEMORY_ID_A> <MEMORY_ID_B> "User-reviewed combined procedure" --include-sensitive --confirm
```

A merge creates a new record and keeps both sources as superseded history. It retains both lineage links and provenance, will not reduce sensitivity, inflate confidence or extend expiry, and removes source embeddings so they cannot continue to appear as active memories. The resulting content is supplied by the user; the merge does not ask a model to invent a replacement.

Completed task runs can be inspected for verified procedural-skill candidates:

```powershell
aie skill-candidate <RUN_ID>
aie skill-save <RUN_ID> --confirm
# Explicitly choose internal sensitivity instead of the sensitive default:
aie skill-save <RUN_ID> --confirm --internal
```

Candidates require a completed run and at least one positive `verify` step. Action-bearing runs additionally require successful policy-ledger execution receipts and a verification step that depends on each action. The candidate is assembled deterministically from plan criteria and recorded step summaries. Saving creates a procedural memory linked to the originating task-run ID. It does not retrain a model or create an executable capability.

## Restricted Windows Settings capability

The only built-in action adapter opens one fixed Windows Settings page; it does not change a setting, run commands or launch arbitrary processes. To enable this adapter, create a user-managed manifest at `%LOCALAPPDATA%\AIE\capabilities\windows-settings-open.json` with:

```json
{
  "capability_id": "windows.settings.open",
  "description": "Open one fixed Windows Settings page.",
  "risk_tier": "low",
  "enabled": true,
  "allow_autonomous": false,
  "approval_required": true,
  "allowed_parameters": ["setting"],
  "max_invocations_per_minute": 3,
  "max_execution_seconds": 5
}
```

Only the keys `display`, `sound`, `bluetooth`, `network`, `windows_update`, `apps` and `privacy` are supported. The manifest must be explicitly enabled and each proposal separately approved.

```powershell
aie propose windows.settings.open "Open Display Settings" --parameters '{"setting":"display"}'
aie proposals
aie approve-proposal <PROPOSAL_ID>
aie execution-enable --confirm
aie execute-proposal <PROPOSAL_ID> --confirm
# Immediate stop for every registered adapter:
aie execution-kill
# Disable the positive execution marker:
aie execution-disable
```

`aie execution-resume --confirm` clears the kill switch, but does not itself enable execution. Each proposal is single-attempt and receives an append-only execution receipt. A successful `ms-settings:` dispatch is not proof that the requested page reached a specific state; inspect the desktop and use a separate verified task step when a postcondition matters. No shell, arbitrary executable, file-write, network or privileged adapter is included.
