"""Metadata-only installed application discovery; never reads user document contents."""
from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


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
        """Return the best-ranked records: the exact tier when one exists, else fuzzy matches."""
        ranked = rank_candidates(name, records, names=record_names,
                                 publisher=lambda r: r.publisher, limit=50)
        if not ranked:
            return []
        exact = [c.item for c in ranked if c.score >= EXACT_SCORE]
        return exact or [c.item for c in ranked]


def record_names(record: Any) -> list[str]:
    names = [getattr(record, "display_name", "") or ""]
    names.extend(getattr(record, "aliases", ()) or ())
    path = getattr(record, "executable_path", None)
    if path:
        names.append(Path(path).stem)
    return [n for n in names if n]


# ---------------------------------------------------------------------------
# Dynamic ranked matching shared by launch and uninstall resolution. No app lists:
# every signal (tokens, initials, fuzzy ratio, publisher, aliases) comes from metadata.
# ---------------------------------------------------------------------------

EXACT_SCORE = 0.97
MIN_SCORE = 0.55
AMBIGUITY_MARGIN = 0.1
_NOISE_TOKENS = {"the", "app", "application", "program", "software", "x64", "x86", "64", "32",
                 "bit", "64bit", "32bit", "edition", "for", "windows", "desktop", "version"}
_TOKEN_RE = re.compile(r"[^\w]+", re.UNICODE)
_VERSION_RE = re.compile(r"\bv?\d+(?:\.\d+)+\b")


def _tokens(text: str) -> list[str]:
    lowered = str(text).casefold().replace("_", " ")
    raw = [t for t in _TOKEN_RE.split(_VERSION_RE.sub(" ", lowered)) if t]
    kept = [t for t in raw if t not in _NOISE_TOKENS]
    return kept or [t for t in _TOKEN_RE.split(lowered) if t]


def edit_distance(a: str, b: str, limit: int = 3) -> int:
    """Optimal-string-alignment distance (Damerau-Levenshtein with adjacent transpositions)."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        current = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            current[j] = min(prev[j] + 1, current[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                current[j] = min(current[j], prev2[j - 2] + 1)
        prev2, prev = prev, current
    return prev[-1]


def _token_match(query_token: str, name_tokens: list[str]) -> float:
    best = 0.0
    for index, token in enumerate(name_tokens):
        if query_token == token:
            return 1.0
        if len(query_token) >= 2 and token.startswith(query_token):
            best = max(best, 0.75 + 0.2 * len(query_token) / len(token))
        if len(query_token) >= 4 and abs(len(query_token) - len(token)) <= 2:
            # Typos: one edit (incl. transposition) for short words, two for long ones.
            allowed = 1 if len(query_token) < 8 else 2
            distance = edit_distance(query_token, token, allowed)
            if distance <= allowed:
                best = max(best, 0.85 - 0.1 * (distance - 1))
        # Initials of consecutive tokens: "vs" -> "visual studio".
        if 2 <= len(query_token) <= len(name_tokens) - index:
            initials = "".join(t[0] for t in name_tokens[index:index + len(query_token)])
            if initials == query_token:
                best = max(best, 0.9)
    return best


def name_score(query: str, name: str, publisher: str | None = None) -> float:
    q_tokens, n_tokens = _tokens(query), _tokens(name)
    publisher_tokens = set(_tokens(publisher)) if publisher else set()
    if not q_tokens or not n_tokens:
        return 0.0
    q_compact, n_compact = "".join(q_tokens), "".join(n_tokens)
    if q_tokens == n_tokens:
        return 1.0
    if q_compact == n_compact:
        return 0.98
    per_token = [_token_match(t, n_tokens) for t in q_tokens]
    matched = sum(per_token) / len(q_tokens)
    if min(per_token) == 0.0:
        matched *= 0.6
    # Name coverage: how much of the candidate name the query (or the publisher) explains.
    explained = sum(1 for t in n_tokens if t in publisher_tokens
                    or any(t == q or t.startswith(q) for q in q_tokens))
    initials_cover = sum(len(q) for q in q_tokens if len(q) >= 2 and _token_match(q, n_tokens) == 0.9)
    coverage = min(1.0, (explained + initials_cover) / len(n_tokens))
    token_score = matched * (0.7 + 0.25 * coverage)
    fuzzy = SequenceMatcher(None, q_compact, n_compact).ratio() * 0.85
    return round(min(0.96, max(token_score, fuzzy)), 4)


@dataclass(frozen=True, slots=True)
class Candidate:
    item: Any
    score: float
    matched_name: str
    reason: str


def rank_candidates(query: str, items: Iterable[Any], *, names: Callable[[Any], Sequence[str]],
                    publisher: Callable[[Any], str | None] | None = None,
                    limit: int = 10, min_score: float = MIN_SCORE) -> list[Candidate]:
    query = str(query or "").strip()
    if not query:
        return []
    q_tokens = set(_tokens(query))
    ranked: list[Candidate] = []
    for item in items:
        best, best_name, reason = 0.0, "", "fuzzy"
        pub = publisher(item) if publisher else None
        for index, candidate_name in enumerate(names(item)):
            score = name_score(query, candidate_name, pub)
            if index > 0:
                score *= 0.98  # aliases rank just below an equal display-name match
            if score > best:
                best, best_name = score, candidate_name
                reason = ("exact" if score >= EXACT_SCORE else "tokens") if index == 0 else "alias"
        if pub and q_tokens:
            pub_tokens = set(_tokens(pub))
            overlap = q_tokens & pub_tokens
            if overlap:
                if best >= MIN_SCORE:
                    best = min(1.0, best + 0.05)
                elif overlap == q_tokens:
                    best, best_name, reason = 0.5, pub, "publisher"
        if best >= min_score:
            ranked.append(Candidate(item, round(best, 4), best_name, reason))
    ranked.sort(key=lambda c: (-c.score, len(c.matched_name)))
    return ranked[:max(1, limit)]


def pick_unambiguous(ranked: list[Candidate], *, same_target: Callable[[Any, Any], bool] | None = None
                     ) -> Candidate | None:
    """Return the single winner, or None when the caller must ask the user to choose."""
    if not ranked or ranked[0].score < 0.6:
        return None
    top = ranked[0]
    rivals = [c for c in ranked[1:] if not (same_target and same_target(top.item, c.item))]
    if not rivals:
        return top
    second = rivals[0]
    if top.score >= EXACT_SCORE and second.score < EXACT_SCORE:
        return top
    if top.score - second.score >= AMBIGUITY_MARGIN:
        return top
    return None
