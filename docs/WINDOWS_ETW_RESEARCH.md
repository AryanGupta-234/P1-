# Windows ETW Research and Process-Capture Prototype

## Objective

Improve process lifecycle coverage beyond periodic user-mode snapshots, while retaining snapshots as a reconciliation fallback. AIE uses documented Windows ETW facilities only. This work does not require a custom kernel driver and must not weaken Secure Boot, VBS, HVCI, Kernel-mode Hardware-enforced Stack Protection or App Control.

## Two separate operations

1. The aie etw-catalog command invokes logman.exe query providers and parses registered provider names/GUIDs. It is discovery only: no ETW session is created, enabled, stopped or modified.
2. The aie etw-process --duration N command is a manual, bounded prototype. It creates a unique session named AIE-Proc-<random>, enables one process provider/keyword, captures for a user-specified duration, stops only that exact session, then decodes an allowlisted subset of process lifecycle metadata.

The ETW path is deliberately not started by aie observe and is not a persistent background session. This limits the first integration to a trace the user can explicitly start and inspect.

## Prototype bounds

- Native Windows only; no automatic elevation.
- Unique AIE-owned session; no attaching to or stopping another session.
- Process lifecycle keyword only; no thread, image load, file I/O, registry, network or stack-walk events.
- Maximum capture duration: 30 minutes; default: 15 seconds.
- 8 MiB circular ETL; 16 KiB buffers; minimum 2 and maximum 8 buffers.
- Decoded XML maximum 32 MiB; output maximum 20,000 process events.
- Allowlisted fields: timestamp, PID, parent PID when present, process image basename, provider GUID, event ID and event version.
- Full executable path is reduced to basename. Command lines, process arguments, exit status, arbitrary provider payload, event message text and user content are not retained.
- Raw trace files are removed after confirmed session stop and decode. If stop cannot be confirmed, the workspace is retained and the CLI reports the exact logman stop <owned-session> -ets recovery command.
- Event/buffer-loss values are reported only when the trace summary contains explicit counters. Missing counters remain unknown; AIE does not infer zero loss.
- This prototype does not yet merge ETW process events with snapshot reconciliation or run continuously.

## Provider and event contract

The first candidate is Microsoft-Windows-Kernel-Process, GUID {22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}. The implementation checks that GUID against the local provider catalog before starting a trace. The process keyword and start/stop event IDs are based on the Windows provider manifest family; Windows versions may vary in schema and access behavior.

The parser currently recognizes process start (event ID 1) and process stop (event ID 2), but target-device validation must confirm event versions and field names on the installed Windows 11 build. The runtime catalog check proves provider registration only; it does not prove that the current account can enable the provider or that the selected keyword produces the expected events.

## Shutdown and recovery

ETW sessions can outlive a client process unless explicitly stopped. AIE therefore uses a unique session name and guarantees a bounded stop attempt in normal, timeout and exception paths. It does not use a broad logman stop call. If shutdown fails, it preserves the trace workspace and presents the exact session name and stop command for local recovery. AIE never claims shutdown succeeded when it cannot verify the result.

## Validation plan

Before continuous integration into the observer, validate on the target Windows 11 desktop:

1. Provider catalog includes the expected GUID.
2. Current-user session creation permissions and whether elevation is required.
3. Process start/stop events for a known benign test process, with correct PID/parent PID and timestamp.
4. Event version/field mapping on the installed Windows build.
5. Normal stop, Ctrl+C/process interruption, command timeout and failed-stop recovery.
6. Event/buffer-loss counters; if unavailable, record that the measurement is unsupported rather than zero.
7. Session delivery latency and AIE CPU/RAM overhead at the default buffer bounds.
8. Compare ETW lifecycle events with before/after process snapshots to measure missed/duplicate events.

## References

- Microsoft, About Event Tracing: https://learn.microsoft.com/en-us/windows/win32/etw/about-event-tracing
- Microsoft, Event Tracing portal: https://learn.microsoft.com/en-us/windows/win32/etw/event-tracing-portal
- Microsoft, logman create trace: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/logman-create-trace
- Microsoft, logman start/stop: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/logman-start-stop
- Microsoft, tracerpt: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/tracerpt
- Microsoft, wevtutil: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/wevtutil
- Windows provider manifest reference for candidate Kernel-Process event metadata: https://github.com/repnz/etw-providers-docs/blob/master/Manifests-Win10-17134/Microsoft-Windows-Kernel-Process.xml. This is a community-maintained manifest mirror, not a Microsoft specification; the target Windows host remains authoritative.

## Non-goals

No custom driver, no ETW session auto-start, no broad system tracing, no event content extraction, no kernel security setting changes, no autonomous response, and no claim of complete process visibility.