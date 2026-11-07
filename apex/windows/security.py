"""Read-only Microsoft Defender status inspection through the documented WMI provider."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


_FIELDS = {
    "antivirus_enabled": "AntivirusEnabled",
    "antispyware_enabled": "AntispywareEnabled",
    "real_time_protection_enabled": "RealTimeProtectionEnabled",
    "behavior_monitor_enabled": "BehaviorMonitorEnabled",
    "ioav_protection_enabled": "IoavProtectionEnabled",
    "network_inspection_enabled": "NISEnabled",
    "antimalware_service_enabled": "AMServiceEnabled",
    "quick_scan_end_time": "QuickScanEndTime",
    "full_scan_end_time": "FullScanEndTime",
    "signature_updated_at": "AntivirusSignatureLastUpdated",
}


def defender_status() -> dict[str, Any]:
    """Read status only. This provider never changes Defender preferences or exclusions."""
    if os.name != "nt":
        raise OSError("Microsoft Defender inspection requires Windows")
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for Defender WMI inspection") from exc
    locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
    service = locator.ConnectServer(".", r"root\Microsoft\Windows\Defender")
    rows = list(service.ExecQuery(
        "SELECT AntivirusEnabled, AntispywareEnabled, RealTimeProtectionEnabled, "
        "BehaviorMonitorEnabled, IoavProtectionEnabled, NISEnabled, AMServiceEnabled, "
        "QuickScanEndTime, FullScanEndTime, AntivirusSignatureLastUpdated "
        "FROM MSFT_MpComputerStatus"
    ))
    if not rows:
        raise RuntimeError("Defender WMI provider returned no status record")
    item = rows[0]
    status = {}
    for output_name, property_name in _FIELDS.items():
        value = getattr(item, property_name, None)
        if property_name.endswith("_EndTime") or property_name.endswith("_Updated"):
            status[output_name] = str(value)[:80] if value else None
        else:
            status[output_name] = bool(value) if value is not None else None
    status.update({
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source": "WMI root/Microsoft/Windows/Defender MSFT_MpComputerStatus",
        "read_only": True,
        "verified": True,
    })
    return status


def provider_available() -> bool:
    if os.name != "nt":
        return False
    from importlib.util import find_spec

    try:
        return find_spec("win32com.client") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
