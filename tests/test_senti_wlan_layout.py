import ctypes

import pytest

from senti.windows import wireless


def test_wlan_radio_state_has_fixed_native_capacity_and_parses_valid_phy_entries():
    state = wireless._WLAN_RADIO_STATE()
    state.dwNumberOfPhys = 2
    state.PhyRadioState[0] = wireless._WLAN_PHY_RADIO_STATE(
        dwPhyIndex=0,
        dot11SoftwareRadioState=wireless._DOT11_RADIO_ON,
        dot11HardwareRadioState=wireless._DOT11_RADIO_ON,
    )
    state.PhyRadioState[1] = wireless._WLAN_PHY_RADIO_STATE(
        dwPhyIndex=2,
        dot11SoftwareRadioState=wireless._DOT11_RADIO_OFF,
        dot11HardwareRadioState=wireless._DOT11_RADIO_ON,
    )
    raw = ctypes.string_at(ctypes.byref(state), ctypes.sizeof(state))

    parsed = wireless._parse_radio_state_buffer(raw)

    assert ctypes.sizeof(wireless._WLAN_RADIO_STATE) == (
        ctypes.sizeof(ctypes.c_uint32) + wireless._MAX_PHYS * ctypes.sizeof(wireless._WLAN_PHY_RADIO_STATE)
    )
    assert [row["phy_index"] for row in parsed] == [0, 2]
    assert parsed[0]["effective_radio_on"] is True
    assert parsed[1]["software_radio_name"] == "off"
    assert parsed[1]["effective_radio_on"] is False


def test_wlan_radio_parser_rejects_short_or_excessive_phy_counts():
    with pytest.raises(ValueError, match="smaller"):
        wireless._parse_radio_state_buffer(b"\x00" * 16)

    state = wireless._WLAN_RADIO_STATE()
    state.dwNumberOfPhys = wireless._MAX_PHYS + 1
    raw = ctypes.string_at(ctypes.byref(state), ctypes.sizeof(state))
    with pytest.raises(ValueError, match="PHY count"):
        wireless._parse_radio_state_buffer(raw)
