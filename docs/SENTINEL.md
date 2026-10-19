# Sentinel Runtime — Windows

Sentinel is the persistent observation and diagnostics profile for AIE. It reuses the existing Windows perception providers and event store; it is not a separate agent stack.

## Runtime model

- One per-user Python worker runs independently of the dashboard.
- The worker can be started immediately or registered in Windows Task Scheduler for the current user's next and future sign-ins.
- The scheduled task uses an interactive, limited-privilege user token. It does not run as SYSTEM.
- A named Windows mutex prevents a second worker from collecting the same streams.
- A stop marker is checked by the observer loop. Pause and resume use the shared per-user AIE observer marker.
- The dashboard is a dependency-free local web interface bound only to 127.0.0.1. A random local token is required for its JSON API and controls.
- The activity stream reads the same SQLite event store used by AIE. Provider health, collection latency, event counts, system inventory and AI assessments are surfaced separately.
- Runtime state, dashboard token, log and SQLite data live under %LOCALAPPDATA%\AIE.

## Install and use

Run these commands from the repository after installing it into a Python 3.11+ environment:

    python -m pip install -e ".[windows]"
    aie sentinel install
    aie sentinel status
    aie sentinel dashboard

The install command creates the Task Scheduler entry named AIE Sentinel Background Watch and starts the worker now. Its logon trigger starts it after the current user signs in. The task is interactive-only and uses LIMITED privilege. It is not a boot-time SYSTEM service, and it is not designed to survive sign-out as a hidden system process.

Other commands:

    aie sentinel start
    aie sentinel stop
    aie sentinel status
    aie sentinel dashboard
    aie sentinel configure --event-logs
    aie sentinel configure --no-event-logs
    aie sentinel configure --window-titles
    aie sentinel configure --no-window-titles
    aie sentinel configure --ui-tree-apps msedge.exe,notepad.exe
    aie sentinel configure --no-ai
    aie sentinel configure --reset
    aie sentinel uninstall

Stopping the worker does not remove the logon task. Uninstall stops the worker and removes that task. Configuration changes are loaded after a worker restart.

## Default sensor profile

| Signal | Default | Collection boundary |
|---|---|---|
| Host and process lifecycle | On | Host metadata, process names, PIDs and creation times; no command lines or executable paths |
| Foreground application | On | Foreground process identity and window class; window title is separately opt-in |
| Process resource sampling | On | Bounded CPU, working-set, thread and I/O counters; top consumers only |
| Network telemetry | On | Interface counters and bounded DNS/TCP-connect diagnostics; no packet capture, browsing history or payload inspection |
| System inventory | Every 15 minutes | Bounded process, installed-application, service, scheduled-task and interface metadata |
| Application/System Event Log | Off | Metadata-only reader; no event message text, XML or Security log |
| UI Automation structure | Off | Requires an explicit executable allowlist; does not read control text, values or passwords |
| Kernel ETW process events | Off | Existing bounded process-lifecycle provider; elevated access may be required |
| Window titles | Off | Marked sensitive when enabled |
| Browser video intelligence | Separate opt-in | Existing browser extension/native-host workflow; playback/performance metadata only |

The inventory pass excludes install/uninstall command strings, full executable paths, environment variables, IP/MAC addresses, scheduled-task XML, and process command lines. The API response filters sensitive event classes and sensitive field names before data is sent to the dashboard.

The existing Windows provider also reads application metadata from the uninstall registry and task names/status from the built-in schtasks query interface. These are read-only queries; Sentinel does not start, stop, install, disable or reconfigure the discovered items.

## Local Ollama collaboration

Sentinel can run a two-stage analysis against the already-installed local Ollama models:

1. A fast 4B model triages a small, bounded packet of recent non-sensitive evidence.
2. A separate 6B model reviews the triage against the original evidence, challenges unsupported claims and lists uncertainty.

The stages run sequentially, and the Ollama request asks the server to release each model after its turn. A memory guard avoids selecting the 4B stage below 4.5 GiB available RAM or the 6B review below 8 GiB available RAM. If an exact 4B/6B tag is not available, AIE may use an eligible already-installed model from its existing local model policy. A missing model is never downloaded automatically. There is no remote/cloud fallback.

The output is a derived, evidence-linked event. Model text is advisory only: it cannot execute shell commands, change permissions, alter policy, or initiate Windows remediation. Ollama being unavailable does not stop the sensor loop.

Optional exact model tags can be set in the local config file at %LOCALAPPDATA%\AIE\sentinel-config.json. Use a tag that is already listed by ollama list. Default discovery is automatic.

## Windows tracing and privilege boundary

Sentinel uses documented Windows interfaces and the AIE providers rather than undocumented kernel hooks. Event Tracing for Windows (ETW) is a Windows tracing facility that can consume kernel or application events; the current AIE ETW provider is narrowly limited to process lifecycle metadata. It is optional and can require an elevated token.

The automatic logon task deliberately uses LIMITED privileges. Therefore, persistent kernel ETW collection is not promised by the default scheduled profile. An ETW provider that cannot obtain the required token reports a degraded provider state while the user-mode sensors continue. A separate narrowly privileged ETW companion would be required before persistent elevated tracing is enabled by default. Sentinel does not install a custom kernel driver.

Useful Microsoft references:
- Event Tracing for Windows: https://learn.microsoft.com/en-us/windows/win32/etw/event-tracing-portal
- About Event Tracing: https://learn.microsoft.com/en-us/windows/win32/etw/about-event-tracing
- schtasks create, including ONLOGON, /IT and /RL: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create
- Microsoft Windows classic API samples: https://github.com/microsoft/Windows-classic-samples

## Data and privacy controls

Sentinel is designed to observe the machine, not capture private content. It does not implement keylogging, credential extraction, clipboard scraping, microphone recording, hidden screenshots, packet-content inspection, browser history scraping, cookie collection, or arbitrary page-text collection. Window titles and UI Automation are sensitive/opt-in. Event-log and ETW providers are opt-in. The dashboard is local-only and does not upload telemetry.

Events are retained in the existing local AIE SQLite database. Use the existing AIE retention, export and delete controls to manage stored evidence. Protect the Windows account and local profile; local SQLite is not an encrypted vault.

## Prototype limits

- The dashboard and background worker are implemented in the repository, but they have not been installed or exercised on the target Windows desktop from this development session.
- The Windows CI build is not proof of Task Scheduler, ETW elevation, UI Automation, live browser bridge, or Ollama runtime behavior on the target machine.
- The inventory and provider sets are bounded and intentionally omit private payloads; “watch everything” is not interpreted as permission to collect secrets or all user content.
- Kernel ETW support is optional process lifecycle tracing, not a custom driver and not a complete kernel activity recorder.
