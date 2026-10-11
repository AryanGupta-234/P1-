# ADR-0007: Privacy-Safe Observer Health Telemetry

## Status

Accepted

## Context

AIE combines multiple independent Windows observation providers with different sampling
cadences and failure modes. A provider permission error, timeout or transient failure
must not terminate the whole observation runtime, and hosted CI needs evidence that the
runtime can detect degradation without collecting private provider payloads.

## Decision

The observer runtime records provider health as local, derived observer.health events.
Each provider is tracked with bounded counters for:

- samples attempted and successfully completed
- events emitted
- total and consecutive errors
- average and most recent sampling latency
- cumulative event-loss counter, available for providers such as ETW
- last error type and timestamp, without exception messages

Provider exceptions are isolated to the provider call. The runtime continues collecting
other providers and emits the health record on a bounded cadence. Health events contain
no command lines, window titles, UIA text/value data, event-log message text/XML, or
arbitrary exception strings.

The event-loss field is intentionally a hook rather than a fabricated metric. Providers
must explicitly report observed loss; absence of loss reporting does not imply zero loss.

## Consequences

Positive:
- Sensor degradation becomes observable and testable.
- One failing provider does not stop unrelated perception.
- Health data is suitable for local diagnostics and future tray UI.
- ETW and other loss-aware providers can report coverage without changing the core contract.

Trade-offs:
- Health records add a small amount of local event-store volume.
- A provider can only report loss that it can actually measure.
- Hosted Windows CI still cannot prove target-desktop permissions or hardware behavior.

## Privacy and security

Health telemetry is internal derived metadata. It stores error class names rather than
exception text and never promotes provider payloads into health records. It does not grant
capabilities or execute actions.
