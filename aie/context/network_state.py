"""Evidence-linked network interface state-change detection.

This tracker consumes privacy-minimized interface snapshots. Traffic counters are
intentionally excluded: they change continuously and do not represent configuration
or connectivity state transitions.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable

from aie.contracts import AIEEvent, EntityRef

_STATE_FIELDS = ("is_up", "speed_mbps", "mtu")


class NetworkInterfaceStateTracker:
    """Emit one derived event when a tracked interface state actually changes."""

    def __init__(self, *, max_interfaces: int = 128) -> None:
        if isinstance(max_interfaces, bool) or not 1 <= max_interfaces <= 512:
            raise ValueError("max_interfaces must be between 1 and 512")
        self.max_interfaces = max_interfaces
        self._states: OrderedDict[str, dict[str, object]] = OrderedDict()

    def observe(self, events: Iterable[AIEEvent]) -> list[AIEEvent]:
        """Update baselines and return evidence-linked state-change events."""
        derived: list[AIEEvent] = []
        for event in events:
            if event.event_type != "network.interface.snapshot":
                continue
            name = event.entity.name
            if not name:
                continue

            current = {field: event.data.get(field) for field in _STATE_FIELDS}
            if name not in self._states:
                if len(self._states) >= self.max_interfaces:
                    continue
                self._states[name] = current
                continue

            previous = self._states[name]
            changed = {
                field: {"before": previous[field], "after": current[field]}
                for field in _STATE_FIELDS
                if previous[field] != current[field]
            }
            self._states[name] = current
            if not changed:
                continue

            derived.append(AIEEvent(
                host_id=event.host_id,
                source="aie.context.network_state",
                event_type="network.interface.state_changed",
                entity=EntityRef(
                    type=event.entity.type,
                    name=name,
                    stable_id=event.entity.stable_id,
                ),
                data={
                    "changed_fields": changed,
                    "evidence_event_id": event.event_id,
                    "traffic_counters_used": False,
                    "causality_inferred": False,
                },
                sensitivity="internal",
                confidence=1.0,
                correlation_id=event.event_id,
                evidence_kind="derived",
            ))
        return derived
