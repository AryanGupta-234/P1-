"""Dynamic uninstall discovery, preview and execution for Win32/MSI and current-user MSIX software.

Nothing here is a hardcoded application list. Entries come from the Windows Uninstall registry
(HKLM 64/32-bit views and HKCU) and, when PyWinRT is installed, from
``Windows.Management.Deployment.PackageManager``. Uninstallers are started with
``ShellExecuteExW`` (``runas`` only for per-machine entries so Windows shows its real UAC
prompt); SENTI never uses a shell, subprocess or UAC bypass.
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import PureWindowsPath
from typing import Any

from senti.windows.app_catalog import Candidate, pick_unambiguous, rank_candidates

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
SETTINGS_URI = "ms-settings:appsfeatures"
RECOVERY_NOTE = "reinstall required; not automatically reversible"
_GUID_RE = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")
_UPDATE_RELEASE_TYPES = {"update", "hotfix", "security update", "service pack", "update rollup"}
_KB_RE = re.compile(r"^KB\d{5,}", re.IGNORECASE)
_VALUE_NAMES = ("DisplayName", "Publisher", "DisplayVersion", "EstimatedSize", "InstallDate",
                "InstallLocation", "UninstallString", "QuietUninstallString", "WindowsInstaller",
                "SystemComponent", "ParentKeyName", "ReleaseType", "NoRemove")
# Script hosts and shells are refused as uninstall targets: an uninstall entry that runs them
# is indistinguishable from an arbitrary command, so the user is sent to Settings instead.
_REFUSED_LAUNCHERS = {"cmd.exe", "powershell.exe", "powershell_ise.exe", "pwsh.exe", "wscript.exe",
                      "cscript.exe", "mshta.exe", "conhost.exe", "wsl.exe", "bash.exe", "forfiles.exe",
                      "regsvr32.exe", "msbuild.exe", "installutil.exe", "cmstp.exe"}
_SIGNATURE_KIND_SYSTEM = 4
_ERROR_CANCELLED = 1223


def _is_file(path: str) -> bool:
    return os.path.isfile(path)


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class UninstallEntry:
    entry_id: str
    display_name: str
    kind: str  # msi | exe | msix
    publisher: str | None = None
    version: str | None = None
    size_kb: int | None = None
    install_date: str | None = None
    install_location: str | None = None
    uninstall_string: str | None = None
    quiet_uninstall_string: str | None = None
    product_code: str | None = None
    hive: str | None = None  # HKLM | HKCU
    view: str | None = None  # 64 | 32 | "" (HKCU is not redirected)
    key_name: str | None = None
    package_full_name: str | None = None
    package_family_name: str | None = None
    signature_kind: str | None = None

    @property
    def per_machine(self) -> bool:
        return self.hive == "HKLM"

    @property
    def needs_elevation(self) -> bool:
        # Per-machine entries were installed for all users and normally need administrator rights.
        return self.per_machine

    @property
    def scope(self) -> str:
        return "machine" if self.per_machine else "user"

    def names(self) -> list[str]:
        names = [self.display_name]
        if self.key_name and not _GUID_RE.fullmatch(self.key_name):
            names.append(self.key_name)
        if self.install_location:
            leaf = PureWindowsPath(self.install_location.rstrip("\\/")).name
            if leaf:
                names.append(leaf)
        if self.package_family_name:
            names.append(self.package_family_name.split("_", 1)[0].replace(".", " "))
        return names

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id, "name": self.display_name, "publisher": self.publisher,
            "version": self.version, "kind": self.kind, "scope": self.scope,
            "size_mb": round(self.size_kb / 1024, 1) if self.size_kb else None,
            "install_date": self.install_date, "install_location": self.install_location,
            "product_code": self.product_code, "package_full_name": self.package_full_name,
            "quiet_available": self.kind in {"msi", "msix"} or bool(self.quiet_uninstall_string),
            "needs_elevation": self.needs_elevation,
        }


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip("\x00").strip()
    return text[:1024] or None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def entry_from_values(hive: str, view: str, key_name: str, values: dict[str, Any]) -> UninstallEntry | None:
    """Build one uninstallable entry from raw registry values, or None when it must be skipped."""
    name = _clean(values.get("DisplayName"))
    if not name:
        return None
    if _as_int(values.get("SystemComponent")) == 1 or _as_int(values.get("NoRemove")) == 1:
        return None
    release = (_clean(values.get("ReleaseType")) or "").casefold()
    if release in _UPDATE_RELEASE_TYPES or _clean(values.get("ParentKeyName")) or _KB_RE.match(key_name):
        return None
    uninstall = _clean(values.get("UninstallString"))
    quiet = _clean(values.get("QuietUninstallString"))
    windows_installer = _as_int(values.get("WindowsInstaller")) == 1
    product_code = None
    if _GUID_RE.fullmatch(key_name) and (windows_installer or _mentions_msiexec(uninstall)):
        product_code = key_name.upper()
    elif _mentions_msiexec(uninstall):
        found = _GUID_RE.search(uninstall or "")
        product_code = found.group(0).upper() if found else None
    if product_code:
        kind = "msi"
    elif uninstall or quiet:
        kind = "exe"
    else:
        return None
    size = _as_int(values.get("EstimatedSize"))
    view_tag = view if hive == "HKLM" else ""
    return UninstallEntry(
        entry_id=f"reg:{hive}:{view_tag}:{key_name}", display_name=name[:300], kind=kind,
        publisher=_clean(values.get("Publisher")), version=_clean(values.get("DisplayVersion")),
        size_kb=size if size and size > 0 else None, install_date=_clean(values.get("InstallDate")),
        install_location=_clean(values.get("InstallLocation")), uninstall_string=uninstall,
        quiet_uninstall_string=quiet, product_code=product_code, hive=hive, view=view_tag,
        key_name=key_name)


def _mentions_msiexec(command: str | None) -> bool:
    return bool(command) and "msiexec" in command.casefold()


def _registry_sources(reg) -> list[tuple[str, str, int, int]]:
    return [("HKLM", "64", reg.HKEY_LOCAL_MACHINE, getattr(reg, "KEY_WOW64_64KEY", 0x100)),
            ("HKLM", "32", reg.HKEY_LOCAL_MACHINE, getattr(reg, "KEY_WOW64_32KEY", 0x200)),
            ("HKCU", "", reg.HKEY_CURRENT_USER, 0)]


def _winreg():
    import winreg
    return winreg


def registry_entries(reg=None) -> list[UninstallEntry]:
    if reg is None:
        if os.name != "nt":
            return []
        reg = _winreg()
    found: dict[str, UninstallEntry] = {}
    for hive, view, root_key, flag in _registry_sources(reg):
        try:
            root = reg.OpenKey(root_key, UNINSTALL_KEY, 0, reg.KEY_READ | flag)
        except OSError:
            continue
        with root:
            try:
                count = reg.QueryInfoKey(root)[0]
            except OSError:
                continue
            for index in range(count):
                try:
                    key_name = reg.EnumKey(root, index)
                    with reg.OpenKey(root, key_name) as sub:
                        values = {}
                        for value_name in _VALUE_NAMES:
                            try:
                                values[value_name] = reg.QueryValueEx(sub, value_name)[0]
                            except OSError:
                                pass
                except OSError:
                    continue
                entry = entry_from_values(hive, view, key_name, values)
                if entry is None:
                    continue
                # The 64- and 32-bit views can expose the same MSI product; keep one.
                dedupe = (entry.product_code or entry.entry_id).casefold()
                found.setdefault(dedupe, entry)
    return list(found.values())


def registry_entry_present(entry: UninstallEntry, reg=None) -> bool:
    reg = reg or _winreg()
    for hive, view, root_key, flag in _registry_sources(reg):
        if hive != entry.hive or (hive == "HKLM" and view != entry.view):
            continue
        try:
            with reg.OpenKey(root_key, f"{UNINSTALL_KEY}\\{entry.key_name}", 0, reg.KEY_READ | flag):
                return True
        except OSError:
            return False
    return False


# ---------------------------------------------------------------------------
# MSIX / Store packages (optional PyWinRT provider)
# ---------------------------------------------------------------------------

def _package_manager():
    """Return a PackageManager, or raise RuntimeError when the projection is unavailable."""
    if os.name != "nt":
        raise RuntimeError("MSIX package management requires Windows")
    try:
        import winrt.windows.applicationmodel  # noqa: F401 - Package objects need this projection
        from winrt.windows.management.deployment import PackageManager
    except ImportError as exc:
        raise RuntimeError("PyWinRT Windows.Management.Deployment projection is not installed") from exc
    return PackageManager()


def msix_provider_status() -> str:
    try:
        _package_manager()
        return "available"
    except RuntimeError as exc:
        return f"unavailable: {exc}"
    except Exception as exc:  # noqa: BLE001 - provider health is reported, not raised
        return f"unavailable: {type(exc).__name__}"


def entry_from_package(package: Any) -> UninstallEntry | None:
    try:
        if package.is_framework or package.is_resource_package or getattr(package, "is_optional", False):
            return None
        if int(package.signature_kind) == _SIGNATURE_KIND_SYSTEM:
            return None
        ident = package.id
        full_name = str(ident.full_name)
        family = str(ident.family_name)
        name = _clean(getattr(package, "display_name", None))
        if not name or name.startswith("ms-resource:"):
            name = str(ident.name)
        version = ident.version
        version_text = f"{version.major}.{version.minor}.{version.build}.{version.revision}"
        try:
            location = _clean(package.installed_path)
        except Exception:  # noqa: BLE001 - older builds lack InstalledPath
            location = None
        try:
            installed = package.installed_date
            install_date = installed.strftime("%Y%m%d") if hasattr(installed, "strftime") else None
        except Exception:  # noqa: BLE001
            install_date = None
        return UninstallEntry(
            entry_id=f"msix:{full_name}", display_name=name[:300], kind="msix",
            publisher=_clean(getattr(package, "publisher_display_name", None)) or _clean(ident.publisher),
            version=version_text, install_date=install_date, install_location=location,
            package_full_name=full_name, package_family_name=family,
            signature_kind=str(int(package.signature_kind)))
    except Exception:  # noqa: BLE001 - one malformed package must not hide the rest
        return None


def msix_entries(manager=None) -> list[UninstallEntry]:
    manager = manager or _package_manager()
    rows = []
    for package in manager.find_packages_for_user(""):
        entry = entry_from_package(package)
        if entry is not None:
            rows.append(entry)
    return rows


def msix_entry_present(entry: UninstallEntry, manager=None) -> bool:
    manager = manager or _package_manager()
    return manager.find_package_for_user("", entry.package_full_name) is not None


# ---------------------------------------------------------------------------
# Enumeration and resolution
# ---------------------------------------------------------------------------

def enumerate_software(*, reg=None, manager=None, include_msix: bool = True) -> tuple[list[UninstallEntry], dict[str, str]]:
    providers: dict[str, str] = {}
    entries: list[UninstallEntry] = []
    try:
        entries.extend(registry_entries(reg))
        providers["registry"] = "available" if (reg is not None or os.name == "nt") else "unavailable: requires Windows"
    except Exception as exc:  # noqa: BLE001
        providers["registry"] = f"unavailable: {type(exc).__name__}"
    if include_msix:
        try:
            entries.extend(msix_entries(manager))
            providers["msix"] = "available"
        except RuntimeError as exc:
            providers["msix"] = f"unavailable: {exc}"
        except Exception as exc:  # noqa: BLE001
            providers["msix"] = f"unavailable: {type(exc).__name__}"
    entries.sort(key=lambda e: e.display_name.casefold())
    return entries, providers


def list_installed_software(*, query: str | None = None, kind: str | None = None,
                            scope: str | None = None, publisher: str | None = None,
                            limit: int = 100, entries: list[UninstallEntry] | None = None,
                            providers: dict[str, str] | None = None) -> dict[str, Any]:
    if entries is None:
        entries, providers = enumerate_software()
    rows = [e for e in entries
            if (not kind or kind == "any" or e.kind == kind)
            and (not scope or scope == "any" or e.scope == scope)
            and (not publisher or publisher.casefold() in (e.publisher or "").casefold())]
    if query:
        rows = [c.item for c in rank_uninstall(query, rows, limit=max(limit, 1))]
    counts: dict[str, int] = {}
    for row in entries:
        counts[row.kind] = counts.get(row.kind, 0) + 1
    limit = max(1, min(int(limit), 500))
    return {
        "summary": f"Found {len(rows)} uninstallable entries (of {len(entries)} total).",
        "count": len(rows), "total": len(entries), "counts_by_kind": counts,
        "providers": providers or {}, "entries": [row.to_dict() for row in rows[:limit]],
        "truncated": len(rows) > limit,
        "source": "Windows Uninstall registry (HKLM 64/32-bit, HKCU) and PackageManager", "verified": True,
    }


def rank_uninstall(query: str, entries: list[UninstallEntry], *, limit: int = 10) -> list[Candidate]:
    return rank_candidates(query, entries, names=lambda e: e.names(), publisher=lambda e: e.publisher,
                           limit=limit)


def _same_product(a: UninstallEntry, b: UninstallEntry) -> bool:
    if a.product_code and a.product_code == b.product_code:
        return True
    return (a.display_name.casefold() == b.display_name.casefold() and a.version == b.version
            and a.kind == b.kind and a.kind != "msix")


def candidate_dict(candidate: Candidate) -> dict[str, Any]:
    row = candidate.item.to_dict()
    row.update({"score": candidate.score, "matched": candidate.matched_name, "reason": candidate.reason})
    return row


@dataclass(frozen=True, slots=True)
class Resolution:
    entry: UninstallEntry | None
    candidates: list[Candidate]

    @property
    def ambiguous(self) -> bool:
        return self.entry is None and bool(self.candidates)


def resolve_uninstall(args: dict[str, Any], entries: list[UninstallEntry] | None = None) -> Resolution:
    if entries is None:
        entries, _providers = enumerate_software()
    entry_id = str(args.get("entry_id") or "").strip()
    if entry_id:
        exact = [e for e in entries if e.entry_id.casefold() == entry_id.casefold()]
        return Resolution(exact[0] if exact else None, [])
    query = str(args.get("application") or "").strip()
    if not query:
        raise ValueError("provide 'application' (a name) or an exact 'entry_id'")
    ranked = rank_uninstall(query, entries, limit=8)
    winner = pick_unambiguous(ranked, same_target=_same_product)
    return Resolution(winner.item if winner else None, ranked)


def _ambiguity_message(query: str, resolution: Resolution) -> str:
    if not resolution.candidates:
        return (f"No installed software matched '{query}'. Use senti_list_installed_software, or "
                f"open {SETTINGS_URI} to browse Installed apps.")
    names = "; ".join(f"{c.item.display_name} [{c.item.entry_id}] ({c.score:.2f})"
                      for c in resolution.candidates[:5])
    return f"'{query}' is ambiguous. Ask the user which one and pass its entry_id. Candidates: {names}"


# ---------------------------------------------------------------------------
# Command-line parsing (Windows CommandLineToArgvW rules)
# ---------------------------------------------------------------------------

def _argv_ctypes(command_line: str) -> list[str]:
    import ctypes
    from ctypes import wintypes
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int(0)
    argv = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not argv:
        raise OSError(ctypes.get_last_error(), "CommandLineToArgvW failed")
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(argv, wintypes.HLOCAL))


def _argv_python(command_line: str) -> list[str]:
    """Pure-Python CommandLineToArgvW equivalent (used off-Windows and as a fallback)."""
    args: list[str] = []
    i, n = 0, len(command_line)
    # argv[0]: quotes delimit, no backslash escaping.
    if command_line.startswith('"'):
        end = command_line.find('"', 1)
        end = n if end < 0 else end
        args.append(command_line[1:end])
        i = end + 1
    else:
        while i < n and command_line[i] not in " \t":
            i += 1
        args.append(command_line[:i])
    while True:
        while i < n and command_line[i] in " \t":
            i += 1
        if i >= n:
            break
        current, in_quotes = [], False
        while i < n:
            ch = command_line[i]
            if ch == "\\":
                start = i
                while i < n and command_line[i] == "\\":
                    i += 1
                slashes = i - start
                if i < n and command_line[i] == '"':
                    current.append("\\" * (slashes // 2))
                    if slashes % 2:
                        current.append('"')
                        i += 1
                    continue
                current.append("\\" * slashes)
                continue
            if ch == '"':
                if in_quotes and i + 1 < n and command_line[i + 1] == '"':
                    current.append('"')
                    i += 2
                    continue
                in_quotes = not in_quotes
                i += 1
                continue
            if ch in " \t" and not in_quotes:
                break
            current.append(ch)
            i += 1
        args.append("".join(current))
    return args


def split_command_line(command_line: str) -> list[str]:
    if not command_line.strip():
        return []  # CommandLineToArgvW("") returns the current process path; never do that.
    if os.name == "nt":
        try:
            return _argv_ctypes(command_line)
        except (OSError, AttributeError):
            pass
    return _argv_python(command_line)


def quote_argument(arg: str) -> str:
    """Quote one argument so CommandLineToArgvW reproduces it exactly."""
    if arg and not any(ch in arg for ch in ' \t"'):
        return arg
    out, slashes = ['"'], 0
    for ch in arg:
        if ch == "\\":
            slashes += 1
            continue
        if ch == '"':
            out.append("\\" * (slashes * 2 + 1) + '"')
        else:
            out.append("\\" * slashes + ch)
        slashes = 0
    out.append("\\" * (slashes * 2) + '"')
    return "".join(out)


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    executable: str
    arguments: list[str]
    raw_arguments: str


def parse_uninstall_command(command: str) -> ParsedCommand:
    text = os.path.expandvars(str(command)).strip()
    if not text:
        raise ValueError("empty uninstall command")
    if text.startswith('"'):
        end = text.find('"', 1)
        if end < 0:
            raise ValueError("unterminated quote in uninstall command")
        executable, tail = text[1:end], text[end + 1:]
    else:
        cut = len(text)
        for index, ch in enumerate(text):
            if ch in " \t":
                cut = index
                break
        executable, tail = text[:cut], text[cut:]
        if not _is_file(executable):
            # Registry values often contain unquoted paths with spaces: C:\Program Files\X\u.exe /S
            for match in re.finditer(r"\.exe(?=\s|$)", text, re.IGNORECASE):
                prefix = text[:match.end()]
                if _is_file(prefix):
                    executable, tail = prefix, text[match.end():]
                    break
    tail = tail.strip()
    arguments = split_command_line('x ' + tail)[1:] if tail else []
    return ParsedCommand(executable.strip(), arguments, tail)


# ---------------------------------------------------------------------------
# Plans and safety policy
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class UninstallPlan:
    entry: UninstallEntry
    kind: str
    executable: str | None
    parameters: str
    quiet: bool
    quiet_available: bool
    needs_elevation: bool
    refused: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def command(self) -> str:
        if self.kind == "msix":
            return f"PackageManager.RemovePackageAsync({self.entry.package_full_name})"
        if not self.executable:
            return ""
        return (quote_argument(self.executable) + (" " + self.parameters if self.parameters else "")).strip()


def _system_root() -> str:
    return os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _temp_roots() -> list[str]:
    roots = [os.environ.get("TEMP"), os.environ.get("TMP"), os.path.join(_system_root(), "Temp")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Temp"))
    return [_norm(r) for r in roots if r]


def in_temp_folder(path: str) -> bool:
    normalized = _norm(path)
    if any(part.casefold() in {"temp", "tmp"} for part in PureWindowsPath(path).parts):
        return True
    return any(normalized == root or normalized.startswith(root + os.sep) for root in _temp_roots())


def _trusted_dll_roots(entry: UninstallEntry) -> list[str]:
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
             os.environ.get("ProgramW6432"), entry.install_location]
    return [_norm(r) for r in roots if r]


def _refusal(entry: UninstallEntry, parsed: ParsedCommand) -> str | None:
    executable = parsed.executable
    if not PureWindowsPath(executable).is_absolute() or not _is_file(executable):
        return "the uninstaller is not an existing absolute executable path"
    if in_temp_folder(executable):
        return "the uninstaller is located in a temporary folder"
    base = PureWindowsPath(executable).name.casefold()
    if base in _REFUSED_LAUNCHERS:
        return f"the uninstall entry runs a shell or script host ({base})"
    if base == "rundll32.exe":
        dll = (parsed.arguments[0] if parsed.arguments else "").split(",", 1)[0].strip().strip('"')
        known = (dll and PureWindowsPath(dll).is_absolute() and _is_file(dll) and not in_temp_folder(dll)
                 and any(_norm(dll).startswith(root + os.sep) for root in _trusted_dll_roots(entry)))
        if not known:
            return "the uninstall entry runs rundll32 with an unknown DLL"
    return None


def build_plan(entry: UninstallEntry, *, quiet: bool = False) -> UninstallPlan:
    if entry.kind == "msix":
        return UninstallPlan(entry, "msix", None, "", True, True, False)
    if entry.kind == "msi":
        if not entry.product_code:
            return UninstallPlan(entry, "msi", None, "", False, True, entry.needs_elevation,
                                 refused="the MSI product code is missing")
        msiexec = os.path.join(_system_root(), "System32", "msiexec.exe")
        params = f"/x {entry.product_code}" + (" /passive" if quiet else "")
        return UninstallPlan(entry, "msi", msiexec, params, quiet, True, entry.needs_elevation)
    notes: list[str] = []
    command = entry.uninstall_string
    use_quiet = False
    if quiet and entry.quiet_uninstall_string:
        command, use_quiet = entry.quiet_uninstall_string, True
    elif quiet:
        notes.append("No QuietUninstallString is registered; the interactive uninstaller will run.")
    command = command or entry.quiet_uninstall_string
    try:
        parsed = parse_uninstall_command(command or "")
    except ValueError as exc:
        return UninstallPlan(entry, "exe", None, "", use_quiet, bool(entry.quiet_uninstall_string),
                             entry.needs_elevation, refused=str(exc))
    if PureWindowsPath(parsed.executable).name.casefold() in {"msiexec.exe", "msiexec"}:
        found = _GUID_RE.search(parsed.raw_arguments)
        if found:  # an MSI routed through an EXE-style entry; always normalize to /x {GUID}
            return build_plan(replace(entry, kind="msi", product_code=found.group(0).upper()), quiet=quiet)
        return UninstallPlan(entry, "exe", None, "", False, False, entry.needs_elevation,
                             refused="msiexec entry without a product code")
    refused = _refusal(entry, parsed)
    return UninstallPlan(entry, "exe", parsed.executable, parsed.raw_arguments, use_quiet,
                         bool(entry.quiet_uninstall_string), entry.needs_elevation,
                         refused=refused, notes=tuple(notes))


# ---------------------------------------------------------------------------
# Simulation (never executes anything)
# ---------------------------------------------------------------------------

def _resolve_or_raise(args: dict[str, Any], entries: list[UninstallEntry] | None) -> UninstallEntry:
    resolution = resolve_uninstall(args, entries)
    if resolution.entry is None:
        if args.get("entry_id"):
            raise ValueError(f"No uninstallable entry has entry_id '{args['entry_id']}'.")
        raise ValueError(_ambiguity_message(str(args.get("application", "")), resolution))
    return resolution.entry


def simulate_uninstall(args: dict[str, Any], entries: list[UninstallEntry] | None = None) -> dict[str, Any]:
    entry = _resolve_or_raise(args, entries)
    plan = build_plan(entry, quiet=bool(args.get("quiet", False)))
    if plan.refused:
        raise ValueError(f"SENTI will not run this uninstaller: {plan.refused}. Open {SETTINGS_URI} "
                         f"(Settings > Apps > Installed apps) and uninstall '{entry.display_name}' there.")
    return {
        "entry_id": entry.entry_id, "name": entry.display_name, "publisher": entry.publisher,
        "version": entry.version,
        "size_mb": round(entry.size_kb / 1024, 1) if entry.size_kb else None,
        "install_location": entry.install_location, "kind": plan.kind, "scope": entry.scope,
        "command": plan.command, "quiet": plan.quiet, "quiet_available": plan.quiet_available,
        "needs_elevation": plan.needs_elevation,
        "elevation": ("Windows will show a UAC prompt; SENTI never bypasses it." if plan.needs_elevation
                      else "Runs as the current user."),
        "current_state": f"'{entry.display_name}' is installed.",
        "intended_state": f"'{entry.display_name}' is removed.",
        "recovery": RECOVERY_NOTE, "notes": list(plan.notes), "executes": False,
    }


# ---------------------------------------------------------------------------
# Execution and verification
# ---------------------------------------------------------------------------

def _launch(plan: UninstallPlan) -> int | None:
    from senti.windows.launch import shell_execute
    directory = os.path.dirname(plan.executable) if plan.executable else None
    return shell_execute(plan.executable, plan.parameters or None,
                         verb="runas" if plan.needs_elevation else None, directory=directory)


def _remove_package(entry: UninstallEntry, timeout: float, manager=None) -> None:
    manager = manager or _package_manager()

    async def run():
        await asyncio.wait_for(manager.remove_package_async(entry.package_full_name), timeout)

    asyncio.run(run())


def _process_activity(pids: set[int]) -> bool:
    try:
        import psutil
    except ImportError:
        return False
    alive = False
    for pid in list(pids):
        try:
            proc = psutil.Process(pid)
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                alive = True
                pids.update(child.pid for child in proc.children(recursive=True))
        except (psutil.Error, OSError):
            continue
    return alive


def _absent(present: Callable[[], bool]) -> bool:
    try:
        return not present()
    except Exception:  # noqa: BLE001 - an unreadable state is not proof of removal
        return False


def wait_for_removal(present: Callable[[], bool], *, timeout: float, poll: float = 2.0,
                     cancel: threading.Event | None = None, activity: Callable[[], bool] | None = None,
                     exit_grace: float = 15.0, clock: Callable[[], float] = time.monotonic,
                     sleep: Callable[[float], None] = time.sleep) -> tuple[str, float]:
    """Poll until the entry disappears. Returns (status, waited_seconds).

    status: ``removed`` | ``in_progress`` (budget ended while still present) | ``cancelled`` |
    ``still_installed`` (uninstaller processes ended and the entry stayed registered).
    """
    started = clock()
    idle_since: float | None = None
    while True:
        waited = clock() - started
        if _absent(present):
            return "removed", waited
        if cancel is not None and cancel.is_set():
            return "cancelled", waited
        if activity is not None:
            if activity():
                idle_since = None
            elif idle_since is None:
                idle_since = clock()
            elif clock() - idle_since >= exit_grace:
                return "still_installed", waited
        if waited >= timeout:
            return "in_progress", waited
        sleep(min(poll, max(0.05, timeout - waited)))


def uninstall(args: dict[str, Any], *, entries: list[UninstallEntry] | None = None,
              cancel: threading.Event | None = None, present: Callable[[UninstallEntry], bool] | None = None,
              launcher: Callable[[UninstallPlan], int | None] | None = None,
              remover: Callable[[UninstallEntry, float], None] | None = None,
              clock: Callable[[], float] = time.monotonic,
              sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    if os.name != "nt" and entries is None:
        raise OSError("uninstalling software requires Windows")
    resolution = resolve_uninstall(args, entries)
    if resolution.entry is None:
        query = str(args.get("entry_id") or args.get("application") or "")
        return {"summary": _ambiguity_message(query, resolution), "status": "ambiguous" if resolution.candidates
                else "not_found", "candidates": [candidate_dict(c) for c in resolution.candidates],
                "settings_uri": SETTINGS_URI, "verified": False}
    entry = resolution.entry
    plan = build_plan(entry, quiet=bool(args.get("quiet", False)))
    if plan.refused:
        return {"summary": f"Refused: {plan.refused}. Use Settings > Apps > Installed apps ({SETTINGS_URI}).",
                "status": "refused", "entry_id": entry.entry_id, "name": entry.display_name,
                "settings_uri": SETTINGS_URI, "verified": False}
    wait_seconds = float(args.get("wait_seconds", 60))
    wait_seconds = max(0.0, min(wait_seconds, 600.0))
    if present is None:
        present = msix_entry_present if entry.kind == "msix" else registry_entry_present
    base = {"entry_id": entry.entry_id, "name": entry.display_name, "kind": plan.kind,
            "command": plan.command, "elevation_requested": plan.needs_elevation,
            "recovery": RECOVERY_NOTE}
    activity = None
    if entry.kind == "msix":
        try:
            (remover or (lambda e, t: _remove_package(e, t)))(entry, max(wait_seconds, 30.0))
        except Exception as exc:  # noqa: BLE001 - deployment errors are reported, not retried
            return {**base, "summary": f"Package removal failed: {str(exc)[:200] or type(exc).__name__}",
                    "status": "failed", "verified": False}
    else:
        try:
            pid = (launcher or _launch)(plan)
        except OSError as exc:
            if getattr(exc, "winerror", None) == _ERROR_CANCELLED or getattr(exc, "errno", None) == _ERROR_CANCELLED:
                return {**base, "summary": "The UAC prompt was declined; nothing was uninstalled.",
                        "status": "cancelled", "verified": False}
            raise
        base["pid"] = pid
        if pid:
            pids = {int(pid)}

            def activity() -> bool:
                return _process_activity(pids)
    status, waited = wait_for_removal(lambda: present(entry), timeout=wait_seconds, cancel=cancel,
                                      activity=activity, clock=clock, sleep=sleep)
    summaries = {
        "removed": f"Uninstalled '{entry.display_name}'; its registration is gone.",
        "in_progress": (f"The uninstaller for '{entry.display_name}' is still running or waiting for input; "
                        "the entry is still registered. Check again with senti_find_application."),
        "cancelled": "Verification was cancelled; the uninstall may still be running.",
        "still_installed": (f"The uninstaller exited but '{entry.display_name}' is still registered; it may "
                            "have been cancelled or need a restart."),
    }
    return {**base, "summary": summaries[status], "status": status, "waited_seconds": round(waited, 1),
            "verified": status == "removed"}
