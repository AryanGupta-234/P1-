import pytest

from aie.delta import SnapshotDeltaTracker


def tracker():
    return SnapshotDeltaTracker()


def update(instance, items):
    return instance.update(
        collection="services",
        items=items,
        identity_field="name",
        entity_type="service",
        source="test.snapshot",
        host_id="test-host",
    )


def test_first_snapshot_only_establishes_baseline():
    events = update(tracker(), [{"name": "Spooler", "status": "running"}])
    assert len(events) == 1
    assert events[0].event_type == "inventory.services.baseline"
    assert events[0].data == {"item_count": 1}


def test_detects_add_remove_and_change():
    subject = tracker()
    update(subject, [
        {"name": "Spooler", "status": "running"},
        {"name": "W32Time", "status": "stopped"},
    ])

    events = update(subject, [
        {"name": "Spooler", "status": "stopped"},
        {"name": "NewSvc", "status": "running"},
    ])
    assert [(event.event_type, event.entity.name) for event in events] == [
        ("inventory.services.added", "NewSvc"),
        ("inventory.services.removed", "W32Time"),
        ("inventory.services.changed", "Spooler"),
    ]
    changed = events[-1]
    assert changed.data["previous"]["status"] == "running"
    assert changed.data["current"]["status"] == "stopped"
    assert all(event.evidence_kind == "derived" for event in events)


def test_order_does_not_create_false_positive_events():
    subject = tracker()
    update(subject, [{"name": "A", "status": "up"}, {"name": "B", "status": "down"}])
    assert update(subject, [{"name": "B", "status": "down"}, {"name": "A", "status": "up"}]) == []


def test_input_mutation_does_not_change_remembered_snapshot():
    subject = tracker()
    item = {"name": "A", "status": "up"}
    update(subject, [item])
    item["status"] = "down"
    assert update(subject, [{"name": "A", "status": "up"}]) == []


def test_duplicate_identity_fails_closed():
    with pytest.raises(ValueError, match="duplicate identity"):
        update(tracker(), [{"name": "A"}, {"name": "A"}])


def test_missing_identity_is_ignored():
    events = update(tracker(), [{"status": "running"}, {"name": "A", "status": "up"}])
    assert events[0].data["item_count"] == 1
