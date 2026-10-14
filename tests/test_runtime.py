from aie.runtime import _health_event


def test_collector_error_event_has_diagnostic_fields():
    event = _health_event(
        "observer.collector_error",
        "process_snapshot",
        {"exception_type": "PermissionError", "consecutive_failures": 2},
    )
    assert event.event_type == "observer.collector_error"
    assert event.entity.name == "process_snapshot"
    assert event.data["consecutive_failures"] == 2
