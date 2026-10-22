import io
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from sentinel import hardware_provider


def test_provider_config_is_localhost_only_and_starts_minimized():
    root = ET.fromstring(hardware_provider._config_xml())
    values = {node.attrib["key"]: node.attrib["value"] for node in root.findall("./appSettings/add")}
    assert values["runWebServerMenuItem"].lower() == "true"
    assert values["listenerIp"] == "127.0.0.1"
    assert values["listenerPort"] == "8085"
    assert values["authenticationEnabled"].lower() == "false"
    assert values["startMinMenuItem"].lower() == "true"
    assert values["minTrayMenuItem"].lower() == "true"


@pytest.mark.parametrize("path", ["../outside.dll", "/rooted.dll", "C:/outside.dll", r"..\\outside.dll"])
def test_provider_archive_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        hardware_provider._validate_member(path)


def test_provider_extracts_only_a_complete_safe_archive(tmp_path: Path):
    archive_path = tmp_path / "provider.zip"
    stage = tmp_path / "stage"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("LibreHardwareMonitor.Windows.Forms.exe", b"executable")
        archive.writestr("LibreHardwareMonitorLib.dll", b"library")
        archive.writestr("Aga.Controls.dll", b"controls")
        archive.writestr("OxyPlot.dll", b"plot")
        archive.writestr("OxyPlot.WindowsForms.dll", b"forms")
    executable = hardware_provider._extract_archive(archive_path, stage)
    assert executable.name == "LibreHardwareMonitor.Windows.Forms.exe"
    assert executable.read_bytes() == b"executable"
    assert hardware_provider.ARCHIVE_SHA256 == "086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001"


def test_provider_rejects_zip_slip_entries(tmp_path: Path):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.txt", b"bad")
    with pytest.raises(ValueError, match="unsafe path"):
        hardware_provider._extract_archive(archive_path, tmp_path / "out")

def test_provider_config_respects_a_valid_persisted_port(monkeypatch):
    monkeypatch.setattr(
        hardware_provider.core,
        "CFG",
        {"advanced": {"lhm_http_port": 8123}},
    )
    assert hardware_provider.configured_port() == 8123
    root = ET.fromstring(hardware_provider._config_xml())
    values = {node.attrib["key"]: node.attrib["value"] for node in root.findall("./appSettings/add")}
    assert values["listenerPort"] == "8123"


def test_provider_config_rejects_an_invalid_persisted_port(monkeypatch):
    monkeypatch.setattr(
        hardware_provider.core,
        "CFG",
        {"advanced": {"lhm_http_port": 70000}},
    )
    assert hardware_provider.configured_port() == 8085
    assert hardware_provider._probe(70000)["connected"] is False

