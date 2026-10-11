"""Minimal Windows notification-area controller for observer lifecycle controls."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from ctypes import wintypes
from typing import Callable

WM_DESTROY = 0x0002
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_LBUTTONDBLCLK = 0x0203
WM_USER = 0x0400
WM_TRAY_CALLBACK = WM_USER + 41
WM_CLOSE = 0x0010

NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
MB_OK = 0x00000000
MB_ICONINFORMATION = 0x00000040
IDI_APPLICATION = 32512

MENU_PAUSE = 1001
MENU_RESUME = 1002
MENU_STATUS = 1003
MENU_EXIT = 1004

_WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
WNDPROC = _WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
)


class _NotifyUnion(ctypes.Union):
    _fields_ = [("uTimeout", wintypes.UINT), ("uVersion", wintypes.UINT)]


class _NotifyIconData(ctypes.Structure):
    _anonymous_ = ("timeout_version",)
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HANDLE),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("timeout_version", _NotifyUnion),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HANDLE),
    ]


class _WindowClass(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _Message(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", wintypes.DWORD),
        ("pt", _Point),
        ("lPrivate", wintypes.DWORD),
    ]


@dataclass(frozen=True, slots=True)
class TrayStatus:
    paused: bool
    event_count: int

    def render(self) -> str:
        state = "PAUSED" if self.paused else "RUNNING"
        return (
            f"P1- observer: {state}\n"
            f"Locally stored events: {self.event_count}\n\n"
            "The tray controller does not start observation. "
            "Use the CLI to start or configure providers."
        )


class TrayActions:
    """Small testable controller over the existing per-user observer pause marker."""

    def __init__(
        self,
        *,
        is_paused: Callable[[], bool],
        set_paused: Callable[[bool], None],
        event_count: Callable[[], int],
    ) -> None:
        self._is_paused = is_paused
        self._set_paused = set_paused
        self._event_count = event_count

    def pause(self) -> bool:
        if self._is_paused():
            return False
        self._set_paused(True)
        return True

    def resume(self) -> bool:
        if not self._is_paused():
            return False
        self._set_paused(False)
        return True

    def status(self) -> TrayStatus:
        count = self._event_count()
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("event_count callback must return a non-negative integer")
        return TrayStatus(paused=self._is_paused(), event_count=count)


class WindowsObserverTray:
    """A hidden Win32 window with a notification-area icon and pause controls."""

    def __init__(self, actions: TrayActions) -> None:
        if os.name != "nt":
            raise RuntimeError("the P1- notification-area controller is Windows-only")
        self.actions = actions
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._class_name = "P1ObserverTrayWindow"
        self._hwnd = None
        self._hinstance = None
        self._wndproc = WNDPROC(self._window_proc)
        self._icon_data = _NotifyIconData()

        self._configure_api()

    def _configure_api(self) -> None:
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

        self.user32.RegisterClassW.argtypes = [ctypes.POINTER(_WindowClass)]
        self.user32.RegisterClassW.restype = wintypes.ATOM
        self.user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        self.user32.CreateWindowExW.restype = wintypes.HWND
        self.user32.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t
        ]
        self.user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self.user32.GetMessageW.argtypes = [
            ctypes.POINTER(_Message), wintypes.HWND, wintypes.UINT, wintypes.UINT
        ]
        self.user32.GetMessageW.restype = ctypes.c_int
        self.user32.TranslateMessage.argtypes = [ctypes.POINTER(_Message)]
        self.user32.DispatchMessageW.argtypes = [ctypes.POINTER(_Message)]
        self.user32.PostQuitMessage.argtypes = [ctypes.c_int]
        self.user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        self.user32.LoadIconW.restype = wintypes.HANDLE
        self.user32.CreatePopupMenu.restype = wintypes.HMENU
        self.user32.AppendMenuW.argtypes = [
            wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR
        ]
        self.user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, wintypes.HWND, wintypes.LPVOID,
        ]
        self.user32.TrackPopupMenu.restype = wintypes.UINT
        self.user32.DestroyMenu.argtypes = [wintypes.HMENU]
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.MessageBoxW.argtypes = [
            wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT
        ]
        self.user32.DestroyWindow.argtypes = [wintypes.HWND]
        self.shell32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD, ctypes.POINTER(_NotifyIconData)
        ]
        self.shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    def _notify(self, operation: int) -> None:
        if not self.shell32.Shell_NotifyIconW(operation, ctypes.byref(self._icon_data)):
            raise ctypes.WinError(ctypes.get_last_error())

    def _create_window(self) -> None:
        self._hinstance = self.kernel32.GetModuleHandleW(None)
        window_class = _WindowClass()
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = self._hinstance
        window_class.hIcon = self.user32.LoadIconW(
            None, ctypes.cast(ctypes.c_void_p(IDI_APPLICATION), wintypes.LPCWSTR)
        )
        window_class.lpszClassName = self._class_name

        if not self.user32.RegisterClassW(ctypes.byref(window_class)):
            error = ctypes.get_last_error()
            if error != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                raise ctypes.WinError(error)

        self._hwnd = self.user32.CreateWindowExW(
            0,
            self._class_name,
            "P1- Observer Tray",
            0,
            0, 0, 0, 0,
            None, None, self._hinstance, None,
        )
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        self._icon_data.cbSize = ctypes.sizeof(_NotifyIconData)
        self._icon_data.hWnd = self._hwnd
        self._icon_data.uID = 1
        self._icon_data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self._icon_data.uCallbackMessage = WM_TRAY_CALLBACK
        self._icon_data.hIcon = self.user32.LoadIconW(
            None, ctypes.cast(ctypes.c_void_p(IDI_APPLICATION), wintypes.LPCWSTR)
        )
        self._icon_data.szTip = "P1- Observer Controls"
        self._notify(NIM_ADD)

    def _show_status(self) -> None:
        status = self.actions.status().render()
        self.user32.MessageBoxW(
            self._hwnd,
            status,
            "P1- Observer Status",
            MB_OK | MB_ICONINFORMATION,
        )

    def _show_menu(self) -> None:
        menu = self.user32.CreatePopupMenu()
        if not menu:
            return
        try:
            paused = self.actions.status().paused
            self.user32.AppendMenuW(
                menu,
                MF_STRING | (MF_GRAYED if paused else 0),
                MENU_PAUSE,
                "Pause observation",
            )
            self.user32.AppendMenuW(
                menu,
                MF_STRING | (0 if paused else MF_GRAYED),
                MENU_RESUME,
                "Resume observation",
            )
            self.user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            self.user32.AppendMenuW(menu, MF_STRING, MENU_STATUS, "Show status")
            self.user32.AppendMenuW(menu, MF_STRING, MENU_EXIT, "Exit tray")
            point = _Point()
            if self.user32.GetCursorPos(ctypes.byref(point)):
                self.user32.SetForegroundWindow(self._hwnd)
                command = self.user32.TrackPopupMenu(
                    menu,
                    TPM_RETURNCMD | TPM_RIGHTBUTTON,
                    point.x,
                    point.y,
                    0,
                    self._hwnd,
                    None,
                )
            else:
                command = 0
        finally:
            self.user32.DestroyMenu(menu)

        if command == MENU_PAUSE:
            changed = self.actions.pause()
            if changed:
                self._show_status()
        elif command == MENU_RESUME:
            changed = self.actions.resume()
            if changed:
                self._show_status()
        elif command == MENU_STATUS:
            self._show_status()
        elif command == MENU_EXIT:
            self.user32.DestroyWindow(self._hwnd)

    def _window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message == WM_TRAY_CALLBACK:
                if lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_menu()
                    return 0
                if lparam == WM_LBUTTONDBLCLK:
                    self._show_status()
                    return 0
            if message == WM_CLOSE:
                self.user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                try:
                    self._notify(NIM_DELETE)
                finally:
                    self.user32.PostQuitMessage(0)
                return 0
        except Exception:
            # Exceptions must never unwind through the native window procedure.
            return 0
        return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def run(self) -> int:
        """Run the Win32 message loop until the user selects Exit."""
        self._create_window()
        message = _Message()
        while True:
            result = self.user32.GetMessageW(ctypes.byref(message), self._hwnd, 0, 0)
            if result == -1:
                self._notify(NIM_DELETE)
                raise ctypes.WinError(ctypes.get_last_error())
            if result == 0:
                return int(message.wParam)
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))


def run_windows_tray() -> int:
    """Start the notification-area controller using P1-'s existing local stores."""
    from aie.config import (
        database_path,
        observer_is_paused,
        set_observer_paused,
    )
    from aie.store import EventStore

    actions = TrayActions(
        is_paused=observer_is_paused,
        set_paused=set_observer_paused,
        event_count=lambda: EventStore(database_path()).count(),
    )
    return WindowsObserverTray(actions).run()
