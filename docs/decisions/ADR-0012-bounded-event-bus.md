# ADR-0012: Bounded Synchronous Event Bus

## Status

Accepted

## Context

The observer runtime previously assembled provider events directly around storage and
derived diagnostics. A future context engine needs one deterministic handoff point for
multiple consumers without introducing hidden queues, background threads or unbounded
retention.

## Decision

Use a small synchronous in-process EventBus with:

- explicit named sinks;
- fixed maximum batch size;
- deterministic sink registration order;
- per-sink handled counts;
- propagation of sink errors rather than silent loss.

The runtime registers durable SQLite as the primary sink and an optional JSONL writer
as a secondary sink. Diagnostics and observer-health derived events use the same bus.
The bus contains no scheduling, concurrency or action capability.

## Consequences

The runtime now has a single ordered publication boundary suitable for future temporal
correlators, activity projections and additional local consumers. Durable insert counts
remain distinguishable from auxiliary sink counts, preventing metric inflation.

A sink that fails blocks that publication cycle instead of silently discarding events.
Future asynchronous processing must add an explicit queue capacity/loss model and
corresponding health telemetry rather than hiding it inside the bus.
