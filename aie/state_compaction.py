"""Explicit age-gated compaction for terminal environment projection records.

Raw event history is never deleted by this module. Only old terminal entries in
the saved projection are eligible, and recent or live state is preserved.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from aie.state_model import EnvironmentProjection


@dataclass(frozen=True)
class CompactionResult:
    projection: EnvironmentProjection
    processes_removed: int
    entities_removed: int
    cutoff: datetime
    max_terminal_records: int


def compact_projection(
    projection: EnvironmentProjection,
    *,
    older_than: datetime,
    max_terminal_records: int = 1000,
) -> CompactionResult:
    """Drop excess old terminal records, retaining the newest bounded tail."""
    if not isinstance(projection, EnvironmentProjection):
        raise ValueError("projection must be an EnvironmentProjection")
    if not isinstance(older_than, datetime) or older_than.tzinfo is None or older_than.utcoffset() is None:
        raise ValueError("older_than must be timezone-aware")
    if isinstance(max_terminal_records, bool) or not isinstance(max_terminal_records, int) or not 0 <= max_terminal_records <= 10000:
        raise ValueError("max_terminal_records must be between 0 and 10000")

    result = deepcopy(projection)
    process_candidates = [
        (key, item) for key, item in result.processes.items()
        if item.status in {"stopped", "replaced"} and item.last_observed < older_than
    ]
    entity_candidates = [
        (key, item) for key, item in result.entities.items()
        if item.status == "removed" and item.last_observed < older_than
    ]
    # Keep the newest old terminal records; all records newer than cutoff remain.
    process_candidates.sort(key=lambda pair: (pair[1].last_observed, str(pair[0])), reverse=True)
    entity_candidates.sort(key=lambda pair: (pair[1].last_observed, str(pair[0])), reverse=True)
    remove_processes = process_candidates[max_terminal_records:]
    remove_entities = entity_candidates[max_terminal_records:]
    for key, _ in remove_processes:
        result.processes.pop(key, None)
    for key, _ in remove_entities:
        result.entities.pop(key, None)

    def prior_count(key: str) -> int:
        try:
            return max(0, int(result.coverage.get(key, "0")))
        except (TypeError, ValueError):
            return 0

    result.coverage["compaction.processes_pruned_total"] = str(
        prior_count("compaction.processes_pruned_total") + len(remove_processes)
    )
    result.coverage["compaction.entities_pruned_total"] = str(
        prior_count("compaction.entities_pruned_total") + len(remove_entities)
    )
    result.coverage["compaction.last_cutoff_utc"] = older_than.astimezone(timezone.utc).isoformat()
    result.coverage["compaction.max_terminal_records"] = str(max_terminal_records)

    return CompactionResult(
        result, len(remove_processes), len(remove_entities), older_than, max_terminal_records
    )
