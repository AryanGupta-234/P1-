# SENTI Phase 1 — Windows test quickstart

This is a temporary test adapter for the independent SENTI Python host. It is **not** the Phase 6 desktop UI.

## Requirements

- Windows 11, Python 3.11 or newer.
- The locally installed Ollama Windows application and the configured SENTI model tag.
- Windows optional dependencies include PyWinRT radio projection for Bluetooth support.
- The Ollama loopback API at `http://127.0.0.1:11434` (the normal local default).
- No cloud provider, model auto-download or Linux/WSL/Docker dependency is used.

## Install the independent SENTI package

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".\senti[windows,dev]"
```

If PowerShell blocks activation, do not weaken machine-wide policy. Run the virtual-environment interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".\senti[windows,dev]"
```

## Start the Phase 1 smoke-test adapter

```powershell
.\.venv\Scripts\python.exe .\scripts\senti_console.py
```

This starts the SENTI Python host. The host communicates with Ollama through Python's direct HTTP client. It does not invoke `ollama run`, `ollama create`, CMD, PowerShell or subprocess for model inference. The script itself is only a temporary text-based test surface.

If the default `SENTI` tag is not installed, the console displays the locally installed tags and asks you to choose one exact tag. It does not download, pull or silently substitute a model. The SENTI personality and host identity remain in the Python runtime prompt; the selected tag identifies only the foundation model.

The console displays the resolved model tag, provider status and database status. If the configured model tag is not installed, SENTI reports it and does not download or silently substitute another model.

## Safety behaviour during testing

- Read-only inspections do not need mutation approval.
- Every state-changing capability displays its exact tool name, risk tier and arguments. It only runs after an explicit `y` confirmation.
- `/stop` persists the emergency stop and blocks all state-changing tools.
- `/resume` asks for an explicit confirmation before re-enabling the approval-gated path.
- `/exit` closes the test adapter.
- SENTI does not elevate itself, bypass UAC, disable Defender, stop anti-cheat services, or permanently delete files.
- The emergency-stop setting is persisted in SENTI's own database under `%LOCALAPPDATA%\SENTI\senti.sqlite3` by default.

## Useful initial tests

Try conversational identity first, then read-only requests such as:
- “What model and providers are connected?”
- “List my running processes.”
- “Show my network adapter and DNS configuration.”
- “Show installed power plans.”
- “Open Bluetooth settings.”
- “Open Wi-Fi settings.”
- “Find the Windows Update advanced options page.”
- “List all Settings URLs by category.”
- “Open the legacy Network and Sharing Center.”
- “List Wi-Fi radio state.”
- “Check Bluetooth radio state.”
- “Open Quick Settings.”
- “Open the Start menu.”
- “Switch to the next virtual desktop.”
- “Check Windows Defender status.”
- “Check Windows Update service and reboot status.”
- “Find the SENTI project notes I asked you to remember.”
- “Show my SENTI profile.”
- “Set my preferred salutation to sir.”

Only test system changes with a non-critical target and review the exact approval details. Do not test network adapter disabling over your only active connection.

## Scope and limitations

The Phase 1 runtime is still headless apart from this smoke-test console. The standalone desktop application and polished interactive approval UI are Phase 6. Some privileged PnP operations, broad Windows shell controls, complete rollback/compensation, ETW/kernel telemetry and target-device validation are not included in this phase's test adapter. Provider status in the runtime manifest indicates availability, not that every operation has been validated on this particular PC.
