"""Read-only Windows inventory providers with explicit platform checks."""
from __future__ import annotations

import ctypes
import os
import platform
from datetime import datetime, timezone
from ctypes import wintypes
from typing import Any


class WindowsUnavailable(RuntimeError):
    pass


def _require_windows() -> None:
    if os.name != "nt":
        raise WindowsUnavailable("This provider requires Windows 11.")


def system_summary() -> dict[str, Any]:
    _require_windows()
    import psutil
    return {"os": platform.platform(), "windows_version": platform.version(),
        "machine": platform.machine(), "processor": platform.processor(),
        "cpu_logical_count": psutil.cpu_count(logical=True),
        "memory_total_bytes": psutil.virtual_memory().total,
        "memory_available_bytes": psutil.virtual_memory().available,
        "observed_at": datetime.now(timezone.utc).isoformat(), "source": "SENTI/psutil"}


_SENTI_ENGINE_NAMES = {"ollama.exe", "ollama app.exe", "llama-server.exe"}


def _is_senti_component(name: str, pid: int | None, own_pid: int) -> bool:
    """SENTI's own runtime and local model engine (so it never advises closing itself)."""
    return pid == own_pid or str(name).casefold() in _SENTI_ENGINE_NAMES


def list_processes(limit: int = 15, sort_by: str = "memory", *, sample_seconds: float = 0.5) -> dict[str, Any]:
    """Top live processes by memory or CPU, plus per-application totals and system memory.

    CPU percentages come from a real short sample (two readings ``sample_seconds`` apart),
    not the meaningless first-call value of 0.0. Rows are compact to keep model context small.
    """
    _require_windows()
    import time

    import psutil
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if sort_by not in {"memory", "cpu", "name"}:
        raise ValueError("sort_by must be memory, cpu or name")
    procs = []
    for proc in psutil.process_iter(attrs=["pid", "name", "memory_info"]):
        try:
            if proc.info.get("pid") == 0:  # System Idle Process is idle time, not a consumer
                continue
            proc.cpu_percent(None)
            procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if sort_by == "cpu":
        time.sleep(max(0.1, min(sample_seconds, 2.0)))
    cores = psutil.cpu_count() or 1
    own_pid = os.getpid()
    rows = []
    for proc in procs:
        try:
            info = proc.info
            memory = info.get("memory_info")
            cpu = proc.cpu_percent(None) / cores if sort_by == "cpu" else None
            name = info.get("name") or "(system)"
            rows.append({"pid": info.get("pid"), "name": name,
                         "memory_mb": round(getattr(memory, "rss", 0) / 1_048_576, 1),
                         **({"senti_component": True} if _is_senti_component(name, info.get("pid"), own_pid) else {}),
                         **({"cpu_percent": round(cpu, 1)} if cpu is not None else {})})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    key = {"memory": lambda r: -r["memory_mb"], "cpu": lambda r: -(r.get("cpu_percent") or 0),
           "name": lambda r: str(r["name"]).casefold()}[sort_by]
    rows.sort(key=key)
    apps: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = apps.setdefault(row["name"], {"name": row["name"], "processes": 0, "memory_mb": 0.0,
                                              **({"senti_component": True} if row.get("senti_component") else {}),
                                              **({"cpu_percent": 0.0} if sort_by == "cpu" else {})})
        entry["processes"] += 1
        entry["memory_mb"] = round(entry["memory_mb"] + row["memory_mb"], 1)
        if sort_by == "cpu":
            entry["cpu_percent"] = round(entry["cpu_percent"] + (row.get("cpu_percent") or 0), 1)
    app_key = (lambda a: -(a.get("cpu_percent") or 0)) if sort_by == "cpu" else (lambda a: -a["memory_mb"])
    top_apps = sorted(apps.values(), key=app_key)[:min(limit, 10)]
    vm = psutil.virtual_memory()
    system = {"total_gb": round(vm.total / 1_073_741_824, 1), "used_percent": vm.percent,
              "available_gb": round(vm.available / 1_073_741_824, 1)}
    lead = top_apps[0] if top_apps else None
    summary = (f"{len(rows)} processes; RAM {system['used_percent']}% used, {system['available_gb']} GB free. "
               + (f"Largest by {sort_by}: {lead['name']} ({lead['processes']} processes, "
                  f"{lead['memory_mb']} MB)." if lead else ""))
    return {"summary": summary, "system_memory": system,
            "note": "Entries marked senti_component are SENTI's own runtime/model engine; closing them stops SENTI.", "top_applications": top_apps,
            "processes": rows[:min(limit, 8)], "count": len(rows), "sorted_by": sort_by,
            "observed_at": datetime.now(timezone.utc).isoformat(), "source": "SENTI/psutil", "verified": True}


def list_windows(limit: int = 100, *, include_titles: bool = False) -> dict[str, Any]:
    _require_windows()
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    rows: list[dict[str, Any]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        if len(rows) >= limit:
            return False
        if not user32.IsWindowVisible(hwnd):
            return True
        title_value = ""
        if include_titles:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                title = ctypes.create_unicode_buffer(min(length + 1, 1024))
                user32.GetWindowTextW(hwnd, title, len(title))
                title_value = title.value[:1024]
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rows.append({"hwnd": int(hwnd), "pid": int(pid.value), "title": title_value})
        return True

    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows(callback_type(callback), 0)
    return {"windows": rows, "count": len(rows), "observed_at": datetime.now(timezone.utc).isoformat(),
            "window_titles_collected": bool(include_titles), "source": "SENTI/Win32 EnumWindows"}
