"""Semantic UI Automation via pywinauto; secret fields are never read or populated."""
from __future__ import annotations
import os

class UIAutomationUnavailable(RuntimeError):
    pass

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

def _resolve(window, *, automation_id: str | None = None, name: str | None = None):
    if bool(automation_id) == bool(name):
        raise ValueError("provide exactly one of automation_id or name")
    matches = []
    for control in window.descendants()[:1000]:
        try:
            info = control.element_info
            if automation_id and info.automation_id == automation_id:
                matches.append(control)
            elif name and info.name == name:
                matches.append(control)
        except Exception:
            continue
    if len(matches) != 1:
        raise ValueError("UIA target was not found uniquely; specify a unique automation_id or exact name")
    return matches[0]

def inspect_tree(hwnd: int, limit: int = 100) -> dict:
    if isinstance(limit, bool) or not 1 <= limit <= 300:
        raise ValueError("limit must be between 1 and 300")
    window = _window(hwnd)
    rows = []
    for control in window.descendants()[:limit]:
        try:
            info = control.element_info
            password = bool(getattr(info, "is_password", False))
            control_type = str(info.control_type or "")
            safe_name = "" if password or control_type in {"Edit", "Document"} else str(info.name or "")[:160]
            rows.append({"name": safe_name, "automation_id": str(info.automation_id or "")[:120],
                         "control_type": control_type, "enabled": bool(info.enabled),
                         "visible": bool(info.visible), "password": password})
        except Exception:
            continue
    return {"hwnd": hwnd, "controls": rows, "count": len(rows), "source": "Windows UI Automation"}

def invoke(hwnd: int, *, automation_id: str | None = None, name: str | None = None) -> dict:
    control = _resolve(_window(hwnd), automation_id=automation_id, name=name)
    info = control.element_info
    if bool(getattr(info, "is_password", False)):
        raise PermissionError("password controls are never automated")
    control.iface_invoke.Invoke()
    return {"summary": f"Invoked UIA control '{info.name[:120]}'.", "hwnd": hwnd,
            "automation_id": info.automation_id, "verified": False}

def set_value(hwnd: int, value: str, *, automation_id: str | None = None, name: str | None = None) -> dict:
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("value must be a string of at most 2000 characters")
    control = _resolve(_window(hwnd), automation_id=automation_id, name=name)
    info = control.element_info
    if bool(getattr(info, "is_password", False)):
        raise PermissionError("password controls are never populated")
    control.iface_value.SetValue(value)
    if control.iface_value.CurrentValue != value:
        raise RuntimeError("UIA value verification did not match the requested text")
    return {"summary": f"Set value on UIA control '{info.name[:120]}'.", "hwnd": hwnd,
            "automation_id": info.automation_id, "verified": True}

def toggle(hwnd: int, *, automation_id: str | None = None, name: str | None = None) -> dict:
    control = _resolve(_window(hwnd), automation_id=automation_id, name=name)
    info = control.element_info
    if bool(getattr(info, "is_password", False)):
        raise PermissionError("password controls are never automated")
    control.iface_toggle.Toggle()
    return {"summary": f"Toggled UIA control '{info.name[:120]}'.", "hwnd": hwnd,
            "automation_id": info.automation_id, "verified": False}

def provider_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import pywinauto
        return True
    except ImportError:
        return False

def select(hwnd: int, *, automation_id: str | None = None, name: str | None = None) -> dict:
    control = _resolve(_window(hwnd), automation_id=automation_id, name=name)
    info = control.element_info
    if bool(getattr(info, "is_password", False)):
        raise PermissionError("password controls are never automated")
    control.iface_selection_item.Select()
    return {"summary": f"Selected UIA control '{info.name[:120]}'.", "hwnd": hwnd,
            "automation_id": info.automation_id, "verified": False}

def expand_collapse(hwnd: int, expanded: bool, *, automation_id: str | None = None,
                    name: str | None = None) -> dict:
    if not isinstance(expanded, bool):
        raise ValueError("expanded must be a boolean")
    control = _resolve(_window(hwnd), automation_id=automation_id, name=name)
    info = control.element_info
    if bool(getattr(info, "is_password", False)):
        raise PermissionError("password controls are never automated")
    pattern = control.iface_expand_collapse
    pattern.Expand() if expanded else pattern.Collapse()
    observed = int(pattern.CurrentExpandCollapseState)
    if observed != (1 if expanded else 0):
        raise RuntimeError("UIA expand/collapse postcondition failed")
    return {"summary": f"UIA control '{info.name[:120]}' is {'expanded' if expanded else 'collapsed'}.",
            "hwnd": hwnd, "automation_id": info.automation_id, "verified": True}

def scroll_container(hwnd: int, axis: str, direction: str, *, automation_id: str | None = None,
                     name: str | None = None) -> dict:
    if axis not in {"horizontal", "vertical"} or direction not in {"forward", "backward"}:
        raise ValueError("axis/direction is invalid")
    control = _resolve(_window(hwnd), automation_id=automation_id, name=name)
    info = control.element_info
    if bool(getattr(info, "is_password", False)):
        raise PermissionError("password controls are never automated")
    increment = 4 if direction == "forward" else 0
    control.iface_scroll.Scroll(increment if axis == "horizontal" else 2,
                                increment if axis == "vertical" else 2)
    return {"summary": f"Scrolled {axis} container {direction}.", "hwnd": hwnd,
            "automation_id": info.automation_id, "verified": False}
