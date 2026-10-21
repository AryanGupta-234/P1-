# SENTINEL

**Windows gaming-performance guardian and diagnostics HUD.**

SENTINEL monitors system performance, correlates lag symptoms with likely causes, surfaces evidence, and proposes a constrained set of remediation actions. The dashboard is served locally and the agent uses a SQLite database for event history and metrics.

> SENTINEL is a user-mode Windows utility, not a kernel driver. It is a diagnostic aid; recommendations are not guarantees of improved performance.

## Features

- Live CPU, memory, paging, disk, GPU, network, process, and system telemetry.
- Rule-based diagnostics for CPU saturation, memory pressure, driver latency, disk stalls, and network jitter.
- Optional local Ollama model council (fast triage + deeper verification).
- Optional OpenAI-compatible cloud inference, disabled by default.
- Microsoft Learn and GitHub issue lookups, cached locally.
- Allowlisted actions with an approval workflow and configurable per-action autopilot.
- Event history, metrics, evidence, inventory, and trace visibility in the web HUD.
- Local HTTP server bound to `127.0.0.1` and token-authenticated API endpoints.
- Additive Intelligence workspace: evidence-linked environment state, explicit persistent memory and revisions, local semantic retrieval, dependency-aware goals, reviewed plan drafts, and read-only Windows UI Automation inspection.
- RAM-aware AI council DEEP-model fallback to FAST under memory pressure; the guard re-enables DEEP after headroom recovers.
- Windows startup installation through Task Scheduler with restart-on-failure settings.
- Dedicated Agent runtime view: live agent CPU/RAM, host comparison, threads/handles, collector health, background worker inventory and retained run history.

## Requirements

- Windows 10/11 for full telemetry and installation.
- Python 3.10 or later (Python 3.12 recommended).
- `psutil` (installed from `requirements.txt`).
- Optional: [Ollama](https://ollama.com/) for local AI inference.
- Optional: Windows Performance Recorder / `wpr` for ETW trace capture.

The `--demo` mode uses synthetic telemetry and can be used to preview the dashboard on other platforms. The full Intelligence feature set is documented in [INTELLIGENCE_INTEGRATION.md](INTELLIGENCE_INTEGRATION.md); UI Automation requires an interactive Windows user session and does not work from the default Session 0 SYSTEM task.

## Quick start

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python agent.py --demo
```

Open the HUD at `http://127.0.0.1:8765/`. For a real Windows telemetry session, run `python agent.py`. On Windows, every direct CLI launch (including `open`, `--demo`, `stop` and `uninstall`) checks the process token and requests UAC elevation when needed. If elevation is declined or cannot be verified, SENTINEL exits without starting. Non-Windows demo use does not require elevation.
The dashboard URL includes a generated access token. Keep it private.

## Windows installation

Run `install.bat` from the checked-out `SENTINEL` directory. The installer requests administrator permission through UAC, detects Python 3.11/3.12 (or offers Python 3.12 through winget), and reads the release from `VERSION` (semantic `MAJOR.MINOR.PATCH`).

Each release is installed into its own immutable directory:

```text
%ProgramFiles%\Sentinel\
  active-version.txt
  versions\
    1.0.0\
      .venv\
      agent.py
      VERSION
      sentinel\
      ui\
    1.0.1\
      .venv\
      agent.py
      VERSION
      sentinel\
      ui\
```

A new version is copied to a staging directory, checked for its required entry point/runtime/dashboard files, and only then moved into its final version directory. Its Python environment and dependencies are created for that release only. The installer does **not** mirror over an existing release folder or upgrade that release's virtual environment. Re-running the same version reuses the existing immutable files; publish a new `VERSION` value for changed code. Previous version folders remain available for rollback, and the active-version pointer changes only after task/shortcut/agent verification succeeds.

The installer registers `SentinelAgent` for the signed-in interactive user at logon with **RunLevel Highest** and restart-on-failure settings. It is deliberately **not** a Session 0 `SYSTEM` task: desktop-window inspection and user notifications require the interactive session.

It creates and verifies a **Desktop** shortcut (using the signed-in user's configured Desktop location, including redirected folders), a per-user Start Menu shortcut, and an **All Users Start Menu → SENTINEL** shortcut. It checks that each saved shortcut exists and points to the selected release's `pythonw.exe` and `agent.py open` command. It waits for the authenticated agent API and confirms the running process is elevated before showing `INSTALLATION COMPLETE`. When something fails, the installer prints an error and does not report success.

To install a new release, pull the repository and run the installer again:

```powershell
git pull origin main
cd SENTINEL
.\install.bat
```

Settings, SQLite history, traces and run records remain separately in `%ProgramData%\Sentinel`; they are never included in a release-folder copy or removed by an upgrade. The **AGENT** view reports process CPU/working-set RAM, host comparison, threads, handles, worker inventory and run history. The **Performance intelligence & reversible tuning** page also shows live collector samples independently of game-session baselines and optional temperature sensors.

Deep ETW capture uses the Windows **Performance Recorder (WPR)** command-line tool when it is available on the installed Windows 11 image. It records a bounded `GeneralProfile.Light` ETL window and never stops or replaces an existing WPR session. The **Windows Performance Toolkit / Xperf is optional**: it can add a DPC/ISR module summary, but is not needed to start a capture or decode ETL metadata with `tracerpt`. Kernel tracing requires an elevated administrator or Performance Log Users context. PDH/typeperf counters remain a separate performance-counter stream; they are **not** ETW event traces.

SENTINEL now has separate **Safeguard**, **Adaptive Runtime**, **AI Orchestrator**, **Unified Memory**, and **Process Intelligence** engines. The safeguard is enforced before action proposals and again at execution. A detected VALORANT process switches the agent to telemetry-only mode: WPR/ETW, power changes, process tuning, timer changes, service control and other system mutations are rejected. VALORANT game profiles are disabled; Riot/Vanguard and Windows processes are excluded from process actions. SENTINEL installs no kernel driver, reads no game memory, injects no code, and does not change Vanguard or Windows security settings. Process-start intelligence uses explainable metadata heuristics and is advisory; it is not an antivirus verdict and does not terminate processes. The adaptive runtime reduces SENTINEL's own process polling, inventory scans and local model inference when a game is active or host resources are under pressure.

To remove the application, tasks and shortcuts, run `uninstall.bat` as administrator. It removes the installed version folders but preserves `%ProgramData%\Sentinel`; delete that data directory manually only when you intentionally want to erase local settings, history and traces.

## Optional local AI

Install Ollama and pull suitable chat models, for example:

```powershell
ollama pull qwen3:4b
ollama pull qwen3:8b
```

SENTINEL auto-detects installed non-embedding Ollama models unless explicit model names are configured. The additive Intelligence workspace can also use this optional local model set for its hardware-aware routine/complex/embedding recommendations:

```powershell
ollama pull qwen2.5:3b-instruct
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text:latest
```

These are optional, must be installed by the operator, and are never downloaded automatically by SENTINEL. Complex inference falls back to the installed 3B model below 7.5 GiB of available RAM; the live AI council resumes its requested DEEP model at 8 GiB.

## Data and configuration

On Windows, runtime data is stored under `%ProgramData%\Sentinel`. On other platforms, demo data is stored under `~/.sentinel`.

- `config.json`: token, model endpoints, profile, and automation settings.
- `sentinel.db`: SQLite telemetry, events, insights, actions, intel cache, configuration revisions, AI usage, inventory/evidence, memories, goals and plan drafts.
- `traces/`: WPR/ETW `.etl` trace output.

Settings and feature toggles are saved to SQLite and mirrored to `config.json`; unchanged settings do not create a new revision. On Windows, the optional cloud API key is protected using the signed-in user's DPAPI profile in both persistent stores. If that profile cannot decrypt the key, the key is omitted from persistence and must be entered again.

Durable local storage uses SQLite. Events, actions, insights, AI transcripts, AI inference usage, settings/revisions, memories, goals, agent runs and ETW trace metadata are retained until explicitly deleted; uninstall does not erase them. High-frequency raw metrics are retained for `retention_days` (default 14 days), then compacted into permanent hourly count/average/minimum/maximum aggregates. This keeps long-term trends without allowing one-second telemetry to grow the database without bound. ETL trace files remain in the protected trace directory; their catalog metadata survives agent restarts.

Do not commit runtime data, tokens, or cloud API keys.

## Developer validation

Install test tooling separately from the minimal runtime requirements:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --check ui/app.js
python -m py_compile agent.py sentinel/*.py tests/*.py
```

The automated suite includes portable unit and demo/API checks. It does not substitute for the target-host Windows validation matrix in [AUDIT_AND_LIMITATIONS.md](AUDIT_AND_LIMITATIONS.md).

## Security and privacy notes

- The HTTP server binds to loopback (`127.0.0.1`); it is not designed to be exposed to a network.
- API requests require the generated local token. Treat the tokenized HUD URL as a credential.
- Cloud inference is opt-in and uses `SENTINEL_CLOUD_KEY` when provided. Review the data sent to any configured provider before enabling it.
- The action layer is allowlisted and risk-tiered. Medium-risk game, power, timer, Wi-Fi and updater changes require fresh explicit approval. Dangerous actions—including DNS flush, standby-list flush, arbitrary process termination, working-set trimming, broad background-priority changes and fan control—are blocked. Safe ETW captures are bounded and run unattended only after the operator explicitly enables the relevant capture opt-in.
- The installer registers a highest-available interactive-user scheduled task. Treat the process and its local API token as privileged user-session software; review `agent.py` and `install.bat` before deployment.
- Use this tool only on systems you own or are authorized to administer.

## Project layout

```text
.
├── agent.py
├── sentinel/       # telemetry, diagnostics, AI, actions, inventory, local API
├── ui/             # dashboard HTML, CSS, and JavaScript
├── install.bat
├── uninstall.bat
├── requirements.txt
└── README.md
```

## Advanced game-session tuning (new)

The **TUNER / THERMAL** workspace adds a snapshotted reversible-action journal, dry-run previews, action rate limits, risk tiers, session-scoped restore, per-game/per-local-hour baselines, temporal cause-correlation candidates, session before/after reports, and six specialist AI modes. AI is advisory only; rule-based risk policy and explicit approvals control actions.

Per-game profiles can set process priority, CPU affinity/Windows CPU Sets, optional allowlisted background-process efficiency-core placement, an AC-only power plan and a process-scoped timer request. Wi-Fi power policy is offered only with sustained ping/jitter evidence, a connected Wi-Fi adapter and AC power. Updater pausing is restricted to a short allowlist of third-party services and is approval-only. Changes are restored at game exit or during recovery after a Sentinel restart when the previous state is still identifiable and has not been changed independently.

ETW capture uses optional Windows Performance Toolkit `xperf` for bounded 12-second NT Kernel Logger windows; automatic windows are disabled until explicitly opted into and are sampled no more than once every 120 seconds during a detected game. This is not a continuous decoded trace. Driver names appear only when xperf or event fields resolve a `.sys` module. Unresolved attribution remains unresolved.

NVIDIA GPU metrics use `nvidia-smi`. Fan speed is reported as a percentage unless an external sensor source reports RPM. CPU/per-core temperatures and RPM can be read from an already-running LibreHardwareMonitor WMI provider only after explicit opt-in; SENTINEL never installs or launches it. Fan curves are not written. Dangerous actions such as standby-list flushing, process termination, working-set trimming and fan control are disabled. The current UI does not decode per-window frame pacing or dropped frames.

See [AUDIT_AND_LIMITATIONS.md](AUDIT_AND_LIMITATIONS.md) for risk boundaries and the Windows validation matrix.

## Limitations

Telemetry availability depends on Windows version, hardware, drivers, language, and permissions. The Kernel page uses PDH / Performance Counters for live DPC, interrupt, paging and memory counters; these graphs do not by themselves prove an ETW trace is active. WPR status is polled separately and an unrecognized status is shown as unknown. Captured ETL traces must be inspected with Windows Performance Analyzer / GPUView for provider-level events. SENTINEL does not yet decode ETW present-history into a live per-frame animation/FPS timeline.

The Process page distinguishes service/background processes from GUI processes with a visible, non-cloaked window intersecting a physical monitor. This is stronger evidence of a user-visible app than a Session ID alone, but it is not proof that a person is looking at it. Process close requests send `WM_CLOSE` to the reviewed app and wait; SENTINEL never escalates that workflow to a force kill.

The demo mode is synthetic. It must never be used to validate actual Windows SCM, PDH, WPR/ETW, DPAPI, display-window enumeration, or UI Automation behavior. Run the Windows install and review the provider-health page on the actual machine. AI output is advisory and may be incorrect. Validate findings before taking remediation actions.

## License

No license is currently specified. All rights remain with the copyright holder unless a license is added.

### Windows integration reliability notes

The optional sensor reader probes the correct LibreHardwareMonitor WMI namespace and the legacy OpenHardwareMonitor namespace, classifies Intel/AMD CPU package/core sensors by hardware identity, and reports when an ASUS embedded-controller fan sensor is not exposed. SENTINEL never installs or launches either provider.

Game-session teardown now retains a restore_pending record when an undo fails and retries that record at runtime and on the next agent start. ETW parsing retains per-event timestamps, uses process-start image records and PID-reuse checks for process names, and names driver modules only when ETW fields or xperf DPC/ISR output actually identify a .sys module.

These additions have regression tests, but must still be validated on the target Windows laptop with Windows Performance Toolkit, the user's already-running optional sensor provider, and a real disposable game session. A portable test cannot certify device-specific sensor support or live driver-symbol attribution.


### Hardware sensors: WMI and loopback REST

SENTINEL reads optional hardware sensors only after you enable the sensor reader and start the sensor provider yourself. It first probes the supported WMI namespaces, then falls back to LibreHardwareMonitor's read-only local `GET http://127.0.0.1:8085/data.json` tree when configured. You can change the local port in the THERMAL sensor settings. The endpoint is loopback-only from SENTINEL's side; it does not follow redirects or call fan-control APIs. A provider configured with HTTP authentication is reported as unavailable because SENTINEL does not store hardware-monitor credentials.

For the REST path, start LibreHardwareMonitor yourself, enable its Web Server / Remote Web Server on localhost (default port 8085), and then enable SENTINEL's optional sensor reader. Availability of CPU package/core and ASUS embedded-controller fan RPM remains dependent on the exact laptop model, firmware and sensor provider. SENTINEL never installs or launches LHM and never writes fan curves.
