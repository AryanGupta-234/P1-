from __future__ import annotations

import os
import subprocess

import pytest

from aie.providers.etw_process import ETWProcessTrace, ETWSessionError


def _result(code=0):
    return subprocess.CompletedProcess([], code, "", "")


def test_etw_trace_uses_kernel_process_provider_and_bounded_buffers(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return _result()

    output = tmp_path / "traces" / "process.etl"
    trace = ETWProcessTrace(output, runner=runner)
    with trace:
        assert trace._started is True
    assert trace._started is False
    start_args = calls[0][0]
    assert start_args[:4] == [
        "logman.exe", "start", trace.session_name, "-ets"
    ]
    assert "Microsoft-Windows-Kernel-Process" in start_args
    assert start_args[-4:] == ["-nb", "16", "64"][-4:] if False else start_args[-3:] == ["-nb", "16", "64"]
    assert calls[1][0] == ["logman.exe", "stop", trace.session_name, "-ets"]


def test_etw_trace_refuses_overwrite_and_invalid_buffer_bounds(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    existing = tmp_path / "existing.etl"
    existing.write_bytes(b"keep")
    trace = ETWProcessTrace(existing, runner=lambda *a, **k: _result())
    with pytest.raises(FileExistsError):
        trace.start()
    with pytest.raises(ValueError):
        ETWProcessTrace(tmp_path / "bad.etl", buffer_size_kb=8,
                        runner=lambda *a, **k: _result())


def test_etw_trace_marks_session_stopped_even_if_stop_command_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    calls = [0]

    def runner(args, **kwargs):
        calls[0] += 1
        return _result(0 if calls[0] == 1 else 1)

    trace = ETWProcessTrace(tmp_path / "trace.etl", runner=runner)
    trace.start()
    with pytest.raises(ETWSessionError):
        trace.stop()
    assert trace._started is False
