"""Allowlisted, reversible actions. Nothing here kills processes or deletes anything.
Every action is proposed -> (auto-run if autopilot enables that kind, else waits for UI approval) -> logged."""
import json, os, subprocess, threading, time
import psutil
from pathlib import Path
from . import core
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
    "undo_power_plan": "Restore the previous power plan",
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
    return [p for p in STATE.get("procs", []) if p.get("bg")]


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
            return "skipped (not Windows)"
        cur = _run(["powercfg", "/getactivescheme"])
        _prev_plan[0] = next((w for w in cur.split() if len(w) == 36 and w.count("-") == 4), None)
        _run(["powercfg", "/setactive", HIGH_PERF])
        return f"High performance active (previous: {_prev_plan[0]})"
    if kind == "terminate_process":
        return _terminate_reviewed_process(args)
    if kind == "undo_power_plan":
        if _prev_plan[0]:
            _run(["powercfg", "/setactive", _prev_plan[0]])
            return f"restored {_prev_plan[0]}"
        return "nothing to restore"
    if kind == "wpr_trace":
        if time.time() - _last_trace[0] < 900:
            return "skipped (rate limit: one trace per 15 min)"
        if not IS_WIN:
            return "skipped (not Windows)"
        from .winutil import run_command
        etw = STATE.setdefault("kernel", {}).get("etw", {})
        if etw.get("recording"):
            return "skipped (a WPR ETW recording is already active; SENTINEL will not cancel another session)"
        start_result = run_command(["wpr.exe", "-start", "GeneralProfile.Light", "-filemode"], timeout=30)
        start_text = ((start_result.stdout or "") + "\n" + (start_result.stderr or "")).strip()
        if start_result.returncode != 0:
            etw.update(available=True, recording=None, state="unknown", checked_at=time.time(),
                       status_text=start_text[-800:], error=f"WPR start failed (exit {start_result.returncode})")
            return f"WPR start failed (exit {start_result.returncode}): {start_text[-240:]}"
        _last_trace[0] = time.time()
        etw.update(available=True, recording=True, state="recording", checked_at=time.time(),
                   status_text=start_text[-800:], error="")
        log("kernel", "ETW WPR GeneralProfile.Light trace recording started (15 s)", "warn")
        time.sleep(15)
        f = os.path.join(TRACE_DIR, time.strftime("trace_%Y%m%d_%H%M%S.etl"))
        stop_result = run_command(["wpr.exe", "-stop", f], timeout=180)
        stop_text = ((stop_result.stdout or "") + "\n" + (stop_result.stderr or "")).strip()
        if stop_result.returncode == 0:
            etw.update(recording=False, state="idle", checked_at=time.time(), status_text=stop_text[-800:], error="")
        else:
            etw.update(recording=None, state="unknown", checked_at=time.time(), status_text=stop_text[-800:],
                       error=f"WPR stop failed (exit {stop_result.returncode}); trace state requires re-check")
        if stop_result.returncode == 0 and os.path.exists(f):
            trace_ts = time.time()
            trace_bytes = os.path.getsize(f)
            trace_row = {"file": f, "ts": trace_ts, "mb": round(trace_bytes / 1048576, 1), "source": "ETW/WPR GeneralProfile.Light", "exists": True}
            STATE.setdefault("traces", []).append(trace_row)
            db("INSERT OR IGNORE INTO trace_archive(ts,file_path,size_bytes,source,status) VALUES(?,?,?,?,?)",
               (trace_ts, f, trace_bytes, trace_row["source"], "captured"))
            return f"trace saved: {f} (ETL; open in Windows Performance Analyzer)"
        return f"WPR stop failed (exit {stop_result.returncode}): {stop_text[-240:]}"
    return "unknown action"


def propose(kind, args=None, origin="brain", reason=""):
    """Entry point for brain / AI / UI. Enforces allowlist and autopilot policy."""
    if kind not in KINDS:
        log("actions", f"REJECTED non-allowlisted action '{kind}' from {origin}", "warn")
        return None
    args = args or {}
    # Terminating a process is never eligible for unattended execution.
    auto = bool(CFG["autopilot"].get(kind)) and kind not in ("undo_power_plan", "terminate_process") and core.get_profile()["automation"]
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
    with _lock:
        rows = db("SELECT kind,args,state FROM actions WHERE id=?", (aid,))
        if not rows or rows[0][2] not in ("pending",):
            return "not pending"
        kind, args = rows[0][0], json.loads(rows[0][1] or "{}")
        if kind == "terminate_process" and not user_confirmed:
            return "explicit user confirmation required; action remains pending"
        db("UPDATE actions SET state='running' WHERE id=?", (aid,))
    try:
        res = _do(kind, args)
        state = "done"
    except Exception as e:
        res, state = repr(e), "failed"
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
        decoded.append({"id": r[0], "ts": r[1], "kind": r[2], "desc": KINDS.get(r[2], r[2]),
            "state": r[3], "origin": r[4], "result": r[5], "args": args})
    return decoded