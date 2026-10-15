"""Event-sourced, evidence-preserving projection of observed Windows state.

This is a bounded view over retained events, not an authoritative live inventory.
Missing evidence remains unknown; absence from a query window never means removal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from aie.contracts import AIEEvent


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


@dataclass
class EnvironmentProjection:
    processes: dict[tuple[str, int, float], ProcessInstance]
    entities: dict[tuple[str, str, str], EntityState]
    coverage: dict[str, str]
    ignored_events: int = 0


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


def _append_evidence(ids: list[str], event_id: str) -> None:
    if event_id not in ids:
        ids.append(event_id)


def project_environment_state(events: Iterable[AIEEvent]) -> EnvironmentProjection:
    """Replay events chronologically and preserve exact process-instance identity."""
    processes: dict[tuple[str, int, float], ProcessInstance] = {}
    entities: dict[tuple[str, str, str], EntityState] = {}
    coverage: dict[str, str] = {
        "processes": "partial: initial process baseline stores only a count",
        "services": "unknown until an entity-level baseline or delta is observed",
        "network_interfaces": "unknown until an entity-level baseline or delta is observed",
        "scheduled_tasks": "unknown until an entity-level baseline or delta is observed",
        "applications": "unknown until an entity-level baseline or delta is observed",
    }
    ignored = 0

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
                existing.status = "running"
                existing.image = image
                existing.last_observed = max(existing.last_observed, event.timestamp)
                _append_evidence(existing.evidence_ids, event.event_id)
            continue
        if kind == "process.stopped_observed":
            key = _process_key(event)
            if key is None or key not in processes:
                # Never close a process using PID alone or an unknown instance.
                ignored += 1
                continue
            instance = processes[key]
            instance.status = "stopped"
            instance.last_observed = max(instance.last_observed, event.timestamp)
            _append_evidence(instance.evidence_ids, event.event_id)
            continue
        if kind == "process.start_confirmed_by_etw":
            key = _process_key(event)
            if key is None or key not in processes:
                ignored += 1
                continue
            instance = processes[key]
            instance.etw_confirmed = True
            instance.last_observed = max(instance.last_observed, event.timestamp)
            _append_evidence(instance.evidence_ids, event.event_id)
            continue

        if kind.startswith("inventory.") and kind.endswith(".baseline"):
            collection = kind[len("inventory."):-len(".baseline")]
            coverage[collection] = "partial: baseline event has collection count; per-item records follow when available"
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
                existing.status = status
                existing.current = current
                existing.last_observed = max(existing.last_observed, event.timestamp)
                _append_evidence(existing.evidence_ids, event.event_id)
            coverage[collection] = "partial: observed entities only; failed or unobserved snapshots remain unknown"
            continue

        if kind == "windows.service.state_changed":
            service = event.data.get("service")
            state = event.data.get("state")
            if not isinstance(service, str) or not service or not isinstance(state, str) or not state:
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
                existing.current = current
                existing.status = "present"
                existing.last_observed = max(existing.last_observed, event.timestamp)
                _append_evidence(existing.evidence_ids, event.event_id)
            coverage["services"] = "partial: Event Log transitions and sampled inventory evidence"
            continue

    return EnvironmentProjection(processes, entities, coverage, ignored)
