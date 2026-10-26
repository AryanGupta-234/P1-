# Security notes

- The local dashboard token is an authentication secret. Do not publish tokenized URLs or runtime `config.json`.
- Keep the HTTP listener on loopback. Do not expose port 8765 to a LAN or the public internet.
- Cloud inference is disabled by default. When enabled, diagnostic context is sent to the configured API provider; inspect that provider's retention and privacy terms.
- The installer creates a highest-available interactive-user logon scheduled task with restart-on-failure. It deliberately does not run as `SYSTEM` in Session 0, because desktop inspection and user notifications require the signed-in session. The per-user process and token should still be treated as privileged software.
- Automatic remediation is disabled by default. Review each allowlisted action before enabling its autopilot setting.
- Report security issues privately to the repository maintainer rather than opening a public issue containing secrets or exploit details.


Advanced tuning actions are risk-tiered by the dedicated Approval Engine.
It reports an explainable 0–100 risk score, priority and confidence. With the
Feature Control automation master enabled, an explicit Control-window policy
allows auto-approval only for the reversible allowlist (game profiles, power
plan, timer resolution and Wi-Fi AC power policy), and only when the preview and
safeguard pass, risk is at most 25, confidence is at least 92%, and a verified
undo snapshot is captured immediately before execution. Updater pauses and
graceful GUI close remain manual. Dangerous/non-reversible operations
(standby-list flush, arbitrary process termination, generic memory trimming,
fan control, DNS flush and broad process-priority changes) are never
auto-approved. Undo refuses to overwrite state that changed independently
after SENTINEL's action. Per-target 30-second cooldowns and a global action
budget remain enforced. ETW is bounded and never interrupts an existing kernel
logger. LibreHardwareMonitor access is read-only; when it is disabled or absent,
SENTINEL also probes Windows ACPI thermal zones where supported. ACPI zone
readings are explicitly labeled as platform readings, not calibrated CPU
package/core temperatures. No driver, LHM instance or sensor utility is
installed by SENTINEL.

## Third-party hardware sensor provider

The optional managed LibreHardwareMonitor provider is downloaded only from the official GitHub v0.9.6 release and checked against its pinned SHA-256 digest before archive extraction. Extraction rejects traversal paths, symlinks, oversized archives and missing required files. Its HTTP listener is configured on IPv4 loopback only (`127.0.0.1:8085`); SENTINEL uses read-only GET requests and never calls fan-control endpoints. Installing the provider is an explicit operator action. Any optional PawnIO driver prompt is owned by LibreHardwareMonitor and requires the operator's decision; SENTINEL does not accept it or install drivers automatically.


## Foreground Activity Intelligence privacy and application launching

The activity service observes only the foreground HWND's process identity, executable path, window class, local idle duration and a bounded title string used transiently for local semantic tokenization. Raw titles are never persisted. URLs, email addresses and credential-oriented title contexts are removed before term extraction. The service does not collect browser page contents, browser history, keystrokes, form values or screenshots. Stored records contain process identity, duration counters, timestamps, generated topic terms and app-transition statistics. Activity retention defaults to 90 days and is configurable.

Learned auto-launch is disabled by default and has its own explicit switch. Candidates must be based on repeated observed transitions and a confidence threshold; their executable must already have been observed and must resolve to a local existing EXE under the configured Program Files or user-installed application roots. UNC paths, arbitrary commands and unobserved paths are refused. Launches are suppressed during games/fullscreen contexts and by global/per-app cooldowns. SENTINEL never launches an application from a title, URL, semantic token or model-generated command.

## Automatic ETW sampling

Automatic WPR sampling requires both the Performance ETW engine toggle and the separate ETW automatic-sampling opt-in. Its 12-second WPR GeneralProfile.Light captures are rate-limited and use the same VALORANT and WPR session ownership safeguards as manual trace capture. WPR (`wpr.exe`) is required; Xperf is optional for supplemental driver-module decoding. The ETW opt-in does not grant permission to unrelated state-changing actions.


## Proactive agent assistant and local AI diagnosis

The proactive assistant consumes the existing local event/insight stream and stores bounded evidence, questions, suggestions and user responses in the existing SQLite database. Agent notifications are rate-limited and deduplicated; desktop delivery originates from the signed-in agent process, not from JavaScript in the dashboard. The HUD is a read/configuration surface.

High-severity findings can be enriched by the existing local Windows specialist. This path uses only the local Ollama FAST model and local indexed documentation; it is deferred while games are active or CPU/memory headroom is insufficient. AI output is schema-validated, may cite only supplied evidence, and cannot execute commands, approve a maintenance operation or bypass the fixed action vocabulary and user-confirmed preview gate. The diagnosis switch is persistent and can be disabled.

## Storage intelligence and deletion review

Storage Intelligence reads file-system metadata only. It does not open file contents, follow symlinks, delete files, uninstall packages, alter package-manager state, or scan Windows/Program Files recursively. Its scope is a bounded list of personal folders, developer/package caches, known build/dependency directories and top-level data-drive folders. It reports partial coverage explicitly.

File access times on Windows are not treated as reliable proof of use or disuse. Recommendations are review candidates only. Hidden files may contain settings, state, credentials or active caches and are never treated as safe-to-delete merely because they are hidden. Every cleanup still uses the existing preview/confirmation/undo boundary.
