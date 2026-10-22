"""Managed, checksum-pinned LibreHardwareMonitor read-only sensor provider.

The provider binds its HTTP interface to 127.0.0.1 only. SENTINEL downloads
only from the official GitHub release, verifies its SHA-256 digest, and never
silently accepts or installs the optional PawnIO kernel driver.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import psutil

from . import core

VERSION = "0.9.6"
EXECUTABLE_NAMES = ("LibreHardwareMonitor.Windows.Forms.exe", "LibreHardwareMonitor.exe")
PROCESS_NAMES = frozenset(name.casefold() for name in EXECUTABLE_NAMES)
PORT = 8085
ARCHIVE_URL = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip"
ARCHIVE_SHA256 = "086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_FILES = 600
_ALLOWED_REDIRECT_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
_LOCK = threading.RLock()
_LAST_START_ATTEMPT = 0.0


def install_root() -> Path:
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    return Path(program_files) / "Sentinel" / "dependencies" / "LibreHardwareMonitor"


def _find_executable(root: Path | None = None) -> Path | None:
    base = root or install_root()
    if not base.is_dir():
        return None
    # The upstream Windows Forms project sets AssemblyName to
    # LibreHardwareMonitor.Windows.Forms. Some packaged releases rename it.
    for executable_name in EXECUTABLE_NAMES:
        found = next((p for p in base.rglob(executable_name) if p.is_file()), None)
        if found is not None:
            return found
    return None


def _config_path(executable: Path) -> Path:
    # LibreHardwareMonitor reads an XML .config file adjacent to its executable.
    return executable.with_suffix(".config")


def _config_xml() -> bytes:
    settings = {
        "runWebServerMenuItem": "True",
        "listenerIp": "127.0.0.1",
        "listenerPort": str(PORT),
        "authenticationEnabled": "False",
        "mainboardMenuItem": "True",
        "cpuMenuItem": "True",
        "ramMenuItem": "True",
        "gpuMenuItem": "True",
        "powerMonitorMenuItem": "True",
        "fanControllerMenuItem": "True",
        "hddMenuItem": "True",
        "nicMenuItem": "True",
        "psuMenuItem": "True",
        "batteryMenuItem": "True",
        "startMinMenuItem": "True",
        "minTrayMenuItem": "True",
    }
    root = ET.Element("configuration")
    app_settings = ET.SubElement(root, "appSettings")
    for key, value in settings.items():
        ET.SubElement(app_settings, "add", {"key": key, "value": value})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _write_config(executable: Path) -> Path:
    path = _config_path(executable)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_config_xml())
    os.replace(temporary, path)
    return path


def _validate_member(name: str) -> PurePosixPath:
    normalized = str(name or "").replace("\\", "/")
    parsed = PurePosixPath(normalized)
    if (not normalized or parsed.is_absolute() or ":" in normalized
            or any(part in ("", ".", "..") for part in parsed.parts)):
        raise ValueError(f"unsafe path in LibreHardwareMonitor archive: {name!r}")
    return parsed


def _extract_archive(archive_path: Path, destination: Path) -> Path:
    """Extract with zip-slip, symbolic-link, entry-count and expanded-size guards."""
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_FILES:
            raise ValueError("LibreHardwareMonitor archive contains too many entries")
        for entry in entries:
            relative = _validate_member(entry.filename)
            mode = (entry.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError("symbolic links are not permitted in the sensor-provider archive")
            target = destination.joinpath(*relative.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += int(entry.file_size or 0)
            if total > MAX_UNPACKED_BYTES or entry.file_size > 32 * 1024 * 1024:
                raise ValueError("LibreHardwareMonitor archive exceeds the extraction size limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(entry, "r") as source, target.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > entry.file_size or written > 32 * 1024 * 1024:
                        raise ValueError("archive entry expanded beyond its declared size")
                    output.write(chunk)
            if written != entry.file_size:
                raise ValueError("archive entry size did not match its metadata")

    executable = _find_executable(destination)
    if executable is None:
        raise ValueError(
            "official release archive did not contain a supported executable: "
            + ", ".join(EXECUTABLE_NAMES)
        )
    required = ("LibreHardwareMonitorLib.dll", "Aga.Controls.dll", "OxyPlot.dll", "OxyPlot.WindowsForms.dll")
    missing = [name for name in required if not (executable.parent / name).is_file()]
    if missing:
        raise ValueError("sensor-provider archive is incomplete; missing: " + ", ".join(missing))
    return executable


def _download_verified() -> Path:
    request = urllib.request.Request(
        ARCHIVE_URL,
        headers={"User-Agent": "SENTINEL-HardwareProvider/1.0", "Accept": "application/octet-stream"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        final_host = urllib.parse.urlparse(response.geturl()).hostname or ""
        if final_host not in _ALLOWED_REDIRECT_HOSTS:
            raise PermissionError(f"sensor-provider download redirected to an untrusted host: {final_host}")
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_ARCHIVE_BYTES:
            raise ValueError("sensor-provider archive exceeds the download size limit")
        descriptor, temporary_name = tempfile.mkstemp(prefix="sentinel-lhm-", suffix=".zip")
        digest = hashlib.sha256()
        total = 0
        try:
            with os.fdopen(descriptor, "wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ValueError("sensor-provider download exceeded the size limit")
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest().casefold() != ARCHIVE_SHA256:
                raise ValueError("LibreHardwareMonitor release checksum verification failed; downloaded file was discarded")
            return Path(temporary_name)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise


def _install() -> Path:
    if not core.IS_WIN:
        raise RuntimeError("LibreHardwareMonitor integration is Windows-only")
    base = install_root()
    release = base / VERSION
    existing = _find_executable(release)
    if existing:
        return existing
    base.mkdir(parents=True, exist_ok=True)
    archive = _download_verified()
    staging = base / (".staging-" + VERSION)
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=False)
        staged_executable = _extract_archive(archive, staging)
        relative_parent = staged_executable.parent.relative_to(staging)
        if release.exists():
            shutil.rmtree(release)
        os.replace(staging, release)
        executable = release / relative_parent / staged_executable.name
        if not executable.is_file():
            raise RuntimeError("installed LibreHardwareMonitor executable could not be verified")
        return executable
    finally:
        try:
            archive.unlink()
        except OSError:
            pass
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _process_running(executable: Path | None = None) -> bool:
    expected = os.path.normcase(os.path.abspath(str(executable))) if executable else None
    try:
        for process in psutil.process_iter(["name", "exe"]):
            try:
                name = str(process.info.get("name") or "").casefold()
                actual = process.info.get("exe")
                if expected and actual and os.path.normcase(os.path.abspath(actual)) == expected:
                    return True
                if name in PROCESS_NAMES and (not expected or not actual):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
    except Exception:
        return False
    return False


def _probe() -> dict[str, Any]:
    connection = None
    try:
        connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=2.0)
        connection.request("GET", "/data.json", headers={"Accept": "application/json", "Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            response.read(1024)
            return {"connected": False, "sensor_count": 0, "reason": f"local sensor endpoint returned HTTP {response.status}"}
        payload = response.read(4 * 1024 * 1024 + 1)
        if len(payload) > 4 * 1024 * 1024:
            return {"connected": False, "sensor_count": 0, "reason": "local sensor endpoint exceeded the 4 MiB response limit"}
        document = json.loads(payload.decode("utf-8-sig"))
        count = 0
        stack = [document] if isinstance(document, dict) else []
        visited = 0
        while stack and visited < 5000:
            node = stack.pop()
            visited += 1
            if not isinstance(node, dict):
                continue
            if node.get("SensorId") and (node.get("RawValue") is not None or node.get("Value") is not None):
                count += 1
            children = node.get("Children")
            if isinstance(children, list):
                stack.extend(child for child in children[:1000] if isinstance(child, dict))
        return {"connected": True, "sensor_count": count, "reason": ""}
    except Exception as exc:
        return {"connected": False, "sensor_count": 0, "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def status() -> dict[str, Any]:
    executable = _find_executable()
    running = _process_running(executable) if executable else False
    probe = _probe()
    return {
        "installed": executable is not None,
        "running": running,
        "connected": bool(probe["connected"]),
        "sensor_count": int(probe["sensor_count"]),
        "version": VERSION if executable else None,
        "port": PORT,
        "endpoint": f"http://127.0.0.1:{PORT}/data.json",
        "executable": str(executable) if executable else None,
        "reason": probe["reason"],
        "driver_policy": "LibreHardwareMonitor may show its optional PawnIO driver prompt; SENTINEL never accepts or installs that driver automatically.",
    }


def start_if_installed() -> dict[str, Any]:
    """Restart the managed provider on demand after an unexpected exit."""
    global _LAST_START_ATTEMPT
    if not core.IS_WIN or core.CFG.get("advanced", {}).get("lhm_enabled") is not True:
        return status()
    executable = _find_executable()
    if executable is None:
        return status()
    probe = _probe()
    if probe["connected"] or _process_running(executable):
        return status()
    now = time.monotonic()
    with _LOCK:
        if now - _LAST_START_ATTEMPT < 60:
            return status()
        _LAST_START_ATTEMPT = now
        try:
            _write_config(executable)
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(
                [str(executable)], cwd=str(executable.parent),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, creationflags=flags,
            )
        except Exception as exc:
            return {
                "installed": True, "running": False, "connected": False,
                "sensor_count": 0, "version": VERSION,
                "message": f"Provider launch failed: {type(exc).__name__}: {str(exc)[:160]}",
            }
    return status()


def install_and_start() -> dict[str, Any]:
    """Explicit operator-triggered installation from the checksum-pinned release."""
    if not core.IS_WIN:
        raise RuntimeError("LibreHardwareMonitor can only be installed on Windows")
    executable = _install()
    _write_config(executable)
    if not _process_running(executable) and not _probe()["connected"]:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(
            [str(executable)], cwd=str(executable.parent),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, creationflags=flags,
        )
    deadline = time.monotonic() + 7.0
    probe = _probe()
    while not probe["connected"] and time.monotonic() < deadline:
        time.sleep(0.35)
        probe = _probe()
    provider_status = status()
    connected = bool(probe["connected"])
    message = (
        f"LibreHardwareMonitor {VERSION} is installed and its local sensor server is responding with {probe['sensor_count']} numeric sensor(s)."
        if connected else
        "LibreHardwareMonitor was installed and launched, but its local sensor endpoint is not responding yet. Check its tray prompt/window; any optional PawnIO driver prompt requires your explicit decision."
    )
    return {
        "ok": True, "installed": True, "running": provider_status["running"] or connected,
        "connected": connected, "sensor_count": int(probe["sensor_count"]),
        "version": VERSION, "port": PORT, "message": message,
        "first_run_note": provider_status["driver_policy"],
        "provider": provider_status,
    }
