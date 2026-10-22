"""Local-first foreground activity intelligence.

Tracks the foreground application and active/idle time on the interactive Windows
desktop. Window titles are processed in memory for semantic topic extraction;
raw titles, page text, URLs, screenshots, keystrokes and form values are never
persisted or transmitted. Application launching is opt-in and restricted to
previously observed executable paths in user/application install locations.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from . import core

IS_WIN = os.name == "nt"
_STOP = threading.Event()
_STARTED = False
_WORKER: threading.Thread | None = None
_LOCK = threading.RLock()
_CURRENT: dict[str, Any] | None = None
_LAST_AUTO_LAUNCH = 0.0
_MAX_SEMANTIC_TERMS = 18
_MAX_RECENT_SESSIONS = 60
_MAX_TASK_CLUSTERS = 250
_MAX_WINDOW_TITLE_CHARS = 420

DEFAULT_SETTINGS = {
    "enabled": True,
    "semantic_context": True,
    "suggestions_enabled": True,
    "auto_launch_learned_apps": False,
    "sample_interval_s": 2,
    "idle_after_seconds": 90,
    "retention_days": 90,
    "min_launch_observations": 8,
    "auto_launch_cooldown_s": 7200,
}

_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "from", "into", "onto", "this", "that",
    "these", "those", "then", "than", "there", "here", "when", "where",
    "what", "which", "while", "your", "you", "are", "was", "were", "has",
    "have", "had", "not", "but", "can", "will", "would", "should", "could",
    "about", "over", "under", "after", "before", "between", "more", "less",
    "new", "tab", "window", "page", "home", "welcome", "loading", "untitled",
    "document", "private", "incognito", "search", "start", "close", "open",
    "microsoft", "google", "desktop",
})
_SENSITIVE_TITLE_MARKERS = re.compile(
    r"(?:https?://|www\\.|[\\w.+-]+@[\\w.-]+\\.[A-Za-z]{2,}|"
    r"\\b(?:password|passcode|one.time.code|otp|recovery.code)\\b)",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.-]{2,40}")


def _settings() -> dict[str, Any]:
    raw = core.CFG.get("activity") if isinstance(core.CFG.get("activity"), dict) else {}
    values = dict(DEFAULT_SETTINGS)
    values.update({key: value for key, value in raw.items() if key in values})
    for key in ("enabled", "semantic_context", "suggestions_enabled", "auto_launch_learned_apps"):
        values[key] = values[key] is True
    values["sample_interval_s"] = _bounded_int(values.get("sample_interval_s"), 2, 1, 5)
    values["idle_after_seconds"] = _bounded_int(values.get("idle_after_seconds"), 90, 30, 900)
    values["retention_days"] = _bounded_int(values.get("retention_days"), 90, 7, 365)
    values["min_launch_observations"] = _bounded_int(values.get("min_launch_observations"), 8, 4, 30)
    values["auto_launch_cooldown_s"] = _bounded_int(values.get("auto_launch_cooldown_s"), 7200, 1800, 86400)
    return values


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(high, number))


def _ensure_schema() -> None:
    core.db("""CREATE TABLE IF NOT EXISTS activity_apps(
        app_key TEXT PRIMARY KEY, app_name TEXT NOT NULL, executable TEXT NOT NULL DEFAULT '',
        first_seen REAL NOT NULL, last_seen REAL NOT NULL, launches INTEGER NOT NULL DEFAULT 0,
        foreground_seconds REAL NOT NULL DEFAULT 0, active_seconds REAL NOT NULL DEFAULT 0,
        last_window_class TEXT NOT NULL DEFAULT '', latest_terms_json TEXT NOT NULL DEFAULT '[]')""")
    core.db("""CREATE TABLE IF NOT EXISTS activity_sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT, app_key TEXT NOT NULL, app_name TEXT NOT NULL,
        executable TEXT NOT NULL DEFAULT '', pid INTEGER, process_created REAL,
        window_class TEXT NOT NULL DEFAULT '', started_at REAL NOT NULL, ended_at REAL,
        foreground_seconds REAL NOT NULL DEFAULT 0, active_seconds REAL NOT NULL DEFAULT 0,
        idle_seconds REAL NOT NULL DEFAULT 0, task_id INTEGER,
        semantic_terms_json TEXT NOT NULL DEFAULT '[]',
        weekday_local INTEGER NOT NULL, hour_local INTEGER NOT NULL,
        is_fullscreen INTEGER NOT NULL DEFAULT 0, is_game INTEGER NOT NULL DEFAULT 0,
        interrupted INTEGER NOT NULL DEFAULT 0)""")
    core.db("""CREATE TABLE IF NOT EXISTS activity_transitions(
        from_app_key TEXT NOT NULL, to_app_key TEXT NOT NULL,
        weekday_local INTEGER NOT NULL, hour_local INTEGER NOT NULL,
        observations INTEGER NOT NULL DEFAULT 0, last_seen REAL NOT NULL,
        PRIMARY KEY(from_app_key,to_app_key,weekday_local,hour_local))""")
    core.db("""CREATE TABLE IF NOT EXISTS activity_tasks(
        id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL,
        terms_json TEXT NOT NULL, app_keys_json TEXT NOT NULL,
        observations INTEGER NOT NULL DEFAULT 0, foreground_seconds REAL NOT NULL DEFAULT 0,
        active_seconds REAL NOT NULL DEFAULT 0, first_seen REAL NOT NULL, last_seen REAL NOT NULL)""")
    core.db("""CREATE TABLE IF NOT EXISTS activity_launches(
        app_key TEXT PRIMARY KEY, last_launch REAL NOT NULL, launch_count INTEGER NOT NULL DEFAULT 0,
        last_result TEXT NOT NULL DEFAULT '')""")
    core.db("CREATE INDEX IF NOT EXISTS ix_activity_sessions_started ON activity_sessions(started_at)")
    core.db("CREATE INDEX IF NOT EXISTS ix_activity_sessions_app ON activity_sessions(app_key,started_at)")
    core.db("CREATE INDEX IF NOT EXISTS ix_activity_transitions_lookup ON activity_transitions(from_app_key,weekday_local,hour_local)")
    core.db("CREATE INDEX IF NOT EXISTS ix_activity_tasks_seen ON activity_tasks(last_seen)")


def semantic_terms(window_title: str, app_name: str = "") -> list[str]:
    """Extract a small dynamic topic vocabulary; never return or store the raw title."""
    raw = str(window_title or "")[:_MAX_WINDOW_TITLE_CHARS]
    # Do not tokenize obvious credentials/URLs/email addresses. This is a
    # conservative local filter, not a claim that all sensitive titles are detected.
    if _SENSITIVE_TITLE_MARKERS.search(raw):
        raw = _SENSITIVE_TITLE_MARKERS.sub(" ", raw)
    raw = re.sub(r"(?i)\\b[A-Z]:\\\\[^\\s|]+", " ", raw)
    raw = re.sub(r"(?i)\\b[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\\b", " ", raw)
    candidates = []
    for token in _TOKEN_RE.findall(raw + " " + str(app_name or "")):
        word = token.casefold().strip("._-")
        if (len(word) < 3 or word in _STOP_WORDS or word.isdigit()
                or any(ch.isdigit() for ch in word) and len(word) > 12):
            continue
        if word not in candidates:
            candidates.append(word)
    return candidates[:_MAX_SEMANTIC_TERMS]


def context_label(terms: list[str]) -> str:
    values = [str(term) for term in terms[:4] if term]
    return " · ".join(values) if values else "General application activity"


def _similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _task_cluster(terms: list[str], app_key: str, app_name: str,
                  foreground_seconds: float, active_seconds: float, ts: float) -> int | None:
    if not terms:
        return None
    incoming = set(terms)
    rows = core.db(
        "SELECT id,terms_json,app_keys_json FROM activity_tasks ORDER BY last_seen DESC LIMIT ?",
        (_MAX_TASK_CLUSTERS,),
    )
    best_id, best_score, best_terms, best_apps = None, 0.0, set(), set()
    for row in rows:
        try:
            existing = set(json.loads(row[1] or "[]"))
            apps = set(json.loads(row[2] or "[]"))
        except (TypeError, ValueError):
            existing, apps = set(), set()
        score = _similarity(incoming, existing)
        if score > best_score:
            best_id, best_score, best_terms, best_apps = int(row[0]), score, existing, apps

    # Dynamic clustering: labels are generated from observed terms, not an
    # application-name/category allowlist.
    if best_id is None or best_score < 0.28:
        task_id = core.insert_id(
            "INSERT INTO activity_tasks(label,terms_json,app_keys_json,observations,foreground_seconds,active_seconds,first_seen,last_seen) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (context_label(terms), json.dumps(terms), json.dumps([app_key]), 1,
             max(0.0, foreground_seconds), max(0.0, active_seconds), ts, ts),
        )
        return task_id

    merged_terms = list(dict.fromkeys([*best_terms, *terms]))[:32]
    merged_apps = list(dict.fromkeys([*best_apps, app_key]))[:40]
    core.db(
        "UPDATE activity_tasks SET label=?,terms_json=?,app_keys_json=?,observations=observations+1,"
        "foreground_seconds=foreground_seconds+?,active_seconds=active_seconds+?,last_seen=? WHERE id=?",
        (context_label(merged_terms), json.dumps(merged_terms), json.dumps(merged_apps),
         max(0.0, foreground_seconds), max(0.0, active_seconds), ts, best_id),
    )
    return best_id


def _window_snapshot() -> dict[str, Any] | None:
    """Read only foreground-process metadata and a short-lived title for local tokenization."""
    if not IS_WIN:
        return None
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value or int(pid.value) == os.getpid():
        return None
    try:
        process = psutil.Process(int(pid.value))
        with process.oneshot():
            name = process.name() or "unknown"
            executable = process.exe() or ""
            created = float(process.create_time())
        settings = _settings()
        title = ""
        if settings["semantic_context"]:
            window_length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(min(_MAX_WINDOW_TITLE_CHARS + 1, max(2, int(window_length) + 1)))
            if window_length:
                user32.GetWindowTextW(hwnd, buffer, len(buffer))
            title = buffer.value[:_MAX_WINDOW_TITLE_CHARS]
        class_buffer = ctypes.create_unicode_buffer(160)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        window_class = class_buffer.value[:160]

        idle_seconds = None
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
        input_info = LASTINPUTINFO()
        input_info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
        user32.GetLastInputInfo.restype = wintypes.BOOL
        if user32.GetLastInputInfo(ctypes.byref(input_info)):
            kernel32 = ctypes.windll.kernel32
            kernel32.GetTickCount.argtypes = []
            kernel32.GetTickCount.restype = wintypes.DWORD
            tick_now = int(kernel32.GetTickCount()) & 0xFFFFFFFF
            idle_seconds = ((tick_now - int(input_info.dwTime)) & 0xFFFFFFFF) / 1000.0

        rect = wintypes.RECT()
        full_screen = False
        if user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            width = int(user32.GetSystemMetrics(0))
            height = int(user32.GetSystemMetrics(1))
            if width > 0 and height > 0:
                full_screen = (
                    int(rect.left) <= 4 and int(rect.top) <= 4
                    and int(rect.right) >= width - 4 and int(rect.bottom) >= height - 4
                )
        process_id = int(pid.value)
        process_name = name[:180]
        app_name = Path(executable).stem[:120] if executable else Path(process_name).stem[:120]
        app_key_source = os.path.normcase(os.path.abspath(executable)) if executable else "name:" + process_name.casefold()
        app_key = hashlib.sha256(app_key_source.encode("utf-8", errors="replace")).hexdigest()[:24]
        configured_games = core.CFG.get("game_processes", [])
        configured_games = {str(item).casefold() for item in configured_games} if isinstance(configured_games, list) else set()
        tracked_game = core.STATE.get("game") if isinstance(core.STATE.get("game"), dict) else {}
        is_game = process_id == int(tracked_game.get("pid") or -1) or process_name.casefold() in configured_games
        own_session = None
        try:
            from .collectors import _session_id
            own_session = _session_id(os.getpid())
            target_session = _session_id(process_id)
        except Exception:
            target_session = None
        if own_session is not None and target_session is not None and target_session != own_session:
            return None

        terms = semantic_terms(title, app_name) if settings["semantic_context"] else semantic_terms("", app_name)
        return {
            "pid": process_id, "process_created": created, "process_name": process_name,
            "app_name": app_name or process_name, "executable": executable,
            "app_key": app_key, "window_class": window_class,
            "terms": terms, "idle_seconds": idle_seconds,
            "fullscreen": full_screen, "is_game": bool(is_game),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError, ValueError):
        return None
    except Exception:
        return None


def _running_executable(path: str) -> bool:
    target = os.path.normcase(os.path.abspath(path))
    for process in psutil.process_iter(["exe"]):
        try:
            current = process.info.get("exe")
            if current and os.path.normcase(os.path.abspath(current)) == target:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return False


def _safe_launch_path(path: str) -> bool:
    """Only previously observed local apps from install/user-app directories are launchable."""
    if not IS_WIN or not path:
        return False
    try:
        candidate = os.path.normcase(os.path.abspath(path))
        if not os.path.isabs(candidate) or not os.path.isfile(candidate):
            return False
        if candidate.startswith("\\\\") or candidate.startswith("\\\\?\\"):
            return False
        roots = [
            os.environ.get("ProgramFiles", r"C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
            os.environ.get("APPDATA", ""),
        ]
        allowed = False
        for root in roots:
            if not root:
                continue
            root_path = os.path.normcase(os.path.abspath(root))
            try:
                if os.path.commonpath([candidate, root_path]) == root_path:
                    allowed = True
                    break
            except ValueError:
                continue
        return allowed and candidate.lower().endswith(".exe")
    except (OSError, ValueError):
        return False


def _launch_observed_app(app_key: str, *, source: str) -> dict[str, Any]:
    rows = core.db(
        "SELECT app_name,executable FROM activity_apps WHERE app_key=? LIMIT 1",
        (str(app_key),),
    )
    if not rows:
        return {"ok": False, "error": "application has not been observed"}
    name, executable = str(rows[0][0]), str(rows[0][1] or "")
    if not _safe_launch_path(executable):
        return {"ok": False, "error": "observed executable is missing or outside the permitted local application folders"}
    if _running_executable(executable):
        return {"ok": False, "error": "application is already running"}
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(
            [executable], cwd=str(Path(executable).parent),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, creationflags=flags,
        )
    except OSError as exc:
        result = f"{type(exc).__name__}: {str(exc)[:140]}"
        core.db(
            "INSERT INTO activity_launches(app_key,last_launch,launch_count,last_result) VALUES(?,?,1,?) "
            "ON CONFLICT(app_key) DO UPDATE SET last_launch=excluded.last_launch,launch_count=activity_launches.launch_count+1,last_result=excluded.last_result",
            (app_key, time.time(), result),
        )
        return {"ok": False, "error": result}
    now = time.time()
    core.db(
        "INSERT INTO activity_launches(app_key,last_launch,launch_count,last_result) VALUES(?,?,1,?) "
        "ON CONFLICT(app_key) DO UPDATE SET last_launch=excluded.last_launch,launch_count=activity_launches.launch_count+1,last_result=excluded.last_result",
        (app_key, now, "started"),
    )
    core.log("activity", f"Opened previously observed application {name}", "ok",
             app_key=app_key, source=source)
    return {"ok": True, "app_name": name, "launched_at": now}


def _suggestions(current_app_key: str, now: float | None = None) -> list[dict[str, Any]]:
    ts = float(now or time.time())
    local = datetime.fromtimestamp(ts).astimezone()
    weekday, hour = local.weekday(), local.hour
    rows = core.db(
        "SELECT t.to_app_key, SUM(t.observations) AS observations, MAX(t.last_seen), "
        "a.app_name,a.executable FROM activity_transitions t "
        "JOIN activity_apps a ON a.app_key=t.to_app_key "
        "WHERE t.from_app_key=? AND t.weekday_local=? "
        "AND MIN(ABS(t.hour_local-?),24-ABS(t.hour_local-?))<=2 "
        "GROUP BY t.to_app_key,a.app_name,a.executable ORDER BY observations DESC LIMIT 8",
        (current_app_key, weekday, hour, hour),
    )
    suggestions = []
    for app_key, observations, last_seen, app_name, executable in rows:
        count = int(observations or 0)
        age_days = max(0.0, (ts - float(last_seen or ts)) / 86400.0)
        confidence = min(0.97, count / (count + 2.5)) * math.exp(-age_days / 120.0)
        suggestions.append({
            "app_key": app_key, "app_name": app_name, "executable": executable,
            "observations": count, "confidence": round(confidence, 3),
            "last_seen": float(last_seen or 0),
            "reason": f"Observed after this application {count} time(s) in a similar weekday/time window",
            "already_running": bool(executable and _running_executable(str(executable))),
            "launchable": _safe_launch_path(str(executable or "")),
            "auto_threshold": count >= _settings()["min_launch_observations"] and confidence >= 0.8,
        })
    return suggestions


def _maybe_auto_launch(current: dict[str, Any], now: float) -> None:
    global _LAST_AUTO_LAUNCH
    settings = _settings()
    if not settings["auto_launch_learned_apps"] or not settings["suggestions_enabled"]:
        return
    if current.get("is_game") or current.get("fullscreen"):
        return
    if current.get("idle_seconds") is not None and current["idle_seconds"] > settings["idle_after_seconds"]:
        return
    if now - _LAST_AUTO_LAUNCH < 1800:
        return
    for suggestion in _suggestions(current["app_key"], now):
        if not suggestion["auto_threshold"] or suggestion["already_running"] or not suggestion["launchable"]:
            continue
        rows = core.db("SELECT last_launch FROM activity_launches WHERE app_key=?", (suggestion["app_key"],))
        if rows and now - float(rows[0][0]) < settings["auto_launch_cooldown_s"]:
            continue
        _LAST_AUTO_LAUNCH = now
        result = _launch_observed_app(suggestion["app_key"], source="learned-routine")
        if not result.get("ok"):
            core.log("activity", "Learned application launch was not completed: " + str(result.get("error", "")), "warn")
        return


def _close_current(ts: float, interrupted: bool = False) -> None:
    global _CURRENT
    current = _CURRENT
    if not current:
        return
    terms = list(current["terms"].keys())[:_MAX_SEMANTIC_TERMS]
    task_id = _task_cluster(
        terms, current["app_key"], current["app_name"],
        current["foreground_seconds"], current["active_seconds"], ts,
    )
    core.db(
        "UPDATE activity_sessions SET ended_at=?,foreground_seconds=?,active_seconds=?,idle_seconds=?,"
        "task_id=?,semantic_terms_json=?,interrupted=? WHERE id=?",
        (ts, current["foreground_seconds"], current["active_seconds"], current["idle_seconds"],
         task_id, json.dumps(terms), int(interrupted), current["session_row_id"]),
    )
    _CURRENT = None


def _record_transition(previous: dict[str, Any], current: dict[str, Any], ts: float) -> None:
    if previous["app_key"] == current["app_key"]:
        return
    # Ignore fleeting focus changes; the former app must have accumulated a
    # minimum dwell time before its next-app relationship is learned.
    if previous.get("active_seconds", 0.0) < 20.0:
        return
    local = datetime.fromtimestamp(ts).astimezone()
    core.db(
        "INSERT INTO activity_transitions(from_app_key,to_app_key,weekday_local,hour_local,observations,last_seen) "
        "VALUES(?,?,?,?,1,?) ON CONFLICT(from_app_key,to_app_key,weekday_local,hour_local) "
        "DO UPDATE SET observations=observations+1,last_seen=excluded.last_seen",
        (previous["app_key"], current["app_key"], local.weekday(), local.hour, ts),
    )


def _begin_segment(item: dict[str, Any], ts: float) -> dict[str, Any]:
    local = datetime.fromtimestamp(ts).astimezone()
    terms = Counter(item.get("terms") or [])
    row_id = core.insert_id(
        "INSERT INTO activity_sessions(app_key,app_name,executable,pid,process_created,window_class,started_at,"
        "foreground_seconds,active_seconds,idle_seconds,semantic_terms_json,weekday_local,hour_local,is_fullscreen,is_game) "
        "VALUES(?,?,?,?,?,?,?,0,0,0,?,?,?,?,?)",
        (item["app_key"], item["app_name"], item["executable"], item["pid"],
         item["process_created"], item["window_class"], ts, json.dumps(list(terms.keys())),
         local.weekday(), local.hour, int(item["fullscreen"]), int(item["is_game"])),
    )
    core.db(
        "INSERT INTO activity_apps(app_key,app_name,executable,first_seen,last_seen,launches,last_window_class,latest_terms_json) "
        "VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(app_key) DO UPDATE SET "
        "app_name=excluded.app_name,executable=CASE WHEN excluded.executable<>'' THEN excluded.executable ELSE activity_apps.executable END,"
        "last_seen=excluded.last_seen,launches=activity_apps.launches+1,last_window_class=excluded.last_window_class,latest_terms_json=excluded.latest_terms_json",
        (item["app_key"], item["app_name"], item["executable"], ts, ts,
         item["window_class"], json.dumps(list(terms.keys()))),
    )
    return {
        **item, "session_row_id": row_id, "started_at": ts, "last_sample": ts,
        "foreground_seconds": 0.0, "active_seconds": 0.0, "idle_seconds": 0.0,
        "terms": terms,
    }


def _sample_once(now: float | None = None, snapshot: dict[str, Any] | None = None) -> None:
    global _CURRENT
    ts = float(now or time.time())
    item = _window_snapshot() if snapshot is None else snapshot
    settings = _settings()
    if not settings["enabled"] or item is None:
        _close_current(ts)
        core.STATE["activity_intelligence"] = {
            "available": IS_WIN, "enabled": settings["enabled"], "state": "idle" if IS_WIN else "unavailable",
            "reason": "No eligible foreground application was observed" if IS_WIN else "Windows foreground APIs are unavailable",
        }
        return

    item = dict(item)
    local = datetime.fromtimestamp(ts).astimezone()
    current = _CURRENT
    same_app = bool(current and current["app_key"] == item["app_key"])
    same_hour = bool(current and (datetime.fromtimestamp(current["started_at"]).astimezone().date() == local.date()
                                  and datetime.fromtimestamp(current["started_at"]).astimezone().hour == local.hour))
    if not same_app or not same_hour:
        previous = current
        _close_current(ts)
        if previous and not same_app:
            _record_transition(previous, item, ts)
        current = _begin_segment(item, ts)
        _CURRENT = current
        _maybe_auto_launch(current, ts)

    current = _CURRENT
    elapsed = max(0.0, min(5.0, ts - float(current["last_sample"])))
    current["last_sample"] = ts
    current["foreground_seconds"] += elapsed
    idle = item.get("idle_seconds")
    is_active = idle is None or float(idle) <= settings["idle_after_seconds"]
    if is_active:
        current["active_seconds"] += elapsed
    else:
        current["idle_seconds"] += elapsed
    for term in item.get("terms") or []:
        current["terms"][term] += 1
    top_terms = [term for term, _ in current["terms"].most_common(_MAX_SEMANTIC_TERMS)]
    core.db(
        "UPDATE activity_sessions SET foreground_seconds=?,active_seconds=?,idle_seconds=?,semantic_terms_json=?,"
        "is_fullscreen=?,is_game=? WHERE id=?",
        (current["foreground_seconds"], current["active_seconds"], current["idle_seconds"],
         json.dumps(top_terms), int(item["fullscreen"]), int(item["is_game"]), current["session_row_id"]),
    )
    core.db(
        "UPDATE activity_apps SET last_seen=?,foreground_seconds=foreground_seconds+?,active_seconds=active_seconds+?,"
        "latest_terms_json=?,last_window_class=? WHERE app_key=?",
        (ts, elapsed, elapsed if is_active else 0.0, json.dumps(top_terms),
         item["window_class"], current["app_key"]),
    )
    core.STATE["activity_intelligence"] = {
        "available": True, "enabled": True, "state": "active" if is_active else "idle",
        "current": {
            "app_key": current["app_key"], "app_name": current["app_name"],
            "executable": current["executable"], "pid": current["pid"],
            "window_class": current["window_class"], "started_at": current["started_at"],
            "foreground_seconds": round(current["foreground_seconds"], 1),
            "active_seconds": round(current["active_seconds"], 1),
            "idle_seconds": round(current["idle_seconds"], 1),
            "idle_for_seconds": round(float(idle or 0), 1) if idle is not None else None,
            "is_active": is_active, "is_fullscreen": bool(item["fullscreen"]),
            "is_game": bool(item["is_game"]), "semantic_terms": top_terms,
            "task_label": context_label(top_terms),
        },
        "sampled_at": ts, "sample_interval_s": settings["sample_interval_s"],
    }


def _worker() -> None:
    core.heartbeat("foreground activity intelligence", _settings()["sample_interval_s"],
                   "foreground application, active/idle time and local semantic context")
    while not _STOP.is_set():
        started = time.monotonic()
        try:
            settings = _settings()
            _sample_once()
            core.heartbeat("foreground activity intelligence", settings["sample_interval_s"],
                           "active screen time and dynamic semantic task clusters" if settings["enabled"] else "disabled by operator")
            if int(time.time()) % 900 < settings["sample_interval_s"]:
                _prune_old(settings["retention_days"])
        except Exception as exc:
            core.heartbeat("foreground activity intelligence", 0,
                           err=f"{type(exc).__name__}: {str(exc)[:150]}")
        remaining = max(0.2, _settings()["sample_interval_s"] - (time.monotonic() - started))
        _STOP.wait(remaining)


def _prune_old(days: int) -> None:
    cut = time.time() - max(7, min(365, int(days))) * 86400
    core.db("DELETE FROM activity_sessions WHERE started_at<?", (cut,))
    core.db("DELETE FROM activity_transitions WHERE last_seen<?", (cut,))
    core.db("DELETE FROM activity_tasks WHERE last_seen<?", (cut,))
    # app identities remain while referenced by recent sessions or transitions.
    core.db("DELETE FROM activity_apps WHERE last_seen<? AND app_key NOT IN (SELECT app_key FROM activity_sessions) "
            "AND app_key NOT IN (SELECT from_app_key FROM activity_transitions) "
            "AND app_key NOT IN (SELECT to_app_key FROM activity_transitions)", (cut,))


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("activity settings must be an object")
    current = _settings()
    allowed = set(DEFAULT_SETTINGS)
    for key, value in payload.items():
        if key not in allowed:
            raise ValueError(f"unknown activity setting: {key}")
        if key in ("enabled", "semantic_context", "suggestions_enabled", "auto_launch_learned_apps"):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be boolean")
        else:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be an integer")
        current[key] = value
    CFG = core.CFG
    CFG["activity"] = current
    core.save_cfg(CFG)
    if not current["enabled"]:
        with _LOCK:
            _close_current(time.time())
    return {"saved": True, "settings": _settings(), "state": core.STATE.get("activity_intelligence", {})}


def launch_app(app_key: str) -> dict[str, Any]:
    if not isinstance(app_key, str) or not re.fullmatch(r"[a-f0-9]{24}", app_key):
        raise ValueError("a valid previously observed application key is required")
    return _launch_observed_app(app_key, source="user-request")


def snapshot() -> dict[str, Any]:
    now = time.time()
    settings = _settings()
    stats = core.STATE.get("activity_intelligence", {})
    current = dict(stats.get("current") or {}) if isinstance(stats.get("current"), dict) else {}
    day_cut = now - 86400
    week_cut = now - 7 * 86400
    app_rows = core.db(
        "SELECT a.app_key,a.app_name,a.executable,a.launches,"
        "COALESCE(SUM(CASE WHEN s.started_at>=? THEN s.foreground_seconds ELSE 0 END),0),"
        "COALESCE(SUM(CASE WHEN s.started_at>=? THEN s.active_seconds ELSE 0 END),0),"
        "MAX(s.started_at) FROM activity_apps a LEFT JOIN activity_sessions s ON s.app_key=a.app_key "
        "GROUP BY a.app_key ORDER BY 6 DESC LIMIT 30",
        (week_cut, week_cut),
    )
    apps = [{
        "app_key": r[0], "app_name": r[1], "executable": r[2],
        "launches": int(r[3] or 0), "foreground_seconds_7d": round(float(r[4] or 0), 1),
        "active_seconds_7d": round(float(r[5] or 0), 1), "last_seen": float(r[6] or 0),
        "launchable": _safe_launch_path(str(r[2] or "")),
    } for r in app_rows]
    hours_rows = core.db(
        "SELECT hour_local,SUM(active_seconds),SUM(foreground_seconds),COUNT(*) "
        "FROM activity_sessions WHERE started_at>=? GROUP BY hour_local ORDER BY hour_local",
        (week_cut,),
    )
    hourly_map = {int(row[0]): {
        "active_seconds": round(float(row[1] or 0), 1),
        "foreground_seconds": round(float(row[2] or 0), 1),
        "sessions": int(row[3] or 0),
    } for row in hours_rows}
    hourly = [{"hour": hour, **hourly_map.get(hour, {"active_seconds": 0.0, "foreground_seconds": 0.0, "sessions": 0})}
              for hour in range(24)]
    task_rows = core.db(
        "SELECT id,label,terms_json,app_keys_json,observations,foreground_seconds,active_seconds,last_seen "
        "FROM activity_tasks ORDER BY active_seconds DESC,last_seen DESC LIMIT 10"
    )
    tasks = []
    for row in task_rows:
        try:
            terms, app_keys = json.loads(row[2] or "[]"), json.loads(row[3] or "[]")
        except (ValueError, TypeError):
            terms, app_keys = [], []
        tasks.append({
            "id": int(row[0]), "label": str(row[1]), "terms": terms,
            "applications": app_keys, "observations": int(row[4] or 0),
            "foreground_seconds": round(float(row[5] or 0), 1),
            "active_seconds": round(float(row[6] or 0), 1), "last_seen": float(row[7] or 0),
        })
    recent_rows = core.db(
        "SELECT id,app_name,app_key,started_at,ended_at,foreground_seconds,active_seconds,idle_seconds,"
        "semantic_terms_json,is_fullscreen,is_game,interrupted FROM activity_sessions "
        "ORDER BY started_at DESC LIMIT ?",
        (_MAX_RECENT_SESSIONS,),
    )
    recent = []
    for row in recent_rows:
        try:
            terms = json.loads(row[8] or "[]")
        except (ValueError, TypeError):
            terms = []
        recent.append({
            "id": int(row[0]), "app_name": row[1], "app_key": row[2],
            "started_at": float(row[3]), "ended_at": float(row[4]) if row[4] else None,
            "foreground_seconds": round(float(row[5] or 0), 1),
            "active_seconds": round(float(row[6] or 0), 1),
            "idle_seconds": round(float(row[7] or 0), 1),
            "semantic_terms": terms, "is_fullscreen": bool(row[9]),
            "is_game": bool(row[10]), "interrupted": bool(row[11]),
        })
    suggestions = _suggestions(str(current["app_key"])) if (
        settings["suggestions_enabled"] and current.get("app_key")
    ) else []
    daily_totals = core.db(
        "SELECT COALESCE(SUM(active_seconds),0),COALESCE(SUM(foreground_seconds),0) "
        "FROM activity_sessions WHERE started_at>=?",
        (day_cut,),
    )
    daily_active = float(daily_totals[0][0] or 0) if daily_totals else 0.0
    daily_foreground = float(daily_totals[0][1] or 0) if daily_totals else 0.0
    return {
        "available": IS_WIN, "enabled": settings["enabled"],
        "state": stats.get("state", "starting" if IS_WIN else "unavailable"),
        "reason": stats.get("reason", "" if IS_WIN else "Windows foreground APIs are unavailable"),
        "sampled_at": stats.get("sampled_at"), "settings": settings,
        "current": current, "daily": {
            "active_seconds": round(daily_active, 1),
            "foreground_seconds": round(daily_foreground, 1),
            "idle_seconds": round(max(0.0, daily_foreground - daily_active), 1),
            "apps_observed": len([app for app in apps if app["last_seen"] >= day_cut]),
        },
        "apps": apps, "hourly": hourly, "tasks": tasks,
        "recent_sessions": recent, "suggestions": suggestions,
        "privacy": {
            "raw_window_titles_persisted": False,
            "browser_urls_or_page_content_collected": False,
            "keystrokes_or_form_values_collected": False,
            "semantic_tokens_local_only": True,
        },
    }


def start() -> None:
    global _STARTED, _WORKER
    if _STARTED:
        return
    _ensure_schema()
    _STOP.clear()
    settings = _settings()
    if not IS_WIN:
        core.STATE["activity_intelligence"] = {
            "available": False, "enabled": settings["enabled"], "state": "unavailable",
            "reason": "Foreground activity intelligence requires the Windows interactive desktop",
        }
        return
    if not settings["enabled"]:
        core.STATE["activity_intelligence"] = {
            "available": True, "enabled": False, "state": "disabled", "reason": "disabled by operator",
        }
        return

    # A previous unclosed interval means the process ended unexpectedly.
    core.db(
        "UPDATE activity_sessions SET ended_at=COALESCE(ended_at,started_at),interrupted=1 "
        "WHERE ended_at IS NULL",
    )
    _STARTED = True
    _WORKER = threading.Thread(target=_worker, name="sentinel-activity-intelligence", daemon=True)
    _WORKER.start()
    core.log("activity", "Foreground activity intelligence started; raw window titles remain memory-only", "ok")


def shutdown() -> None:
    global _STARTED
    _STOP.set()
    with _LOCK:
        _close_current(time.time(), interrupted=True)
    if _WORKER and _WORKER.is_alive():
        _WORKER.join(timeout=3)
    _STARTED = False
