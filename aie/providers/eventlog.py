"""Opt-in metadata-only reader for allowlisted Windows classic event logs.

The provider reads only Application/System record metadata. It never reads Event
Description/Message text, XML payloads, Security logs, or arbitrary log channels.
"""
from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Protocol

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id

_ALLOWED_LOGS = frozenset({"Application", "System"})


class EventLogApi(Protocol):
    def open(self, channel: str) -> Any: ...
    def close(self, handle: Any) -> None: ...
    def oldest_record(self, handle: Any) -> int: ...
    def record_count(self, handle: Any) -> int: ...
    def read_from(self, handle: Any, start_record: int, max_records: int) -> list[Any]: ...


class _Win32EventLogApi:
    """Adapter over pywin32's documented classic Event Log functions."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows Event Log observation requires native Windows.")
        try:
            import win32evtlog
        except ImportError as exc:
            raise RuntimeError(
                "Install optional Windows dependencies: python -m pip install -e '.[windows]'"
            ) from exc
        self._api = win32evtlog

    def open(self, channel: str) -> Any:
        return self._api.OpenEventLog(None, channel)

    def close(self, handle: Any) -> None:
        self._api.CloseEventLog(handle)

    def oldest_record(self, handle: Any) -> int:
        return int(self._api.GetOldestEventLogRecord(handle))

    def record_count(self, handle: Any) -> int:
        return int(self._api.GetNumberOfEventLogRecords(handle))

    def read_from(self, handle: Any, start_record: int, max_records: int) -> list[Any]:
        flags = self._api.EVENTLOG_SEEK_READ | self._api.EVENTLOG_FORWARDS_READ
        records = self._api.ReadEventLog(handle, flags, start_record)
        return list(records or [])[:max_records]


class WindowsEventLogProvider:
    """Poll new metadata records from Application/System without reading message text."""

    name = "windows.eventlog"

    def __init__(
        self,
        *,
        channels: Iterable[str] = ("Application", "System"),
        api: EventLogApi | None = None,
        max_records_per_channel: int = 50,
    ) -> None:
        if not 1 <= max_records_per_channel <= 200:
            raise ValueError("max_records_per_channel must be between 1 and 200")
        selected = tuple(dict.fromkeys(channels))
        if not selected:
            raise ValueError("At least one Windows event log channel must be selected.")
        invalid = set(selected) - _ALLOWED_LOGS
        if invalid:
            raise ValueError(
                "Only the allowlisted Application and System channels are supported."
            )
        self.channels = selected
        self.api = api or _Win32EventLogApi()
        self.max_records_per_channel = max_records_per_channel
        self._last_record: dict[str, int] = {}
        self._error_channels: set[str] = set()

    def _append_recovery_event(self, events: list[AIEEvent], channel: str) -> None:
        """Emit a recovery signal only after the channel can be queried again."""
        if channel not in self._error_channels:
            return
        events.append(AIEEvent(
            timestamp=datetime.now(timezone.utc),
            host_id=host_id(),
            source=self.name,
            event_type="windows.eventlog.provider_recovered",
            entity=EntityRef(type="windows_eventlog_channel", name=channel),
            data={"channel": channel, "recovered": True},
            sensitivity="internal",
            confidence=1.0,
            evidence_kind="observed",
        ))
        self._error_channels.discard(channel)

    def collect_snapshot(self) -> list[AIEEvent]:
        events: list[AIEEvent] = []
        for channel in self.channels:
            handle = None
            try:
                handle = self.api.open(channel)
                oldest = self.api.oldest_record(handle)
                count = self.api.record_count(handle)
                if count <= 0:
                    self._append_recovery_event(events, channel)
                    continue
                newest = oldest + count - 1
                previous = self._last_record.get(channel)

                # Establish a baseline on startup; do not replay historical logs.
                if previous is None:
                    self._last_record[channel] = newest
                    self._append_recovery_event(events, channel)
                    continue

                # A cleared log has an unknowable loss count; rollover has an exact gap.
                if newest < previous:
                    events.append(AIEEvent(
                        timestamp=datetime.now(timezone.utc),
                        host_id=host_id(),
                        source=self.name,
                        event_type="windows.eventlog.sequence_reset",
                        entity=EntityRef(
                            type="windows_eventlog_channel",
                            name=channel,
                        ),
                        data={
                            "channel": channel,
                            "loss_count_known": False,
                            "reason_code": "record_sequence_reset",
                        },
                        sensitivity="internal",
                        confidence=1.0,
                        evidence_kind="observed",
                    ))
                    previous = oldest - 1
                elif previous < oldest - 1:
                    dropped_records = oldest - previous - 1
                    events.append(AIEEvent(
                        timestamp=datetime.now(timezone.utc),
                        host_id=host_id(),
                        source=self.name,
                        event_type="windows.eventlog.records_lost",
                        entity=EntityRef(
                            type="windows_eventlog_channel",
                            name=channel,
                        ),
                        data={
                            "channel": channel,
                            "dropped_records": dropped_records,
                            "loss_count_known": True,
                            "reason_code": "retention_rollover",
                        },
                        sensitivity="internal",
                        confidence=1.0,
                        evidence_kind="observed",
                    ))
                    previous = oldest - 1

                start_record = max(oldest, previous + 1)
                if start_record > newest:
                    self._last_record[channel] = newest
                    self._append_recovery_event(events, channel)
                    continue

                records = self.api.read_from(
                    handle,
                    start_record,
                    self.max_records_per_channel,
                )
                if not records:
                    self._append_recovery_event(events, channel)
                    continue

                for record in records:
                    record_number = int(getattr(record, "RecordNumber", 0))
                    if record_number < start_record:
                        continue
                    event_id = int(getattr(record, "EventID", 0)) & 0xFFFF
                    provider_name = str(getattr(record, "SourceName", "unknown"))[:128]
                    computer = str(getattr(record, "ComputerName", ""))[:128]
                    event_type = int(getattr(record, "EventType", 0))
                    category = int(getattr(record, "EventCategory", 0))
                    generated = getattr(record, "TimeGenerated", None)
                    generated_at = (
                        generated.isoformat()
                        if hasattr(generated, "isoformat")
                        else str(generated) if generated is not None else None
                    )
                    stable_id = f"{channel}:{record_number}"

                    events.append(AIEEvent(
                        timestamp=datetime.now(timezone.utc),
                        host_id=host_id(),
                        source=self.name,
                        event_type="windows.eventlog.record",
                        entity=EntityRef(
                            type="windows_event",
                            name=provider_name,
                            stable_id=stable_id,
                        ),
                        data={
                            "channel": channel,
                            "record_number": record_number,
                            "event_id": event_id,
                            "event_type_code": event_type,
                            "category": category,
                            "computer": computer,
                            "generated_at": generated_at,
                            "message_collected": False,
                            "xml_collected": False,
                        },
                        sensitivity="internal",
                        confidence=1.0,
                        evidence_kind="observed",
                    ))
                    self._last_record[channel] = max(
                        self._last_record.get(channel, 0),
                        record_number,
                    )
                self._append_recovery_event(events, channel)
            except Exception as exc:
                # Access denied, cleared logs or unavailable channels are non-fatal.
                # Re-emit a compact error signal each poll while the channel stays
                # unavailable, so aggregate health cannot mistake another channel's
                # successful records for recovery.
                events.append(AIEEvent(
                    timestamp=datetime.now(timezone.utc),
                    host_id=host_id(),
                    source=self.name,
                    event_type="windows.eventlog.provider_error",
                    entity=EntityRef(type="windows_eventlog_channel", name=channel),
                    data={
                        "channel": channel,
                        "error_type": type(exc).__name__,
                        "message_collected": False,
                    },
                    sensitivity="internal",
                    confidence=1.0,
                    evidence_kind="observed",
                ))
                self._error_channels.add(channel)
                continue
            finally:
                if handle is not None:
                    try:
                        self.api.close(handle)
                    except Exception:
                        pass
        return events
