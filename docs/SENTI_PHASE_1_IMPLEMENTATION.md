# SENTI Phase 1 Implementation

**Branch:** `feature/senti-phase-1-runtime`  
**Status (2026-11-07):** Expanded Phase 1 runtime and Windows adapters; CI lint passes, but full test suite has known failures and target Windows 11 validation remains required. Not release-ready.  
**Architecture authority:** [ADR-0017](adr/0017-senti-runtime-and-data-independence.md)

## Runtime contract

- `SentiService` / `SentiHost` are Python APIs; there is no model CLI invocation. The standalone SENTI wheel is built from `senti/pyproject.toml`, separately from the root AIE distribution.
- `OllamaClient` calls `/api/tags` and `/api/chat` on loopback HTTP. It never downloads models and always sends `think: false`.
- Model tool calls are untrusted proposals. The Python host validates and dispatches only registered typed capabilities. Identity/model/operator/capability questions are answered from the live host manifest; process-visibility requests call the live read-only process provider.
- No SENTI package code imports AIE or SENTINEL.
- One SENTI-owned SQLite database stores profile, app catalogue, optional conversation history, memories, task records, audit events and a change journal.
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

This is an expanded Phase 1 runtime and automation foundation, not universal control of every Windows surface. The following remain incomplete or intentionally excluded:

- PnP device enable/disable through a scoped, least-privilege elevation broker. SENTI currently inspects PnP state but does not change device-node state or self-elevate.
- Named, bounded Defender scan/update-check/repair recipes. Current Defender and Windows Update tools are read-only posture snapshots; they do not change protection settings or install updates.
- Full app metadata enrichment, AppX/MSIX manifest harvesting, complete publisher/signature validation, and robust post-launch process/window readiness verification. Packaged-app discovery remains best-effort through the Shell AppsFolder namespace.
- Native authenticated named-pipe IPC, a background Windows service/host lifecycle, and the polished standalone desktop client. The included text console is only a temporary Phase 1 smoke-test adapter; the desktop UI remains deferred to Phase 6.
- A desktop approval queue/consent surface and scoped UAC broker. Mutations are executable only in a host that supplies an explicit approval callback; the temporary console supplies a text confirmation prompt.
- Complete rollback/compensation for every mutation. Some operations verify postconditions and return prior state or attempt rollback (DNS, power plan, Wi-Fi PHY state, selected Bluetooth state); other dispatch-style actions cannot guarantee reversal. Receipts must not imply universal reversibility.
- Native control of every Start/taskbar/Quick Settings surface. Current shell support is a fixed shortcut allowlist and reports dispatch rather than independently verified shell-state changes.
- Full memory-management UX, semantic/embedding retrieval, review/correction/export workflows, encrypted sensitive-memory storage and automatic profile onboarding. Current memory is bounded lexical retrieval of normal-sensitivity user-approved records plus explicit save/search/forget and profile read/update.
- Dedicated process termination remains deliberately unregistered. SENTI can inspect processes and close supported user windows gracefully, but it does not offer a generic kill-process tool.
- Target-device testing for Windows WLAN/WinRT radio permissions, WMI, PowrProf, UIA, Core Audio, filesystem boundaries, shell shortcuts, service/task changes and the configured local Ollama model.

ETW/kernel-level telemetry, advanced evidence correlation, adaptive background autonomy and the polished desktop UI are later phases. SENTI does not bypass UAC, override hardware radio switches, or interfere with anti-cheat/security software.

## Python integration

```python
from senti import SentiService

assistant = SentiService()
manifest = assistant.start()
reply = assistant.send_message("List the available read-only Windows diagnostics")
print(reply["response"])
assistant.stop()
```

A future desktop application should embed or host this API without changing the product boundary.


## Validation snapshot

- The Windows CI matrix installs the root AIE package and independent SENTI package, checks optional Windows imports (including PyWinRT radio APIs), builds the existing WPF dashboard, runs Ruff, executes SENTI-focused tests, builds both Python distributions and then runs the full repository suite.
- The latest commit adds focused tests for automatic memory retrieval/sensitivity filtering and the fixed native WLAN structure layout. CI for the current branch head is in progress; cancelled/superseded workflow runs are not a successful gate.
- An earlier full repository run exposed two unrelated PRIXON identity-test failures (newline preservation and expected wording). PRIXON is outside SENTI's product boundary and has not been modified. Process termination is deliberately unregistered and its SENTI registry test reflects that safety boundary.
- No CI result substitutes for target Windows 11 testing. Native WLAN/WinRT radio permissions, WMI, PowrProf, UIA, Core Audio, filesystem boundaries, shell shortcuts, service/task changes and the actual local Ollama model still require device validation.

**Release gate:** require a completed green SENTI-focused test matrix on Python 3.11 and 3.12, successful independent SENTI distribution validation, and an explicit target-device smoke test before declaring Phase 1 release-ready. Full repository test status is tracked separately because PRIXON identity tests are outside this milestone.

## Automatic memory context

Before each model request, the host performs a bounded lexical search across SENTI's `preferences`, `personal`, `project` and `technical` namespaces. It selects at most six normal-sensitivity records within a 4,000-character budget. Sensitive memories are excluded by the store query and checked again at the host boundary. Retrieved content is labeled as untrusted reference data and cannot modify system policy. This is lexical matching, not embedding-based semantic retrieval.

## Phase 1 extensions added on 2026-11-07

- Power plan enumeration/current-plan inspection and selection of an exact installed scheme GUID through the Windows PowrProf API. Selection is approval-gated and verifies the active GUID; the previous GUID is returned as recovery information.
- Read-only Microsoft Defender protection/signature inspection through the Defender WMI provider. No Defender exclusions, preferences or protection settings are changed.
- Read-only Windows Update posture snapshot: selected update-service states, installed hotfix metadata and reboot-required registry indicators. It does not query Microsoft's online update service and does not install or uninstall updates.
- Unified-store memory APIs: bounded JSON payloads, credential-like field rejection, namespace-scoped search, expiry, deletion and change-journal records. Normal memory search excludes sensitive records. Sensitive memory encryption and a user-facing memory manager are not implemented.
- Persistent SENTI emergency stop. The trusted host can disable every state-changing capability; the flag survives host restarts and is surfaced in the runtime manifest. The stop must be explicitly cleared by the host.
- Bounded UI Automation wait-for by one exact automation ID or name, returning only safe metadata for a unique, visible and enabled control.
- A temporary interactive smoke-test console supplies a per-operation approval prompt. It is not the standalone desktop UI, which remains deferred to Phase 6.

## Verification status and remaining acceptance gates

The Windows CI workflow has verified package installation and the WPF dashboard build. The most recent completed full test run reached the suite after lint and reported an SENTI test expectation that still listed process termination, plus two PRIXON identity-test mismatches. Process termination remains deliberately unregistered; the SENTI test is being aligned to that safety boundary. The PRIXON subsystem is outside SENTI's product boundary and has not been modified.

A green SENTI-focused test run and a complete green repository suite are still required. Power APIs, WMI providers, UI Automation, Core Audio, adapter/service/task operations, interaction lease, filesystem scoping, and the actual local Ollama model must also be exercised on the target Windows 11 device before claiming end-to-end validation.


## Native Wi-Fi radio controls

- Inspect WLAN interface GUIDs, interface state and per-PHY software/hardware radio state with the Windows Native WLAN API (`WlanEnumInterfaces`, `WlanQueryInterface`).
- Enable/disable the software radio on one exact interface GUID using `WlanSetInterface`; mutation is host-approval-gated and the before-state is returned in the receipt.
- Hardware radio is read-only. SENTI refuses to enable software radio when the hardware switch is reported off, and does not claim a hardware switch can be overridden.
- Each change is re-queried. When the postcondition fails, SENTI attempts to restore every PHY changed by that invocation.
- This is not a Bluetooth radio provider; Bluetooth radio control remains outstanding. Interface enumeration and driver support must be validated on the target Windows 11 device.


## Bluetooth radio controls

- Enumerate Bluetooth radio devices and effective radio state with the Windows.Devices.Radios WinRT API.
- Request Windows radio-control access only when the user-approved mutation is invoked; then set one uniquely named Bluetooth radio to On or Off.
- Re-enumerate and verify the effective radio state. Hardware/policy-disabled states and denied access are reported as failures rather than bypassed.
- Successful receipts include the previous state as compensation information.
- The provider is optional in the Windows extra and uses the PyWinRT `winrt-Windows.Devices.Radios` package. It is unavailable when that package or a usable Bluetooth radio is absent.
- Actual permission prompts, OEM radio policy and hardware state must be validated on the target Windows 11 device.


## Windows 11 shell shortcuts

- Add typed, allowlisted actions for Start, Quick Settings, notification center, Task View, taskbar cycling, Alt+Tab window switching, and virtual-desktop navigation/create/close.
- Each action first validates the exact target window/process against protected-window policy, then uses the existing foreground-window and interaction lease to dispatch a fixed shortcut.
- There is no arbitrary key-sequence input through this shell tool. Shortcut dispatch is reported as unverified because it does not independently prove the shell surface changed.
- Create/close virtual desktop actions remain approval-gated and are not represented as automatically reversible.


## User-approved profile operations

- SENTI exposes a read-only profile lookup and an approval-gated profile update.
- The schema accepts only four user-supplied fields: display name, preferred salutation, locale and interaction style, each with strict length bounds.
- No username or display name is derived from a Windows account folder, machine metadata or inferred identity. The default salutation remains `sir`.
- The update modifies the existing SENTI-owned profile row in the unified store; it does not create another profile database.


## Windows Settings and Control Panel catalogue

- SENTI maintains a curated catalogue of the documented Microsoft `ms-settings:` URI reference. Each entry has a stable ID, category, display name, canonical URI, aliases, lifecycle status, availability caveat and minimum Windows build where Microsoft specifies one.
- Catalogue categories cover Accounts, Apps, Control Center, Devices, Accessibility, Extras, Family, Gaming/Mixed Reality, Network and internet, Personalization, Phone, Privacy, Search, Sound, System, Time and language, and Update and security.
- Read-only tools search pages by natural-language query and enumerate the catalogue by category with offset pagination. This allows SENTI to discover a page before opening it without sending the full URI catalogue in every model prompt.
- The open-page tool resolves only catalogue IDs, documented page names, aliases or an exact URI already in the catalogue. It does not accept arbitrary URI strings or model-generated query parameters.
- Removed pages are listed for reference but cannot be launched. Deprecated pages are marked. Conditional pages carry notes about build, SKU, account, hardware, enrollment or feature requirements. Launch dispatch is reported as unverified until Settings UI readiness can be independently observed.
- Parameterized deep links (for example app-specific Default Apps/Installed Apps pages, camera IDs and specific audio endpoint IDs) are documented with caveats; SENTI does not accept arbitrary parameter strings. Device-specific deep-link construction needs a separate validated provider.
- A second fixed allowlist covers legacy Control Panel applets via fixed `control.exe` arguments. MMC/CPL/EXE entry points remain a separate reviewed allowlist; neither path exposes arbitrary shell/command input.
- Source reference: [Microsoft Learn — Launch Windows Settings](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings). The catalogue is a documented reference inventory, not a guarantee that every URI is implemented on every Windows 11 SKU or device.
