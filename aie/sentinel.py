"""Persistent Windows Sentinel background worker and lifecycle commands."""
from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
import typer
from rich.console import Console

from aie.config import data_dir, database_path, observer_is_paused
from aie.sentinel_dashboard import make_dashboard_server, start_dashboard_thread
from aie.store import EventStore

sentinel_app = typer.Typer(no_args_is_help=True, help="Persistent Windows Sentinel background agent.")
console = Console()
TASK_NAME = "AIE Sentinel Background Watch"

DEFAULT_CONFIG: dict[str, Any] = {
    "sample_interval_seconds": 2.0,
    "network_interval_seconds": 30.0,
    "include_network": True,
    "include_foreground": True,
    "include_process_resources": True,
    "process_resource_interval_seconds": 15.0,
    "include_event_logs": False,
    "include_etw": False,
    "include_window_titles": False,
    "ui_tree_apps": [],
    "ai_enabled": True,
    "analysis_interval_seconds": 300,
    "fast_model": None,
    "deep_model": None,
    "dashboard_port": 8765,
    "registry_enabled": True,
    "registry_interval_seconds": 180,
    "deep_inventory_enabled": True,
    "deep_inventory_interval_seconds": 900,
    "knowledge_enabled": True,
    "knowledge_interval_seconds": 21600,
    "knowledge_learn_top_per_query": 4,
    "knowledge_github_files_per_repo": 8,
}


def _paths() -> dict[str, Path]:
    root = data_dir()
    return {
        "root": root,
        "config": root / "sentinel-config.json",
        "state": root / "sentinel-state.json",
        "stop": root / "sentinel.stop",
        "token": root / "sentinel-dashboard.token",
        "log": root / "sentinel.log",
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_windows() -> None:
    if os.name != "nt":
        raise typer.BadParameter("Sentinel requires native Windows 10/11.")


def _load_config() -> dict[str, Any]:
    path = _paths()["config"]
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Sentinel config is unreadable. Use configure --reset.") from exc
        if not isinstance(loaded, dict):
            raise RuntimeError("Sentinel config must be a JSON object.")
        for key in DEFAULT_CONFIG:
            if key in loaded:
                config[key] = loaded[key]

    ranges = {
        "sample_interval_seconds": (0.5, 30.0),
        "network_interval_seconds": (5.0, 300.0),
        "process_resource_interval_seconds": (2.0, 300.0),
    }
    for key, (minimum, maximum) in ranges.items():
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
            raise RuntimeError(f"{key} must be between {minimum} and {maximum}.")
    if not isinstance(config["analysis_interval_seconds"], int) or isinstance(config["analysis_interval_seconds"], bool) or not 60 <= config["analysis_interval_seconds"] <= 3600:
        raise RuntimeError("analysis_interval_seconds must be between 60 and 3600.")
    for key, minimum, maximum in (
        ("registry_interval_seconds", 60, 3600),
        ("deep_inventory_interval_seconds", 300, 7200),
        ("knowledge_interval_seconds", 3600, 604800),
    ):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise RuntimeError(f"{key} must be between {minimum} and {maximum}.")
    for key, minimum, maximum in (
        ("knowledge_learn_top_per_query", 1, 10),
        ("knowledge_github_files_per_repo", 1, 20),
    ):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise RuntimeError(f"{key} must be between {minimum} and {maximum}.")
    if not isinstance(config["ui_tree_apps"], list) or any(not isinstance(item, str) for item in config["ui_tree_apps"]):
        raise RuntimeError("ui_tree_apps must be a list of executable names.")
    for key in (
        "include_network", "include_foreground", "include_process_resources",
        "include_event_logs", "include_etw", "include_window_titles", "ai_enabled",
        "registry_enabled", "deep_inventory_enabled", "knowledge_enabled",
    ):
        if not isinstance(config[key], bool):
            raise RuntimeError(f"{key} must be a boolean.")
    for key in ("fast_model", "deep_model"):
        value = config[key]
        if value is not None and (
            not isinstance(value, str) or not value.strip() or len(value) > 200
        ):
            raise RuntimeError(f"{key} must be null or an installed model name.")
    return config


def _save_config(config: dict[str, Any]) -> None:
    path = _paths()["config"]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(config, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_state() -> dict[str, Any]:
    try:
        value = json.loads(_paths()["state"].read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    path = _paths()["state"]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, indent=2, ensure_ascii=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _pid_is_sentinel(pid: object) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return False
        if process.name().casefold() not in {"python.exe", "pythonw.exe", "python"}:
            return False
        command = " ".join(process.cmdline()).casefold()
        return "aie.sentinel" in command and "worker" in command
    except (psutil.Error, OSError, PermissionError):
        return False


def _rotate_log(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > 8 * 1024 * 1024:
            backup = path.with_suffix(".log.1")
            try:
                backup.unlink()
            except FileNotFoundError:
                pass
            path.replace(backup)
    except OSError:
        pass


def _start_worker() -> bool:
    _require_windows()
    state = _read_state()
    if _pid_is_sentinel(state.get("pid")):
        return False
    paths = _paths()
    try:
        paths["stop"].unlink()
    except FileNotFoundError:
        pass
    _rotate_log(paths["log"])
    flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    )
    with paths["log"].open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "aie.sentinel", "worker"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(Path.cwd()),
            creationflags=flags,
            close_fds=True,
        )
    state.update({
        "status": "starting",
        "pid": process.pid,
        "launch_requested_at": _now(),
        "worker_command": "python -m aie.sentinel worker",
    })
    _write_state(state)
    return True


def _create_logon_task() -> None:
    _require_windows()
    schtasks = shutil.which("schtasks.exe")
    if not schtasks:
        raise RuntimeError("Windows Task Scheduler CLI was not found.")
    command = f'"{sys.executable}" -m aie.sentinel worker'
    completed = subprocess.run(
        [
            schtasks, "/Create", "/SC", "ONLOGON",
            "/TN", TASK_NAME, "/TR", command,
            "/IT", "/RL", "LIMITED", "/F",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Task Scheduler rejected the task").strip()
        raise RuntimeError(detail[:500])


def _delete_logon_task() -> bool:
    _require_windows()
    schtasks = shutil.which("schtasks.exe")
    if not schtasks:
        raise RuntimeError("Windows Task Scheduler CLI was not found.")
    completed = subprocess.run(
        [schtasks, "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode == 0:
        return True
    output = (completed.stderr + completed.stdout).casefold()
    if any(term in output for term in ("cannot find", "does not exist", "not found")):
        return False
    raise RuntimeError((completed.stderr or completed.stdout or "Unable to delete scheduled task").strip()[:500])


def _request_stop(timeout_seconds: float = 12.0) -> bool:
    _require_windows()
    _paths()["stop"].touch(exist_ok=True)
    deadline = time.monotonic() + max(0.0, min(timeout_seconds, 30.0))
    while time.monotonic() < deadline:
        if not _pid_is_sentinel(_read_state().get("pid")):
            return True
        time.sleep(0.25)
    return not _pid_is_sentinel(_read_state().get("pid"))


def _acquire_mutex() -> tuple[Any, Any] | None:
    if os.name != "nt":
        return None
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, True, "Local\\AIE.Sentinel.Background")
    last_error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(last_error)
    if last_error == 183:
        kernel32.CloseHandle(handle)
        return None
    return kernel32, handle


def _ensure_token() -> str:
    path = _paths()["token"]
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    except OSError:
        pass
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    return value


def _worker() -> None:
    _require_windows()
    mutex = _acquire_mutex()
    if mutex is None:
        return

    paths = _paths()
    stop_path = paths["stop"]
    config = _load_config()
    store = EventStore(database_path())
    state_lock = threading.RLock()
    ai_lock = threading.Lock()
    token = _ensure_token()
    server = None
    dashboard_thread = None
    command_queue: queue.Queue[str] = queue.Queue(maxsize=12)
    started = _now()
    state: dict[str, Any] = {
        "status": "starting",
        "pid": os.getpid(),
        "started_at": started,
        "heartbeat_at": _now(),
        "event_count": store.count(),
        "hardware": {},
        "provider_health": {},
        "ai": {
            "enabled": bool(config["ai_enabled"]),
            "status": "discovering" if config["ai_enabled"] else "disabled",
            "triage": {},
            "review": {},
            "automatic_actions_taken": False,
        },
        "features": {
            "network": config["include_network"],
            "foreground": config["include_foreground"],
            "process_resources": config["include_process_resources"],
            "event_logs": config["include_event_logs"],
            "kernel_etw": config["include_etw"],
            "window_titles": config["include_window_titles"],
            "ui_tree_allowlist_count": len(config["ui_tree_apps"]),
            "registry": config["registry_enabled"],
            "deep_windows_inventory": config["deep_inventory_enabled"],
            "microsoft_knowledge_crawler": config["knowledge_enabled"],
        },
        "limitations": [
            "No custom kernel driver is installed.",
            "Kernel ETW is optional and can require an elevated token.",
            "No keylogging, credential capture, screen recording or microphone capture.",
        ],
    }

    for port in range(int(config["dashboard_port"]), int(config["dashboard_port"]) + 11):
        try:
            server = make_dashboard_server(
                token=token,
                state_path=paths["state"],
                stop_path=stop_path,
                db_path=database_path(),
                command_queue=command_queue,
                config_loader=_load_config,
                config_saver=_save_config,
                inference_lock=ai_lock,
                port=port,
            )
            state["dashboard_url"] = f"http://127.0.0.1:{port}/"
            break
        except OSError:
            continue
    if server is not None:
        dashboard_thread = start_dashboard_thread(server)
    else:
        state["dashboard_error"] = "No free loopback dashboard port was found."

    _write_state(state)
    next_analysis = time.monotonic() + 45.0
    last_count_update = 0.0
    last_cycle_event = 0.0
    ai_thread: threading.Thread | None = None
    inventory_lock = threading.Lock()
    inventory_thread: threading.Thread | None = None
    next_inventory = time.monotonic() + 5.0
    registry_provider = None
    registry_init_error: str | None = None
    try:
        from aie.providers.registry import WindowsRegistryProvider
        registry_provider = WindowsRegistryProvider()
    except Exception as exc:  # noqa: BLE001 - optional registry collector degrades independently.
        registry_init_error = type(exc).__name__
    registry_lock = threading.Lock()
    registry_thread: threading.Thread | None = None
    next_registry = time.monotonic() + 4.0
    deep_inventory_lock = threading.Lock()
    deep_inventory_thread: threading.Thread | None = None
    next_deep_inventory = time.monotonic() + 20.0
    knowledge_lock = threading.Lock()
    knowledge_thread: threading.Thread | None = None
    next_knowledge = time.monotonic() + 60.0
    state["registry"] = {
        "enabled": bool(config["registry_enabled"]),
        "status": "degraded" if registry_init_error else ("starting" if config["registry_enabled"] else "disabled"),
        "error": registry_init_error,
        "last_snapshot_at": None,
    }
    state["deep_inventory"] = {
        "enabled": bool(config["deep_inventory_enabled"]),
        "status": "scheduled" if config["deep_inventory_enabled"] else "disabled",
        "last_snapshot_at": None,
    }
    state["knowledge"] = {
        "enabled": bool(config["knowledge_enabled"]),
        "status": "scheduled" if config["knowledge_enabled"] else "disabled",
        "documents": 0,
    }

    def update_inventory() -> None:
        nonlocal inventory_thread
        try:
            from aie.sentinel_inventory import collect_system_inventory
            event = collect_system_inventory()
            store.append(event)
            data = event.data
            with state_lock:
                state["last_inventory_at"] = event.timestamp.isoformat()
                state["inventory_summary"] = {
                    "processes": data.get("process_count", 0),
                    "applications": data.get("installed_application_count", 0),
                    "services": data.get("service_count", 0),
                    "scheduled_tasks": data.get("scheduled_task_count", 0),
                }
                state["event_count"] = store.count()
                _write_state(state)
        except Exception as exc:  # noqa: BLE001 - inventory refresh cannot stop observation.
            with state_lock:
                state["inventory_error"] = type(exc).__name__
                _write_state(state)
        finally:
            inventory_lock.release()
            inventory_thread = None

    def update_registry() -> None:
        nonlocal registry_thread
        try:
            if registry_provider is None:
                raise RuntimeError(registry_init_error or "registry_provider_unavailable")
            events = registry_provider.collect_snapshot()
            added = store.append_many(events)
            latest = events[-1] if events else None
            with state_lock:
                if latest is not None:
                    data = latest.data
                    state["registry"] = {
                        "enabled": True,
                        "status": "watching",
                        "last_snapshot_at": latest.timestamp.isoformat(),
                        "event_type": latest.event_type,
                        "changed_sections": data.get("changed_sections", []),
                        "service_count": data.get("service_catalog", {}).get("service_registry_count_sampled", 0),
                        "driver_service_count": data.get("service_catalog", {}).get("driver_service_count_sampled", 0),
                    }
                else:
                    state["registry"]["status"] = "watching"
                state["registry"]["last_poll_at"] = _now()
                state["registry"]["events_added"] = int(state["registry"].get("events_added", 0)) + added
                state["event_count"] = store.count()
                _write_state(state)
        except Exception as exc:  # noqa: BLE001 - registry access errors do not stop other sensors.
            with state_lock:
                state["registry"] = {
                    "enabled": True,
                    "status": "degraded",
                    "error": type(exc).__name__,
                    "last_poll_at": _now(),
                }
                _write_state(state)
        finally:
            registry_lock.release()
            registry_thread = None

    def update_deep_inventory() -> None:
        nonlocal deep_inventory_thread
        try:
            from aie.providers.windows_internal import collect_windows_deep_inventory
            event = collect_windows_deep_inventory()
            store.append(event)
            data = event.data
            operating_system = data.get("operating_system", {})
            computer = data.get("computer", {})
            bios = data.get("bios", {})
            secure_boot = data.get("secure_boot", {})
            defender = data.get("defender_status", {})
            disk_summary = []
            for disk in data.get("fixed_disks", [])[:16]:
                if not isinstance(disk, dict):
                    continue
                try:
                    size = int(disk.get("Size") or 0)
                    free = int(disk.get("FreeSpace") or 0)
                except (TypeError, ValueError):
                    continue
                disk_summary.append({
                    "drive": str(disk.get("DeviceID") or "Drive")[:12],
                    "filesystem": str(disk.get("FileSystem") or "—")[:16],
                    "size_gib": round(size / (1024 ** 3), 1),
                    "free_gib": round(free / (1024 ** 3), 1),
                    "used_percent": round(max(0, min(100, (size - free) / size * 100)), 1) if size else 0,
                })
            firewall_summary = [
                {
                    "name": str(item.get("Name") or "Profile")[:24],
                    "enabled": item.get("Enabled") is True,
                    "inbound": str(item.get("DefaultInboundAction") or "—")[:20],
                    "outbound": str(item.get("DefaultOutboundAction") or "—")[:20],
                }
                for item in data.get("firewall_profiles", [])[:8]
                if isinstance(item, dict)
            ]
            pnp_summary = [
                {"status": str(item.get("status") or "unknown")[:24], "count": int(item.get("count") or 0)}
                for item in data.get("pnp_status_counts", [])[:16]
                if isinstance(item, dict)
            ]
            physical_disk_summary = [
                {
                    "name": str(item.get("FriendlyName") or "Physical disk")[:90],
                    "media_type": str(item.get("MediaType") or "—")[:24],
                    "bus_type": str(item.get("BusType") or "—")[:24],
                    "health": str(item.get("HealthStatus") or "Unknown")[:24],
                    "operational": str(item.get("OperationalStatus") or "Unknown")[:48],
                    "size_gib": round(int(item.get("Size") or 0) / (1024 ** 3), 1),
                }
                for item in data.get("physical_disks", [])[:32]
                if isinstance(item, dict)
            ]
            bitlocker_summary = [
                {
                    "mount": str(item.get("MountPoint") or "Volume")[:16],
                    "volume_status": str(item.get("VolumeStatus") or "Unknown")[:32],
                    "protection": str(item.get("ProtectionStatus") or "Unknown")[:24],
                    "encryption_percent": item.get("EncryptionPercentage"),
                    "method": str(item.get("EncryptionMethod") or "—")[:32],
                }
                for item in data.get("bitlocker_volumes", [])[:32]
                if isinstance(item, dict)
            ]
            battery_summary = [
                {
                    "name": str(item.get("Name") or "Battery")[:80],
                    "charge_percent": item.get("EstimatedChargeRemaining"),
                    "battery_status": item.get("BatteryStatus"),
                    "health_status": str(item.get("Status") or "Unknown")[:24],
                    "estimated_runtime_minutes": (
                        round(float(item.get("EstimatedRunTime")), 0)
                        if isinstance(item.get("EstimatedRunTime"), (int, float))
                        and not isinstance(item.get("EstimatedRunTime"), bool)
                        and item.get("EstimatedRunTime") >= 0
                        and item.get("EstimatedRunTime") < 2**31
                        else None
                    ),
                    "design_capacity_mwh": item.get("DesignCapacity"),
                    "full_charge_capacity_mwh": item.get("FullChargeCapacity"),
                    "capacity_health_percent": (
                        round(float(item.get("FullChargeCapacity")) / float(item.get("DesignCapacity")) * 100, 1)
                        if isinstance(item.get("DesignCapacity"), (int, float))
                        and isinstance(item.get("FullChargeCapacity"), (int, float))
                        and not isinstance(item.get("DesignCapacity"), bool)
                        and not isinstance(item.get("FullChargeCapacity"), bool)
                        and item.get("DesignCapacity") > 0
                        and item.get("FullChargeCapacity") > 0
                        else None
                    ),
                }
                for item in data.get("batteries", [])[:8]
                if isinstance(item, dict)
            ]
            posture_alerts: list[dict[str, str]] = []
            if secure_boot.get("supported") is True and secure_boot.get("enabled") is False:
                posture_alerts.append({
                    "severity": "info",
                    "category": "BOOT",
                    "title": "UEFI Secure Boot reports disabled",
                    "detail": "Secure Boot is supported on this platform but reports disabled.",
                })
            if defender.get("AntivirusEnabled") is False:
                posture_alerts.append({
                    "severity": "high",
                    "category": "DEFENDER",
                    "title": "Microsoft Defender antivirus reports disabled",
                    "detail": "The latest Windows security status reports AntivirusEnabled=false.",
                })
            if defender.get("RealTimeProtectionEnabled") is False:
                posture_alerts.append({
                    "severity": "high",
                    "category": "DEFENDER",
                    "title": "Real-time protection reports disabled",
                    "detail": "The latest Windows security status reports RealTimeProtectionEnabled=false.",
                })
            for profile in firewall_summary:
                if profile.get("enabled") is False:
                    posture_alerts.append({
                        "severity": "high",
                        "category": "FIREWALL",
                        "title": "Windows Firewall profile reports disabled",
                        "detail": str(profile.get("name") or "Profile")[:40] + " profile is disabled.",
                    })
            for disk in physical_disk_summary:
                health = str(disk.get("health") or "").casefold()
                if health in {"warning", "unhealthy", "critical"}:
                    posture_alerts.append({
                        "severity": "critical" if health in {"unhealthy", "critical"} else "high",
                        "category": "STORAGE",
                        "title": "Physical disk reports " + health.upper(),
                        "detail": str(disk.get("name") or "A physical disk")[:90],
                    })
            for item in pnp_summary:
                status_name = str(item.get("status") or "").casefold()
                if status_name in {"error", "degraded"} and int(item.get("count") or 0) > 0:
                    posture_alerts.append({
                        "severity": "high",
                        "category": "DEVICE",
                        "title": "PnP devices report " + status_name.upper(),
                        "detail": str(item.get("count")) + " present device(s) reported this status.",
                    })
            for volume in bitlocker_summary:
                protection = str(volume.get("protection") or "").casefold()
                if protection in {"off", "0", "false"}:
                    posture_alerts.append({
                        "severity": "info",
                        "category": "BITLOCKER",
                        "title": "BitLocker protection is off or suspended",
                        "detail": str(volume.get("mount") or "Volume") + " · " + str(volume.get("volume_status") or "status unavailable"),
                    })
            posture_alerts = posture_alerts[:16]
            alert_keys = [
                str(item.get("severity", "")) + "|" + str(item.get("category", "")) + "|" + str(item.get("title", ""))
                for item in posture_alerts
                if isinstance(item, dict)
            ]
            with state_lock:
                previous_alert_keys = set(state.get("deep_inventory", {}).get("alert_keys", []))
                auto_review_needed = any(
                    item.get("severity") in {"high", "critical"}
                    and (
                        str(item.get("severity", "")) + "|" +
                        str(item.get("category", "")) + "|" +
                        str(item.get("title", "")) not in previous_alert_keys
                    )
                    for item in posture_alerts
                )
                state["deep_inventory"] = {
                    "enabled": True,
                    "status": "available",
                    "last_snapshot_at": event.timestamp.isoformat(),
                    "system_driver_count": data.get("system_driver_count", 0),
                    "signed_pnp_driver_count": data.get("signed_pnp_driver_count", 0),
                    "fixed_disk_count": len(disk_summary),
                    "pnp_device_count": data.get("pnp_device_count"),
                    "pnp_status_counts": pnp_summary,
                    "defender_status_available": bool(defender),
                    "defender": {
                        key: defender.get(key)
                        for key in (
                            "AMServiceEnabled", "AntivirusEnabled",
                            "RealTimeProtectionEnabled", "BehaviorMonitorEnabled",
                            "NISEnabled",
                        )
                        if key in defender
                    } if isinstance(defender, dict) else {},
                    "firewall_profile_count": len(firewall_summary),
                    "firewall_profiles": firewall_summary,
                    "physical_disks": physical_disk_summary,
                    "physical_disk_count": len(physical_disk_summary),
                    "bitlocker_volumes": bitlocker_summary,
                    "bitlocker_volume_count": len(bitlocker_summary),
                    "batteries": battery_summary,
                    "battery_count": len(battery_summary),
                    "posture_alerts": posture_alerts,
                    "posture_alert_count": len(posture_alerts),
                    "alert_keys": alert_keys,
                    "automatic_ai_review_queued": bool(auto_review_needed and config["ai_enabled"]),
                    "operating_system": {
                        key: operating_system.get(key)
                        for key in ("Caption", "Version", "BuildNumber", "OSArchitecture")
                        if isinstance(operating_system, dict) and key in operating_system
                    },
                    "bios": {
                        key: bios.get(key)
                        for key in ("Manufacturer", "SMBIOSBIOSVersion", "ReleaseDate")
                        if isinstance(bios, dict) and key in bios
                    },
                    "secure_boot": {
                        key: secure_boot.get(key)
                        for key in ("supported", "enabled")
                        if isinstance(secure_boot, dict) and key in secure_boot
                    },
                    "logical_processors": computer.get("NumberOfLogicalProcessors") if isinstance(computer, dict) else None,
                    "physical_memory_bytes": computer.get("TotalPhysicalMemory") if isinstance(computer, dict) else None,
                    "hypervisor_present": computer.get("HypervisorPresent") if isinstance(computer, dict) else None,
                    "disks": disk_summary,
                }
                state["event_count"] = store.count()
                _write_state(state)
            if auto_review_needed and config["ai_enabled"]:
                try:
                    command_queue.put_nowait("ai_review_now")
                except queue.Full:
                    with state_lock:
                        state["deep_inventory"]["automatic_ai_review_queued"] = False
                        state["deep_inventory"]["automatic_ai_review_error"] = "command_queue_full"
                        _write_state(state)
        except Exception as exc:  # noqa: BLE001 - optional CIM inventory is isolated.
            with state_lock:
                state["deep_inventory"] = {
                    "enabled": True,
                    "status": "degraded",
                    "error": type(exc).__name__,
                    "last_attempt_at": _now(),
                }
                _write_state(state)
        finally:
            deep_inventory_lock.release()
            deep_inventory_thread = None

    def update_knowledge() -> None:
        nonlocal knowledge_thread
        try:
            from aie.knowledge.crawler import KnowledgeStore, MicrosoftKnowledgeCrawler
            from aie.contracts import AIEEvent, EntityRef
            from aie.providers.windows import host_id
            knowledge_path = data_dir() / "knowledge" / "microsoft-knowledge.sqlite3"
            knowledge_store = KnowledgeStore(knowledge_path)
            result = MicrosoftKnowledgeCrawler(knowledge_store).crawl(
                learn_top_per_query=int(config["knowledge_learn_top_per_query"]),
                github_files_per_repo=int(config["knowledge_github_files_per_repo"]),
            )
            stats = knowledge_store.stats()
            store.append(AIEEvent(
                host_id=host_id(),
                source="aie.knowledge.crawler",
                event_type="knowledge.crawl_completed",
                entity=EntityRef(type="knowledge_corpus", name="microsoft_windows"),
                data={
                    "learn_queries": result.learn_queries,
                    "learn_documents": result.learn_documents,
                    "github_repositories": result.github_repositories,
                    "github_documents": result.github_documents,
                    "documents_added": result.documents_added,
                    "documents_updated": result.documents_updated,
                    "unchanged": result.unchanged,
                    "failures": result.failures,
                    "elapsed_seconds": result.elapsed_seconds,
                    "total_documents": stats["documents"],
                    "sources": stats["sources"],
                    "network_scope": "approved_microsoft_public_sources_only",
                    "local_content_index": True,
                },
                sensitivity="internal",
                confidence=1.0,
                evidence_kind="observed",
            ))
            with state_lock:
                state["knowledge"] = {
                    "enabled": True,
                    "status": "available" if result.failures == 0 else "partial",
                    **result.to_dict(),
                    **stats,
                }
                state["event_count"] = store.count()
                _write_state(state)
        except Exception as exc:  # noqa: BLE001 - network crawling cannot stop local observation.
            with state_lock:
                state["knowledge"] = {
                    "enabled": True,
                    "status": "degraded",
                    "error": type(exc).__name__,
                    "last_attempt_at": _now(),
                }
                _write_state(state)
        finally:
            knowledge_lock.release()
            knowledge_thread = None

    def update_ai() -> None:
        nonlocal ai_thread
        try:
            from aie.sentinel_ai import SentinelModelCollaborator
            assessment = SentinelModelCollaborator(
                fast_model=config.get("fast_model"),
                deep_model=config.get("deep_model"),
            ).analyze(store.recent(120))
            if assessment is not None:
                store.append(assessment)
                data = assessment.data
                with state_lock:
                    state["ai"] = {
                        "enabled": True,
                        "status": "available",
                        "models": data.get("models", {}),
                        "triage": data.get("triage", {}),
                        "review": data.get("review", {}),
                        "knowledge_references": data.get("knowledge_references", []),
                        "last_assessment_at": assessment.timestamp.isoformat(),
                        "input_event_count": data.get("input_event_count", 0),
                        "automatic_actions_taken": False,
                    }
        except Exception as exc:  # noqa: BLE001 - optional inference must not stop sensors.
            with state_lock:
                state["ai"] = {
                    "enabled": True,
                    "status": "unavailable",
                    "error": type(exc).__name__,
                    "automatic_actions_taken": False,
                }
        finally:
            with state_lock:
                state["heartbeat_at"] = _now()
                _write_state(state)
            ai_lock.release()
            ai_thread = None

    def on_cycle(cycle: dict[str, object]) -> None:
        nonlocal next_analysis, last_count_update, last_cycle_event, next_inventory, next_registry, next_deep_inventory, next_knowledge
        nonlocal ai_thread, inventory_thread, registry_thread, deep_inventory_thread, knowledge_thread
        now_mono = time.monotonic()
        try:
            # Dashboard profile changes are persisted atomically and become live on this cycle.
            config.update(_load_config())
        except (OSError, RuntimeError, ValueError):
            pass  # Keep the last known-good in-memory profile if a concurrent edit is incomplete.
        with state_lock:
            state["status"] = "running"
            state["features"].update({
                "registry": bool(config["registry_enabled"]),
                "deep_windows_inventory": bool(config["deep_inventory_enabled"]),
                "microsoft_knowledge_crawler": bool(config["knowledge_enabled"]),
            })
            state["ai"]["enabled"] = bool(config["ai_enabled"])
            if not config["registry_enabled"] and not registry_lock.locked():
                state["registry"].update({"enabled": False, "status": "disabled"})
            if not config["deep_inventory_enabled"] and not deep_inventory_lock.locked():
                state["deep_inventory"].update({"enabled": False, "status": "disabled"})
            if not config["knowledge_enabled"] and not knowledge_lock.locked():
                state["knowledge"].update({"enabled": False, "status": "disabled"})
            if not config["ai_enabled"]:
                state["ai"]["status"] = "disabled"
            state["heartbeat_at"] = _now()
            state["observer_paused"] = observer_is_paused()
            state["last_cycle"] = cycle
            state["provider_health"] = cycle.get("provider_health", {})
            if now_mono - last_count_update >= 10.0:
                state["event_count"] = store.count()
                last_count_update = now_mono
            try:
                from aie.hardware import runtime_profile
                state["hardware"] = runtime_profile()
                state["cpu_percent"] = round(psutil.cpu_percent(interval=None), 1)
            except (OSError, RuntimeError, TypeError, ValueError):
                state["cpu_percent"] = 0.0
            if now_mono - last_cycle_event >= 30.0 and cycle.get("status") == "running":
                providers = cycle.get("providers", [])
                if isinstance(providers, list):
                    from aie.contracts import AIEEvent, EntityRef
                    from aie.providers.windows import host_id
                    store.append(AIEEvent(
                        host_id=host_id(),
                        source="aie.sentinel",
                        event_type="observer.cycle",
                        entity=EntityRef(type="sentinel_worker", name="background_watch"),
                        data={
                            "events_collected": cycle.get("events_collected", 0),
                            "providers": providers,
                            "cycle_interval_seconds": config["sample_interval_seconds"],
                        },
                        sensitivity="internal",
                        evidence_kind="observed",
                    ))
                last_cycle_event = now_mono
            _write_state(state)

        while True:
            try:
                action = command_queue.get_nowait()
            except queue.Empty:
                break

            started_actions: list[str] = []
            deferred_actions: list[str] = []
            if action in {"scan_now", "deep_scan_now"} and deep_inventory_lock.acquire(blocking=False):
                deep_inventory_thread = threading.Thread(
                    target=update_deep_inventory,
                    name="aie-sentinel-deep-scan-on-demand",
                    daemon=True,
                )
                deep_inventory_thread.start()
                started_actions.append("deep_inventory")
            if action == "scan_now" and inventory_lock.acquire(blocking=False):
                inventory_thread = threading.Thread(
                    target=update_inventory,
                    name="aie-sentinel-inventory-on-demand",
                    daemon=True,
                )
                inventory_thread.start()
                started_actions.append("system_inventory")
            if action in {"scan_now", "registry_scan_now"} and config["registry_enabled"] and registry_lock.acquire(blocking=False):
                registry_thread = threading.Thread(
                    target=update_registry,
                    name="aie-sentinel-registry-scan-on-demand",
                    daemon=True,
                )
                registry_thread.start()
                started_actions.append("registry")
            if action == "knowledge_crawl_now" and config["knowledge_enabled"] and knowledge_lock.acquire(blocking=False):
                knowledge_thread = threading.Thread(
                    target=update_knowledge,
                    name="aie-sentinel-knowledge-crawl-on-demand",
                    daemon=True,
                )
                knowledge_thread.start()
                started_actions.append("knowledge_crawl")
            if action == "ai_review_now" and config["ai_enabled"]:
                if ai_lock.acquire(blocking=False):
                    next_analysis = now_mono + int(config["analysis_interval_seconds"])
                    ai_thread = threading.Thread(
                        target=update_ai,
                        name="aie-sentinel-ai-review-on-demand",
                        daemon=True,
                    )
                    ai_thread.start()
                    started_actions.append("ai_review")
                else:
                    next_analysis = min(next_analysis, now_mono + 20.0)
                    deferred_actions.append("ai_review")
            with state_lock:
                state["last_command"] = {
                    "action": action,
                    "started": started_actions,
                    "deferred": deferred_actions,
                    "accepted_at": _now(),
                    "status": "started" if started_actions else "deferred" if deferred_actions else "busy_or_disabled",
                }
                _write_state(state)

        if now_mono >= next_inventory and inventory_lock.acquire(blocking=False):
            next_inventory = now_mono + 900.0
            inventory_thread = threading.Thread(
                target=update_inventory,
                name="aie-sentinel-windows-inventory",
                daemon=True,
            )
            inventory_thread.start()

        if cycle.get("status") == "running" and config["registry_enabled"] and registry_provider is not None:
            if now_mono >= next_registry and registry_lock.acquire(blocking=False):
                next_registry = now_mono + int(config["registry_interval_seconds"])
                registry_thread = threading.Thread(
                    target=update_registry,
                    name="aie-sentinel-registry-observer",
                    daemon=True,
                )
                registry_thread.start()

        if cycle.get("status") == "running" and config["deep_inventory_enabled"]:
            if now_mono >= next_deep_inventory and deep_inventory_lock.acquire(blocking=False):
                next_deep_inventory = now_mono + int(config["deep_inventory_interval_seconds"])
                deep_inventory_thread = threading.Thread(
                    target=update_deep_inventory,
                    name="aie-sentinel-deep-windows-inventory",
                    daemon=True,
                )
                deep_inventory_thread.start()

        if cycle.get("status") == "running" and config["knowledge_enabled"]:
            if now_mono >= next_knowledge and knowledge_lock.acquire(blocking=False):
                next_knowledge = now_mono + int(config["knowledge_interval_seconds"])
                knowledge_thread = threading.Thread(
                    target=update_knowledge,
                    name="aie-sentinel-microsoft-knowledge-crawler",
                    daemon=True,
                )
                knowledge_thread.start()

        if (
            config["ai_enabled"]
            and cycle.get("status") == "running"
            and now_mono >= next_analysis
            and ai_lock.acquire(blocking=False)
        ):
            next_analysis = now_mono + int(config["analysis_interval_seconds"])
            ai_thread = threading.Thread(
                target=update_ai,
                name="aie-sentinel-local-model-review",
                daemon=True,
            )
            ai_thread.start()

    try:
        while not stop_path.exists():
            config = _load_config()
            try:
                from aie.runtime import observe
                observe(
                    duration=86400,
                    interval=float(config["sample_interval_seconds"]),
                    db_path=database_path(),
                    include_network=bool(config["include_network"]),
                    network_interval=float(config["network_interval_seconds"]),
                    include_foreground=bool(config["include_foreground"]),
                    include_window_titles=bool(config["include_window_titles"]),
                    include_process_resources=bool(config["include_process_resources"]),
                    process_resource_interval=float(config["process_resource_interval_seconds"]),
                    include_event_logs=bool(config["include_event_logs"]),
                    include_etw=bool(config["include_etw"]),
                    include_ui_tree=bool(config["ui_tree_apps"]),
                    ui_tree_app_names={name.casefold() for name in config["ui_tree_apps"]},
                    stop_file=stop_path,
                    on_cycle=on_cycle,
                )
            except Exception as exc:  # noqa: BLE001 - recover transient provider faults.
                with state_lock:
                    state["status"] = "degraded"
                    state["last_error_type"] = type(exc).__name__
                    state["heartbeat_at"] = _now()
                    _write_state(state)
                time.sleep(5.0)
            if stop_path.exists():
                break
            time.sleep(1.0)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if dashboard_thread is not None:
            dashboard_thread.join(timeout=2.0)
        if inventory_thread is not None:
            inventory_thread.join(timeout=2.0)
        if registry_thread is not None:
            registry_thread.join(timeout=2.0)
        if deep_inventory_thread is not None:
            deep_inventory_thread.join(timeout=2.0)
        if knowledge_thread is not None:
            knowledge_thread.join(timeout=2.0)
        with state_lock:
            state["status"] = "stopped"
            state["stopped_at"] = _now()
            state["heartbeat_at"] = _now()
            _write_state(state)
        kernel32, handle = mutex
        try:
            kernel32.ReleaseMutex(handle)
        finally:
            kernel32.CloseHandle(handle)


@sentinel_app.command("start")
def sentinel_start() -> None:
    """Start Sentinel now in a detached per-user process."""
    _require_windows()
    try:
        started = _start_worker()
    except (OSError, RuntimeError, psutil.Error) as exc:
        console.print(f"[red]Start failed: {type(exc).__name__}: {exc}[/red]")
        raise typer.Exit(2) from exc
    console.print("[green]Sentinel start requested.[/green]" if started else "[cyan]Sentinel is already running.[/cyan]")


@sentinel_app.command("stop")
def sentinel_stop() -> None:
    """Gracefully stop the Sentinel worker."""
    try:
        stopped = _request_stop()
    except (OSError, RuntimeError) as exc:
        console.print(f"[red]Stop request failed: {exc}[/red]")
        raise typer.Exit(2) from exc
    console.print("[green]Sentinel stopped.[/green]" if stopped else "[yellow]Stop requested; worker has not exited yet.[/yellow]")


@sentinel_app.command("install")
def sentinel_install() -> None:
    """Install a current-user logon trigger and start Sentinel immediately."""
    try:
        _create_logon_task()
        _start_worker()
    except (OSError, RuntimeError, psutil.Error) as exc:
        console.print(f"[red]Installation failed: {type(exc).__name__}: {exc}[/red]")
        raise typer.Exit(2) from exc
    console.print("[green]Sentinel installed for this user's sign-in and started.[/green]")
    console.print("It runs as your normal user, not as SYSTEM.")


@sentinel_app.command("uninstall")
def sentinel_uninstall() -> None:
    """Stop Sentinel and remove its Task Scheduler logon trigger."""
    try:
        stopped = _request_stop()
        removed = _delete_logon_task()
    except (OSError, RuntimeError) as exc:
        console.print(f"[red]Uninstall failed: {exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(
        f"[green]Startup task {'removed' if removed else 'was not present'}; "
        f"worker {'stopped' if stopped else 'is still shutting down'}.[/green]"
    )


@sentinel_app.command("status")
def sentinel_status() -> None:
    """Display worker, collector, model and event-store status."""
    _require_windows()
    state = _read_state()
    running = _pid_is_sentinel(state.get("pid"))
    console.print(f"Worker: {'RUNNING' if running else 'STOPPED'}")
    console.print(f"Observation: {'PAUSED' if observer_is_paused() else 'ACTIVE'}")
    console.print(f"Local events: {EventStore(database_path()).count()}")
    console.print(f"Dashboard: {state.get('dashboard_url', 'not available')}")
    console.print(f"Heartbeat: {state.get('heartbeat_at', 'not available')}")
    ai = state.get("ai", {})
    console.print(f"Local model review: {ai.get('status', 'not started')}")


@sentinel_app.command("dashboard")
def sentinel_dashboard() -> None:
    """Open the authenticated local Sentinel dashboard."""
    _require_windows()
    state = _read_state()
    if not _pid_is_sentinel(state.get("pid")):
        console.print("[yellow]Sentinel is not running. Run aie sentinel start first.[/yellow]")
        raise typer.Exit(1)
    base = state.get("dashboard_url")
    if not isinstance(base, str) or not base.startswith("http://127.0.0.1:"):
        console.print("[red]Loopback dashboard is unavailable.[/red]")
        raise typer.Exit(1)
    url = f"{base}#token={_ensure_token()}"
    if not webbrowser.open(url, new=2):
        console.print(f"Open this local URL: {url}")
    else:
        console.print("[green]Sentinel command center opened.[/green]")


@sentinel_app.command("configure")
def sentinel_configure(
    reset: bool = typer.Option(False, "--reset", help="Restore conservative defaults."),
    enable_event_logs: bool = typer.Option(False, "--event-logs", help="Opt in to Application/System event metadata."),
    disable_event_logs: bool = typer.Option(False, "--no-event-logs", help="Disable Event Log sampling."),
    enable_etw: bool = typer.Option(False, "--etw", help="Opt in to kernel ETW process events; requires elevated token."),
    disable_etw: bool = typer.Option(False, "--no-etw", help="Disable ETW process events."),
    include_titles: bool = typer.Option(False, "--window-titles", help="Opt in to sensitive foreground titles."),
    disable_titles: bool = typer.Option(False, "--no-window-titles", help="Disable foreground title capture."),
    disable_ai: bool = typer.Option(False, "--no-ai", help="Disable the Ollama review cycle."),
    fast_model: str | None = typer.Option(None, "--fast-model", help="Exact installed 4B triage model tag."),
    deep_model: str | None = typer.Option(None, "--deep-model", help="Exact installed 6B review model tag."),
    analysis_interval: int | None = typer.Option(None, "--analysis-interval", min=60, max=3600),
    ui_tree_apps: str | None = typer.Option(None, "--ui-tree-apps", help="Opt in to structural UIA for comma-separated app executable names."),
    enable_registry: bool = typer.Option(False, "--registry", help="Enable bounded read-only registry change monitoring."),
    disable_registry: bool = typer.Option(False, "--no-registry", help="Disable registry monitoring."),
    enable_deep_inventory: bool = typer.Option(False, "--deep-inventory", help="Enable deeper CIM, driver, disk, PnP, Defender and firewall inventory."),
    disable_deep_inventory: bool = typer.Option(False, "--no-deep-inventory", help="Disable deeper Windows inventory."),
    enable_knowledge: bool = typer.Option(False, "--knowledge", help="Enable periodic Microsoft documentation crawling."),
    disable_knowledge: bool = typer.Option(False, "--no-knowledge", help="Disable the Microsoft knowledge crawler."),
    registry_interval: int | None = typer.Option(None, "--registry-interval", min=60, max=3600),
    deep_inventory_interval: int | None = typer.Option(None, "--deep-inventory-interval", min=300, max=7200),
    knowledge_interval: int | None = typer.Option(None, "--knowledge-interval", min=3600, max=604800),
) -> None:
    """Configure approved Windows sensors and exact local model tags."""
    _require_windows()
    if (
        (enable_event_logs and disable_event_logs)
        or (enable_etw and disable_etw)
        or (include_titles and disable_titles)
        or (enable_registry and disable_registry)
        or (enable_deep_inventory and disable_deep_inventory)
        or (enable_knowledge and disable_knowledge)
    ):
        raise typer.BadParameter("Do not enable and disable the same option in one call.")
    config = dict(DEFAULT_CONFIG) if reset else _load_config()
    if reset:
        config["ai_enabled"] = True
    if enable_event_logs:
        if importlib.util.find_spec("win32evtlog") is None:
            raise typer.BadParameter("Install the optional Windows dependencies before enabling Event Logs.")
        config["include_event_logs"] = True
    if disable_event_logs:
        config["include_event_logs"] = False
    if enable_etw:
        if importlib.util.find_spec("pyetwkit") is None:
            raise typer.BadParameter("Install the optional Windows dependencies before enabling ETW.")
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise typer.BadParameter("ETW selection requires an elevated token. Do not run the whole dashboard as administrator.")
        config["include_etw"] = True
    if disable_etw:
        config["include_etw"] = False
    if include_titles:
        config["include_window_titles"] = True
    if disable_titles:
        config["include_window_titles"] = False
    if disable_ai:
        config["ai_enabled"] = False
    if enable_registry:
        config["registry_enabled"] = True
    if disable_registry:
        config["registry_enabled"] = False
    if enable_deep_inventory:
        config["deep_inventory_enabled"] = True
    if disable_deep_inventory:
        config["deep_inventory_enabled"] = False
    if enable_knowledge:
        config["knowledge_enabled"] = True
    if disable_knowledge:
        config["knowledge_enabled"] = False
    if registry_interval is not None:
        config["registry_interval_seconds"] = registry_interval
    if deep_inventory_interval is not None:
        config["deep_inventory_interval_seconds"] = deep_inventory_interval
    if knowledge_interval is not None:
        config["knowledge_interval_seconds"] = knowledge_interval
    if fast_model:
        config["fast_model"] = fast_model.strip()
    if deep_model:
        config["deep_model"] = deep_model.strip()
    if analysis_interval is not None:
        config["analysis_interval_seconds"] = analysis_interval
    if ui_tree_apps is not None:
        names = [item.strip().casefold() for item in ui_tree_apps.split(",") if item.strip()]
        if names and importlib.util.find_spec("pywinauto") is None:
            raise typer.BadParameter("Install the optional Windows dependencies before enabling UIA.")
        if any("/" in item or "\\" in item for item in names):
            raise typer.BadParameter("UIA allowlist entries must be executable basenames, not file paths.")
        config["ui_tree_apps"] = names
    _save_config(config)
    console.print_json(json.dumps(config, indent=2))
    console.print("[yellow]Restart Sentinel to apply updated settings.[/yellow]")


@sentinel_app.command("worker")
def sentinel_worker() -> None:
    """Internal detached worker entry point."""
    try:
        _worker()
    except Exception as exc:  # noqa: BLE001
        console.print(f"Sentinel worker stopped: {type(exc).__name__}")
        raise typer.Exit(2) from exc


if __name__ == "__main__":
    sentinel_app()
