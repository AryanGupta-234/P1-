"""Explicit, user-requested text clipboard access only; no background monitoring."""
from __future__ import annotations
import os

def _clipboard():
    if os.name != "nt":
        raise OSError("Windows clipboard provider is available only on Windows")
    try:
        import win32clipboard
        import win32con
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for clipboard operations") from exc
    return win32clipboard, win32con

def get_text() -> dict:
    clipboard, constants = _clipboard()
    clipboard.OpenClipboard()
    try:
        if not clipboard.IsClipboardFormatAvailable(constants.CF_UNICODETEXT):
            return {"text": "", "available": False, "verified": True}
        value = clipboard.GetClipboardData(constants.CF_UNICODETEXT)
        if not isinstance(value, str):
            raise RuntimeError("clipboard does not contain Unicode text")
        return {"text": value[:20_000], "available": True, "verified": True}
    finally:
        clipboard.CloseClipboard()

def set_text(value: str) -> dict:
    if not isinstance(value, str) or len(value) > 20_000:
        raise ValueError("clipboard text must contain at most 20000 characters")
    clipboard, constants = _clipboard()
    clipboard.OpenClipboard()
    try:
        clipboard.EmptyClipboard()
        clipboard.SetClipboardData(constants.CF_UNICODETEXT, value)
        observed = clipboard.GetClipboardData(constants.CF_UNICODETEXT)
        if observed != value:
            raise RuntimeError("clipboard text verification failed")
    finally:
        clipboard.CloseClipboard()
    return {"summary": "Updated the clipboard with the requested text.", "length": len(value), "verified": True}

def provider_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import win32clipboard
        return True
    except ImportError:
        return False
