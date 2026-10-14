# ADR-0022: Evidence-Linked Network Interface State Changes

- **Status:** Accepted
- **Date:** 2026-10-14

## Context

The Windows network provider emits periodic interface snapshots. Snapshot history is useful for inspection, but downstream context needs an explicit event when an interface changes operational state. Treating traffic-counter increments as state changes would create continuous noise and misleading signals.

## Decision

Add a bounded in-memory `NetworkInterfaceStateTracker` to the observer runtime.

- The first snapshot for each interface establishes a baseline and emits no change event.
- Later snapshots compare only `is_up`, `speed_mbps` and `mtu`.
- A changed field emits one derived `network.interface.state_changed` event.
- The derived event references the exact source snapshot event ID and is correlated to that evidence.
- Byte/packet/error/drop counters are excluded from change detection.
- The tracker stores no IP or MAC addresses and is bounded to 128 interfaces by default.
- The tracker never configures, enables, disables or otherwise mutates a network interface.

## Consequences

AIE can distinguish observed interface snapshots from evidence-linked state transitions. The state tracker is process-local; after restart, the first snapshot re-establishes the baseline. Interface disappearance is not inferred because a missing row may reflect a transient or incomplete provider result. Hosted Windows CI and target-desktop validation are required before this change is considered fully validated.
