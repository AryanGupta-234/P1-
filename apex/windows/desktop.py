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


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def _user32():
    if os.name != "nt":
        raise DesktopUnavailable("desktop input is available only on Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    user32.GetLastInputInfo.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD, ctypes.c_size_t]
    user32.mouse_event.restype = None
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    user32.keybd_event.restype = None
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
    user32.GetGUIThreadInfo.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    return user32


def _last_input_tick() -> int | None:
    if os.name != "nt":
        return None
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not _user32().GetLastInputInfo(ctypes.byref(info)):
        return None
    return int(info.dwTime)


def reset_interaction_lease() -> None:
    """Capture the user's last-input timestamp at the beginning of a host request."""
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


def _require_foreground(user32, hwnd: int) -> tuple[int, int, int, int]:
    if isinstance(hwnd, bool) or not isinstance(hwnd, int) or hwnd <= 0:
        raise ValueError("a valid target window handle is required")
    handle = wintypes.HWND(hwnd)
    if not user32.IsWindow(handle) or not user32.IsWindowVisible(handle):
        raise ValueError("target window no longer exists or is not visible")
    foreground = user32.GetForegroundWindow()
    if int(foreground or 0) != hwnd:
        raise UserInterrupted("Target window is not foreground; APEX will not take over the desktop.")
    pid = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(handle, ctypes.byref(pid)) or not pid.value:
        raise ValueError("could not resolve the target window's process identity")
    try:
        import psutil
        process = psutil.Process(pid.value)
        process_name = process.name() or ""
        _created_at = process.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        raise UserInterrupted("Target process exited or its identity cannot be verified.") from exc
    protected = {
        "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe",
        "lsass.exe", "winlogon.exe", "dwm.exe", "fontdrvhost.exe", "secure system",
        "riotclientservices.exe", "riotclientux.exe", "vgc.exe", "vgtray.exe",
        "easyanticheat.exe", "easyanticheat_eos.exe", "battleye.exe", "faceitclient.exe",
    }
    lowered = process_name.casefold()
    if lowered in protected or lowered.startswith(("vg", "easyanticheat", "battleye", "faceit")):
        raise PermissionError("Protected Windows, security or anti-cheat windows cannot receive APEX input.")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        raise OSError(ctypes.get_last_error(), "could not resolve target window bounds")
    return rect.left, rect.top, rect.right, rect.bottom


def _target(hwnd: int):
    user32 = _user32()
    bounds = _require_foreground(user32, hwnd)
    _check_interaction_lease()
    return user32, bounds


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
    flags = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010),
             "middle": (0x0020, 0x0040)}
    down, up = flags[button]
    _check_interaction_lease()
    if not user32.SetCursorPos(x, y):
        raise OSError(ctypes.get_last_error(), "Windows rejected pointer positioning")
    pressed = False
    try:
        for _ in range(count):
            _check_interaction_lease()
            if int(user32.GetForegroundWindow() or 0) != hwnd:
                raise UserInterrupted("Foreground window changed during click.")
            user32.mouse_event(down, 0, 0, 0, 0)
            pressed = True
            user32.mouse_event(up, 0, 0, 0, 0)
            pressed = False
            _refresh_interaction_lease()
    finally:
        if pressed:
            user32.mouse_event(up, 0, 0, 0, 0)
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
    sent: list[str] = []
    try:
        for key in normalized:
            _check_interaction_lease()
            user32.keybd_event(_VIRTUAL_KEYS[key], 0, 0, 0)
            sent.append(key)
        for key in reversed(normalized):
            user32.keybd_event(_VIRTUAL_KEYS[key], 0, 0x0002, 0)
            sent.pop()
    finally:
        for key in reversed(sent):
            user32.keybd_event(_VIRTUAL_KEYS[key], 0, 0x0002, 0)
    if int(user32.GetForegroundWindow() or 0) != hwnd:
        raise UserInterrupted("Foreground window changed during keyboard input.")
    _refresh_interaction_lease()
    return {"summary": f"Dispatched hotkey {'+'.join(normalized)}.", "hwnd": hwnd,
            "keys": normalized, "verified": False}


def _focused_control_is_safe(hwnd: int) -> None:
    user32 = _user32()
    thread_id = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) or not info.hwndFocus:
        raise UserInterrupted("Could not identify the focused control; text entry is disabled.")
    root = user32.GetAncestor(info.hwndFocus, 2)  # GA_ROOT
    if int(root or 0) != hwnd:
        raise UserInterrupted("Focused control does not belong to the verified target window.")
    try:
        from pywinauto import Desktop
        focused = Desktop(backend="uia").window(handle=int(info.hwndFocus)).wrapper_object()
        element = focused.element_info
        if bool(getattr(element, "is_password", False)):
            raise PermissionError("APEX never types into a password control.")
        if str(getattr(element, "control_type", "")) not in {"Edit", "ComboBox"}:
            raise PermissionError("Text entry is restricted to verified Edit or ComboBox controls.")
        if not bool(getattr(element, "enabled", True)) or not bool(getattr(element, "visible", True)):
            raise UserInterrupted("Focused control is not enabled and visible.")
    except ImportError as exc:
        raise DesktopUnavailable("UI Automation is required to verify the focused control before text entry.") from exc


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


def type_text(hwnd: int, text: str) -> dict:
    """Type text only into a verified focused, non-password UIA control."""
    if not isinstance(text, str) or not 1 <= len(text) <= 2000:
        raise ValueError("text must contain between 1 and 2000 characters")
    if "\x00" in text:
        raise ValueError("NUL characters are not valid text input")
    user32, _bounds = _target(hwnd)
    _focused_control_is_safe(hwnd)
    sent_units = 0
    for offset in range(0, len(text), 12):
        _check_interaction_lease()
        if int(user32.GetForegroundWindow() or 0) != hwnd:
            raise UserInterrupted("Foreground window changed during text entry.")
        _focused_control_is_safe(hwnd)
        chunk = text[offset:offset + 12]
        events: list[INPUT] = []
        for char in chunk:
            code = ord(char)
            if code <= 0xFFFF:
                units = [code]
            else:
                adjusted = code - 0x10000
                units = [0xD800 + (adjusted >> 10), 0xDC00 + (adjusted & 0x3FF)]
            for unit in units:
                events.append(INPUT(type=1, union=_INPUT_UNION(ki=KEYBDINPUT(0, unit, 0x0004, 0, 0))))
                events.append(INPUT(type=1, union=_INPUT_UNION(ki=KEYBDINPUT(0, unit, 0x0004 | 0x0002, 0, 0))))
        array = (INPUT * len(events))(*events)
        written = user32.SendInput(len(events), ctypes.cast(array, ctypes.c_void_p), ctypes.sizeof(INPUT))
        if written != len(events):
            raise OSError(ctypes.get_last_error(), "Windows did not accept the complete text-entry batch")
        sent_units += len(chunk)
        _refresh_interaction_lease()
    return {"summary": f"Typed {sent_units} characters into the verified focused control.",
            "hwnd": hwnd, "characters": sent_units, "verified": False,
            "verification": "Text-input events were dispatched; application acceptance is not independently verified."}
