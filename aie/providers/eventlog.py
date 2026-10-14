"""Strictly allowlisted, read-only Windows System event-log sampling."""
from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id

_EVENT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"
_ALLOWED = {
    ("Service Control Manager", 7036): "windows.service.state_changed",
    ("Microsoft-Windows-Kernel-Power", 42): "windows.power.sleep",
    ("Microsoft-Windows-Kernel-General", 12): "windows.system.started",
    ("Microsoft-Windows-Kernel-General", 13): "windows.system.stopped",
}
_MAX_EVENTS = 100
_MAX_OUTPUT_CHARS = 2_000_000


class EventLogError(RuntimeError):
    """Raised when the allowlisted Windows event-log query fails."""


def _events_root(output: str) -> ET.Element:
    text = output.lstrip("\\ufeff \\r\\n\\t")
    if text.startswith("<?xml"):
        _, _, text = text.partition("?>")
        text = text.lstrip()
    if not text:
        return ET.Element("Events")
    if text.startswith("<Events"):
        return ET.fromstring(text)
    return ET.fromstring(
        f'<Events xmlns="http://schemas.microsoft.com/win/2004/08/events/event">'
        f"{text}</Events>"
    )


def parse_system_events(output: str, *, event_host_id: str | None = None) -> list[AIEEvent]:
    """Parse only allowlisted provider/ID pairs; ignore rendered messages and other data."""
    if len(output) > _MAX_OUTPUT_CHARS:
        raise EventLogError("event-log response exceeded the configured output limit")
    identity = event_host_id or host_id()
    try:
        root = _events_root(output)
    except ET.ParseError as exc:
        raise EventLogError("event-log XML was malformed") from exc

    events: list[AIEEvent] = []
    for element in root.findall(f"{_EVENT_NS}Event"):
        system = element.find(f"{_EVENT_NS}System")
        if system is None:
            continue
        provider = system.find(f"{_EVENT_NS}Provider")
        event_id_element = system.find(f"{_EVENT_NS}EventID")
        created = system.find(f"{_EVENT_NS}TimeCreated")
        record = system.find(f"{_EVENT_NS}EventRecordID")
        if provider is None or event_id_element is None or created is None or record is None:
            continue
        provider_name = provider.attrib.get("Name", "")
        try:
            event_id = int(event_id_element.text or "")
            record_id = int(record.text or "")
            timestamp = datetime.fromisoformat(
                created.attrib.get("SystemTime", "").replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            continue
        event_type = _ALLOWED.get((provider_name, event_id))
        if event_type is None or record_id < 0:
            continue
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            continue

        data: dict[str, str | int] = {"record_id": record_id, "event_id": event_id}
        entity_type = "system"
        entity_name = provider_name
        if event_id == 7036:
            event_data = element.find(f"{_EVENT_NS}EventData")
            fields = {
                item.attrib.get("Name", "").casefold(): (item.text or "").strip()
                for item in (event_data.findall(f"{_EVENT_NS}Data") if event_data is not None else [])
            }
            service = fields.get("param1", "")[:128]
            state = fields.get("param2", "")[:32]
            if not service or not state:
                continue
            entity_type = "service"
            entity_name = service
            data.update({"service": service, "state": state})

        deterministic_id = str(uuid5(
            NAMESPACE_URL,
            f"{identity}|System|{record_id}|{provider_name}|{event_id}",
        ))
        events.append(AIEEvent(
            event_id=deterministic_id,
            timestamp=timestamp,
            host_id=identity,
            source="windows.eventlog.system",
            event_type=event_type,
            entity=EntityRef(type=entity_type, name=entity_name, stable_id=str(record_id)),
            data=data,
            sensitivity="internal",
            confidence=1.0,
            evidence_kind="observed",
        ))
    return events


class WindowsEventLogProvider:
    """Queries a fixed System-log allowlist and advances by event record ID."""

    def __init__(self, *, timeout: float = 10.0, runner=subprocess.run) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout
        self._runner = runner
        self._last_record_id: int | None = None

    @staticmethod
    def _xpath(after_record_id: int | None) -> str:
        allowlist = (
            "(Provider[@Name='Service Control Manager'] and EventID=7036) or "
            "(Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=42) or "
            "(Provider[@Name='Microsoft-Windows-Kernel-General'] and "
            "(EventID=12 or EventID=13))"
        )
        if after_record_id is not None:
            allowlist = f"({allowlist}) and EventRecordID > {after_record_id}"
        return f"*[System[{allowlist}]]"

    def _query(self, after_record_id: int | None, *, newest_first: bool) -> list[AIEEvent]:
        direction = "true" if newest_first else "false"
        try:
            result = self._runner(
                ["wevtutil.exe", "qe", "System",
                 f"/q:{self._xpath(after_record_id)}",
                 "/f:xml", f"/rd:{direction}", f"/c:{_MAX_EVENTS}"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=self.timeout, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EventLogError(
                f"event-log query failed: {type(exc).__name__}"
            ) from exc
        if result.returncode != 0:
            raise EventLogError(f"wevtutil returned exit code {result.returncode}")
        events = parse_system_events(result.stdout)
        return sorted(events, key=lambda event: int(event.data["record_id"]))

    def collect_recent(self) -> list[AIEEvent]:
        """Seed from the newest 100 events, then page forward from the last record."""
        if self._last_record_id is None:
            initial = self._query(None, newest_first=True)
            if initial:
                self._last_record_id = max(int(event.data["record_id"]) for event in initial)
            return initial

        collected: list[AIEEvent] = []
        for _ in range(5):
            page = self._query(self._last_record_id, newest_first=False)
            page = [
                event for event in page
                if int(event.data["record_id"]) > self._last_record_id
            ]
            if not page:
                break
            collected.extend(page)
            self._last_record_id = max(int(event.data["record_id"]) for event in page)
            if len(page) < _MAX_EVENTS:
                break

        if not collected:
            latest = self._query(None, newest_first=True)
            latest_id = max(
                (int(event.data["record_id"]) for event in latest),
                default=self._last_record_id,
            )
            if latest_id < self._last_record_id:
                # The System log was cleared/recreated; establish a fresh cursor.
                self._last_record_id = latest_id
                return latest
        return collected
