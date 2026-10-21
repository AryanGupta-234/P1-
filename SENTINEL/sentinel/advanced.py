"""SENTINEL advanced tuning, reversible-action journal and bounded ETW diagnostics.

This module intentionally prefers explicit evidence and safe refusal over broad,
opaque operating-system tweaks. Kernel traces use the inbox/Windows Performance
Toolkit ETW controller; no custom driver is installed or required.
"""
from __future__ import annotations

import csv
import ctypes
import datetime as _dt
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import psutil

from . import core
from .core import CFG, IS_WIN, LIVE, STATE, db, heartbeat, insight, log, publish

RISK_TIERS = {
    # Diagnostic capture is read-only apart from a bounded trace file. It may only
    # run unattended after an explicit ETW autopilot opt-in.
    "wpr_trace": "safe",
    "etw_capture": "safe",
    "game_profile_apply": "medium",
    "power_plan": "medium",
    "timer_resolution": "medium",
    "wifi_max_performance": "medium",
    "pause_updater_service": "medium",
    # Actions below are deliberately disabled until a safe, complete undo exists.
    "terminate_process": "dangerous",
    "trim_bg": "dangerous",
    "flush_dns": "dangerous",
    "standby_flush": "dangerous",
    "fan_control": "dangerous",
    "bg_priority": "dangerous",
    "undo_power_plan": "dangerous",
}

SPECIALISTS = {
    "frame_time": "Analyse frame pacing and game responsiveness. Separate measured telemetry from hypotheses. Look for CPU scheduling, GPU clocks, frametime proxies and contention. Never infer FPS or dropped frames unless those measurements exist.",
    "driver_etw": "Analyse Windows ETW evidence for DPC/ISR, interrupts, context switches, disk and network activity. Name a driver only when its module is explicitly present in decoded ETW data; otherwise say attribution is unresolved.",
    "thermal": "Analyse thermal and power limits. Distinguish sensor readings, NVIDIA throttle flags and missing sensors. Never recommend fan curves, voltage changes or firmware changes.",
    "network": "Analyse ping, jitter, loss, DNS and interface evidence. Do not recommend generic registry/TCP tweaks. Only consider a reversible Wi-Fi adapter power policy if the connection is Wi-Fi and latency evidence is abnormal.",
    "memory_io": "Analyse memory pressure, paging, hard faults, disk latency and process I/O. Do not recommend standby-list flushing or arbitrary process termination.",
    "profile_tuner": "Act as a controlled tuning specialist. Suggest only an allowlisted reversible adjustment, state the pre-change metric, success threshold and rollback condition. Never claim execution; the rule engine handles approval and action policy.",
}

BASELINE_METRICS = ("cpu", "mem", "gpu", "gputemp", "gpuclk", "gpupwr", "dpc", "irq", "pagesin", "pagesout", "dlat", "ping", "jitter")
UPDATER_SERVICES = {"gupdate", "gupdatem", "edgeupdate", "edgeupdatem", "adobearmservice"}

_LOCK = threading.RLock()
_STOP = threading.Event()
_STARTED = False
_LAST_BASELINE = 0.0
_LAST_ETW = 0.0
_LAST_GAME_ID: str | None = None
_ETW_OWNED = False
_LAST_THERMAL = {"cpu": False, "gpu": False}
_TIMER_REQUESTS: dict[int, int] = {}
_LAST_GPU_THROTTLE: tuple[str, ...] = ()
_ETW_DONE = threading.Event()
_ETW_DONE.set()
_ETW_CAPTURE_LOCK = threading.Lock()
_UNDO_LOCK = threading.RLock()
_LAST_SESSION_RESTORE_RETRY = 0.0


def _ensure_schema() -> None:
    db("""CREATE TABLE IF NOT EXISTS action_journal(
        id INTEGER PRIMARY KEY AUTOINCREMENT, action_id INTEGER NOT NULL UNIQUE,
        kind TEXT NOT NULL, risk TEXT NOT NULL, created_at REAL NOT NULL,
        before_json TEXT NOT NULL DEFAULT '{}', undo_json TEXT NOT NULL DEFAULT '{}',
        undo_available INTEGER NOT NULL DEFAULT 0, dry_run INTEGER NOT NULL DEFAULT 0,
        changed INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT '', reverted_at REAL,
        revert_result TEXT NOT NULL DEFAULT '')""")
    db("""CREATE TABLE IF NOT EXISTS personal_baselines(
        game_key TEXT NOT NULL, hour_local INTEGER NOT NULL, metric TEXT NOT NULL,
        sample_count INTEGER NOT NULL, mean REAL NOT NULL, m2 REAL NOT NULL,
        min_value REAL NOT NULL, max_value REAL NOT NULL, updated_at REAL NOT NULL,
        PRIMARY KEY(game_key,hour_local,metric))""")
    db("""CREATE TABLE IF NOT EXISTS game_sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT, game_key TEXT NOT NULL, pid INTEGER,
        create_time REAL, started_at REAL NOT NULL, ended_at REAL,
        before_json TEXT NOT NULL, after_json TEXT, report_json TEXT,
        profile_action_id INTEGER, status TEXT NOT NULL DEFAULT 'active')""")
    db("""CREATE TABLE IF NOT EXISTS tuner_experiments(
        id INTEGER PRIMARY KEY AUTOINCREMENT, action_id INTEGER NOT NULL,
        game_session_id INTEGER, metric TEXT NOT NULL, before_value REAL,
        target_direction TEXT NOT NULL, started_at REAL NOT NULL,
        measured_at REAL, after_value REAL, delta_pct REAL, outcome TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '')""")
    db("""CREATE TABLE IF NOT EXISTS etw_attribution(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, trace_path TEXT NOT NULL,
        provider TEXT NOT NULL, event_name TEXT NOT NULL, pid INTEGER, tid INTEGER,
        process_name TEXT, module_name TEXT, duration_us REAL, attribution TEXT NOT NULL,
        evidence_json TEXT NOT NULL DEFAULT '{}')""")
    db("""CREATE TABLE IF NOT EXISTS thermal_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, sensor TEXT NOT NULL,
        event TEXT NOT NULL, value REAL, threshold REAL, detail TEXT NOT NULL DEFAULT '')""")
    db("CREATE INDEX IF NOT EXISTS ix_adv_journal_created ON action_journal(created_at)")
    db("CREATE INDEX IF NOT EXISTS ix_adv_baseline_lookup ON personal_baselines(game_key,hour_local)")
    db("CREATE INDEX IF NOT EXISTS ix_adv_sessions_started ON game_sessions(started_at)")
    db("CREATE INDEX IF NOT EXISTS ix_adv_etw_ts ON etw_attribution(ts)")
    db("CREATE TABLE IF NOT EXISTS session_actions(session_id INTEGER NOT NULL, action_id INTEGER NOT NULL UNIQUE, created_at REAL NOT NULL, PRIMARY KEY(session_id,action_id))")


_ensure_schema()


def risk_tier(kind: str) -> str:
    return RISK_TIERS.get(kind, "dangerous")


def _run(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    from .winutil import run_command
    return run_command(args, timeout=timeout)


def _power_plan() -> str | None:
    if not IS_WIN:
        return None
    try:
        result = _run(["powercfg.exe", "/getactivescheme"], 8)
        text = (result.stdout or "") + " " + (result.stderr or "")
        match = re.search(r"([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})", text)
        return match.group(1).lower() if result.returncode == 0 and match else None
    except Exception:
        return None


def _process_identity(args: dict) -> tuple[psutil.Process, dict]:
    pid = int(args.get("pid", 0))
    created = float(args.get("create_time", -1))
    exe = os.path.normcase(os.path.abspath(str(args.get("exe") or "")))
    if pid <= 4 or created <= 0 or not exe:
        raise ValueError("exact PID, creation time and executable path are required")
    proc = psutil.Process(pid)
    with proc.oneshot():
        current = {"pid": pid, "create_time": proc.create_time(), "exe": os.path.normcase(os.path.abspath(proc.exe() or "")),
                   "name": proc.name(), "priority_class": getattr(proc, "nice", lambda: None)(),
                   "cpu_affinity": proc.cpu_affinity() if hasattr(proc, "cpu_affinity") else None}
    if abs(current["create_time"] - created) > 0.02 or current["exe"] != exe:
        raise ValueError("process identity changed; refresh the process inventory")
    return proc, current


def _cpu_set_inventory() -> dict:
    """Return Windows CPU-set IDs grouped by EfficiencyClass; unavailable is explicit."""
    if not IS_WIN:
        return {"available": False, "reason": "Windows CPU Set API only"}
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = k32.GetSystemCpuSetInformation
        fn.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p, ctypes.c_ulong]
        fn.restype = ctypes.c_bool
        needed = ctypes.c_ulong(0)
        fn(None, 0, ctypes.byref(needed), None, 0)
        if needed.value <= 0 or needed.value > 1_000_000:
            return {"available": False, "reason": "CPU Set API returned an invalid buffer size"}
        buf = ctypes.create_string_buffer(needed.value)
        if not fn(buf, needed.value, ctypes.byref(needed), None, 0):
            return {"available": False, "reason": f"GetSystemCpuSetInformation error {ctypes.get_last_error()}"}
        raw = memoryview(buf.raw[:needed.value])
        groups: dict[int, list[int]] = {}
        index = 0
        while index + 24 <= len(raw):
            size = int.from_bytes(raw[index:index+4], "little")
            typ = int.from_bytes(raw[index+4:index+8], "little")
            if size < 8 or index + size > len(raw):
                break
            if typ == 0 and size >= 24:
                cpu_id = int.from_bytes(raw[index+8:index+12], "little")
                efficiency = int(raw[index+18])
                groups.setdefault(efficiency, []).append(cpu_id)
            index += size
        if not groups:
            return {"available": False, "reason": "No CPU Set records returned"}
        levels = sorted(groups)
        return {"available": True, "efficiency": groups[levels[0]], "performance": groups[levels[-1]],
                "efficiency_class_levels": levels, "sets_by_class": groups,
                "note": "Windows EfficiencyClass ordering is used; validate on this CPU. CPU Sets are a placement preference, not a hard real-time reservation."}
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}


def _get_process_default_cpu_sets(pid: int) -> list[int] | None:
    if not IS_WIN:
        return None
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000 | 0x0400, False, int(pid))  # QUERY_LIMITED_INFORMATION | SET_INFORMATION
        if not h:
            return None
        try:
            fn = k32.GetProcessDefaultCpuSets
            fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
            fn.restype = ctypes.c_bool
            needed = ctypes.c_ulong(0)
            fn(h, None, 0, ctypes.byref(needed))
            if needed.value > 4096:
                return None
            if not needed.value:
                return []
            arr = (ctypes.c_ulong * needed.value)()
            if not fn(h, arr, needed.value, ctypes.byref(needed)):
                return None
            return [int(x) for x in arr[:needed.value]]
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def _set_process_default_cpu_sets(pid: int, cpu_sets: list[int]) -> bool:
    if not IS_WIN:
        return False
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000 | 0x0200, False, int(pid))  # QUERY_LIMITED_INFORMATION | SET_INFORMATION
        if not h:
            return False
        try:
            fn = k32.SetProcessDefaultCpuSets
            fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong]
            fn.restype = ctypes.c_bool
            arr = (ctypes.c_ulong * len(cpu_sets))(*cpu_sets) if cpu_sets else None
            return bool(fn(h, arr, len(cpu_sets)))
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


def action_preview(kind: str, args: dict | None = None) -> dict:
    """Side-effect-free dry run: describe risk, targets, current state and support."""
    args = args or {}
    risk = risk_tier(kind)
    plan: dict[str, Any] = {"kind": kind, "risk": risk, "dry_run": True, "supported": True,
                            "undo_available": kind in {"power_plan", "timer_resolution", "game_profile_apply", "wifi_max_performance", "pause_updater_service", "wpr_trace", "etw_capture"},
                            "automatic_allowed": risk == "safe", "changes": [], "warnings": []}
    if kind == "power_plan":
        plan["supported"] = IS_WIN and bool(_power_plan())
        plan["current_power_plan"] = _power_plan() or "unavailable"
        plan["changes"] = ["Set the active Windows power scheme to the selected performance scheme"]
        if not IS_WIN: plan["warnings"].append("Windows power management is available only on Windows")
    elif kind == "timer_resolution":
        ms = int(args.get("milliseconds", 1))
        plan["supported"] = IS_WIN and ms in (1, 2)
        plan["changes"] = [f"Request {ms} ms multimedia timer resolution for the Sentinel process lifetime"]
        plan["warnings"].append("This is a process-scoped request, not a guarantee of lower input latency.")
    elif kind == "game_profile_apply":
        try:
            _, ident = _process_identity(args)
            plan["target"] = ident
            plan["changes"] = ["Apply the saved per-game process priority and selected CPU Set policy"]
        except Exception as exc:
            plan["supported"] = False; plan["warnings"].append(str(exc))
    elif kind == "wifi_max_performance":
        plan["supported"] = IS_WIN
        plan["changes"] = ["Set the current power plan's Wi-Fi adapter AC power-saving mode to Maximum Performance"]
        plan["warnings"].append("Offered only after persistent ping/jitter evidence and a confirmed active Wi-Fi adapter. No TCP registry settings are changed.")
    elif kind == "pause_updater_service":
        svc = str(args.get("service") or "").casefold()
        plan["supported"] = IS_WIN and svc in UPDATER_SERVICES
        plan["changes"] = [f"Stop allowlisted third-party updater service {svc}; restart it on game exit/undo if it was running"]
        plan["warnings"].append("Microsoft Update, Defender and security services are never stopped by this action.")
    elif kind in ("standby_flush", "fan_control", "trim_bg", "flush_dns", "terminate_process"):
        plan["supported"] = False
        plan["undo_available"] = False
        plan["warnings"].append("This action is not enabled because it cannot meet the reversible-action contract safely.")
    elif kind == "wpr_trace":
        wpr = shutil.which("wpr.exe") or (r"C:\Windows\System32\wpr.exe" if IS_WIN else None)
        plan["supported"] = bool(IS_WIN and wpr and os.path.isfile(wpr))
        plan["changes"] = ["Capture a bounded 15-second WPR GeneralProfile.Light ETW trace"]
        plan["warnings"].append("Requires Windows Performance Recorder. Existing WPR recordings will never be stopped or replaced.")
    elif kind == "etw_capture":
        plan["supported"] = bool(IS_WIN and locate_xperf())
        plan["changes"] = ["Capture a bounded NT Kernel Logger window (process, scheduler, DPC/ISR, disk and network providers)"]
        plan["warnings"].append("Requires Windows Performance Toolkit xperf and permission to start a kernel trace. Existing logger sessions will never be stopped or replaced.")
    else:
        plan["supported"] = False; plan["warnings"].append("Unknown action")
    return plan


def prepare_action(action_id: int, kind: str, args: dict, *, dry_run: bool = False) -> dict:
    """Snapshot state before an action and enforce a per-action rate limit."""
    preview = action_preview(kind, args)
    if not preview["supported"]:
        raise ValueError("action not supported: " + "; ".join(preview["warnings"]))
    if dry_run:
        return preview
    risk = risk_tier(kind)
    if risk == "dangerous":
        raise PermissionError("dangerous actions are never automatic and this action is disabled until it has a safe undo")
    now = time.time()
    if kind in {"power_plan", "timer_resolution", "wifi_max_performance", "pause_updater_service"}:
        session_id = STATE.get("advanced", {}).get("active_session_id")
        if not session_id:
            raise RuntimeError(f"{kind} requires an active tracked game session; no change was made")
    recent = db("SELECT created_at FROM action_journal WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,))
    if recent and now - float(recent[0][0]) < 30:
        raise RuntimeError("rate limited: wait 30 seconds before repeating this action")
    global_recent = db("SELECT COUNT(*) FROM action_journal WHERE created_at>=?", (now - 60,))
    if global_recent and int(global_recent[0][0]) >= 3:
        raise RuntimeError("global rate limit: no more than three state-changing actions per minute")
    before: dict[str, Any] = {}
    undo: dict[str, Any] = {}
    undo_available = False
    if kind == "power_plan":
        old = _power_plan()
        if not old:
            raise RuntimeError("could not read the current Windows power plan; action refused")
        battery = psutil.sensors_battery()
        if battery is not None and not battery.power_plugged:
            raise RuntimeError("power-plan tuning is disabled on battery; connect AC power before applying")
        before = {"power_plan": old}
        undo = {"kind": "power_plan", "power_plan": old}
        undo_available = True
    elif kind == "timer_resolution":
        ms = int(args.get("milliseconds", 1))
        if not IS_WIN or ms not in (1, 2): raise ValueError("timer resolution supports 1 or 2 ms on Windows only")
        before = {"sentinel_timer_requests": dict(_TIMER_REQUESTS)}
        undo = {"kind": "timer_resolution", "milliseconds": ms}
        undo_available = True
    elif kind == "game_profile_apply":
        proc, ident = _process_identity(args)
        active_game = STATE.get("game") if isinstance(STATE.get("game"), dict) else None
        if not active_game or int(active_game.get("pid") or 0) != ident["pid"]:
            raise RuntimeError("game profile may only target the currently detected game process")
        try:
            if abs(float(active_game.get("create_time") or 0) - ident["create_time"]) > 0.02:
                raise RuntimeError("tracked game process identity changed; refresh the game session")
        except (TypeError, ValueError):
            raise RuntimeError("tracked game creation time is unavailable; game profile refused")
        current_cpu_sets = _get_process_default_cpu_sets(ident["pid"])
        profile = args.get("profile") if isinstance(args.get("profile"), dict) else {}
        old_power = _power_plan() if profile.get("apply_power_plan") else None
        timer_ms = int(profile.get("timer_resolution_ms", 0) or 0)
        if (profile.get("cpu_set_policy") in ("efficiency", "performance") or profile.get("background_efficiency_allowlist")) and current_cpu_sets is None:
            raise RuntimeError("could not snapshot the game process CPU Set state; refusing a non-reversible placement change")
        if profile.get("apply_power_plan") and not old_power:
            raise RuntimeError("could not snapshot the active power plan; game profile was not applied")
        if profile.get("apply_power_plan"):
            battery = psutil.sensors_battery()
            if battery is not None and not battery.power_plugged:
                raise RuntimeError("game power-plan tuning is disabled on battery; connect AC power before applying this profile")
        background_names = {str(x).casefold() for x in profile.get("background_efficiency_allowlist", []) if isinstance(x, str)}
        background = []
        for row in STATE.get("procs", []):
            if (str(row.get("name") or "").casefold() in background_names and int(row.get("session_id") or 0) > 0
                    and int(row.get("onscreen_windows") or 0) == 0 and int(row.get("pid") or 0) != ident["pid"]):
                try:
                    bp, bi = _process_identity({"pid": row["pid"], "create_time": row["create_time"], "exe": row["exe"]})
                    previous_sets = _get_process_default_cpu_sets(bi["pid"])
                    if previous_sets is None:
                        continue  # never move a background process unless its prior state can be snapshotted
                    background.append({"pid": bi["pid"], "create_time": bi["create_time"], "exe": bi["exe"],
                                       "default_cpu_sets": previous_sets})
                except Exception:
                    continue
        before = {**ident, "default_cpu_sets": current_cpu_sets, "power_plan": old_power, "timer_request_ms": timer_ms,
                  "background_processes": background}
        undo = {"kind": "game_profile_apply", "pid": ident["pid"], "create_time": ident["create_time"], "exe": ident["exe"],
                "priority_class": ident["priority_class"], "cpu_affinity": ident["cpu_affinity"], "default_cpu_sets": current_cpu_sets,
                "background_processes": background, "power_plan": old_power, "timer_resolution_ms": timer_ms}
        undo_available = True
    elif kind == "wifi_max_performance":
        if not IS_WIN: raise RuntimeError("Windows only")
        evidence = _check_network_evidence()
        if not evidence.get("candidate"):
            raise RuntimeError("Wi-Fi power tuning requires persistent elevated ping/jitter evidence")
        if not wifi_connected():
            raise RuntimeError("no connected Wi-Fi adapter detected; no network setting changed")
        battery = psutil.sensors_battery()
        if not (battery and battery.power_plugged):
            raise RuntimeError("Wi-Fi power tuning is AC-only; connect power before proposing this change")
        old = _wifi_power_setting()
        if not old: raise RuntimeError("could not read current Wi-Fi power policy")
        before = old
        undo = {"kind": "wifi_max_performance", **old}
        undo_available = True
    elif kind == "pause_updater_service":
        service = str(args.get("service") or "").casefold()
        if service not in UPDATER_SERVICES: raise ValueError("service is not in SENTINEL's third-party updater allowlist")
        state = _service_state(service)
        if state != "running":
            raise RuntimeError(f"updater {service} is {state or 'unknown'}, not running; SENTINEL will not change its pre-existing state")
        before = {"service": service, "state": state}
        undo = {"kind": "pause_updater_service", "service": service, "was_running": True}
        undo_available = True
    elif kind in ("wpr_trace", "etw_capture"):
        before = {"trace_directory": core.TRACE_DIR, "created_at": now}
        undo = {"kind": "delete_trace", "path": ""}
        undo_available = True
    else:
        raise ValueError("no reversible implementation for this action")
    db("INSERT INTO action_journal(action_id,kind,risk,created_at,before_json,undo_json,undo_available) VALUES(?,?,?,?,?,?,?)",
       (int(action_id), kind, risk, now, json.dumps(before, sort_keys=True), json.dumps(undo, sort_keys=True), int(undo_available)))
    return {"risk": risk, "before": before, "undo_available": undo_available}


def _wifi_power_setting() -> dict | None:
    if not IS_WIN: return None
    subgroup = "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1"
    setting = "12bbebe6-58d6-4636-95bb-3217ef867c1a"
    scheme = _power_plan()
    if not scheme: return None
    result = _run(["powercfg.exe", "/query", scheme, subgroup, setting], 8)
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0: return None
    ac = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)", text)
    if not ac: return None
    return {"scheme": scheme, "subgroup": subgroup, "setting": setting, "ac_index": int(ac.group(1), 16)}



def wifi_connected() -> bool:
    """Return true only when Windows reports an Up Wi-Fi interface."""
    if not IS_WIN:
        return False
    command = "Get-NetAdapter -Physical -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' -and ($_.Name -match 'Wi-?Fi|Wireless' -or $_.InterfaceDescription -match 'Wi-?Fi|Wireless|802.11') } | Select-Object -First 1 Name"
    try:
        result = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], 8)
        return result.returncode == 0 and bool((result.stdout or "").strip())
    except Exception:
        return False


def apply_wifi_max_performance() -> str:
    if not IS_WIN: raise RuntimeError("Windows only")
    battery = psutil.sensors_battery()
    if not battery or not battery.power_plugged: raise RuntimeError("AC power is required; refusing to change Wi-Fi power policy on battery")
    old = _wifi_power_setting()
    if not old: raise RuntimeError("Wi-Fi AC power setting could not be read; no change applied")
    r = _run(["powercfg.exe", "/setacvalueindex", old["scheme"], old["subgroup"], old["setting"], "0"], 8)
    if r.returncode != 0: raise RuntimeError("powercfg could not set Wi-Fi maximum performance")
    active = _run(["powercfg.exe", "/setactive", old["scheme"]], 8)
    if active.returncode != 0: raise RuntimeError("Wi-Fi policy was changed but the active scheme could not be refreshed")
    return f"Wi-Fi adapter AC power policy set to maximum performance (previous index {old['ac_index']}; undo restores it)"

def _service_state(name: str) -> str | None:
    if not IS_WIN: return None
    safe = name.replace("'", "''")
    r = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
              f"$s=Get-Service -Name '{safe}' -ErrorAction Stop; $s.Status.ToString().ToLowerInvariant()"], 8)
    value = (r.stdout or "").strip().casefold()
    return value if r.returncode == 0 and value in ("running", "stopped", "paused") else None


def mark_action_result(action_id: int, result: str, changed: bool) -> None:
    rows = db("SELECT kind,undo_json FROM action_journal WHERE action_id=?", (int(action_id),))
    if not rows: return
    kind = rows[0][0]
    try: undo = json.loads(rows[0][1] or "{}")
    except Exception: undo = {}
    # Store the exact applied state so rollback can detect concurrent user changes.
    if kind == "power_plan":
        undo["applied_plan"] = _power_plan()
    if kind in ("wpr_trace", "etw_capture"):
        candidates = re.findall(r"(?:[A-Za-z]:\\|/)[^\r\n]+?\.etl", str(result), re.I)
        if candidates:
            candidate = os.path.abspath(candidates[-1].strip().rstrip(".,;"))
            root = os.path.abspath(core.TRACE_DIR)
            try:
                if os.path.commonpath([candidate, root]) == root:
                    undo["path"] = candidate
            except ValueError:
                pass
    if kind == "wifi_max_performance":
        undo["applied_ac_index"] = 0
    if kind == "game_profile_apply":
        profile = db("SELECT args FROM actions WHERE id=?", (int(action_id),))
        if profile:
            try: payload = json.loads(profile[0][0] or "{}")
            except Exception: payload = {}
            p = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
            if p.get("apply_power_plan"):
                undo["applied_plan"] = _power_plan()
            undo["timer_applied_ms"] = int(p.get("timer_resolution_ms", 0) or 0)
            # Capture exact post-application values. Undo restores only fields that
            # still equal the values SENTINEL applied, preserving later user changes.
            try:
                proc, ident = _process_identity({k: undo.get(k) for k in ("pid", "create_time", "exe")})
                undo["applied_priority_class"] = getattr(proc, "nice", lambda: None)()
                undo["applied_cpu_affinity"] = proc.cpu_affinity() if hasattr(proc, "cpu_affinity") else None
                undo["applied_default_cpu_sets"] = _get_process_default_cpu_sets(ident["pid"])
            except Exception:
                undo["applied_process_state_captured"] = False
            else:
                undo["applied_process_state_captured"] = True
            captured_background = []
            for item in undo.get("background_processes", []):
                snap = dict(item)
                try:
                    bp, bi = _process_identity({"pid": snap["pid"], "create_time": snap["create_time"], "exe": snap["exe"]})
                    snap["applied_default_cpu_sets"] = _get_process_default_cpu_sets(bi["pid"])
                except Exception:
                    snap["applied_default_cpu_sets"] = None
                captured_background.append(snap)
            undo["background_processes"] = captured_background
    db("UPDATE action_journal SET changed=?,result=?,undo_json=? WHERE action_id=?",
       (int(bool(changed)), str(result)[:800], json.dumps(undo, sort_keys=True), int(action_id)))
    if changed:
        experiments = db("SELECT id,metric,started_at,before_value FROM tuner_experiments WHERE action_id=? AND outcome='awaiting_approval'", (int(action_id),))
        for exp_id, metric, requested_at, before_value in experiments:
            age = time.time() - float(requested_at)
            if before_value is None or age > 180:
                reason = "baseline missing" if before_value is None else f"approval arrived {age:.0f}s after baseline; baseline expired"
                result = undo_action(int(action_id))
                db("UPDATE tuner_experiments SET measured_at=?,outcome=?,detail=? WHERE id=?",
                   (time.time(), "rolled_back_stale_baseline" if result.get("ok") else "rollback_failed_stale_baseline",
                    f"{reason}; {result.get('result') or result.get('error') or 'rollback unknown'}"[:500], exp_id))
            else:
                db("UPDATE tuner_experiments SET started_at=?,outcome='measuring',detail=? WHERE id=?",
                   (time.time(), f"pre-action baseline retained; request age {age:.1f}s", exp_id))


def apply_game_profile(args: dict) -> str:
    if not IS_WIN: return "skipped (Windows only)"
    proc, ident = _process_identity(args)
    profile = args.get("profile") if isinstance(args.get("profile"), dict) else {}
    priority_name = str(profile.get("priority", "above_normal"))
    priorities = {"normal": psutil.NORMAL_PRIORITY_CLASS, "below_normal": psutil.BELOW_NORMAL_PRIORITY_CLASS,
                  "above_normal": psutil.ABOVE_NORMAL_PRIORITY_CLASS}
    if priority_name not in priorities: raise ValueError("priority must be normal, below_normal or above_normal")
    proc.nice(priorities[priority_name])
    affinity = profile.get("affinity")
    affinity_applied = False
    if affinity is not None:
        if not isinstance(affinity, list) or not affinity or len(affinity) > psutil.cpu_count():
            raise ValueError("affinity must be a non-empty list of logical CPU indexes")
        cpus = sorted(set(int(x) for x in affinity))
        if min(cpus) < 0 or max(cpus) >= psutil.cpu_count(): raise ValueError("affinity contains an invalid CPU index")
        proc.cpu_affinity(cpus); affinity_applied = True
    cpu_policy = str(profile.get("cpu_set_policy", "unchanged"))
    cpu_set_applied = False
    selected = []
    if cpu_policy in ("efficiency", "performance") or profile.get("background_efficiency_allowlist"):
        sets = _cpu_set_inventory()
        if not sets.get("available"):
            raise RuntimeError("Windows CPU Set topology unavailable; no affinity fallback was applied")
        if cpu_policy in ("efficiency", "performance"):
            selected = sets[cpu_policy]
            if not selected: raise RuntimeError(f"no {cpu_policy} CPU Sets reported")
            if not _set_process_default_cpu_sets(ident["pid"], selected):
                raise RuntimeError(f"SetProcessDefaultCpuSets failed ({ctypes.get_last_error()})")
            cpu_set_applied = True
        bg_sets = sets["efficiency"]
        allow_names = {str(x).casefold() for x in profile.get("background_efficiency_allowlist", []) if isinstance(x, str)}
        moved = 0
        for row in STATE.get("procs", []):
            if (str(row.get("name") or "").casefold() not in allow_names or int(row.get("pid") or 0) == ident["pid"]
                    or int(row.get("session_id") or 0) <= 0 or int(row.get("onscreen_windows") or 0) > 0):
                continue
            try:
                bp, bi = _process_identity({"pid": row["pid"], "create_time": row["create_time"], "exe": row["exe"]})
                if _set_process_default_cpu_sets(bi["pid"], bg_sets): moved += 1
            except Exception:
                continue
    plan = _power_plan() if profile.get("apply_power_plan") else None
    if profile.get("apply_power_plan"):
        target = str(profile.get("power_plan_guid") or "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c")
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", target): raise ValueError("invalid power plan GUID")
        r = _run(["powercfg.exe", "/setactive", target], 10)
        if r.returncode != 0: raise RuntimeError("powercfg could not activate the selected plan")
    timer_ms = int(profile.get("timer_resolution_ms", 0) or 0)
    if timer_ms:
        if timer_ms not in (1, 2): raise ValueError("timer resolution must be disabled, 1 or 2 ms")
        _timer_request(timer_ms, begin=True)
    return f"Game profile applied to {ident['name']} PID {ident['pid']}: priority={priority_name}, affinity={'set' if affinity_applied else 'unchanged'}, CPU Sets={'set' if cpu_set_applied else 'unchanged'}, background efficiency-core targets={moved if 'moved' in locals() else 0}, power={'changed' if plan else 'unchanged'}, timer={timer_ms or 'unchanged'} ms"


def _timer_request(milliseconds: int, *, begin: bool) -> None:
    if not IS_WIN: raise RuntimeError("Windows only")
    if int(milliseconds) not in (1, 2): raise ValueError("timer request must be 1 or 2 ms")
    winmm = ctypes.WinDLL("winmm", use_last_error=True)
    fn = winmm.timeBeginPeriod if begin else winmm.timeEndPeriod
    fn.argtypes = [ctypes.c_uint]
    fn.restype = ctypes.c_uint
    if not begin and _TIMER_REQUESTS.get(int(milliseconds), 0) <= 0:
        raise RuntimeError("no matching SENTINEL timer request is active")
    code = int(fn(int(milliseconds)))
    if code != 0: raise OSError(code, "multimedia timer request failed")
    current = _TIMER_REQUESTS.get(int(milliseconds), 0) + (1 if begin else -1)
    if current > 0: _TIMER_REQUESTS[int(milliseconds)] = current
    else: _TIMER_REQUESTS.pop(int(milliseconds), None)
    STATE.setdefault("advanced", {})["active_timer_ms"] = max(_TIMER_REQUESTS, default=None)


def _restore(undo: dict) -> str:
    kind = undo.get("kind")
    if kind == "power_plan":
        original = str(undo.get("power_plan") or "")
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", original): raise ValueError("invalid power-plan restore value")
        current = _power_plan()
        applied = undo.get("applied_plan")
        if not current:
            raise RuntimeError("active power scheme is unknown; previous scheme was not forced and rollback will retry")
        if applied and current != applied:
            return "not restored: active power scheme changed after SENTINEL's action; preserving user change"
        r = _run(["powercfg.exe", "/setactive", original], 10)
        if r.returncode != 0: raise RuntimeError("could not restore previous power plan")
        return f"restored previous power plan {original}"
    if kind == "timer_resolution":
        period = int(undo.get("milliseconds", 1))
        if _TIMER_REQUESTS.get(period, 0) <= 0:
            return "timer request already ended with the previous Sentinel process; no system timer setting remains to restore"
        _timer_request(period, begin=False)
        return "released SENTINEL's multimedia timer-resolution request"
    if kind == "game_profile_apply":
        args = {k: undo.get(k) for k in ("pid", "create_time", "exe")}
        partial = []
        try:
            proc, _ = _process_identity(args)
            process_alive = True
        except Exception:
            proc = None
            process_alive = False
            partial.append("game process has exited or changed identity; process-scoped settings no longer apply")
        # Restore process state only if it still equals the exact values SENTINEL applied.
        if process_alive and undo.get("applied_process_state_captured"):
            current_priority = getattr(proc, "nice", lambda: None)()
            if current_priority == undo.get("applied_priority_class") and undo.get("priority_class") is not None:
                proc.nice(undo["priority_class"])
            elif current_priority != undo.get("priority_class"):
                partial.append("priority changed independently; left untouched")
            current_affinity = proc.cpu_affinity() if hasattr(proc, "cpu_affinity") else None
            applied_affinity = undo.get("applied_cpu_affinity")
            prior_affinity = undo.get("cpu_affinity")
            if applied_affinity is not None and current_affinity == applied_affinity and isinstance(prior_affinity, list):
                proc.cpu_affinity(prior_affinity)
            elif applied_affinity is not None and current_affinity != prior_affinity:
                partial.append("affinity changed independently; left untouched")
        elif process_alive:
            partial.append("post-apply process snapshot unavailable; process settings left untouched")
        prior = undo.get("default_cpu_sets")
        applied_sets = undo.get("applied_default_cpu_sets")
        target_cpu_set_failed = False
        if process_alive and prior is not None and applied_sets is not None:
            current_sets = _get_process_default_cpu_sets(int(undo["pid"]))
            if current_sets is None:
                target_cpu_set_failed = True
                restore_failures.append("game process CPU Set state is temporarily unreadable")
            elif current_sets == applied_sets:
                target_cpu_set_failed = not _set_process_default_cpu_sets(int(undo["pid"]), prior)
                if target_cpu_set_failed:
                    restore_failures.append("game process CPU Set restore failed")
            elif current_sets != prior:
                partial.append("CPU Sets changed independently; left untouched")
        background_failures = 0
        restore_failures = []
        for item in undo.get("background_processes", []):
            try:
                bp, _ = _process_identity({"pid": item["pid"], "create_time": item["create_time"], "exe": item["exe"]})
                old_sets = item.get("default_cpu_sets")
                applied_bg = item.get("applied_default_cpu_sets")
                current_bg = _get_process_default_cpu_sets(int(item["pid"]))
                if old_sets is not None and applied_bg is not None and current_bg is None:
                    background_failures += 1
                    restore_failures.append(f"background PID {item['pid']} CPU Set state is temporarily unreadable")
                elif old_sets is not None and applied_bg is not None and current_bg == applied_bg:
                    if not _set_process_default_cpu_sets(int(item["pid"]), old_sets):
                        background_failures += 1
                        restore_failures.append(f"background PID {item['pid']} CPU Set restore failed")
                elif current_bg != old_sets:
                    partial.append(f"background PID {item['pid']} CPU Sets changed independently; left untouched")
            except psutil.NoSuchProcess:
                # Exited background process no longer has a persistent CPU Set assignment.
                continue
            except Exception:
                background_failures += 1
        timer_ms = int(undo.get("timer_applied_ms") or 0)
        if timer_ms and _TIMER_REQUESTS.get(timer_ms, 0) > 0:
            _timer_request(timer_ms, begin=False)
        if undo.get("power_plan"):
            current = _power_plan()
            applied = undo.get("applied_plan")
            if applied and current and current != applied:
                partial.append("power plan changed independently; left untouched")
            elif not current:
                restore_failures.append("active power plan is unknown; previous plan was not forced")
            else:
                r = _run(["powercfg.exe", "/setactive", str(undo["power_plan"])], 10)
                if r.returncode != 0:
                    restore_failures.append("previous power plan could not be restored")
        details = f"restored eligible game-process settings; {len(undo.get('background_processes', [])) - background_failures} background CPU Set target(s) handled"
        if target_cpu_set_failed: details += "; target CPU Set restore incomplete"
        if background_failures: details += f"; {background_failures} background restore(s) incomplete"
        if partial: details += "; " + "; ".join(partial[:5])
        if restore_failures:
            raise RuntimeError(details + "; retry required: " + "; ".join(restore_failures[:5]))
        return details
    if kind == "wifi_max_performance":
        scheme = str(undo.get("scheme") or "")
        subgroup, setting = undo.get("subgroup"), undo.get("setting")
        index = int(undo.get("ac_index"))
        current = _wifi_power_setting()
        if not current:
            raise RuntimeError("current Wi-Fi power policy could not be read; no value was overwritten and rollback will retry")
        if current.get("scheme") != scheme or current.get("ac_index") != undo.get("applied_ac_index", 0):
            return "not restored: Wi-Fi power policy or active scheme changed after SENTINEL's action; preserving user change"
        r = _run(["powercfg.exe", "/setacvalueindex", scheme, subgroup, setting, hex(index)], 8)
        if r.returncode != 0: raise RuntimeError("could not restore previous Wi-Fi AC policy")
        _run(["powercfg.exe", "/setactive", scheme], 8)
        return "restored previous Wi-Fi AC power-saving index"
    if kind == "pause_updater_service":
        if undo.get("was_running"):
            service = str(undo.get("service") or "")
            if service.casefold() not in UPDATER_SERVICES: raise ValueError("updater service is not allowlisted")
            current_state = _service_state(service)
            if current_state == "running": return f"updater service {service} is already running; no change made"
            if current_state is None:
                raise RuntimeError(f"updater service {service} state is unknown; restore will retry")
            if current_state != "stopped": return f"not restarted: {service} state is {current_state}; preserving external state"
            r = _run(["sc.exe", "start", service], 15)
            if r.returncode != 0: raise RuntimeError("could not restart previously running updater service")
            return f"restarted previously running updater service {service}"
        return "service was stopped before SENTINEL's action; left stopped"
    if kind == "delete_trace":
        raw_path = str(undo.get("path") or "").strip()
        if not raw_path:
            return "no SENTINEL trace file was created; nothing to remove"
        path = os.path.abspath(raw_path)
        root = os.path.abspath(core.TRACE_DIR)
        if os.path.commonpath([path, root]) != root or not path.lower().endswith(".etl"):
            raise ValueError("trace path is outside the SENTINEL trace directory")
        if os.path.exists(path): os.remove(path)
        db("UPDATE trace_archive SET status='removed by undo' WHERE file_path=?", (path,))
        return "removed SENTINEL-captured ETL file"
    raise ValueError("no undo handler for this action")


def capture_failed_action_state(action_id: int) -> None:
    """Capture post-failure values so partial writes can be conditionally undone."""
    rows = db("SELECT kind,undo_json FROM action_journal WHERE action_id=?", (int(action_id),))
    if not rows:
        return
    kind = rows[0][0]
    try:
        undo = json.loads(rows[0][1] or "{}")
    except Exception:
        undo = {}
    if kind == "power_plan":
        undo["applied_plan"] = _power_plan()
    elif kind == "game_profile_apply":
        try:
            proc, ident = _process_identity({k: undo.get(k) for k in ("pid", "create_time", "exe")})
            undo["applied_priority_class"] = getattr(proc, "nice", lambda: None)()
            undo["applied_cpu_affinity"] = proc.cpu_affinity() if hasattr(proc, "cpu_affinity") else None
            undo["applied_default_cpu_sets"] = _get_process_default_cpu_sets(ident["pid"])
            undo["applied_process_state_captured"] = True
        except Exception:
            undo["applied_process_state_captured"] = False
        captured = []
        for item in undo.get("background_processes", []):
            snap = dict(item)
            try:
                bp, bi = _process_identity({"pid": snap["pid"], "create_time": snap["create_time"], "exe": snap["exe"]})
                snap["applied_default_cpu_sets"] = _get_process_default_cpu_sets(bi["pid"])
            except Exception:
                snap["applied_default_cpu_sets"] = None
            captured.append(snap)
        undo["background_processes"] = captured
        action = db("SELECT args FROM actions WHERE id=?", (int(action_id),))
        if action:
            try:
                profile = json.loads(action[0][0] or "{}").get("profile", {})
            except Exception:
                profile = {}
            if isinstance(profile, dict):
                if profile.get("apply_power_plan"):
                    undo["applied_plan"] = _power_plan()
                undo["timer_applied_ms"] = int(profile.get("timer_resolution_ms", 0) or 0)
    db("UPDATE action_journal SET undo_json=? WHERE action_id=?",
       (json.dumps(undo, sort_keys=True), int(action_id)))


def undo_action(action_id: int) -> dict:
    """Perform a journaled undo at most once per process; concurrent callers serialize."""
    with _UNDO_LOCK:
        rows = db("SELECT undo_json,undo_available,reverted_at FROM action_journal WHERE action_id=?", (int(action_id),))
        if not rows: return {"ok": False, "error": "no undo journal exists for this action"}
        if not rows[0][1]: return {"ok": False, "error": "this action has no safe automatic undo"}
        if rows[0][2]: return {"ok": False, "error": "this action has already been reverted"}
        try:
            undo = json.loads(rows[0][0] or "{}")
            result = _restore(undo)
            db("UPDATE action_journal SET reverted_at=?,revert_result=? WHERE action_id=? AND reverted_at IS NULL",
               (time.time(), result, int(action_id)))
            log("rollback", f"Action #{action_id}: {result}", "ok")
            return {"ok": True, "result": result}
        except Exception as exc:
            result = f"{type(exc).__name__}: {str(exc)[:180]}"
            db("UPDATE action_journal SET revert_result=? WHERE action_id=?", (result, int(action_id)))
            log("rollback", f"Action #{action_id} rollback failed: {result}", "error")
            return {"ok": False, "error": result}

def revert_all() -> dict:
    rows = db("SELECT action_id FROM action_journal WHERE undo_available=1 AND changed=1 AND reverted_at IS NULL ORDER BY id DESC LIMIT 500")
    results = [dict(action_id=int(r[0]), **undo_action(int(r[0]))) for r in rows]
    return {"attempted": len(results), "reverted": sum(1 for r in results if r.get("ok")), "results": results}


def list_journal(limit: int = 100) -> list[dict]:
    rows = db("SELECT action_id,kind,risk,created_at,before_json,undo_available,changed,result,reverted_at,revert_result FROM action_journal ORDER BY id DESC LIMIT ?", (min(500, max(1, int(limit))),))
    out = []
    for r in rows:
        try: before = json.loads(r[4] or "{}")
        except Exception: before = {}
        out.append({"action_id": r[0], "kind": r[1], "risk": r[2], "created_at": r[3], "before": before,
                    "undo_available": bool(r[5]), "changed": bool(r[6]), "result": r[7], "reverted_at": r[8], "revert_result": r[9]})
    return out


def _metric_mean(metric: str, seconds: int = 30) -> tuple[float | None, int]:
    values = core.window(metric, seconds)
    clean = []
    for value in values:
        try:
            n = float(value)
            if math.isfinite(n): clean.append(n)
        except (TypeError, ValueError):
            continue
    if len(clean) < 8:
        return None, len(clean)
    import statistics
    return float(statistics.mean(clean)), len(clean)


def start_tuner_experiment(kind: str, args: dict, metric: str, direction: str) -> dict:
    """Create a user-approved experiment around one reversible allowlisted action."""
    allowed_metrics = {"cpu", "dpc", "irq", "pagesin", "pagesout", "dlat", "ping", "jitter", "gpu", "gpuclk", "gputemp", "gpupwr"}
    if metric not in allowed_metrics:
        raise ValueError("metric is not eligible for the closed-loop tuner")
    if direction not in ("lower", "higher"):
        raise ValueError("direction must be lower or higher")
    preview = action_preview(kind, args)
    if not preview.get("supported") or not preview.get("undo_available") or risk_tier(kind) != "medium":
        raise ValueError("tuner accepts only supported, reversible medium-risk actions")
    before, count = _metric_mean(metric, 30)
    if before is None:
        raise ValueError(f"insufficient recent {metric} samples ({count}/8); tuner did not propose a change")
    from . import actions
    action_id = actions.propose(kind, args, origin="closed-loop-tuner", reason=f"Controlled experiment: seek {direction} {metric}; baseline {before:.3f}")
    if not action_id:
        raise RuntimeError("rule engine refused the proposed action")
    db("INSERT INTO tuner_experiments(action_id,game_session_id,metric,before_value,target_direction,started_at,outcome,detail) VALUES(?,?,?,?,?,?,?,?)",
       (int(action_id), STATE.get("advanced", {}).get("active_session_id"), metric, before, direction, time.time(), "awaiting_approval", f"baseline samples={count}"))
    return {"action_id": int(action_id), "metric": metric, "before": before, "samples": count,
            "direction": direction, "risk": preview["risk"], "requires_approval": True,
            "message": "No adjustment has been made. Approve the action in Control to start measurement."}


def _evaluate_tuner(ts: float) -> None:
    rows = db("SELECT id,action_id,metric,before_value,target_direction,started_at FROM tuner_experiments WHERE outcome='measuring' ORDER BY id LIMIT 20")
    for row in rows:
        exp_id, action_id, metric, before, direction, started = row
        if ts - float(started) < 60:
            continue
        after, count = _metric_mean(str(metric), 45)
        if after is None:
            if ts - float(started) < 180:
                continue
            result = undo_action(int(action_id))
            outcome = "rolled_back_insufficient_data" if result.get("ok") else "rollback_failed_insufficient_data"
            detail = result.get("result") or result.get("error") or f"only {count} measurement samples"
            db("UPDATE tuner_experiments SET measured_at=?,outcome=?,detail=? WHERE id=?",
               (ts, outcome, str(detail)[:500], exp_id))
            continue
        before_value = float(before)
        signed = ((before_value - after) if direction == "lower" else (after - before_value))
        delta_pct = (signed / abs(before_value) * 100.0) if abs(before_value) > 1e-6 else None
        # Require a measured >=3% improvement; otherwise revert rather than
        # perpetuating a change whose benefit is not visible in the chosen signal.
        if delta_pct is not None and delta_pct >= 3.0:
            outcome = "kept_improved"
            detail = f"{metric} moved from {before_value:.3f} to {after:.3f} ({delta_pct:.2f}% improvement over {count} samples); change retained"
        else:
            result = undo_action(int(action_id))
            outcome = "rolled_back_no_improvement" if result.get("ok") else "rollback_failed_no_improvement"
            detail = f"{metric} moved from {before_value:.3f} to {after:.3f}; improvement was below 3%. " + str(result.get("result") or result.get("error") or "rollback result unknown")
        db("UPDATE tuner_experiments SET measured_at=?,after_value=?,delta_pct=?,outcome=?,detail=? WHERE id=?",
           (ts, after, delta_pct, outcome, detail[:700], exp_id))
        log("tuner", detail, "ok" if outcome == "kept_improved" else "warn")


def _current_metrics() -> dict:
    data = {}
    for key in BASELINE_METRICS:
        value = LIVE.get(key)
        if value is None:
            continue
        try:
            number = float(value)
            if math.isfinite(number): data[key] = number
        except (TypeError, ValueError):
            continue
    gpu = STATE.get("gpu", {})
    for src, dst in (("temp", "gputemp"), ("clk", "gpuclk"), ("pwr", "gpupwr")):
        try:
            value = float(gpu.get(src))
            if math.isfinite(value): data[dst] = value
        except (TypeError, ValueError): pass
    return data


def _baseline_sample(game_key: str, hour: int, metrics: dict, ts: float) -> None:
    for name, value in metrics.items():
        rows = db("SELECT sample_count,mean,m2,min_value,max_value FROM personal_baselines WHERE game_key=? AND hour_local=? AND metric=?", (game_key, hour, name))
        if rows:
            n, mean, m2, low, high = rows[0]
            n2 = int(n) + 1
            delta = value - float(mean)
            mean2 = float(mean) + delta / n2
            m22 = float(m2) + delta * (value - mean2)
            low2, high2 = min(float(low), value), max(float(high), value)
        else:
            n2, mean2, m22, low2, high2 = 1, value, 0.0, value, value
        db("INSERT INTO personal_baselines(game_key,hour_local,metric,sample_count,mean,m2,min_value,max_value,updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
           "ON CONFLICT(game_key,hour_local,metric) DO UPDATE SET sample_count=excluded.sample_count,mean=excluded.mean,m2=excluded.m2,min_value=excluded.min_value,max_value=excluded.max_value,updated_at=excluded.updated_at",
           (game_key, hour, name, n2, mean2, m22, low2, high2, ts))


def _baseline_for(game_key: str, hour: int) -> dict:
    rows = db("SELECT metric,sample_count,mean,m2,min_value,max_value,updated_at FROM personal_baselines WHERE game_key=? AND hour_local=?", (game_key, hour))
    return {r[0]: {"samples": r[1], "mean": r[2], "stddev": math.sqrt(max(0.0, r[3] / max(1, r[1] - 1))),
                   "min": r[4], "max": r[5], "updated_at": r[6]} for r in rows}


def _correlate_window(start: float, end: float) -> list[dict]:
    """Return bounded changes near a spike; all links are temporal, not causal."""
    out: list[dict] = []
    rows = db("SELECT ts,level,src,msg,data FROM events WHERE ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 100", (start, end))
    allowed = {"process", "services", "eventlog", "inventory", "network", "ETW", "thermal", "kernel", "game", "baseline"}
    for r in rows:
        src = str(r[2] or "")
        if not any(key.casefold() in src.casefold() for key in allowed):
            continue
        try: data = json.loads(r[4] or "{}")
        except Exception: data = {}
        out.append({"ts": r[0], "seconds_before_spike": round(end-r[0], 1), "level": r[1], "source": src,
                    "event": r[3], "evidence": data, "relationship": "temporal association; causality not established"})
    etw_rows = db("SELECT ts,provider,event_name,pid,tid,process_name,module_name,attribution,evidence_json FROM etw_attribution WHERE ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 50", (start, end))
    for r in etw_rows:
        try: evidence = json.loads(r[8] or "{}")
        except Exception: evidence = {}
        out.append({"ts": r[0], "seconds_before_spike": round(end-r[0], 1), "level": "info", "source": "ETW",
                    "event": r[2], "evidence": {"provider": r[1], "pid": r[3], "tid": r[4], "process": r[5], "module": r[6],
                    "attribution": r[7], "fields": evidence}, "relationship": "ETW temporal evidence; attribution confidence depends on available PID/module fields"})
    thermal_rows = db("SELECT ts,sensor,event,value,threshold,detail FROM thermal_events WHERE ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 30", (start, end))
    for r in thermal_rows:
        out.append({"ts": r[0], "seconds_before_spike": round(end-r[0], 1), "level": "warn", "source": "thermal",
                    "event": f"{r[1]}: {r[2]}", "evidence": {"value": r[3], "threshold": r[4], "detail": r[5]},
                    "relationship": "thermal/power event near the spike; causality not established"})
    action_rows = db("SELECT ts,kind,state,result,args FROM actions WHERE ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 30", (start, end))
    for r in action_rows:
        try: args = json.loads(r[4] or "{}")
        except Exception: args = {}
        out.append({"ts": r[0], "seconds_before_spike": round(end-r[0], 1), "level": "info", "source": "SENTINEL action",
                    "event": f"{r[1]} · {r[2]}", "evidence": {"result": r[3], "args": args},
                    "relationship": "recorded SENTINEL action near the spike; outcome is not evidence of causation"})
    out.sort(key=lambda x: float(x.get("ts") or 0), reverse=True)
    return out[:30]


def _sample_active_game(ts: float) -> None:
    global _LAST_BASELINE
    if ts - _LAST_BASELINE < 15: return
    _LAST_BASELINE = ts
    game = STATE.get("game")
    if not isinstance(game, dict): return
    game_key = str(game.get("name") or "unknown-game").casefold()
    hour = _dt.datetime.fromtimestamp(ts).hour
    metrics = _current_metrics()
    # Compare against the baseline before incorporating this sample so a spike
    # cannot dilute the very baseline used to classify it.
    baseline = _baseline_for(game_key, hour)
    for name, value in metrics.items():
        ref = baseline.get(name)
        if not ref or ref["samples"] < 12: continue
        std = max(ref["stddev"], abs(ref["mean"]) * 0.08, 0.1)
        if value > ref["mean"] + 3.0 * std and name in ("cpu", "gpu", "gputemp", "dpc", "irq", "pagesin", "dlat", "ping", "jitter"):
            key = f"baseline-{game_key}-{hour}-{name}"
            recent = db("SELECT ts FROM events WHERE src='baseline' AND msg LIKE ? ORDER BY id DESC LIMIT 1", (f"%{name}%",))
            if not (recent and ts - recent[0][0] < 300):
                related = _correlate_window(ts - 120, ts)
                detail = f"{name}={value:.2f}; personal baseline mean {ref['mean']:.2f}, stddev {ref['stddev']:.2f}, samples {ref['samples']}. "
                detail += "Nearby observations are temporal candidates only; they do not prove cause."
                db("INSERT INTO events(ts,level,src,msg,data) VALUES(?,?,?,?,?)",
                   (ts, "warn", "baseline", f"Personal baseline deviation: {name}", json.dumps({"game": game_key, "hour": hour, "metric": name, "observed": value, "baseline": ref, "correlated_events": related})))
                insight("warn", key, f"Outside personal baseline: {name}", detail, game_key)
    _baseline_sample(game_key, hour, metrics, ts)


def _metrics_delta(before: dict, after: dict) -> dict:
    out = {}
    for key in sorted(set(before) | set(after)):
        a, b = before.get(key), after.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out[key] = {"before": a, "after": b, "delta": round(b-a, 3),
                        "delta_pct": round((b-a)/abs(a)*100, 2) if abs(a) > 1e-9 else None}
    return out


def _start_game_session(game: dict, ts: float) -> int:
    key = str(game.get("name") or "unknown-game").casefold()
    metrics = _current_metrics()
    cur = db("INSERT INTO game_sessions(game_key,pid,create_time,started_at,before_json,status) VALUES(?,?,?,?,?,'active')",
             (key, int(game.get("pid") or 0), float(game.get("create_time") or 0), ts, json.dumps(metrics, sort_keys=True)))
    sid = db("SELECT MAX(id) FROM game_sessions")[0][0]
    log("session", f"Game session started: {game.get('name')}", "ok", session_id=sid, game=key)
    publish("game_session", {"id": sid, "game": key, "state": "started"})
    return int(sid)


def _restore_session_actions(session_id: int) -> list[dict]:
    """Restore only journaled changes linked to this session; dismiss stale proposals."""
    ids: list[int] = []
    profile_rows = db("SELECT profile_action_id FROM game_sessions WHERE id=?", (int(session_id),))
    if profile_rows and profile_rows[0][0]:
        ids.append(int(profile_rows[0][0]))
    linked = db("SELECT action_id FROM session_actions WHERE session_id=? ORDER BY created_at DESC", (int(session_id),))
    ids.extend(int(row[0]) for row in linked)
    outcomes: list[dict] = []
    for action_id in dict.fromkeys(ids):
        journal = db("SELECT changed,reverted_at FROM action_journal WHERE action_id=?", (action_id,))
        if journal:
            if journal[0][0] and not journal[0][1]:
                result = undo_action(action_id)
                outcomes.append({"action_id": action_id, **result})
            continue
        action_rows = db("SELECT state FROM actions WHERE id=?", (action_id,))
        if action_rows and action_rows[0][0] == "pending":
            try:
                from . import actions
                actions.dismiss(action_id)
                outcomes.append({"action_id": action_id, "ok": True, "result": "pending proposal dismissed because its game session ended"})
            except Exception as exc:
                outcomes.append({"action_id": action_id, "ok": False, "error": f"could not dismiss pending action: {type(exc).__name__}: {str(exc)[:140]}"})
    return outcomes


def _end_game_session(session_id: int, ts: float) -> dict:
    """Close a session only after its linked state has been restored or safely refused.

    A failed undo leaves the row in restore_pending so the next engine/restart pass
    can retry it. This prevents a crash between report generation and rollback from
    silently marking an unrestored session as completed.
    """
    rows = db("SELECT game_key,started_at,before_json FROM game_sessions WHERE id=? AND status IN ('active','restore_pending')",
              (int(session_id),))
    if not rows:
        return {"ok": False, "error": "no active or restore-pending game session"}
    game_key, started, before_raw = rows[0]
    try:
        before = json.loads(before_raw or "{}")
    except Exception:
        before = {}
    after = _current_metrics()
    delta = _metrics_delta(before, after)
    causes = _correlate_window(float(started), ts)
    report_enabled = CFG.get("advanced", {}).get("auto_report_sessions", True) is True
    restore_results = _restore_session_actions(int(session_id))
    failures = [item for item in restore_results if not item.get("ok")]
    report = {
        "game": game_key,
        "duration_seconds": round(max(0.0, ts - float(started)), 1),
        "before": before,
        "after": after,
        "delta": delta,
        "temporal_candidates": causes if report_enabled else [],
        "restoration": restore_results,
        "restoration_pending": bool(failures),
        "limitations": [
            "Session snapshots are endpoints, not a controlled A/B experiment.",
            "Correlated changes are temporal associations, not proven causes.",
            "FPS/frame-time values are not inferred if no frame telemetry source is available.",
            "Rollback preserves external changes and may remain pending when Windows refuses a restore.",
        ],
    }
    status = "restore_pending" if failures else "completed"
    db("UPDATE game_sessions SET ended_at=?,after_json=?,report_json=?,status=? WHERE id=?",
       (ts, json.dumps(after, sort_keys=True), json.dumps(report, sort_keys=True) if report_enabled else None,
        status, int(session_id)))
    if failures:
        log("rollback", f"Game session #{session_id} ended but {len(failures)} linked change(s) still need restoration; retry scheduled",
            "error", session_id=int(session_id), failures=failures[:8])
    else:
        log("session", f"Game session ended: {game_key} ({int(max(0.0, ts-float(started)))} s); linked changes restored or safely preserved",
            "ok", session_id=int(session_id))
    publish("game_session", {"id": int(session_id), "game": game_key, "state": status, "report": report})
    return report

def _service_loop_restore_on_game_end(session_id: int) -> None:
    """Compatibility wrapper for older callers; uses the unified session journal."""
    _restore_session_actions(int(session_id))


def _retry_pending_session_restores(ts: float) -> None:
    global _LAST_SESSION_RESTORE_RETRY
    if ts - _LAST_SESSION_RESTORE_RETRY < 30:
        return
    _LAST_SESSION_RESTORE_RETRY = ts
    rows = db("SELECT id FROM game_sessions WHERE status='restore_pending' ORDER BY ended_at LIMIT 20")
    for row in rows:
        try:
            _end_game_session(int(row[0]), ts)
        except Exception as exc:
            log("rollback", f"Session #{int(row[0])} restore retry failed: {type(exc).__name__}: {str(exc)[:140]}",
                "error", session_id=int(row[0]))


def _cpu_temperature_threshold(sensor: str) -> float:
    config = CFG.get("advanced", {}) if isinstance(CFG.get("advanced"), dict) else {}
    key = "cpu_temp_warn_c" if sensor == "cpu" else "gpu_temp_warn_c"
    default = 88.0 if sensor == "cpu" else 82.0
    try: return float(config.get(key, default))
    except (TypeError, ValueError): return default


def _thermal_watch(ts: float) -> None:
    global _LAST_GPU_THROTTLE
    hardware = STATE.get("hardware_sensors", {})
    cpu_values = hardware.get("cpu_temperatures") or []
    cpu_max = max((float(x.get("value")) for x in cpu_values if isinstance(x.get("value"), (int, float))), default=None)
    try: gpu_temp = float((STATE.get("gpu") or {}).get("temp"))
    except (TypeError, ValueError): gpu_temp = None
    for sensor, value in (("cpu", cpu_max), ("gpu", gpu_temp)):
        if value is None: continue
        threshold = _cpu_temperature_threshold(sensor)
        hot = value >= threshold
        if hot and not _LAST_THERMAL[sensor]:
            _LAST_THERMAL[sensor] = True
            detail = f"{sensor.upper()} sensor reports {value:.1f}°C (early-warning threshold {threshold:.1f}°C)."
            db("INSERT INTO thermal_events(ts,sensor,event,value,threshold,detail) VALUES(?,?,?,?,?,?)",
               (ts, sensor, "pre_throttle_warning", value, threshold, detail))
            insight("high" if value >= threshold + 5 else "warn", f"thermal-{sensor}-warning", f"Thermal headroom low: {sensor.upper()}", detail, sensor)
        elif not hot and _LAST_THERMAL[sensor]:
            _LAST_THERMAL[sensor] = False
            db("INSERT INTO thermal_events(ts,sensor,event,value,threshold,detail) VALUES(?,?,?,?,?,?)",
               (ts, sensor, "temperature_recovered", value, threshold, f"{sensor.upper()} returned below warning threshold"))
    throttle = tuple(sorted(str(x) for x in (STATE.get("gpu") or {}).get("throttle", []) if x))
    if throttle != _LAST_GPU_THROTTLE:
        if throttle:
            db("INSERT INTO thermal_events(ts,sensor,event,value,threshold,detail) VALUES(?,?,?,?,?,?)",
               (ts, "gpu", "gpu_throttle_flag_changed", None, None, "NVIDIA reported throttle reason(s): " + ", ".join(throttle)))
        elif _LAST_GPU_THROTTLE:
            db("INSERT INTO thermal_events(ts,sensor,event,value,threshold,detail) VALUES(?,?,?,?,?,?)",
               (ts, "gpu", "gpu_throttle_flag_cleared", None, None, "NVIDIA no longer reports active throttle reasons"))
        _LAST_GPU_THROTTLE = throttle


def _lhm_sample() -> dict:
    """Read an already-running LHM/OpenHardwareMonitor WMI provider; never launch/install it."""
    if not IS_WIN:
        return {"available": False, "reason": "Windows only"}
    config = CFG.get("advanced", {}) if isinstance(CFG.get("advanced"), dict) else {}
    if config.get("lhm_enabled") is not True:
        return {"available": False, "reason": "Optional hardware sensor reader disabled"}

    # WMI namespaces use a single backslash. Query both the current
    # LibreHardwareMonitor namespace and its predecessor for compatibility.
    command = r"""
$ErrorActionPreference = 'Stop'
$providerNamespace = $null
$sensors = @()
$probeErrors = @()
foreach ($ns in @('root\LibreHardwareMonitor', 'root\OpenHardwareMonitor')) {
    try {
        $found = @(Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction Stop |
            Where-Object { $null -ne $_.Value } |
            Select-Object -First 300 Name,Parent,SensorType,Value,Identifier)
        if ($found.Count -gt 0) {
            $providerNamespace = $ns
            $sensors = $found
            break
        }
    } catch {
        $probeErrors += ($ns + ': ' + $_.Exception.Message)
    }
}
if (-not $providerNamespace) {
    throw ('No running hardware sensor WMI provider returned data. ' + ($probeErrors -join ' | '))
}
[pscustomobject]@{ namespace = $providerNamespace; sensors = @($sensors) } |
    ConvertTo-Json -Compress -Depth 4
"""
    try:
        r = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], 12)
        if r.returncode != 0:
            return {"available": False, "reason": (r.stderr or r.stdout or "WMI provider did not respond")[:220]}
        raw = (r.stdout or "").strip()
        if not raw:
            return {"available": False, "reason": "Hardware sensor WMI provider returned empty output"}
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "sensors" in parsed:
            provider_namespace = str(parsed.get("namespace") or "unknown")
            sensor_rows = parsed.get("sensors") or []
        else:
            # Older PowerShell script output / test fixtures may contain a bare
            # CIM sensor array.
            provider_namespace = "unknown"
            sensor_rows = parsed if isinstance(parsed, list) else [parsed]
        if isinstance(sensor_rows, dict):
            sensor_rows = [sensor_rows]

        normalized = []
        for sensor in sensor_rows[:300]:
            if not isinstance(sensor, dict):
                continue
            try:
                value = float(sensor.get("Value"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            normalized.append({
                "name": str(sensor.get("Name") or "")[:120],
                "parent": str(sensor.get("Parent") or "")[:180],
                "type": str(sensor.get("SensorType") or "")[:40],
                "value": value,
                "identifier": str(sensor.get("Identifier") or "")[:220],
            })
        if not normalized:
            return {"available": False, "reason": "WMI namespace responded but exposed no numeric sensors",
                    "namespace": provider_namespace}

        cpu_temperatures = []
        per_core_temperatures = []
        fan_rpm = []
        hardware_names = set()
        for sensor in normalized:
            name = sensor["name"].casefold()
            parent = sensor["parent"].casefold()
            identifier = sensor["identifier"].casefold().replace("\\", "/")
            kind = sensor["type"].casefold()
            value = sensor["value"]
            if sensor["parent"]:
                hardware_names.add(sensor["parent"])
            # LHM labels Intel/AMD CPU hardware by model name (e.g. "Intel Core
            # i5-12500H"), not always with the literal word CPU. Identifiers are
            # the most stable fallback across vendor naming variations.
            cpu_hardware = any(token in (parent + " " + identifier) for token in (
                "intelcpu", "amdcpu", "intel core", "amd ryzen", "cpu", "processor"
            ))
            explicitly_gpu = any(token in (parent + " " + name + " " + identifier) for token in (
                "nvidia", "geforce", "radeon", "graphics", "gpu", "video"
            ))
            cpu_named = any(token in name for token in ("cpu package", "cpu core", "processor package"))
            if kind == "temperature" and -10.0 <= value <= 130.0 and (cpu_hardware or cpu_named) and not explicitly_gpu:
                cpu_temperatures.append(sensor)
                if re.search(r"\bcore\s*(?:#|\d|\[)", name) or "cpu core" in name:
                    per_core_temperatures.append(sensor)
            if kind == "fan" and 0.0 < value <= 30000.0:
                fan_rpm.append(sensor)

        return {
            "available": True,
            "source": "externally-running hardware-monitor WMI provider",
            "provider": "LibreHardwareMonitor" if "LibreHardwareMonitor" in provider_namespace else "OpenHardwareMonitor",
            "namespace": provider_namespace,
            "checked_at": time.time(),
            "cpu_temperatures": cpu_temperatures[:48],
            "per_core_temperatures": per_core_temperatures[:64],
            "fan_rpm": fan_rpm[:32],
            "sensor_count": len(normalized),
            "hardware": sorted(hardware_names)[:40],
            "cpu_sensor_count": len(cpu_temperatures),
            "fan_sensor_count": len(fan_rpm),
            "cpu_reason": "" if cpu_temperatures else "Provider is running, but no CPU temperature sensors were exposed for this hardware",
            "fan_reason": "" if fan_rpm else "Provider is running, but no fan RPM sensors were exposed; ASUS EC fan telemetry may not be supported",
        }
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}



def _hardware_loop() -> None:
    while not _STOP.is_set():
        try:
            if IS_WIN and CFG.get("advanced", {}).get("lhm_enabled") is True:
                result = _lhm_sample()
                STATE["hardware_sensors"] = result
                heartbeat("optional hardware sensors (LHM)", 5, f"{result.get('sensor_count', 0)} sensor(s)" if result.get("available") else result.get("reason", "unavailable"),
                          "" if result.get("available") else result.get("reason", "unavailable"))
            elif not CFG.get("advanced", {}).get("lhm_enabled"):
                STATE["hardware_sensors"] = {"available": False, "reason": "Optional LHM reader disabled"}
            _thermal_watch(time.time())
        except Exception as exc:
            heartbeat("optional hardware sensors (LHM)", 5, err=f"{type(exc).__name__}: {str(exc)[:100]}")
        _STOP.wait(5)


def locate_xperf() -> str | None:
    for candidate in (shutil.which("xperf.exe"), r"C:\Program Files (x86)\Windows Kits\10\Windows Performance Toolkit\xperf.exe",
                      r"C:\Program Files\Windows Kits\10\Windows Performance Toolkit\xperf.exe"):
        if candidate and os.path.isfile(candidate): return candidate
    return None


def _parse_dpc_report(path: str) -> list[dict]:
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")[:2_000_000]
    except OSError:
        return []
    out = []
    for line in content.splitlines():
        # xperf's dpcisr summary includes module/function names and execution duration.
        if not line.strip() or not re.search(r"\.sys\b", line, re.I): continue
        module = re.search(r"([A-Za-z0-9_.-]+\.sys)", line, re.I)
        nums = re.findall(r"\d+(?:\.\d+)?", line)
        if not module: continue
        out.append({"module": module.group(1), "line": line.strip()[:500], "numeric_fields": nums[:8],
                    "attribution": "driver module named by xperf dpcisr summary"})
        if len(out) >= 50: break
    return out


def _etl_local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _etw_int(value: Any) -> int | None:
    try:
        raw = str(value).strip()
        if not raw:
            return None
        return int(raw, 0)
    except (TypeError, ValueError):
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None


def _etw_process_name_for_pid(pid: int | None, process_starts: dict[int, str], trace_end: float) -> str | None:
    if not pid:
        return None
    if pid in process_starts:
        return process_starts[pid]
    # The live process list is only a fallback. Reject a PID that was created
    # after the captured trace window, which is evidence of PID reuse.
    for row in STATE.get("procs", []):
        try:
            if int(row.get("pid", -1)) != int(pid):
                continue
            created = float(row.get("create_time"))
            if created <= trace_end + 1.0:
                return str(row.get("name") or "") or None
            return None
        except (TypeError, ValueError):
            continue
    return None


def _parse_etw_xml(xml_path: str, trace_end: float | None = None) -> dict:
    """Parse tracerpt XML into bounded event evidence without guessing attribution."""
    trace_end = float(trace_end if trace_end is not None else time.time())
    raw_events: list[dict] = []
    process_starts: dict[int, str] = {}
    try:
        for _, elem in ET.iterparse(xml_path, events=("end",)):
            if _etl_local_name(elem.tag) != "Event":
                continue
            system = next((node for node in elem.iter() if _etl_local_name(node.tag) == "System"), None)
            if system is None:
                elem.clear()
                continue

            def child(parent, wanted):
                return next((node for node in parent if _etl_local_name(node.tag) == wanted), None)

            provider_node = child(system, "Provider")
            provider = provider_node.attrib.get("Name", "") if provider_node is not None else ""
            event_id_node = child(system, "EventID")
            task_node = child(system, "Task")
            opcode_node = child(system, "Opcode")
            event_id = (event_id_node.text or "") if event_id_node is not None else ""
            task = (task_node.text or "") if task_node is not None else ""
            opcode = (opcode_node.text or "") if opcode_node is not None else ""
            execution = child(system, "Execution")
            header_pid = _etw_int(execution.attrib.get("ProcessID")) if execution is not None else None
            tid = _etw_int(execution.attrib.get("ThreadID")) if execution is not None else None
            created_node = child(system, "TimeCreated")
            event_ts = trace_end
            if created_node is not None and created_node.attrib.get("SystemTime"):
                try:
                    event_ts = _dt.datetime.fromisoformat(created_node.attrib["SystemTime"].replace("Z", "+00:00")).timestamp()
                except (TypeError, ValueError, OverflowError):
                    event_ts = trace_end
            fields = {}
            for node in elem.iter():
                if _etl_local_name(node.tag) == "Data":
                    key = str(node.attrib.get("Name") or "")[:100]
                    if key:
                        fields[key] = (node.text or "")[:220]

            normalized_fields = {
                re.sub(r"[^a-z0-9]", "", key.casefold()): value for key, value in fields.items()
            }
            payload_pid = next((
                _etw_int(normalized_fields[key])
                for key in ("processid", "pid", "processidentifier", "targetprocessid")
                if key in normalized_fields and _etw_int(normalized_fields[key]) is not None
            ), None)
            signature = f"{provider} {task} {event_id} {opcode}".casefold()
            event_name = f"{task or 'Event'}:{event_id or '?'}:{opcode or '?'}"
            image_value = next((
                value for key, value in normalized_fields.items()
                if key in ("imagefilename", "imagename", "processname", "processpath", "filename")
                and str(value).strip()
            ), "")
            image_name = re.split(r"[\\/]", str(image_value).strip().strip('"'))[-1] if image_value else ""
            target_pid = payload_pid or header_pid
            if target_pid and image_name and image_name.casefold().endswith((".exe", ".com")) and (
                ("process" in signature and ("start" in signature or event_id in ("1", "10")))
            ):
                process_starts[int(target_pid)] = image_name[:180]

            module_name = None
            for key, value in fields.items():
                normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
                if not any(token in normalized_key for token in ("module", "driver", "routine", "image", "file", "path")):
                    continue
                match = re.search(r"([a-z0-9_.-]+\.sys)\b", str(value), re.I)
                if match:
                    module_name = match.group(1)[:180]
                    break

            relevant = any(token in signature for token in (
                "dpc", "interrupt", "cswitch", "disk", "tcp", "process", "thread", "image", "driver", "network", "kernel"
            )) or bool(module_name)
            if relevant and len(raw_events) < 1500:
                pid = target_pid
                duration_us = None
                for key, value in normalized_fields.items():
                    if any(token in key for token in ("durationus", "dpctimeus", "isrtimeus")):
                        try:
                            parsed_duration = float(value)
                            if math.isfinite(parsed_duration) and parsed_duration >= 0:
                                duration_us = parsed_duration
                        except (TypeError, ValueError):
                            pass
                        break
                raw_events.append({
                    "ts": float(event_ts),
                    "provider": provider[:180],
                    "event_name": event_name[:220],
                    "pid": pid,
                    "tid": tid,
                    "pid_source": "event payload" if payload_pid is not None else ("ETW execution header" if header_pid is not None else "unavailable"),
                    "process_name": None,
                    "module_name": module_name,
                    "duration_us": duration_us,
                    "fields": fields,
                    "signature": signature,
                })
            elem.clear()
    except Exception as exc:
        return {"ok": False, "reason": f"ETW XML parse failed: {type(exc).__name__}: {str(exc)[:160]}", "events": []}

    for event in raw_events:
        event["process_name"] = _etw_process_name_for_pid(event.get("pid"), process_starts, trace_end)
        event["fields"]["_sentinel_pid_source"] = event["pid_source"]
        event["fields"]["_sentinel_process_attribution"] = (
            "ETW ProcessStart image event" if event.get("pid") in process_starts
            else "current process inventory with PID-reuse time guard" if event.get("process_name")
            else "unresolved"
        )
        event.pop("signature", None)
        event.pop("pid_source", None)
    return {
        "ok": True,
        "events": raw_events,
        "process_start_count": len(process_starts),
        "process_attribution_count": sum(1 for event in raw_events if event.get("process_name")),
        "unattributed_event_count": sum(1 for event in raw_events if not event.get("process_name") and not event.get("module_name")),
    }


def _decode_etl(etl_path: str, trace_id: str, trace_end: float | None = None) -> dict:
    """Decode tracerpt metadata and xperf DPC/ISR summary with explicit attribution confidence."""
    trace_dir = os.path.dirname(etl_path)
    xml_path = os.path.join(trace_dir, trace_id + ".xml")
    txt_path = os.path.join(trace_dir, trace_id + "-dpcisr.txt")
    tracerpt = shutil.which("tracerpt.exe")
    if not tracerpt:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        candidates = (
            os.path.join(system_root, "Sysnative", "tracerpt.exe"),
            os.path.join(system_root, "System32", "tracerpt.exe"),
        )
        tracerpt = next((path for path in candidates if os.path.isfile(path)), None)
    if not tracerpt:
        return {"decoded": False, "reason": "tracerpt.exe unavailable", "event_count": 0,
                "named_driver_modules": [], "process_attribution_count": 0}
    r = _run([tracerpt, etl_path, "-o", xml_path, "-of", "XML", "-y"], 120)
    if r.returncode != 0 or not os.path.isfile(xml_path):
        return {"decoded": False, "reason": ((r.stderr or r.stdout or "tracerpt failed")[:220]),
                "event_count": 0, "named_driver_modules": [], "process_attribution_count": 0}
    try:
        parsed = _parse_etw_xml(xml_path, trace_end)
        if not parsed.get("ok"):
            return {"decoded": False, "reason": parsed.get("reason", "ETW XML parse failed"),
                    "event_count": 0, "named_driver_modules": [], "process_attribution_count": 0}
        events = parsed["events"]
        xperf = locate_xperf()
        drivers = []
        driver_report_available = False
        if xperf:
            dr = _run([xperf, "-i", etl_path, "-a", "dpcisr", "-o", txt_path], 60)
            driver_report_available = dr.returncode == 0 and os.path.isfile(txt_path)
            if driver_report_available:
                drivers = _parse_dpc_report(txt_path)
        trace_ts = float(trace_end if trace_end is not None else time.time())
        for event in events:
            if event.get("module_name"):
                attribution = "driver module explicitly present in decoded ETW event data"
            elif event.get("process_name"):
                attribution = "process image from ETW ProcessStart or PID-identity-guarded live inventory"
            elif event.get("pid"):
                attribution = "ETW event PID present; process image unresolved"
            else:
                attribution = "unresolved; event contains no PID or driver module"
            db(
                "INSERT INTO etw_attribution(ts,trace_path,provider,event_name,pid,tid,process_name,module_name,duration_us,attribution,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (event.get("ts") or trace_ts, etl_path, event["provider"], event["event_name"], event["pid"], event["tid"],
                 event["process_name"], event["module_name"], event["duration_us"], attribution,
                 json.dumps(event["fields"], sort_keys=True)),
            )
        for driver in drivers:
            db(
                "INSERT INTO etw_attribution(ts,trace_path,provider,event_name,module_name,attribution,evidence_json) VALUES(?,?,?,?,?,?,?)",
                (trace_ts, etl_path, "NT Kernel Logger", "DPC/ISR summary", driver["module"],
                 driver["attribution"], json.dumps(driver, sort_keys=True)),
            )
        return {
            "decoded": True,
            "event_count": len(events),
            "process_start_count": parsed["process_start_count"],
            "process_attribution_count": parsed["process_attribution_count"],
            "unattributed_event_count": parsed["unattributed_event_count"],
            "driver_report_available": driver_report_available,
            "named_driver_modules": drivers[:20],
            "event_samples": [{
                "ts": event.get("ts"), "provider": event["provider"], "event": event["event_name"], "pid": event["pid"],
                "process": event["process_name"], "module": event["module_name"],
                "duration_us": event["duration_us"],
            } for event in events[:100]],
            "attribution_boundary": (
                "Process images are resolved from process-start events or a current PID record whose creation "
                "time is not later than the trace end. Driver modules are named only when decoded event fields "
                "or xperf's DPC/ISR summary explicitly contain a .sys image. PID reuse and missing symbols remain unresolved."
            ),
        }
    finally:
        for output in (xml_path, txt_path):
            try:
                os.remove(output)
            except OSError:
                pass



def capture_kernel_window(duration: int = 12) -> dict:
    """Serialize SENTINEL-owned kernel captures so simultaneous requests cannot race logger ownership."""
    if not _ETW_CAPTURE_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "another SENTINEL ETW capture is already in progress"}
    try:
        return _capture_kernel_window_locked(duration)
    finally:
        _ETW_CAPTURE_LOCK.release()


def _capture_kernel_window_locked(duration: int = 12) -> dict:
    """Capture one bounded NT Kernel Logger window using xperf (WPT); no session takeover."""
    global _ETW_OWNED
    if not IS_WIN: return {"ok": False, "error": "Windows only"}
    xperf = locate_xperf()
    if not xperf: return {"ok": False, "error": "Windows Performance Toolkit xperf.exe is not installed"}
    duration = max(5, min(20, int(duration)))
    status = _run([xperf, "-loggers"], 10)
    if status.returncode != 0:
        return {"ok": False, "error": "could not inspect ETW logger ownership; refusing to start a kernel session"}
    loggers = (status.stdout or "") + (status.stderr or "")
    if "NT Kernel Logger" in loggers or STATE.get("kernel", {}).get("etw", {}).get("recording"):
        return {"ok": False, "error": "a kernel/WPR ETW session is already active; SENTINEL will not stop or replace it"}
    trace_id = _dt.datetime.now().strftime("sentinel_kernel_%Y%m%d_%H%M%S_%f")
    etl_path = os.path.join(core.TRACE_DIR, trace_id + ".etl")
    flags = "PROC_THREAD+LOADER+PROFILE+DISK_IO+DISK_IO_INIT+FILE_IO+FILE_IO_INIT+HARD_FAULTS+INTERRUPT+DPC+CSWITCH+NETWORKTRACE"
    # Reset the completion signal before starting the owned logger. Shutdown may
    # race with this worker as soon as ownership is published below; it must see
    # an unset event and wait for xperf -d to finish writing the ETL.
    _ETW_DONE.clear()
    try:
        start = _run([xperf, "-on", flags, "-stackwalk", "CSwitch+ReadyThread+DPC+ISR", "-BufferSize", "1024",
                      "-MaxBuffers", "256", "-MaxFile", "256", "-FileMode", "Circular"], 20)
    except Exception:
        _ETW_DONE.set()
        raise
    if start.returncode != 0:
        _ETW_DONE.set()
        return {"ok": False, "error": ((start.stderr or start.stdout or "xperf start failed")[:260])}
    _ETW_OWNED = True
    state = STATE.setdefault("kernel", {}).setdefault("etw_engine", {})
    state.update({"available": True, "recording": True, "state": "recording", "started_at": time.time(),
                  "source": "Windows Performance Toolkit xperf / NT Kernel Logger", "providers": flags.split("+"),
                  "window_seconds": duration, "error": ""})
    heartbeat("advanced ETW kernel observer", duration, "NT Kernel Logger capture active")
    # Shutdown shortens the wait, but the capture owner must always close its
    # own logger and release the completion event. A failed -d gets one bounded
    # owner-only stop attempt; we never stop a logger we did not start.
    try:
        _STOP.wait(duration)
        stop = _run([xperf, "-d", etl_path], 120)
    except Exception as exc:
        cleanup_error = ""
        try:
            cleanup = _run([xperf, "-stop"], 30)
            if cleanup.returncode != 0:
                cleanup_error = (cleanup.stderr or cleanup.stdout or "xperf -stop failed")[:180]
        except Exception as cleanup_exc:
            cleanup_error = f"{type(cleanup_exc).__name__}: {str(cleanup_exc)[:140]}"
        state.update({"recording": None, "state": "unknown", "stopped_at": time.time(),
                      "error": f"{type(exc).__name__}: {str(exc)[:180]}" + (f"; cleanup: {cleanup_error}" if cleanup_error else "")})
        raise
    finally:
        _ETW_OWNED = False
        _ETW_DONE.set()
    state.update({"recording": False, "state": "idle" if stop.returncode == 0 else "unknown", "stopped_at": time.time(),
                  "error": "" if stop.returncode == 0 else (stop.stderr or stop.stdout or "xperf stop failed")[:240]})
    if stop.returncode != 0 or not os.path.isfile(etl_path):
        return {"ok": False, "error": state["error"] or "ETW trace output was not created"}
    decoded = _decode_etl(etl_path, trace_id, time.time())
    size = os.path.getsize(etl_path)
    db("INSERT OR IGNORE INTO trace_archive(ts,file_path,size_bytes,source,status) VALUES(?,?,?,?,?)",
       (time.time(), etl_path, size, "ETW/xperf NT Kernel Logger", "captured"))
    STATE.setdefault("traces", []).append({"file": etl_path, "ts": time.time(), "mb": round(size/1048576, 1),
                                             "source": "ETW/xperf NT Kernel Logger", "exists": True})
    log("ETW", f"Captured {duration}s kernel ETW window; {decoded.get('event_count', 0)} decoded events; {len(decoded.get('named_driver_modules', []))} named driver module(s)", "ok")
    state.update({"last_trace": etl_path, "last_decode": decoded, "last_at": time.time(), "last_event_count": decoded.get("event_count", 0),
                  "driver_modules": decoded.get("named_driver_modules", [])})
    return {"ok": True, "path": etl_path, "bytes": size, "decoded": decoded}


def _capture_thread() -> None:
    try:
        capture_kernel_window(12)
    except Exception as exc:
        STATE.setdefault("kernel", {}).setdefault("etw_engine", {}).update({"state": "error", "recording": None,
            "error": f"{type(exc).__name__}: {str(exc)[:180]}", "checked_at": time.time()})
        heartbeat("advanced ETW kernel observer", 0, err=STATE["kernel"]["etw_engine"]["error"])


def _etw_schedule(ts: float) -> None:
    global _LAST_ETW
    config = CFG.get("advanced", {}) if isinstance(CFG.get("advanced"), dict) else {}
    enabled = config.get("etw_enabled") is True
    game = STATE.get("game")
    state = STATE.setdefault("kernel", {}).setdefault("etw_engine", {})
    state.setdefault("available", bool(locate_xperf()) if IS_WIN else False)
    state.setdefault("state", "idle" if IS_WIN else "unavailable")
    state["enabled"] = enabled
    if not enabled:
        heartbeat("advanced ETW kernel observer", 0, "disabled by operator")
        return
    if not CFG.get("autopilot", {}).get("etw_capture"):
        heartbeat("advanced ETW kernel observer", 0, "enabled; waiting for explicit automatic-capture opt-in")
        return
    if not IS_WIN:
        state.update(state="unavailable", error="Windows only"); return
    if not game:
        heartbeat("advanced ETW kernel observer", 0, "armed; waiting for configured game process")
        return
    if ts - _LAST_ETW < 120: return
    _LAST_ETW = ts
    # Diagnostics are represented in the action queue/journal like every other
    # operation. Autopilot runs this safe capture only after explicit opt-in.
    from . import actions
    aid = actions.propose("etw_capture", {"duration": 12}, origin="etw-engine",
                          reason="Opted-in bounded ETW sample during an active game")
    if not aid:
        heartbeat("advanced ETW kernel observer", 120, "capture proposal refused by policy")


def _check_network_evidence() -> dict:
    ping = core.window("ping", 60)
    jitter = core.window("jitter", 60)
    if len(ping) < 8 or len(jitter) < 8:
        return {"supported": False, "reason": "insufficient ping/jitter samples"}
    import statistics
    pm, jm = statistics.mean(ping), statistics.mean(jitter)
    candidate = pm >= 80 or jm >= 20
    return {"supported": True, "ping_mean_ms": round(pm, 2), "jitter_mean_ms": round(jm, 2),
            "candidate": candidate, "reason": "persistent latency/jitter elevation" if candidate else "no persistent latency/jitter elevation",
            "causality": "network tuning remains manual and requires an explicit user-approved Wi-Fi power-policy change"}


def _advance_game_session(ts: float) -> None:
    global _LAST_GAME_ID
    game = STATE.get("game")
    identity = None
    if isinstance(game, dict): identity = f"{game.get('name')}:{game.get('pid')}:{game.get('create_time')}"
    if identity and identity != _LAST_GAME_ID:
        # End previous session before opening a new one (e.g. two games in sequence).
        if _LAST_GAME_ID:
            rows = db("SELECT id FROM game_sessions WHERE status='active' ORDER BY id DESC LIMIT 1")
            if rows: _end_game_session(int(rows[0][0]), ts)
        sid = _start_game_session(game, ts)
        STATE.setdefault("advanced", {})["active_session_id"] = sid
        profile = get_game_profile(str(game.get("name") or ""))
        if profile:
            try:
                from . import actions
                aid = actions.propose("game_profile_apply", {"pid": game["pid"], "create_time": game["create_time"], "exe": game["exe"], "profile": profile},
                                      origin="game-profile", reason="A saved per-game profile is available; approval is required")
                if aid:
                    db("UPDATE game_sessions SET profile_action_id=? WHERE id=?", (aid, sid))
            except Exception as exc:
                log("game", f"Per-game profile proposal failed: {type(exc).__name__}: {str(exc)[:100]}", "warn")
        _LAST_GAME_ID = identity
    elif not identity and _LAST_GAME_ID:
        rows = db("SELECT id FROM game_sessions WHERE status='active' ORDER BY id DESC LIMIT 1")
        if rows: _end_game_session(int(rows[0][0]), ts)
        STATE.setdefault("advanced", {}).pop("active_session_id", None)
        _LAST_GAME_ID = None


def _engine_loop() -> None:
    while not _STOP.is_set():
        ts = time.time()
        try:
            _advance_game_session(ts)
            _retry_pending_session_restores(ts)
            _sample_active_game(ts)
            _evaluate_tuner(ts)
            _etw_schedule(ts)
            STATE.setdefault("advanced", {})["network_evidence"] = _check_network_evidence()
            STATE["advanced"]["cpu_topology"] = STATE["advanced"].get("cpu_topology") or _cpu_set_inventory()
            heartbeat("advanced intelligence", 5, "baselines, correlation and game-session accounting")
        except Exception as exc:
            heartbeat("advanced intelligence", 5, err=f"{type(exc).__name__}: {str(exc)[:150]}")
        _STOP.wait(5)


def link_action_to_session(action_id: int, session_id: int | None = None) -> bool:
    """Tie temporary performance actions to the active game session for auto-restore."""
    if session_id is None:
        session_id = STATE.get("advanced", {}).get("active_session_id")
    if not session_id:
        return False
    rows = db("SELECT id,status FROM game_sessions WHERE id=?", (int(session_id),))
    if not rows or rows[0][1] != "active":
        return False
    db("INSERT OR IGNORE INTO session_actions(session_id,action_id,created_at) VALUES(?,?,?)",
       (int(session_id), int(action_id), time.time()))
    return True


def get_game_profile(game_name: str) -> dict | None:
    key = str(game_name or "").casefold().strip()
    if not key: return None
    rows = db("SELECT profile_json FROM game_profiles WHERE game_key=?", (key,))
    if not rows: return None
    try: return json.loads(rows[0][0])
    except Exception: return None


def save_game_profile(game_name: str, profile: dict) -> dict:
    key = str(game_name or "").casefold().strip()
    if not key or len(key) > 180 or not isinstance(profile, dict): raise ValueError("game name and profile object required")
    priority = str(profile.get("priority", "above_normal"))
    if priority not in ("normal", "below_normal", "above_normal"): raise ValueError("priority must be normal, below_normal or above_normal")
    affinity = profile.get("affinity")
    if affinity is not None:
        if not isinstance(affinity, list) or not affinity or len(affinity) > (psutil.cpu_count() or 1): raise ValueError("affinity must be a non-empty CPU index list")
        affinity = sorted(set(int(x) for x in affinity))
        if min(affinity) < 0 or max(affinity) >= (psutil.cpu_count() or 1): raise ValueError("affinity CPU index out of range")
    cpu_set_policy = str(profile.get("cpu_set_policy", "unchanged"))
    if cpu_set_policy not in ("unchanged", "efficiency", "performance"): raise ValueError("invalid CPU Set policy")
    timer_ms = int(profile.get("timer_resolution_ms", 0) or 0)
    if timer_ms not in (0, 1, 2): raise ValueError("timer resolution must be 0, 1 or 2 ms")
    background = profile.get("background_efficiency_allowlist", [])
    if not isinstance(background, list) or len(background) > 30 or any(not isinstance(x, str) or len(x) > 100 for x in background):
        raise ValueError("background efficiency allowlist must be a list of at most 30 executable names")
    plan_guid = str(profile.get("power_plan_guid") or "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", plan_guid): raise ValueError("invalid power plan GUID")
    clean = {"priority": priority, "affinity": affinity, "cpu_set_policy": cpu_set_policy,
             "apply_power_plan": profile.get("apply_power_plan") is True,
             "power_plan_guid": plan_guid,
             "timer_resolution_ms": timer_ms,
             "background_efficiency_allowlist": [str(x).casefold() for x in background]}
    db("""CREATE TABLE IF NOT EXISTS game_profiles(game_key TEXT PRIMARY KEY,display_name TEXT NOT NULL,profile_json TEXT NOT NULL,updated_at REAL NOT NULL)""")
    db("INSERT INTO game_profiles(game_key,display_name,profile_json,updated_at) VALUES(?,?,?,?) ON CONFLICT(game_key) DO UPDATE SET display_name=excluded.display_name,profile_json=excluded.profile_json,updated_at=excluded.updated_at",
       (key, game_name[:180], json.dumps(clean, sort_keys=True), time.time()))
    log("profile", f"Saved reversible game profile for {game_name}", "ok", game=key)
    return {"game": game_name, "profile": clean}


def status() -> dict:
    game = STATE.get("game") if isinstance(STATE.get("game"), dict) else None
    hour = _dt.datetime.now().hour
    key = str(game.get("name") or "").casefold() if game else ""
    baseline = _baseline_for(key, hour) if key else {}
    rows = db("SELECT id,game_key,started_at,ended_at,status FROM game_sessions ORDER BY id DESC LIMIT 15")
    recent_sessions = [{"id": r[0], "game": r[1], "started_at": r[2], "ended_at": r[3], "status": r[4]} for r in rows]
    reports = db("SELECT id,game_key,started_at,ended_at,report_json FROM game_sessions WHERE report_json IS NOT NULL ORDER BY id DESC LIMIT 10")
    session_reports = []
    for r in reports:
        try: data = json.loads(r[4])
        except Exception: data = {}
        session_reports.append({"id": r[0], "game": r[1], "started_at": r[2], "ended_at": r[3], "report": data})
    thermal = db("SELECT ts,sensor,event,value,threshold,detail FROM thermal_events ORDER BY id DESC LIMIT 30")
    etw = db("SELECT ts,provider,event_name,pid,tid,process_name,module_name,attribution,evidence_json FROM etw_attribution ORDER BY id DESC LIMIT 60")
    etw_rows = []
    for r in etw:
        try: evidence = json.loads(r[8] or "{}")
        except Exception: evidence = {}
        etw_rows.append({"ts": r[0], "provider": r[1], "event": r[2], "pid": r[3], "tid": r[4], "process": r[5], "module": r[6], "attribution": r[7], "evidence": evidence})
    profiles = db("SELECT display_name,updated_at FROM game_profiles ORDER BY display_name")
    baseline_events = db("SELECT ts,level,msg,data FROM events WHERE src='baseline' ORDER BY id DESC LIMIT 20")
    correlation_events = []
    for r in baseline_events:
        try: payload = json.loads(r[3] or "{}")
        except Exception: payload = {}
        correlation_events.append({"ts": r[0], "level": r[1], "event": r[2], "evidence": payload})
    journal = list_journal(30)
    experiments = db("SELECT id,action_id,metric,before_value,after_value,delta_pct,outcome,detail,started_at,measured_at FROM tuner_experiments ORDER BY id DESC LIMIT 20")
    tuner_history = [{"id": r[0], "action_id": r[1], "metric": r[2], "before": r[3], "after": r[4], "delta_pct": r[5], "outcome": r[6], "detail": r[7], "started_at": r[8], "measured_at": r[9]} for r in experiments]
    adv = STATE.get("advanced", {})
    return {"risk_tiers": RISK_TIERS, "settings": dict(CFG.get("advanced", {})), "game": game, "game_key": key, "baseline_hour": hour, "baseline": baseline,
            "network_evidence": adv.get("network_evidence", _check_network_evidence()),
            "cpu_topology": adv.get("cpu_topology", _cpu_set_inventory()),
            "etw_engine": STATE.get("kernel", {}).get("etw_engine", {}),
            "hardware_sensors": STATE.get("hardware_sensors", {"available": False, "reason": "not sampled"}),
            "gpu": STATE.get("gpu", {}), "thermal_events": [{"ts": r[0], "sensor": r[1], "event": r[2], "value": r[3], "threshold": r[4], "detail": r[5]} for r in thermal],
            "etw_events": etw_rows, "sessions": recent_sessions, "session_reports": session_reports,
            "correlation_events": correlation_events,
            "game_profiles": [{"game": r[0], "updated_at": r[1]} for r in profiles],
            "action_journal": journal, "tuner_history": tuner_history, "specialists": list(SPECIALISTS)}


def settings_update(payload: dict) -> dict:
    if not isinstance(payload, dict): raise ValueError("settings must be an object")
    current = CFG.get("advanced") if isinstance(CFG.get("advanced"), dict) else {}
    allowed = {"etw_enabled", "lhm_enabled", "cpu_temp_warn_c", "gpu_temp_warn_c", "auto_report_sessions"}
    for key, value in payload.items():
        if key not in allowed: raise ValueError(f"unknown advanced setting: {key}")
        if key in ("etw_enabled", "lhm_enabled", "auto_report_sessions") and not isinstance(value, bool): raise ValueError(f"{key} must be boolean")
        if key in ("cpu_temp_warn_c", "gpu_temp_warn_c"):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 50 <= float(value) <= 110: raise ValueError(f"{key} must be between 50 and 110 °C")
            value = float(value)
        current[key] = value
    CFG["advanced"] = current
    core.save_cfg(CFG)
    return {"saved": True, "settings": dict(current), "revision": core.config_revision()}


def _recover_interrupted_sessions() -> None:
    """Resume a live session, but retry any teardown that was already requested."""
    global _LAST_GAME_ID, _LAST_SESSION_RESTORE_RETRY
    rows = db("SELECT id,game_key,pid,create_time,started_at,status FROM game_sessions WHERE status IN ('active','restore_pending') ORDER BY id")
    recovered = 0
    resumed_session_id = None
    for row in rows:
        session_id, game_key, pid, create_time, started_at, status = row
        # restore_pending means session teardown already began (including clean
        # shutdown); never silently resume it and leave its temporary tuning active.
        if status == "restore_pending":
            try:
                _end_game_session(int(session_id), time.time())
                recovered += 1
            except Exception as exc:
                log("rollback", f"Pending session #{session_id} recovery failed: {type(exc).__name__}: {str(exc)[:160]}", "error")
            continue
        if pid and create_time:
            try:
                proc = psutil.Process(int(pid))
                actual_create = float(proc.create_time())
                if abs(actual_create - float(create_time)) <= 0.02:
                    if resumed_session_id is not None:
                        # Do not restore an additional active session while another
                        # exact live game identity has already been resumed.
                        log("rollback", f"Multiple active session records detected; leaving session #{session_id} untouched for review",
                            "warn", session_id=int(session_id))
                        continue
                    name = proc.name()
                    exe = proc.exe()
                    STATE["game"] = {"name": name, "pid": int(pid), "create_time": actual_create,
                                     "since": float(started_at), "exe": exe}
                    resumed_session_id = int(session_id)
                    STATE.setdefault("advanced", {})["active_session_id"] = resumed_session_id
                    _LAST_GAME_ID = f"{name}:{int(pid)}:{actual_create}"
                    log("session", f"Resumed game session #{session_id} after Sentinel restart", "ok", game=game_key)
                    continue
            except psutil.AccessDenied:
                log("rollback", f"Could not verify PID {pid} for interrupted session #{session_id}; leaving actions untouched", "warn")
                continue
            except psutil.NoSuchProcess:
                pass
            except Exception as exc:
                log("rollback", f"Could not verify interrupted session #{session_id}: {type(exc).__name__}", "warn")
                continue
        try:
            report = _end_game_session(int(session_id), time.time())
            if report.get("duration_seconds") is not None:
                recovered += 1
        except Exception as exc:
            log("rollback", f"Interrupted game session #{session_id} recovery failed: {type(exc).__name__}: {str(exc)[:160]}", "error")
    if resumed_session_id is None:
        STATE.setdefault("advanced", {}).pop("active_session_id", None)
        _LAST_GAME_ID = None
    _LAST_SESSION_RESTORE_RETRY = 0.0
    if recovered:
        log("rollback", f"Recovered or retried {recovered} interrupted game-session teardown(s)", "warn")


def start() -> None:
    global _STARTED
    if _STARTED: return
    _STARTED = True
    _STOP.clear()
    STATE.setdefault("advanced", {})
    STATE.setdefault("hardware_sensors", {"available": False, "reason": "not sampled"})
    _recover_interrupted_sessions()
    threading.Thread(target=_engine_loop, name="sentinel-advanced-engine", daemon=True).start()
    threading.Thread(target=_hardware_loop, name="sentinel-hardware-sensors", daemon=True).start()
    log("advanced", "Reversible-action journal, baselines, session reports and optional diagnostics initialized", "ok")


def shutdown() -> None:
    """Stop workers and restore game-session changes while the process is alive."""
    global _STARTED, _ETW_OWNED, _LAST_GAME_ID
    _STOP.set()
    if _ETW_OWNED:
        # Let the capture owner close and archive its ETL with xperf -d.
        # The capture worker is awakened by _STOP and owns the xperf -d
        # finalization. Give that bounded finalizer time to complete before using
        # the emergency stop path, avoiding a concurrent -d / -stop race.
        if not _ETW_DONE.wait(130):
            xperf = locate_xperf()
            if xperf:
                try: _run([xperf, "-stop"], 30)
                except Exception: pass
            _ETW_OWNED = False
            _ETW_DONE.set()
    active_session_id = STATE.get("advanced", {}).get("active_session_id")
    if active_session_id:
        try:
            _end_game_session(int(active_session_id), time.time())
        except Exception as exc:
            log("rollback", f"Shutdown game-session restore failed: {type(exc).__name__}: {str(exc)[:160]}", "error")
        STATE.setdefault("advanced", {}).pop("active_session_id", None)
        STATE["game"] = None
        _LAST_GAME_ID = None
    # A process exit releases Windows multimedia timer requests automatically;
    # a paired timeEndPeriod is still attempted while the process is alive.
    timer = STATE.get("advanced", {}).get("active_timer_ms")
    if timer:
        try: _timer_request(int(timer), begin=False)
        except Exception: pass
        STATE.get("advanced", {}).pop("active_timer_ms", None)
    _STARTED = False
