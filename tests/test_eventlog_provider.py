from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aie.providers.eventlog import WindowsEventLogProvider


class FakeEventLogApi:
    def __init__(self):
        self.records = {
            "Application": [],
            "System": [],
        }
        self.closed = []

    def open(self, channel):
        return channel

    def close(self, handle):
        self.closed.append(handle)

    def oldest_record(self, handle):
        values = self.records[handle]
        return values[0].RecordNumber if values else 0

    def record_count(self, handle):
        return len(self.records[handle])

    def read_from(self, handle, start_record, max_records):
        values = [
            record for record in self.records[handle]
            if record.RecordNumber >= start_record
        ]
        return values[:max_records]


def record(number, event_id=1001):
    return SimpleNamespace(
        RecordNumber=number,
        EventID=event_id,
        EventType=4,
        EventCategory=0,
        SourceName="ExampleProvider",
        ComputerName="AIE-DESKTOP",
        TimeGenerated=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
        StringInserts=["SECRET MESSAGE TEXT MUST NOT BE READ"],
    )


def test_eventlog_skips_historical_backlog_on_first_poll():
    api = FakeEventLogApi()
    api.records["Application"] = [record(20), record(21)]
    provider = WindowsEventLogProvider(channels=["Application"], api=api)

    assert provider.collect_snapshot() == []
    assert provider._last_record["Application"] == 21


def test_eventlog_emits_only_new_metadata_records():
    api = FakeEventLogApi()
    api.records["System"] = [record(100)]
    provider = WindowsEventLogProvider(channels=["System"], api=api)
    assert provider.collect_snapshot() == []

    api.records["System"].extend([record(101, 7000), record(102, 7001)])
    events = provider.collect_snapshot()

    assert [event.data["record_number"] for event in events] == [101, 102]
    assert [event.data["event_id"] for event in events] == [7000, 7001]
    assert all(event.event_type == "windows.eventlog.record" for event in events)
    assert all(event.data["message_collected"] is False for event in events)
    assert all(event.data["xml_collected"] is False for event in events)
    assert all("SECRET" not in str(event.data) for event in events)


def test_eventlog_batch_limit_does_not_skip_backlog():
    api = FakeEventLogApi()
    api.records["Application"] = [record(1)]
    provider = WindowsEventLogProvider(
        channels=["Application"],
        api=api,
        max_records_per_channel=1,
    )
    provider.collect_snapshot()

    api.records["Application"].extend([record(2), record(3), record(4)])
    first = provider.collect_snapshot()
    second = provider.collect_snapshot()
    third = provider.collect_snapshot()

    assert [e.data["record_number"] for e in first + second + third] == [2, 3, 4]


def test_eventlog_channels_are_allowlisted():
    api = FakeEventLogApi()
    with pytest.raises(ValueError, match="allowlisted"):
        WindowsEventLogProvider(channels=["Security"], api=api)


def test_eventlog_record_limit_is_bounded():
    with pytest.raises(ValueError):
        WindowsEventLogProvider(api=FakeEventLogApi(), max_records_per_channel=1000)


def test_eventlog_handles_are_closed():
    api = FakeEventLogApi()
    api.records["Application"] = [record(1)]
    api.records["System"] = [record(2)]
    provider = WindowsEventLogProvider(api=api)
    provider.collect_snapshot()

    assert api.closed == ["Application", "System"]


def test_eventlog_clear_or_record_number_reset_is_detected():
    api = FakeEventLogApi()
    api.records["System"] = [record(100), record(101)]
    provider = WindowsEventLogProvider(channels=["System"], api=api)
    assert provider.collect_snapshot() == []

    # Simulate a cleared classic event log and a new record-number sequence.
    api.records["System"] = [record(1, 6000), record(2, 6001)]
    emitted = provider.collect_snapshot()

    assert [event.data["record_number"] for event in emitted] == [1, 2]


class FailingEventLogApi(FakeEventLogApi):
    def open(self, channel):
        raise PermissionError("private details should not be copied")


def test_eventlog_access_error_is_reported_once_without_error_message():
    api = FailingEventLogApi()
    provider = WindowsEventLogProvider(channels=["System"], api=api)

    first = provider.collect_snapshot()
    second = provider.collect_snapshot()

    assert len(first) == 1
    assert first[0].event_type == "windows.eventlog.provider_error"
    assert first[0].data["error_type"] == "PermissionError"
    assert "message" not in first[0].data
    assert second == []
