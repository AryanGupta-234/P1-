"""Read-only Windows Update posture snapshot using WMI and registry metadata."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


_UPDATE_SERVICES = ("wuauserv", "UsoSvc", "BITS", "WaaSMedicSvc")


def update_status(hotfix_limit: int = 100) -> dict[str, Any]:
    """Report service posture, installed hotfix metadata and reboot flags; never install updates."""
    if os.name != "nt":
        raise OSError("Windows Update inspection requires Windows")
    if isinstance(hotfix_limit, bool) or not 1 <= hotfix_limit <= 200:
        raise ValueError("hotfix_limit must be between 1 and 200")
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for Windows Update WMI inspection") from exc

    locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
    service = locator.ConnectServer(".", r"root\cimv2")
    service_rows = list(service.ExecQuery(
        "SELECT Name, State, StartMode, Status FROM Win32_Service "
        "WHERE Name='wuauserv' OR Name='UsoSvc' OR Name='BITS' OR Name='WaaSMedicSvc'"
    ))
    services = {
        str(item.Name): {
            "state": str(item.State or "unknown")[:40],
            "start_mode": str(item.StartMode or "unknown")[:40],
            "status": str(item.Status or "unknown")[:40],
        }
        for item in service_rows
    }

    hotfixes = []
    for item in service.ExecQuery(
        "SELECT HotFixID, InstalledOn, Description FROM Win32_QuickFixEngineering"
    ):
        hotfixes.append({
            "id": str(item.HotFixID or "")[:80],
            "installed_on": str(item.InstalledOn or "")[:40],
            "description": str(item.Description or "")[:120],
        })
        if len(hotfixes) >= hotfix_limit:
            break
    hotfixes.sort(key=lambda row: row["installed_on"], reverse=True)

    reboot_flags = _reboot_flags()
    return {
        "services": services,
        "service_coverage": sorted(services),
        "installed_hotfixes": hotfixes,
        "hotfix_count_returned": len(hotfixes),
        "reboot_pending": any(reboot_flags.values()),
        "reboot_indicators": reboot_flags,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source": "WMI Win32_Service/Win32_QuickFixEngineering and Windows Update registry metadata",
        "read_only": True,
        "verified": True,
        "limitations": [
            "Hotfix inventory is not a complete list of Microsoft Store or every driver update.",
            "This snapshot does not search online for pending updates or install/uninstall anything.",
        ],
    }


def _reboot_flags() -> dict[str, bool | None]:
    try:
        import winreg
    except ImportError:
        return {"component_based_servicing": None, "windows_update": None, "pending_file_rename": None}

    def key_exists(path: str, value_name: str | None = None) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ) as key:
                if value_name is None:
                    return True
                winreg.QueryValueEx(key, value_name)
                return True
        except OSError:
            return False

    return {
        "component_based_servicing": key_exists(
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"
        ),
        "windows_update": key_exists(
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
        ),
        "pending_file_rename": key_exists(
            r"SYSTEM\CurrentControlSet\Control\Session Manager", "PendingFileRenameOperations"
        ),
    }


def provider_available() -> bool:
    if os.name != "nt":
        return False
    from importlib.util import find_spec

    try:
        return find_spec("win32com.client") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
