"""Safe installed-application resolution and launch without shell command strings."""
from __future__ import annotations

import os
from pathlib import Path
from apex.windows.app_catalog import AppDiscovery


def _all_records(store=None):
    records = AppDiscovery().registry_records()
    if store is not None:
        for row in store.list_apps():
            records.append(type("StoredApp", (), {
                "display_name": row["display_name"], "executable_path": row["executable_path"],
                "aumid": row["aumid"], "aliases": tuple(row["aliases"]),
                "publisher": row["metadata"].get("publisher"), "version": row["metadata"].get("version"),
                "source": row["source"], "trust_state": row["trust_state"], "available": row["available"]})())
    unique = {}
    for row in records:
        key = (getattr(row, "aumid", None) or row.executable_path or row.display_name).casefold()
        unique.setdefault(key, row)
    return list(unique.values())


def discover_applications(store=None) -> dict:
    if os.name != "nt":
        raise OSError("application discovery requires Windows")
    records = _all_records(store)
    if store is not None:
        for row in records:
            store.upsert_app(display_name=row.display_name, executable_path=row.executable_path,
                             aumid=getattr(row, "aumid", None), aliases=list(row.aliases),
                             metadata={"publisher": row.publisher, "version": row.version},
                             trust_state=row.trust_state, source=row.source, available=row.available)
    return {"count": len(records), "applications": [
        {"display_name": row.display_name, "executable_path": row.executable_path,
         "aumid": getattr(row, "aumid", None), "aliases": list(row.aliases),
         "publisher": row.publisher, "version": row.version,
         "source": row.source, "trust_state": row.trust_state, "available": row.available}
        for row in records[:1000]], "source": "Windows App Paths, Uninstall, Start Menu and AppsFolder metadata"}


def launch_application(name: str, store=None) -> dict:
    if os.name != "nt":
        raise OSError("application launching requires Windows")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError("application name must contain 1 to 120 characters")
    records = _all_records(store)
    matches = AppDiscovery.resolve(records, name)
    if not matches:
        raise LookupError(f"No registered executable or packaged app matched '{name}'.")
    paths = {str(Path(item.executable_path).resolve()) for item in matches
             if item.executable_path and Path(item.executable_path).is_file()}
    package_ids = {getattr(item, "aumid", None) for item in matches if getattr(item, "aumid", None)}
    if len(paths) == 1 and not package_ids:
        target = next(iter(paths))
        executable = Path(target)
        if not executable.is_file():
            raise FileNotFoundError("resolved application executable no longer exists")
        forbidden_parts = {"downloads", "temp", "tmp", "cache", "caches", "$recycle.bin"}
        if any(part.casefold() in forbidden_parts for part in executable.parts):
            raise PermissionError("application candidates in Downloads, temporary or cache paths are blocked by default")
        stat = executable.lstat()
        if executable.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
            raise PermissionError("reparse-point application targets are not launchable")
        os.startfile(str(executable))
        return {"summary": f"Dispatched application launch: {executable.name}.", "application": name,
                "executable_path": str(executable), "trust_state": matches[0].trust_state, "verified": False,
                "verification": "Launch request dispatched; process and window readiness require a fresh inventory check."}
    if not paths and len(package_ids) == 1:
        aumid = next(iter(package_ids))
        os.startfile(f"shell:AppsFolder\\{aumid}")
        return {"summary": f"Dispatched packaged application launch: {matches[0].display_name}.",
                "application": name, "aumid": aumid, "verified": False,
                "verification": "Packaged-app launch request dispatched; process/window readiness requires a fresh inventory check."}
    choices = sorted({item.display_name for item in matches})[:8]
    raise ValueError("Application resolution is ambiguous or has no verified executable/AUMID: " + ", ".join(choices))
