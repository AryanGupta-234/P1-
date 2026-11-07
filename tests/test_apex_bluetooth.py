from enum import IntEnum

import pytest

from apex.windows import bluetooth


class RadioKind(IntEnum):
    BLUETOOTH = 1
    WIFI = 2


class RadioState(IntEnum):
    UNKNOWN = 0
    ON = 1
    OFF = 2
    DISABLED = 3


class RadioAccessStatus(IntEnum):
    ALLOWED = 0
    DENIED_BY_USER = 1
    DENIED_BY_SYSTEM = 2


class FakeRadio:
    def __init__(self, name="Bluetooth Radio", state=RadioState.OFF,
                 *, accepts_state=True, hardware_disabled=False):
        self.name = name
        self.kind = RadioKind.BLUETOOTH
        self.state = state
        self.accepts_state = accepts_state
        self.hardware_disabled = hardware_disabled
        self.set_calls = []

    async def set_state_async(self, desired):
        self.set_calls.append(desired)
        if self.accepts_state and not (self.hardware_disabled and desired == RadioState.ON):
            self.state = desired
            return RadioAccessStatus.ALLOWED
        return RadioAccessStatus.ALLOWED


class FakeRadioAPI:
    radios = []
    access = RadioAccessStatus.ALLOWED

    @classmethod
    async def get_radios_async(cls):
        return cls.radios

    @classmethod
    async def request_access_async(cls):
        return cls.access


def install_fake(monkeypatch, radios):
    FakeRadioAPI.radios = radios
    FakeRadioAPI.access = RadioAccessStatus.ALLOWED
    monkeypatch.setattr(
        bluetooth,
        "_winrt",
        lambda: (FakeRadioAPI, RadioAccessStatus, RadioKind, RadioState),
    )


def test_list_bluetooth_radios_is_read_only_and_reports_state(monkeypatch):
    radio = FakeRadio(state=RadioState.ON)
    install_fake(monkeypatch, [radio])

    result = bluetooth.list_bluetooth_radios()

    assert result["count"] == 1
    assert result["radios"][0]["name"] == "Bluetooth Radio"
    assert result["radios"][0]["state"] == "on"
    assert radio.set_calls == []


def test_bluetooth_toggle_checks_access_and_verifies_state(monkeypatch):
    radio = FakeRadio(state=RadioState.OFF)
    install_fake(monkeypatch, [radio])

    result = bluetooth.set_bluetooth_radio("Bluetooth Radio", True)

    assert result["previous_state"] == "off"
    assert result["state"] == "on"
    assert result["verified"] is True
    assert result["compensation"]["restore_state"] == "off"
    assert radio.set_calls == [RadioState.ON]


def test_bluetooth_toggle_rejects_disabled_hardware_radio(monkeypatch):
    radio = FakeRadio(state=RadioState.DISABLED)
    install_fake(monkeypatch, [radio])

    with pytest.raises(PermissionError, match="disabled"):
        bluetooth.set_bluetooth_radio("Bluetooth Radio", True)

    assert radio.set_calls == []


def test_bluetooth_toggle_requires_windows_radio_access(monkeypatch):
    radio = FakeRadio()
    install_fake(monkeypatch, [radio])
    FakeRadioAPI.access = RadioAccessStatus.DENIED_BY_USER

    with pytest.raises(PermissionError, match="denied"):
        bluetooth.set_bluetooth_radio("Bluetooth Radio", True)

    assert radio.set_calls == []


def test_bluetooth_toggle_rejects_ambiguous_radio_names(monkeypatch):
    install_fake(monkeypatch, [FakeRadio(), FakeRadio()])

    with pytest.raises(LookupError, match="ambiguous"):
        bluetooth.set_bluetooth_radio("Bluetooth Radio", True)


def test_bluetooth_sync_api_rejects_running_event_loop():
    import asyncio

    async def invoke():
        with pytest.raises(RuntimeError, match="active asyncio event loop"):
            bluetooth.set_bluetooth_radio("Bluetooth Radio", True)

    asyncio.run(invoke())


def test_bluetooth_toggle_validates_input(monkeypatch):
    install_fake(monkeypatch, [FakeRadio()])
    with pytest.raises(ValueError):
        bluetooth.set_bluetooth_radio("", True)
    with pytest.raises(ValueError):
        bluetooth.set_bluetooth_radio("Bluetooth Radio", "on")
