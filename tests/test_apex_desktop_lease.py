import pytest
from apex.windows import desktop

def test_interaction_lease_aborts_when_last_input_changes(monkeypatch):
    ticks = iter([100, 101])
    monkeypatch.setattr(desktop.os, "name", "nt")
    monkeypatch.setattr(desktop, "_last_input_tick", lambda: next(ticks))
    desktop.reset_interaction_lease()
    with pytest.raises(desktop.UserInterrupted):
        desktop._check_interaction_lease()

def test_interaction_lease_fails_closed_when_input_timestamp_unavailable(monkeypatch):
    monkeypatch.setattr(desktop.os, "name", "nt")
    monkeypatch.setattr(desktop, "_last_input_tick", lambda: None)
    desktop.reset_interaction_lease()
    with pytest.raises(desktop.UserInterrupted):
        desktop._check_interaction_lease()

def test_non_windows_lease_fails_closed_without_loading_user32(monkeypatch):
    monkeypatch.setattr(desktop.os, "name", "posix")
    desktop.reset_interaction_lease()
    with pytest.raises(desktop.DesktopUnavailable):
        desktop._check_interaction_lease()
