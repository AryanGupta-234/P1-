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

## Systemwide process-resource sampling
Systemwide process sampling is opt-in, bounded by process count and cadence, and emits only a small top-consumer summary. It records PID, process name, creation time, CPU share of total logical CPU capacity, RSS, thread count and process I/O counters. It excludes command lines, executable paths, environment variables, handles and window content. Some processes may be skipped because of access restrictions or the configured scan cap; the event reports truncation.

## Windows Event Log observation
Event Log collection is off by default and restricted to the classic Application/System channels. The first sample establishes a cursor and does not replay historical records. Only provider name, event ID/type/category, record number, machine and event timestamp are stored; message text, XML payloads and Security logs are excluded. Polling is bounded and uses the optional pywin32 dependency.

## Activity-to-model context egress
Activity summaries are never attached to model requests by default. The user must opt in per request with `--with-activity`. The packager uses only the safe timeline projection and excludes sensitive events, window titles, Event Log message/XML content, UIA node trees, feedback notes and raw payloads. Remote requests that include activity summaries require a separate `--confirm-activity-egress` confirmation. Activity context is a safe, bounded timeline projection; it never contains raw event payloads.

## Memory-to-model context egress
Memory is never attached to a model request by default. The user must opt in per request. Matching records are bounded and quoted as untrusted reference data. Sensitive memories are excluded by default and cannot be attached to cloud or remote Ollama requests. Remote requests that include non-sensitive memories require a separate `--confirm-memory-egress` confirmation. Observer events and screen/browser telemetry are not attached by this mechanism.

## Persistent local memory
Memory records are written only through explicit user commands or reviewed application calls; no collector or model silently promotes events into memory. Records are stored in a separate local SQLite database. Sensitivity is a handling label that controls default listing/retrieval, not encryption. Do not store passwords, API keys, tokens, recovery codes or other credentials in memory. Use the sensitive flag and hidden interactive input for private notes, and protect the Windows account/device. Memory expiry, correction/supersession and deletion are user-controlled. Optional semantic embeddings are generated only by an already-installed local Ollama model and stored in local SQLite keyed by memory ID and model. Embeddings are not encryption and may retain semantic information about the source text. Sensitive memories are excluded from indexing by default; `aie memory-index --include-sensitive` requires an explicit flag and prints a warning. Do not embed credentials, tokens or recovery codes.

## Browser observation
Use explicit extension permissions. Collect only playback/performance metrics needed for diagnosis. Never collect page text, credentials, cookies, payment data, form fields or browsing history.

## Action proposal ledger\nProposals are stored in a separate local SQLite audit database. The AIE API appends creation and review events and exposes no update/delete operation for that ledger. Capability manifests are user-authored JSON files in `%LOCALAPPDATA%\\AIE\\capabilities`; an empty or invalid capability directory grants no capabilities. Proposal parameter names resembling credentials are rejected, nested payloads are disallowed, and values are size-bounded. User approval re-runs the current policy. A status of approved means authorized for a future reviewed executor only; it does not mean an action ran. There is currently no executor. This is append-only at the application API level, not tamper-proof against a user with direct filesystem/database access.\n\n## Action proposal ledger
Proposals are recorded in a separate local SQLite audit database. The application API only appends creation/review events; it exposes no update/delete operation. Capability manifests are user-authored JSON files under `%LOCALAPPDATA%\AIE\capabilities`; the folder is empty by default and invalid manifests fail closed. Proposal parameters are bounded flat scalars; credential-like parameter names and nested objects are rejected. User approval re-evaluates current policy. An `approved` state means authorized for a future reviewed executor only, not that an action ran. There is currently no executor. The ledger is append-only through the application API and chains events with SHA-256 hashes plus a stored head checkpoint. `aie policy-audit-check` detects edits, deletion, tail truncation and broken links. This provides tamper evidence, not tamper-proof storage against a local administrator able to rewrite the database and recompute the chain/checkpoint.

## Autonomy tiers
- Tier 0: observe and explain.
- Tier 1: propose reversible changes.
- Tier 2: execute explicitly pre-authorized low-risk actions within allowlists and budgets.
- Tier 3: approval required (network configuration, process termination, service changes, file moves/deletes, installations, external communication).
- Tier 4: unsupported (credential extraction, security-control bypass, covert surveillance, destructive action without clear consent).

## Incident response
Provide global pause/kill switch. Stop automation after repeated failures, retain minimal audit metadata, and allow user review/deletion. Never hide execution.
