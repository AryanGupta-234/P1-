from pathlib import Path

from aie import runtime


class FakeWindowsProvider:
    name = "windows.user_mode"

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


def test_unpaused_observer_resumes_sampling_and_emits_health(tmp_path: Path, monkeypatch):
    provider = FakeWindowsProvider()
    install_fake_clock(monkeypatch)
    monkeypatch.setattr(runtime, "WindowsProvider", lambda: provider)
    monkeypatch.setattr(runtime, "observer_is_paused", lambda: False)

    db_path = tmp_path / "running.sqlite3"
    total = runtime.observe(
        duration=1,
        interval=0.5,
        db_path=db_path,
        include_network=False,
        include_foreground=False,
    )

    from aie.store import EventStore
    stored = EventStore(db_path)
    health_events = stored.query_events(event_types=["observer.health"], limit=10)

    assert total == 1
    assert provider.calls == 2
    assert len(health_events) == 1
    assert health_events[0].data["providers"]["windows.user_mode"]["samples_attempted"] == 1


def test_provider_failure_is_isolated_and_reported_in_health(tmp_path: Path, monkeypatch):
    from aie.store import EventStore

    class FailingForegroundProvider:
        name = "windows.foreground"

        def __init__(self, **kwargs):
            pass

        def collect_snapshot(self):
            raise PermissionError("this private message must never be persisted")

    provider = FakeWindowsProvider()
    install_fake_clock(monkeypatch)
    monkeypatch.setattr(runtime, "WindowsProvider", lambda: provider)
    monkeypatch.setattr(runtime, "WindowsForegroundProvider", FailingForegroundProvider)
    monkeypatch.setattr(runtime, "observer_is_paused", lambda: False)

    db_path = tmp_path / "failing-provider.sqlite3"
    total = runtime.observe(
        duration=1,
        interval=0.5,
        db_path=db_path,
        include_network=False,
        include_foreground=True,
        include_video_diagnostics=False,
    )

    health_events = EventStore(db_path).query_events(
        event_types=["observer.health"],
        limit=10,
    )
    assert total == 1
    assert health_events
    foreground_health = health_events[-1].data["providers"]["windows.foreground"]
    assert foreground_health["state"] == "degraded"
    assert foreground_health["errors"] == 1
    assert foreground_health["last_error_type"] == "PermissionError"
    assert "private message" not in str(health_events[-1].data)


def test_opt_in_eventlog_provider_is_polled_and_persisted(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from aie.contracts import AIEEvent, EntityRef
    from aie.store import EventStore

    provider = FakeWindowsProvider()
    eventlog_calls = []

    class FakeEventLogProvider:
        name = "windows.eventlog"

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


def test_opt_in_system_process_resource_provider_is_polled_and_persisted(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from aie.contracts import AIEEvent, EntityRef
    from aie.store import EventStore

    calls = []

    class FakeProcessResourceProvider:
        name = "windows.process_resources"

        def __init__(self, *, max_processes, sample_interval):
            assert max_processes == 64
            assert sample_interval == 10.0

        def collect_snapshot(self):
            calls.append(True)
            return [AIEEvent(
                event_id="process-resource-001",
                timestamp=datetime.now(timezone.utc),
                host_id="host-a",
                source="windows.process_resources",
                event_type="process.system_resource_snapshot",
                entity=EntityRef(type="host_process_set", name="top_process_consumers"),
                data={
                    "total_processes_seen": 20,
                    "sampled_processes": 20,
                    "reported_processes": 10,
                    "truncated": False,
                    "processes": [{"pid": 10, "process_name": "browser.exe"}],
                },
            )]

    install_fake_clock(monkeypatch)
    monkeypatch.setattr(runtime, "WindowsProvider", FakeWindowsProvider)
    monkeypatch.setattr(
        runtime,
        "WindowsProcessResourceProvider",
        FakeProcessResourceProvider,
    )
    monkeypatch.setattr(runtime, "observer_is_paused", lambda: False)

    db_path = tmp_path / "observer-process-resources.sqlite3"
    added = runtime.observe(
        duration=1,
        interval=0.5,
        db_path=db_path,
        include_network=False,
        include_foreground=False,
        include_process_resources=True,
        process_resource_interval=10.0,
        process_resource_max_processes=64,
        include_video_diagnostics=False,
    )

    stored = EventStore(db_path)
    assert calls == [True]
    assert added >= 1
    assert stored.get("process-resource-001") is not None



def test_opt_in_etw_provider_is_polled_and_closed(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from aie.contracts import AIEEvent, EntityRef
    from aie.store import EventStore

    provider = FakeWindowsProvider()
    calls = []

    class FakeEtwProvider:
        name = "windows.etw.process"

        def __init__(self, *, max_events_per_poll):
            assert max_events_per_poll == 7
            self.closed = False
            self.paused = 0
            self.resumed = 0

        def collect_snapshot(self):
            calls.append("collect")
            return [AIEEvent(
                event_id="etw-001",
                timestamp=datetime.now(timezone.utc),
                host_id="host-a",
                source="windows.etw.process",
                event_type="process.etw_start",
                entity=EntityRef(type="process", name="demo.exe", stable_id="4321"),
                data={"pid": 4321, "process_name": "demo.exe", "lifecycle": "start"},
            )]

        def pause(self):
            self.paused += 1

        def resume(self):
            self.resumed += 1

        def close(self):
            self.closed = True

    install_fake_clock(monkeypatch)
    monkeypatch.setattr(runtime, "WindowsProvider", lambda: provider)
    monkeypatch.setattr(runtime, "WindowsETWProcessProvider", FakeEtwProvider)
    monkeypatch.setattr(runtime, "observer_is_paused", lambda: False)

    db_path = tmp_path / "observer-etw.sqlite3"
    added = runtime.observe(
        duration=1,
        interval=0.5,
        db_path=db_path,
        include_network=False,
        include_foreground=False,
        include_event_logs=False,
        include_process_resources=False,
        include_etw=True,
        etw_max_events_per_poll=7,
        include_video_diagnostics=False,
    )

    assert calls
    assert added >= 1
    assert EventStore(db_path).get("etw-001") is not None


def test_etw_loss_is_reflected_in_observer_health(tmp_path: Path, monkeypatch):
    from datetime import datetime, timezone

    from aie.contracts import AIEEvent, EntityRef
    from aie.store import EventStore

    provider = FakeWindowsProvider()

    class FakeETWProvider:
        name = "windows.etw.process"

        def __init__(self, *, max_events_per_poll):
            assert max_events_per_poll == 7
            self.calls = 0

        def collect_snapshot(self):
            self.calls += 1
            if self.calls > 1:
                return []
            return [AIEEvent(
                event_id="etw-health-001",
                timestamp=datetime.now(timezone.utc),
                host_id="host-a",
                source=self.name,
                event_type="process.etw_health.queue_drop",
                entity=EntityRef(type="etw_session", name="kernel_process"),
                data={"dropped_events": 4, "loss_kind": "consumer_queue_drop"},
            )]

        def pause(self):
            pass

        def resume(self):
            pass

        def close(self):
            pass

    install_fake_clock(monkeypatch)
    monkeypatch.setattr(runtime, "WindowsProvider", lambda: provider)
    monkeypatch.setattr(runtime, "WindowsETWProcessProvider", FakeETWProvider)
    monkeypatch.setattr(runtime, "observer_is_paused", lambda: False)

    db_path = tmp_path / "etw-loss.sqlite3"
    total = runtime.observe(
        duration=1,
        interval=0.5,
        db_path=db_path,
        include_network=False,
        include_foreground=False,
        include_etw=True,
        etw_max_events_per_poll=7,
        include_video_diagnostics=False,
    )

    health_events = EventStore(db_path).query_events(event_types=["observer.health"], limit=10)
    assert total == 2
    assert health_events[-1].data["providers"]["windows.etw.process"]["event_loss"] == 4
