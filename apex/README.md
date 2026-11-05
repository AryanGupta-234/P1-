# APEX — Standalone Windows Assistant Runtime

APEX is an independent, local-first Windows assistant. Its Python runtime calls the installed Ollama service through the loopback HTTP API; it does not invoke `ollama run`, CMD, PowerShell, or subprocesses to obtain model responses. Normal inference sends `think: false` explicitly from Python.

## Runtime API

```python
from apex import ApexService

assistant = ApexService()
manifest = assistant.start()
reply = assistant.send_message("Summarize my current system status")
print(reply["response"])
assistant.stop()
```

The `ApexService` is an in-process API for a future independent Windows desktop client. Phase 1 does not ship the desktop UI. The host connects to `http://127.0.0.1:11434` by default, discovers installed models only, and never pulls one automatically. On Windows, it checks the API first and can launch the installed `ollama app.exe` directly using the Windows shell API if the API is unavailable and auto-start is enabled. It never invokes `ollama run`, CMD, PowerShell or a subprocess for model inference. The configured model tag defaults to `APEX`.

## Windows dependencies

Install the project with its Windows extra to enable UI Automation, Win32/COM integration, Core Audio and Recycle Bin operations. Capabilities report unavailable when their provider is not present or the host is not running on Windows.

## Data and privacy

APEX stores data under `%LOCALAPPDATA%\APEX\apex-unified.sqlite3` by default (override with `APEX_DATA_DIR`). Conversation persistence is disabled by default; set `APEX_PERSIST_CONVERSATIONS=true` to opt in. Window titles are not collected by default; set `APEX_INCLUDE_WINDOW_TITLES=true` to opt in. Clipboard reads are explicit tool calls, never background collection. UIA omits Edit and Document values and blocks password controls.

## Approvals

Read-only operations can run when their provider is available. All mutating actions require an approval callback supplied by the host application. Without one, APEX returns `approval_required` and makes no change. This source release intentionally does not include a GUI approval prompt.

## Scope limitations

The initial implementation includes registered Windows inventory, EXE and packaged-app discovery/launch, Settings and MMC navigation, process/window inventory, window management, bounded mouse/keyboard/text/drag input, UIA, audio/media, approved-root file operations, clipboard, DNS, adapter/DHCP controls, allowlisted service controls, brightness, scheduled tasks and Event Log metadata. It does not include kernel access, unrestricted shell execution, UAC/secure-desktop bypass, broad security-control changes, arbitrary driver installation, passive keylogging, or universal automation of every third-party application. A dispatched input or opened Settings page is not reported as verified application state.
