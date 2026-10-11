# Security and Privacy Baseline

## Threat model
AIE observes local Windows activity and may later propose or execute scoped actions. Threats include untrusted webpage content, prompt injection, malicious files, model hallucinations, over-collection, privilege escalation, runaway loops and accidental destructive changes.

## Controls
- Read-only sensors; no execution capability in perception providers.
- Least-privilege identity; passive monitoring must not require elevation.
- User can pause observation and inspect/export/delete retained data.
- Data minimization, sensitivity labels, bounded retention and local-first storage.
- No passwords, cookies, tokens, keystrokes, clipboard contents or form data collection.
- Browser content is untrusted data, never policy or authorization.
- Models cannot grant capabilities or edit policy.
- OS actions require policy-broker authorization, scoped capability, budgets, timeout and audit.
- Approval for destructive, privileged, financial, external or difficult-to-reverse actions.
- Every action has a postcondition verifier; failed verification stops execution rather than blindly retrying.
- Cloud model routing must respect explicit per-request egress policy and minimize/redact telemetry. The CLI sends only the prompt explicitly supplied to `aie ask`; observer events, screen metadata and browser telemetry are not attached automatically.

## Screen and UI Automation observation
Structural UI Automation sampling is off by default and requires an explicit per-process allowlist. The initial provider records only control type, class, automation ID and geometry, with strict depth/node/time bounds. It does not query control text, values, passwords or screenshots. Window-title capture remains separately opt-in and sensitive.

Screen capture must be visibly enabled, pauseable and event-driven where practical. Capture only for an explicitly selected capability. No hidden continuous recording; avoid storing raw screenshots unless explicitly requested.

## Windows Event Log observation
Event Log collection is off by default and restricted to the classic Application/System channels. The first sample establishes a cursor and does not replay historical records. Only provider name, event ID/type/category, record number, machine and event timestamp are stored; message text, XML payloads and Security logs are excluded. Polling is bounded and uses the optional pywin32 dependency.

## Browser observation
Use explicit extension permissions. Collect only playback/performance metrics needed for diagnosis. Never collect page text, credentials, cookies, payment data, form fields or browsing history.

## Autonomy tiers
- Tier 0: observe and explain.
- Tier 1: propose reversible changes.
- Tier 2: execute explicitly pre-authorized low-risk actions within allowlists and budgets.
- Tier 3: approval required (network configuration, process termination, service changes, file moves/deletes, installations, external communication).
- Tier 4: unsupported (credential extraction, security-control bypass, covert surveillance, destructive action without clear consent).

## Incident response
Provide global pause/kill switch. Stop automation after repeated failures, retain minimal audit metadata, and allow user review/deletion. Never hide execution.
