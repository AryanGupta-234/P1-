"""Validated Windows Settings URI and MMC launchers backed by a searchable catalogue."""
from __future__ import annotations

import os
import sys
from typing import Any

from senti.windows.settings_catalog import (
    MICROSOFT_SOURCE,
    SETTINGS_CATALOG,
    list_settings_pages as _list_settings_pages,
    resolve_settings_page,
    search_settings_pages as _search_settings_pages,
)

# Public compatibility mapping. The runtime tool uses the catalogue resolver rather
# than embedding this large mapping in an LLM tool schema.
SETTINGS_URIS = {
    item["id"]: item["uri"]
    for item in SETTINGS_CATALOG
    if item["lifecycle"] != "removed" and item["id"] != "sound_device_properties"
}
SETTINGS_URIS.update({
    "apps": "ms-settings:appsfeatures",
    "startup": "ms-settings:startupapps",
    "network": "ms-settings:network-status",
    "windows_update": "ms-settings:windowsupdate",
    "night_light": "ms-settings:nightlight",
})

CONTROL_PANEL_TARGETS = {
    "network_sharing_center": "/name Microsoft.NetworkAndSharingCenter",
    "devices_and_printers": "/name Microsoft.DevicesAndPrinters",
    "credential_manager": "/name Microsoft.CredentialManager",
    "administrative_tools": "/name Microsoft.AdministrativeTools",
    "user_accounts": "/name Microsoft.UserAccounts",
    "windows_firewall": "/name Microsoft.WindowsFirewall",
    "power_options": "/name Microsoft.PowerOptions",
    "programs_and_features": "/name Microsoft.ProgramsAndFeatures",
    "mouse_properties": "/name Microsoft.Mouse",
    "keyboard_properties": "/name Microsoft.Keyboard",
    "system_properties": "/name Microsoft.System",
    "fonts": "/name Microsoft.Fonts",
    "region": "/name Microsoft.RegionAndLanguage",
    "date_and_time": "/name Microsoft.DateAndTime",
}

CONSOLE_TARGETS = {
    "device_manager": "devmgmt.msc",
    "services": "services.msc",
    "event_viewer": "eventvwr.msc",
    "task_scheduler": "taskschd.msc",
    "disk_management": "diskmgmt.msc",
    "computer_management": "compmgmt.msc",
    "component_services": "comexp.msc",
    "certificate_manager": "certmgr.msc",
    "local_group_policy": "gpedit.msc",
    "local_security_policy": "secpol.msc",
    "performance_monitor": "perfmon.msc",
    "resource_monitor": "resmon.exe",
    "system_configuration": "msconfig.exe",
    "system_information": "msinfo32.exe",
    "registry_editor": "regedit.exe",
    "task_manager": "taskmgr.exe",
    "firewall_advanced": "wf.msc",
    "windows_defender_firewall": "firewall.cpl",
    "network_connections": "ncpa.cpl",
    "programs_and_features": "appwiz.cpl",
    "power_options": "powercfg.cpl",
    "sound_control_panel": "mmsys.cpl",
    "mouse_properties": "main.cpl",
    "internet_options": "inetcpl.cpl",
    "system_properties": "sysdm.cpl",
    "date_time": "timedate.cpl",
    "region": "intl.cpl",
    "user_accounts": "netplwiz.exe",
    "fonts": "shell:fonts",
}


def get_windows_build() -> int | None:
    """Return the current Windows build number, or None off Windows."""
    if os.name != "nt":
        return None
    version = sys.getwindowsversion()
    return int(version.build)


def list_settings_pages(*, category: str | None = None, include_deprecated: bool = True,
                        limit: int = 40, offset: int = 0) -> dict[str, Any]:
    return _list_settings_pages(
        category=category,
        include_deprecated=include_deprecated,
        limit=limit,
        offset=offset,
    )


def search_settings_pages(query: str = "", *, category: str | None = None,
                          include_deprecated: bool = False, limit: int = 15) -> dict[str, Any]:
    return _search_settings_pages(
        query,
        category=category,
        include_deprecated=include_deprecated,
        limit=limit,
    )


def open_settings(target: str) -> dict[str, Any]:
    """Open one exact catalogue page/alias; never pass through arbitrary URI text."""
    if os.name != "nt":
        raise OSError("Windows Settings launcher is available only on Windows")
    page = resolve_settings_page(target)
    if page["lifecycle"] == "removed":
        raise ValueError(f"Settings page '{page['label']}' is documented as removed")
    if page["id"] == "sound_device_properties":
        raise ValueError("Specific sound-device properties require a device endpoint parameter; arbitrary URI parameters are disabled.")
    build = get_windows_build()
    minimum = page.get("minimum_build")
    if minimum and build and build < minimum:
        raise OSError(
            f"Settings page '{page['label']}' requires Windows build {minimum} or later; "
            f"this device reports build {build}"
        )
    os.startfile(page["uri"])
    return {
        "summary": f"Dispatched Windows Settings page: {page['label']}.",
        "target": page["id"],
        "label": page["label"],
        "category": page["category"],
        "uri": page["uri"],
        "lifecycle": page["lifecycle"],
        "availability_note": page["availability_note"] or None,
        "minimum_build": minimum,
        "source": MICROSOFT_SOURCE,
        "verified": False,
        "verification": "The URI launch was dispatched; Settings page readiness and interactive availability are not independently verified.",
    }


def open_control_panel(target: str) -> dict[str, Any]:
    """Open one fixed Control Panel applet via a reviewed control.exe argument."""
    if os.name != "nt":
        raise OSError("Windows Control Panel launcher is available only on Windows")
    if not isinstance(target, str):
        raise ValueError("target must be a string key")
    key = target.strip().lower()
    arguments = CONTROL_PANEL_TARGETS.get(key)
    if arguments is None:
        raise ValueError("Control Panel target is not in the SENTI allowlist")
    os.startfile("control.exe", arguments=arguments)
    return {
        "summary": f"Dispatched Control Panel applet: {key}.",
        "target": key,
        "arguments": arguments,
        "verified": False,
        "verification": "The Control Panel applet launch was dispatched; UI readiness is not independently verified.",
    }


def open_console(target: str) -> dict[str, Any]:
    if os.name != "nt":
        raise OSError("Windows management console launcher is available only on Windows")
    if not isinstance(target, str):
        raise ValueError("target must be a string key")
    key = target.strip().lower()
    console = CONSOLE_TARGETS.get(key)
    if not console:
        raise ValueError("console target is not in the SENTI allowlist")
    os.startfile(console)
    return {
        "summary": f"Dispatched Windows management console: {key}.",
        "target": key,
        "console": console,
        "verified": False,
        "verification": "The console launch was dispatched; UI readiness is not independently verified.",
    }


def provider_available() -> bool:
    return os.name == "nt"
