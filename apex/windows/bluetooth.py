"""Windows Bluetooth radio inspection/control through the Windows.Devices.Radios API."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

_STATE_NAMES = {0: "unknown", 1: "on", 2: "off", 3: "disabled"}
_SETTLE_TIMEOUT_SECONDS = 5.0


def _require_windows() -> None:
    if os.name != "nt":
        raise OSError("Bluetooth radio controls require Windows")


def _winrt():
    _require_windows()
    try:
        from winrt.windows.devices.radios import Radio, RadioAccessStatus, RadioKind, RadioState
    except ImportError as exc:
        raise RuntimeError(
            "PyWinRT radio projection is unavailable; install the APEX Windows dependencies"
        ) from exc
    return Radio, RadioAccessStatus, RadioKind, RadioState


def _state_name(value: Any) -> str:
    return _STATE_NAMES.get(int(value), f"unknown_{int(value)}")


async def _bluetooth_objects():
    Radio, _AccessStatus, RadioKind, _RadioState = _winrt()
    radios = await Radio.get_radios_async()
    return [radio for radio in radios if radio.kind == RadioKind.BLUETOOTH]


async def _list_async() -> dict[str, Any]:
    radios = await _bluetooth_objects()
    items = [
        {
            "name": str(radio.name or "")[:160],
            "state": _state_name(radio.state),
            "state_code": int(radio.state),
        }
        for radio in radios
    ]
    return {
        "radios": items,
        "count": len(items),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source": "Windows.Devices.Radios WinRT API",
        "verified": True,
    }


def list_bluetooth_radios() -> dict[str, Any]:
    return asyncio.run(_list_async())


async def _set_async(radio_name: str, enabled: bool) -> dict[str, Any]:
    Radio, RadioAccessStatus, RadioKind, RadioState = _winrt()
    radios = await Radio.get_radios_async()
    matches = [
        radio for radio in radios
        if radio.kind == RadioKind.BLUETOOTH and str(radio.name or "").casefold() == radio_name.casefold()
    ]
    if len(matches) != 1:
        raise LookupError("exact Bluetooth radio name was not found or is ambiguous")
    radio = matches[0]
    before = int(radio.state)
    desired = RadioState.ON if enabled else RadioState.OFF
    desired_code = int(desired)
    if before == desired_code:
        return {
            "summary": f"Bluetooth radio '{radio_name}' is already {_state_name(before)}.",
            "radio_name": radio_name,
            "previous_state": _state_name(before),
            "state": _state_name(before),
            "verified": True,
        }
    if before in {0, 3}:
        raise PermissionError(
            f"Bluetooth radio is {_state_name(before)}; hardware or policy state prevents a safe change"
        )

    access = await Radio.request_access_async()
    if access != RadioAccessStatus.ALLOWED:
        raise PermissionError(f"Windows denied Bluetooth radio control access: {access!s}")

    status = await radio.set_state_async(desired)
    if status != RadioAccessStatus.ALLOWED:
        raise PermissionError(f"Windows rejected Bluetooth radio state change: {status!s}")

    deadline = asyncio.get_running_loop().time() + _SETTLE_TIMEOUT_SECONDS
    observed = before
    while asyncio.get_running_loop().time() < deadline:
        refreshed = await Radio.get_radios_async()
        refreshed_matches = [
            item for item in refreshed
            if item.kind == RadioKind.BLUETOOTH and str(item.name or "").casefold() == radio_name.casefold()
        ]
        if len(refreshed_matches) != 1:
            raise RuntimeError("Bluetooth radio disappeared or became ambiguous during state verification")
        observed = int(refreshed_matches[0].state)
        if observed == desired_code:
            return {
                "summary": f"Bluetooth radio '{radio_name}' is now {_state_name(observed)}.",
                "radio_name": radio_name,
                "previous_state": _state_name(before),
                "state": _state_name(observed),
                "verified": True,
                "compensation": {
                    "radio_name": radio_name,
                    "restore_state": _state_name(before),
                },
            }
        await asyncio.sleep(0.2)

    # A failed postcondition triggers a best-effort restore to the exact prior state.
    try:
        if before in {1, 2}:
            rollback_state = RadioState.ON if before == 1 else RadioState.OFF
            rollback_status = await refreshed_matches[0].set_state_async(rollback_state)
            rollback_attempted = rollback_status == RadioAccessStatus.ALLOWED
        else:
            rollback_attempted = False
    except Exception:
        rollback_attempted = False
    raise RuntimeError(
        "Bluetooth radio did not reach the requested state; "
        f"previous_state={_state_name(before)}, observed_state={_state_name(observed)}, "
        f"rollback_accepted={rollback_attempted}"
    )


def set_bluetooth_radio(radio_name: str, enabled: bool) -> dict[str, Any]:
    """Change one exact named Bluetooth radio and verify the effective state."""
    if not isinstance(radio_name, str) or not 1 <= len(radio_name.strip()) <= 160:
        raise ValueError("radio_name must contain 1 to 160 characters")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_set_async(radio_name.strip(), enabled))
    raise RuntimeError("synchronous Bluetooth control cannot run inside an active asyncio event loop")


def provider_available() -> bool:
    if os.name != "nt":
        return False
    from importlib.util import find_spec

    try:
        return find_spec("winrt.windows.devices.radios") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
