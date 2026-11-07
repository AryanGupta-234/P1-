# APEX Phase 1 Implementation

**Branch:** `feature/apex-phase-1-runtime`  
**Status (2026-11-07):** Expanded Phase 1 runtime and Windows adapters; CI lint passes, but full test suite has known failures and target Windows 11 validation remains required. Not release-ready.  
**Architecture authority:** [ADR-0017](adr/0017-apex-runtime-and-data-independence.md)

## Runtime contract

- `ApexService` / `ApexHost` are Python APIs; there is no model CLI invocation. The standalone APEX wheel is built from `apex/pyproject.toml`, separately from the root AIE distribution.
- `OllamaClient` calls `/api/tags` and `/api/chat` on loopback HTTP. It never downloads models and always sends `think: false`.
- Model tool calls are untrusted proposals. The Python host validates and dispatches only registered typed capabilities. Identity/model/operator/capability questions are answered from the live host manifest; process-visibility requests call the live read-only process provider.
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
- Bounded mouse movement/click/scroll, hotkeys, Unicode text entry only into a verified focused non-password Edit/ComboBox control, and same-window drag/drop; stop on user input.
- UIA tree inspection, invoke, value set, select, toggle, expand/collapse and scroll; password and editable/document values are excluded.
- Master and per-application audio session controls through Core Audio, plus named media-key dispatch.
- Approved-root file listing/create/copy/move/rename/Recycle Bin operations; no permanent-delete tool.
- Explicit clipboard get/set; no background clipboard listener.
- Service control and startup-type changes for explicitly allowlisted non-protected services, DNS configuration with rollback attempt, adapter enable/disable and DHCP lease actions (approval-gated), WMI brightness control, and non-Microsoft scheduled-task controls.

## Not yet complete / needs device validation

This is an initial Phase 1 implementation, not universal control of all Windows surfaces. Power-plan configuration, dedicated Wi-Fi/Bluetooth toggles, PnP enable/disable with scoped elevation, Defender/update action recipes, full Shell/taskbar/virtual-desktop control, full AppX/MSIX manifest enrichment and signature verification, robust post-launch window verification, native named-pipe IPC, interactive approval UI and full rollback coverage remain follow-up work. ETW, kernel-level telemetry, advanced diagnostics and desktop UI are later phases. Packaged-app discovery currently uses the Shell AppsFolder namespace and is best-effort.

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

- Contract, import-boundary, shell-boundary, tool-schema, self-awareness and Ollama request tests have been added to the branch.
- Automated test execution is pending; no passing local/CI test result is claimed in this document.
- Import-boundary regression tests are included to reject any AIE imports in the APEX package.
- Shell-boundary regression tests are included to reject subprocess, CMD or arbitrary-shell model execution paths.
- Ollama contract tests cover `think: false` in the Python `/api/chat` JSON body and exact configured-tag/implicit-`:latest` resolution.
- Windows integration validation remains **pending on the target Windows 11 machine**. COM, Core Audio, UI Automation, file-system and desktop input adapters have not been exercised on the user's PC.

This is an initial Phase 1 runtime and adapter set, not completion of every Phase 1 requirement. Mutating tools return `approval_required` unless the host supplies an explicit approval callback; no GUI approval surface is included in this milestone. Service mutations additionally require an exact name in `APEX_ALLOWED_SERVICES`, which defaults to an empty allowlist. See the follow-up checklist for remaining Phase 1 coverage.


## Phase 1 extensions added on 2026-11-07

- Power plan enumeration/current-plan inspection and selection of an exact installed scheme GUID through the Windows PowrProf API. Selection is approval-gated and verifies the active GUID; the previous GUID is returned as recovery information.
- Read-only Microsoft Defender protection/signature inspection through the Defender WMI provider. No Defender exclusions, preferences or protection settings are changed.
- Read-only Windows Update posture snapshot: selected update-service states, installed hotfix metadata and reboot-required registry indicators. It does not query Microsoft's online update service and does not install or uninstall updates.
- Unified-store memory APIs: bounded JSON payloads, credential-like field rejection, namespace-scoped search, expiry, deletion and change-journal records. Normal memory search excludes sensitive records. Sensitive memory encryption and a user-facing memory manager are not implemented.
- Persistent APEX emergency stop. The trusted host can disable every state-changing capability; the flag survives host restarts and is surfaced in the runtime manifest. The stop must be explicitly cleared by the host.
- Bounded UI Automation wait-for by one exact automation ID or name, returning only safe metadata for a unique, visible and enabled control.
- A temporary interactive smoke-test console supplies a per-operation approval prompt. It is not the standalone desktop UI, which remains deferred to Phase 6.

## Verification status and remaining acceptance gates

The Windows CI workflow has verified package installation and the WPF dashboard build. The most recent completed full test run reached the suite after lint and reported an APEX test expectation that still listed process termination, plus two PRIXON identity-test mismatches. Process termination remains deliberately unregistered; the APEX test is being aligned to that safety boundary. The PRIXON subsystem is outside APEX's product boundary and has not been modified.

A green APEX-focused test run and a complete green repository suite are still required. Power APIs, WMI providers, UI Automation, Core Audio, adapter/service/task operations, interaction lease, filesystem scoping, and the actual local Ollama model must also be exercised on the target Windows 11 device before claiming end-to-end validation.


## Native Wi-Fi radio controls

- Inspect WLAN interface GUIDs, interface state and per-PHY software/hardware radio state with the Windows Native WLAN API (`WlanEnumInterfaces`, `WlanQueryInterface`).
- Enable/disable the software radio on one exact interface GUID using `WlanSetInterface`; mutation is host-approval-gated and the before-state is returned in the receipt.
- Hardware radio is read-only. APEX refuses to enable software radio when the hardware switch is reported off, and does not claim a hardware switch can be overridden.
- Each change is re-queried. When the postcondition fails, APEX attempts to restore every PHY changed by that invocation.
- This is not a Bluetooth radio provider; Bluetooth radio control remains outstanding. Interface enumeration and driver support must be validated on the target Windows 11 device.
