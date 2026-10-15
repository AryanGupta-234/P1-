from datetime import datetime, timezone, timedelta

from aie.contracts import AIEEvent, EntityRef
from aie.state_model import project_environment_state


def event(
    event_id, kind, when, *, host="host-a", name="demo.exe",
    entity_type="process", stable="42", data=None,
):
    return AIEEvent(
        event_id=event_id,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=when),
        host_id=host, source="test", event_type=kind,
        entity=EntityRef(type=entity_type, name=name, stable_id=stable),
        data=data or {},
    )


def test_process_projection_uses_host_pid_and_creation_time():
    events = [
        event("start", "process.started_observed", 1, data={"pid": 42, "create_time": 10.0}),
        event("stop", "process.stopped_observed", 5, data={"pid": 42, "create_time": 10.0}),
        event("reuse", "process.started_observed", 6, data={"pid": 42, "create_time": 20.0}),
    ]
    projection = project_environment_state(events)
    assert projection.processes[("host-a", 42, 10.0)].status == "stopped"
    assert projection.processes[("host-a", 42, 20.0)].status == "running"


def test_pid_replacement_closes_only_the_exact_previous_instance():
    events = [
        event("start-old", "process.started_observed", 1,
              data={"pid": 42, "create_time": 10.0}),
        event("replace", "process.replaced_observed", 2,
              data={"pid": 42, "create_time": 20.0, "previous_create_time": 10.0}),
    ]
    projection = project_environment_state(events)
    assert projection.processes[("host-a", 42, 10.0)].status == "replaced"
    assert projection.processes[("host-a", 42, 20.0)].status == "running"
    assert "replace" in projection.processes[("host-a", 42, 10.0)].evidence_ids


def test_pid_only_stop_cannot_close_a_process_instance():
    events = [
        event("start", "process.started_observed", 1, data={"pid": 42, "create_time": 10.0}),
        event("bad-stop", "process.stopped_observed", 5, data={"pid": 42}),
    ]
    projection = project_environment_state(events)
    assert projection.processes[("host-a", 42, 10.0)].status == "running"
    assert projection.ignored_events == 1


def test_etw_confirmation_attaches_only_to_existing_matching_instance():
    events = [
        event("confirm-first", "process.start_confirmed_by_etw", 1,
              data={"pid": 42, "process_create_time": 10.0}),
        event("start", "process.started_observed", 2,
              data={"pid": 42, "create_time": 10.0}),
        event("confirm", "process.start_confirmed_by_etw", 3,
              data={"pid": 42, "process_create_time": 10.0}),
    ]
    projection = project_environment_state(events)
    instance = projection.processes[("host-a", 42, 10.0)]
    assert instance.etw_confirmed is True
    assert "confirm-first" not in instance.evidence_ids
    assert "confirm" in instance.evidence_ids
    assert projection.ignored_events == 1


def test_inventory_baseline_and_service_transition_are_projected():
    events = [
        event("baseline", "inventory.services.baseline", 1,
              entity_type="service", name="services", stable="services",
              data={"item_count": 1, "coverage": "count_only"}),
        event("present", "inventory.services.present_observed", 2,
              entity_type="service", name="Spooler", stable="Spooler",
              data={"current": {"name": "Spooler", "status": "running"}}),
        event("transition", "windows.service.state_changed", 3,
              entity_type="service", name="Spooler", stable="99",
              data={"service": "Spooler", "state": "stopped"}),
    ]
    projection = project_environment_state(events)
    service = projection.entities[("host-a", "services", "Spooler")]
    assert service.current["status"] == "stopped"
    assert service.status == "present"
    assert service.evidence_ids == ["present", "transition"]


def test_inventory_removal_is_explicit_and_unknown_absence_is_not_removal():
    events = [
        event("present", "inventory.services.present_observed", 1,
              entity_type="service", name="Svc", stable="Svc",
              data={"current": {"name": "Svc", "status": "running"}}),
        event("removed", "inventory.services.removed", 2,
              entity_type="service", name="Svc", stable="Svc",
              data={"previous": {"name": "Svc", "status": "running"}}),
    ]
    projection = project_environment_state(events)
    assert projection.entities[("host-a", "services", "Svc")].status == "removed"
    assert projection.coverage["services"].startswith("partial")


def test_projection_serialization_round_trip_and_incremental_update():
    first = event(
        "start", "process.started_observed", 1,
        data={"pid": 42, "create_time": 10.0},
    )
    initial = project_environment_state([first])
    restored = type(initial).from_dict(initial.to_dict())
    stop = event(
        "stop", "process.stopped_observed", 2,
        data={"pid": 42, "create_time": 10.0},
    )
    resumed = project_environment_state([stop], initial=restored)
    instance = resumed.processes[("host-a", 42, 10.0)]
    assert instance.status == "stopped"
    assert instance.evidence_ids == ["start", "stop"]
