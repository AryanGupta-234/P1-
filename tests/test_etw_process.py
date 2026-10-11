from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from aie.providers.etw_process import (
    KERNEL_PROCESS_GUID,
    ETWProcessCaptureError,
    WindowsETWProcessProvider,
    parse_tracerpt_loss_summary,
    parse_tracerpt_xml,
)


SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<Events xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <Event>
    <System>
      <Provider Name="Microsoft-Windows-Kernel-Process" Guid="{22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}" />
      <EventID>1</EventID><Version>2</Version>
      <TimeCreated SystemTime="2026-10-11T10:00:00.000Z" />
    </System>
    <EventData>
      <Data Name="ProcessID">4321</Data>
      <Data Name="ParentProcessID">123</Data>
      <Data Name="ImageName">C:\\Users\\demo\\app.exe</Data>
    </EventData>
  </Event>
  <Event>
    <System>
      <Provider Name="Microsoft-Windows-Kernel-Process" Guid="{22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}" />
      <EventID>2</EventID><Version>0</Version>
      <TimeCreated SystemTime="2026-10-11T10:00:02.000Z" />
    </System>
    <EventData>
      <Data Name="ProcessID">4321</Data>
      <Data Name="ImageName">app.exe</Data>
    </EventData>
  </Event>
  <Event>
    <System>
      <Provider Name="Microsoft-Windows-Kernel-Image" Guid="{2cb15d1d-5fc1-11d2-abe1-00a0c911f518}" />
      <EventID>1</EventID><Version>0</Version>
      <TimeCreated SystemTime="2026-10-11T10:00:03.000Z" />
    </System>
    <EventData><Data Name="ProcessID">99</Data></EventData>
  </Event>
  <Event>
    <System>
      <Provider Name="Microsoft-Windows-Kernel-Process" Guid="{22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}" />
      <EventID>1</EventID><Version>0</Version>
      <TimeCreated SystemTime="2026-10-11T10:00:04.000Z" />
    </System>
    <EventData><Data Name="ProcessID">invalid</Data></EventData>
  </Event>
</Events>
"""


def test_parse_tracerpt_only_allowlisted_process_lifecycle_metadata():
    events, truncated = parse_tracerpt_xml(SAMPLE_XML, machine_id="host-test")

    assert not truncated
    assert [event.event_type for event in events] == [
        "windows.process.started",
        "windows.process.stopped",
    ]
    started = events[0]
    assert started.data["pid"] == 4321
    assert started.data["parent_pid"] == 123
    assert started.data["process_name"] == "app.exe"
    assert "C:\\Users" not in started.model_dump_json()
    assert started.entity.stable_id
    assert events[1].data["pid"] == 4321


def test_parse_tracerpt_applies_event_cap_and_reports_truncation():
    events, truncated = parse_tracerpt_xml(
        SAMPLE_XML,
        machine_id="host-test",
        max_events=1,
    )

    assert len(events) == 1
    assert truncated


def test_parse_tracerpt_rejects_bad_xml_and_invalid_event_cap():
    with pytest.raises(ValueError, match="invalid XML"):
        parse_tracerpt_xml("<broken", machine_id="host-test")
    with pytest.raises(ValueError, match="max_events"):
        parse_tracerpt_xml(SAMPLE_XML, machine_id="host-test", max_events=0)


def test_loss_summary_preserves_unknown_metrics():
    assert parse_tracerpt_loss_summary("Events Lost: 3\nBuffers Lost: 1") == (3, 1)
    assert parse_tracerpt_loss_summary("Summary unavailable") == (None, None)


def test_capture_starts_stops_owned_session_and_persists_bounded_metadata(tmp_path):
    calls: list[list[str]] = []
    clock = [10.0]

    def runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["logman.exe", "create", "trace"]:
            etl = Path(command[command.index("-o") + 1])
            etl.write_bytes(b"synthetic-etl")
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["logman.exe", "stop"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "tracerpt.exe":
            xml = Path(command[command.index("-o") + 1])
            summary = Path(command[command.index("-summary") + 1])
            xml.write_text(SAMPLE_XML, encoding="utf-8")
            summary.write_text("Events Lost: 0\nBuffers Lost: 0", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"Unexpected executable: {command[0]}")

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    provider = WindowsETWProcessProvider(
        runner=runner,
        sleep=sleep,
        monotonic=lambda: clock[0],
        is_windows=True,
        temp_root=tmp_path,
        machine_id="host-test",
    )
    capture = provider.collect(duration_seconds=5)

    assert len(capture.events) == 2
    assert capture.events_lost == 0
    assert capture.buffers_lost == 0
    assert capture.duration_seconds == 5.0
    assert capture.etl_size_bytes == len(b"synthetic-etl")
    create = calls[0]
    stop = calls[1]
    assert create[:4] == ["logman.exe", "create", "trace", capture.session_name]
    assert create[create.index("-p") + 1] == f"{{{KERNEL_PROCESS_GUID}}}"
    assert create[create.index("-p") + 2] == "0x10"
    assert create[create.index("-max") + 1] == "8"
    assert create[create.index("-nb") + 1:create.index("-nb") + 3] == ["2", "8"]
    assert stop == ["logman.exe", "stop", capture.session_name, "-ets"]
    assert not Path(create[create.index("-o") + 1]).exists()
    coverage = capture.coverage_event(machine_id="host-test")
    assert coverage.data["loss_metrics_available"] is True


def test_capture_refuses_non_windows_before_running_commands():
    called = []
    provider = WindowsETWProcessProvider(
        runner=lambda *a, **k: called.append(a),
        is_windows=False,
    )

    with pytest.raises(ETWProcessCaptureError, match="native_windows_required"):
        provider.collect()
    assert called == []


def test_capture_validates_duration_before_running_commands():
    called = []
    provider = WindowsETWProcessProvider(
        runner=lambda *a, **k: called.append(a),
        is_windows=True,
    )

    with pytest.raises(ValueError, match="duration_seconds"):
        provider.collect(duration_seconds=0)
    assert called == []


def test_failed_stop_preserves_workspace_and_reports_exact_session_command(tmp_path):
    def runner(command, **kwargs):
        if command[:3] == ["logman.exe", "create", "trace"]:
            Path(command[command.index("-o") + 1]).write_bytes(b"etl")
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["logman.exe", "stop"]:
            return subprocess.CompletedProcess(command, 5, "", "")
        raise AssertionError("trace decode must not run after an unconfirmed stop")

    provider = WindowsETWProcessProvider(
        runner=runner,
        sleep=lambda _: None,
        is_windows=True,
        temp_root=tmp_path,
        machine_id="host-test",
    )
    with pytest.raises(ETWProcessCaptureError, match="session_stop_failed") as raised:
        provider.collect()

    error = raised.value
    assert error.recovery_command == f"logman stop {error.session_name} -ets"
    assert error.workspace is not None
    assert Path(error.workspace).is_dir()
    shutil.rmtree(error.workspace)


def test_capture_cleans_workspace_when_session_start_fails(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 5, "", "")

    provider = WindowsETWProcessProvider(
        runner=runner,
        is_windows=True,
        temp_root=tmp_path,
        machine_id="host-test",
    )
    with pytest.raises(ETWProcessCaptureError, match="session_start_failed"):
        provider.collect()

    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []
