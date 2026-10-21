# Security notes

- The local dashboard token is an authentication secret. Do not publish tokenized URLs or runtime `config.json`.
- Keep the HTTP listener on loopback. Do not expose port 8765 to a LAN or the public internet.
- Cloud inference is disabled by default. When enabled, diagnostic context is sent to the configured API provider; inspect that provider's retention and privacy terms.
- The installer creates a highest-available interactive-user logon scheduled task with restart-on-failure. It deliberately does not run as `SYSTEM` in Session 0, because desktop inspection and user notifications require the signed-in session. The per-user process and token should still be treated as privileged software.
- Automatic remediation is disabled by default. Review each allowlisted action before enabling its autopilot setting.
- Report security issues privately to the repository maintainer rather than opening a public issue containing secrets or exploit details.


Advanced tuning actions are risk-tiered. Dangerous/non-reversible operations
(standby-list flush, arbitrary process termination, generic memory trimming,
fan control and broad process-priority changes) are blocked. Medium-risk game
profiles, power/timer changes, Wi-Fi power policy and allowlisted updater pauses
require explicit approval and are session-linked for best-effort restoration.
Undo refuses to overwrite state that changed independently after SENTINEL's
action. ETW is bounded and never interrupts an existing kernel logger. Optional
LibreHardwareMonitor access is read-only, opt-in, and requires an external
instance already running; no driver or sensor utility is installed by SENTINEL.