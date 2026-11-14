"""Metadata-only installed application discovery; never reads user document contents."""
from __future__ import annotations
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

@dataclass(frozen=True, slots=True)
class AppRecord:
    display_name: str
    executable_path: str | None
    aliases: tuple[str, ...]
    publisher: str | None
    version: str | None
    source: str
    trust_state: str = "unknown"
    available: bool = False
    aumid: str | None = None

class AppDiscovery:
    EXCLUDED_DIRS = {"$recycle.bin", "system volume information", "winsxs", "windows installer",
                     "softwaredistribution", "installer", "temp", "cache", "caches", "windowsapps"}

    def registry_records(self) -> list[AppRecord]:
        if os.name != "nt":
            return []
        import winreg
        records: dict[str, AppRecord] = {}
        hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
        views = (getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0))
        key_path = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
        for hive in hives:
            for view in views:
                try:
                    with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as root:
                        for i in range(winreg.QueryInfoKey(root)[0]):
                            try:
                                sub = winreg.EnumKey(root, i)
                                with winreg.OpenKey(root, sub) as app_key:
                                    raw, _ = winreg.QueryValueEx(app_key, None)
                                path = os.path.expandvars(str(raw)).strip().strip('"')
                                if Path(path).is_file():
                                    name = Path(sub).stem
                                    records[path.casefold()] = AppRecord(name, path, (name, sub), None, None,
                                                                          "app_paths", "unknown", True)
                            except OSError:
                                continue
                except OSError:
                    pass
        uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
        for hive in hives:
            for view in views:
                try:
                    with winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | view) as root:
                        for i in range(winreg.QueryInfoKey(root)[0]):
                            try:
                                with winreg.OpenKey(root, winreg.EnumKey(root, i)) as app_key:
                                    values = {}
                                    for key in ("DisplayName", "Publisher", "DisplayVersion", "DisplayIcon", "InstallLocation"):
                                        try:
                                            values[key] = winreg.QueryValueEx(app_key, key)[0]
                                        except OSError:
                                            pass
                                name = str(values.get("DisplayName", "")).strip()
                                if not name:
                                    continue
                                raw = str(values.get("DisplayIcon", "")).strip().strip('"').split(",", 1)[0]
                                path = os.path.expandvars(raw) if raw.lower().endswith(".exe") else None
                                if path and not Path(path).is_file():
                                    path = None
                                record = AppRecord(name, path, (name,), str(values.get("Publisher") or "") or None,
                                                   str(values.get("DisplayVersion") or "") or None,
                                                   "uninstall_registry", "unknown", bool(path))
                                records.setdefault((path or f"name:{name}").casefold(), record)
                            except OSError:
                                continue
                except OSError:
                    pass
        for root in self._start_menu_roots():
            records.update({row.executable_path.casefold(): row for row in self._shortcut_records(root)
                            if row.executable_path})
        for row in self._packaged_app_records():
            records[f"aumid:{row.aumid.casefold()}"] = row
        return list(records.values())

    @staticmethod
    def _packaged_app_records() -> list[AppRecord]:
        """Enumerate Start-menu package identities through the Shell AppsFolder namespace."""
        if os.name != "nt":
            return []
        try:
            import win32com.client
            shell = win32com.client.Dispatch("Shell.Application")
            namespace = shell.NameSpace("shell:AppsFolder")
            if namespace is None:
                return []
            found: list[AppRecord] = []
            for item in namespace.Items():
                try:
                    name = str(item.Name or "").strip()
                    aumid = str(item.ExtendedProperty("System.AppUserModel.ID") or "").strip()
                    if not aumid:
                        item_path = str(item.Path or "")
                        if "!" in item_path:
                            aumid = item_path.rsplit("\\", 1)[-1].strip()
                    if not name or not aumid or "!" not in aumid or len(aumid) > 300:
                        continue
                    found.append(AppRecord(name, None, (name,), None, None,
                                           "shell_apps_folder", "package", True, aumid))
                except Exception:
                    continue
            return found
        except Exception:
            return []

    @staticmethod
    def _start_menu_roots() -> list[Path]:
        roots = []
        for raw in (os.environ.get("APPDATA"), os.environ.get("PROGRAMDATA")):
            if raw:
                roots.append(Path(raw) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
        return [root for root in roots if root.is_dir()]

    @staticmethod
    def _shortcut_records(root: Path) -> list[AppRecord]:
        try:
            import win32com.client
        except ImportError:
            return []
        shell = win32com.client.Dispatch("WScript.Shell")
        found: list[AppRecord] = []
        for path in root.rglob("*.lnk"):
            try:
                shortcut = shell.CreateShortcut(str(path))
                target = os.path.expandvars(str(shortcut.TargetPath or "")).strip()
                if not target.lower().endswith(".exe") or not Path(target).is_file():
                    continue
                name = path.stem
                found.append(AppRecord(name, str(Path(target).resolve()), (name, Path(target).stem),
                                        None, None, "start_menu_shortcut", "unknown", True))
            except Exception:
                continue
        return found

    def scan_volume(self, root: str | Path, *, cancel: threading.Event | None = None,
                    max_files: int = 20_000, max_seconds: float = 60.0) -> Iterator[AppRecord]:
        if isinstance(max_files, bool) or not 1 <= max_files <= 50_000:
            raise ValueError("max_files must be from 1 through 50000")
        if isinstance(max_seconds, bool) or not 1.0 <= max_seconds <= 300.0:
            raise ValueError("max_seconds must be from 1 through 300")
        if os.name != "nt":
            raise OSError("application volume scanning requires Windows")
        root_path = Path(root).resolve(strict=True)
        if not root_path.is_dir() or not root_path.drive or root_path != Path(root_path.anchor):
            raise ValueError("root must be the root of an accessible local volume")
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(str(root_path)) != 3:
            raise ValueError("application scan is restricted to fixed local volumes")
        cancelled = cancel or threading.Event()
        started = time.monotonic()
        seen = 0
        stack = [root_path]
        while (stack and not cancelled.is_set() and seen < max_files
               and time.monotonic() - started < max_seconds):
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        if (cancelled.is_set() or seen >= max_files
                                or time.monotonic() - started >= max_seconds):
                            break
                        try:
                            stat = entry.stat(follow_symlinks=False)
                            if entry.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name.casefold() not in self.EXCLUDED_DIRS:
                                    stack.append(Path(entry.path))
                                continue
                            if not entry.is_file(follow_symlinks=False) or not entry.name.lower().endswith(".exe"):
                                continue
                            seen += 1
                            if seen % 100 == 0:
                                time.sleep(0.01)
                            path = Path(entry.path)
                            yield AppRecord(path.stem, str(path), (path.stem, path.name), None, None,
                                            "volume_scan", "unknown", True)
                        except OSError:
                            continue
            except OSError:
                continue

    @staticmethod
    def resolve(records: list[AppRecord], name: str) -> list[AppRecord]:
        query = name.casefold().strip()
        if not query:
            return []
        exact = [r for r in records if r.display_name.casefold() == query or any(a.casefold() == query for a in r.aliases)]
        return exact or [r for r in records if query in r.display_name.casefold() or any(query in a.casefold() for a in r.aliases)]
