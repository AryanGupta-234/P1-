"""Allowlisted Windows 11 shell and virtual-desktop shortcuts."""
from __future__ import annotations

import os
from typing import Any

from senti.windows import desktop, window_ops

_ACTIONS: dict[str, tuple[str, ...]] = {
    "start_menu": ("win",),
    "quick_settings": ("win", "a"),
    "notification_center": ("win", "n"),
    "task_view": ("win", "tab"),
    "taskbar_cycle": ("win", "t"),
    "switch_window": ("alt", "tab"),
    "next_virtual_desktop": ("win", "ctrl", "right"),
    "previous_virtual_desktop": ("win", "ctrl", "left"),
    "create_virtual_desktop": ("win", "ctrl", "d"),
    "close_virtual_desktop": ("win", "ctrl", "f4"),
}


def shell_action(hwnd: int, action: str) -> dict[str, Any]:
    """Dispatch only a fixed, reviewed shell shortcut to the verified foreground window."""
    if action not in _ACTIONS:
        raise ValueError(f"unsupported shell action; choose one of: {', '.join(sorted(_ACTIONS))}")
    # Ensure the target is a visible, user-owned top-level window before input dispatch.
    window_ops._resolve(hwnd)
    result = desktop.press_hotkey(hwnd, list(_ACTIONS[action]))
    return {
        "summary": f"Dispatched Windows shell action '{action}'.",
        "action": action,
        "hwnd": hwnd,
        "keys": list(_ACTIONS[action]),
        "input_dispatched": True,
        "verified": False,
        "verification": "Windows shell state is not independently confirmed by the shortcut event.",
        **({"dispatch": result} if isinstance(result, dict) else {}),
    }


def provider_available() -> bool:
    return os.name == "nt" and desktop.provider_available()
