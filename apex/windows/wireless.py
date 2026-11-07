"""Native Windows WLAN radio inspection and software-radio control.

Hardware radio switches are read-only through this API. APEX only changes the
software radio state for one exact WLAN interface GUID.
"""
from __future__ import annotations

import ctypes
import os
import uuid
from datetime import datetime, timezone
from typing import Any

_WLAN_INTF_OPCODE_RADIO_STATE = 4
_DOT11_RADIO_UNKNOWN = 0
_DOT11_RADIO_ON = 1
_DOT11_RADIO_OFF = 2
_MAX_INTERFACES = 32
_MAX_PHYS = 64


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _WLAN_PHY_RADIO_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPhyIndex", ctypes.c_uint32),
        ("dot11SoftwareRadioState", ctypes.c_int),
        ("dot11HardwareRadioState", ctypes.c_int),
    ]


class _WLAN_RADIO_STATE(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfPhys", ctypes.c_uint32),
        ("PhyRadioState", _WLAN_PHY_RADIO_STATE * _MAX_PHYS),
    ]


class _WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", _GUID),
        ("strInterfaceDescription", ctypes.c_wchar * 256),
        ("isState", ctypes.c_int),
    ]


class _WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", ctypes.c_uint32),
        ("dwIndex", ctypes.c_uint32),
        ("InterfaceInfo", _WLAN_INTERFACE_INFO * 1),
    ]


_STATE_NAMES = {
    0: "not_ready",
    1: "connected",
    2: "ad_hoc_network_formed",
    3: "disconnecting",
    4: "disconnected",
    5: "associating",
    6: "discovering",
    7: "authenticating",
}


def _require_windows() -> None:
    if os.name != "nt":
        raise OSError("Native WLAN radio controls require Windows")


def _guid_from_text(value: str) -> _GUID:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("interface_guid must be a valid WLAN interface GUID") from exc
    result = _GUID()
    result.Data1 = parsed.time_low
    result.Data2 = parsed.time_mid
    result.Data3 = parsed.time_hi_version
    result.Data4[:] = parsed.bytes[8:]
    return result


def _guid_text(value: _GUID) -> str:
    raw = ctypes.string_at(ctypes.byref(value), ctypes.sizeof(_GUID))
    return str(uuid.UUID(bytes_le=raw))


def _api():
    _require_windows()
    dll = ctypes.WinDLL("wlanapi.dll", use_last_error=True)
    handle = ctypes.c_void_p
    dll.WlanOpenHandle.argtypes = [
        ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(handle),
    ]
    dll.WlanOpenHandle.restype = ctypes.c_uint32
    dll.WlanEnumInterfaces.argtypes = [
        handle, ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(_WLAN_INTERFACE_INFO_LIST)),
    ]
    dll.WlanEnumInterfaces.restype = ctypes.c_uint32
    dll.WlanQueryInterface.argtypes = [
        handle, ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    dll.WlanQueryInterface.restype = ctypes.c_uint32
    dll.WlanSetInterface.argtypes = [
        handle, ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_void_p,
    ]
    dll.WlanSetInterface.restype = ctypes.c_uint32
    dll.WlanFreeMemory.argtypes = [ctypes.c_void_p]
    dll.WlanFreeMemory.restype = None
    dll.WlanCloseHandle.argtypes = [handle, ctypes.c_void_p]
    dll.WlanCloseHandle.restype = ctypes.c_uint32
    return dll


class _WlanSession:
    def __init__(self):
        self.api = _api()
        self.handle = ctypes.c_void_p()
        negotiated = ctypes.c_uint32()
        code = self.api.WlanOpenHandle(2, None, ctypes.byref(negotiated), ctypes.byref(self.handle))
        self._check(code, "WlanOpenHandle")

    @staticmethod
    def _check(code: int, operation: str) -> None:
        if code != 0:
            raise OSError(code, f"{operation} failed with WLAN API error {code}")

    def close(self) -> None:
        if self.handle:
            self.api.WlanCloseHandle(self.handle, None)
            self.handle = ctypes.c_void_p()

    def interfaces(self) -> list[dict[str, Any]]:
        pointer = ctypes.POINTER(_WLAN_INTERFACE_INFO_LIST)()
        self._check(self.api.WlanEnumInterfaces(self.handle, None, ctypes.byref(pointer)),
                    "WlanEnumInterfaces")
        try:
            count = int(pointer.contents.dwNumberOfItems)
            if count > _MAX_INTERFACES:
                raise RuntimeError("WLAN interface count exceeded the safety bound")
            rows = []
            base = ctypes.addressof(pointer.contents.InterfaceInfo)
            stride = ctypes.sizeof(_WLAN_INTERFACE_INFO)
            for index in range(count):
                item = _WLAN_INTERFACE_INFO.from_address(base + index * stride)
                rows.append({
                    "interface_guid": _guid_text(item.InterfaceGuid),
                    "description": str(item.strInterfaceDescription or "")[:240],
                    "interface_state": _STATE_NAMES.get(int(item.isState), f"unknown_{int(item.isState)}"),
                })
            return rows
        finally:
            self.api.WlanFreeMemory(ctypes.cast(pointer, ctypes.c_void_p))

    def radio(self, guid: _GUID) -> list[dict[str, Any]]:
        data_size = ctypes.c_uint32()
        data = ctypes.c_void_p()
        opcode_type = ctypes.c_uint32()
        code = self.api.WlanQueryInterface(
            self.handle, ctypes.byref(guid), _WLAN_INTF_OPCODE_RADIO_STATE, None,
            ctypes.byref(data_size), ctypes.byref(data), ctypes.byref(opcode_type),
        )
        self._check(code, "WlanQueryInterface(radio_state)")
        try:
            expected_size = ctypes.sizeof(_WLAN_RADIO_STATE)
            if not data or data_size.value < expected_size:
                raise RuntimeError("WLAN radio-state response is smaller than WLAN_RADIO_STATE")
            count = ctypes.cast(data, ctypes.POINTER(ctypes.c_uint32)).contents.value
            required = ctypes.sizeof(ctypes.c_uint32) + count * ctypes.sizeof(_WLAN_PHY_RADIO_STATE)
            if count > _MAX_PHYS or required > expected_size or required > data_size.value:
                raise RuntimeError("WLAN radio-state response failed bounds validation")
            raw = ctypes.string_at(data, expected_size)
            state = _WLAN_RADIO_STATE.from_buffer_copy(raw)
            return [
                {
                    "phy_index": int(item.dwPhyIndex),
                    "software_radio": int(item.dot11SoftwareRadioState),
                    "software_radio_name": _radio_name(int(item.dot11SoftwareRadioState)),
                    "hardware_radio": int(item.dot11HardwareRadioState),
                    "hardware_radio_name": _radio_name(int(item.dot11HardwareRadioState)),
                    "effective_radio_on": (
                        item.dot11SoftwareRadioState == _DOT11_RADIO_ON
                        and item.dot11HardwareRadioState == _DOT11_RADIO_ON
                    ),
                }
                for item in state.PhyRadioState[:count]
            ]
        finally:
            if data:
                self.api.WlanFreeMemory(data)

    def set_software_radio(self, guid: _GUID, phy_index: int, enabled: bool) -> None:
        state = _WLAN_PHY_RADIO_STATE(
            dwPhyIndex=phy_index,
            dot11SoftwareRadioState=_DOT11_RADIO_ON if enabled else _DOT11_RADIO_OFF,
            dot11HardwareRadioState=_DOT11_RADIO_UNKNOWN,
        )
        self._check(
            self.api.WlanSetInterface(
                self.handle, ctypes.byref(guid), _WLAN_INTF_OPCODE_RADIO_STATE,
                ctypes.sizeof(state), ctypes.byref(state), None,
            ),
            "WlanSetInterface(radio_state)",
        )


def _parse_radio_state_buffer(raw: bytes) -> list[dict[str, Any]]:
    """Parse the fixed WLAN_RADIO_STATE structure, using only valid PHY entries."""
    expected_size = ctypes.sizeof(_WLAN_RADIO_STATE)
    if not isinstance(raw, bytes) or len(raw) < expected_size:
        raise ValueError("radio-state buffer is smaller than the native WLAN_RADIO_STATE structure")
    state = _WLAN_RADIO_STATE.from_buffer_copy(raw[:expected_size])
    count = int(state.dwNumberOfPhys)
    if count > _MAX_PHYS:
        raise ValueError("radio-state PHY count exceeds WLAN_MAX_PHY_INDEX")
    return [
        {
            "phy_index": int(item.dwPhyIndex),
            "software_radio": int(item.dot11SoftwareRadioState),
            "software_radio_name": _radio_name(int(item.dot11SoftwareRadioState)),
            "hardware_radio": int(item.dot11HardwareRadioState),
            "hardware_radio_name": _radio_name(int(item.dot11HardwareRadioState)),
            "effective_radio_on": (
                item.dot11SoftwareRadioState == _DOT11_RADIO_ON
                and item.dot11HardwareRadioState == _DOT11_RADIO_ON
            ),
        }
        for item in state.PhyRadioState[:count]
    ]


def _radio_name(value: int) -> str:
    return {_DOT11_RADIO_UNKNOWN: "unknown", _DOT11_RADIO_ON: "on",
            _DOT11_RADIO_OFF: "off"}.get(value, f"unknown_{value}")


def list_wireless_radios() -> dict[str, Any]:
    session = _WlanSession()
    try:
        rows = []
        for interface in session.interfaces():
            guid = _guid_from_text(interface["interface_guid"])
            try:
                phys = session.radio(guid)
                error = None
            except OSError as exc:
                phys = []
                error = str(exc)[:240]
            rows.append({**interface, "physical_radios": phys, "query_error": error})
        return {
            "interfaces": rows,
            "count": len(rows),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "source": "Windows Native WLAN API (WlanEnumInterfaces/WlanQueryInterface)",
            "hardware_radio_mutable": False,
            "verified": True,
        }
    finally:
        session.close()


def set_wireless_software_radio(interface_guid: str, enabled: bool) -> dict[str, Any]:
    """Change one interface's software radio state and rollback changed PHYs on failure."""
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    requested_guid = _guid_from_text(interface_guid)
    session = _WlanSession()
    changed: list[tuple[int, bool]] = []
    try:
        interfaces = session.interfaces()
        matches = [row for row in interfaces
                   if row["interface_guid"].casefold() == interface_guid.casefold()]
        if len(matches) != 1:
            raise LookupError("exact WLAN interface GUID was not found or is ambiguous")
        before = session.radio(requested_guid)
        if not before:
            raise RuntimeError("WLAN interface exposes no physical radio state")
        if any(item["hardware_radio"] == _DOT11_RADIO_UNKNOWN for item in before):
            raise RuntimeError("hardware radio state is unknown; refusing to change software radio")
        if enabled and any(item["hardware_radio"] == _DOT11_RADIO_OFF for item in before):
            raise PermissionError("hardware radio switch is off; APEX cannot or will not override hardware state")
        try:
            for item in before:
                old_enabled = item["software_radio"] == _DOT11_RADIO_ON
                if old_enabled is enabled:
                    continue
                session.set_software_radio(requested_guid, item["phy_index"], enabled)
                changed.append((item["phy_index"], old_enabled))
            after = session.radio(requested_guid)
            matches_state = all(
                item["software_radio"] == (_DOT11_RADIO_ON if enabled else _DOT11_RADIO_OFF)
                for item in after
            )
            if len(after) != len(before) or not matches_state:
                raise RuntimeError("WLAN software radio postcondition failed")
        except Exception:
            # Restore only PHYs this request successfully changed.
            for phy_index, old_enabled in reversed(changed):
                try:
                    session.set_software_radio(requested_guid, phy_index, old_enabled)
                except Exception:
                    pass
            raise
        effective = all(item["effective_radio_on"] for item in after)
        return {
            "summary": (
                "Wi-Fi software radio is on." if enabled and effective else
                "Wi-Fi software radio is on, but hardware radio remains off." if enabled else
                "Wi-Fi software radio is off."
            ),
            "interface_guid": interface_guid,
            "interface_description": matches[0]["description"],
            "previous_radios": before,
            "radios": after,
            "requested_enabled": enabled,
            "effective_radio_on": effective,
            "verified": True,
            "hardware_controlled": True,
        }
    finally:
        session.close()


def provider_available() -> bool:
    return os.name == "nt"
