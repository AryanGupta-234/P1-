"""Window-manager operations bound to verified, user-owned top-level windows."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

PROTECTED_PROCESS_NAMES = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe",
    "lsass.exe", "winlogon.exe", "dwm.exe", "fontdrvhost.exe", "secure system",
    "vgc.exe", "vgtray.exe", "riotclientservices.exe", "riotclientux.exe",
    "easyanticheat.exe", "easyanticheat_eos.exe", "battleye.exe", "faceitclient.exe",
}


def _user32():
    if os.name != "nt":
        raise OSError("window manager is available only on Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.IsZoomed.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    return user32


def _resolve(hwnd: int):
    user32 = _user32()
    if isinstance(hwnd, bool) or not isinstance(hwnd, int) or hwnd <= 0:
        raise ValueError("a valid window handle is required")
    handle = wintypes.HWND(hwnd)
    if not user32.IsWindow(handle) or not user32.IsWindowVisible(handle):
        raise ValueError("target window no longer exists or is not visible")
    pid = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(handle, ctypes.byref(pid)) or not pid.value:
        raise ValueError("could not resolve target window process identity")
    import psutil
    try:
        process = psutil.Process(pid.value)
        name, created = (process.name() or "").casefold(), process.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        raise ValueError("target process is no longer available or cannot be verified") from exc
    if name in PROTECTED_PROCESS_NAMES or name.startswith(("vg", "easyanticheat", "battleye", "faceit")):
        raise PermissionError("protected Windows or anti-cheat process windows cannot be managed by APEX")
    return user32, pid.value, created, name


def activate(hwnd: int) -> dict:
    user32, pid, created, name = _resolve(hwnd)
    if not user32.SetForegroundWindow(wintypes.HWND(hwnd)) or int(user32.GetForegroundWindow() or 0) != hwnd:
        raise PermissionError("Windows refused or failed to verify foreground activation")
    return {"summary": f"Activated window for {name}.", "hwnd": hwnd, "pid": pid,
            "process_created_at": created, "verified": True}


def show(hwnd: int, command: str) -> dict:
    user32, pid, created, name = _resolve(hwnd)
    commands = {"minimize": 6, "maximize": 3, "restore": 9}
    if command not in commands:
        raise ValueError("command must be minimize, maximize or restore")
    user32.ShowWindow(wintypes.HWND(hwnd), commands[command])
    verified = (bool(user32.IsIconic(hwnd)) if command == "minimize" else
                bool(user32.IsZoomed(hwnd)) if command == "maximize" else not bool(user32.IsIconic(hwnd)))
    if not verified:
        raise RuntimeError("window state did not reach the requested postcondition")
    return {"summary": f"Window {command} operation verified for {name}.", "hwnd": hwnd,
            "pid": pid, "process_created_at": created, "verified": True}


def move_resize(hwnd: int, x: int, y: int, width: int, height: int) -> dict:
    user32, pid, created, name = _resolve(hwnd)
    values = (x, y, width, height)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("window bounds must be integers")
    if not (-32768 <= x <= 32767 and -32768 <= y <= 32767 and 100 <= width <= 16384 and 100 <= height <= 16384):
        raise ValueError("window bounds are outside supported limits")
    if not user32.SetWindowPos(wintypes.HWND(hwnd), None, x, y, width, height, 0x0004 | 0x0010):
        raise OSError(ctypes.get_last_error(), "Windows rejected the move/resize request")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise OSError(ctypes.get_last_error(), "could not verify window bounds")
    verified = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top) == values
    if not verified:
        raise RuntimeError("window bounds did not match the requested dimensions")
    return {"summary": f"Moved/resized window for {name}.", "hwnd": hwnd, "pid": pid,
            "process_created_at": created, "verified": True}


def close(hwnd: int) -> dict:
    user32, pid, created, name = _resolve(hwnd)
    if not user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0):
        raise OSError(ctypes.get_last_error(), "Windows rejected the close request")
    return {"summary": f"Sent a graceful close request to {name}.", "hwnd": hwnd, "pid": pid,
            "process_created_at": created, "verified": False,
            "verification": "A close message was sent; process exit must be confirmed by a later inventory read."}


def provider_available() -> bool:
    return os.name == "nt"
