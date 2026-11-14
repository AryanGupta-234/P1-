"""Semantic UI Automation via pywinauto; sensitive/document content is never read."""
from __future__ import annotations

import os
import time


class UIAutomationUnavailable(RuntimeError):
    pass


_SAFE_INSPECTION_TYPES = {
    "Button", "CheckBox", "RadioButton", "ToggleButton", "ComboBox", "Tab", "TabItem",
    "Menu", "MenuItem", "Hyperlink", "Tree", "TreeItem", "Slider", "Spinner",
    "ToolBar", "Window", "Pane", "Group", "ScrollBar",
}
_CONTROL_TYPES = {
    "invoke": {"Button", "MenuItem", "Hyperlink", "TabItem", "TreeItem", "SplitButton"},
    "set_value": {"Edit", "ComboBox", "Spinner"},
    "select": {"ComboBox", "TabItem", "TreeItem"},
    "toggle": {"CheckBox", "RadioButton", "ToggleButton"},
    "expand_collapse": {"TreeItem", "ComboBox", "Pane", "Group"},
    "scroll": {"ScrollBar", "List", "ListView", "Pane", "Group"},
    "wait": _SAFE_INSPECTION_TYPES | {"Edit"},
}


def _window(hwnd: int):
    if os.name != "nt":
        raise UIAutomationUnavailable("Windows UI Automation requires Windows")
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise UIAutomationUnavailable("pywinauto is not installed") from exc
    if isinstance(hwnd, bool) or not isinstance(hwnd, int) or hwnd <= 0:
        raise ValueError("a valid window handle is required")
    window = Desktop(backend="uia").window(handle=hwnd)
    if not window.exists(timeout=1.0):
        raise ValueError("target window does not exist")
    return window


def _resolve(window, *, operation: str, automation_id: str | None = None,
             name: str | None = None):
    if bool(automation_id) == bool(name):
        raise ValueError("provide exactly one of automation_id or name")
    allowed = _CONTROL_TYPES[operation]
    matches = []
    for control in window.descendants()[:1000]:
        try:
            info = control.element_info
            if str(info.control_type or "") not in allowed:
                continue
            if bool(getattr(info, "is_password", False)):
                continue
            if automation_id and info.automation_id == automation_id:
                matches.append(control)
            elif name and info.name == name:
                matches.append(control)
        except Exception:
            continue
    if len(matches) != 1:
        raise ValueError("UIA target was not found uniquely within the allowed control types")
    return matches[0]


def inspect_tree(hwnd: int, limit: int = 100) -> dict:
    if isinstance(limit, bool) or not 1 <= limit <= 300:
        raise ValueError("limit must be between 1 and 300")
    window = _window(hwnd)
    rows = []
    for control in window.descendants()[: min(limit * 3, 900)]:
        if len(rows) >= limit:
            break
        try:
            info = control.element_info
            password = bool(getattr(info, "is_password", False))
            control_type = str(info.control_type or "")
            if password or control_type not in _SAFE_INSPECTION_TYPES:
                continue
            rows.append({"name": str(info.name or "")[:120],
                         "automation_id": str(info.automation_id or "")[:120],
                         "control_type": control_type, "enabled": bool(info.enabled),
                         "visible": bool(info.visible)})
        except Exception:
            continue
    return {"hwnd": hwnd, "controls": rows, "count": len(rows),
            "source": "Windows UI Automation; text/document/list contents excluded"}


def invoke(hwnd: int, *, automation_id: str | None = None, name: str | None = None) -> dict:
    control = _resolve(_window(hwnd), operation="invoke", automation_id=automation_id, name=name)
    info = control.element_info
    control.iface_invoke.Invoke()
    return {"summary": f"Invoked UIA control '{str(info.name or '')[:120]}'.", "hwnd": hwnd,
            "automation_id": info.automation_id, "verified": False}


def set_value(hwnd: int, value: str, *, automation_id: str | None = None,
              name: str | None = None) -> dict:
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("value must be a string of at most 2000 characters")
    control = _resolve(_window(hwnd), operation="set_value", automation_id=automation_id, name=name)
    info = control.element_info
    if bool(getattr(info, "is_password", False)):
        raise PermissionError("password controls are never populated")
    control.iface_value.SetValue(value)
    if control.iface_value.CurrentValue != value:
        raise RuntimeError("UIA value verification did not match the requested text")
    return {"summary": f"Set value on UIA control '{str(info.name or '')[:120]}'.", "hwnd": hwnd,
            "automation_id": info.automation_id, "verified": True}


def toggle(hwnd: int, *, automation_id: str | None = None, name: str | None = None) -> dict:
    control = _resolve(_window(hwnd), operation="toggle", automation_id=automation_id, name=name)
    info = control.element_info
    control.iface_toggle.Toggle()
    return {"summary": f"Toggled UIA control '{str(info.name or '')[:120]}'.", "hwnd": hwnd,
            "automation_id": info.automation_id, "verified": False}


def provider_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import pywinauto  # noqa: F401
        return True
    except ImportError:
        return False


def select(hwnd: int, *, automation_id: str | None = None, name: str | None = None) -> dict:
    control = _resolve(_window(hwnd), operation="select", automation_id=automation_id, name=name)
    info = control.element_info
    control.iface_selection_item.Select()
    return {"summary": f"Selected UIA control '{str(info.name or '')[:120]}'.", "hwnd": hwnd,
            "automation_id": info.automation_id, "verified": False}


def expand_collapse(hwnd: int, expanded: bool, *, automation_id: str | None = None,
                    name: str | None = None) -> dict:
    if not isinstance(expanded, bool):
        raise ValueError("expanded must be a boolean")
    control = _resolve(_window(hwnd), operation="expand_collapse",
                       automation_id=automation_id, name=name)
    info = control.element_info
    pattern = control.iface_expand_collapse
    pattern.Expand() if expanded else pattern.Collapse()
    observed = int(pattern.CurrentExpandCollapseState)
    if observed != (1 if expanded else 0):
        raise RuntimeError("UIA expand/collapse postcondition failed")
    return {"summary": f"UIA control '{str(info.name or '')[:120]}' is {'expanded' if expanded else 'collapsed'}.",
            "hwnd": hwnd, "automation_id": info.automation_id, "verified": True}


def scroll_container(hwnd: int, axis: str, direction: str, *, automation_id: str | None = None,
                     name: str | None = None) -> dict:
    if axis not in {"horizontal", "vertical"} or direction not in {"forward", "backward"}:
        raise ValueError("axis/direction is invalid")
    control = _resolve(_window(hwnd), operation="scroll", automation_id=automation_id, name=name)
    info = control.element_info
    pattern = control.iface_scroll
    no_amount = 2
    small_increment = 4
    small_decrement = 1
    horizontal = (small_increment if direction == "forward" else small_decrement) if axis == "horizontal" else no_amount
    vertical = (small_increment if direction == "forward" else small_decrement) if axis == "vertical" else no_amount
    pattern.Scroll(horizontal, vertical)
    return {"summary": f"Scrolled {axis} container {direction}.", "hwnd": hwnd,
            "automation_id": info.automation_id, "verified": False}



def wait_for_control(hwnd: int, timeout_seconds: float = 5.0, *,
                     automation_id: str | None = None, name: str | None = None) -> dict:
    """Wait a bounded time for a unique, visible, enabled semantic control.

    Control values and document/list contents are never read by this operation.
    """
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be a number")
    if not 0.1 <= timeout_seconds <= 10.0:
        raise ValueError("timeout_seconds must be between 0.1 and 10 seconds")
    if bool(automation_id) == bool(name):
        raise ValueError("provide exactly one of automation_id or name")

    window = _window(hwnd)
    deadline = time.monotonic() + float(timeout_seconds)
    while True:
        matches = []
        for control in window.descendants()[:1000]:
            try:
                info = control.element_info
                if str(info.control_type or "") not in _CONTROL_TYPES["wait"]:
                    continue
                if bool(getattr(info, "is_password", False)):
                    continue
                if automation_id and info.automation_id == automation_id:
                    matches.append(control)
                elif name and info.name == name:
                    matches.append(control)
            except Exception:
                continue

        if len(matches) > 1:
            raise ValueError("UIA wait target matched more than one allowed control")
        if matches:
            info = matches[0].element_info
            if bool(info.visible) and bool(info.enabled):
                return {
                    "summary": f"UIA control '{str(info.name or '')[:120]}' is visible and enabled.",
                    "hwnd": hwnd,
                    "name": str(info.name or "")[:120],
                    "automation_id": str(info.automation_id or "")[:120],
                    "control_type": str(info.control_type or ""),
                    "verified": True,
                }

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("UIA control did not become visible and enabled before the timeout")
        time.sleep(min(0.1, remaining))
