from datetime import datetime, timedelta, timezone

import pytest

from aie.state_model import EnvironmentProjection, EntityState, ProcessInstance
from aie.state_compaction import compact_projection


NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def sample_projection():
    old = NOW - timedelta(days=90)
    recent = NOW - timedelta(days=2)
    processes = {}
    for pid, when, status in [
        (1, old - timedelta(days=20), "stopped"),
        (2, old - timedelta(days=10), "replaced"),
        (3, old, "stopped"),
        (4, recent, "stopped"),
        (5, old - timedelta(days=30), "running"),
    ]:
        processes[("host", pid, float(pid))] = ProcessInstance(
            "host", pid, float(pid), f"p{pid}.exe", status,
            when - timedelta(minutes=1), when, [f"p{pid}"],
        )
    entities = {}
    for name, when, status in [
        ("old-a", old - timedelta(days=20), "removed"),
        ("old-b", old - timedelta(days=10), "removed"),
        ("recent", recent, "removed"),
        ("present", old - timedelta(days=30), "present"),
    ]:
        entities[("host", "services", name)] = EntityState(
            "host", "services", name, "service", name, status, {},
            when - timedelta(minutes=1), when, [name],
        )
    return EnvironmentProjection(processes, entities, {"processes": "partial"}, 0)


def test_compaction_only_removes_excess_old_terminal_records():
    original = sample_projection()
    result = compact_projection(original, older_than=NOW - timedelta(days=60), max_terminal_records=1)
    compacted = result.projection
    assert result.processes_removed == 2
    assert result.entities_removed == 1
    assert ("host", 1, 1.0) not in compacted.processes
    assert ("host", 2, 2.0) not in compacted.processes
    assert ("host", 3, 3.0) in compacted.processes
    assert ("host", 4, 4.0) in compacted.processes
    assert ("host", 5, 5.0) in compacted.processes
    assert ("host", "services", "old-a") not in compacted.entities
    assert ("host", "services", "old-b") in compacted.entities
    assert ("host", "services", "recent") in compacted.entities
    assert ("host", "services", "present") in compacted.entities
    assert len(original.processes) == 5
    assert compacted.coverage["compaction.processes_pruned_total"] == "2"


def test_compaction_can_remove_all_eligible_old_terminal_records():
    result = compact_projection(
        sample_projection(), older_than=NOW - timedelta(days=60), max_terminal_records=0
    )
    assert result.processes_removed == 3
    assert result.entities_removed == 2
    assert all(item.status == "running" or item.last_observed >= NOW - timedelta(days=60)
               for item in result.projection.processes.values())


def test_compaction_requires_aware_cutoff_and_bounded_limit():
    projection = sample_projection()
    with pytest.raises(ValueError):
        compact_projection(projection, older_than=datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        compact_projection(projection, older_than=NOW, max_terminal_records=-1)


def test_entity_terminal_limit_is_applied_per_inventory_collection():
    projection = sample_projection()
    when = NOW - timedelta(days=120)
    for collection in ("applications", "scheduled_tasks"):
        for suffix in ("a", "b"):
            name = collection + suffix
            projection.entities[("host", collection, name)] = EntityState(
                "host", collection, name, collection, name, "removed", {},
                when - timedelta(minutes=1), when, [name],
            )
    result = compact_projection(
        projection, older_than=NOW - timedelta(days=60), max_terminal_records=1
    )
    assert ("host", "applications", "applicationsa") not in result.projection.entities
    assert ("host", "applications", "applicationsb") in result.projection.entities
    assert ("host", "scheduled_tasks", "scheduled_tasksa") not in result.projection.entities
    assert ("host", "scheduled_tasks", "scheduled_tasksb") in result.projection.entities
