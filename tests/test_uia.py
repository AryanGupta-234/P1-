import json
import subprocess

import pytest

from aie.providers import uia


def test_non_windows_inspection_fails_closed(monkeypatch):
    monkeypatch.setattr(uia.os, "name", "posix")
    result = uia.inspect_windows()
    assert result.available is False
    assert result.reason == "native_windows_required"
    assert result.windows == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_windows": 0}, {"max_windows": 41},
        {"max_nodes": 0}, {"max_nodes": 1001},
        {"max_depth": 0}, {"max_depth": 9},
        {"timeout": 0.5}, {"timeout": 31},
    ],
)
def test_inspection_rejects_unbounded_limits(kwargs):
    with pytest.raises(ValueError):
        uia.inspect_windows(**kwargs)


def test_uia_script_does_not_read_names_or_values():
    script = uia._powershell_script(5, 100, 4)
    assert "Current.Name" not in script
    assert "ValuePattern" not in script
    assert "TextPattern" not in script
    assert "IsPassword" in script
    assert "AutomationId" in script
    assert "Get-Process" in script


def test_inspection_returns_bounded_structural_metadata(monkeypatch):
    monkeypatch.setattr(uia.os, "name", "nt")
    monkeypatch.setattr(uia.shutil, "which", lambda _: "powershell.exe")
    payload = {
        "schema_version": 1, "mode": "read_only_structure",
        "text_values_collected": False, "password_values_collected": False,
        "windows": [{"controls": [{"control_type": "ControlType.Window",
                                   "automation_id": "MainWindow"}]}],
        "nodes_inspected": 1, "truncated": False,
    }
    monkeypatch.setattr(
        uia.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(payload), ""),
    )
    result = uia.inspect_windows()
    assert result.available is True
    assert result.nodes_inspected == 1
    assert result.windows[0]["controls"][0]["automation_id"] == "MainWindow"


def test_inspection_rejects_oversized_and_malformed_output(monkeypatch):
    monkeypatch.setattr(uia.os, "name", "nt")
    monkeypatch.setattr(uia.shutil, "which", lambda _: "powershell.exe")
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, '{"schema_version":999}', "")
    monkeypatch.setattr(uia.subprocess, "run", fake_run)
    assert uia.inspect_windows().reason == "invalid_uia_response"
    monkeypatch.setattr(
        uia.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "x" * (uia.MAX_OUTPUT_BYTES + 1), ""),
    )
    assert uia.inspect_windows().reason == "uia_output_limit_exceeded"


def test_inspection_timeout_is_reported(monkeypatch):
    monkeypatch.setattr(uia.os, "name", "nt")
    monkeypatch.setattr(uia.shutil, "which", lambda _: "powershell.exe")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(uia.subprocess, "run", timeout)
    result = uia.inspect_windows()
    assert result.available is False
    assert result.reason == "inspection_timeout"
    assert result.truncated is True
