"""Open any catalogued Windows settings surface through validated, shell-free launchers.

Every launch target comes from the static catalogue or verified discovery; text from the
model is only ever used as a lookup key. Launching uses ``os.startfile`` (ShellExecuteW)
with an absolute executable path and a fixed argument string -- never a command shell.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from senti.windows import settings_catalog as catalog
from senti.windows import settings_discovery as discovery

CATALOGUE_VERSION = catalog.CATALOGUE_VERSION
KINDS = catalog.KINDS
MICROSOFT_SOURCE = catalog.MICROSOFT_SOURCE
SETTINGS_CATALOG = catalog.SETTINGS_CATALOG
STATIC_SURFACES = catalog.STATIC_SURFACES
catalogue_counts = catalog.catalogue_counts
kind_label = catalog.kind_label
public_entry = catalog.public_entry
rank_surfaces = catalog.rank_surfaces
resolve_exact = catalog.resolve_exact
resolve_settings_page = catalog.resolve_settings_page
settings_categories = catalog.settings_categories
validate_entry = catalog.validate_entry
_list_settings_pages = catalog.list_settings_pages
_search_settings_pages = catalog.search_settings_pages

# Public compatibility mapping (id -> URI); the runtime resolves through the catalogue.
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

# Legacy short keys accepted by the older tools, mapped to catalogue ids.
CONTROL_PANEL_TARGETS = {
    "network_sharing_center": "cp_network_sharing",
    "devices_and_printers": "cp_devices_printers",
    "credential_manager": "cp_credential_manager",
    "administrative_tools": "cp_administrative_tools",
    "user_accounts": "cp_user_accounts",
    "windows_firewall": "cp_windows_firewall",
    "power_options": "cp_power_options",
    "programs_and_features": "cp_programs_features",
    "mouse_properties": "cp_mouse",
    "keyboard_properties": "cp_keyboard",
    "system_properties": "cp_system",
    "fonts": "cp_fonts",
    "region": "cp_region",
    "date_and_time": "cp_date_time",
}

CONSOLE_TARGETS = {
    "device_manager": "msc_devmgmt",
    "services": "msc_services",
    "event_viewer": "msc_eventvwr",
    "task_scheduler": "msc_taskschd",
    "disk_management": "msc_diskmgmt",
    "computer_management": "msc_compmgmt",
    "component_services": "msc_comexp",
    "certificate_manager": "msc_certmgr",
    "local_group_policy": "msc_gpedit",
    "local_security_policy": "msc_secpol",
    "performance_monitor": "msc_perfmon",
    "resource_monitor": "util_resmon",
    "system_configuration": "util_msconfig",
    "system_information": "util_msinfo32",
    "registry_editor": "util_regedit",
    "task_manager": "util_taskmgr",
    "firewall_advanced": "msc_wf",
    "windows_defender_firewall": "cpl_firewall",
    "network_connections": "cpl_ncpa",
    "programs_and_features": "cpl_appwiz",
    "power_options": "cpl_powercfg",
    "sound_control_panel": "cpl_mmsys",
    "mouse_properties": "cpl_main",
    "internet_options": "cpl_inetcpl",
    "system_properties": "cpl_sysdm",
    "date_time": "cpl_timedate",
    "region": "cpl_intl",
    "user_accounts": "util_netplwiz",
    "fonts": "shell_fonts",
}

# Which kinds each tool scope may open, and whether controlled-tier consoles are allowed.
SCOPES: dict[str, tuple[frozenset[str], bool, dict[str, str]]] = {
    "surface": (frozenset(KINDS), False, {}),
    "settings": (frozenset({"ms_settings"}), False, {}),
    "control_panel": (frozenset({"control_name", "cpl", "shell_clsid"}), False, CONTROL_PANEL_TARGETS),
    "console": (frozenset({"msc", "utility", "cpl", "control_name", "shell_folder", "shell_clsid"}),
                True, CONSOLE_TARGETS),
}
SAFE_TOOL = "senti_open_windows_surface"
CONTROLLED_TOOL = "senti_open_management_console"


def get_windows_build() -> int | None:
    """Return the current Windows build number, or None off Windows."""
    if os.name != "nt":
        return None
    return int(sys.getwindowsversion().build)


def provider_available() -> bool:
    return os.name == "nt"


def surface_catalog(include_discovered: bool = True) -> list[dict[str, Any]] | tuple[dict[str, Any], ...]:
    """Static catalogue, optionally merged with cached read-only discovery."""
    if not include_discovered:
        return STATIC_SURFACES
    return discovery.merged_catalog()


# ------------------------------------------------------------------------------ search

def list_settings_pages(*, category: str | None = None, include_deprecated: bool = True,
                        limit: int = 40, offset: int = 0) -> dict[str, Any]:
    return _list_settings_pages(category=category, include_deprecated=include_deprecated,
                                limit=limit, offset=offset)


def search_settings_pages(query: str = "", *, category: str | None = None,
                          include_deprecated: bool = False, limit: int = 15) -> dict[str, Any]:
    return _search_settings_pages(query, category=category, include_deprecated=include_deprecated,
                                  limit=limit)


def _candidate(entry: dict[str, Any]) -> dict[str, Any]:
    row = {
        "id": entry["id"], "title": entry["title"], "kind": entry["kind"],
        "kind_label": kind_label(entry["kind"]), "category": entry.get("category"),
        "target": entry["target"], "risk": entry["risk"], "lifecycle": entry["lifecycle"],
        "present": entry["present"], "source": entry["source"],
        "availability": entry.get("availability") or None,
        "open_with": CONTROLLED_TOOL if entry["risk"] == "controlled" else SAFE_TOOL,
    }
    for key in ("score", "match"):
        if key in entry:
            row[key] = entry[key]
    return row


def search_windows_surfaces(query: str = "", *, kind: str | None = None, category: str | None = None,
                            include_deprecated: bool = False, include_discovered: bool = True,
                            limit: int = 15, offset: int = 0) -> dict[str, Any]:
    """Rank every known surface (Settings, Control Panel, consoles, utilities, folders)."""
    if not isinstance(query, str) or len(query) > 160:
        raise ValueError("query must contain at most 160 characters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if kind is not None and kind not in KINDS:
        raise ValueError("kind must be one of " + ", ".join(KINDS))
    entries = surface_catalog(include_discovered)
    kinds = (kind,) if kind else None
    ranked = rank_surfaces(query, entries, kinds=kinds, category=category,
                           include_deprecated=include_deprecated, limit=offset + limit)
    mode = "ranked"
    if not ranked and not query.strip():
        mode = "listing"
        order = {name: index for index, name in enumerate(KINDS)}
        pool = [public_entry(e) for e in entries
                if (kind is None or e["kind"] == kind)
                and (category is None or (e.get("category") or "").casefold() == category.casefold())
                and (include_deprecated or e["lifecycle"] not in {"deprecated", "removed"})]
        pool.sort(key=lambda e: (order.get(e["kind"], 99), e.get("category") or "", e["title"]))
        total = len(pool)
        ranked = pool[: offset + limit]
    else:
        total = len(ranked)
    page = ranked[offset: offset + limit]
    return {
        "candidates": [_candidate(item) for item in page],
        "count": len(page),
        "mode": mode,
        "total": total if mode == "listing" else None,
        "offset": offset,
        "next_offset": offset + limit if mode == "listing" and offset + limit < total else None,
        "query": query,
        "catalogue_counts": catalogue_counts(entries),
        "catalogue_version": CATALOGUE_VERSION,
        "guidance": "Choose one candidate id and pass it to open_with. Scores are relative; "
                    "present=false means it was not found on this PC.",
    }


# ------------------------------------------------------------------------------ launch

def _paths() -> tuple[str, str]:
    root = discovery.windows_directory()
    return root, discovery.system32_directory(root)


def launch_spec(entry: dict[str, Any]) -> tuple[str, str | None]:
    """Return (file, fixed arguments) for ``os.startfile``; derived only from catalogue fields."""
    validate_entry(entry)
    root, system32 = _paths()
    kind = entry["kind"]
    if kind == "ms_settings":
        return entry["target"], None
    control = os.path.join(system32, "control.exe")
    if kind == "control_name":
        page = entry.get("page")
        return control, f"/name {entry['canonical_name']}" + (f" /page {page}" if page else "")
    if kind == "cpl":
        return control, entry["target"]
    if kind == "msc":
        path = entry.get("path") or os.path.join(system32, entry["file"])
        return path, None
    if kind == "utility":
        path = entry.get("path")
        if not path:
            path = next((os.path.join(folder, entry["file"]) for folder in (system32, root)
                         if os.path.isfile(os.path.join(folder, entry["file"]))),
                        os.path.join(system32, entry["file"]))
        return path, entry.get("arguments")
    return os.path.join(root, "explorer.exe"), entry["target"]


def _resolve(target: str, scope: str) -> dict[str, Any]:
    kinds, _allow_controlled, legacy = SCOPES[scope]
    if not isinstance(target, str):
        raise TypeError("target must be a string")
    key = target.strip()
    key = legacy.get(key.lower(), key)
    if scope == "settings":
        return resolve_settings_page(key)
    return resolve_exact(key, surface_catalog(), kinds=kinds)


def _prepare(target: str, scope: str) -> tuple[dict[str, Any], str, str | None]:
    """Resolve and vet a target. Raises ValueError (or OSError for build limits)."""
    entry = _resolve(target, scope)
    _kinds, allow_controlled, _legacy = SCOPES[scope]
    title = entry["title"]
    if entry["lifecycle"] == "removed":
        raise ValueError(f"'{title}' is documented as removed from current Windows")
    if entry["id"] == "sound_device_properties":
        raise ValueError("Specific sound-device properties require a device endpoint parameter; "
                         "arbitrary URI parameters are disabled.")
    if entry["present"] is False:
        raise ValueError(f"'{title}' was not found on this PC ({entry.get('availability') or 'not installed'})")
    if entry["risk"] == "controlled" and not allow_controlled:
        raise ValueError(f"'{title}' can change system configuration (risk tier 'controlled'); "
                         f"open it with {CONTROLLED_TOOL}")
    minimum = entry.get("minimum_build")
    build = get_windows_build()
    if minimum and build and build < minimum:
        raise OSError(f"'{title}' requires Windows build {minimum} or later; this device reports build {build}")
    file, arguments = launch_spec(entry)
    return entry, file, arguments


def _effect(entry: dict[str, Any]) -> str:
    text = f"Opens the {entry['title']} {kind_label(entry['kind'])}; no settings are changed."
    if entry["risk"] == "controlled":
        text += " The opened tool can change system configuration, but SENTI makes no changes itself."
    return text


def simulate_open(target: str, scope: str = "surface") -> dict[str, Any]:
    """Preview what a launch would do. Never launches anything."""
    try:
        entry, file, arguments = _prepare(target, scope)
    except OSError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "id": entry["id"], "title": entry["title"], "kind": entry["kind"], "target": entry["target"],
        "launch": {"file": file, "arguments": arguments}, "present": entry["present"],
        "source": entry["source"], "surface_risk": entry["risk"], "lifecycle": entry["lifecycle"],
        "availability": entry.get("availability") or None, "effect": _effect(entry),
        "changes_settings": False,
    }


def _launch(target: str, scope: str) -> tuple[dict[str, Any], str, str | None]:
    if os.name != "nt":
        raise OSError("Windows settings launchers are available only on Windows")
    entry, file, arguments = _prepare(target, scope)
    if arguments is None:
        os.startfile(file)
    else:
        os.startfile(file, arguments=arguments)
    return entry, file, arguments


def _result(entry: dict[str, Any], file: str, arguments: str | None) -> dict[str, Any]:
    return {
        "summary": f"Dispatched {kind_label(entry['kind'])}: {entry['title']}.",
        "target": entry["id"], "title": entry["title"], "kind": entry["kind"],
        "launch_target": entry["target"], "file": file, "arguments": arguments,
        "present": entry["present"], "source": entry["source"],
        "availability": entry.get("availability") or None,
        "verified": False,
        "verification": "The launch was dispatched; window readiness is not independently verified.",
    }


def open_windows_surface(target: str) -> dict[str, Any]:
    """Open any low-risk catalogued surface by exact id, target, title or alias."""
    return _result(*_launch(target, "surface"))


def open_settings(target: str) -> dict[str, Any]:
    """Open one exact ms-settings catalogue page/alias; never pass through arbitrary URI text."""
    entry, file, arguments = _launch(target, "settings")
    result = _result(entry, file, arguments)
    result.update({
        "summary": f"Dispatched Windows Settings page: {entry['title']}.",
        "label": entry["title"], "category": entry["category"], "uri": entry["target"],
        "lifecycle": entry["lifecycle"], "availability_note": entry.get("availability") or None,
        "minimum_build": entry.get("minimum_build"), "source": MICROSOFT_SOURCE,
    })
    return result


def open_control_panel(target: str) -> dict[str, Any]:
    """Open one catalogued Control Panel item or applet via control.exe/explorer.exe."""
    return _result(*_launch(target, "control_panel"))


def open_console(target: str) -> dict[str, Any]:
    """Open a catalogued console or utility, including controlled-tier ones (approval-gated)."""
    return _result(*_launch(target, "console"))
