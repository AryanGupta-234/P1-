"""WMI monitor brightness controls with read-back verification."""
from __future__ import annotations
import os

def _service():
    if os.name != "nt":
        raise OSError("monitor brightness requires Windows")
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for monitor brightness control") from exc
    locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
    return locator.ConnectServer(".", "root\\wmi")

def get_brightness() -> dict:
    service = _service()
    levels = []
    for item in service.ExecQuery("SELECT InstanceName, CurrentBrightness, Level FROM WmiMonitorBrightness"):
        levels.append({"instance": str(item.InstanceName)[:240], "current_percent": int(item.CurrentBrightness),
                       "supported_levels": [int(x) for x in (item.Level or [])[:101]]})
    return {"monitors": levels, "count": len(levels), "source": "WMI WmiMonitorBrightness"}

def set_brightness(percent: int) -> dict:
    if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
        raise ValueError("brightness must be an integer from 0 through 100")
    service = _service()
    methods = list(service.ExecQuery("SELECT InstanceName FROM WmiMonitorBrightnessMethods"))
    if not methods:
        raise RuntimeError("no monitor exposes the WMI brightness control method")
    for monitor in methods:
        params = monitor.Methods_("WmiSetBrightness").InParameters.SpawnInstance_()
        params.Timeout = 0
        params.Brightness = percent
        result = monitor.ExecMethod_("WmiSetBrightness", params)
        if int(result.ReturnValue) != 0:
            raise OSError(f"monitor brightness method returned WMI code {int(result.ReturnValue)}")
    observed = get_brightness()
    if not observed["monitors"] or any(abs(item["current_percent"] - percent) > 2 for item in observed["monitors"]):
        raise RuntimeError("brightness postcondition did not match requested level")
    return {"summary": f"Set supported monitor brightness to approximately {percent}%.",
            "brightness_percent": percent, "monitors": observed["monitors"], "verified": True}

def provider_available() -> bool:
    if os.name != "nt":
        return False
    from importlib.util import find_spec
    try:
        return find_spec("win32com.client") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
