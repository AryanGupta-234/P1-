"""Convert tracerpt XML for Kernel-Process ETW events into normalized evidence."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Iterator
from uuid import NAMESPACE_URL, uuid5

from aie.contracts import AIEEvent, EntityRef
from aie.store import EventStore
from aie.providers.etw_process import KERNEL_PROCESS_GUID
from aie.providers.windows import host_id

_ETW_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"
_PROCESS_EVENTS = {1: "process.started_etw", 2: "process.stopped_etw"}


@dataclass(frozen=True)
class ETWTraceStats:
    events_logged: int | None = None
    events_lost: int | None = None
    buffers_written: int | None = None
    log_buffers_lost: int | None = None
    realtime_buffers_lost: int | None = None


def read_trace_stats(xml_path: Path) -> ETWTraceStats:
    """Read optional tracerpt trace-header counters without loading the XML tree."""
    names = {
        "eventslogged": "events_logged",
        "eventslost": "events_lost",
        "bufferswritten": "buffers_written",
        "logbufferslost": "log_buffers_lost",
        "realtimebufferslost": "realtime_buffers_lost",
    }
    values: dict[str, int] = {}
    in_header = False
    for action, element in ET.iterparse(xml_path, events=("start", "end")):
        local_name = element.tag.rsplit("}", 1)[-1].casefold()
        if action == "start" and local_name == "header":
            in_header = True
        elif action == "end" and in_header and local_name in names and element.text:
            try:
                values[names[local_name]] = int(element.text.strip(), 10)
            except ValueError:
                pass
        elif action == "end" and local_name == "header":
            in_header = False
            element.clear()
    return ETWTraceStats(**values)


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return element.find(f"{_ETW_NS}{name}")


def _data_fields(event_data: ET.Element | None) -> dict[str, str]:
    fields: dict[str, str] = {}
    if event_data is None:
        return fields
    for item in event_data.findall(f"{_ETW_NS}Data"):
        name = item.attrib.get("Name", "").casefold().replace("_", "")
        if name and item.text:
            fields[name] = item.text.strip()
    return fields


def _integer(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value, 10)
    except ValueError:
        try:
            return int(value, 0)
        except ValueError:
            return None


def iter_process_events(xml_path: Path, *, event_host_id: str | None = None) -> Iterator[AIEEvent]:
    """Yield only Kernel-Process start/stop records; command lines are never retained."""
    identity = event_host_id or host_id()
    root: ET.Element | None = None
    context = ET.iterparse(xml_path, events=("start", "end"))
    for action, element in context:
        if root is None and action == "start":
            root = element
        if action != "end" or element.tag != f"{_ETW_NS}Event":
            continue

        def discard_event() -> None:
            element.clear()
            if root is not None:
                root.clear()

        system = _child(element, "System")
        if system is None:
            discard_event()
            continue
        provider = _child(system, "Provider")
        event_id_element = _child(system, "EventID")
        time_created = _child(system, "TimeCreated")
        if provider is None or event_id_element is None or time_created is None:
            discard_event()
            continue
        provider_guid = provider.attrib.get("Guid", "").casefold()
        provider_name = provider.attrib.get("Name", "").casefold()
        try:
            event_id = int(event_id_element.text or "")
        except ValueError:
            discard_event()
            continue
        event_type = _PROCESS_EVENTS.get(event_id)
        known_provider = (
            provider_guid == KERNEL_PROCESS_GUID.casefold()
            or provider_name == "microsoft-windows-kernel-process"
        )
        if not known_provider or event_type is None:
            discard_event()
            continue
        timestamp_text = time_created.attrib.get("SystemTime")
        try:
            timestamp = datetime.fromisoformat(
                (timestamp_text or "").replace("Z", "+00:00")
            )
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("ETW timestamp must be timezone-aware")
        except ValueError:
            discard_event()
            continue
        fields = _data_fields(_child(element, "EventData"))
        pid = _integer(fields.get("processid"))
        if pid is None or pid < 0:
            discard_event()
            continue
        parent_pid = _integer(fields.get("parentprocessid"))
        raw_image = fields.get("imagename") or fields.get("imagefilename")
        image_name = PureWindowsPath(raw_image).name if raw_image else f"pid:{pid}"
        data: dict[str, int | str] = {"pid": pid}
        if parent_pid is not None and parent_pid >= 0:
            data["parent_pid"] = parent_pid
        if image_name and not image_name.startswith("pid:"):
            data["image_name"] = image_name
        event_id = str(uuid5(
            NAMESPACE_URL,
            f"{identity}|{timestamp.isoformat()}|{event_type}|{pid}|{image_name}",
        ))
        yield AIEEvent(
            event_id=event_id,
            timestamp=timestamp,
            host_id=identity,
            source="windows.etw.kernel_process",
            event_type=event_type,
            entity=EntityRef(type="process", name=image_name, stable_id=str(pid)),
            data=data,
            sensitivity="internal",
            confidence=1.0,
            evidence_kind="observed",
        )
        discard_event()


def decode_trace_xml(
    xml_path: Path,
    jsonl_path: Path,
    *,
    event_host_id: str | None = None,
    store: EventStore | None = None,
    batch_size: int = 250,
) -> int:
    """Stream normalized events to JSONL and optionally batch-import into SQLite."""
    if jsonl_path.resolve() == xml_path.resolve():
        raise ValueError("JSONL output must not overwrite tracerpt XML input")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    batch: list[AIEEvent] = []
    try:
        with jsonl_path.open("x", encoding="utf-8") as output:
            for event in iter_process_events(xml_path, event_host_id=event_host_id):
                output.write(event.model_dump_json() + "\n")
                count += 1
                if store is not None:
                    batch.append(event)
                    if len(batch) >= batch_size:
                        store.append_many(batch)
                        batch.clear()
            if store is not None and batch:
                store.append_many(batch)
    except Exception:
        jsonl_path.unlink(missing_ok=True)
        raise
    return count
