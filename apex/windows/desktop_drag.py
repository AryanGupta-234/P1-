"""Short, bounded drag/drop gestures scoped to one verified foreground window."""
from __future__ import annotations

import os
import time

from apex.windows import desktop


def drag_drop(hwnd: int, start_x: int, start_y: int, end_x: int, end_y: int,
              *, steps: int = 8, interval_ms: int = 12) -> dict:
    if os.name != "nt":
        raise OSError("desktop drag/drop requires Windows")
    values = (start_x, start_y, end_x, end_y)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("drag coordinates must be integers")
    if isinstance(steps, bool) or not 2 <= steps <= 20:
        raise ValueError("drag steps must be between 2 and 20")
    if isinstance(interval_ms, bool) or not 0 <= interval_ms <= 30:
        raise ValueError("drag interval must be between 0 and 30 ms")
    user32 = desktop._user32()
    bounds = desktop._require_foreground(user32, hwnd)
    for x, y in ((start_x, start_y), (end_x, end_y)):
        desktop._point(bounds, x, y)
    desktop._check_interaction_lease()
    if not user32.SetCursorPos(start_x, start_y):
        raise OSError("Windows rejected drag start positioning")
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    try:
        for index in range(1, steps + 1):
            desktop._check_interaction_lease()
            if int(user32.GetForegroundWindow() or 0) != hwnd:
                raise desktop.UserInterrupted("Foreground changed during drag/drop.")
            x = round(start_x + (end_x - start_x) * index / steps)
            y = round(start_y + (end_y - start_y) * index / steps)
            if not user32.SetCursorPos(x, y):
                raise OSError("Windows rejected drag movement")
            if interval_ms:
                time.sleep(interval_ms / 1000.0)
    finally:
        # Always release the left button, even after cancellation or foreground change.
        user32.mouse_event(0x0004, 0, 0, 0, 0)
    if int(user32.GetForegroundWindow() or 0) != hwnd:
        raise desktop.UserInterrupted("Foreground changed after drag/drop.")
    desktop._refresh_interaction_lease()
    return {"summary": "Dispatched a bounded drag/drop gesture.", "hwnd": hwnd,
            "start": [start_x, start_y], "end": [end_x, end_y],
            "button_released": True, "verified": False,
            "verification": "Input was dispatched; application drop acceptance must be verified separately."}
