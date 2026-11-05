# APEX Phase 1 Implementation

**Branch:** `feature/apex-phase-1-runtime`  
**Status:** Initial runtime and Windows adapter implementation; Windows target-machine validation remains required.  
**Architecture authority:** [ADR-0017](adr/0017-apex-runtime-and-data-independence.md)

## Runtime contract

- `ApexService` / `ApexHost` are Python APIs; there is no model CLI invocation.
- `OllamaClient` calls `/api/tags` and `/api/chat` on loopback HTTP. It never downloads models and always sends `think: false`.
- Model tool calls are untrusted proposals. The Python host validates and dispatches only registered typed capabilities.
- No APEX package code imports AIE or SENTINEL.
- One APEX-owned SQLite database stores profile, app catalogue, optional conversation history, memories, task records, audit events and a change journal.
- Conversation history and window-title collection are disabled by default.
- Mutating tools require an approval callback; without it, the action is not executed.

## Initial Windows capability set

- Host/OS summary, process inventory, optional window inventory, network interface and storage summaries.
- Event Log metadata, PnP device inventory, service inventory and startup registry metadata (arguments are not collected).
- App Paths, Uninstall metadata, Start Menu shortcut catalogue, bounded metadata-only local-volume executable scan, alias resolution and approved app launch.
- Allowlisted Settings URI and MMC console opening.
- Window activation/state/move/resize/graceful close.
- Bounded mouse movement/click/scroll and hotkey input bound to a verified foreground window; stop on user input.
- UIA tree inspection, invoke, value set, select, toggle, expand/collapse and scroll; password and editable/document values are excluded.
- Master and per-application audio session controls through Core Audio.
- Approved-root file listing/create/copy/move/rename/Recycle Bin operations; no permanent-delete tool.
- Explicit clipboard get/set; no background clipboard listener.
- Service control for a protected/allowlisted noncritical service set, DNS configuration with rollback attempt, WMI brightness control, and non-Microsoft scheduled-task controls.

## Not yet complete / needs device validation

This is an initial Phase 1 implementation, not universal control of all Windows surfaces. Power-plan configuration, Wi-Fi/Bluetooth enable/disable, adapter lifecycle, PnP enable/disable with scoped elevation, Defender/update action recipes, full Shell/taskbar/virtual-desktop control, drag/drop and text entry with sensitive-control gating, app MSIX/AUMID catalogue enrichment, full-file version/signature metadata, robust post-launch window verification, native named-pipe IPC, interactive approval UI and full rollback coverage remain follow-up work. ETW, kernel-level telemetry, advanced diagnostics and desktop UI are later phases.

## Python integration

```python
from apex import ApexService

assistant = ApexService()
manifest = assistant.start()
reply = assistant.send_message("List the available read-only Windows diagnostics")
print(reply["response"])
assistant.stop()
```

A future desktop application should embed or host this API without changing the product boundary.


## Validation snapshot

- Cross-platform contract suite: **22 tests passed** in the development container.
- Python bytecode compilation passed for `apex/` and its tests.
- Import-boundary tests verify no AIE imports in the APEX package.
- Shell-boundary tests verify no subprocess, CMD or arbitrary-shell model execution path.
- Ollama contract tests verify `think: false` in the Python `/api/chat` JSON body and exact configured-tag/implicit-`:latest` resolution only.
- Windows integration validation remains **pending on the target Windows 11 machine**. COM, Core Audio, UI Automation, file-system and desktop input adapters have not been exercised on the user's PC.

This is an initial Phase 1 runtime and adapter set, not completion of every Phase 1 requirement. Mutating tools return `approval_required` unless the host supplies an explicit approval callback; no GUI approval surface is included in this milestone. See the follow-up checklist for remaining Phase 1 coverage.
