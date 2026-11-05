"""Validated launchers for documented Windows Settings pages and MMC/CPL targets."""
from __future__ import annotations
import os

SETTINGS_URIS = {
    "display": "ms-settings:display", "sound": "ms-settings:sound", "bluetooth": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi", "network": "ms-settings:network-status", "power": "ms-settings:powersleep",
    "windows_update": "ms-settings:windowsupdate", "apps": "ms-settings:appsfeatures",
    "startup": "ms-settings:startupapps", "notifications": "ms-settings:notifications",
    "accessibility": "ms-settings:accessibility", "night_light": "ms-settings:nightlight",
}
CONSOLE_TARGETS = {
    "device_manager": "devmgmt.msc", "services": "services.msc", "event_viewer": "eventvwr.msc",
    "task_scheduler": "taskschd.msc", "disk_management": "diskmgmt.msc", "computer_management": "compmgmt.msc",
}

def open_settings(target: str) -> dict:
    if os.name != "nt":
        raise OSError("Windows Settings launcher is available only on Windows")
    if not isinstance(target, str):
        raise ValueError("target must be a string key")
    key = target.strip().lower()
    uri = SETTINGS_URIS.get(key)
    if not uri:
        raise ValueError("settings target is not in the APEX allowlist")
    os.startfile(uri)
    return {"summary": f"Dispatched Windows Settings page: {key}.", "target": key,
            "uri": uri, "verified": False, "verification": "The URI was dispatched; page readiness is not verified."}

def open_console(target: str) -> dict:
    if os.name != "nt":
        raise OSError("Windows management console launcher is available only on Windows")
    if not isinstance(target, str):
        raise ValueError("target must be a string key")
    key = target.strip().lower()
    console = CONSOLE_TARGETS.get(key)
    if not console:
        raise ValueError("console target is not in the APEX allowlist")
    os.startfile(console)
    return {"summary": f"Dispatched Windows management console: {key}.", "target": key,
            "console": console, "verified": False}
