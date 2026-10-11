import pytest

from aie.providers.etw_process import WindowsETWProcessProvider


class FakeEvent:
    def __init__(self, event_id, properties, provider="Microsoft-Windows-Kernel-Process"):
        self.event_id = event_id
        self.provider_name = provider
        self._properties = properties

    def to_dict(self):
        return {"properties": self._properties}


class FakeSession:
    def __init__(self, events):
        self.events = list(events)
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def next_event_timeout(self, timeout_ms):
        if self.events:
            return self.events.pop(0)
        return None


def make_provider(events):
    session = FakeSession(events)
    provider = WindowsETWProcessProvider(
        session_factory=lambda: session,
        require_admin=False,
        timeout_ms=1,
    )
    return provider, session


def test_normalizes_process_start_without_command_line_or_path():
    provider, session = make_provider([
        FakeEvent(1, {
            "ProcessId": 4321,
            "ParentId": 123,
            "ImageFileName": r"C:\Users\Public\demo.exe",
            "UniqueProcessKey": 98765,
        })
    ])
    try:
        event = next((item for _ in range(20) for item in provider.collect_snapshot()), None)
        assert event is not None
        assert event.event_type == "process.etw_start"
        assert event.entity.stable_id == "4321:98765"
        assert event.data["process_name"] == "demo.exe"
        assert event.data["command_line_collected"] is False
        assert event.data["executable_path_collected"] is False
    finally:
        provider.close()
    assert session.started is True
    assert session.stopped is True


def test_normalizes_process_stop_and_ignores_unknown_event_ids():
    provider, _ = make_provider([
        FakeEvent(99, {"ProcessId": 9}),
        FakeEvent(2, {"ProcessId": 4321, "ImageName": "demo.exe"}),
    ])
    try:
        collected = []
        for _ in range(20):
            collected.extend(provider.collect_snapshot())
            if collected:
                break
        assert len(collected) == 1
        assert collected[0].event_type == "process.etw_stop"
        assert collected[0].data["lifecycle"] == "stop"
    finally:
        provider.close()


def test_provider_reports_consumer_queue_drops():
    provider, _ = make_provider([])
    try:
        provider._queue_drops = 4
        events = provider.collect_snapshot()
        health = next(event for event in events if "queue_drop" in event.event_type)
        assert health.data["dropped_events"] == 4
        assert health.data["loss_kind"] == "consumer_queue_drop"
    finally:
        provider.close()


def test_provider_requires_admin_by_default(monkeypatch):
    monkeypatch.setattr(
        "aie.providers.etw_process._is_windows_admin",
        lambda: False,
    )
    with pytest.raises(PermissionError, match="elevated"):
        WindowsETWProcessProvider(
            session_factory=lambda: FakeSession([]),
            require_admin=True,
        )


def test_provider_rejects_unbounded_configuration():
    with pytest.raises(ValueError):
        WindowsETWProcessProvider(
            session_factory=lambda: FakeSession([]),
            require_admin=False,
            max_events_per_poll=5000,
        )
