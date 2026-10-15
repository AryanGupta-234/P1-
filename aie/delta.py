"""Deterministic, in-memory snapshot reconciliation for read-only inventory sources."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from aie.contracts import AIEEvent, EntityRef


class SnapshotDeltaTracker:
    """Turn successive allowlisted inventory snapshots into evidence events.

    The first sample establishes a baseline. Later samples emit additions,
    removals and field changes. Snapshot values are copied through canonical
    JSON serialization so caller mutation cannot rewrite the remembered state.
    """

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, dict[str, Any]]] = {}

    @staticmethod
    def _canonical(item: dict[str, Any]) -> str:
        return json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def update(
        self,
        *,
        collection: str,
        items: Iterable[dict[str, Any]],
        identity_field: str,
        entity_type: str,
        source: str,
        host_id: str,
    ) -> list[AIEEvent]:
        if not collection or not identity_field or not entity_type or not source or not host_id:
            raise ValueError("collection, identity_field, entity_type, source and host_id are required")

        current: dict[str, dict[str, Any]] = {}
        for raw in items:
            if not isinstance(raw, dict):
                continue
            identity = raw.get(identity_field)
            if identity is None or not str(identity).strip():
                continue
            key = str(identity)
            # Duplicate identities in one snapshot are ambiguous; fail closed.
            if key in current:
                raise ValueError(f"duplicate identity {key!r} in {collection!r} snapshot")
            current[key] = json.loads(self._canonical(raw))

        previous = self._snapshots.get(collection)
        self._snapshots[collection] = current
        if previous is None:
            return [
                AIEEvent(
                    host_id=host_id, source=source,
                    event_type=f"inventory.{collection}.baseline",
                    entity=EntityRef(type=entity_type, name=collection),
                    data={"item_count": len(current), "coverage": "count_only"},
                    sensitivity="internal",
                ),
                *[
                    AIEEvent(
                        host_id=host_id, source=source,
                        event_type=f"inventory.{collection}.present_observed",
                        entity=EntityRef(type=entity_type, name=key, stable_id=key),
                        data={"current": item, "baseline": True},
                        sensitivity="internal", confidence=1.0,
                        evidence_kind="observed",
                    )
                    for key, item in sorted(current.items())
                ],
            ]

        events: list[AIEEvent] = []
        for key in sorted(current.keys() - previous.keys()):
            item = current[key]
            events.append(AIEEvent(
                host_id=host_id, source=source,
                event_type=f"inventory.{collection}.added",
                entity=EntityRef(type=entity_type, name=key, stable_id=key),
                data={"current": item}, sensitivity="internal",
                confidence=0.95, evidence_kind="derived",
            ))
        for key in sorted(previous.keys() - current.keys()):
            item = previous[key]
            events.append(AIEEvent(
                host_id=host_id, source=source,
                event_type=f"inventory.{collection}.removed",
                entity=EntityRef(type=entity_type, name=key, stable_id=key),
                data={"previous": item}, sensitivity="internal",
                confidence=0.95, evidence_kind="derived",
            ))
        for key in sorted(current.keys() & previous.keys()):
            before, after = previous[key], current[key]
            if self._fingerprint(self._canonical(before)) == self._fingerprint(self._canonical(after)):
                continue
            events.append(AIEEvent(
                host_id=host_id, source=source,
                event_type=f"inventory.{collection}.changed",
                entity=EntityRef(type=entity_type, name=key, stable_id=key),
                data={"previous": before, "current": after},
                sensitivity="internal", confidence=0.95, evidence_kind="derived",
            ))
        return events
