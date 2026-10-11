"""Read-only foreground-window observations for Windows.

Window titles are omitted by default because they can contain document names,
private chats, email subjects or other user content. Enabling titles is an
explicit opt-in and marks the resulting event as sensitive.
"""
from __future__ import annotations

import os
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
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return "unknown"


class WindowsForegroundProvider:
    """Emit an event only when the foreground application/window identity changes."""

    name = "windows.foreground"

    def __init__(
        self,
        *,
        api: ForegroundApi | None = None,
        process_lookup: Callable[[int], str] = _process_name,
        include_window_titles: bool = False,
    ) -> None:
        if api is None:
            api = _Win32ForegroundApi()
        self._api = api
        self._process_lookup = process_lookup
        self._include_window_titles = include_window_titles
        self._last_fingerprint: tuple[int, int, str, str, str | None] | None = None

    def collect_snapshot(self) -> Iterator[AIEEvent]:
        """Return a single derived foreground transition, without capturing screen pixels."""
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
        except (OSError, ValueError, TypeError):
            return

        fingerprint = (handle, pid, process_name, window_class, title)
        if fingerprint == self._last_fingerprint:
            return
        self._last_fingerprint = fingerprint

        data = {
            "pid": pid,
            "process_name": process_name,
            "window_class": window_class,
            "window_title_collected": self._include_window_titles,
        }
        if title is not None:
            data["window_title"] = title

        yield AIEEvent(
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
        )
