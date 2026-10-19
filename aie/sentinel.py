"""Persistent Windows Sentinel background worker and lifecycle commands."""
from __future__ import annotations

import ctypes
import importlib.util
import json
import os
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
    if not isinstance(config["analysis_interval_seconds"], int) or not 60 <= config["analysis_interval_seconds"] <= 3600:
        raise RuntimeError("analysis_interval_seconds must be between 60 and 3600.")
    if not isinstance(config["ui_tree_apps"], list) or any(not isinstance(item, str) for item in config["ui_tree_apps"]):
        raise RuntimeError("ui_tree_apps must be a list of executable names.")
    for key in (
        "include_network", "include_foreground", "include_process_resources",
        "include_event_logs", "include_etw", "include_window_titles", "ai_enabled",
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
        nonlocal next_analysis, last_count_update, last_cycle_event, next_inventory, ai_thread, inventory_thread
        now_mono = time.monotonic()
        with state_lock:
            state["status"] = "running"
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

        if now_mono >= next_inventory and inventory_lock.acquire(blocking=False):
            next_inventory = now_mono + 900.0
            inventory_thread = threading.Thread(
                target=update_inventory,
                name="aie-sentinel-windows-inventory",
                daemon=True,
            )
            inventory_thread.start()

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
) -> None:
    """Configure approved Windows sensors and exact local model tags."""
    _require_windows()
    if (enable_event_logs and disable_event_logs) or (enable_etw and disable_etw) or (include_titles and disable_titles):
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
