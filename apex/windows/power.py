"""Windows Power API access for enumerating and selecting installed power schemes."""
from __future__ import annotations

import ctypes
import os
import uuid
from datetime import datetime, timezone
from typing import Any


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


_ERROR_SUCCESS = 0
_ERROR_NO_MORE_ITEMS = 259
_ACCESS_SCHEME = 16


def _require_windows() -> None:
    if os.name != "nt":
        raise OSError("Windows power-plan APIs are available only on Windows")


def _to_guid(value: str) -> _GUID:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("power-plan identifier must be a valid GUID") from exc
    guid = _GUID()
    guid.Data1 = parsed.time_low
    guid.Data2 = parsed.time_mid
    guid.Data3 = parsed.time_hi_version
    guid.Data4[:] = parsed.bytes[8:]
    return guid


def _guid_text(value: _GUID) -> str:
    raw = ctypes.string_at(ctypes.byref(value), ctypes.sizeof(_GUID))
    return str(uuid.UUID(bytes_le=raw))


def _api():
    _require_windows()
    dll = ctypes.WinDLL("PowrProf.dll", use_last_error=True)
    dll.PowerEnumerate.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(_GUID),
        ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_ubyte),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    dll.PowerEnumerate.restype = ctypes.c_uint32
    dll.PowerReadFriendlyName.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(_GUID),
        ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
    ]
    dll.PowerReadFriendlyName.restype = ctypes.c_uint32
    dll.PowerGetActiveScheme.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(_GUID))]
    dll.PowerGetActiveScheme.restype = ctypes.c_uint32
    dll.PowerSetActiveScheme.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GUID)]
    dll.PowerSetActiveScheme.restype = ctypes.c_uint32
    return dll


def _check(code: int, operation: str) -> None:
    if code != _ERROR_SUCCESS:
        raise OSError(code, f"{operation} failed with Windows error {code}")


def _friendly_name(api, guid: _GUID) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    size = ctypes.c_uint32(ctypes.sizeof(buffer))
    code = api.PowerReadFriendlyName(
        None, ctypes.byref(guid), None, None,
        ctypes.cast(buffer, ctypes.c_void_p), ctypes.byref(size),
    )
    if code != _ERROR_SUCCESS:
        return _guid_text(guid)
    return buffer.value[:240] or _guid_text(guid)


def list_power_plans() -> dict[str, Any]:
    api = _api()
    plans = []
    index = 0
    while index < 128:
        buffer = (ctypes.c_ubyte * ctypes.sizeof(_GUID))()
        size = ctypes.c_uint32(ctypes.sizeof(_GUID))
        code = api.PowerEnumerate(
            None, None, None, _ACCESS_SCHEME, index, buffer, ctypes.byref(size)
        )
        if code == _ERROR_NO_MORE_ITEMS:
            break
        _check(code, "PowerEnumerate")
        guid = _GUID.from_buffer_copy(bytes(buffer))
        plans.append({"guid": _guid_text(guid), "name": _friendly_name(api, guid)})
        index += 1
    if index >= 128:
        raise RuntimeError("power scheme enumeration reached its safety bound")
    active = get_active_power_plan()
    for plan in plans:
        plan["active"] = plan["guid"].casefold() == active["guid"].casefold()
    return {
        "plans": plans,
        "count": len(plans),
        "active_guid": active["guid"],
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source": "Windows PowrProf power-plan API",
        "verified": True,
    }


def get_active_power_plan() -> dict[str, Any]:
    api = _api()
    allocated = ctypes.POINTER(_GUID)()
    _check(api.PowerGetActiveScheme(None, ctypes.byref(allocated)), "PowerGetActiveScheme")
    try:
        guid = _GUID.from_buffer_copy(
            ctypes.string_at(allocated, ctypes.sizeof(_GUID))
        )
    finally:
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(allocated, ctypes.c_void_p))
    return {"guid": _guid_text(guid), "name": _friendly_name(api, guid), "verified": True}


def set_active_power_plan(guid_text: str) -> dict[str, Any]:
    """Select only an installed scheme and verify the active GUID after the change."""
    api = _api()
    requested = _to_guid(guid_text)
    requested_text = _guid_text(requested)
    installed = {item["guid"].casefold() for item in list_power_plans()["plans"]}
    if requested_text.casefold() not in installed:
        raise ValueError("requested power plan is not present in the installed scheme catalogue")
    previous = get_active_power_plan()
    if previous["guid"].casefold() == requested_text.casefold():
        return {
            "summary": f"Power plan is already set to {previous['name']}.",
            "active_plan": previous, "previous_guid": previous["guid"], "verified": True,
        }
    _check(api.PowerSetActiveScheme(None, ctypes.byref(requested)), "PowerSetActiveScheme")
    observed = get_active_power_plan()
    if observed["guid"].casefold() != requested_text.casefold():
        try:
            rollback = _to_guid(previous["guid"])
            api.PowerSetActiveScheme(None, ctypes.byref(rollback))
        finally:
            raise RuntimeError("power-plan postcondition failed; previous plan restoration was attempted")
    return {
        "summary": f"Power plan changed to {observed['name']}.",
        "active_plan": observed, "previous_guid": previous["guid"], "verified": True,
    }


def provider_available() -> bool:
    return os.name == "nt"
