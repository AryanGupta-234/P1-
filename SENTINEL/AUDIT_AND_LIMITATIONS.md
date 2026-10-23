## UI revision 1.2.12

Agent heartbeats are rendered as a visual collector map; the full worker table remains available under a disclosure for auditing. The Engine Deck pulse rail surfaces the state of existing safety, runtime, AI, memory and WPR engines. These cards are descriptive and do not grant execution authority. All action decisions remain subject to backend policy and explicit confirmation requirements.

## UI revision 1.2.11

Network, Kernel and System views now expose measured telemetry through visual meters and a host summary. Long-form operational explanations are opt-in disclosures so the everyday interface emphasizes values and controls. The meters normalize their display only; their bars are not calibrated safety thresholds. Actual collector data and sample timestamps remain the source of truth.

# SENTINEL deep reliability and security audit

This note records the fixes made in the current repair build and separates code-level verification from checks that require the target Windows 10/11 host.

## Repair matrix

| Reported symptom | Root cause / risk | Repair in this build | Verification boundary |
|---|---|---|---|
| SCM service scan reports `WinError 2` | A disappearing service can raise during per-service reads; `powershell` may also resolve from a broken or untrusted PATH | Per-service exception isolation; full Win32_Service/CIM fallback; known Windows tools resolved from Sysnative/System32 before PATH; source health retained | Mocked SCM race and command resolution tests pass. Validate on the target machine and inspect provider health |
| Settings do not remember toggles / changes | UI settings need stable persistence and meaningful revision tracking | Feature/sensor toggles persist via SQLite plus JSON recovery mirror; recursive changed-key history; no-op saves do not create fake revisions | Unit tests and local API smoke pass. Confirm settings survive an actual Windows agent restart |
| Evidence sensor matrix / posture values null | Inventory omitted Defender, Firewall, Secure Boot and BitLocker component records from health/posture input | Preserve component-level provider health; incomplete sources remain unknown and do not become a green posture | Demo/API and unit checks pass. Hardware-/policy-dependent Windows providers still need live validation |
| Process list duplicates | PID alone is not a durable process identity because Windows can reuse PIDs | Use PID plus process creation time as the row and action identity; clean bounded state for exited identities | Unit checks pass; observe a long-running Windows session for live PID reuse behavior |
| Process list missing full path / app-vs-background ambiguity | Short dashboard summary did not show full bounded inventory; session ID alone does not prove a visible desktop app | Full process API (bounded to 2,000 records); executable path, parent, owner, CPU/RAM/I/O/threads/handles/session; physical-monitor intersection and DWM-cloak checks | API/demo tests pass. Win32 display APIs require a real interactive Windows test |
| Unsafe process termination | `psutil.Process.terminate()` is a hard process termination, not a graceful close | Reviewed process identity is rechecked; send `WM_CLOSE` to eligible visible windows; wait; never escalate to TerminateProcess or `taskkill`; autopilot cannot auto-terminate | Static/unit safety checks pass. Verify on a disposable GUI app on target PC |
| System tab blank at startup | View could render before first SSE tick and fail to retry | First telemetry tick requests System refresh; guarded refresh interval and visible errors; storage/source health blocks | Browser-level screenshot testing unavailable in this runtime; Node syntax and local API smoke pass |
| Demo System inventory is empty | Demo inventory imported a missing fixture | Explicit synthetic demo fixture and synthetic health status; not labeled as live Windows data | Demo API smoke passes; demo is never evidence of native Windows behavior |
| Kernel page implies ETW from paging graphs | Paging/DPC charts are PDH counters, not ETW trace events | PDH and WPR/ETW status are separate; unrecognized WPR output stays `unknown`; bounded approved WPR capture stores ETL | Parser/unit tests only. Actual WPR session, provider coverage and ETL contents are unverified until run on Windows |
| GUI animation / present telemetry absent | No present-history ETW event decoder or frame-pacing model is wired to the UI | UI describes the scope correctly; no invented FPS/frame latency values | Per-frame DWM/ETW animation timeline is not implemented in this build |
| AI status/usage unclear | Runtime health and inference usage were not presented together | Agent PID/session/resources; AI status/task/model; retained success/failure/latency/token usage; memory fallback reason | API and demo smoke pass. Actual inference requires installed and running local Ollama |
| Data loss / nonpersistent controls | Need one durable source of truth across settings and memory workflows | Existing SQLite extended with settings, config history, AI usage, memory revisions, goals and evidence; Windows directory ACL tightened; DPAPI cloud-key storage | DB/API and simulated DPAPI tests pass. Native Windows DPAPI and ACL must be checked on target machine |

## Process visibility semantics

The UI separates the following states:

- **Session 0 / service:** not part of the logged-in desktop.
- **Interactive session:** process has a nonzero session identity; not proof of a visible window.
- **Window visible:** Windows reports a top-level window visible.
- **On physical monitor:** window bounds intersect an enumerated monitor rectangle.
- **Cloaked:** DWM reports the window cloaked; not treated as an interactive visible app.
- **Foreground:** process currently owns the foreground window.

These are OS observations, not a claim that a human is watching the app. Process “heavy” or “background” review is advisory and scoped to known review candidates and sustained usage thresholds. There is no universal safe algorithm that can determine whether an arbitrary process is useless. No process is auto-killed. A close request is sent only after explicit review and is limited to `WM_CLOSE`; an app that refuses to exit remains running.

## Kernel telemetry semantics

- Live DPC, interrupt, page-in/out, page-read/fault, commit and disk metrics are sampled through Windows PDH / Performance Counters (`typeperf`).
- WPR session state is queried independently through `wpr -status`. `recording=True` requires recognized positive status output; `False` requires recognized negative output; any ambiguous output is `unknown`.
- ETL capture is a bounded Windows Performance Recorder trace. The file is not equivalent to a decoded live timeline. Use Windows Performance Analyzer / GPUView to inspect event providers, scheduling, present history and frame timing.
- This build does not yet decode DXGI/DWM present events into real-time per-window FPS, dropped-frame or input-to-photon measurements. Do not infer those from DPC or paging counters.

## Persistence boundaries

Windows runtime DB: `%ProgramData%\Sentinel\sentinel.db`.

- Events, actions, insights, AI transcripts, AI inference usage, settings/config history, memories, goals, agent runs and ETW trace metadata persist until explicitly deleted.
- High-frequency metrics remain raw for `retention_days` (14 days by default), then are compacted into permanent hourly sample-count, average, minimum and maximum aggregates. The Kernel tab exposes this archive.
- Latest-state snapshots are updated by key; they are not a historical snapshot archive.
- Uninstall removes the scheduled task and shortcut but preserves the DB, settings and trace files.
- Windows optional cloud API key uses DPAPI for the interactive user. If decrypt fails, the application fails closed by not restoring the key. Re-enter the key to persist it again.

The retention policy deliberately preserves long-term history while bounding high-frequency raw telemetry. Hourly rollups retain trend statistics, not each original one-second sample.

## AIE capability verification

The six earlier AIE integration claims are present in this source build with these boundaries:

1. **Evidence intelligence:** bounded observed-state projection and evidence references; missing observations do not imply removal. Not full AIE event-store/provider parity.
2. **Persistent memory:** five memory kinds, provenance, confidence, sensitivity, revisions, TTL, lexical and local semantic retrieval. Records are user-directed; there is no automatic memory consolidation or continual self-writing.
3. **Goal management:** persistent goals, ordered dependency-aware steps, transition history, pause/resume and guarded completion.
4. **Plan generation:** local model JSON plan suggestions, schema/dependency validation and integrity-checked pending drafts. Acceptance creates steps only; no actions execute.
5. **Hardware-aware inference:** model discovery and live RAM guard; DEEP falls back below 7.5 GiB and resumes at 8 GiB. Models are not automatically downloaded.
6. **UI Automation:** bounded read-only tree structure inspection in an interactive user session. No text/value/password content, screenshots or UI interaction are collected.

## Validation summary

The current source build passes:

- `python -m py_compile agent.py sentinel/*.py tests/*.py`
- `node --check ui/app.js`
- `python -m pytest -q` — 54 tests (portable SENTINEL regression suite; Windows-native behavior still needs target-host validation)
- local authenticated API smoke in `--demo` mode, including System inventory, process list, Kernel archive endpoint, storage, profile and Intelligence context.

The demo smoke uses synthetic inventory / telemetry and does not validate Windows APIs. Browser screenshot automation could not be run in the build environment. The following must still be checked on the real Windows machine: SCM/CIM access, scheduled task identity and ACLs, native DPAPI, monitor/window enumeration, UI Automation, WPR start/status/stop and actual ETL provider coverage, physical PDH counters, local Ollama chat/embedding, and behavior of WM_CLOSE against a disposable GUI application.


## Durable history policy

- Events and audit/action records are not removed by the hourly maintenance job.
- AI transcript and inference-usage rows are retained; no newest-N truncation is applied.
- Settings, configuration revisions, memories, goals, goal history, run history and ETW trace metadata persist until explicitly deleted.
- One-second metrics remain raw for `retention_days` (14 by default). Before raw rows age out, they are folded into permanent hourly sample-count, average, minimum and maximum aggregates.
- The Kernel tab exposes the hourly archive. This is a deliberate storage/performance trade-off: it preserves long-term trend evidence, not every individual 1-second point forever.


## Advanced game-session tuning foundation (added 20 October 2026)

- Every supported mutating action is snapshotted in `action_journal` before execution, with risk, dry-run metadata, undo payload, result, and revert result. Unsupported/unreversible actions are refused; old actions from before the journal existed cannot be reconstructed or reverted. `REVERT ALL` only reverses changed entries with a captured undo payload, and it preserves external changes when the current state no longer matches the exact value SENTINEL applied.
- Risk tiers: bounded diagnostics are safe but unattended capture is off until the operator separately opts in; power/profile/timer/Wi-Fi/updater changes are medium and need explicit approval; standby-list flush, arbitrary process close/kill, memory trimming, generic background priority, DNS flush, and fan control are dangerous and disabled.
- Session-scoped power, timer, Wi-Fi policy and approved allowlisted updater actions are linked to the detected game session. They are automatically restored on game exit and SENTINEL startup recovery. Reboot/process crash recovery restores eligible external state; process-specific scheduling settings naturally cease when that process exits. Timer-resolution requests are process-owned and Windows drops them when the previous Sentinel process exits.
- Closed-loop experiments require at least eight recent samples, explicit action approval and a fresh pre-action baseline. They evaluate a 45-second window after a 60-second settling period; less than 3% measured improvement triggers rollback. It is a single-metric heuristic, not a controlled A/B test. Do not change other system settings during a trial.
- Baselines are per game and local hour, using running mean/variance and sample counts. Baseline deviations and session reports correlate temporally adjacent Event Log, process, network, thermal, ETW and SENTINEL action evidence. Correlation is not proof of causality. No FPS/frame-time values are invented when no frame telemetry source exists.
- Six local AI specialist prompts are available (frame time, driver/ETW, thermal, network, memory/I/O and profile tuner). They explain evidence and propose hypotheses only; the allowlist/risk/approval rule engine decides whether an action can be queued. Model discovery stays with the existing local Ollama adapter.
- ETW uses the Windows Performance Toolkit `xperf` NT Kernel Logger for bounded 12-second windows, no more than once every 120 seconds while a configured game is active after both ETW enablement and an explicit auto-capture opt-in. A manual capture is also available. It never starts a custom driver or interrupts an existing logger session. `tracerpt` metadata may provide PID/TID/process names; `xperf -a dpcisr` may provide `.sys` modules. If Windows/driver symbols or event data do not expose a module or PID, attribution stays unresolved. This is not an always-on, lossless streaming decoder or guaranteed per-spike causal attribution.
- GPU temperature, clocks, power and throttle flags use `nvidia-smi` when available. `nvidia-smi fan.speed` is a percentage, not an RPM value. CPU and per-core temperatures/fan RPM are read only from an already running external LibreHardwareMonitor WMI provider when the operator enables the reader; SENTINEL does not install, bundle or launch LHM. Missing CPU/fan sensors remain unavailable. Fan curves are never changed; supported ASUS devices should use Armoury Crate.
- This phase does not implement DWM/DXGI per-window FPS, dropped-frame or frame-pacing telemetry. It also does not implement standby memory flushing, automatic kill/trim operations, firmware fan control, voltage/overclocking, generic TCP registry tweaks, or guaranteed updater/network optimization.

Target PC validation still required: xperf provider/stack availability and event loss, actual driver-module symbol resolution, CPU Set API and priority changes, timer/power restore across game exit and crash, service stop/restart with third-party updater versions, Wi-Fi policy values on the installed adapter, NVIDIA fan reporting, and the optional LHM provider if separately installed by the operator.


## Phase 1–4 SENTINEL game-session implementation

The advanced game-session layer is an additive feature set in `sentinel/advanced.py`. It reuses the existing action approval flow and SQLite journal rather than creating a second executor. The runtime exposes dry-run previews, snapshots and conditional undo, a rate-limited action journal, an explicit Revert All confirmation, risk tiers, per-game profiles, per-game/per-hour rolling baselines, temporal correlation, session snapshots/reports, six evidence-only specialist AI prompts, a measured tuner, bounded ETW capture and thermal telemetry.

### Action and safety boundaries

- Safe actions are read-only bounded diagnostic captures. Automatic ETW capture is disabled until the operator separately enables the ETW observer and the existing `etw_capture` autopilot flag.
- Medium actions always require fresh user approval: game process priority/CPU placement, an AC-only power-plan change, a process-scoped 1–2 ms timer request, evidence-gated Wi-Fi AC power policy and allowlisted third-party updater pause.
- Dangerous operations are blocked: arbitrary process termination, working-set trim, standby-list flush, DNS flush, generic background-priority changes and fan control. Standby-list flushing cannot meet a trustworthy undo contract.
- Rollback compares current values with the exact values SENTINEL applied and preserves any intervening user change. Revert All attempts only journal entries with a recorded change and an undo handler; a result can be partial if an external change prevents safe restoration.
- Game-session exit and clean agent shutdown trigger best-effort restoration. After an interrupted agent run, a still-live exact game process resumes its session; a stale session is closed and eligible actions are restored.
- The closed-loop tuner starts only after measured samples and explicit approval, requires at least eight samples, waits for a post-change measurement window, and reverts if measured improvement is under 3% or evidence is insufficient. This is a single-signal heuristic, not a causal A/B test.

### ETW, attribution and sensor boundaries

- The advanced ETW observer uses Windows Performance Toolkit `xperf` NT Kernel Logger when installed. It captures bounded 12-second windows, at least 120 seconds apart, only during an active detected game and only after the operator enables both the feature and its explicit automatic-capture opt-in. Manual capture is also available. Existing logger sessions are never taken over or stopped.
- The capture requests process/thread/image, context-switch, DPC/ISR, interrupt, disk/file, hard-fault and network flags. `tracerpt` decodes a bounded event set and `xperf -a dpcisr` may name driver modules. PID/process attribution and DPC/ISR driver-module attribution are distinct evidence classes. An event without module/PID evidence remains unresolved. This is periodic bounded ETW sampling, not continuous always-on event streaming; event coverage, stacks, symbol resolution and provider availability must be validated on the target Windows system.
- NVIDIA telemetry comes from `nvidia-smi`; the exposed fan speed is a percentage, not RPM. CPU/per-core temperatures and fan RPM are read only from an already-running LibreHardwareMonitor WMI provider when the user explicitly enables the reader. SENTINEL does not download, bundle, install or launch LHM. Missing sensors remain unavailable, not zero.
- CPU Set efficiency/performance grouping uses Windows `EfficiencyClass` and must be validated on the actual hybrid CPU. CPU Sets express scheduler placement preferences; they are not hard real-time reservations. No fan curves, firmware writes or ASUS fan-control changes are issued. Use Armoury Crate for supported ASUS fan modes.
- Temperature warning thresholds are configurable advisory early-warning values, not guarantees of a hardware throttle point. NVIDIA throttle flags are shown only when the GPU reports them. Per-core CPU temperatures and fan RPM require sensor availability. GPU clocks and wattage are shown only when `nvidia-smi` supplies readings.
- SENTINEL still does not decode per-window DXGI/DWM present history into true FPS, dropped frames or input-to-photon latency. Session reports do not invent frame metrics and do not claim causation from temporal correlation.

### Phase test boundary

The portable SENTINEL suite currently passes 55 tests, including journal/risk/rate-limit/rollback, game-session recovery, baseline/tuner, thermal source gating and UI/API behaviour. Python compilation and dashboard JavaScript syntax checks pass. Native xperf/WPR capture, CPU Set mapping, timer/power/Wi-Fi/SCM restoration, actual LHM WMI compatibility, NVIDIA sensor availability and game profile behaviour remain pending on the target Windows 11 laptop. No custom kernel driver is installed or required.

### GPU power / clock visualization

The Performance Intelligence workspace also renders a paired time-aligned waterfall from the same bounded GPU clock and power samples used by the sparklines. It is a normalized within-series history view, not a claim of synchronized hardware sampling beyond the collector timestamps. Missing or insufficient samples remain an explicit collecting state.


## Windows integration hardening — 21 October 2026

- **ETW attribution:** tracerpt XML decoding now captures per-event timestamps, reads PID values from event payloads as well as execution headers, builds a PID-to-image map from ProcessStart image events, and only falls back to the current process inventory when its creation time is not later than the trace end. A PID that appears to have been reused after the trace is left unresolved. Driver names are persisted only when a decoded field or the xperf DPC/ISR report explicitly identifies a .sys module. The decoder exposes attribution counts, sample events and whether an xperf driver report was available.
- **ETW ownership:** concurrent SENTINEL captures are serialized, trace filenames include sub-second uniqueness, and the owner always signals completion after attempting to close its logger. Shutdown wakes the capture worker and waits for its owned finalization before using a bounded emergency stop path.
- **ASUS/LHM sensors:** the optional reader now uses valid single-backslash WMI namespaces and probes both root\LibreHardwareMonitor and the legacy root\OpenHardwareMonitor. CPU classification accepts Intel/AMD hardware identifiers and model names rather than requiring the literal word CPU; core temperatures and numeric fan RPM are separated from GPU sensors. The reader remains opt-in and only queries an already-running provider. ASUS embedded-controller fan sensors may still be unavailable on some firmware/driver combinations; the UI now surfaces provider-specific CPU/fan availability reasons.
- **Session rollback:** the session row is no longer marked completed before linked undo operations run. Failed undos leave restore_pending, are retried by the runtime, and are retried during startup recovery. Duplicate links to the same profile action are deduplicated. Undo is serialized within the process; transient failures to read/restore CPU Sets, power plans or updater service state remain retryable rather than being silently marked reverted.

Regression coverage was added in tests/test_advanced_windows_integrations.py for ETW ProcessStart/DPC attribution, PID-reuse rejection, LHM sensor classification and startup/session rollback retry. These are deterministic parser/policy tests, not proof of actual xperf symbol resolution, laptop sensor exposure or Windows scheduler/SCM restoration.

**Still requires target-machine validation:** install Windows Performance Toolkit if needed and capture ETL during a reproducible DPC/ISR spike; verify that xperf resolves the responsible .sys module and inspect the ETL in WPA. Run the optional LHM reader while LibreHardwareMonitor is already running and confirm CPU Package/Core and ASUS fan RPM availability. Apply a reversible game profile on a disposable session, end the game, restart SENTINEL during an active session, and verify the action journal and external power/process state. No custom driver is installed, no fan curve is written and no hardware sensor software is bundled.


## Windows integration follow-up — 21 October 2026

### ETW event attribution
- The bounded NT Kernel Logger decoder consumes the event timestamp, PID from payload/header, thread ID, event provider/task/opcode and explicit image/module fields.
- Process names are resolved from ProcessStart events only when that start timestamp is at or before the event being attributed. A live process-list fallback is guarded by process creation time. A PID reused later in the same trace is not allowed to name earlier events.
- Driver attribution is reported only when an event field or xperf's DPC/ISR summary explicitly names a `.sys` module. The trace's event and driver-report availability/counts are exposed separately. Missing stacks, symbols or module records remain unresolved.
- SENTINEL serializes its own ETW capture windows and finalizes only its owned logger. This is bounded capture/decoding, not a continuous real-time kernel event stream.

### Hardware sensor providers
- CPU/package/core temperatures and fan RPM remain opt-in and read-only. SENTINEL tries the LibreHardwareMonitor / OpenHardwareMonitor WMI namespaces, then the explicitly configured local LibreHardwareMonitor HTTP `GET /data.json` endpoint (default port 8085) if WMI is unavailable or incomplete.
- REST requests are sent only to fixed loopback address `127.0.0.1`, only to `/data.json`, with a 3-second timeout and 4 MiB response cap. SENTINEL does not follow redirects, call sensor-control endpoints, start LHM, install LHM, or bundle its binaries. HTTP authentication-enabled servers return an explicit unavailable status; credentials are not stored by SENTINEL.
- The tree reader is bounded by node/depth limits, uses `SensorId`, `Type`, `RawValue` and hardware identity, rejects non-finite readings, and separates CPU temperatures from GPU temperatures. ASUS embedded-controller fan sensors are not guaranteed by model/EC/firmware; if LHM does not expose fan RPM, the UI reports the reason rather than fabricating a reading. Fan curves are never written; use Armoury Crate for supported ASUS fan modes.
- LibreHardwareMonitor's official server serializes a hardware tree at `/data.json` with sensor IDs/types/raw values and hardware IDs; its test client reads the endpoint on localhost. WMI behavior is version-dependent, so SENTINEL retains both read paths. (Implementation references: the upstream HTTP server and its basic REST test script.)

### Session rollback guarantees
- A game session is only marked completed after its linked journal actions have been undone or safely preserved because the external state changed independently.
- Failed restores remain `restore_pending`; the agent retries them during runtime and on startup. The original game end timestamp and performance snapshot are retained across retries.
- If SENTINEL cannot observe the exact post-apply CPU Set/process state, it does not guess. The action stays un-reverted and the session stays pending for retry/manual review. This may remain pending until the process exits or Windows exposes enough state to restore safely.

### Validation boundary
- Added deterministic regression tests for ETW attribution and PID reuse within a trace, WMI and loopback REST sensor-tree parsing, ASUS CPU/core/fan classification, startup/runtime session restore retries, journaled power-plan undo, and fail-closed unknown CPU Set state.
- The Windows CI matrix compiles SENTINEL, checks dashboard JavaScript and runs SENTINEL tests under Python 3.11 and 3.12. A green hosted Windows CI run validates mocked and portable logic, not xperf symbol resolution, this ASUS embedded-controller sensor map, or live state restoration on the target laptop.
- Target-machine validation remains required: capture an actual trace with Windows Performance Toolkit installed and inspect xperf/WPA driver modules; launch LHM manually with its localhost Web Server enabled and confirm which CPU and ASUS fan sensors appear; then test a disposable game session with power/process profile changes, normal game exit, agent restart and action-journal inspection.

## Autonomous approval and thermal telemetry update

- A dedicated deterministic Approval Engine now computes risk (0–100), priority and confidence independently. Dangerous actions remain blocked and cannot be overridden by the Control window.
- Automatic medium-risk approval is limited to game profiles, power-plan changes, timer-resolution requests and Wi-Fi AC power policy. It requires the global automation master, the separate Control-window policy, a supported preview, a fresh safeguard pass, risk ≤25, confidence ≥92%, and a verified undo snapshot captured immediately before execution. Updater pauses and graceful GUI close remain manual.
- The Control window exposes the autonomy master and reversible-medium policy, and pending actions display their risk score, priority and confidence. The 30-second cooldown is now scoped to the same action kind and exact target arguments; the existing global three-actions-per-minute budget remains.
- Thermal collection now probes Windows ACPI thermal zones when the optional LHM reader is disabled or unavailable. These are labeled as platform thermal-zone readings, not CPU-package/core measurements, and are not used for CPU-package threshold alerts. LHM remains read-only and opt-in; fan RPM and per-core readings still depend on hardware/provider support.
- This source-level update has not been executed on the target Windows host in this session. Validate Control-window automation, rollback, ACPI provider output, NVIDIA GPU temperature, and sensor health on the actual machine before relying on automatic tuning. Unsupported or empty hardware providers must remain explicitly unavailable rather than synthesized.


## v1.0.6 engineering additions

- Added a managed, checksum-pinned LibreHardwareMonitor v0.9.6 dependency with bounded ZIP extraction and a loopback-only read-only sensor endpoint.
- Expanded normalized hardware telemetry beyond temperatures/fans to expose CPU/GPU temperature, clock, power, voltage and load measurements plus a device/type/unit inventory. Unsupported readings remain unavailable rather than inferred.
- Fixed the Intelligence evidence selector to use the collection query helper, and normalized API collection payloads before rendering state, memories, goals and draft plans.
- Replaced the multi-column splash card and diagnostic copy with a compact centered startup ignition animation and one progress indicator.
- Hardware coverage still requires target-machine verification. Fan RPM, voltage, power and CPU clocks depend on firmware/embedded-controller support; optional PawnIO installation remains an operator decision.


## v1.0.7 activity intelligence and ETW audit

- Added an independent foreground activity engine with a bounded sampler, process identity, active/idle time, fullscreen/game context, local weekday/hour, dynamic semantic task clustering and observed app transitions.
- Window titles are used transiently for local token extraction only; URL/email strings and credential-oriented title contexts are redacted before tokenization. Raw window titles, browser page content, history, screenshots, keystrokes and form values are not persisted or collected.
- Added a dedicated Activity Intelligence dashboard with current focus, active/foreground/idle time, 24-hour activity rhythm, rolling 7-day app usage, task clusters, recent sessions and next-app suggestions.
- Added explicit observed-application opening and a separate learned auto-launch opt-in. Automatic launches are disabled by default and require repeated evidence, confidence >=0.80, stable active context, an existing observed executable under permitted app-install roots, no game/fullscreen context and launch cooldowns.
- Fixed usage semantics: app focus transitions are counted separately from hourly storage intervals; hourly segments do not increment the focus-session count.
- Corrected automatic ETW sampling to use inbox WPR as the required recorder. Xperf is optional for supplemental DPC/ISR module attribution. Automatic capture is separately opted in, bounded to 12 seconds and configurable at 120–900 second intervals.
- ETW automatic sampling uses trace preflight, VALORANT hard interlock, WPR ownership checks and a single-capture lock; no other tool's recording is stopped or cancelled.
- Remaining host verification: confirm Windows foreground API behavior on the target desktop, identify which laptop sensors and WPR providers are available, and observe real app transitions before enabling learned auto-launch.
