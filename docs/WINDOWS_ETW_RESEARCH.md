# Windows ETW Research Track

## Objective
Identify the least-privilege event providers needed for AIE's environmental model before enabling any trace session. ETW can expose application-defined and operating-system/kernel-originated events through provider/session/consumer roles. It is not a promise of complete visibility: provider event schemas, permissions, session settings, buffer capacity and consumer throughput govern coverage.

## First instrument: read-only provider catalog
AIE's `aie etw-catalog` command invokes `logman.exe query providers` and parses provider names/GUIDs. It only enumerates registered providers. It does **not** start, stop, enable or alter tracing sessions.

## Candidate event families to evaluate
- Kernel process lifecycle: process start/stop and parent/child relationship.
- Kernel image: image load/unload metadata where supported and authorized.
- Thread lifecycle only if it adds measurable value beyond process events.
- File I/O, registry and network tracing only for narrow, explicitly justified diagnostic scenarios; these can produce high event volume and expose sensitive metadata.

## Design requirements before real-time ETW capture
1. Document provider GUID, event IDs/versions, keywords, levels and OS/build compatibility.
2. Use a named, AIE-owned session with explicit start/stop lifecycle and bounded buffers.
3. Require elevation only where the chosen provider/session actually requires it; never silently elevate.
4. Implement loss counters, backpressure, cancellation and graceful session shutdown.
5. Normalize only allowlisted fields; avoid command lines, paths or payloads unless explicitly justified.
6. Verify telemetry through synthetic process lifecycle tests and compare with periodic reconciliation.
7. AIE must never take ownership of or stop unrelated ETW sessions.

## Kernel driver position
Do not write a custom driver to obtain basic process/application awareness. If documented ETW/Event Log facilities cannot meet a demonstrated requirement, a driver becomes a separate project with threat model, WDK toolchain, signing requirements, code review, crash testing, install/uninstall UX and explicit consent. Preserve VBS, HVCI, Secure Boot and App Control policies.

## References
- [Microsoft Event Tracing portal](https://learn.microsoft.com/en-us/windows/win32/etw/event-tracing-portal)
- [About Event Tracing](https://learn.microsoft.com/en-us/windows/win32/etw/about-event-tracing)
- [Windows driver signing](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/driver-signing)
