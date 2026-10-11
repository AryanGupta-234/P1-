"""Read-only Windows UI Automation (UIA) metadata inspection.

This module never reads control names, captions, text, values, passwords, or document
contents. It does not invoke UIA control patterns or send mouse/keyboard input.
"""
from __future__ import annotations

import os
from typing import Any


class UIAUnavailable(RuntimeError):
    """Raised when the native Windows UIA inspection backend cannot be used."""


def _safe_get(info: Any, attribute: str) -> Any:
    try:
        return getattr(info, attribute)
    except Exception:
        return None


def _safe_string(value: Any, limit: int = 128) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:limit]


def element_metadata(info: Any, depth: int = 0) -> dict[str, Any]:
    """Convert a UIA element to a privacy-minimized metadata record.

    Deliberately does not access the 'name' or 'rich_text' properties because those
    properties may contain document content, account identifiers, or private messages.
    """
    handle = _safe_get(info, "handle")
    process_id = _safe_get(info, "process_id")
    return {
        "depth": depth,
        "handle": int(handle) if isinstance(handle, int) and handle > 0 else None,
        "process_id": (
            int(process_id)
            if isinstance(process_id, int) and process_id > 0
            else None
        ),
        "control_type": _safe_string(_safe_get(info, "control_type")),
        "class_name": _safe_string(_safe_get(info, "class_name")),
        "automation_id": _safe_string(_safe_get(info, "automation_id")),
        "framework_id": _safe_string(_safe_get(info, "framework_id")),
        "enabled": _safe_get(info, "enabled"),
        "visible": _safe_get(info, "visible"),
    }


def _validate_limits(max_depth: int, max_nodes: int) -> None:
    if not 0 <= max_depth <= 8:
        raise ValueError("max_depth must be between 0 and 8")
    if not 1 <= max_nodes <= 1000:
        raise ValueError("max_nodes must be between 1 and 1000")


def walk_element_tree(
    root: Any,
    *,
    max_depth: int = 3,
    max_nodes: int = 150,
) -> dict[str, Any]:
    """Walk a wrapper tree with strict output depth and node-count limits.

    Root and child objects are pywinauto wrappers. This function is separated from
    backend loading so traversal and privacy behavior can be unit-tested.
    """
    _validate_limits(max_depth, max_nodes)
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    stack: list[tuple[Any, int]] = [(root, 0)]
    truncated = False

    while stack and len(records) < max_nodes:
        wrapper, depth = stack.pop()
        info = _safe_get(wrapper, "element_info")
        if info is None:
            info = wrapper
        record = element_metadata(info, depth)
        records.append(record)

        if depth >= max_depth:
            continue

        try:
            children = wrapper.children()
        except Exception as exc:
            errors.append({"depth": depth, "error_type": type(exc).__name__})
            continue

        remaining = max_nodes - len(records) - len(stack)
        if len(children) > remaining:
            children = children[:max(0, remaining)]
            truncated = True
        for child in reversed(children):
            stack.append((child, depth + 1))

    if stack:
        truncated = True

    return {
        "elements": records,
        "element_count": len(records),
        "truncated": truncated,
        "traversal_errors": errors,
    }


def _desktop() -> Any:
    if os.name != "nt":
        raise UIAUnavailable("UI Automation inspection requires native Windows.")
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise UIAUnavailable(
            'Install the optional UIA extra with: python -m pip install -e ".[windows-ui]"'
        ) from exc
    try:
        return Desktop(backend="uia")
    except Exception as exc:
        raise UIAUnavailable(
            f"Windows UI Automation backend could not initialize ({type(exc).__name__})."
        ) from exc


def list_top_level_windows(max_windows: int = 100) -> list[dict[str, Any]]:
    """List visible top-level window metadata without reading window titles."""
    if not 1 <= max_windows <= 500:
        raise ValueError("max_windows must be between 1 and 500")
    desktop = _desktop()
    try:
        windows = desktop.windows(visible_only=True)
    except Exception as exc:
        raise UIAUnavailable(
            f"Could not enumerate top-level UIA windows ({type(exc).__name__})."
        ) from exc

    records = []
    for window in windows[:max_windows]:
        info = _safe_get(window, "element_info")
        if info is None:
            continue
        records.append(element_metadata(info))
    return records


def inspect_window(
    handle: int,
    *,
    max_depth: int = 3,
    max_nodes: int = 150,
) -> dict[str, Any]:
    """Inspect one explicitly selected window by HWND; metadata only."""
    if not isinstance(handle, int) or handle <= 0:
        raise ValueError("handle must be a positive integer")
    _validate_limits(max_depth, max_nodes)
    desktop = _desktop()
    try:
        wrapper = desktop.window(handle=handle).wrapper_object()
    except Exception as exc:
        raise UIAUnavailable(
            f"Could not attach to window handle {handle} ({type(exc).__name__})."
        ) from exc

    result = walk_element_tree(wrapper, max_depth=max_depth, max_nodes=max_nodes)
    info = _safe_get(wrapper, "element_info")
    result["target"] = element_metadata(info if info is not None else wrapper)
    result["privacy"] = {
        "text_values_collected": False,
        "window_titles_collected": False,
        "actions_invoked": False,
    }
    return result
