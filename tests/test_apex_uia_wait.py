from types import SimpleNamespace

import pytest

from apex.windows import uia


class FakeWindow:
    def __init__(self, controls):
        self._controls = controls

    def descendants(self):
        return self._controls


def control(*, name="Save", automation_id="saveButton", control_type="Button",
            visible=True, enabled=True, is_password=False):
    return SimpleNamespace(element_info=SimpleNamespace(
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        visible=visible,
        enabled=enabled,
        is_password=is_password,
    ))


def test_wait_for_control_returns_only_safe_target_metadata(monkeypatch):
    target = control()
    monkeypatch.setattr(uia, "_window", lambda _hwnd: FakeWindow([target]))

    result = uia.wait_for_control(42, automation_id="saveButton", timeout_seconds=1.0)

    assert result["verified"] is True
    assert result["name"] == "Save"
    assert result["automation_id"] == "saveButton"
    assert result["control_type"] == "Button"
    assert "value" not in result


def test_wait_for_control_rejects_ambiguous_matches(monkeypatch):
    monkeypatch.setattr(uia, "_window", lambda _hwnd: FakeWindow([
        control(), control(name="Save copy", automation_id="saveButton"),
    ]))

    with pytest.raises(ValueError, match="more than one"):
        uia.wait_for_control(42, automation_id="saveButton", timeout_seconds=1.0)


def test_wait_for_control_rejects_password_controls(monkeypatch):
    monkeypatch.setattr(uia, "_window", lambda _hwnd: FakeWindow([
        control(control_type="Edit", is_password=True),
    ]))

    with pytest.raises(TimeoutError):
        uia.wait_for_control(42, automation_id="saveButton", timeout_seconds=0.1)


@pytest.mark.parametrize("timeout", [0, -1, 10.1, True, "5"])
def test_wait_for_control_rejects_invalid_timeout(monkeypatch, timeout):
    with pytest.raises(ValueError):
        uia.wait_for_control(42, automation_id="saveButton", timeout_seconds=timeout)
