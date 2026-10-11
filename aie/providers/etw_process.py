"""Bounded, owned ETW process-lifecycle capture for Windows.

The first implementation deliberately uses Windows' built-in logman/tracerpt
frontends rather than defining unsafe ctypes layouts for ETW structures. It
creates a uniquely named AIE session, enables process events only, records to
an 8 MiB circular ETL, stops only that session, and then parses an allowlisted
subset of process metadata.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id


KERNEL_PROCESS_GUID = "22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716"
KERNEL_PROCESS_PROVIDER = "Microsoft-Windows-Kernel-Process"
PROCESS_KEYWORD = 0x10
INFORMATIONAL_LEVEL = 4
MAX_TRACE_MIB = 8
MAX_DECODED_XML_BYTES = 32 * 1024 * 1024
MAX_PROCESS_EVENTS = 20_000
_PROCESS_NAME = re.compile(r"^[\w .()\-]{1,260}$", re.UNICODE)
_LOSS_PATTERNS = {
    "events_lost": re.compile(r"(?:events\s+lost|eventslost)\s*[:=]\s*(\d+)", re.I),
    "buffers_lost": re.compile(r"(?:buffers\s+lost|logbufferslost|realtimebufferslost)\s*[:=]\s*(\d+)", re.I),
}


class ETWProcessCaptureError(RuntimeError):
    """Sanitized ETW capture failure; never includes command output or user data."""

    def __init__(
        self,
        reason_code: str,
        *,
        return_code: int | None = None,
        session_name: str | None = None,
        recovery_command: str | None = None,
        workspace: str | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.return_code = return_code
        self.session_name = session_name
        self.recovery_command = recovery_command
        self.workspace = workspace
        detail = reason_code
        if return_code is not None:
            detail += f" (exit code {return_code})"
        if recovery_command:
            detail += f"; stop the owned session with: {recovery_command}"
        if workspace:
            detail += f"; ETL workspace retained at: {workspace}"
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class ETWProcessCapture:
    session_name: str
    events: tuple[AIEEvent, ...]
    duration_seconds: float
    etl_size_bytes: int
    events_lost: int | None
    buffers_lost: int | None
    truncated: bool

    def coverage_event(self, *, machine_id: str) -> AIEEvent:
        """Describe measured coverage; unknown loss counters remain None."""
        return AIEEvent(
            timestamp=datetime.now(timezone.utc),
            host_id=machine_id,
            source="aie.etw.process",
            event_type="windows.etw.coverage",
            entity=EntityRef(type="etw_session", name="AIE process lifecycle capture"),
            data={
                "provider_guid": KERNEL_PROCESS_GUID,
                "session_name": self.session_name,
                "duration_seconds": round(self.duration_seconds, 3),
                "process_events": len(self.events),
                "events_lost": self.events_lost,
                "buffers_lost": self.buffers_lost,
                "loss_metrics_available": (
                    self.events_lost is not None or self.buffers_lost is not None
                ),
                "etl_size_bytes": self.etl_size_bytes,
                "truncated": self.truncated,
                "buffer_size_kib": 16,
                "minimum_buffers": 2,
                "maximum_buffers": 8,
                "maximum_trace_mib": MAX_TRACE_MIB,
            },
            sensitivity="internal",
            evidence_kind="observed",
        )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value.strip(), 0)
    except (TypeError, ValueError):
        try:
            parsed = int(value.strip(), 10)
        except (TypeError, ValueError):
            return None
    return parsed if 0 <= parsed <= 0xFFFFFFFF else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_process_name(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().strip("\x00")
    if not raw or any(ord(char) < 32 for char in raw):
        return None
    name = PureWindowsPath(raw.replace("/", "\\")).name
    return name if _PROCESS_NAME.fullmatch(name) else None


def _first_descendant(element: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in element.iter() if _local_name(item.tag) == name), None)


def _process_event_from_xml(
    element: ET.Element,
    *,
    machine_id: str,
) -> AIEEvent | None:
    system = _first_descendant(element, "System")
    if system is None:
        return None
    provider = _first_descendant(system, "Provider")
    if provider is None:
        return None
    guid = (provider.attrib.get("Guid") or "").strip("{}").casefold()
    name = (provider.attrib.get("Name") or "").casefold()
    if guid != KERNEL_PROCESS_GUID and name != KERNEL_PROCESS_PROVIDER.casefold():
        return None

    event_id_element = _first_descendant(system, "EventID")
    version_element = _first_descendant(system, "Version")
    time_element = _first_descendant(system, "TimeCreated")
    event_id = _parse_int(event_id_element.text if event_id_element is not None else None)
    version = _parse_int(version_element.text if version_element is not None else None) or 0
    timestamp = _parse_timestamp(
        time_element.attrib.get("SystemTime") if time_element is not None else None
    )
    if event_id not in (1, 2) or timestamp is None:
        return None

    event_data = _first_descendant(element, "EventData")
    if event_data is None:
        return None
    values = {
        (item.attrib.get("Name") or "").casefold(): (item.text or "").strip()
        for item in event_data.iter()
        if _local_name(item.tag) == "Data"
    }
    pid = _parse_int(values.get("processid") or values.get("process_id"))
    if pid is None or pid == 0:
        return None
    parent_pid = _parse_int(values.get("parentprocessid") or values.get("parent_process_id"))
    process_name = _safe_process_name(values.get("imagename") or values.get("image_name"))
    event_type = "windows.process.started" if event_id == 1 else "windows.process.stopped"
    payload: dict[str, object] = {
        "pid": pid,
        "process_name": process_name,
        "provider_guid": KERNEL_PROCESS_GUID,
        "event_id": event_id,
        "event_version": version,
    }
    if event_id == 1 and parent_pid is not None:
        payload["parent_pid"] = parent_pid

    return AIEEvent(
        timestamp=timestamp,
        host_id=machine_id,
        source="aie.etw.process",
        event_type=event_type,
        entity=EntityRef(
            type="process",
            name=process_name or f"process-{pid}",
            stable_id=f"{pid}:{timestamp.isoformat()}",
        ),
        data=payload,
        sensitivity="internal",
        evidence_kind="observed",
    )


def parse_tracerpt_xml(
    payload: str,
    *,
    machine_id: str,
    max_events: int = MAX_PROCESS_EVENTS,
) -> tuple[tuple[AIEEvent, ...], bool]:
    """Parse only Kernel-Process start/stop metadata; reject all other providers."""
    if not 1 <= max_events <= MAX_PROCESS_EVENTS:
        raise ValueError(f"max_events must be between 1 and {MAX_PROCESS_EVENTS}")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("tracerpt returned invalid XML") from exc

    events: list[AIEEvent] = []
    truncated = False
    for element in root.iter():
        if _local_name(element.tag) != "Event":
            continue
        event = _process_event_from_xml(element, machine_id=machine_id)
        if event is None:
            continue
        if len(events) >= max_events:
            truncated = True
            break
        events.append(event)
    events.sort(key=lambda item: item.timestamp)
    return tuple(events), truncated


def parse_tracerpt_loss_summary(payload: str) -> tuple[int | None, int | None]:
    """Parse counters only when tracerpt explicitly reports them."""
    output: list[int | None] = []
    for key in ("events_lost", "buffers_lost"):
        match = _LOSS_PATTERNS[key].search(payload)
        output.append(int(match.group(1)) if match else None)
    return output[0], output[1]


class WindowsETWProcessProvider:
    """Capture process start/stop events in a short-lived AIE-owned ETW session."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.perf_counter,
        is_windows: bool | None = None,
        temp_root: Path | None = None,
        machine_id: str | None = None,
    ) -> None:
        self._runner = runner
        self._sleep = sleep
        self._monotonic = monotonic
        self._is_windows = os.name == "nt" if is_windows is None else is_windows
        self._temp_root = temp_root
        self._machine_id = machine_id

    def _run(self, command: list[str], *, timeout: float) -> subprocess.CompletedProcess:
        try:
            return self._runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise ETWProcessCaptureError("command_timeout") from exc
        except OSError as exc:
            raise ETWProcessCaptureError(type(exc).__name__) from exc

    def _stop_owned_session(self, session_name: str) -> bool:
        try:
            result = self._run(
                ["logman.exe", "stop", session_name, "-ets"],
                timeout=15.0,
            )
        except ETWProcessCaptureError:
            return False
        return result.returncode == 0

    def collect(self, duration_seconds: int = 15) -> ETWProcessCapture:
        if not self._is_windows:
            raise ETWProcessCaptureError("native_windows_required")
        if not 1 <= duration_seconds <= 1800:
            raise ValueError("duration_seconds must be between 1 and 1800")

        machine_id = self._machine_id or host_id()
        session_name = f"AIE-Proc-{uuid4().hex[:12]}"
        workspace = Path(tempfile.mkdtemp(prefix="aie-etw-", dir=self._temp_root))
        etl_path = workspace / "process.etl"
        xml_path = workspace / "process.xml"
        summary_path = workspace / "summary.txt"
        started = False
        stopped = False
        started_at = self._monotonic()
        capture_error: ETWProcessCaptureError | None = None

        try:
            start_command = [
                "logman.exe", "create", "trace", session_name,
                "-p", f"{{{KERNEL_PROCESS_GUID}}}", hex(PROCESS_KEYWORD),
                str(INFORMATIONAL_LEVEL),
                "-o", str(etl_path), "-f", "bincirc", "-max", str(MAX_TRACE_MIB),
                "-bs", "16", "-nb", "2", "8", "-ft", "5", "-ets",
            ]
            result = self._run(start_command, timeout=20.0)
            if result.returncode != 0:
                raise ETWProcessCaptureError(
                    "session_start_failed", return_code=result.returncode,
                    session_name=session_name,
                )
            started = True
            started_at = self._monotonic()
            self._sleep(float(duration_seconds))

            if not self._stop_owned_session(session_name):
                if not self._stop_owned_session(session_name):
                    capture_error = ETWProcessCaptureError(
                        "session_stop_failed",
                        session_name=session_name,
                        recovery_command=f"logman stop {session_name} -ets",
                        workspace=str(workspace),
                    )
                    raise capture_error
            stopped = True

            if not etl_path.is_file():
                raise ETWProcessCaptureError("etl_file_missing", session_name=session_name)
            etl_size = etl_path.stat().st_size
            if etl_size <= 0:
                raise ETWProcessCaptureError("etl_file_empty", session_name=session_name)

            decode = self._run(
                [
                    "tracerpt.exe", str(etl_path), "-o", str(xml_path),
                    "-of", "XML", "-summary", str(summary_path), "-y",
                ],
                timeout=90.0,
            )
            if decode.returncode != 0:
                raise ETWProcessCaptureError(
                    "trace_decode_failed", return_code=decode.returncode,
                    session_name=session_name,
                )
            if not xml_path.is_file():
                raise ETWProcessCaptureError("decoded_xml_missing", session_name=session_name)
            if xml_path.stat().st_size > MAX_DECODED_XML_BYTES:
                raise ETWProcessCaptureError(
                    "decoded_xml_exceeds_limit", session_name=session_name
                )
            xml_payload = xml_path.read_text(encoding="utf-8", errors="replace")
            events, truncated = parse_tracerpt_xml(
                xml_payload,
                machine_id=machine_id,
            )
            summary = (
                summary_path.read_text(encoding="utf-8", errors="replace")
                if summary_path.is_file() else ""
            )
            events_lost, buffers_lost = parse_tracerpt_loss_summary(summary)
            elapsed = max(0.0, self._monotonic() - started_at)
            return ETWProcessCapture(
                session_name=session_name,
                events=events,
                duration_seconds=elapsed,
                etl_size_bytes=etl_size,
                events_lost=events_lost,
                buffers_lost=buffers_lost,
                truncated=truncated,
            )
        except ETWProcessCaptureError:
            raise
        except BaseException:
            raise
        finally:
            if started and not stopped:
                stopped = self._stop_owned_session(session_name)
            if stopped or not started:
                shutil.rmtree(workspace, ignore_errors=True)

