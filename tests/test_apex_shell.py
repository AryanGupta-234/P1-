import pytest

from apex.windows import shell


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("start_menu", ["win"]),
        ("quick_settings", ["win", "a"]),
        ("notification_center", ["win", "n"]),
        ("task_view", ["win", "tab"]),
        ("taskbar_cycle", ["win", "t"]),
        ("switch_window", ["alt", "tab"]),
        ("next_virtual_desktop", ["win", "ctrl", "right"]),
        ("previous_virtual_desktop", ["win", "ctrl", "left"]),
        ("create_virtual_desktop", ["win", "ctrl", "d"]),
        ("close_virtual_desktop", ["win", "ctrl", "f4"]),
    ],
)
def test_shell_action_dispatches_only_fixed_allowlisted_hotkeys(monkeypatch, action, expected):
    calls = []
    monkeypatch.setattr(shell.window_ops, "_resolve", lambda hwnd: (object(), 123, 1.0, "explorer.exe"))
    monkeypatch.setattr(
        shell.desktop, "press_hotkey",
        lambda hwnd, keys: calls.append((hwnd, keys)) or {"summary": "dispatched"},
    )

    result = shell.shell_action(55, action)

    assert calls == [(55, expected)]
    assert result["verified"] is False
    assert result["keys"] == expected


def test_shell_action_rejects_arbitrary_or_unknown_shortcut(monkeypatch):
    called = []
    monkeypatch.setattr(shell.window_ops, "_resolve", lambda _hwnd: called.append("resolved"))
    with pytest.raises(ValueError, match="unsupported shell action"):
        shell.shell_action(55, "powershell")
    assert called == []


def test_shell_action_validates_target_before_dispatch(monkeypatch):
    called = []
    monkeypatch.setattr(shell.window_ops, "_resolve", lambda _hwnd: (_ for _ in ()).throw(
        PermissionError("protected window")
    ))
    monkeypatch.setattr(shell.desktop, "press_hotkey", lambda *_args: called.append("dispatched"))

    with pytest.raises(PermissionError, match="protected"):
        shell.shell_action(55, "start_menu")
    assert called == []
