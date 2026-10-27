# SENTINEL 1.2.30 — Adaptive Agent Assist and deeper Storage Intelligence

SENTINEL's observer, collectors and dashboard run as the signed-in user with a standard token. Administrator-only maintenance is handed to a narrowly scoped helper only after the operator confirms the exact preview and approves Windows UAC. The helper accepts one short-lived SQLite-backed job ID, binds it to the same Windows principal and interactive session, rechecks the kill switch, safeguard and original state, and can execute only a fixed allowlist of maintenance action IDs. It cannot accept arbitrary commands, scripts or paths.

The initial Windows Knowledge Engine registers approved Microsoft/OEM documentation URLs, fetches only HTTPS pages from its official-domain allowlist, bounds response size/time, removes active page payloads, stores versioned text chunks locally and returns source/build/edition/architecture citations. Retrieval is local lexical search; indexed text is reference material, never executable instructions.

**Safety contract:** maintenance remains manual-only with a fresh preview and explicit confirmation. Declining UAC cancels the job. Steam/Epic game folders are never moved directly, OEM fan controls remain guided, and BIOS/firmware, Secure Boot, Defender/Tamper Protection and Riot Vanguard are not automatically modified.

# SENTINEL 1.2.23 — Windows Intelligence & Liquid Glass foundation

The consolidated upgrade backlog is [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). It covers the Windows Knowledge Engine, local specialist-model evaluation, evidence correlation, expanded maintenance library, goal-driven learning, scheduler, chat/voice, least-privilege elevation, boot optimisation and GUI-first redesign.

**Safety contract:** maintenance mutations remain manual-only; every write needs a fresh preview and explicit confirmation. Launcher-owned Steam/Epic folders are never moved directly. OEM fan controls remain guided. BIOS/firmware, Secure Boot, Defender/Tamper Protection and Riot Vanguard are outside automatic modification. The model is advisory and cannot grant permissions or execute commands.

## Agent health topology and Engine pulse rail (v1.2.12)

The Agent workspace now renders collector heartbeats as a compact status map with state, age and run count before the detailed worker table. The detailed timings and per-function notes remain available in an expanded view. The Engine Deck adds a five-part pulse rail for safeguard, adaptive runtime, AI admission, memory pressure and WPR availability; each state comes from the existing backend engine response. Intelligence routing, memory and plan-lifecycle explanations are also collapsed into optional disclosures. These are presentation-only changes and do not add collectors, authorize actions or change the underlying admission and rollback policies.

## Graphical telemetry workspaces and compact technical disclosures (v1.2.12)

Network, Kernel and System now open with visual telemetry surfaces: latency/jitter and throughput meters, DPC/interrupt/paging/disk meters, and a Windows host banner with memory headroom, Secure Boot state and installed-app count. These are fed from the existing local snapshot and inventory response; they do not introduce extra collectors or new background threads.

Technical explanations that are useful for audit but not needed for everyday interaction are collapsed into guided disclosures. Core status, measured values, trends, action buttons and safety controls remain visible. The signal meters distinguish missing samples from observed zeroes. Workspace animations use transform/opacity rather than continuous blur effects, with reduced-motion preferences respected.

## Startup data hydration and visual command cockpit (v1.2.12)

SENTINEL's splash screen is now a real workspace data-loading phase, not an animation-only prelude. It authenticates the local node, restores the initial snapshot, then awaits telemetry history, events, insights, safeguard/runtime policies, source status and AI transcript. It subsequently hydrates the operational workspaces (command, network, agent, system inventory, process field and thermal/ETW) and the remaining workspaces (kernel archive, activity intelligence, memory/goals, intelligence feed, AI, evidence, action control, configuration, task history and activity stream) before revealing the dashboard.

The loader uses a shared four-request asynchronous I/O limit and bounded request timeouts. This avoids flooding the local agent with dozens of concurrent requests and avoids starting duplicate Windows collectors in the browser; it reads the agent's existing collectors and caches. Each workspace exposes a real data-ready or degraded status. Missing or unsupported sources are not reported as successfully loaded. The first view is shown only after the preload batches finish; the splash has a short minimum display time so very fast machines still show the startup feedback.

The command workspace is a visual control surface: circular live CPU, RAM, GPU and DPC gauges, a recent multi-signal performance chart, a radar-style node summary and icon-led shortcuts to the main workspaces. Evidence, activity feeds, culprits and secondary telemetry remain available as expandable detail panels. The rest of the UI retains the current glass visual language, with animated page entry, panel highlights, orbital instrumentation and responsive layouts. Reduced-motion preferences are respected.

## Agent-first diagnostics and storage review (v1.2.30)

The background agent consumes structured Windows events and diagnostic insights, then persists contextual questions and conservative next-check suggestions in SQLite. It can deliver native Windows notifications while the HUD is closed. The local specialist model is advisory-only, bounded to two queued diagnosis attempts per hour, and admitted only when runtime telemetry is valid and CPU/memory headroom is available. Event evidence is filtered to omit credential-like fields before it is attached to a finding.

Storage Intelligence adds largest-file evidence, per-extension file counts, versioned Python site-packages, uv/Poetry/PDM/pipx, Go, Composer, Ruby, Conda and environment-overridden package caches. Bounded scan roots rotate through the selected folders so the same early directories do not consume every pass. A scan yields when game/foreground priority changes and resumes from the interrupted root later. Large/old files and package/cache footprints are review candidates only; NTFS last-access metadata is a weak signal, and the agent never deletes files or uninstalls packages.

The Adaptive Runtime treats missing CPU telemetry as unknown rather than idle, and optional diagnosis/storage work remains deferred until telemetry is healthy. These changes shed SENTINEL-owned work; they do not change other applications' priorities, affinity, services, power plan, or anti-cheat state.

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

Open the HUD at `http://127.0.0.1:8765/`. For a real Windows telemetry session, run `python agent.py`. On Windows, the observer/dashboard runs as the signed-in user with a standard token. Installation and uninstallation request Administrator permission. Individual maintenance actions request UAC only after you review and confirm their exact preview. The elevated helper accepts one short-lived, audited job ID; it cannot run arbitrary commands.
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

Deep ETW capture uses the Windows **Performance Recorder (WPR)** command-line tool when it is available on the installed Windows 11 image. It records a bounded `GeneralProfile.Light` ETL window and never stops or replaces an existing WPR session. The **Windows Performance Toolkit / Xperf is optional**: it can add a DPC/ISR module summary, but is not needed to start a capture or decode ETL metadata with `tracerpt`. This SENTINEL installer runs the agent with elevated administrator privileges and the Safeguard currently requires that administrator context; Performance Log Users-only operation is not enabled. PDH/typeperf counters remain a separate performance-counter stream; they are **not** ETW event traces.

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
- The action layer is allowlisted and risk-tiered. The Control window includes a deterministic Approval Engine that scores risk (0–100), priority and confidence. When the Feature Control automation master is enabled, the separate reversible-medium policy may auto-approve only game profiles, power-plan changes, timer requests and Wi-Fi power policy when the proposal is supported, safeguard-approved, risk is ≤25, confidence is ≥92%, and execution captures a verified undo snapshot. Updater pauses and graceful GUI close remain manual; dangerous actions—including DNS flush, standby-list flush, arbitrary process termination, working-set trimming, broad background-priority changes and fan control—remain blocked from automatic execution. Per-target cooldowns prevent repeated changes to the same target, while a global action budget remains enforced. Safe ETW captures are bounded and run unattended only after the operator explicitly enables the relevant capture opt-in.
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

NVIDIA GPU metrics use `nvidia-smi`. Fan speed is reported as a percentage unless the managed sensor library reports RPM. CPU/per-core temperatures and RPM are read by SENTINEL's direct, read-only library integration. Fan curves are not written. Dangerous actions such as standby-list flushing, process termination, working-set trimming and fan control are disabled. The current UI does not decode per-window frame pacing or dropped frames.

See [AUDIT_AND_LIMITATIONS.md](AUDIT_AND_LIMITATIONS.md) for risk boundaries and the Windows validation matrix.

## Limitations

Telemetry availability depends on Windows version, hardware, drivers, language, and permissions. The Kernel page uses PDH / Performance Counters for live DPC, interrupt, paging and memory counters; these graphs do not by themselves prove an ETW trace is active. WPR status is polled separately and an unrecognized status is shown as unknown. Captured ETL traces must be inspected with Windows Performance Analyzer / GPUView for provider-level events. SENTINEL does not yet decode ETW present-history into a live per-frame animation/FPS timeline.

The Process page distinguishes service/background processes from GUI processes with a visible, non-cloaked window intersecting a physical monitor. This is stronger evidence of a user-visible app than a Session ID alone, but it is not proof that a person is looking at it. Process close requests send `WM_CLOSE` to the reviewed app and wait; SENTINEL never escalates that workflow to a force kill.

The demo mode is synthetic. It must never be used to validate actual Windows SCM, PDH, WPR/ETW, DPAPI, display-window enumeration, or UI Automation behavior. Run the Windows install and review the provider-health page on the actual machine. AI output is advisory and may be incorrect. Validate findings before taking remediation actions.

## License

No license is currently specified. All rights remain with the copyright holder unless a license is added.

### Windows integration reliability notes

The optional sensor reader loads LibreHardwareMonitor's managed sensor library in-process, classifies Intel/AMD CPU package/core sensors by hardware identity, and reports when an ASUS embedded-controller fan sensor is not exposed. SENTINEL does not launch the monitor GUI or depend on its separate HTTP web server.

Game-session teardown now retains a restore_pending record when an undo fails and retries that record at runtime and on the next agent start. ETW parsing retains per-event timestamps, uses process-start image records and PID-reuse checks for process names, and names driver modules only when ETW fields or xperf DPC/ISR output actually identify a .sys module.

These additions have regression tests, but must still be validated on the target Windows laptop with Windows Performance Toolkit, the user's already-running optional sensor provider, and a real disposable game session. A portable test cannot certify device-specific sensor support or live driver-symbol attribution.


### Hardware sensors: WMI and loopback REST

SENTINEL reads optional hardware sensors from its managed LibreHardwareMonitor library and also checks Windows ACPI and NVIDIA sources. It does not require the monitor's Remote Web Server switch, avoiding the former inactive-server startup error.

CPU temperature availability and fan RPM depend on the model, firmware and provider. SENTINEL never launches the monitor GUI or writes fan curves.


## Managed hardware sensor provider (v1.0.6)

The Performance view can install the official LibreHardwareMonitor release from its explicit **Install Sensor Library** control. SENTINEL verifies the published SHA-256 before extraction and reads sensors directly in-process. No separate monitor window or HTTP endpoint is started.

The dashboard enumerates provider readings with device, sensor class and unit, including temperatures, CPU/GPU clocks, power, voltage, load and fan RPM when firmware exposes them. A zero-RPM fan value is preserved as an observed stopped-fan state. NVIDIA telemetry remains a separate fallback source. Windows ACPI values are identified as platform thermal zones rather than CPU package readings.

**Hardware limits:** LibreHardwareMonitor cannot create a sensor that firmware or the embedded controller does not expose. Laptop fan RPM, fan curves, CPU package power/voltage and some clock domains may remain unavailable on a particular ASUS model. No values are synthesized. Some sensor access may require LibreHardwareMonitor's optional PawnIO driver; SENTINEL does not silently accept the provider's driver prompt or install a kernel driver. The local endpoint is not exposed to the network.


## Activity Intelligence and automatic ETW sampling (v1.0.7)

### Foreground Activity Intelligence

The new Activity Intelligence workspace learns the applications and tasks actually used on the Windows desktop. A local foreground sampler records process identity, app focus intervals, active-versus-idle time, fullscreen/game context, local hour and weekday. Bounded window-title text is used only in memory to derive generic semantic terms; it is not persisted. The backend learning path is implemented independently of the dashboard in `sentinel/activity_learning.py`: task clusters use corpus-frequency-weighted semantic term similarity with recency weighting, while next-app predictions score repeated transitions against competing destinations, evidence age and local-hour distance. Models update from locally observed sessions and transitions; no cloud model or dashboard-side inference is involved.

App identity is derived from the observed executable path rather than a predefined application catalogue. The app usage view separates focus sessions from hourly storage intervals. Suggestions expose their observation count, confidence, current running state and launch eligibility.

Learned app launching is disabled by default. Enabling it is a separate policy action. Automatic launches require a repeated transition pattern, confidence of at least 0.80, an observed local executable under permitted installed-app folders, no already-running copy, at least 60 seconds of active use in the current foreground context, no game/fullscreen context, and both global and per-app cooldowns. It launches only the previously observed executable without arbitrary command-line arguments or shell execution. A manual OPEN APP action is available for eligible suggestions.

### Bounded automatic ETW sampling

Windows Performance Recorder (`wpr.exe`) is the actual ETW recorder. Xperf is optional and adds supplemental DPC/ISR driver-module decoding; it is not required to capture or decode the WPR trace. Automatic sampling has two separate controls: the ETW engine toggle and the explicit automatic ETW sampling opt-in. The dedicated ETW opt-in does not require the general system-action autopilot master.

When opted in, SENTINEL captures a 12-second `GeneralProfile.Light` trace at a configurable 120–900 second interval while a game or a stable, active foreground work session is present. The existing VALORANT interlock, trace preflight, external WPR-session ownership checks and single-capture lock remain mandatory. The capture path never stops or cancels a trace owned by another tool. Manual capture remains available when automatic sampling is off.


## SENTINEL 1.2.20 — restored workspace and guarded maintenance

The original graphite / lime / ember interface and full multi-module startup console are restored. All workspace datasets, including Maintenance, remain in the two-stage bounded boot hydration; the splash remains visible until each source reports ready or degraded.

The Maintenance workspace includes read-only inventory, DNS resolver timing, a local rule-based goal planner, startup controls, bounded temporary/shader cleanup, physical adapter and Winsock/IP repair, hardware-matched Windows Update driver selection with prior-package export and restore-point checks, rollback from an exported package, SFC/DISM, an allowlisted service set, power modes, NTFS retrim and identity-checked process tuning. Each system change remains previewed, explicitly confirmed, checked by the VALORANT/process-observer safeguard, administrator-gated where required and bounded by a rolling action budget. The maintenance kill switch defaults ON.

Diagnostic inventory runs on a background worker and defers WMI/driver scans during games or resource pressure. Idle and weekly schedules remain read-only. Disk trend sampling is bounded; thermal forecasts alert only. Game moves remain in launcher library tools; OEM fan controls remain guided through supported vendor software; BIOS, Secure Boot and security settings remain read-only.

The separate adaptive medium-risk tuner requires five consecutive measured improvements for the same action target and game in addition to the existing global automation master, policy toggle, fixed allowlist, risk/confidence checks, live safeguard and verified undo snapshot. Dangerous and maintenance actions cannot use that approval path.


## SENTINEL 1.2.21 — evidence intelligence and launcher planning

The Maintenance workspace now presents a local evidence-health summary with coverage, severity, confidence and supporting measurements for sustained CPU pressure, memory pressure, storage headroom, thermal elevation, GPU throttling, network degradation and selected security posture. It is heuristic evidence correlation—not an AI diagnosis guarantee—and recommendations remain advisory.

Read-only OEM discovery identifies the Windows BIOS manufacturer/model and supported thermal-profile utilities from installed-app inventory. Fan changes remain guided through signed OEM software; firmware/EC/ACPI register writes are disabled. Predictive thermal alerts are based on repeated samples and an estimated time to threshold, not a single instantaneous reading.

Read-only Steam and Epic manifest discovery feeds a game relocation planner. It validates source manifest, target NTFS volume and manifest install size plus 10% free-space headroom. SENTINEL does not move launcher-owned folders, edit manifests or touch save data; the actual move remains inside the launcher. Xbox / WindowsApps package folders remain outside direct relocation.


## 1.2.24 visual and planning foundation

The dashboard theme uses graphite `#171717`, deep forest `#06110c` and signal red `#a31c1b`, with green as the positive/active accent. Typography uses local Windows font stacks to avoid network-dependent startup. The detailed data-hydrating splash and existing API/DOM contracts are retained while the interface moves to the new liquid-glass system.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for phased TODOs and completion criteria.


## 1.2.24 — Runtime privilege separation and local Windows knowledge

The installed interactive task uses the limited token. The ProgramData data directory grants the signed-in user Modify access and retains SYSTEM/Administrators Full Control so the normal agent and its same-user UAC helper can share the local SQLite journal. Install/uninstall still require Administrator rights; observation, telemetry, dashboard and model routing do not.

For an administrator-required maintenance action, SENTINEL stores the exact action, arguments and before-snapshot in a one-use request that expires with the preview (maximum 180 seconds). The helper verifies principal/session identity, job state, action manifest, kill switch, Safeguard and before-snapshot, then calls the existing maintenance executor and journal. No reusable administrator token is stored. The UI reports standard-user/elevated state and job cancellation.

The Intelligence workspace adds a source registry and local retrieval UI. Source records retain URL, publisher, user-supplied licence metadata, component, build range, edition, architecture and API/command version. The ingest route accepts user-triggered HTML/plain-text pages from approved HTTPS vendor documentation hosts only, follows at most one same-host redirect, strips active page elements, and stores SHA-256-versioned chunks. Search filters by component and available Windows compatibility metadata and shows provenance with each result.



**Current trace privilege boundary:** WPR/ETW capture still has an Administrator requirement and is not yet connected to the per-action maintenance broker. It remains fail-closed in the standard-user task for this release; a dedicated trace-ticket broker is a tracked follow-up. Do not run the entire observer/dashboard elevated just to enable trace capture.


## 1.2.25 — Local Windows Specialist

The Windows Knowledge workspace now includes an advisory specialist endpoint. It combines a bounded set of current local telemetry with up to six locally indexed, build-aware documentation passages and asks the selected local Ollama FAST model for a structured diagnosis. Cloud inference is rejected for this workflow.

The response is validated against a strict schema. Evidence references must exist in the supplied packet, and proposed action IDs must belong to a fixed maintenance vocabulary. Raw commands and scripts are not accepted. The specialist cannot execute actions, approve changes, or change safeguards. Maintenance remains manual-only with fresh preview and explicit confirmation.


## 1.2.26 — Installer privilege-contract correction

The installer verifies the intended runtime: a non-elevated standard-user process in the signed-in interactive session, matching the installed version and expected Python executable. The previous post-install check incorrectly required the observer/dashboard to be elevated even though Task Scheduler deliberately registered it with `RunLevel Limited`.

The normal opener accepts a verified standard-user observer and no longer restarts it merely because it is not elevated. It replaces an explicitly mismatched runtime using the Limited interactive task and verifies the result. Unknown runtime identity fails closed. Administrator elevation remains required for installation/uninstallation and is requested separately for an explicitly approved privileged helper job.


## 1.2.29 — Agent-owned automation and Storage Intelligence

The running Windows agent now watches new warning/error events and high-priority insights, creates evidence-linked questions and suggested first fixes, and delivers native desktop alerts without depending on the dashboard being open. High-severity findings can receive an additional local FAST-model diagnosis when the adaptive runtime reports safe idle headroom. All AI output is advisory; existing manual preview, approval, Safeguard and rollback controls remain authoritative.

The new Storage Intelligence worker reports drive capacity, selected personal/developer folders, file extensions, hidden-file footprint, Python/Node/.NET/Rust/Java cache and package sizes, build outputs and secondary-drive top-level folders. It uses bounded metadata-only scans, defers during gaming/resource pressure, and offers review candidates rather than deleting files or uninstalling packages. Usage timestamps are treated as weak heuristics.

Assistant preferences, answers, notification history and scan settings persist in the existing local SQLite database. The Maintenance HUD only displays results and changes configuration; the agent owns detection, scanning, local AI analysis and notification delivery.
