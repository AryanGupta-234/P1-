# Windows Application Automation Strategy

## Objective

Make AIE capable of interacting with a broad range of Windows applications through supported, observable interfaces. "Automatable" is a compatibility goal, not a promise that every application exposes every control.

## Adapter priority

1. **Native application APIs / documented command interfaces:** most stable when available.
2. **COM / Windows system APIs:** use for supported Office, shell and system integrations.
3. **Microsoft UI Automation (UIA):** discover windows and controls through the accessibility tree, inspect supported control patterns, and invoke only registered actions.
4. **Application-specific adapters:** add tested adapters for applications with custom controls or richer APIs.
5. **Visual interaction fallback:** only as an explicitly enabled, user-visible fallback; require foreground/window identity checks and confirmation before consequential interactions.

Microsoft UI Automation exposes application elements, properties, control patterns and events to client applications. Provider quality varies by app and custom controls, so AIE must detect unsupported controls and fall back safely rather than guess. See [Microsoft UI Automation overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-uiautomationoverview) and [UI Automation client overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-clientsoverview).

## Planned AIE interfaces

- `ApplicationRegistry`: known app identity, install source and supported adapter IDs.
- `WindowCatalog`: top-level windows, process identity and foreground state.
- `UIATreeReader`: bounded, on-demand control-tree inspection; redact text values by default.
- `ControlActionRegistry`: explicit actions mapped to UIA control patterns.
- `ApplicationAdapter`: optional per-app API/COM/CLI/UIA integration.
- `ActionProposal`: structured intent, target app/window/control, parameters and risk.
- `PolicyBroker`: authorization, user approval, timeout, rate limits and audit.
- `OutcomeVerifier`: verify the intended UI/state change; otherwise stop and report.

## Compatibility and safety requirements

- Never collect passwords, authentication tokens, browser cookies or private message contents.
- Do not scrape all UI text in the background. Inspect only a user-authorized target and minimize/redact values.
- Verify process ID, process creation time, window handle and app identity immediately before an action.
- Never click a control based only on screen coordinates when a stable UIA/API target is available.
- High-impact operations (send, delete, purchase, submit, publish, install, privilege/security change) require explicit approval.
- Respect application integrity levels and Windows security boundaries; do not inject into other processes or bypass protected UI.
- Record action proposals, authorization outcomes and verification results—not sensitive UI content.

## Coverage model

AIE should maintain a per-app compatibility record:

- `API`: documented native integration.
- `COM`: supported COM automation.
- `UIA_FULL`: reliable UIA controls and events.
- `UIA_PARTIAL`: some custom/owner-drawn controls unavailable.
- `CLI_ONLY`: documented command interface.
- `MANUAL_ONLY`: no reliable supported interface identified.

Coverage is discovered and tested per application. Do not assume that a UIA tree is complete; some apps expose incomplete or virtualized controls.
