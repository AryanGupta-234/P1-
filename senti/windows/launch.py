"""Safe installed-application resolution, preview, launch and verification without shell strings.

Candidates come dynamically from App Paths, the Uninstall registry, Start Menu shortcuts and the
Shell AppsFolder (packaged-app AUMIDs). Resolution is ranked (token, initials, fuzzy, alias and
publisher signals); ambiguity returns scored candidates instead of guessing.
"""
from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from senti.windows.app_catalog import (
    AppDiscovery,
    AppRecord,
    Candidate,
    pick_unambiguous,
    rank_candidates,
    record_names,
)

_FORBIDDEN_PARTS = {"downloads", "temp", "tmp", "cache", "caches", "$recycle.bin"}
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_NOASYNC = 0x00000100
_SW_SHOWNORMAL = 1


# ---------------------------------------------------------------------------
# ShellExecuteExW (shared with the uninstall provider)
# ---------------------------------------------------------------------------

def shell_execute(file: str, parameters: str | None = None, *, verb: str | None = None,
                  directory: str | None = None, show: int = _SW_SHOWNORMAL) -> int | None:
    """Start ``file`` through ShellExecuteExW and return the new process id when Windows reports one.

    ``verb="runas"`` makes Windows show its real UAC consent prompt. Raises ``OSError`` with
    ``winerror`` set (1223 when the user declines UAC).
    """
    if os.name != "nt":
        raise OSError("ShellExecuteExW requires Windows")
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel32.GetProcessId.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_NOASYNC
    info.lpVerb = verb
    info.lpFile = file
    info.lpParameters = parameters
    info.lpDirectory = directory
    info.nShow = show
    # COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE, as ShellExecuteEx documentation requires.
    hr = ole32.CoInitializeEx(None, 0x2 | 0x4)
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            code = ctypes.get_last_error()
            raise ctypes.WinError(code)
    finally:
        if hr in (0, 1):
            ole32.CoUninitialize()
    if not info.hProcess:
        return None
    try:
        return int(kernel32.GetProcessId(info.hProcess)) or None
    finally:
        kernel32.CloseHandle(info.hProcess)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def _all_records(store=None) -> list[AppRecord]:
    records = AppDiscovery().registry_records()
    if store is not None:
        for row in store.list_apps(limit=2000):
            metadata = row.get("metadata") or {}
            records.append(AppRecord(row["display_name"], row["executable_path"], tuple(row["aliases"]),
                                     metadata.get("publisher"), metadata.get("version"), row["source"],
                                     row["trust_state"], bool(row["available"]), row.get("aumid")))
    unique: dict[str, AppRecord] = {}
    for row in records:
        key = (row.aumid or row.executable_path or row.display_name).casefold()
        unique.setdefault(key, row)
    return list(unique.values())


def discover_applications(store=None) -> dict:
    if os.name != "nt":
        raise OSError("application discovery requires Windows")
    records = _all_records(store)
    if store is not None:
        for row in records:
            store.upsert_app(display_name=row.display_name, executable_path=row.executable_path,
                             aumid=row.aumid, aliases=list(row.aliases),
                             metadata={"publisher": row.publisher, "version": row.version},
                             trust_state=row.trust_state, source=row.source, available=row.available)
    return {"count": len(records), "applications": [
        {"display_name": row.display_name, "executable_path": row.executable_path,
         "aumid": row.aumid, "aliases": list(row.aliases),
         "publisher": row.publisher, "version": row.version,
         "source": row.source, "trust_state": row.trust_state, "available": row.available}
        for row in records[:1000]], "source": "Windows App Paths, Uninstall, Start Menu and AppsFolder metadata"}


def _is_file(path: str) -> bool:
    return os.path.isfile(path)


def _launchable(record: AppRecord) -> bool:
    if record.aumid:
        return True
    return bool(record.executable_path) and _is_file(record.executable_path)


def _target(record: AppRecord) -> tuple[str, str]:
    if record.aumid:
        return "aumid", record.aumid
    return "exe", str(Path(record.executable_path).resolve())


_DERIVED_NAME_SOURCES = {"app_paths", "volume_scan"}


def _same_target(a: AppRecord, b: AppRecord) -> bool:
    ka, ta = _target(a)
    kb, tb = _target(b)
    if ka == kb and ta.casefold() == tb.casefold():
        return True
    # An App Paths alias (name derived from the exe file) with exactly the same name as a
    # user-facing Start menu/AppsFolder entry is the same app to the user; the latter wins.
    return (a.display_name.casefold() == b.display_name.casefold()
            and (a.source in _DERIVED_NAME_SOURCES) != (b.source in _DERIVED_NAME_SOURCES))


def launch_candidate_dict(candidate: Candidate) -> dict[str, Any]:
    record = candidate.item
    kind, target = _target(record)
    return {"display_name": record.display_name, "kind": kind, "target": target,
            "publisher": record.publisher, "source": record.source, "score": candidate.score,
            "matched": candidate.matched_name, "reason": candidate.reason}


def rank_launch(name: str, records: list[AppRecord], *, limit: int = 10) -> list[Candidate]:
    usable = [r for r in records if _launchable(r)]
    ranked = rank_candidates(name, usable, names=record_names, publisher=lambda r: r.publisher,
                             limit=limit * 3)
    # Names derived from file names rank just below user-facing names of equal quality.
    ranked = sorted(ranked, key=lambda c: (-(c.score - (0.005 if c.item.source in _DERIVED_NAME_SOURCES
                                                         else 0.0)), len(c.matched_name)))
    unique: list[Candidate] = []
    for candidate in ranked:  # collapse shortcut/App Paths duplicates for the same target
        index = next((i for i, seen in enumerate(unique) if _same_target(candidate.item, seen.item)), None)
        if index is None:
            unique.append(candidate)
        elif (unique[index].item.source in _DERIVED_NAME_SOURCES
              and candidate.item.source not in _DERIVED_NAME_SOURCES):
            # Keep the better score but present the user-facing record (e.g. Start menu name).
            kept = unique[index]
            unique[index] = Candidate(candidate.item, kept.score, kept.matched_name, kept.reason)
    return unique[:limit]


def resolve_launch(name: str, store=None, records: list[AppRecord] | None = None
                   ) -> tuple[Candidate | None, list[Candidate]]:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError("application name must contain 1 to 120 characters")
    if records is None:
        if os.name != "nt":
            raise OSError("application launching requires Windows")
        records = _all_records(store)
    ranked = rank_launch(name, records, limit=8)
    return pick_unambiguous(ranked, same_target=_same_target), ranked


def _check_executable(path: str) -> Path:
    executable = Path(path)
    if not executable.is_file():
        raise FileNotFoundError("resolved application executable no longer exists")
    if any(part.casefold() in _FORBIDDEN_PARTS for part in executable.parts):
        raise PermissionError("application candidates in Downloads, temporary or cache paths are blocked by default")
    stat = executable.lstat()
    if executable.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
        raise PermissionError("reparse-point application targets are not launchable")
    return executable


# ---------------------------------------------------------------------------
# Running-state probes
# ---------------------------------------------------------------------------

def processes_for_executable(path: str) -> set[int]:
    try:
        import psutil
    except ImportError:
        return set()
    wanted = os.path.normcase(os.path.normpath(path))
    found = set()
    for proc in psutil.process_iter(["exe"]):
        try:
            exe = proc.info.get("exe")
            if exe and os.path.normcase(os.path.normpath(exe)) == wanted:
                found.add(proc.pid)
        except (psutil.Error, OSError):
            continue
    return found


def _package_root(aumid: str) -> str | None:
    family = aumid.split("!", 1)[0]
    try:
        import winrt.windows.applicationmodel  # noqa: F401
        from winrt.windows.management.deployment import PackageManager
        for package in PackageManager().find_packages_for_user("", family):
            return str(package.installed_path)
    except Exception:  # noqa: BLE001 - optional provider
        return None
    return None


def processes_under(root: str | None) -> set[int]:
    if not root:
        return set()
    try:
        import psutil
    except ImportError:
        return set()
    prefix = os.path.normcase(os.path.normpath(root)) + os.sep
    found = set()
    for proc in psutil.process_iter(["exe"]):
        try:
            exe = proc.info.get("exe")
            if exe and os.path.normcase(os.path.normpath(exe)).startswith(prefix):
                found.add(proc.pid)
        except (psutil.Error, OSError):
            continue
    return found


def windows_for_aumid(aumid: str) -> list[int]:
    """Visible top-level windows whose AppUserModel.ID property equals ``aumid``."""
    try:
        import win32gui
        from win32com.propsys import propsys, pscon
    except ImportError:
        return []
    wanted = aumid.casefold()
    found: list[int] = []

    def visit(hwnd, _extra):
        # Windows without a property store are skipped.
        with contextlib.suppress(Exception):
            if win32gui.IsWindowVisible(hwnd):
                store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
                value = store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue()
                if value and str(value).casefold() == wanted:
                    found.append(int(hwnd))
        return True

    with contextlib.suppress(Exception):
        win32gui.EnumWindows(visit, None)
    return found


def _running_probe(kind: str, target: str) -> Callable[[], dict[str, Any]]:
    if kind == "exe":
        return lambda: {"pids": sorted(processes_for_executable(target)), "windows": []}
    root = _package_root(target)
    return lambda: {"pids": sorted(processes_under(root)), "windows": windows_for_aumid(target)}


# ---------------------------------------------------------------------------
# Simulate, launch and verify
# ---------------------------------------------------------------------------

def _ambiguity_text(name: str, ranked: list[Candidate]) -> str:
    if not ranked:
        return f"No registered executable or packaged app matched '{name}'."
    listing = "; ".join(f"{c.item.display_name} ({c.score:.2f})" for c in ranked[:5])
    return f"'{name}' is ambiguous; ask the user which application to open. Candidates: {listing}"


def simulate_launch(args: dict[str, Any], store=None, records: list[AppRecord] | None = None,
                    probe: Callable[[str, str], Callable[[], dict[str, Any]]] | None = None) -> dict[str, Any]:
    name = str(args.get("application", ""))
    winner, ranked = resolve_launch(name, store, records)
    if winner is None:
        raise ValueError(_ambiguity_text(name, ranked))
    record = winner.item
    kind, target = _target(record)
    if kind == "exe":
        _check_executable(target)
    state = (probe or _running_probe)(kind, target)()
    running = bool(state["pids"] or state["windows"])
    return {"application": record.display_name, "kind": kind, "target": target,
            "publisher": record.publisher, "source": record.source, "score": winner.score,
            "already_running": running, "running_pids": state["pids"][:20],
            "current_state": "running" if running else "not running",
            "intended_state": "running (a new window or the existing instance is brought up)",
            "alternatives": [launch_candidate_dict(c) for c in ranked[1:4]], "executes": False}


def wait_for_running(check: Callable[[], dict[str, Any]], before: set[int], *, launched_pid: int | None,
                     timeout: float, poll: float = 0.5, clock: Callable[[], float] = time.monotonic,
                     sleep: Callable[[float], None] = time.sleep) -> tuple[bool, str, list[int]]:
    started = clock()
    while True:
        state = check()
        pids = set(state["pids"])
        new = sorted(pids - before)
        if new:
            return True, "a new process for the application is running", new
        if launched_pid and launched_pid in pids:
            return True, "the launched process is running", [launched_pid]
        if state["windows"]:
            return True, "a window for the packaged app is open", sorted(pids)
        if clock() - started >= timeout:
            if pids:
                return True, "an existing instance is running; the launch was handed to it", sorted(pids)
            return False, "no process or window for the application appeared within the wait", []
        sleep(poll)


def launch_application(name: str, store=None, *, verify_seconds: float = 10.0,
                       records: list[AppRecord] | None = None,
                       launcher: Callable[..., int | None] | None = None,
                       probe: Callable[[str, str], Callable[[], dict[str, Any]]] | None = None,
                       clock: Callable[[], float] = time.monotonic,
                       sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    if os.name != "nt" and records is None:
        raise OSError("application launching requires Windows")
    winner, ranked = resolve_launch(name, store, records)
    if winner is None:
        return {"summary": _ambiguity_text(name, ranked), "status": "ambiguous" if ranked else "not_found",
                "application": name, "candidates": [launch_candidate_dict(c) for c in ranked],
                "verified": False}
    record = winner.item
    kind, target = _target(record)
    check = (probe or _running_probe)(kind, target)
    before = set(check()["pids"])
    launch = launcher or shell_execute
    if kind == "exe":
        executable = _check_executable(target)
        pid = launch(str(executable), None, directory=str(executable.parent))
    else:
        pid = launch(f"shell:AppsFolder\\{target}", None)
    verify_seconds = max(0.0, min(float(verify_seconds), 30.0))
    verified, detail, pids = wait_for_running(check, before, launched_pid=pid, timeout=verify_seconds,
                                              clock=clock, sleep=sleep)
    label = record.display_name
    summary = (f"Opened {label}; {detail}." if verified
               else f"Launch of {label} was dispatched but not verified: {detail}.")
    result = {"summary": summary, "application": label, "kind": kind, "target": target,
              "trust_state": record.trust_state, "score": winner.score, "pids": pids[:20],
              "verified": verified, "verification": detail}
    if kind == "exe":
        result["executable_path"] = target
    else:
        result["aumid"] = target
    return result
