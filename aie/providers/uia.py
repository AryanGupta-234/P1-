"""Opt-in structural UI Automation metadata for allowlisted Windows applications.

This provider deliberately does not read control names/text, values, passwords or
screenshots. It exports a bounded tree of control types, classes and geometry only.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import psutil

from aie.contracts import AIEEvent, EntityRef
from aie.providers.foreground import ForegroundApi, _Win32ForegroundApi
from aie.providers.windows import host_id


class UIATreeReader(Protocol):
    def read_tree(self, hwnd: int, *, max_nodes: int, max_depth: int) -> list[dict[str, Any]]:
        """Return structural metadata only; never return text or value patterns."""
        ...


class _PywinautoTreeReader:
    """Read a bounded UIA control tree without querying content-bearing properties."""

    def read_tree(self, hwnd: int, *, max_nodes: int, max_depth: int) -> list[dict[str, Any]]:
        from pywinauto import Desktop

        root = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
        queue: list[tuple[Any, int | None, int]] = [(root, None, 0)]
        nodes: list[dict[str, Any]] = []

        while queue and len(nodes) < max_nodes:
            wrapper, parent_index, depth = queue.pop(0)
            index = len(nodes)
            try:
                info = wrapper.element_info
                control_type = str(info.control_type or "unknown")[:64]
                class_name = str(info.class_name or "unknown")[:128]
                automation_id = str(info.automation_id or "")[:128]
                rect = wrapper.rectangle()
                rectangle = [
                    int(rect.left),
                    int(rect.top),
                    int(rect.right),
                    int(rect.bottom),
                ]
                visible = bool(wrapper.is_visible())
                enabled = bool(wrapper.is_enabled())
                try:
                    focusable = bool(info.is_keyboard_focusable)
                except (AttributeError, RuntimeError):
                    focusable = None
            except Exception:
                continue

            nodes.append({
                "index": index,
                "parent_index": parent_index,
                "depth": depth,
                "control_type": control_type,
                "class_name": class_name,
                "automation_id": automation_id,
                "rectangle": rectangle,
                "visible": visible,
                "enabled": enabled,
                "focusable": focusable,
            })

            if depth >= max_depth:
                continue
            try:
                children = wrapper.children()
            except Exception:
                continue
            for child in children:
                if len(queue) + len(nodes) >= max_nodes:
                    break
                queue.append((child, index, depth + 1))

        return nodes


def _process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except (psutil.Error, OSError):
        return "unknown"


class WindowsUIATreeProvider:
    """Emit structural UIA snapshots only for explicitly allowlisted foreground apps."""

    name = "windows.uia"

    def __init__(
        self,
        *,
        allowed_process_names: set[str] | frozenset[str],
        reader: UIATreeReader | None = None,
        api: ForegroundApi | None = None,
        process_lookup: Callable[[int], str] = _process_name,
        max_nodes: int = 80,
        max_depth: int = 5,
        sample_interval: float = 10.0,
        timeout_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if os.name != "nt":
            raise OSError("UI Automation observation requires native Windows.")
        names = {
            name.strip().casefold()
            for name in allowed_process_names
            if isinstance(name, str) and name.strip()
        }
        if not names:
            raise ValueError("UI Automation requires at least one explicitly allowlisted app.")
        if len(names) > 20:
            raise ValueError("At most 20 UI Automation apps may be allowlisted.")
        if not 1 <= max_nodes <= 200:
            raise ValueError("max_nodes must be between 1 and 200")
        if not 1 <= max_depth <= 8:
            raise ValueError("max_depth must be between 1 and 8")
        if not 2.0 <= sample_interval <= 300.0:
            raise ValueError("sample_interval must be between 2 and 300 seconds")
        if not 0.1 <= timeout_seconds <= 5.0:
            raise ValueError("timeout_seconds must be between 0.1 and 5 seconds")

        self.allowed_process_names = names
        self.reader = reader or _PywinautoTreeReader()
        self.api = api or _Win32ForegroundApi()
        self.process_lookup = process_lookup
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.sample_interval = sample_interval
        self.timeout_seconds = timeout_seconds
        self.clock = clock
        self._last_identity: tuple[int, int] | None = None
        self._last_sample_at = float("-inf")
        self._scan_lock = threading.Lock()

    @staticmethod
    def _sanitize_nodes(raw_nodes: list[dict[str, Any]], max_nodes: int) -> list[dict[str, Any]]:
        """Allow only structural fields; discard any accidental text/value payload."""
        sanitized: list[dict[str, Any]] = []
        allowed_types = {"index": int, "parent_index": (int, type(None)),
                         "depth": int, "control_type": str, "class_name": str,
                         "automation_id": str, "rectangle": list, "visible": bool,
                         "enabled": bool, "focusable": (bool, type(None))}
        for raw in raw_nodes[:max_nodes]:
            if not isinstance(raw, dict):
                continue
            node: dict[str, Any] = {}
            for key in ("index", "depth"):
                value = raw.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    node[key] = value
            parent = raw.get("parent_index")
            if parent is None or (isinstance(parent, int) and not isinstance(parent, bool)):
                node["parent_index"] = parent
            for key in ("control_type", "class_name", "automation_id"):
                value = raw.get(key)
                if isinstance(value, str):
                    node[key] = value[:128]
            rectangle = raw.get("rectangle")
            if (
                isinstance(rectangle, list)
                and len(rectangle) == 4
                and all(isinstance(item, int) and not isinstance(item, bool) for item in rectangle)
            ):
                node["rectangle"] = rectangle
            for key in ("visible", "enabled"):
                value = raw.get(key)
                if isinstance(value, bool):
                    node[key] = value
            focusable = raw.get("focusable")
            if focusable is None or isinstance(focusable, bool):
                node["focusable"] = focusable
            if "index" in node and "control_type" in node and "rectangle" in node:
                sanitized.append(node)
        return sanitized

    def _read_with_timeout(self, hwnd: int) -> list[dict[str, Any]] | None:
        """Bound the caller wait; a single-flight lock prevents stuck worker buildup."""
        if not self._scan_lock.acquire(blocking=False):
            return None
        completed = threading.Event()
        result: list[list[dict[str, Any]] | None] = [None]

        def worker() -> None:
            try:
                result[0] = self.reader.read_tree(
                    hwnd,
                    max_nodes=self.max_nodes,
                    max_depth=self.max_depth,
                )
            except Exception:
                result[0] = None
            finally:
                completed.set()
                self._scan_lock.release()

        thread = threading.Thread(target=worker, name="aie-uia-scan", daemon=True)
        try:
            thread.start()
        except RuntimeError:
            self._scan_lock.release()
            return None
        if not completed.wait(self.timeout_seconds):
            return None
        return result[0]

    def collect_snapshot(self) -> list[AIEEvent]:
        """Sample the current allowlisted foreground window on a bounded cadence."""
        hwnd = self.api.foreground_window()
        if not hwnd:
            return []
        try:
            handle = int(hwnd)
            pid = int(self.api.process_id(handle))
            if pid <= 0:
                return []
            process_name = self.process_lookup(pid) or "unknown"
        except (OSError, ValueError, TypeError):
            return []

        if process_name.casefold() not in self.allowed_process_names:
            return []

        identity = (handle, pid)
        now = self.clock()
        if identity == self._last_identity and now - self._last_sample_at < self.sample_interval:
            return []

        self._last_identity = identity
        self._last_sample_at = now
        nodes = self._read_with_timeout(handle)
        if nodes is None:
            return []
        sanitized = self._sanitize_nodes(nodes, self.max_nodes)
        if not sanitized:
            return []

        return [AIEEvent(
            host_id=host_id(),
            source=self.name,
            event_type="window.uia_tree_snapshot",
            entity=EntityRef(
                type="application_window",
                name=process_name,
                stable_id=str(handle),
            ),
            data={
                "pid": pid,
                "process_name": process_name,
                "node_count": len(sanitized),
                "max_nodes": self.max_nodes,
                "max_depth": self.max_depth,
                "text_collected": False,
                "screenshot_collected": False,
                "nodes": sanitized,
            },
            sensitivity="internal",
            confidence=0.95,
            evidence_kind="observed",
        )]
