import pytest

import aie.desktop.tray as tray
from aie.desktop.tray import TrayActions, TrayStatus, WindowsObserverTray


def test_tray_actions_pause_resume_are_idempotent():
    state = {"paused": False}
    actions = TrayActions(
        is_paused=lambda: state["paused"],
        set_paused=lambda value: state.__setitem__("paused", value),
        event_count=lambda: 42,
    )

    assert actions.pause() is True
    assert actions.pause() is False
    assert actions.status() == TrayStatus(paused=True, event_count=42)
    assert actions.resume() is True
    assert actions.resume() is False
    assert actions.status().paused is False


def test_tray_status_rejects_invalid_event_counts():
    actions = TrayActions(
        is_paused=lambda: False,
        set_paused=lambda value: None,
        event_count=lambda: -1,
    )
    with pytest.raises(ValueError, match="non-negative integer"):
        actions.status()


def test_native_tray_refuses_non_windows_platform(monkeypatch):
    monkeypatch.setattr(tray.os, "name", "posix")
    actions = TrayActions(
        is_paused=lambda: False,
        set_paused=lambda value: None,
        event_count=lambda: 0,
    )
    with pytest.raises(RuntimeError, match="Windows-only"):
        WindowsObserverTray(actions)
