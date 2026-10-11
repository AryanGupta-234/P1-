from pathlib import Path

from aie import runtime


class FakeWindowsProvider:
    def __init__(self):
        self.calls = 0

    def collect_snapshot(self, *, include_host=True):
        self.calls += 1
        return []


def install_fake_clock(monkeypatch):
    state = {"now": 0.0}

    def monotonic():
        return state["now"]

    def sleep(seconds):
        state["now"] += seconds

    monkeypatch.setattr(runtime.time, "monotonic", monotonic)
    monkeypatch.setattr(runtime.time, "sleep", sleep)


def test_paused_observer_collects_no_events(tmp_path: Path, monkeypatch):
    provider = FakeWindowsProvider()
    install_fake_clock(monkeypatch)
    monkeypatch.setattr(runtime, "WindowsProvider", lambda: provider)
    monkeypatch.setattr(runtime, "observer_is_paused", lambda: True)

    total = runtime.observe(
        duration=1,
        interval=0.5,
        db_path=tmp_path / "paused.sqlite3",
        include_network=False,
        include_foreground=False,
    )

    assert total == 0
    assert provider.calls == 0


def test_unpaused_observer_resumes_sampling(tmp_path: Path, monkeypatch):
    provider = FakeWindowsProvider()
    install_fake_clock(monkeypatch)
    monkeypatch.setattr(runtime, "WindowsProvider", lambda: provider)
    monkeypatch.setattr(runtime, "observer_is_paused", lambda: False)

    total = runtime.observe(
        duration=1,
        interval=0.5,
        db_path=tmp_path / "running.sqlite3",
        include_network=False,
        include_foreground=False,
    )

    assert total == 0
    assert provider.calls == 2


def test_opt_in_eventlog_provider_is_polled_and_persisted(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from aie.contracts import AIEEvent, EntityRef
    from aie.store import EventStore

    provider = FakeWindowsProvider()
    eventlog_calls = []

    class FakeEventLogProvider:
        def __init__(self, *, channels, max_records_per_channel):
            assert channels == ("Application", "System")
            assert max_records_per_channel == 5

        def collect_snapshot(self):
            eventlog_calls.append(True)
            return [AIEEvent(
                event_id="eventlog-001",
                timestamp=datetime.now(timezone.utc),
                host_id="host-a",
                source="windows.eventlog",
                event_type="windows.eventlog.record",
                entity=EntityRef(type="windows_event", name="TestProvider", stable_id="System:101"),
                data={"channel": "System", "record_number": 101, "message_collected": False},
            )]

    install_fake_clock(monkeypatch)
    monkeypatch.setattr(runtime, "WindowsProvider", lambda: provider)
    monkeypatch.setattr(runtime, "WindowsEventLogProvider", FakeEventLogProvider)
    monkeypatch.setattr(runtime, "observer_is_paused", lambda: False)

    db_path = tmp_path / "observer-eventlog.sqlite3"
    added = runtime.observe(
        duration=1,
        interval=0.5,
        db_path=db_path,
        include_network=False,
        include_foreground=False,
        include_event_logs=True,
        event_log_channels=("Application", "System"),
        event_log_max_records=5,
    )

    stored = EventStore(db_path)
    assert eventlog_calls
    assert added >= 1
    assert stored.get("eventlog-001") is not None
