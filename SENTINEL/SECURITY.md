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