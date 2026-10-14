"""Strictly allowlisted, read-only Windows System event-log sampling."""
from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id

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
    text = output.lstrip("\ufeff \r\n\t")
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


def _find_child(element: ET.Element, name: str) -> ET.Element | None:
    return next(
        (child for child in element if child.tag.rsplit("}", 1)[-1] == name),
        None,
    )


def _find_children(element: ET.Element, name: str) -> list[ET.Element]:
    return [
        child for child in element
        if child.tag.rsplit("}", 1)[-1] == name
    ]


def _record_metadata(output: str) -> tuple[int, int | None]:
    root = _events_root(output)
    elements = _find_children(root, "Event")
    record_ids: list[int] = []
    for element in elements:
        system = _find_child(element, "System")
        record = _find_child(system, "EventRecordID") if system is not None else None
        try:
            if record is not None and record.text:
                record_ids.append(int(record.text, 10))
        except ValueError:
            continue
    return len(elements), max(record_ids, default=None)


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
    for element in _find_children(root, "Event"):
        system = _find_child(element, "System")
        if system is None:
            continue
        provider = _find_child(system, "Provider")
        event_id_element = _find_child(system, "EventID")
        created = _find_child(system, "TimeCreated")
        record = _find_child(system, "EventRecordID")
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
            event_data = _find_child(element, "EventData")
            fields = {
                item.attrib.get("Name", "").casefold(): (item.text or "").strip()
                for item in (_find_children(event_data, "Data") if event_data is not None else [])
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

    def __init__(
        self, *, timeout: float = 10.0, runner=subprocess.run,
        last_record_id: int | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if last_record_id is not None and last_record_id < 0:
            raise ValueError("last_record_id must be non-negative")
        self.timeout = timeout
        self._runner = runner
        self._last_record_id = last_record_id
        self._pending_record_id: int | None = None

    def commit_cursor(self, save_checkpoint=None) -> int | None:
        """Commit the sampled cursor after its events have been durably persisted."""
        if self._pending_record_id is None:
            return self._last_record_id
        candidate = self._pending_record_id
        if save_checkpoint is not None:
            save_checkpoint(candidate)
        self._last_record_id = candidate
        self._pending_record_id = None
        return self._last_record_id

    def discard_pending_cursor(self) -> None:
        """Allow the same page to be sampled again after a persistence failure."""
        self._pending_record_id = None

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

    def _query(
        self, after_record_id: int | None, *, newest_first: bool
    ) -> tuple[list[AIEEvent], int | None, int]:
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
        raw_count, latest_record_id = _record_metadata(result.stdout)
        events.sort(key=lambda event: int(event.data["record_id"]))
        return events, latest_record_id, raw_count

    def collect_recent(self) -> list[AIEEvent]:
        """Read a bounded page without advancing the durable cursor prematurely."""
        if self._pending_record_id is not None:
            raise RuntimeError("event-log cursor has an uncommitted page")

        cursor = self._last_record_id
        if cursor is None:
            initial, latest_id, _ = self._query(None, newest_first=True)
            self._pending_record_id = latest_id
            return initial

        collected: list[AIEEvent] = []
        candidate = cursor
        for _ in range(5):
            page, latest_id, raw_count = self._query(
                candidate, newest_first=False
            )
            if latest_id is None or latest_id <= candidate:
                break
            collected.extend(
                event for event in page
                if int(event.data["record_id"]) > candidate
            )
            candidate = latest_id
            if raw_count < _MAX_EVENTS:
                break

        if candidate == cursor and not collected:
            latest, latest_id, _ = self._query(None, newest_first=True)
            if latest_id is not None and latest_id < cursor:
                # The System log was cleared/recreated; establish a fresh cursor.
                candidate = latest_id
                collected = latest

        if candidate != cursor:
            self._pending_record_id = candidate
        return collected
