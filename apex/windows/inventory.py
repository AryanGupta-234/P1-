"""Read-only Windows inventory providers with explicit platform checks."""
from __future__ import annotations
import os
import platform
from datetime import datetime, timezone
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
        "observed_at": datetime.now(timezone.utc).isoformat(), "source": "APEX/psutil"}

def list_processes(limit: int = 100) -> dict[str, Any]:
    _require_windows()
    import psutil
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    rows = []
    for proc in psutil.process_iter(attrs=["pid", "name", "exe", "memory_info", "cpu_percent", "create_time"]):
        try:
            info = proc.info
            memory = info.get("memory_info")
            rows.append({"pid": info.get("pid"), "name": info.get("name"), "executable": info.get("exe"),
                "memory_rss_bytes": getattr(memory, "rss", None), "cpu_percent_sample": info.get("cpu_percent"),
                "created_at": info.get("create_time")})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if len(rows) >= limit:
            break
    return {"processes": rows, "count": len(rows), "limit": limit,
            "observed_at": datetime.now(timezone.utc).isoformat(), "source": "APEX/psutil"}

def list_windows(limit: int = 100, *, include_titles: bool = False) -> dict[str, Any]:
    _require_windows()
    import ctypes
    from ctypes import wintypes
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
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
            "window_titles_collected": bool(include_titles), "source": "APEX/Win32 EnumWindows"}
