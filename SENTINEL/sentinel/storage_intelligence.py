"""Bounded, read-only storage and developer-footprint intelligence.

Only path metadata is inspected. File contents are never opened. Findings are review
candidates, not deletion instructions; this module exposes no delete/uninstall API.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import psutil

from . import core, runtime_engine

_STARTED = False
_STOP = threading.Event()
_WAKE = threading.Event()
_SCAN_LOCK = threading.Lock()
_SCAN_REQUESTED = False
_NEXT_SCAN = 0.0

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "deep_scan_interval_hours": 72,
    "max_entries": 15000,
    "max_seconds": 18,
}

SKIP_NAMES = {
    "$recycle.bin", "system volume information", "windows", "program files",
    "program files (x86)", "programdata", ".git", ".hg", ".svn",
    "node_cache", "lost+found",
}
ARTIFACT_NAMES = (".venv", "venv", "node_modules", "target", "build", "dist", "bin", "obj")


def ensure_schema() -> None:
    core.db("""CREATE TABLE IF NOT EXISTS storage_intelligence_settings(
        setting_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at REAL NOT NULL)""")
    core.db("""CREATE TABLE IF NOT EXISTS storage_scan_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT, scanned_at REAL NOT NULL,
        payload_json TEXT NOT NULL, bytes_scanned INTEGER NOT NULL DEFAULT 0,
        files_scanned INTEGER NOT NULL DEFAULT 0, partial INTEGER NOT NULL DEFAULT 0)""")
    core.db("CREATE INDEX IF NOT EXISTS ix_storage_scan_history_ts ON storage_scan_history(scanned_at)")
    now = time.time()
    for key, value in DEFAULTS.items():
        core.db("INSERT OR IGNORE INTO storage_intelligence_settings(setting_key,value_json,updated_at) VALUES(?,?,?)",
                (key, json.dumps(value, separators=(",", ":")), now))


ensure_schema()


def settings() -> dict[str, Any]:
    values = dict(DEFAULTS)
    for key, raw in core.db("SELECT setting_key,value_json FROM storage_intelligence_settings"):
        if key in DEFAULTS:
            try:
                values[key] = json.loads(raw)
            except (TypeError, ValueError):
                pass
    return values


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    global _NEXT_SCAN, _SCAN_REQUESTED
    if not isinstance(payload, dict):
        raise ValueError("storage settings payload must be an object")
    current = settings()
    updated = dict(current)
    for key, value in payload.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown storage setting: {key}")
        if key == "enabled":
            if not isinstance(value, bool):
                raise ValueError("enabled must be a boolean")
        elif key == "deep_scan_interval_hours":
            if isinstance(value, bool) or not isinstance(value, int) or not 24 <= value <= 720:
                raise ValueError("deep_scan_interval_hours must be from 24 to 720")
        elif key == "max_entries":
            if isinstance(value, bool) or not isinstance(value, int) or not 1000 <= value <= 50000:
                raise ValueError("max_entries must be from 1000 to 50000")
        elif key == "max_seconds":
            if isinstance(value, bool) or not isinstance(value, int) or not 5 <= value <= 45:
                raise ValueError("max_seconds must be from 5 to 45")
        updated[key] = value
    now = time.time()
    for key, value in updated.items():
        if current.get(key) != value or not core.db(
            "SELECT 1 FROM storage_intelligence_settings WHERE setting_key=?", (key,)
        ):
            core.db(
                "INSERT INTO storage_intelligence_settings(setting_key,value_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(setting_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                (key, json.dumps(value, separators=(",", ":")), now),
            )
    if "deep_scan_interval_hours" in payload:
        previous_scan = core.db("SELECT MAX(scanned_at) FROM storage_scan_history")[0][0] or 0
        _NEXT_SCAN = max(time.time() + 60, float(previous_scan) + int(updated["deep_scan_interval_hours"]) * 3600
                         if previous_scan else time.time() + 90)
    if payload.get("enabled") is False:
        _SCAN_REQUESTED = False
    _WAKE.set()
    core.log("storage-intelligence", "persistent storage intelligence settings updated", "info",
             changed_keys=sorted(payload.keys()))
    return settings()


def _local_roots() -> list[tuple[str, str, str]]:
    """Return selected user/cache/developer roots; never enumerate an entire drive."""
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    candidates: list[tuple[str, str, str]] = [
        ("Downloads", str(home / "Downloads"), "user-files"),
        ("Desktop", str(home / "Desktop"), "user-files"),
        ("Documents", str(home / "Documents"), "user-files"),
        ("Pictures", str(home / "Pictures"), "user-files"),
        ("Videos", str(home / "Videos"), "user-files"),
        ("Music", str(home / "Music"), "user-files"),
        ("Saved Games", str(home / "Saved Games"), "user-files"),
        ("Windows temporary files", str(local / "Temp"), "temporary"),
        ("Python package cache", str(local / "pip" / "Cache"), "python-cache"),
        ("Python package cache", str(home / ".cache" / "pip"), "python-cache"),
        ("Python user packages", str(roaming / "Python"), "python-packages"),
        ("Python environments", str(home / ".virtualenvs"), "python-environments"),
        ("SENTINEL runtime Python packages", str(Path(sys.prefix) / "Lib" / "site-packages"), "python-packages"),
        ("npm cache", str(local / "npm-cache"), "node-cache"),
        ("npm cache", str(home / ".npm"), "node-cache"),
        ("pnpm store", str(local / "pnpm" / "store"), "node-cache"),
        ("Yarn cache", str(local / "Yarn" / "Cache"), "node-cache"),
        ("Rust package cache", str(home / ".cargo" / "registry"), "rust-cache"),
        ("NuGet package cache", str(home / ".nuget" / "packages"), "dotnet-cache"),
        ("Gradle cache", str(home / ".gradle" / "caches"), "java-cache"),
        ("Maven repository", str(home / ".m2" / "repository"), "java-cache"),
    ]
    for parent in (local / "Programs" / "Python", home / "AppData" / "Local" / "Programs" / "Python"):
        try:
            for install in sorted(parent.iterdir())[:8]:
                candidates.append(("Python site-packages", str(install / "Lib" / "site-packages"), "python-packages"))
        except OSError:
            pass
    # Discover common project folders one level below known workspaces. Only known
    # generated/dependency directories are measured; project source is not read.
    for workspace in ("source/repos", "Projects", "projects", "workspace", "dev", "Development", "Code"):
        base = home / workspace
        try:
            children = sorted(base.iterdir(), key=lambda item: item.name.casefold())[:30]
        except OSError:
            continue
        for project in children:
            if not project.is_dir() or project.is_symlink():
                continue
            for artifact in ARTIFACT_NAMES:
                try:
                    target = project / artifact
                    if target.is_dir() and not target.is_symlink():
                        category = "python-environments" if artifact in (".venv", "venv") else (
                            "node-dependencies" if artifact == "node_modules" else "build-output")
                        candidates.append((f"{project.name} / {artifact}", str(target), category))
                except OSError:
                    continue
    # For secondary data volumes, inspect top-level data folders as bounded roots.
    # The OS volume is represented by the curated user/cache roots above to avoid a
    # broad recursive walk through Windows and Program Files.
    system_drive = os.path.splitdrive(os.environ.get("SystemDrive", "C:").strip())[0].casefold()
    if os.name == "nt":
        partitions = psutil.disk_partitions(all=False)
    else:
        partitions = []
    for part in partitions:
        mount = os.path.abspath(str(part.mountpoint or ""))
        mount_drive = os.path.splitdrive(mount)[0].casefold()
        if not mount or (system_drive and mount_drive == system_drive):
            continue
        try:
            children = sorted(os.scandir(mount), key=lambda item: item.name.casefold())
        except OSError:
            continue
        for entry in children[:20]:
            try:
                if not entry.is_dir(follow_symlinks=False) or entry.is_symlink() or entry.name.casefold() in SKIP_NAMES:
                    continue
                candidates.append((f"{os.path.basename(mount.rstrip(os.sep)) or mount} / {entry.name}",
                                   entry.path, "drive-directory"))
            except OSError:
                continue
    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for label, raw_path, category in candidates:
        path = os.path.abspath(os.path.expandvars(raw_path))
        key = os.path.normcase(path)
        if key in seen or not os.path.isdir(path):
            continue
        seen.add(key)
        found.append((label, path, category))
    return found[:100]


def _hidden(entry: os.DirEntry[str], stat_result: os.stat_result) -> bool:
    attrs = getattr(stat_result, "st_file_attributes", 0)
    return bool(attrs & 0x2) or entry.name.startswith(".")


def category_is_node_dependencies(path: str) -> bool:
    return os.path.basename(os.path.normpath(path)).casefold() == "node_modules"


def _measure(path: str, max_entries: int, deadline: float, category: str = "") -> dict[str, Any]:
    """Count directory metadata only, with one shared time/entry budget."""
    total_bytes = files = dirs = hidden_files = hidden_bytes = 0
    extension_bytes: dict[str, int] = defaultdict(int)
    newest_mtime = 0.0
    oldest_atime = time.time()
    newest_atime = 0.0
    top_level_access: dict[str, float] = defaultdict(float)
    partial = False
    stack: list[tuple[str, int, str, bool]] = [(path, 0, "", False)]
    top_level_bytes: dict[str, int] = defaultdict(int)
    visited = 0
    while stack:
        if visited >= max_entries or time.monotonic() >= deadline:
            partial = True
            break
        folder, depth, package_name, in_hidden_dir = stack.pop()
        try:
            entries = os.scandir(folder)
        except (OSError, PermissionError):
            continue
        with entries:
            for entry in entries:
                if visited >= max_entries or time.monotonic() >= deadline:
                    partial = True
                    break
                visited += 1
                try:
                    stat_result = entry.stat(follow_symlinks=False)
                except (OSError, PermissionError):
                    continue
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    dirs += 1
                    if depth < 5 and entry.name.casefold() not in SKIP_NAMES:
                        # Direct package folders become individual buckets.
                        # Scoped npm packages are named @scope/package rather than
                        # collapsed into one @scope aggregate.
                        if category_is_node_dependencies(path) and depth == 1 and package_name.startswith("@"):
                            child_group = package_name + "/" + entry.name
                        elif category == "python-environments" and depth == 2 and os.path.basename(folder).casefold() == "site-packages":
                            child_group = entry.name
                        elif category == "python-packages" and depth == 0 and os.path.basename(path).casefold() == "site-packages":
                            child_group = entry.name
                        else:
                            child_group = entry.name if depth == 0 else package_name
                        stack.append((entry.path, depth + 1, child_group,
                                      in_hidden_dir or _hidden(entry, stat_result)))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                size = max(0, int(stat_result.st_size))
                files += 1
                total_bytes += size
                if package_name:
                    top_level_bytes[package_name] += size
                newest_mtime = max(newest_mtime, float(stat_result.st_mtime or 0))
                if stat_result.st_atime:
                    access_time = float(stat_result.st_atime)
                    oldest_atime = min(oldest_atime, access_time)
                    newest_atime = max(newest_atime, access_time)
                    if package_name:
                        top_level_access[package_name] = max(top_level_access[package_name], access_time)
                if in_hidden_dir or _hidden(entry, stat_result):
                    hidden_files += 1
                    hidden_bytes += size
                suffix = Path(entry.name).suffix.casefold() or "[no extension]"
                extension_bytes[suffix] += size
    return {
        "path": path[:320], "bytes": total_bytes, "files": files, "directories": dirs,
        "hidden_files": hidden_files, "hidden_bytes": hidden_bytes,
        "newest_write_at": newest_mtime or None,
        "oldest_access_at": oldest_atime if oldest_atime < time.time() else None,
        "newest_access_at": newest_atime or None,
        "extensions": dict(extension_bytes),
        "top_level": [
            {"name": name, "bytes": size,
             "newest_access_at": top_level_access.get(name) or None,
             "last_access_age_days": max(0, int((time.time() - top_level_access[name]) / 86400))
                 if top_level_access.get(name) else None}
            for name, size in sorted(top_level_bytes.items(), key=lambda item: item[1], reverse=True)[:30]
        ],
        "entries_visited": visited, "partial": partial,
    }


def _drive_summary() -> list[dict[str, Any]]:
    drives: list[dict[str, Any]] = []
    try:
        for part in psutil.disk_partitions(all=False):
            mount = str(part.mountpoint or "")
            if not mount:
                continue
            try:
                usage = psutil.disk_usage(mount)
            except (OSError, PermissionError):
                continue
            total = int(usage.total)
            free = int(usage.free)
            used = int(usage.used)
            drives.append({
                "mountpoint": mount, "filesystem": str(part.fstype or ""),
                "total_bytes": total, "used_bytes": used, "free_bytes": free,
                "used_percent": round(float(usage.percent), 1),
                "free_percent": round(free * 100 / total, 1) if total else 0.0,
                "status": "critical" if total and free / total < 0.05 else (
                    "low" if total and free / total < 0.12 else "normal"),
            })
    except Exception:
        pass
    return drives


def _category_label(category: str) -> str:
    return {
        "user-files": "User files",
        "temporary": "Temporary files",
        "python-cache": "Python cache",
        "python-packages": "Python packages",
        "python-environments": "Python environments",
        "node-cache": "Node.js package cache",
        "node-dependencies": "Node.js dependencies",
        "rust-cache": "Rust/Cargo cache",
        "dotnet-cache": ".NET/NuGet packages",
        "java-cache": "Java/Gradle/Maven cache",
        "build-output": "Build outputs",
        "drive-directory": "Other drive folders",
    }.get(category, category)


def scan_once(roots: list[tuple[str, str, str]] | None = None,
              max_entries: int | None = None, max_seconds: int | None = None) -> dict[str, Any]:
    """Run a bounded scan and persist a single immutable result snapshot."""
    if not _SCAN_LOCK.acquire(blocking=False):
        return {"accepted": False, "reason": "a storage scan is already running"}
    try:
        config = settings()
        entry_budget = int(max_entries or config["max_entries"])
        duration_budget = int(max_seconds or config["max_seconds"])
        deadline = time.monotonic() + max(5, min(45, duration_budget))
        selected = roots if roots is not None else _local_roots()
        root_results: list[dict[str, Any]] = []
        extension_totals: dict[str, int] = defaultdict(int)
        category_totals: dict[str, int] = defaultdict(int)
        candidates: list[dict[str, Any]] = []
        used_entries = 0
        used_bytes = 0
        partial = False
        now = time.time()
        for label, path, category in selected[:100]:
            if used_entries >= entry_budget or time.monotonic() >= deadline:
                partial = True
                break
            if not os.path.isdir(path) or os.path.islink(path):
                continue
            remaining = max(1, entry_budget - used_entries)
            root_deadline = min(deadline, time.monotonic() + 1.5)
            measured = _measure(path, remaining, root_deadline, category=category)
            used_entries += measured["entries_visited"]
            used_bytes += measured["bytes"]
            partial = partial or bool(measured["partial"])
            category_totals[category] += int(measured["bytes"])
            for extension, size in measured["extensions"].items():
                extension_totals[extension] += int(size)
            newest = measured.get("newest_write_at")
            newest_access = measured.get("newest_access_at")
            age_days = max(0, int((now - newest) / 86400)) if newest else None
            access_age_days = max(0, int((now - newest_access) / 86400)) if newest_access else None
            usage_signal = (
                "possibly-cold-weak-signal" if access_age_days is not None and access_age_days >= 60
                else "recent-access-seen" if access_age_days is not None and access_age_days <= 7
                else "unknown-or-weak"
            )
            result = {
                "label": _clean_label(label), "category": category,
                "category_label": _category_label(category), **measured,
                "last_write_age_days": age_days,
                "last_access_age_days": access_age_days,
                "usage_signal": usage_signal,
            }
            root_results.append(result)
            name = os.path.basename(path).casefold()
            size = int(measured["bytes"])
            if category in ("python-environments", "python-packages", "node-dependencies", "dotnet-cache"):
                for component in measured.get("top_level", []):
                    component_age = component.get("last_access_age_days")
                    component_size = int(component.get("bytes") or 0)
                    if component_size >= 100 * 1024 * 1024 and component_age is not None and component_age >= 60:
                        candidates.append({
                            "path": path[:320], "name": f"{label} / {component.get('name', 'package')}",
                            "bytes": component_size,
                            "reason": "Large dependency/package component with an old last-access signal",
                            "review_type": "package-usage-review",
                            "confidence": "low",
                            "usage_signal": "possibly-cold-weak-signal",
                            "last_access_age_days": int(component_age),
                            "suggestion": "Check project manifests, lockfiles and active imports before removing this package. A file timestamp is only a weak hint; use the owning package manager and keep a recovery path.",
                        })
            if size >= 150 * 1024 * 1024 and category in (
                "temporary", "python-cache", "node-cache", "rust-cache",
                "dotnet-cache", "java-cache", "build-output", "node-dependencies",
            ):
                candidates.append({
                    "path": path[:320], "name": label, "bytes": size,
                    "reason": f"Large {_category_label(category).lower()} footprint",
                    "review_type": "cache-or-generated-output",
                    "confidence": "medium",
                    "suggestion": "Review whether this cache/build output is still needed. Close related tools first and use the owning package manager or build tool to clean it; do not delete it while a build or installer is active.",
                })
            if category == "drive-directory" and size >= 1024 * 1024 * 1024:
                candidates.append({
                    "path": path[:320], "name": label, "bytes": size,
                    "reason": "Large top-level folder on a secondary data drive",
                    "review_type": "large-drive-folder",
                    "confidence": "medium" if measured.get("last_access_age_days") is not None else "low",
                    "usage_signal": usage_signal,
                    "suggestion": "Inspect its largest subfolders and package/file types. Confirm the owning application or game before moving anything; folder size or old timestamps alone do not make the contents safe to delete.",
                })
            if name == "downloads" and age_days is not None and age_days >= 60 and size >= 300 * 1024 * 1024:
                candidates.append({
                    "path": path[:320], "name": label, "bytes": size,
                    "reason": "Large Downloads folder with old files",
                    "review_type": "user-file-review",
                    "confidence": "low",
                    "suggestion": "Sort by size and last modified date, then review installers and archives individually. Folder age does not prove that its contents are unused.",
                })
            if measured["hidden_files"] and measured["hidden_bytes"] >= 100 * 1024 * 1024:
                candidates.append({
                    "path": path[:320], "name": label, "bytes": measured["hidden_bytes"],
                    "reason": "Large hidden-file footprint",
                    "review_type": "hidden-file-review",
                    "confidence": "low",
                    "suggestion": "Inspect hidden paths individually. Hidden files often contain application settings, credentials or active caches; do not bulk-delete them.",
                })
        drive_rows = _drive_summary()
        if any(drive["status"] in ("low", "critical") for drive in drive_rows):
            candidates.insert(0, {
                "path": "", "name": "Drive capacity", "bytes": 0,
                "reason": "A drive has low free capacity",
                "review_type": "capacity-review", "confidence": "high",
                "suggestion": "Use the ranked directory and extension report to find large review candidates. SENTINEL will not delete or move data automatically.",
            })
        top_extensions = sorted(extension_totals.items(), key=lambda item: item[1], reverse=True)[:24]
        top_roots = sorted(root_results, key=lambda item: item["bytes"], reverse=True)[:30]
        candidates.sort(key=lambda item: item["bytes"], reverse=True)
        payload = {
            "scanned_at": now, "scan_mode": "bounded-read-only",
            "drives": drive_rows, "roots": top_roots,
            "language_footprints": [
                {"name": _category_label(key), "bytes": value, "category": key}
                for key, value in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
                if key in {"python-cache", "python-packages", "python-environments", "node-cache",
                           "node-dependencies", "rust-cache", "dotnet-cache", "java-cache", "build-output"}
            ],
            "extensions": [{"extension": key, "bytes": value} for key, value in top_extensions],
            "review_candidates": candidates[:30],
            "coverage": {"entries_visited": used_entries, "bytes_metadata_total": used_bytes,
                         "roots_measured": len(root_results), "partial": partial or len(root_results) < len(selected)},
            "usage_caveat": "File usage is not directly instrumented. Last-access metadata can be disabled or coarse on Windows; last-write age is a heuristic, not proof that content is unused.",
            "safety": {"file_contents_opened": False, "files_deleted": 0,
                       "packages_uninstalled": 0, "system_paths_scanned": False},
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(raw.encode("utf-8")) > 3 * 1024 * 1024:
            payload["review_candidates"] = payload["review_candidates"][:12]
            payload["roots"] = payload["roots"][:12]
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        core.db(
            "INSERT INTO storage_scan_history(scanned_at,payload_json,bytes_scanned,files_scanned,partial) VALUES(?,?,?,?,?)",
            (now, raw, used_bytes, used_entries, int(partial)),
        )
        core.db("DELETE FROM storage_scan_history WHERE id NOT IN (SELECT id FROM storage_scan_history ORDER BY id DESC LIMIT 12)")
        core.persist_snapshot("storage_intelligence", payload)
        core.STATE["storage_intelligence"] = payload
        core.log("storage-intelligence", "bounded read-only storage scan completed", "ok",
                 roots=len(root_results), entries=used_entries, partial=partial)
        return payload
    finally:
        _SCAN_LOCK.release()


def _clean_label(value: str) -> str:
    return " ".join(str(value or "").split())[:100]


def status() -> dict[str, Any]:
    rows = core.db("SELECT id,scanned_at,payload_json,bytes_scanned,files_scanned,partial FROM storage_scan_history ORDER BY id DESC LIMIT 1")
    if not rows:
        return {"available": False, "settings": settings(), "snapshot": None, "next_scan_at": _NEXT_SCAN}
    row = rows[0]
    try:
        payload = json.loads(row[2])
    except (ValueError, TypeError):
        payload = {}
    return {
        "available": True, "settings": settings(),
        "scan": {"id": row[0], "scanned_at": row[1], "bytes_scanned": row[3],
                 "entries_visited": row[4], "partial": bool(row[5])},
        "snapshot": payload, "next_scan_at": _NEXT_SCAN,
    }


def request_scan() -> dict[str, Any]:
    global _SCAN_REQUESTED
    _SCAN_REQUESTED = True
    _WAKE.set()
    core.log("storage-intelligence", "manual read-only storage scan requested; waiting for safe resource window", "info")
    return {"accepted": True, "state": "queued", "message": "The agent will start the scan when CPU, memory and foreground workload permit."}


def _resources_allow_scan() -> tuple[bool, str]:
    try:
        return runtime_engine.admit_optional_work(
            "storage intelligence", min_available_gib=4.0, max_cpu_percent=45.0,
        )
    except Exception as exc:
        return False, f"resource state unavailable: {type(exc).__name__}"


def _worker() -> None:
    global _NEXT_SCAN, _SCAN_REQUESTED
    previous = core.db("SELECT MAX(scanned_at) FROM storage_scan_history")[0][0] or 0
    interval = int(settings()["deep_scan_interval_hours"]) * 3600
    _NEXT_SCAN = max(time.time() + 60, float(previous) + interval if previous else time.time() + 90)
    while not _STOP.is_set():
        config = settings()
        requested = _SCAN_REQUESTED
        due = time.time() >= _NEXT_SCAN
        if config.get("enabled") and (requested or due):
            permitted, reason = _resources_allow_scan()
            if permitted:
                _SCAN_REQUESTED = False
                try:
                    result = scan_once()
                    if result.get("accepted") is not False:
                        interval = int(settings()["deep_scan_interval_hours"]) * 3600
                        _NEXT_SCAN = time.time() + interval
                except Exception as exc:
                    core.log("storage-intelligence", f"scan failed: {type(exc).__name__}: {str(exc)[:160]}", "warn")
                    _NEXT_SCAN = time.time() + 1800
            else:
                core.heartbeat("storage intelligence", 30, reason)
                _NEXT_SCAN = max(_NEXT_SCAN, time.time() + 120)
        elif not config.get("enabled"):
            core.heartbeat("storage intelligence", 30, "paused by persistent configuration")
        _WAKE.wait(30)
        _WAKE.clear()


def start() -> None:
    global _STARTED
    if _STARTED:
        return
    ensure_schema()
    _STOP.clear()
    _WAKE.clear()
    _STARTED = True
    core.thread(_worker, "storage-intelligence")


def shutdown() -> None:
    _STOP.set()
    _WAKE.set()
