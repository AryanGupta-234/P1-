"""Deterministic, provenance-preserving context packets from projected state."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aie.state_model import EnvironmentProjection


def build_environment_context(
    projection: EnvironmentProjection,
    *,
    max_processes: int = 50,
    max_entities: int = 100,
) -> dict[str, Any]:
    """Build a bounded factual context packet; never infer absent relationships."""
    if not 1 <= max_processes <= 500:
        raise ValueError("max_processes must be between 1 and 500")
    if not 1 <= max_entities <= 1000:
        raise ValueError("max_entities must be between 1 and 1000")
    processes = sorted(
        projection.processes.values(),
        key=lambda item: (
            item.status != "running", -item.last_observed.timestamp(), item.pid
        ),
    )
    entities = sorted(
        projection.entities.values(),
        key=lambda item: (item.collection, item.name.casefold(), item.identity),
    )
    selected_processes = processes[:max_processes]
    selected_entities = entities[:max_entities]

    def observed(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    return {
        "context_schema": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantics": {
            "kind": "observed_state_summary",
            "inference_performed": False,
            "absence_means_removal": False,
            "evidence_reference_field": "evidence_ids",
        },
        "coverage": dict(sorted(projection.coverage.items())),
        "processes": [
            {
                "host_id": item.host_id, "pid": item.pid,
                "create_time": item.create_time, "image": item.image,
                "status": item.status,
                "first_observed": observed(item.first_observed),
                "last_observed": observed(item.last_observed),
                "etw_confirmed": item.etw_confirmed,
                "evidence_ids": list(item.evidence_ids),
                "evidence_truncated": getattr(item, "evidence_truncated", False),
            }
            for item in selected_processes
        ],
        "entities": [
            {
                "host_id": item.host_id, "collection": item.collection,
                "identity": item.identity, "entity_type": item.entity_type,
                "name": item.name, "status": item.status, "current": item.current,
                "first_observed": observed(item.first_observed),
                "last_observed": observed(item.last_observed),
                "evidence_ids": list(item.evidence_ids),
                "evidence_truncated": getattr(item, "evidence_truncated", False),
            }
            for item in selected_entities
        ],
        "limits": {
            "processes_included": len(selected_processes),
            "processes_omitted": max(0, len(processes) - len(selected_processes)),
            "entities_included": len(selected_entities),
            "entities_omitted": max(0, len(entities) - len(selected_entities)),
            "ignored_source_events": projection.ignored_events,
        },
    }
