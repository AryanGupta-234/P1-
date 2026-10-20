import subprocess

import pytest

from aie.providers.eventlog import (
    EventLogError,
    WindowsEventLogProvider,
    parse_system_events,
)


XML = """<Events xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
<Event><System><Provider Name="Service Control Manager"/><EventID>7036</EventID>
<TimeCreated SystemTime="2026-10-14T10:00:00.000Z"/><EventRecordID>77</EventRecordID>
</System><EventData><Data Name="param1">Windows Update</Data>
<Data Name="param2">running</Data></EventData>
<RenderingInfo><Message>Do not persist this rendered message.</Message></RenderingInfo></Event>
<Event><System><Provider Name="Microsoft-Windows-Kernel-Power"/><EventID>42</EventID>
<TimeCreated SystemTime="2026-10-14T10:01:00.000Z"/><EventRecordID>78</EventRecordID>
</System></Event>
<Event><System><Provider Name="Other"/><EventID>1</EventID>
<TimeCreated SystemTime="2026-10-14T10:02:00.000Z"/><EventRecordID>79</EventRecordID>
</System></Event>
</Events>"""


def test_event_log_parser_enforces_allowlist_and_minimal_fields():
    events = parse_system_events(XML, event_host_id="host-test")
    assert [event.event_type for event in events] == [
        "windows.service.state_changed", "windows.power.sleep"
    ]
    assert events[0].entity.name == "Windows Update"
    assert events[0].data == {
        "record_id": 77, "event_id": 7036,
        "service": "Windows Update", "state": "running",
    }
    assert "Do not persist" not in str(events[0].data)
    assert all(event.host_id == "host-test" for event in events)


def test_event_log_event_ids_are_deterministic():
    first = parse_system_events(XML, event_host_id="host-test")
    second = parse_system_events(XML, event_host_id="host-test")
    assert [event.event_id for event in first] == [event.event_id for event in second]


def test_event_log_parser_rejects_oversized_and_malformed_xml():
    with pytest.raises(EventLogError, match="output limit"):
        parse_system_events("x" * 2_000_001)
    with pytest.raises(EventLogError, match="malformed"):
        parse_system_events("<Events>")


def test_event_log_provider_uses_fixed_system_allowlist():
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, XML, "")

    events = WindowsEventLogProvider(runner=runner).collect_recent()
    args = calls[0][0]
    assert args[:3] == ["wevtutil.exe", "qe", "System"]
    assert "/f:xml" in args
    assert "/c:100" in args
    assert "Security" not in " ".join(args)
    assert len(events) == 2


def test_event_log_provider_reports_command_failure():
    provider = WindowsEventLogProvider(
        runner=lambda args, **kwargs: subprocess.CompletedProcess(args, 1, "", "denied")
    )
    with pytest.raises(EventLogError):
        provider.collect_recent()


def test_event_log_provider_advances_record_cursor():
    responses = [XML, XML.replace(">77<", ">80<").replace(">78<", ">81<")]
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, responses.pop(0), "")

    provider = WindowsEventLogProvider(runner=runner)
    first = provider.collect_recent()
    provider.commit_cursor()
    second = provider.collect_recent()

    assert [event.data["record_id"] for event in first] == [77, 78]
    assert [event.data["record_id"] for event in second] == [80, 81]
    assert "EventRecordID > 79" in calls[1][3]
    assert "/rd:false" in calls[1]


def test_windows_provider_reuses_eventlog_cursor(monkeypatch):
    from aie.providers import eventlog
    from aie.providers.windows import WindowsProvider

    instances = []

    class FakeEventLogProvider:
        def __init__(self, last_record_id=None):
            self.calls = 0
            instances.append(self)

        def collect_recent(self):
            self.calls += 1
            return []

    monkeypatch.setattr(eventlog, "WindowsEventLogProvider", FakeEventLogProvider)
    provider = WindowsProvider.__new__(WindowsProvider)
    assert list(provider.collect_eventlog_events()) == []
    assert list(provider.collect_eventlog_events()) == []
    assert len(instances) == 1
    assert instances[0].calls == 2


def test_event_log_parser_accepts_unqualified_xml():
    unqualified = XML.replace(
        ' xmlns="http://schemas.microsoft.com/win/2004/08/events/event"', ""
    )
    events = parse_system_events(unqualified, event_host_id="host-test")
    assert len(events) == 2
    assert events[0].data["record_id"] == 77


def test_event_log_parser_accepts_only_allowlisted_kernel_general_ids():
    xml = """<Events>
    <Event><System><Provider Name="Microsoft-Windows-Kernel-General"/>
    <EventID>12</EventID><TimeCreated SystemTime="2026-10-14T10:00:00Z"/>
    <EventRecordID>101</EventRecordID></System></Event>
    <Event><System><Provider Name="Microsoft-Windows-Kernel-General"/>
    <EventID>13</EventID><TimeCreated SystemTime="2026-10-14T10:01:00Z"/>
    <EventRecordID>102</EventRecordID></System></Event>
    <Event><System><Provider Name="Microsoft-Windows-Kernel-General"/>
    <EventID>14</EventID><TimeCreated SystemTime="2026-10-14T10:02:00Z"/>
    <EventRecordID>103</EventRecordID></System></Event>
    </Events>"""
    events = parse_system_events(xml, event_host_id="host-test")
    assert [event.event_type for event in events] == [
        "windows.system.started", "windows.system.stopped"
    ]



def test_event_log_cursor_is_not_advanced_until_commit():
    provider = WindowsEventLogProvider(
        runner=lambda args, **kwargs: subprocess.CompletedProcess(args, 0, XML, "")
    )
    provider.collect_recent()
    assert provider._last_record_id is None
    with pytest.raises(RuntimeError, match="uncommitted"):
        provider.collect_recent()
    provider.commit_cursor()
    assert provider._last_record_id == 79


def test_event_log_cursor_can_resume_from_persisted_record_id():
    responses = [XML.replace(">77<", ">80<").replace(">78<", ">81<")]
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, responses.pop(0), "")

    provider = WindowsEventLogProvider(runner=runner, last_record_id=78)
    events = provider.collect_recent()
    assert [event.data["record_id"] for event in events] == [80, 81]
    assert "EventRecordID > 78" in calls[0][3]



def test_windows_provider_persists_cursor_after_event_batch(tmp_path, monkeypatch):
    from aie.providers import eventlog
    from aie.providers.windows import WindowsProvider
    from aie.store import EventStore

    created = []

    class FakeEventLogProvider:
        def __init__(self, last_record_id=None):
            self.last_record_id = last_record_id
            self.committed = False
            created.append(self)

        def collect_recent(self):
            return []

        def commit_cursor(self, save_checkpoint):
            save_checkpoint(456)
            self.committed = True
            return 456

        def discard_pending_cursor(self):
            pass

    monkeypatch.setattr(eventlog, "WindowsEventLogProvider", FakeEventLogProvider)
    store = EventStore(tmp_path / "observer.sqlite3")
    store.set_checkpoint("windows.eventlog.system.record_id", "123")

    provider = WindowsProvider.__new__(WindowsProvider)
    assert list(provider.collect_eventlog_events(store)) == []
    assert created[0].last_record_id == 123
    assert provider.commit_eventlog_cursor(store) == 456
    assert store.get_checkpoint("windows.eventlog.system.record_id") == "456"
