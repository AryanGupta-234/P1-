"""Read-only, bounded and cached discovery of Windows settings surfaces on this PC.

Sources (all current-user readable, nothing is written or launched):

* registered Control Panel items: ``HKLM``/``HKCU`` ``...\\Explorer\\ControlPanel\\NameSpace``
  joined with ``HKCR\\CLSID\\{clsid}`` (``System.ApplicationName``, ``LocalizedString``);
* ``.msc`` and ``.cpl`` files present in ``%SystemRoot%\\System32``;
* known folders from ``HKLM\\...\\Explorer\\FolderDescriptions`` (``Name`` -> ``shell:<Name>``).

Results are merged with the static catalogue, de-duplicated and marked with
``source`` (static | discovered | both) and ``present`` (True | False | "unknown").
Off Windows, or when ``winreg`` is missing, every registry source reports "unavailable"
and the static catalogue is returned unchanged.
"""
from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

from senti.windows import settings_catalog as catalog

try:  # pragma: no cover - import shape depends on the platform
    import winreg as _winreg
except ImportError:  # pragma: no cover - non-Windows
    _winreg = None

CP_NAMESPACE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\ControlPanel\NameSpace"
FOLDER_DESCRIPTIONS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FolderDescriptions"
MAX_NAMESPACE_ITEMS = 400
MAX_FILES = 20000         # directory entries scanned in System32 (typically ~5000)
MAX_FOLDERS = 400
MAX_CLSID_PROBES = 200
TIME_BUDGET_SECONDS = 4.0
CACHE_TTL_SECONDS = 600.0

_CLSID_RE = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {}


def windows_directory() -> str:
    """Return the Windows directory, preferring the kernel API over environment variables."""
    if os.name == "nt":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(260)
            length = ctypes.windll.kernel32.GetSystemWindowsDirectoryW(buffer, 260)
            if 0 < length < 260 and os.path.isabs(buffer.value):
                return buffer.value
        except (AttributeError, OSError, ValueError):
            pass
    value = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return value if os.path.isabs(value) else r"C:\Windows"


def system32_directory(root: str | None = None) -> str:
    return os.path.join(root or windows_directory(), "System32")


def _clean_text(value: Any, limit: int = 120) -> str | None:
    if not isinstance(value, str):
        return None
    text = _CONTROL_CHARS.sub(" ", value).strip()
    return text[:limit] or None


def _load_indirect(value: str) -> str | None:
    """Resolve ``@dll,-id`` resource strings with SHLoadIndirectString (read-only)."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(512)
        result = ctypes.windll.shlwapi.SHLoadIndirectString(value, buffer, 512, None)
        return buffer.value if result == 0 and buffer.value else None
    except (AttributeError, OSError, ValueError):
        return None


def _display_string(value: Any) -> str | None:
    text = _clean_text(value, 400)
    if text and text.startswith("@"):
        text = _clean_text(_load_indirect(text))
    return _clean_text(text)


class _Registry:
    """Small read-only wrapper so tests can inject a fake ``winreg`` module."""

    def __init__(self, module: Any) -> None:
        self.m = module
        self.access = getattr(module, "KEY_READ", 0x20019) | getattr(module, "KEY_WOW64_64KEY", 0)

    def open(self, hive: Any, path: str) -> Any | None:
        try:
            return self.m.OpenKey(hive, path, 0, self.access)
        except OSError:
            return None

    def close(self, key: Any) -> None:
        closer = getattr(self.m, "CloseKey", None)
        if closer is not None and key is not None:
            try:
                closer(key)
            except OSError:
                pass

    def subkeys(self, key: Any, limit: int) -> list[str]:
        names: list[str] = []
        index = 0
        while index < limit:
            try:
                names.append(self.m.EnumKey(key, index))
            except OSError:
                break
            index += 1
        return names

    def value(self, key: Any, name: str) -> Any:
        try:
            return self.m.QueryValueEx(key, name)[0]
        except OSError:
            return None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")[:60] or "item"


def _discover_control_panel(reg: _Registry, deadline: float) -> tuple[list[dict[str, Any]], str]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    truncated = False
    hives = [("HKLM", reg.m.HKEY_LOCAL_MACHINE), ("HKCU", reg.m.HKEY_CURRENT_USER)]
    classes_root = reg.m.HKEY_CLASSES_ROOT
    for hive_name, hive in hives:
        namespace = reg.open(hive, CP_NAMESPACE)
        if namespace is None:
            continue
        try:
            names = reg.subkeys(namespace, MAX_NAMESPACE_ITEMS + 1)
            if len(names) > MAX_NAMESPACE_ITEMS:
                names, truncated = names[:MAX_NAMESPACE_ITEMS], True
            for name in names:
                if time.monotonic() > deadline:
                    return items, "truncated"
                if not _CLSID_RE.match(name) or name.upper() in seen:
                    continue
                clsid = name.upper()
                seen.add(clsid)
                ns_key = reg.open(namespace, name)
                ns_title = reg.value(ns_key, "") if ns_key is not None else None
                reg.close(ns_key)
                class_key = reg.open(classes_root, "CLSID\\" + name)
                if class_key is None:
                    continue
                try:
                    app_name = _clean_text(reg.value(class_key, "System.ApplicationName"), 100)
                    title = (_display_string(reg.value(class_key, "LocalizedString"))
                             or _clean_text(reg.value(class_key, ""))
                             or _clean_text(ns_title))
                    info = _display_string(reg.value(class_key, "InfoTip"))
                finally:
                    reg.close(class_key)
                if app_name and not catalog._CANONICAL_RE.match(app_name):
                    app_name = None
                if not title and not app_name:
                    continue
                items.append({
                    "clsid": clsid, "canonical_name": app_name, "title": title or app_name,
                    "info": info, "hive": hive_name,
                })
        finally:
            reg.close(namespace)
    return items, "truncated" if truncated else "ok"


def _discover_known_folders(reg: _Registry, deadline: float) -> tuple[list[dict[str, Any]], str]:
    root = reg.open(reg.m.HKEY_LOCAL_MACHINE, FOLDER_DESCRIPTIONS)
    if root is None:
        return [], "unavailable"
    items: list[dict[str, Any]] = []
    status = "ok"
    seen: set[str] = set()
    try:
        names = reg.subkeys(root, MAX_FOLDERS + 1)
        if len(names) > MAX_FOLDERS:
            names, status = names[:MAX_FOLDERS], "truncated"
        for guid in names:
            if time.monotonic() > deadline:
                return items, "truncated"
            key = reg.open(root, guid)
            if key is None:
                continue
            try:
                name = _clean_text(reg.value(key, "Name"), 80)
                localized = _display_string(reg.value(key, "LocalizedName"))
            finally:
                reg.close(key)
            if not name or not catalog._FOLDER_RE.match(name) or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            items.append({"name": name, "guid": guid.upper() if _CLSID_RE.match(guid) else None,
                          "title": localized or name})
    finally:
        reg.close(root)
    return items, status


def _discover_files(system32: str, deadline: float) -> tuple[list[dict[str, Any]], str]:
    items: list[dict[str, Any]] = []
    status = "ok"
    try:
        with os.scandir(system32) as iterator:
            for count, entry in enumerate(iterator):
                if count >= MAX_FILES or time.monotonic() > deadline:
                    status = "truncated"
                    break
                lowered = entry.name.casefold()
                if not lowered.endswith((".msc", ".cpl")) or not catalog._FILE_RE.match(entry.name):
                    continue
                try:
                    if not entry.is_file():
                        continue
                except OSError:
                    continue
                items.append({"file": entry.name, "path": entry.path,
                              "kind": "msc" if lowered.endswith(".msc") else "cpl"})
    except OSError:
        return [], "unavailable"
    return items, status


def _probe_clsids(reg: _Registry, clsids: list[str], deadline: float) -> dict[str, bool]:
    present: dict[str, bool] = {}
    for clsid in clsids[:MAX_CLSID_PROBES]:
        if time.monotonic() > deadline:
            break
        key = reg.open(reg.m.HKEY_CLASSES_ROOT, "CLSID\\" + clsid)
        present[clsid] = key is not None
        reg.close(key)
    return present


def _probe_utilities(root: str) -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    folders = (system32_directory(root), root)
    for entry in catalog.STATIC_SURFACES:
        if entry["kind"] != "utility" or entry["file"] in found:
            continue
        found[entry["file"]] = next(
            (os.path.join(folder, entry["file"]) for folder in folders
             if os.path.isfile(os.path.join(folder, entry["file"]))), None)
    return found


def discover(*, winreg_module: Any = "default", windows_root: str | None = None,
             use_cache: bool = True, force: bool = False) -> dict[str, Any]:
    """Enumerate registered surfaces. Bounded, cached and safe to call off Windows."""
    custom = winreg_module != "default" or windows_root is not None
    now = time.monotonic()
    if use_cache and not force and not custom:
        with _cache_lock:
            cached = _cache.get("discovery")
            if cached and now - cached[0] < CACHE_TTL_SECONDS:
                return cached[1]
    module = _winreg if winreg_module == "default" else winreg_module
    root = windows_root or windows_directory()
    started = time.monotonic()
    deadline = started + TIME_BUDGET_SECONDS
    status: dict[str, str] = {}
    control_panel: list[dict[str, Any]] = []
    folders: list[dict[str, Any]] = []
    clsid_present: dict[str, bool] = {}
    reg = _Registry(module) if module is not None else None
    if reg is None:
        status["control_panel"] = status["known_folders"] = status["clsid_probe"] = "unavailable"
    else:
        for name, func in (("control_panel", _discover_control_panel), ("known_folders", _discover_known_folders)):
            try:
                rows, state = func(reg, deadline)
            except Exception as exc:  # noqa: BLE001 - discovery must degrade, never crash callers
                rows, state = [], f"error:{type(exc).__name__}"
            status[name] = state
            if name == "control_panel":
                control_panel = rows
            else:
                folders = rows
        wanted = sorted({e["clsid"] for e in catalog.STATIC_SURFACES if e.get("clsid")})
        try:
            clsid_present = _probe_clsids(reg, wanted, deadline)
            status["clsid_probe"] = "ok"
        except Exception as exc:  # noqa: BLE001
            status["clsid_probe"] = f"error:{type(exc).__name__}"
    if os.name == "nt" or windows_root is not None:
        files, status["system32_files"] = _discover_files(system32_directory(root), deadline)
        utilities = _probe_utilities(root)
        status["utilities"] = "ok"
    else:
        files, utilities = [], {}
        status["system32_files"] = status["utilities"] = "unavailable"
    result = {
        "control_panel": control_panel, "files": files, "known_folders": folders,
        "clsid_present": clsid_present, "utilities": utilities, "status": status,
        "windows_root": root, "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    if not custom:
        with _cache_lock:
            _cache["discovery"] = (time.monotonic(), result)
            _cache.pop("merged", None)
    return result


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _ok(state: str | None) -> bool:
    return state in {"ok", "truncated"}


def _unique_id(base: str, taken: set[str]) -> str:
    candidate, index = base, 2
    while candidate in taken:
        candidate, index = f"{base}_{index}", index + 1
    taken.add(candidate)
    return candidate


def merge(static: tuple[dict[str, Any], ...] | list[dict[str, Any]], found: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge discovery into the static catalogue: dedupe, mark source and presence."""
    status = found.get("status", {})
    cp_by_name = {i["canonical_name"].casefold(): i for i in found.get("control_panel", []) if i.get("canonical_name")}
    cp_by_clsid = {i["clsid"]: i for i in found.get("control_panel", [])}
    files = {i["file"].casefold(): i for i in found.get("files", [])}
    folders = {i["name"].casefold(): i for i in found.get("known_folders", [])}
    clsid_present = found.get("clsid_present", {})
    utilities = found.get("utilities", {})
    used_clsids: set[str] = set()
    used_files: set[str] = set()
    used_folders: set[str] = set()
    merged: list[dict[str, Any]] = []

    for original in static:
        entry = dict(original)
        entry["aliases"] = list(original.get("aliases") or ())
        kind = entry["kind"]
        hit: dict[str, Any] | None = None
        if kind in {"control_name", "shell_clsid"}:
            if kind == "control_name":
                hit = cp_by_name.get(entry["canonical_name"].casefold())
            if hit is None and entry.get("clsid"):
                hit = cp_by_clsid.get(entry["clsid"])
            if hit is not None:
                used_clsids.add(hit["clsid"])
            elif kind == "shell_clsid" and entry.get("clsid") in clsid_present:
                # A missing CLSID only disproves a namespace; control.exe /name items can
                # still be registered through other paths, so they stay "unknown".
                entry["present"] = clsid_present[entry["clsid"]]
            elif kind == "control_name" and clsid_present.get(entry.get("clsid") or ""):
                entry["present"] = True
        elif kind in {"msc", "cpl"} and _ok(status.get("system32_files")):
            hit = files.get(entry["file"].casefold())
            if hit is not None:
                used_files.add(entry["file"].casefold())
                entry["path"] = hit["path"]
            elif status.get("system32_files") == "ok":
                entry["present"] = False
        elif kind == "utility" and entry["file"] in utilities:
            path = utilities[entry["file"]]
            entry["present"] = path is not None
            if path:
                entry["path"] = path
        elif kind == "shell_folder" and _ok(status.get("known_folders")):
            hit = folders.get(entry["folder_name"].casefold())
            if hit is not None:
                used_folders.add(entry["folder_name"].casefold())
            elif status.get("known_folders") == "ok":
                entry["present"] = False
        if hit is not None:
            entry["source"] = "both"
            entry["present"] = True
        merged.append(entry)

    taken = {item["id"] for item in merged}
    discovered: list[dict[str, Any]] = []
    for item in found.get("control_panel", []):
        if item["clsid"] in used_clsids:
            continue
        common = {"category": "Control Panel", "title": item["title"], "clsid": item["clsid"],
                  "aliases": [a for a in (item.get("info"), item.get("canonical_name")) if a]}
        if item.get("canonical_name"):
            discovered.append(catalog._entry(
                id=_unique_id("cp_" + _slug(item["canonical_name"].removeprefix("Microsoft.")), taken),
                kind="control_name", target=item["canonical_name"], canonical_name=item["canonical_name"],
                **common))
        else:
            discovered.append(catalog._entry(
                id=_unique_id("clsid_" + _slug(item["clsid"]), taken), kind="shell_clsid",
                target="shell:::" + item["clsid"], **common))
    for key, item in files.items():
        if key in used_files:
            continue
        stem = item["file"].rsplit(".", 1)[0]
        discovered.append(catalog._entry(
            id=_unique_id(f"{item['kind']}_{_slug(stem)}", taken), kind=item["kind"],
            category="Management consoles" if item["kind"] == "msc" else "Control Panel applets",
            title=f"{stem} ({item['file']})", target=item["file"], file=item["file"], path=item["path"],
            aliases=[stem], risk="controlled" if item["kind"] == "msc" else "low",
            availability="Discovered in System32; not reviewed in the static catalogue."))
    for key, item in folders.items():
        if key in used_folders:
            continue
        discovered.append(catalog._entry(
            id=_unique_id("shell_" + _slug(item["name"]), taken), kind="shell_folder", category="Folders",
            title=item["title"] if item["title"] == item["name"] else f"{item['title']} ({item['name']})",
            target="shell:" + item["name"], folder_name=item["name"], aliases=[item["name"]]))
    for entry in discovered:
        entry["source"] = "discovered"
        entry["present"] = True
        try:
            catalog.validate_entry(entry)
        except ValueError:
            continue
        merged.append(entry)
    return merged


def merged_catalog(*, force: bool = False) -> list[dict[str, Any]]:
    """Static catalogue merged with cached discovery; never raises."""
    with _cache_lock:
        cached = _cache.get("merged")
        fresh = cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS
    if fresh and not force:
        return cached[1]
    try:
        found = discover(force=force)
        merged = merge(catalog.STATIC_SURFACES, found)
    except Exception:  # noqa: BLE001 - fall back to the static catalogue
        merged = [dict(item) for item in catalog.STATIC_SURFACES]
    with _cache_lock:
        _cache["merged"] = (time.monotonic(), merged)
    return merged


def summary(found: dict[str, Any] | None = None, merged: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    found = found if found is not None else discover()
    merged = merged if merged is not None else merge(catalog.STATIC_SURFACES, found)
    by_source: dict[str, int] = {}
    by_present: dict[str, int] = {}
    for entry in merged:
        by_source[entry["source"]] = by_source.get(entry["source"], 0) + 1
        key = str(entry["present"]).lower()
        by_present[key] = by_present.get(key, 0) + 1
    return {
        "discovered": {
            "control_panel_items": len(found.get("control_panel", [])),
            "system32_msc": sum(1 for f in found.get("files", []) if f["kind"] == "msc"),
            "system32_cpl": sum(1 for f in found.get("files", []) if f["kind"] == "cpl"),
            "known_folders": len(found.get("known_folders", [])),
        },
        "status": found.get("status", {}),
        "elapsed_ms": found.get("elapsed_ms"),
        "merged_total": len(merged),
        "by_source": by_source,
        "by_present": by_present,
    }
