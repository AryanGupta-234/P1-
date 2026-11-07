import pytest

from apex.windows import wireless


GUID = "381b4222-f694-41f0-9685-ff5bb260df2e"


class FakeWlanSession:
    def __init__(self, *, hardware=wireless._DOT11_RADIO_ON, software=wireless._DOT11_RADIO_ON,
                 apply_changes=True):
        self.hardware = hardware
        self.software = software
        self.apply_changes = apply_changes
        self.calls = []
        self.closed = False

    def interfaces(self):
        return [{
            "interface_guid": GUID,
            "description": "Test Wireless Adapter",
            "interface_state": "connected",
        }]

    def radio(self, _guid):
        return [{
            "phy_index": 0,
            "software_radio": self.software,
            "software_radio_name": wireless._radio_name(self.software),
            "hardware_radio": self.hardware,
            "hardware_radio_name": wireless._radio_name(self.hardware),
            "effective_radio_on": (
                self.software == wireless._DOT11_RADIO_ON
                and self.hardware == wireless._DOT11_RADIO_ON
            ),
        }]

    def set_software_radio(self, _guid, phy_index, enabled):
        self.calls.append((phy_index, enabled))
        if self.apply_changes:
            self.software = (wireless._DOT11_RADIO_ON if enabled else wireless._DOT11_RADIO_OFF)

    def close(self):
        self.closed = True


def test_wifi_guid_conversion_round_trips():
    assert wireless._guid_text(wireless._guid_from_text(GUID)) == GUID


def test_wifi_radio_name_handles_unknown_values():
    assert wireless._radio_name(wireless._DOT11_RADIO_ON) == "on"
    assert wireless._radio_name(wireless._DOT11_RADIO_OFF) == "off"
    assert wireless._radio_name(99) == "unknown_99"


def test_wifi_radio_switch_is_verified_and_returns_previous_state(monkeypatch):
    session = FakeWlanSession()
    monkeypatch.setattr(wireless, "_WlanSession", lambda: session)

    result = wireless.set_wireless_software_radio(GUID, False)

    assert result["verified"] is True
    assert result["previous_radios"][0]["software_radio_name"] == "on"
    assert result["radios"][0]["software_radio_name"] == "off"
    assert result["effective_radio_on"] is False
    assert session.calls == [(0, False)]
    assert session.closed is True


def test_wifi_radio_does_not_override_hardware_switch(monkeypatch):
    session = FakeWlanSession(hardware=wireless._DOT11_RADIO_OFF)
    monkeypatch.setattr(wireless, "_WlanSession", lambda: session)

    with pytest.raises(PermissionError, match="hardware radio switch is off"):
        wireless.set_wireless_software_radio(GUID, True)

    assert session.calls == []
    assert session.closed is True


def test_wifi_radio_attempts_rollback_when_postcondition_fails(monkeypatch):
    session = FakeWlanSession(apply_changes=False)
    monkeypatch.setattr(wireless, "_WlanSession", lambda: session)

    with pytest.raises(RuntimeError, match="postcondition"):
        wireless.set_wireless_software_radio(GUID, False)

    assert session.calls == [(0, False), (0, True)]
    assert session.closed is True


def test_wifi_radio_rejects_invalid_arguments(monkeypatch):
    session = FakeWlanSession()
    monkeypatch.setattr(wireless, "_WlanSession", lambda: session)

    with pytest.raises(ValueError):
        wireless.set_wireless_software_radio("not-a-guid", True)
    with pytest.raises(ValueError):
        wireless.set_wireless_software_radio(GUID, 1)
