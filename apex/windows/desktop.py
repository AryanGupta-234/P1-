"""Bounded Win32 input operations scoped to a verified foreground window."""
from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes


class UserInterrupted(RuntimeError):
    """User activity changed desktop ownership during an APEX input request."""


class DesktopUnavailable(RuntimeError):
    pass


_lease_lock = threading.Lock()
_lease_last_input: int | None = None


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def _user32():
    if os.name != "nt":
        raise DesktopUnavailable("desktop input is available only on Windows")
    return ctypes.WinDLL("user32", use_last_error=True)


def _last_input_tick() -> int | None:
    if os.name != "nt":
        return None
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not _user32().GetLastInputInfo(ctypes.byref(info)):
        return None
    return int(info.dwTime)


def reset_interaction_lease() -> None:
    """Capture the user's current input timestamp at the beginning of a request."""
    global _lease_last_input
    current = _last_input_tick()
    with _lease_lock:
        _lease_last_input = current


def _check_interaction_lease() -> None:
    if os.name != "nt":
        raise DesktopUnavailable("desktop input is available only on Windows")
    current = _last_input_tick()
    with _lease_lock:
        baseline = _lease_last_input
    if current is None or baseline is None:
        raise UserInterrupted("Cannot verify desktop ownership; input injection is disabled.")
    if current != baseline:
        raise UserInterrupted("User input detected; APEX released desktop control.")


def _refresh_interaction_lease() -> None:
    global _lease_last_input
    current = _last_input_tick()
    with _lease_lock:
        _lease_last_input = current


def _target(hwnd: int):
    user32 = _user32()
    if isinstance(hwnd, bool) or not isinstance(hwnd, int) or hwnd <= 0:
        raise ValueError("a valid target window handle is required")
    handle = wintypes.HWND(hwnd)
    if not user32.IsWindow(handle) or not user32.IsWindowVisible(handle):
        raise ValueError("target window no longer exists or is not visible")
    if int(user32.GetForegroundWindow() or 0) != hwnd:
        raise UserInterrupted("Target window is not foreground; APEX will not take over the desktop.")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        raise OSError(ctypes.get_last_error(), "could not resolve target window bounds")
    _check_interaction_lease()
    return user32, (rect.left, rect.top, rect.right, rect.bottom)


def _point(bounds: tuple[int, int, int, int], x: int, y: int) -> None:
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (x, y)):
        raise ValueError("screen coordinates must be integers")
    left, top, right, bottom = bounds
    if not (left <= x < right and top <= y < bottom):
        raise ValueError("input point must be inside the verified target window")


def move_pointer(hwnd: int, x: int, y: int) -> dict:
    user32, bounds = _target(hwnd)
    _point(bounds, x, y)
    _check_interaction_lease()
    if not user32.SetCursorPos(x, y):
        raise OSError(ctypes.get_last_error(), "Windows rejected pointer movement")
    _refresh_interaction_lease()
    return {"summary": "Moved pointer within the verified target window.", "hwnd": hwnd,
            "x": x, "y": y, "verified": False}


def click(hwnd: int, x: int, y: int, button: str = "left", *, count: int = 1) -> dict:
    user32, bounds = _target(hwnd)
    _point(bounds, x, y)
    if button not in {"left", "right", "middle"} or isinstance(count, bool) or count not in {1, 2}:
        raise ValueError("button/count is invalid")
    flags = {
        "left": (0x0002, 0x0004), "right": (0x0008, 0x0010),
        "middle": (0x0020, 0x0040),
    }
    down, up = flags[button]
    _check_interaction_lease()
    if not user32.SetCursorPos(x, y):
        raise OSError(ctypes.get_last_error(), "Windows rejected pointer positioning")
    sent = 0
    try:
        for _ in range(count):
            user32.mouse_event(down, 0, 0, 0, 0)
            sent += 1
            user32.mouse_event(up, 0, 0, 0, 0)
            sent = 0
    finally:
        if sent:
            user32.mouse_event(up, 0, 0, 0, 0)
    if int(user32.GetForegroundWindow() or 0) != hwnd:
        raise UserInterrupted("Foreground window changed during click.")
    _refresh_interaction_lease()
    return {"summary": f"Dispatched {button} {'double-click' if count == 2 else 'click'}.",
            "hwnd": hwnd, "x": x, "y": y, "button": button, "count": count,
            "verified": False, "verification": "Input dispatch does not prove the application acted."}


def scroll(hwnd: int, amount: int, axis: str = "vertical", *, x: int | None = None,
           y: int | None = None) -> dict:
    user32, bounds = _target(hwnd)
    if x is None or y is None:
        raise ValueError("scroll requires an explicit point inside the target window")
    _point(bounds, x, y)
    if isinstance(amount, bool) or not isinstance(amount, int) or not -20 <= amount <= 20 or amount == 0:
        raise ValueError("scroll amount must be a non-zero integer from -20 through 20")
    if axis not in {"vertical", "horizontal"}:
        raise ValueError("axis must be vertical or horizontal")
    _check_interaction_lease()
    if not user32.SetCursorPos(x, y):
        raise OSError(ctypes.get_last_error(), "Windows rejected scroll positioning")
    flag = 0x0800 if axis == "vertical" else 0x1000
    user32.mouse_event(flag, 0, 0, amount * 120, 0)
    _refresh_interaction_lease()
    return {"summary": f"Dispatched {axis} scroll.", "hwnd": hwnd, "x": x, "y": y,
            "axis": axis, "amount": amount, "verified": False}


_VIRTUAL_KEYS = {
    "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "home": 0x24, "end": 0x23, "page_up": 0x21, "page_down": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
    **{str(i): ord(str(i)) for i in range(10)},
}


def press_hotkey(hwnd: int, keys: list[str]) -> dict:
    user32, _bounds = _target(hwnd)
    if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
        raise ValueError("keys must contain one to four named keys")
    normalized = [key.strip().lower() for key in keys if isinstance(key, str)]
    if len(normalized) != len(keys) or any(key not in _VIRTUAL_KEYS for key in normalized):
        raise ValueError("hotkey contains an unsupported key")
    if len(set(normalized)) != len(normalized):
        raise ValueError("hotkey keys must be unique")
    _check_interaction_lease()
    sent = []
    try:
        for key in normalized:
            user32.keybd_event(_VIRTUAL_KEYS[key], 0, 0, 0)
            sent.append(key)
        for key in reversed(normalized):
            user32.keybd_event(_VIRTUAL_KEYS[key], 0x0002, 0, 0)
            sent.pop()
    finally:
        for key in reversed(sent):
            user32.keybd_event(_VIRTUAL_KEYS[key], 0x0002, 0, 0)
    if int(user32.GetForegroundWindow() or 0) != hwnd:
        raise UserInterrupted("Foreground window changed during keyboard input.")
    _refresh_interaction_lease()
    return {"summary": f"Dispatched hotkey {'+'.join(normalized)}.", "hwnd": hwnd,
            "keys": normalized, "verified": False}
