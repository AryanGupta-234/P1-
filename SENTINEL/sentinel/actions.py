"""Allowlisted, reversible actions. Nothing here kills processes or deletes anything.
Every action is proposed -> (auto-run if autopilot enables that kind, else waits for UI approval) -> logged."""
import json, os, subprocess, threading, time
import psutil
from pathlib import Path
from . import core, safeguard
from .core import CFG, IS_WIN, STATE, db, log, publish, TRACE_DIR

NO_WIN = 0x08000000 if IS_WIN else 0
HIGH_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
KINDS = {
    "bg_priority": "Lower memory + I/O priority of background apps while gaming (CPU speed untouched)",
    "flush_dns": "Flush the DNS resolver cache",
    "power_plan": "Switch to High performance power plan (previous plan saved for undo)",
    "wpr_trace": "Record a 15 s ETW kernel trace (Windows Performance Recorder) for deep analysis",
    "trim_bg": "Trim working sets of background apps to free RAM for the game",
    "terminate_process": "Request graceful close of a reviewed user app window (no force-kill)",
    "undo_power_plan": "Restore the previous power plan (legacy; use the journal undo)",
    "game_profile_apply": "Apply an approved reversible per-game priority / CPU Set / power / timer profile",
    "timer_resolution": "Request a reversible 1–2 ms multimedia timer period for the game session",
    "wifi_max_performance": "Use evidence-gated Wi-Fi adapter maximum-performance AC policy (reversible)",
    "etw_capture": "Capture a bounded NT Kernel Logger ETW window and decode DPC/ISR/process evidence",
    "pause_updater_service": "Temporarily pause an allowlisted third-party updater (approval required; undo restarts it)",
}
_last_trace = [0.0]
_prev_plan = [None]
_handled = set()
_lock = threading.Lock()

if IS_WIN:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    nt = ctypes.WinDLL("ntdll")
    ps = ctypes.WinDLL("psapi")
    k32.OpenProcess.restype = wintypes.HANDLE

    def _prio(pid, mem, io):
        h = k32.OpenProcess(0x0700, False, pid)
        if not h:
            return False
        try:
            m = ctypes.c_uint32(mem)
            ok = bool(k32.SetProcessInformation(h, 0, ctypes.byref(m), 4))   # ProcessMemoryPriority
            i = ctypes.c_int(io)
            nt.NtSetInformationProcess(h, 33, ctypes.byref(i), 4)              # ProcessIoPriority
            return ok
        finally:
            k32.CloseHandle(h)

    def _trim(pid):
        h = k32.OpenProcess(0x0700, False, pid)
        if not h:
            return False
        try:
            return bool(ps.EmptyWorkingSet(h))
        finally:
            k32.CloseHandle(h)
else:
    def _prio(pid, mem, io): return True
    def _trim(pid): return True


def _bg_targets():
    return [p for p in STATE.get("procs", []) if p.get("bg")
            and not safeguard.is_protected_process(p.get("name"), p.get("exe"))]


def _run(cmd, timeout=30):
    from .winutil import run_command
    r = run_command(cmd, timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


def _terminate_reviewed_process(args):
    """Send WM_CLOSE to a reviewed interactive GUI app; never escalate to TerminateProcess."""
    if not IS_WIN:
        return "skipped (process close requests are Windows-only)"
    try:
        pid = int(args.get("pid"))
        expected_create = float(args.get("create_time"))
        expected_exe = os.path.normcase(os.path.abspath(str(args.get("exe") or "")))
    except (TypeError, ValueError):
        return "rejected (invalid process identity)"
    if pid <= 4 or not expected_exe or not os.path.isabs(expected_exe):
        return "rejected (missing or protected process identity)"
    guard = safeguard.check_action("terminate_process", args)
    if not guard["allowed"]:
        return "rejected by SENTINEL safeguard: " + guard["reason"]
    protected = {"system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe",
        "winlogon.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe", "securityhealthservice.exe",
        "msmpeng.exe", "nissrv.exe", "trustedinstaller.exe", "explorer.exe"}
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            name = (proc.name() or "").casefold()
            current_create = proc.create_time()
            current_exe = os.path.normcase(os.path.abspath(proc.exe() or ""))
        if name in protected:
            return f"rejected (protected Windows process: {name})"
        if abs(current_create - expected_create) > 0.01 or current_exe != expected_exe:
            return "rejected (process identity changed since review; refresh the process list)"
        system_root = os.path.normcase(os.path.abspath(os.environ.get("SystemRoot", r"C:\Windows")))
        try:
            if os.path.commonpath([current_exe, system_root]) == system_root:
                return "rejected (Windows system directory protection)"
        except ValueError:
            return "rejected (invalid executable path)"
        from .collectors import _session_id
        if _session_id(pid) in (None, 0):
            return "rejected (target is not in an interactive user session)"

        # Enumerate only visible top-level windows owned by this exact PID. Do not read
        # titles, text, controls, or window contents. Generic background processes do
        # not have a safe, universal graceful-stop protocol and are left alone.
        from .collectors import _physical_window_handles
        windows = _physical_window_handles(pid)
        if not windows:
            return "not sent (no current non-cloaked window intersects a physical monitor; no force-kill fallback)"
        user32 = ctypes.windll.user32
        # HWND is pointer-sized on Win64; do not allow ctypes to default to c_int.
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL

        sent = 0
        for hwnd in windows[:32]:
            # WM_CLOSE asks the app to shut down through its normal window procedure.
            if user32.PostMessageW(hwnd, 0x0010, 0, 0):
                sent += 1
        if not sent:
            return "close request could not be delivered; process was not terminated"
        try:
            proc.wait(timeout=6)
            return f"application closed after WM_CLOSE (pid {pid}); no force-kill was used"
        except psutil.TimeoutExpired:
            return f"WM_CLOSE sent to {sent} window(s) (pid {pid}); process remains running. No force-kill was attempted."
    except psutil.NoSuchProcess:
        return "rejected (process has already exited)"
    except psutil.AccessDenied:
        return "rejected (access denied; no privilege escalation attempted)"
    except Exception as exc:
        return f"failed safely: {type(exc).__name__}: {str(exc)[:160]}"


def _do(kind, args):
    if kind == "bg_priority":
        n = 0
        for p in _bg_targets():
            if p["pid"] in _handled:
                continue
            lvl = 2 if p["name"].lower() in ("discord.exe", "teams.exe", "ms-teams.exe", "slack.exe", "zoom.exe", "spotify.exe") else 1
            if _prio(p["pid"], lvl, 1 if lvl == 2 else 0):
                n += 1
            _handled.add(p["pid"])
        return f"lowered mem/IO priority on {n} background processes"
    if kind == "trim_bg":
        n = sum(1 for p in _bg_targets() if _trim(p["pid"]))
        return f"trimmed {n} background processes"
    if kind == "flush_dns":
        return _run(["ipconfig", "/flushdns"]).strip()[:120] or "ok"
    if kind == "power_plan":
        if not IS_WIN:
            raise RuntimeError("power plan changes are Windows-only")
        from .winutil import run_command
        result = run_command(["powercfg.exe", "/setactive", HIGH_PERF], timeout=12)
        if result.returncode != 0:
            raise RuntimeError(f"powercfg failed (exit {result.returncode}): {(result.stderr or result.stdout or '')[:180]}")
        return "High performance power plan activated; previous scheme is journaled for undo"
    if kind == "terminate_process":
        return _terminate_reviewed_process(args)
    if kind == "game_profile_apply":
        from . import advanced
        return advanced.apply_game_profile(args)
    if kind == "timer_resolution":
        from . import advanced
        ms = int(args.get("milliseconds", 1))
        advanced._timer_request(ms, begin=True)
        return f"requested {ms} ms multimedia timer period; paired release is journaled"
    if kind == "wifi_max_performance":
        from . import advanced
        return advanced.apply_wifi_max_performance()
    if kind == "pause_updater_service":
        from . import advanced
        service = str(args.get("service") or "").casefold()
        if service not in advanced.UPDATER_SERVICES:
            return "rejected (service is not allowlisted)"
        from .winutil import run_command
        state_before = advanced._service_state(service)
        if state_before != "running":
            return f"not changed (updater service state changed to {state_before or 'unknown'} outside SENTINEL before the request)"
        r = run_command(["sc.exe", "stop", service], timeout=15)
        message = (r.stdout or "") + " " + (r.stderr or "")
        if r.returncode != 0 and "STOP_PENDING" not in message:
            after_error = advanced._service_state(service)
            if after_error != "running":
                return f"not changed (SCM reported a stop error and the service is now {after_error or 'unknown'}; preserving its external state)"
            raise RuntimeError(f"could not stop {service}: {message[:180]}")
        # Do not record a reversible change until SCM confirms the service is stopped.
        deadline = time.monotonic() + 12
        state = None
        while time.monotonic() < deadline:
            state = advanced._service_state(service)
            if state == "stopped":
                return f"paused allowlisted updater {service}; it was running before the game-session action and is linked to automatic restore"
            if state not in ("running", "paused"):
                time.sleep(0.4)
                continue
            if state == "running":
                time.sleep(0.4)
                continue
        raise RuntimeError(f"SCM did not confirm {service} stopped (last state: {state or 'unknown'}); attempted rollback will preserve uncertain state")
    if kind == "etw_capture":
        from . import advanced
        result = advanced.capture_kernel_window(int(args.get("duration", 12)))
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "ETW capture failed"))
        return f"ETW capture saved: {result['path']} ({result['bytes']} bytes; {result['decoded'].get('event_count',0)} decoded events)"
    if kind == "undo_power_plan":
        if _prev_plan[0]:
            _run(["powercfg", "/setactive", _prev_plan[0]])
            return f"restored {_prev_plan[0]}"
        return "nothing to restore"
    if kind in ("wpr_trace", "etw_capture"):
        from . import advanced
        guard = safeguard.check_action(kind, args)
        if not guard["allowed"]:
            raise PermissionError(guard["reason"])
        result = advanced.capture_kernel_window(int(args.get("duration", 12)))
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "WPR capture failed"))
        decoded = result.get("decoded") or {}
        return (f"WPR ETW trace saved: {result['path']} ({result['bytes']} bytes; "
                f"{decoded.get('event_count', 0)} decoded events; "
                f"{len(decoded.get('named_driver_modules', []))} named driver module(s))")
    return "unknown action"


def propose(kind, args=None, origin="brain", reason=""):
    """Entry point for brain / AI / UI. Risk tiers gate every proposal."""
    if kind not in KINDS:
        log("actions", f"REJECTED non-allowlisted action '{kind}' from {origin}", "warn")
        return None
    args = args or {}
    from . import advanced
    try:
        preview = advanced.action_preview(kind, args)
    except Exception as exc:
        log("actions", f"REJECTED {kind}: preview failed ({type(exc).__name__}: {str(exc)[:200]})", "warn")
        return None
    if not preview.get("supported") or preview.get("risk") == "dangerous":
        detail = "; ".join(str(item) for item in (preview.get("warnings") or []) if item)
        log("actions", f"REJECTED {kind}: {detail[:260] or 'risk policy'}", "warn")
        return None
    # Only explicitly opted-in SAFE diagnostic actions may run automatically.
    # Medium risk always needs a fresh approval; dangerous actions never run.
    auto = (preview.get("risk") == "safe" and bool(CFG["autopilot"].get(kind))
            and core.get_profile()["automation"])
    db("INSERT INTO actions(ts,kind,args,state,origin,result) VALUES(?,?,?,?,?,?)",
       (time.time(), kind, json.dumps(args), "pending", origin, reason))
    aid = db("SELECT MAX(id) FROM actions")[0][0]
    row = {"id": aid, "kind": kind, "desc": KINDS[kind], "origin": origin, "reason": reason, "state": "pending"}
    publish("action", row)
    log("actions", f"{origin} proposes: {KINDS[kind]}" + (f" - {reason}" if reason else ""), "info")
    if auto:
        threading.Thread(target=execute, args=(aid,), daemon=True).start()
    return aid


def execute(aid, *, user_confirmed=False):
    from . import advanced
    with _lock:
        rows = db("SELECT kind,args,state FROM actions WHERE id=?", (aid,))
        if not rows or rows[0][2] not in ("pending",):
            return "not pending"
        kind, args = rows[0][0], json.loads(rows[0][1] or "{}")
        tier = advanced.risk_tier(kind)
        guard = safeguard.check_action(kind, args)
        if not guard["allowed"]:
            reason = "blocked by SENTINEL safeguard: " + guard["reason"]
            db("UPDATE actions SET state='blocked',result=? WHERE id=?", (reason[:400], aid))
            log("safeguard", f"{kind} blocked: {guard['reason'][:180]}", "warn")
            return reason
        if tier == "dangerous":
            return "blocked by risk policy: dangerous actions are never automated and this action has no approved reversible implementation"
        if tier == "medium" and not user_confirmed:
            return "explicit user approval required; action remains pending"
        try:
            advanced.prepare_action(int(aid), kind, args)
        except Exception as exc:
            db("UPDATE actions SET state='blocked',result=? WHERE id=?", (f"{type(exc).__name__}: {str(exc)[:250]}", aid))
            log("actions", f"{kind} blocked before execution: {type(exc).__name__}: {str(exc)[:180]}", "warn")
            return f"blocked: {type(exc).__name__}: {str(exc)[:200]}"
        db("UPDATE actions SET state='running' WHERE id=?", (aid,))
    try:
        res = _do(kind, args)
        state = "done"
        # The ETW trace is the only file created by diagnostic capture and can be deleted by Undo.
        changed = not str(res).lower().startswith(("skipped", "nothing", "rejected", "not sent", "not changed"))
        advanced.mark_action_result(int(aid), str(res), changed)
        if changed and kind in {"game_profile_apply", "power_plan", "timer_resolution", "wifi_max_performance", "pause_updater_service"}:
            advanced.link_action_to_session(int(aid))
    except Exception as e:
        res, state = f"{type(e).__name__}: {str(e)[:220]}", "failed"
        # Capture post-failure values for operations that can partially mutate
        # process/power state before raising; undo remains conditional on exact match.
        if kind in {"game_profile_apply", "power_plan"}:
            try: advanced.capture_failed_action_state(int(aid))
            except Exception: pass
        # Best-effort rollback for partial writes; preserves user changes if state diverged.
        rollback = advanced.undo_action(int(aid))
        if rollback.get("ok"):
            res += f" · rollback: {rollback['result']}"
    db("UPDATE actions SET state=?, result=? WHERE id=?", (state, res[:400], aid))
    publish("action", {"id": aid, "kind": kind, "state": state, "result": res})
    log("actions", f"{kind}: {res}", "ok" if state == "done" else "error")
    return res


def dismiss(aid):
    db("UPDATE actions SET state='dismissed' WHERE id=? AND state='pending'", (aid,))
    publish("action", {"id": aid, "state": "dismissed"})


def list_actions(limit=40):
    rows = db("SELECT id,ts,kind,state,origin,result,args FROM actions ORDER BY id DESC LIMIT ?", (limit,))
    decoded = []
    for r in rows:
        try: args = json.loads(r[6] or "{}")
        except Exception: args = {}
        journal = db("SELECT risk,undo_available,changed,reverted_at,revert_result FROM action_journal WHERE action_id=?", (r[0],))
        meta = journal[0] if journal else ("dangerous", 0, 0, None, "")
        decoded.append({"id": r[0], "ts": r[1], "kind": r[2], "desc": KINDS.get(r[2], r[2]),
            "state": r[3], "origin": r[4], "result": r[5], "args": args,
            "risk": meta[0], "undo_available": bool(meta[1]), "changed": bool(meta[2]),
            "reverted_at": meta[3], "revert_result": meta[4]})
    return decoded