# Security and Privacy Boundaries

## Collection defaults
AIE is read-only and local-first. Default telemetry is limited to OS metadata required for inventory and process awareness.

Disabled by design:
- Keystroke capture, clipboard scraping and covert screenshots.
- Microphone, camera or ambient recording.
- Credential, token, cookie or browser-session extraction.
- Arbitrary document, email or private-message contents.
- Stealth persistence, privilege escalation or security-control bypass.

## Data handling
- Store under the current user's LocalAppData directory.
- Apply field allowlists; never serialize arbitrary process command lines by default.
- Preserve source, timestamp, host and sensitivity metadata.
- Implement retention and deletion before long-term monitoring.
- Cloud inference remains disabled unless policy permits the data class and task.
- Never commit credentials, API keys or personal telemetry.

## Kernel and privileged telemetry
Use supported Windows telemetry (ETW and Windows Event Log), with explicit providers, filters and bounded buffers. Some sources require administrative rights or special privileges.

A custom kernel driver is a separate security-critical deliverable requiring documented need, threat model, review, signing, compatible test systems, crash testing, user consent and removal procedure. It must not hide activity, bypass security tools, intercept credentials or collect unrelated content.

## Future actions
The observer has no execution capability. Future actions require a separate least-privilege policy broker, capability manifests, budgets, audit and verification. Destructive, privileged and externally visible actions require human approval.
