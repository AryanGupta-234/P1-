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


def test_observer_continues_after_collector_exception(monkeypatch, tmp_path):
    import aie.runtime as runtime
    from aie.contracts import AIEEvent, EntityRef
    from aie.store import EventStore

    clock = [0.0]
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        runtime.time, "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    class Provider:
        calls = 0

        def __init__(self):
            pass

        def collect_snapshot(self, include_host=True):
            self.calls += 1
            if self.calls == 1:
                raise PermissionError("not included in event")
            return [AIEEvent(
                host_id="test", source="test", event_type="process.sample",
                entity=EntityRef(type="process", name="sample"),
            )]

        def collect_state_deltas(self):
            return []

    monkeypatch.setattr(runtime, "WindowsProvider", Provider)
    monkeypatch.setattr(runtime, "host_id", lambda: "test")
    path = tmp_path / "observer.sqlite3"
    runtime.observe(1, 0.5, path)
    stored = EventStore(path).recent(20)
    assert any(item.event_type == "observer.collector_error" for item in stored)
    assert any(item.event_type == "observer.collector_recovered" for item in stored)
    assert any(item.event_type == "process.sample" for item in stored)
