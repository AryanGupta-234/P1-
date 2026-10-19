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
| Registry intelligence | Every 3 minutes | Read-only, allowlisted Windows configuration keys; service/driver metadata and autorun name/change detection |
| Deep Windows inventory | Every 15 minutes | CIM OS/CPU/driver/disk/PnP metadata, Defender status and firewall profiles |
| Microsoft knowledge crawler | Every 6 hours | Fixed Windows topics from Learn plus selected MicrosoftDocs/classic-samples Markdown; locally indexed |
| Application/System Event Log | Off | Metadata-only reader; no event message text, XML or Security log |
| UI Automation structure | Off | Requires an explicit executable allowlist; does not read control text, values or passwords |
| Kernel ETW process events | Off | Bounded process-lifecycle provider; elevated access may be required |
| Window titles | Off | Marked sensitive when enabled |
| Browser video intelligence | Separate opt-in | Existing browser extension/native-host workflow; playback/performance metadata only |

The inventory pass excludes install/uninstall command strings, full executable paths, environment variables, IP/MAC addresses, scheduled-task XML, and process command lines. The API response filters sensitive event classes and sensitive field names before data is sent to the dashboard.

The existing Windows provider also reads application metadata from the uninstall registry and task names/status from the built-in schtasks query interface. These are read-only queries; Sentinel does not start, stop, install, disable or reconfigure the discovered items.

The registry sensor is an allowlisted configuration observer, not a recursive hive dump. It reads selected OS/build, UAC, Device Guard/HVCI, Secure Boot, crash configuration, selected Defender policy and Remote Desktop configuration values, plus bounded service-registration metadata. It watches Run/RunOnce entry names and compares in-memory fingerprints to detect changes; it does not persist autorun command strings or full image paths. It does not read SAM, SECURITY, LSA secrets, credential stores, user secrets, or protected process memory. It opens keys for read access only.

The deeper CIM snapshot queries documented Windows management providers for OS/computer/CPU information, system-driver and signed PnP driver metadata, fixed-disk capacity, present PnP status counts, Microsoft Defender status and Windows Firewall profile state. It does not collect serial numbers, device instance IDs, process command lines, executable paths or event-message content. Some Defender or PnP classes may be unavailable on a given Windows edition or configuration; an unavailable subsystem is reported as a degraded inventory pass rather than treated as an empty successful result.

This is not literal read-every-byte-of-the-kernel monitoring. Sentinel does not map kernel memory, dump arbitrary process memory, attach a debugger, install a custom kernel driver, or bypass Windows access controls. ETW remains the supported kernel tracing interface; the current adapter is narrowly limited to process lifecycle metadata. Thread, image-load, registry and other ETW categories are not claimed as active until the pinned provider implementation and coverage are separately validated.

## Microsoft technical knowledge crawler

The crawler is read-only and uses outbound HTTPS GET requests only. It searches a fixed set of Windows engineering topics on Microsoft Learn and reads selected Markdown files from these Microsoft-owned repositories:

- MicrosoftDocs/win32
- MicrosoftDocs/windows-driver-docs
- microsoft/Windows-classic-samples

Repository trees are ranked by Windows-internals topics before a small fixed number of Markdown files is fetched. The crawler validates allowed source hosts after redirects, caps response sizes and stores page text in %LOCALAPPDATA%\AIE\knowledge\microsoft-knowledge.sqlite3. The corpus is local; it does not upload machine inventory, event data or personal files. The Microsoft Learn search endpoint is a public site endpoint rather than a guaranteed stable product API, so failures are isolated and the crawler may need maintenance if Learn changes it.

Use the local knowledge CLI:

    aie knowledge crawl
    aie knowledge status
    aie knowledge search "kernel ETW registry"

Sentinel performs an initial knowledge crawl after it starts collecting and repeats on the configured cadence (default six hours). Tune or disable this background activity with:

    aie sentinel configure --knowledge-interval 21600
    aie sentinel configure --no-knowledge

Registry and deep inventory controls:

    aie sentinel configure --registry-interval 180
    aie sentinel configure --no-registry
    aie sentinel configure --deep-inventory-interval 900
    aie sentinel configure --no-deep-inventory

Configuration changes are applied after restarting Sentinel. The dashboard includes live registry/CIM/ETW/knowledge status and a search field backed only by the local knowledge database.

The Sentinel command deck also exposes live, authenticated controls for the independent registry, deep-CIM, Microsoft knowledge and local-AI schedules. Profile changes are validated against a fixed allowlist, written atomically to the local config file and loaded by the worker on its next observer cycle. The UI does not expose sensitive opt-ins such as foreground window titles, Event Log, UI Automation or ETW; those remain explicit CLI choices.

The command deck can queue a bounded system inventory scan, a deep CIM scan, a registry snapshot, a local AI review or a Microsoft knowledge crawl. Requests enter a small in-process queue and are dispatched by the worker; duplicate work is skipped while that collector is already busy. The dashboard reports the latest command state and the resulting events remain in the local event vault.

Ask Sentinel is a user-triggered local Q&A surface. It builds a bounded packet from recent non-sensitive events, retrieves a few relevant documents from the local Microsoft knowledge index, and calls only an already-installed local 3B or 4B Ollama model when at least 3.5 GiB of RAM is available. It returns bounded evidence IDs and validated Microsoft reference links. There is no cloud fallback, automatic model pull, command execution, remediation or privileged action. An unavailable Ollama service is reported as an unavailable local AI request.

The redesigned Titan command deck surfaces system inventory counts, Windows build metadata, bounded fixed-disk capacity/free-space values, Defender booleans, firewall profile status, PnP health counts and the latest triage hypotheses/reviewer uncertainties. It uses the same loopback-only API, token and local SQLite store as the existing dashboard. Live resource charts continue to display sampled CPU and RAM; decorative motion does not generate or simulate telemetry.

The deep diagnostics view additionally queries Windows Storage cmdlets for bounded physical-disk health metadata when available, BitLocker volume status and encryption percentage (never recovery keys), and battery status/estimated charge/runtime. When WMI exposes both design and full-charge capacity, the UI calculates a capacity-retention estimate; this is a diagnostic ratio, not a vendor-certified battery-health test. The WMI estimated remaining runtime is displayed in the provider's documented minutes unit. Missing Windows modules, unsupported hardware or unavailable classes are reported as unavailable data rather than synthesized values. A filterable signed-PnP driver explorer reads the latest local CIM event; it does not query the internet. BIOS vendor/version and UEFI Secure Boot state are also collected where available; firmware serial numbers and BitLocker recovery material are never requested.

Ask Sentinel and the scheduled two-stage 4B/6B analysis share one inference lock. A Q&A request receives a busy response rather than launching a competing model while another inference is running, helping avoid unnecessary concurrent model memory use.

A local posture watch evaluates the latest snapshot for explicit signals: Defender antivirus or real-time protection reporting disabled; a firewall profile reporting disabled; physical storage reporting Warning/Unhealthy/Critical; PnP groups reporting Error/Degraded; and BitLocker protection reporting Off (shown as informational because protection may be temporarily suspended). A newly observed high/critical signal queues one local model review; repeated copies of the same finding are deduplicated. A Secure Boot-disabled finding is informational because firmware setup may be intentional. This automation is analysis-only and never changes Windows settings or starts remediation.



## Local Ollama collaboration

Sentinel can run a two-stage analysis against the already-installed local Ollama models:

1. A fast 4B model triages a small, bounded packet of recent non-sensitive evidence.
2. A separate 6B model reviews the triage against the original evidence, challenges unsupported claims and lists uncertainty.

The stages run sequentially, and each Ollama request asks the server to release its model after the turn. The 4B pass requires at least 4.5 GiB available RAM; the 6B review requires at least 8 GiB. Sentinel uses only installed 4B and 6B tags (automatic discovery or exact configured tags). It does not silently substitute unrelated model sizes, download missing models, or fall back to cloud inference.

Before model inference, Sentinel can retrieve up to three relevant entries from the local Microsoft knowledge index using the observed event categories. The 4B and 6B stages receive these bounded excerpts and source URLs as untrusted reference material. The dashboard shows the reference links used by the latest assessment. A model cannot turn a documentation snippet into permission to run a command.

The output is a derived, evidence-linked event. Model text is advisory only: it cannot execute shell commands, change permissions, alter policy, or initiate Windows remediation. Ollama or the crawler being unavailable does not stop the sensor loop.

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
- The Windows CI build is not proof of Task Scheduler, ETW elevation, Registry ACLs, CIM inventory, Defender cmdlets, PnP visibility, live browser bridge, or Ollama runtime behavior on the target machine.
- The Microsoft Learn search endpoint is not a contractual API; crawler compatibility must be monitored and maintained.
- The inventory and provider sets are bounded and intentionally omit private payloads; “watch everything” is not interpreted as permission to collect secrets or all user content.
- Kernel ETW support is optional process lifecycle tracing, not a custom driver and not a complete kernel activity recorder. Registry/CIM collectors are selected configuration snapshots and do not claim exhaustive system-state coverage.
