"""Event-sourced, evidence-preserving projection of observed Windows state.

This is a bounded view over retained events, not an authoritative live inventory.
Missing evidence remains unknown; absence from a query window never means removal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Any

from aie.contracts import AIEEvent


MAX_EVIDENCE_IDS_PER_STATE = 64


@dataclass
class ProcessInstance:
    host_id: str
    pid: int
    create_time: float
    image: str
    status: str
    first_observed: datetime
    last_observed: datetime
    evidence_ids: list[str] = field(default_factory=list)
    etw_confirmed: bool = False
    evidence_truncated: bool = False


@dataclass
class EntityState:
    host_id: str
    collection: str
    identity: str
    entity_type: str
    name: str
    status: str
    current: dict
    first_observed: datetime
    last_observed: datetime
    evidence_ids: list[str] = field(default_factory=list)
    evidence_truncated: bool = False


@dataclass
class EnvironmentProjection:
    processes: dict[tuple[str, int, float], ProcessInstance]
    entities: dict[tuple[str, str, str], EntityState]
    coverage: dict[str, str]
    ignored_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        def stamp(value: datetime) -> str:
            return value.isoformat()

        return {
            "processes": [
                {**vars(item), "first_observed": stamp(item.first_observed),
                 "last_observed": stamp(item.last_observed)}
                for _, item in sorted(self.processes.items())
            ],
            "entities": [
                {**vars(item), "first_observed": stamp(item.first_observed),
                 "last_observed": stamp(item.last_observed)}
                for _, item in sorted(self.entities.items())
            ],
            "coverage": dict(self.coverage),
            "ignored_events": self.ignored_events,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EnvironmentProjection":
        if not isinstance(payload, dict):
            raise ValueError("projection snapshot must be an object")
        processes = {}
        for raw in payload.get("processes", []):
            item = dict(raw)
            item["first_observed"] = datetime.fromisoformat(item["first_observed"])
            item["last_observed"] = datetime.fromisoformat(item["last_observed"])
            item.setdefault("evidence_truncated", False)
            instance = ProcessInstance(**item)
            processes[(instance.host_id, instance.pid, instance.create_time)] = instance
        entities = {}
        for raw in payload.get("entities", []):
            item = dict(raw)
            item["first_observed"] = datetime.fromisoformat(item["first_observed"])
            item["last_observed"] = datetime.fromisoformat(item["last_observed"])
            item.setdefault("evidence_truncated", False)
            entity = EntityState(**item)
            entities[(entity.host_id, entity.collection, entity.identity)] = entity
        coverage = payload.get("coverage", {})
        ignored = payload.get("ignored_events", 0)
        if not isinstance(coverage, dict) or isinstance(ignored, bool) or not isinstance(ignored, int):
            raise ValueError("projection snapshot metadata is invalid")
        return cls(processes, entities, dict(coverage), ignored)


def _pid(event: AIEEvent):
    value = event.data.get("pid")
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    if result < 0 or (isinstance(value, float) and not value.is_integer()):
        return None
    return result


def _create_time(event: AIEEvent):
    value = event.data.get("create_time", event.data.get("process_create_time"))
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _process_key(event: AIEEvent):
    pid, created = _pid(event), _create_time(event)
    if pid is None or created is None:
        return None
    return event.host_id, pid, created


def _append_evidence(owner: ProcessInstance | EntityState, event_id: str) -> None:
    """Retain a bounded tail of unique evidence IDs and expose any truncation."""
    ids = owner.evidence_ids
    if event_id in ids:
        return
    if len(ids) >= MAX_EVIDENCE_IDS_PER_STATE:
        del ids[0]
        owner.evidence_truncated = True
    ids.append(event_id)


def project_environment_state(
    events: Iterable[AIEEvent],
    initial: EnvironmentProjection | None = None,
) -> EnvironmentProjection:
    """Replay events chronologically, optionally extending a persisted projection."""
    processes = initial.processes if initial is not None else {}
    entities = initial.entities if initial is not None else {}
    coverage: dict[str, str] = dict(initial.coverage) if initial is not None else {
        "processes": "partial: initial process baseline stores only a count",
        "services": "unknown until an entity-level baseline or delta is observed",
        "network_interfaces": "unknown until an entity-level baseline or delta is observed",
        "scheduled_tasks": "unknown until an entity-level baseline or delta is observed",
        "applications": "unknown until an entity-level baseline or delta is observed",
    }
    ignored = initial.ignored_events if initial is not None else 0

    ordered = sorted(
        events,
        key=lambda item: (
            item.timestamp.timestamp()
            if item.timestamp.tzinfo is not None and item.timestamp.utcoffset() is not None
            else float("-inf"),
            item.event_id,
        ),
    )
    for event in ordered:
        if event.timestamp.tzinfo is None or event.timestamp.utcoffset() is None:
            ignored += 1
            continue
        kind = event.event_type
        if kind == "process.baseline":
            coverage["processes"] = (
                "partial: baseline count only; pre-existing process instances are not enumerated"
            )
            continue
        if kind in {"process.started_observed", "process.replaced_observed"}:
            if kind == "process.replaced_observed":
                old_created = event.data.get("previous_create_time")
                if old_created is not None:
                    try:
                        old_created = float(old_created)
                    except (TypeError, ValueError):
                        old_created = None
                    if old_created is not None and math.isfinite(old_created) and old_created >= 0:
                        old_key = (event.host_id, _pid(event), old_created)
                        old_instance = processes.get(old_key)
                        if old_instance is not None:
                            if event.timestamp >= old_instance.last_observed:
                                old_instance.status = "replaced"
                                old_instance.last_observed = event.timestamp
                            _append_evidence(old_instance, event.event_id)
            key = _process_key(event)
            if key is None:
                ignored += 1
                continue
            host, pid, created = key
            image = event.entity.name
            existing = processes.get(key)
            if existing is None:
                processes[key] = ProcessInstance(
                    host, pid, created, image, "running",
                    event.timestamp, event.timestamp, [event.event_id],
                )
            else:
                if event.timestamp >= existing.last_observed:
                    existing.status = "running"
                    existing.image = image
                    existing.last_observed = event.timestamp
                _append_evidence(existing, event.event_id)
            continue
        if kind == "process.stopped_observed":
            key = _process_key(event)
            if key is None or key not in processes:
                # Never close a process using PID alone or an unknown instance.
                ignored += 1
                continue
            instance = processes[key]
            if event.timestamp >= instance.last_observed:
                instance.status = "stopped"
                instance.last_observed = event.timestamp
            _append_evidence(instance, event.event_id)
            continue
        if kind == "process.start_confirmed_by_etw":
            key = _process_key(event)
            if key is None or key not in processes:
                ignored += 1
                continue
            instance = processes[key]
            instance.etw_confirmed = True
            instance.last_observed = max(instance.last_observed, event.timestamp)
            _append_evidence(instance, event.event_id)
            continue

        if kind.startswith("inventory.") and kind.endswith(".baseline"):
            collection = kind[len("inventory."):-len(".baseline")]
            coverage[collection] = (
                "partial: collection count plus any entity-level records in this evidence window"
            )
            continue
        if kind.startswith("inventory.") and kind.endswith((
            ".present_observed", ".added", ".changed", ".removed"
        )):
            remainder = kind[len("inventory."):]
            collection, action = remainder.rsplit(".", 1)
            identity = event.entity.stable_id or event.entity.name
            if not identity:
                ignored += 1
                continue
            key = (event.host_id, collection, identity)
            payload = event.data.get("current") or event.data.get("previous") or {}
            if not isinstance(payload, dict):
                ignored += 1
                continue
            existing = entities.get(key)
            if action == "removed":
                status = "removed"
                current = dict(payload)
            else:
                status = "present"
                current = dict(payload)
            if existing is None:
                entities[key] = EntityState(
                    event.host_id, collection, identity, event.entity.type,
                    event.entity.name, status, current, event.timestamp,
                    event.timestamp, [event.event_id],
                )
            else:
                if event.timestamp >= existing.last_observed:
                    existing.status = status
                    existing.current = current
                    existing.last_observed = event.timestamp
                _append_evidence(existing, event.event_id)
            coverage[collection] = (
                "partial: observed entities only; failed or unobserved snapshots remain unknown"
            )
            continue

        if kind == "windows.service.state_changed":
            service = event.data.get("service")
            state = event.data.get("state")
            if (
                not isinstance(service, str) or not service
                or not isinstance(state, str) or not state
            ):
                ignored += 1
                continue
            key = (event.host_id, "services", service)
            current = {"name": service, "status": state}
            existing = entities.get(key)
            if existing is None:
                entities[key] = EntityState(
                    event.host_id, "services", service, "service", service,
                    "present", current, event.timestamp, event.timestamp,
                    [event.event_id],
                )
            else:
                if event.timestamp >= existing.last_observed:
                    existing.current = current
                    existing.status = "present"
                    existing.last_observed = event.timestamp
                _append_evidence(existing, event.event_id)
            coverage["services"] = "partial: Event Log transitions and sampled inventory evidence"
            continue

    return EnvironmentProjection(processes, entities, coverage, ignored)
