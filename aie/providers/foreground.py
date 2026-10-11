"""Read-only foreground-window and active-process observations for Windows.

Window titles are omitted by default because they can contain document names,
private chats, email subjects or other user content. Enabling titles is an
explicit opt-in and marks the resulting event as sensitive.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from typing import Protocol

import psutil

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id


class ForegroundApi(Protocol):
    """Small Win32 API surface for dependency-injected tests."""

    def foreground_window(self) -> int | None: ...
    def process_id(self, hwnd: int) -> int: ...
    def window_class(self, hwnd: int) -> str: ...
    def window_title(self, hwnd: int) -> str: ...


class _Win32ForegroundApi:
    """Thin ctypes adapter around documented user32 foreground-window functions."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Foreground-window observation requires native Windows.")

        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.GetClassNameW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self._user32.GetClassNameW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self._user32.GetWindowTextW.restype = ctypes.c_int

    def foreground_window(self) -> int | None:
        handle = self._user32.GetForegroundWindow()
        return int(handle) if handle else None

    def process_id(self, hwnd: int) -> int:
        process_id = self._wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(
            self._wintypes.HWND(hwnd),
            self._ctypes.byref(process_id),
        )
        return int(process_id.value)

    def window_class(self, hwnd: int) -> str:
        buffer = self._ctypes.create_unicode_buffer(256)
        self._user32.GetClassNameW(self._wintypes.HWND(hwnd), buffer, len(buffer))
        return buffer.value

    def window_title(self, hwnd: int) -> str:
        buffer = self._ctypes.create_unicode_buffer(512)
        self._user32.GetWindowTextW(self._wintypes.HWND(hwnd), buffer, len(buffer))
        return buffer.value


def _process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except (psutil.Error, OSError):
        return "unknown"


class WindowsForegroundProvider:
    """Emit foreground transitions and periodic read-only active-process metrics."""

    name = "windows.foreground"

    def __init__(
        self,
        *,
        api: ForegroundApi | None = None,
        process_lookup: Callable[[int], str] = _process_name,
        process_factory: Callable[[int], psutil.Process] = psutil.Process,
        include_window_titles: bool = False,
        resource_sample_interval: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if api is None:
            api = _Win32ForegroundApi()
        if not 1.0 <= resource_sample_interval <= 60.0:
            raise ValueError("resource_sample_interval must be between 1 and 60 seconds")

        self._api = api
        self._process_lookup = process_lookup
        self._process_factory = process_factory
        self._include_window_titles = include_window_titles
        self._resource_sample_interval = resource_sample_interval
        self._clock = clock
        self._last_fingerprint: tuple[int, int, str, str, str | None] | None = None
        self._active_process: psutil.Process | None = None
        self._active_process_identity: tuple[int, float] | None = None
        self._last_resource_sample = float("-inf")

    def _sample_active_process(
        self,
        *,
        pid: int,
        process_name: str,
        hwnd: int,
    ) -> AIEEvent | None:
        now = self._clock()
        if now - self._last_resource_sample < self._resource_sample_interval:
            return None
        self._last_resource_sample = now

        try:
            if self._active_process is None or self._active_process_identity is None:
                process = self._process_factory(pid)
                create_time = float(process.create_time())
                process.cpu_percent(interval=None)  # Prime the per-process CPU counter.
                self._active_process = process
                self._active_process_identity = (pid, create_time)
                cpu_pct = None
            else:
                process = self._active_process
                create_time = float(process.create_time())
                if self._active_process_identity != (pid, create_time):
                    process = self._process_factory(pid)
                    create_time = float(process.create_time())
                    process.cpu_percent(interval=None)
                    self._active_process = process
                    self._active_process_identity = (pid, create_time)
                    cpu_pct = None
                else:
                    cpu_value = process.cpu_percent(interval=None)
                    cpu_pct = float(cpu_value) if cpu_value is not None else None

            try:
                memory_rss_bytes = int(process.memory_info().rss)
            except (psutil.Error, OSError, AttributeError):
                memory_rss_bytes = None
            try:
                thread_count = int(process.num_threads())
            except (psutil.Error, OSError, AttributeError):
                thread_count = None
            try:
                io = process.io_counters()
                io_read_bytes = int(io.read_bytes)
                io_write_bytes = int(io.write_bytes)
            except (psutil.Error, OSError, AttributeError):
                io_read_bytes = None
                io_write_bytes = None
        except (psutil.Error, OSError, ValueError, TypeError):
            self._active_process = None
            self._active_process_identity = None
            return None

        return AIEEvent(
            host_id=host_id(),
            source=self.name,
            event_type="process.foreground_resource_sample",
            entity=EntityRef(
                type="process",
                name=process_name,
                stable_id=f"{pid}:{create_time:.3f}",
            ),
            data={
                "pid": pid,
                "process_name": process_name,
                "create_time": create_time,
                "foreground_window_handle": hwnd,
                "cpu_pct": cpu_pct,
                "memory_rss_bytes": memory_rss_bytes,
                "thread_count": thread_count,
                "io_read_bytes": io_read_bytes,
                "io_write_bytes": io_write_bytes,
            },
            sensitivity="internal",
            confidence=0.9,
            evidence_kind="observed",
        )

    def collect_snapshot(self) -> Iterator[AIEEvent]:
        """Emit changed foreground identity and bounded periodic process metrics."""
        hwnd = self._api.foreground_window()
        if not hwnd:
            return

        try:
            handle = int(hwnd)
            pid = int(self._api.process_id(handle))
            if pid <= 0:
                return
            process_name = self._process_lookup(pid) or "unknown"
            window_class = self._api.window_class(handle) or "unknown"
            title = self._api.window_title(handle) if self._include_window_titles else None
        except (psutil.Error, OSError, ValueError, TypeError):
            return

        fingerprint = (handle, pid, process_name, window_class, title)
        events: list[AIEEvent] = []
        if fingerprint != self._last_fingerprint:
            self._last_fingerprint = fingerprint
            data = {
                "pid": pid,
                "process_name": process_name,
                "window_class": window_class,
                "window_title_collected": self._include_window_titles,
            }
            if title is not None:
                data["window_title"] = title

            events.append(AIEEvent(
                host_id=host_id(),
                source=self.name,
                event_type="window.foreground_changed",
                entity=EntityRef(
                    type="application_window",
                    name=process_name,
                    stable_id=str(handle),
                ),
                data=data,
                sensitivity="sensitive" if self._include_window_titles else "internal",
                confidence=1.0,
                evidence_kind="observed",
            ))

        resource_event = self._sample_active_process(
            pid=pid,
            process_name=process_name,
            hwnd=handle,
        )
        if resource_event is not None:
            events.append(resource_event)

        yield from events
