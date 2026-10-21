"""SENTINEL safety boundary.

All state-changing actions and system trace captures must pass through this module.
It deliberately uses process metadata only: no game-memory access, injection, drivers,
or interaction with Vanguard internals.
"""
from __future__ import annotations

import ctypes
import os
import time
from typing import Any

import psutil

from . import core

POLICY_VERSION = 1
VALORANT_NAMES = frozenset({
    "valorant-win64-shipping.exe",
    "valorant.exe",
})
RIOT_NAMES = frozenset({
    "riotclientservices.exe",
    "riotclientux.exe",
    "riotclientcrashhandler.exe",
    "vgtray.exe",
    "vgc.exe",
})
VANGUARD_SERVICES = frozenset({"vgc", "vgk"})
PROTECTED_NAMES = frozenset({
    *VALORANT_NAMES, *RIOT_NAMES, "system", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "services.exe", "lsass.exe", "winlogon.exe", "svchost.exe",
    "dwm.exe", "fontdrvhost.exe", "securityhealthservice.exe", "msmpeng.exe",
    "nissrv.exe", "trustedinstaller.exe",
})
TRACE_ACTIONS = frozenset({"wpr_trace", "etw_capture"})
PROCESS_ACTIONS = frozenset({
    "bg_priority", "trim_bg", "terminate_process", "game_profile_apply",
    "timer_resolution",
})
MUTATING_ACTIONS = frozenset({
    "bg_priority", "trim_bg", "terminate_process", "game_profile_apply",
    "timer_resolution", "power_plan", "wifi_max_performance",
    "pause_updater_service", "flush_dns", "wpr_trace", "etw_capture",
})

_probe_cache: dict[str, Any] = {"at": 0.0, "valorant": False, "complete": False, "error": ""}


def is_protected_process(name: str | None = None, exe: str | None = None) -> bool:
    """Match exact process basenames; do not use broad substring matching."""
    name_key = os.path.basename(str(name or "")).casefold()
    exe_key = os.path.basename(str(exe or "")).casefold()
    return name_key in PROTECTED_NAMES or exe_key in PROTECTED_NAMES


def _admin_status() -> bool:
    if not core.IS_WIN:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _read_process_state(*, force_probe: bool = False) -> tuple[bool, bool, float, str]:
    """Return (Valorant active, scan complete, scan age, source).

    A fresh collector snapshot is preferred. A short metadata-only psutil probe is used
    when the collector is stale, because capture and mutation decisions must not depend
    on an old game-presence observation.
    """
    now = time.time()
    scanned_at = float(core.STATE.get("proc_scan_at") or 0.0)
    age = max(0.0, now - scanned_at) if scanned_at else float("inf")
    if core.off("processes"):
        return False, False, age, "process_monitor_disabled"

    rows = core.STATE.get("procs") or []
    if not force_probe and scanned_at and age <= 4.0:
        active = any(
            str(row.get("name") or "").casefold() in VALORANT_NAMES
            or os.path.basename(str(row.get("exe") or "")).casefold() in VALORANT_NAMES
            for row in rows if isinstance(row, dict)
        )
        return active, True, age, "collector_snapshot"

    if not force_probe and now - float(_probe_cache.get("at") or 0.0) <= 1.5:
        return bool(_probe_cache["valorant"]), bool(_probe_cache["complete"]), age, "live_process_probe_cache"

    active = False
    complete = True
    error = ""
    try:
        for proc in psutil.process_iter(attrs=["name", "exe"]):
            try:
                info = proc.info
                name = os.path.basename(str(info.get("name") or "")).casefold()
                exe = os.path.basename(str(info.get("exe") or "")).casefold()
                if name in VALORANT_NAMES or exe in VALORANT_NAMES:
                    active = True
                    break
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except (psutil.AccessDenied, OSError):
                # Metadata denial is expected for protected processes. The game image
                # name is normally readable; do not treat a single denial as failure.
                continue
    except Exception as exc:
        complete = False
        error = f"{type(exc).__name__}: {str(exc)[:120]}"
    _probe_cache.update(at=now, valorant=active, complete=complete, error=error)
    return active, complete, age, "live_process_probe"


def snapshot(*, force_process_probe: bool = False) -> dict[str, Any]:
    """Expose the effective safety posture and the evidence used to choose it."""
    active, complete, age, source = _read_process_state(force_probe=force_process_probe)
    vanguard = core.STATE.get("services", {}).get("vanguard", {})
    vgc = str(vanguard.get("vgc") or "unknown").casefold()
    vgk = str(vanguard.get("vgk") or "unknown").casefold()
    if active:
        mode = "valorant_read_only"
    elif not complete:
        mode = "fail_closed_unknown"
    else:
        mode = "normal_guarded"
    return {
        "policy_version": POLICY_VERSION,
        "mode": mode,
        "valorant_active": active,
        "process_detection_complete": complete,
        "process_scan_age_s": None if age == float("inf") else round(age, 2),
        "detection_source": source,
        "vanguard_services": {"vgc": vgc, "vgk": vgk},
        "vanguard_observation": "service metadata only; SENTINEL never queries driver internals",
        "kernel_driver_installed_by_sentinel": False,
        "game_memory_access": False,
        "injection": False,
        "system_mutations_allowed": bool(complete and not active),
        "kernel_trace_allowed": bool(core.IS_WIN and complete and not active and _admin_status()),
        "administrator": _admin_status(),
        "protected_processes": sorted(PROTECTED_NAMES),
        "policy_note": "VALORANT sessions are telemetry-only. No process tuning, system tuning, service control, WPR or ETW capture is allowed.",
    }


def check_action(kind: str, args: dict | None = None) -> dict[str, Any]:
    """Fail-closed policy check called at proposal and execution time."""
    args = args if isinstance(args, dict) else {}
    current = snapshot()
    target_name = str(args.get("name") or args.get("process_name") or "")
    target_exe = str(args.get("exe") or args.get("path") or "")
    if is_protected_process(target_name, target_exe):
        return {"allowed": False, "code": "protected_target", "reason": "Target is a protected Riot/Vanguard or Windows process; SENTINEL will not modify it."}

    if kind == "game_profile_apply":
        profile_game = str(args.get("game") or args.get("game_name") or "").casefold()
        active_game = str((core.STATE.get("game") or {}).get("name") or "").casefold()
        target = os.path.basename(target_exe).casefold()
        if (profile_game in VALORANT_NAMES or active_game in VALORANT_NAMES
                or target in VALORANT_NAMES):
            return {"allowed": False, "code": "valorant_profile_forbidden", "reason": "VALORANT process profiles are permanently disabled in SENTINEL. No CPU Set, priority, timer, or power changes will be applied to the game."}

    if kind in MUTATING_ACTIONS and not current["process_detection_complete"]:
        return {"allowed": False, "code": "process_state_unknown", "reason": "The process observer is disabled, stale or incomplete. SENTINEL cannot safely establish that VALORANT is absent, so all system/process mutations and trace capture are blocked."}
    if kind in MUTATING_ACTIONS and current["valorant_active"]:
        return {"allowed": False, "code": "valorant_read_only", "reason": "VALORANT is running. SENTINEL has entered strict read-only mode; all system/process mutations and WPR/ETW captures are blocked."}

    if kind in TRACE_ACTIONS:
        if not core.IS_WIN:
            return {"allowed": False, "code": "windows_only", "reason": "WPR tracing is available only on Windows."}
        if not current["process_detection_complete"]:
            return {"allowed": False, "code": "game_state_unknown", "reason": "Could not reliably confirm game presence. Trace capture is blocked until process monitoring is healthy."}
        if not current["administrator"]:
            return {"allowed": False, "code": "elevation_required", "reason": "WPR system trace requires an elevated administrator or Performance Log Users context."}

    if kind in PROCESS_ACTIONS and not current["process_detection_complete"]:
        return {"allowed": False, "code": "process_state_unknown", "reason": "Process inventory is stale or incomplete. Refresh process identities before attempting a process change."}

    if kind == "pause_updater_service":
        service = str(args.get("service") or "").casefold()
        if service in VANGUARD_SERVICES or service.startswith("vg"):
            return {"allowed": False, "code": "vanguard_service_protected", "reason": "Vanguard services are permanently excluded from SENTINEL service controls."}

    return {"allowed": True, "code": "allowed", "reason": "Policy checks passed; the action's risk tier and approval requirements still apply."}


def trace_preflight() -> dict[str, Any]:
    """Dedicated WPR preflight; no session is started or stopped here."""
    result = check_action("etw_capture")
    if not result["allowed"]:
        return result
    return {"allowed": True, "code": "ready", "reason": "No VALORANT process detected, process monitor is healthy, and administrator rights are present."}
