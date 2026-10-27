"""Sentinel collectors: everything Windows exposes, sampled continuously.
Sources: psutil (process/CPU/RAM/net/disk), typeperf (PDH perf counters: DPC, interrupts,
paging, disk latency), nvidia-smi, wevtutil (event logs), registry autoruns, service control
manager, ping, powercfg."""
import csv, io, os, re, subprocess, time, random, math, shutil, ctypes, json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import psutil
from . import core
from .core import log, metric, heartbeat, STATE, CFG, IS_WIN, insight, LIVE
from .winutil import resolve_command, run_command

NO_WIN = 0x08000000 if IS_WIN else 0
NCPU = psutil.cpu_count() or 1
WARMUP = 45  # seconds before "new thing appeared" alerts start (learn baseline first)


def run(cmd, timeout=15):
    try:
        r = run_command(cmd, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as exc:
        return f"[SENTINEL_COMMAND_ERROR:{type(exc).__name__}:{str(exc)[:180]}]"


def sleep_to(t0, every):
    d = every - (time.time() - t0)
    if d > 0:
        time.sleep(d)


# ------------------------------------------------------------------ 1s: system + processes
_procs = {}                 # (pid, creation_time) -> psutil.Process; PID reuse is distinct
_proc_pid_identity = {}     # pid -> stable (pid, creation_time)
_proc_cpu_hot = {}          # identity -> consecutive high-resource observations
_proc_warned = set()
_last_process_snapshot = 0.0
_prev = {"disk": None, "net": None, "cpu": None, "t": None, "io": {}}
BG_NAMES = {n.lower() for n in (
    "chrome.exe msedge.exe msedgewebview2.exe firefox.exe brave.exe opera.exe discord.exe steam.exe "
    "steamwebhelper.exe epicgameslauncher.exe onedrive.exe dropbox.exe googledrivefs.exe teams.exe "
    "ms-teams.exe slack.exe zoom.exe spotify.exe whatsapp.exe telegram.exe widgets.exe code.exe "
    "creative cloud.exe ccxprocess.exe adobeipcbroker.exe phoneexperiencehost.exe overwolf.exe "
    "searchindexer.exe msmpeng.exe tiworker.exe trustedinstaller.exe").split()}
NOISE = {"conhost.exe", "backgroundtaskhost.exe", "runtimebroker.exe", "searchprotocolhost.exe",
         "searchfilterhost.exe", "smartscreen.exe", "wmiprvse.exe", "taskhostw.exe", "dllhost.exe"}


def _session_id(pid):
    if not IS_WIN:
        return None
    try:
        value = ctypes.c_uint32()
        if ctypes.windll.kernel32.ProcessIdToSessionId(int(pid), ctypes.byref(value)):
            return int(value.value)
    except Exception:
        pass
    return None


def _window_presence():
    """Map PIDs to visible, non-cloaked windows intersecting real display monitors.

    Window titles and contents are never read. An interactive Session ID by itself is
    not treated as proof that an app is visible on a physical display.
    """
    presence = {}
    if not IS_WIN:
        return presence
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi
        rect_type = wintypes.RECT
        # HWND/HMONITOR are pointer-sized handles. Explicit prototypes prevent
        # ctypes' default c_int conversion from truncating 64-bit window handles.
        monitor_proc_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
            ctypes.POINTER(rect_type), ctypes.c_ssize_t,
        )
        enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, ctypes.c_ssize_t)
        user32.EnumDisplayMonitors.argtypes = [
            wintypes.HDC, ctypes.POINTER(rect_type), monitor_proc_type, ctypes.c_ssize_t,
        ]
        user32.EnumDisplayMonitors.restype = wintypes.BOOL
        user32.EnumWindows.argtypes = [enum_proc_type, ctypes.c_ssize_t]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(rect_type)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        dwmapi.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
        ]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
        monitors = []

        def monitor_callback(_monitor, _dc, rect_ptr, _data):
            try:
                r = rect_ptr.contents
                monitors.append((int(r.left), int(r.top), int(r.right), int(r.bottom)))
            except Exception:
                pass
            return True

        monitor_cb = monitor_proc_type(monitor_callback)
        user32.EnumDisplayMonitors(None, None, monitor_cb, 0)
        if not monitors:
            width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
            if width > 0 and height > 0:
                monitors.append((0, 0, int(width), int(height)))

        foreground = user32.GetForegroundWindow()
        foreground_pid = ctypes.c_ulong()
        if foreground:
            user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))

        def callback(hwnd, _):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if not pid.value:
                    return True
                item = presence.setdefault(int(pid.value), {
                    "visible": 0, "onscreen": 0, "cloaked": 0,
                    "foreground": False, "handles": [],
                })
                item["visible"] += 1
                if int(pid.value) == int(foreground_pid.value):
                    item["foreground"] = True

                cloaked = ctypes.c_uint32(0)
                hr = dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
                if hr != 0:
                    item["cloak_unknown"] = item.get("cloak_unknown", 0) + 1
                    return True
                if cloaked.value:
                    item["cloaked"] += 1
                    return True

                rect = rect_type()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True
                left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
                if right <= left or bottom <= top:
                    return True
                on_monitor = any(right > ml and left < mr and bottom > mt and top < mb
                                 for ml, mt, mr, mb in monitors)
                if on_monitor:
                    item["onscreen"] += 1
                    item["handles"].append(int(hwnd))
            except Exception:
                pass
            return True

        enum_cb = enum_proc_type(callback)
        user32.EnumWindows(enum_cb, 0)
    except Exception:
        return presence
    return presence


def _visible_window_counts():
    """Compatibility helper returning visible top-level window counts by PID."""
    return {pid: item["visible"] for pid, item in _window_presence().items()}


def _physical_window_handles(pid):
    """Recheck a PID's non-cloaked windows intersecting a physical display."""
    item = _window_presence().get(int(pid), {})
    return list(item.get("handles", [])) if item.get("onscreen", 0) else []


def classify_process_presence(session_id, visible, onscreen, cloaked=0):
    """Human-readable evidence classification; never equates a process with a window."""
    if session_id in (None, 0):
        return "session 0 / service or system"
    if onscreen > 0:
        return "visible on physical monitor"
    if cloaked > 0:
        return "interactive session / DWM-cloaked window"
    if visible > 0:
        return "interactive session / visible but off-monitor"
    return "interactive session / no visible window"


def _process_path_state(path):
    if not path:
        return "unavailable"
    try:
        return "present" if os.path.isfile(path) else "file_missing_or_unmounted"
    except OSError:
        return "inaccessible"


def fast_loop():
    psutil.cpu_percent(percpu=True)
    t_start = time.time()
    last_process_scan = 0.0
    while True:
        t0 = time.time()
        now = t0
        per = psutil.cpu_percent(percpu=True)
        metric("cpu", sum(per) / len(per))
        STATE["cores"] = [round(x, 1) for x in per]
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        metric("mem", vm.percent); metric("mem_free_mb", vm.available / 1048576)
        metric("swap", sw.percent)
        dt = (now - _prev["t"]) if _prev["t"] else 0
        d = psutil.disk_io_counters()
        if d and _prev["disk"] and dt:
            metric("diskr", max(0.0, (d.read_bytes - _prev["disk"].read_bytes) / dt / 1048576))
            metric("diskw", max(0.0, (d.write_bytes - _prev["disk"].write_bytes) / dt / 1048576))
        _prev["disk"] = d
        n = psutil.net_io_counters()
        if n and _prev["net"] and dt:
            metric("netdown", max(0.0, (n.bytes_recv - _prev["net"].bytes_recv) * 8 / dt / 1e6))
            metric("netup", max(0.0, (n.bytes_sent - _prev["net"].bytes_sent) * 8 / dt / 1e6))
        _prev["net"] = n
        cs = psutil.cpu_stats()
        if _prev["cpu"] and dt:
            metric("ctx", (cs.ctx_switches - _prev["cpu"].ctx_switches) / dt)
            metric("ints", (cs.interrupts - _prev["cpu"].interrupts) / dt)
        _prev["cpu"] = cs
        _prev["t"] = now
        try:
            from . import runtime_engine
            process_interval = runtime_engine.process_scan_interval()
        except Exception:
            process_interval = 1.0
        if not core.off("processes"):
            if now - last_process_scan >= process_interval:
                scan_processes(now, now - t_start > WARMUP)
                last_process_scan = now
        else:
            STATE["procs"] = []; STATE["proc_total"] = 0; STATE["proc_recommendations"] = []
            STATE.pop("proc_scan_at", None)
            heartbeat("process inventory", 1, "disabled in Feature Control")
        heartbeat("system+processes", 1, f"{STATE.get('proc_total', 0)} processes tracked")
        sleep_to(t0, 1.0)


def dedupe_process_rows(rows):
    """Collapse duplicate enumeration results by process instance, never by name/PID alone."""
    unique = {}
    for row in rows:
        try:
            identity = (int(row["pid"]), float(row["create_time"]))
        except (KeyError, TypeError, ValueError):
            continue
        old = unique.get(identity)
        quality = (int(bool(row.get("exe"))) + int(row.get("name") != "<access denied>")
                   + int(row.get("path_state") == "present"))
        old_quality = (-1 if old is None else
            int(bool(old.get("exe"))) + int(old.get("name") != "<access denied>")
            + int(old.get("path_state") == "present"))
        if old is None or quality > old_quality:
            unique[identity] = row
    return list(unique.values())


def scan_processes(now, learned):
    """Reconcile by (PID, creation time), retain full executable identity and UI session facts."""
    current = {}
    window_presence = _window_presence()
    rows = []
    inaccessible = 0
    for p in psutil.process_iter():
        try:
            with p.oneshot():
                pid = p.pid
                created = p.create_time()
                identity = (int(pid), float(created))
                current[identity] = p
                name = p.name() or "<unknown>"
                exe = ""
                try: exe = p.exe() or ""
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError): pass
                try: parent = p.parent()
                except (psutil.Error, OSError): parent = None
                try: parent_pid = parent.pid if parent else None
                except (psutil.Error, OSError): parent_pid = None
                try: parent_name = parent.name() if parent else "--"
                except (psutil.Error, OSError): parent_name = "--"
                try: username = p.username()
                except (psutil.AccessDenied, psutil.NoSuchProcess, OSError): username = "unavailable"
                try: status = p.status()
                except (psutil.Error, OSError): status = "unknown"
                try: cpu = max(0.0, p.cpu_percent() / NCPU)
                except (psutil.Error, OSError): cpu = 0.0
                try: mi = p.memory_info(); mem = int(mi.rss / 1048576)
                except (psutil.Error, OSError): mem = 0
                try:
                    io = p.io_counters(); total_io = io.read_bytes + io.write_bytes
                except (psutil.Error, OSError, AttributeError): total_io = 0
                last = _prev["io"].get(identity)
                _prev["io"][identity] = (total_io, now)
                iom = ((total_io - last[0]) / max(0.001, now - last[1]) / 1048576) if last else 0.0
                try: threads = p.num_threads()
                except (psutil.Error, OSError): threads = 0
                try: handles = p.num_handles() if IS_WIN else None
                except (psutil.Error, OSError, AttributeError): handles = None
                session = _session_id(pid)
                window_facts = window_presence.get(pid, {})
                windows = int(window_facts.get("visible", 0))
                onscreen_windows = int(window_facts.get("onscreen", 0))
                cloaked_windows = int(window_facts.get("cloaked", 0))
                app_kind = classify_process_presence(session, windows, onscreen_windows, cloaked_windows)
                bg = name.lower() in BG_NAMES
                path_state = _process_path_state(exe)
                row = {
                    "pid": int(pid), "create_time": float(created), "name": name,
                    "exe": exe, "path_state": path_state, "parent_pid": parent_pid,
                    "parent_name": parent_name, "username": username, "status": status,
                    "session_id": session, "visible_windows": windows,
                    "onscreen_windows": onscreen_windows, "cloaked_windows": cloaked_windows,
                    "foreground": bool(window_facts.get("foreground", False)),
                    "window_cloak_unknown": int(window_facts.get("cloak_unknown", 0)),
                    "app_kind": app_kind, "cpu": round(cpu, 2), "mem": mem,
                    "io": round(max(0.0, iom), 3), "thr": int(threads),
                    "handles": handles, "bg": bg,
                }
                rows.append(row)
        except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
            continue
        except (psutil.AccessDenied, PermissionError):
            # Keep a visible placeholder for protected processes rather than silently
            # making the process inventory look complete. Never invent a name/path.
            inaccessible += 1
            try:
                pid = int(p.pid)
                created = float(p.create_time())
                ident = (pid, created)
                current[ident] = p
                facts = window_presence.get(pid, {})
                rows.append({"pid": pid, "create_time": created, "name": "<access denied>",
                    "exe": "", "path_state": "access_denied", "parent_pid": None,
                    "parent_name": "unknown", "username": "access denied", "status": "unknown",
                    "session_id": _session_id(pid), "visible_windows": int(facts.get("visible", 0)),
                    "onscreen_windows": int(facts.get("onscreen", 0)), "cloaked_windows": int(facts.get("cloaked", 0)),
                    "foreground": bool(facts.get("foreground", False)), "window_cloak_unknown": int(facts.get("cloak_unknown", 0)),
                    "app_kind": "protected process / metadata access denied", "cpu": 0.0, "mem": 0,
                    "io": 0.0, "thr": None, "handles": None, "bg": False})
            except Exception:
                pass
        except Exception:
            continue

    STATE["proc_inaccessible"] = inaccessible
    # Bound per-process scratch maps. Long-running systems can create millions of
    # short-lived process instances; stale CPU/IO/review entries must not accumulate.
    live_identities = set(current)
    for identity in list(_prev["io"]):
        if identity not in live_identities:
            _prev["io"].pop(identity, None)
    for identity in list(_proc_cpu_hot):
        if identity not in live_identities:
            _proc_cpu_hot.pop(identity, None)
    _proc_warned.intersection_update(live_identities)

    # Detect PID reuse. A new creation timestamp is a different process instance.
    previous_pids = dict(_proc_pid_identity)
    live_pids = {}
    for ident in current:
        live_pids[ident[0]] = ident
    for pid, old_ident in list(previous_pids.items()):
        new_ident = live_pids.get(pid)
        if new_ident is None or new_ident != old_ident:
            old_meta = _procs.get(old_ident)
            if learned and old_meta and old_meta.get("name", "").lower() not in NOISE:
                log("procwatch", f"exit / identity changed: {old_meta.get('name')} (pid {pid})", "debug")
            _procs.pop(old_ident, None); _prev["io"].pop(old_ident, None); _proc_cpu_hot.pop(old_ident, None)
    _proc_pid_identity.clear(); _proc_pid_identity.update(live_pids)
    _procs.clear()
    for ident, proc in current.items():
        try: _procs[ident] = {"name": proc.name(), "born": ident[1]}
        except Exception: _procs[ident] = {"name": "<exited>", "born": ident[1]}

    rows = dedupe_process_rows(rows)
    rows.sort(key=lambda r: (r["cpu"], r["mem"], r["pid"]), reverse=True)
    STATE["procs"] = rows[:2000]
    STATE["proc_total"] = len(rows)
    STATE["proc_scan_at"] = float(now)
    metric("procs", len(rows))

    # Persist the latest bounded process inventory periodically, not every sample.
    # Process lifecycle changes are separately retained in the append-only events table.
    global _last_process_snapshot
    if now - _last_process_snapshot >= 30:
        try:
            core.persist_snapshot("processes.latest", {"schema": 1, "count": len(rows), "rows": rows[:2000]})
            _last_process_snapshot = now
        except Exception as exc:
            log("storage", f"process snapshot persistence failed: {type(exc).__name__}: {str(exc)[:160]}", "warn")

    # Emit distinct process start observations after the warm-up baseline.
    if learned and previous_pids:
        row_by_identity = {(r["pid"], r["create_time"]): r for r in rows}
        for pid, ident in live_pids.items():
            if previous_pids.get(pid) == ident:
                continue
            r = row_by_identity.get(ident)
            if not r or r["name"].lower() in NOISE:
                continue
            log("procwatch", f"start observed: {r['name']} (pid {pid}) · {r['app_kind']}",
                "debug", executable=r["exe"], parent=r["parent_name"], session_id=r["session_id"],
                create_time=r["create_time"], visible_windows=r["visible_windows"])
            try:
                from . import security_engine
                security_engine.observe_process_start(r)
            except Exception as exc:
                log("process-security", f"start assessment unavailable: {type(exc).__name__}: {str(exc)[:120]}", "warn")

    # Advisory only: require repeated high resource use, protect Windows and service processes.
    protected = {"system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe",
                 "winlogon.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe", "winlog.exe", "securityhealthservice.exe",
                 "msmpeng.exe", "nissrv.exe", "searchindexer.exe", "trustedinstaller.exe", "systemsettings.exe"}
    recommendations = []
    for r in rows:
        ident = (r["pid"], r["create_time"])
        in_windows = bool(r["exe"] and os.environ.get("SystemRoot") and os.path.normcase(r["exe"]).startswith(os.path.normcase(os.environ["SystemRoot"] + os.sep)))
        eligible = (r["bg"] and r["name"].lower() not in protected and r["session_id"] not in (None, 0)
                    and not in_windows and r["path_state"] == "present")
        hot = eligible and (r["cpu"] >= 8 or r["mem"] >= 900)
        _proc_cpu_hot[ident] = _proc_cpu_hot.get(ident, 0) + 1 if hot else 0
        if hot and _proc_cpu_hot[ident] >= 15:
            recommendations.append({"pid": r["pid"], "create_time": r["create_time"], "name": r["name"],
                "exe": r["exe"], "cpu": r["cpu"], "mem": r["mem"], "reason": "sustained resource use; review before acting",
                "safe_to_terminate": False, "observations": _proc_cpu_hot[ident]})
            key = f"process-review-{r['pid']}-{int(r['create_time'])}"
            if ident not in _proc_warned:
                _proc_warned.add(ident)
                insight("warn", key, f"Review sustained background usage: {r['name']}",
                        f"CPU {r['cpu']:.1f}% · RAM {r['mem']} MB. This is an advisory, not a claim that the process is useless.",
                        r["exe"])
    STATE["proc_recommendations"] = recommendations[:30]

    # Game detection by exact process name, with the selected instance identity retained.
    gp = {str(g).lower() for g in CFG.get("game_processes", [])}
    g = next((r for r in rows if r["name"].lower() in gp), None)
    was = STATE.get("game")
    if g and not was:
        STATE["game"] = {"name": g["name"], "pid": g["pid"], "create_time": g["create_time"], "since": now}
        log("game", f"GAME MODE ON - {g['name']} detected (pid {g['pid']})", "ok")
    elif was and (not g or (g["pid"], g["create_time"]) != (was.get("pid"), was.get("create_time"))):
        STATE["game"] = None
        log("game", f"Game session ended ({int(now - was['since'])}s)", "ok")
    elif g and was:
        STATE["game"].update(cpu=g["cpu"], mem=g["mem"], exe=g["exe"], session_id=g["session_id"])


# ------------------------------------------------------------------ typeperf (PDH counters)
TP = {
    r"\Processor(_Total)\% DPC Time": "dpc",
    r"\Processor(_Total)\% Interrupt Time": "irq",
    r"\Memory\Pages Input/sec": "pagesin",
    r"\Memory\Pages Output/sec": "pagesout",
    r"\Memory\Page Reads/sec": "pagereads",
    r"\Memory\Page Faults/sec": "pagefaults",
    r"\Memory\Transition Faults/sec": "transitionfaults",
    r"\Memory\Demand Zero Faults/sec": "demandzerofaults",
    r"\Memory\Transition Pages RePurposed/sec": "transitionrepurposed",
    r"\Memory\Pages/sec": "pagessec",
    r"\Memory\Pool Paged Bytes": "pagedpoolbytes",
    r"\Memory\Pool Nonpaged Bytes": "nonpagedpoolbytes",
    r"\Memory\Cache Bytes": "cachebytes",
    r"\Memory\Available MBytes": "availablemb",
    r"\Memory\Committed Bytes": "committedbytes",
    r"\Memory\Commit Limit": "commitlimit",
    r"\Paging File(_Total)\% Usage": "pagefilepct",
    r"\PhysicalDisk(_Total)\Avg. Disk sec/Read": "dlat",
    r"\PhysicalDisk(_Total)\Avg. Disk sec/Transfer": "dlatxfer",
    r"\PhysicalDisk(_Total)\% Disk Time": "disk_busy",
    r"\Processor Information(_Total)\% Processor Performance": "cpuperf",
    r"\System\Processor Queue Length": "runq",
}


def _persist_kernel_snapshot(state: dict, last_attempt: float) -> float:
    """Persist the latest PDH state at a bounded cadence and retain the real failure reason."""
    now = time.monotonic()
    if now - last_attempt < 30:
        return last_attempt
    # Advance the retry clock before attempting I/O. A broken database must not
    # emit a warning on every one-second PDH sample.
    last_attempt = now
    try:
        core.persist_snapshot("kernel.latest", {
            "source": "PDH / typeperf",
            "pdh": dict(state),
            "values": {name: LIVE.get(name) for name in set(TP.values())},
            "captured_at": time.time(),
        })
    except Exception as store_exc:
        log(
            "storage",
            f"kernel snapshot persistence failed: {type(store_exc).__name__}: {str(store_exc)[:240]}",
            "warn",
        )
    return last_attempt


def typeperf_loop():
    if not IS_WIN:
        return
    exe = resolve_command("typeperf.exe")
    if not exe:
        STATE.setdefault("kernel", {})["pdh"] = {"available": False, "error": "typeperf.exe not found"}
        heartbeat("kernel counters (PDH)", 0, err="typeperf.exe not found")
        return
    keys = list(TP)
    last_state_save = 0.0
    while True:
        if core.off("kernel"):
            STATE.setdefault("kernel", {}).setdefault("pdh", {}).update(available=False, state="disabled", error="disabled in Feature Control")
            heartbeat("kernel counters (PDH)", 1, "disabled in Feature Control")
            time.sleep(5); continue
        try:
            p = subprocess.Popen([exe, "-si", "1"] + keys, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", creationflags=NO_WIN, bufsize=1)
            state = STATE.setdefault("kernel", {}).setdefault("pdh", {})
            state.update(available=True, source="PDH / typeperf", state="streaming", samples=0, last_sample=None,
                counters=list(TP.values()), scope="DPC/interrupt, memory paging/faults/pools, commit and physical disk counters", error="")
            log("kernel", "PDH counter stream attached; these are performance counters, not an ETW event stream", "ok")
            samples = 0; malformed = 0; unsupported = set()
            assert p.stdout is not None
            for line in p.stdout:
                line = line.strip().lstrip("\ufeff")
                if not line or line.startswith('"(PDH') or line.lower().startswith("exiting"):
                    continue
                try: row = next(csv.reader([line]))
                except Exception: malformed += 1; continue
                if len(row) != len(keys) + 1:
                    malformed += 1
                    continue
                for counter, value in zip(keys, row[1:]):
                    name = TP[counter]
                    try:
                        f = float(value)
                        if not math.isfinite(f): raise ValueError("non-finite counter")
                    except (ValueError, TypeError):
                        unsupported.add(name); continue
                    if name in ("dlat", "dlatxfer"):
                        f *= 1000.0
                    metric(name, f)
                samples += 1
                state.update(samples=samples, last_sample=time.time(), malformed_rows=malformed, unsupported=sorted(unsupported))
                heartbeat("kernel counters (PDH)", 1, f"{samples} samples; {len(keys)-len(unsupported)} valid counters")
                last_state_save = _persist_kernel_snapshot(state, last_state_save)
            try:
                stderr = (p.stderr.read() if p.stderr else "").strip()
                code = p.wait(timeout=2)
            except Exception:
                stderr, code = "", None
            if code not in (0, None):
                state.update(available=False, state="stopped", error=(stderr or f"typeperf exit code {code}")[:300])
                heartbeat("kernel counters (PDH)", 1, err=state["error"])
            else:
                state.update(state="reconnecting", error=(stderr[:300] if stderr else ""))
            log("kernel", "PDH counter stream ended; reconnecting", "warn")
        except Exception as exc:
            state = STATE.setdefault("kernel", {}).setdefault("pdh", {})
            state.update(available=False, state="unavailable", error=f"{type(exc).__name__}: {str(exc)[:240]}")
            heartbeat("kernel counters (PDH)", 1, err=state["error"])
            log("kernel", f"PDH stream unavailable: {state['error']}", "error")
        time.sleep(3)


def classify_wpr_status(returncode, output):
    """Interpret WPR status conservatively: unknown text never becomes idle/active."""
    text = str(output or "")
    low = text.casefold()
    inactive_markers = ("not recording", "no recording", "not in progress", "no active recording",
        "there is no recording", "no trace profile running", "not currently recording",
        "not running", "not active", "no profile is running", "no active profile")
    active_markers = ("recording is in progress", "recording is active", "wpr is recording",
        "profile is running", "recording profile")
    active_match = any(marker in low for marker in active_markers)
    inactive_match = any(marker in low for marker in inactive_markers)
    available = returncode == 0
    recording = (True if active_match and not inactive_match else (False if inactive_match else None)) if available else None
    error = "" if available and recording is not None else (f"wpr exit code {returncode}" if not available else "unrecognized WPR status output")
    return {"available": available, "recording": recording,
        "state": "recording" if recording is True else "idle" if recording is False else "unknown",
        "status_text": text[-1800:], "error": error}


def etw_status_loop():
    """Report the actual Windows Performance Recorder ETW session status."""
    if not IS_WIN:
        return
    exe = resolve_command("wpr.exe")
    kernel = STATE.setdefault("kernel", {})
    while True:
        t0 = time.time()
        if core.off("kernel"):
            kernel["etw"] = {"available": False, "recording": None, "state": "unknown", "source": "Windows Performance Recorder", "error": "disabled in Feature Control; current recording state not observed", "checked_at": time.time()}
            heartbeat("ETW session status", 30, "disabled in Feature Control")
            time.sleep(5); continue
        if not exe:
            kernel["etw"] = {"available": False, "recording": None, "state": "unknown", "source": "Windows Performance Recorder", "error": "wpr.exe not found; current recording state not observed", "checked_at": time.time()}
            heartbeat("ETW session status", 30, err="wpr.exe not found")
            time.sleep(30); continue
        try:
            r = run_command([exe, "-status"], timeout=12)
            output = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
            parsed = classify_wpr_status(r.returncode, output)
            recording = parsed["recording"]
            kernel["etw"] = {**parsed, "source": "Windows Performance Recorder / ETW", "checked_at": time.time()}
            heartbeat("ETW session status", 30, "recording active" if recording is True else "WPR reports no active trace" if recording is False else "WPR status unverified",
                err=("" if recording is not None and r.returncode == 0 else kernel["etw"]["error"]))
            try: core.persist_snapshot("kernel.etw.latest", dict(kernel["etw"]))
            except Exception as store_exc: log("storage", f"ETW status persistence failed: {type(store_exc).__name__}: {str(store_exc)[:240]}", "warn")
        except Exception as exc:
            kernel["etw"] = {"available": False, "recording": None, "state": "unknown", "source": "Windows Performance Recorder / ETW",
                "error": f"{type(exc).__name__}: {str(exc)[:200]}", "checked_at": time.time()}
            heartbeat("ETW session status", 30, err=kernel["etw"]["error"])
        sleep_to(t0, 30)


# ------------------------------------------------------------------ GPU
def gpu_loop():
    exe = shutil.which("nvidia-smi") or (r"C:\Windows\System32\nvidia-smi.exe" if IS_WIN else None)
    if not exe or not os.path.exists(exe):
        heartbeat("gpu", 0, "no NVIDIA GPU / nvidia-smi")
        return
    q = "name,temperature.gpu,utilization.gpu,clocks.sm,clocks.max.sm,power.draw,power.limit,memory.used,memory.total,clocks_throttle_reasons.active"
    while True:
        t0 = time.time()
        if core.off("gpu"):
            heartbeat("gpu (nvidia-smi)", 2, "disabled in Feature Control"); time.sleep(5); continue
        out = run([exe, f"--query-gpu={q}", "--format=csv,noheader,nounits"], 5)
        if not out.strip():
            out = run([exe, f"--query-gpu={q.replace('throttle','event')}", "--format=csv,noheader,nounits"], 5)
        f = [x.strip() for x in out.strip().split(",")] if out.strip() else []
        fan_out = run([exe, "--query-gpu=fan.speed", "--format=csv,noheader,nounits"], 5)
        fan_pct = None
        try:
            fan_value = fan_out.strip().splitlines()[0].strip().replace("%", "")
            if fan_value.upper() not in ("N/A", "[N/A]", "NOT SUPPORTED"):
                parsed_fan = float(fan_value)
                if 0 <= parsed_fan <= 100: fan_pct = parsed_fan
        except (IndexError, TypeError, ValueError):
            pass
        if len(f) >= 10:
            try:
                metric("gpu", float(f[2])); metric("gputemp", float(f[1])); metric("gpuclk", float(f[3]))
                metric("gpumem", float(f[7]) / max(1, float(f[8])) * 100); metric("gpupwr", float(f[5]))
                bits = int(f[9], 16) if f[9].startswith("0x") else 0
                STATE["gpu"] = {"name": f[0], "temp": f[1], "util": f[2], "clk": f[3], "maxclk": f[4],
                                "pwr": f[5], "pwrlim": f[6], "vram": f[7], "vramtot": f[8],
                                "fan_speed_pct": fan_pct, "fan_speed_source": "nvidia-smi fan.speed (percentage)" if fan_pct is not None else "unsupported/unavailable",
                                "fan_rpm": None,
                                "throttle": [n for b, n in ((4, "power cap"), (8, "HW slowdown"), (32, "SW thermal"),
                                                            (64, "HW thermal"), (128, "power brake")) if bits & b]}
            except Exception:
                pass
        heartbeat("gpu (nvidia-smi)", 2, STATE.get("gpu", {}).get("name", ""))
        try:
            from . import runtime_engine
            interval = runtime_engine.collector_interval("gpu", 2.0)
        except Exception:
            interval = 2.0
        sleep_to(t0, interval)


# ------------------------------------------------------------------ network
_seen_remote = set()
_ping_hist = []


def ping_loop():
    host = "1.1.1.1"
    while True:
        t0 = time.time()
        if core.off("ping"):
            heartbeat("latency probe (ping)", 1, "disabled in Feature Control"); time.sleep(5); continue
        cmd = ["ping", "-n", "1", "-w", "1000", host] if IS_WIN else ["ping", "-c", "1", "-W", "1", host]
        out = run(cmd, 3)
        m = re.search(r"time[=<]\s*([\d.]+)\s*ms", out)
        if m:
            v = float(m.group(1)); metric("ping", v)
            if _ping_hist:
                metric("jitter", abs(v - _ping_hist[-1]))
            _ping_hist.append(v); del _ping_hist[:-20]
            metric("loss", 0)
        else:
            metric("loss", 100)
        heartbeat("latency probe (ping)", 1, f"{host}")
        try:
            from . import runtime_engine
            interval = runtime_engine.collector_interval("ping", 1.0)
        except Exception:
            interval = 1.0
        sleep_to(t0, interval)


def is_private(ip):
    return ip.startswith(("10.", "192.168.", "127.", "169.254.", "::1", "fe80", "0.")) or re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip)


def net_loop():
    t_start = time.time()
    while True:
        t0 = time.time()
        if core.off("net"):
            heartbeat("network connections", 5, "disabled in Feature Control"); time.sleep(5); continue
        conns = []
        try:
            for c in psutil.net_connections(kind="inet"):
                if c.raddr and c.status == "ESTABLISHED" and not is_private(c.raddr.ip):
                    ident = _proc_pid_identity.get(c.pid) if c.pid else None
                    name = _procs.get(ident, {}).get("name", "?") if ident else "?"
                    conns.append({"proc": name, "pid": c.pid, "ip": c.raddr.ip, "port": c.raddr.port})
                    key = (name, c.raddr.ip)
                    if key not in _seen_remote:
                        _seen_remote.add(key)
                        if time.time() - t_start > WARMUP:
                            log("netwatch", f"new outbound  {name} -> {c.raddr.ip}:{c.raddr.port}", "debug")
        except Exception as e:
            heartbeat("network connections", 5, err=str(e)[:60])
        STATE["net"] = conns[:80]
        metric("conns", len(conns))
        heartbeat("network connections", 5, f"{len(conns)} established, {len(_seen_remote)} endpoints learned")
        try:
            from . import runtime_engine
            interval = runtime_engine.collector_interval("network", 5.0)
        except Exception:
            interval = 5.0
        sleep_to(t0, interval)


# ------------------------------------------------------------------ services / autoruns / event log / config
def _read_services():
    """Read SCM metadata with per-service isolation and a CIM fallback.

    Windows services can disappear between enumeration and individual SCM queries.
    psutil raises FileNotFoundError/WinError 2 in that race; keep the other rows and
    use Win32_Service via PowerShell to repair a fully/partially failed enumeration.
    """
    records, errors = [], []
    if not IS_WIN:
        return records, errors
    try:
        iterator = iter(psutil.win_service_iter())
        for service in iterator:
            name = "<unknown>"
            try:
                name = service.name()
                row = {"name": name}
                for field, accessor in (("display", "display_name"), ("state", "status"),
                    ("start", "start_type"), ("pid", "pid"), ("binpath", "binpath"),
                    ("username", "username"), ("description", "description")):
                    try:
                        row[field] = getattr(service, accessor)()
                    except (psutil.NoSuchProcess, FileNotFoundError, ProcessLookupError):
                        row[field] = None
                        if field in ("state", "start"):
                            row["record_error"] = "service vanished during SCM query"
                    except psutil.AccessDenied:
                        row[field] = None
                    except (OSError, AttributeError) as exc:
                        row[field] = None
                        errors.append({"service": name, "field": field,
                            "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
                records.append(row)
            except (psutil.NoSuchProcess, FileNotFoundError, ProcessLookupError):
                errors.append({"service": name, "error": "service disappeared during enumeration"})
            except (psutil.AccessDenied, OSError) as exc:
                errors.append({"service": name, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
    except Exception as exc:
        errors.append({"service": "<enumeration>", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})

    # Recover from SCM transient errors using a separate Windows CIM provider.
    if not records or errors:
        try:
            from .winutil import powershell
            script = r"""
$ErrorActionPreference='Stop'
$items = @(Get-CimInstance Win32_Service -ErrorAction Stop | Select-Object @{n='name';e={$_.Name}},@{n='display';e={$_.DisplayName}},@{n='state';e={$_.State.ToLower()}},@{n='start';e={$_.StartMode.ToLower()}},@{n='pid';e={$_.ProcessId}},@{n='binpath';e={$_.PathName}},@{n='username';e={$_.StartName}})
@{services=$items;count=$items.Count} | ConvertTo-Json -Depth 5 -Compress
"""
            result = powershell(script, timeout=35)
            if result.returncode == 0 and result.stdout.strip():
                payload = json.loads(result.stdout.strip().lstrip("\ufeff"))
                fallback = payload.get("services", []) if isinstance(payload, dict) else []
                if isinstance(fallback, dict): fallback = [fallback]
                count = payload.get("count") if isinstance(payload, dict) else None
                valid_rows = (isinstance(fallback, list)
                    and all(isinstance(row, dict) and row.get("name") for row in fallback)
                    and isinstance(count, int) and not isinstance(count, bool) and count == len(fallback))
                if valid_rows:
                    # CIM is a complete fresh snapshot, not merely a patch to the
                    # possibly-racy SCM list. Keep earlier race diagnostics marked recovered.
                    records = list(fallback)
                    errors = [{**item, "recovered": True} for item in errors]
                    errors.append({"service": "<psutil-fallback>",
                        "error": "SCM enumeration race recovered by complete Win32_Service CIM snapshot",
                        "recovered": True})
                else:
                    errors.append({"service": "<cim-fallback>", "error": "CIM response did not contain a validated complete service list"})
            elif result.returncode != 0:
                errors.append({"service": "<cim-fallback>", "error": (result.stderr or f"PowerShell exit {result.returncode}")[:200]})
        except Exception as exc:
            errors.append({"service": "<cim-fallback>", "error": f"{type(exc).__name__}: {str(exc)[:180]}"})

    records.sort(key=lambda r: (str(r.get("display") or r.get("name") or "").casefold(), str(r.get("name") or "")))
    return records, errors[:100]


def service_loop():
    if not IS_WIN:
        return
    last = {}
    first = True
    while True:
        t0 = time.time()
        if core.off("services"):
            heartbeat("services (SCM)", 30, "disabled in Feature Control"); time.sleep(5); continue
        cur, errors = _read_services()
        states = {str(row["name"]): row.get("state") or "unknown" for row in cur if row.get("name")}
        if not first:
            for row in cur:
                k, st = row.get("name"), row.get("state") or "unknown"
                if not k: continue
                if k not in last:
                    log("services", f"NEW service registered: {k} ({row.get('display') or ''})", "warn")
                elif last[k] != st:
                    lvl = "warn" if k.lower() in ("vgc", "vgk", "windefend", "wuauserv") else "debug"
                    log("services", f"{k}: {last[k]} -> {st}", lvl)
        last = states
        running = sum(1 for value in states.values() if value == "running")
        STATE["services_catalog"] = cur
        STATE["services"] = {"running": running, "total": len(cur), "errors": len(errors),
            "vanguard": {"vgc": states.get("vgc", "n/a"), "vgk": states.get("vgk", "n/a")}}
        try: core.persist_snapshot("services.latest", {"captured_at": time.time(), "summary": STATE["services"], "rows": cur[:1200], "errors": errors[:50]})
        except Exception as store_exc: log("storage", f"SCM snapshot persistence failed: {type(store_exc).__name__}", "warn")
        first = False
        unresolved = [item for item in errors if not item.get("recovered")]
        recovered_count = sum(1 for item in errors if item.get("recovered"))
        detail = f"{running}/{len(cur)} running; {len(unresolved)} unresolved read errors; {recovered_count} recovered"
        heartbeat("services (SCM)", 30, detail, err=(unresolved[0]["error"] if unresolved else ""))
        if unresolved:
            log("services", f"SCM enumeration has {len(unresolved)} unresolved errors; other services retained", "warn")
        elif recovered_count:
            log("services", "SCM enumeration recovered through a complete Win32_Service CIM snapshot", "info")
        sleep_to(t0, 30.0)


def autorun_loop():
    if not IS_WIN:
        return
    import winreg
    keys = [(winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run")]
    last = None
    while True:
        t0 = time.time()
        if core.off("autoruns"):
            heartbeat("autorun watcher (registry)", 60, "disabled in Feature Control"); time.sleep(5); continue
        cur = {}
        for root, path in keys:
            try:
                with winreg.OpenKey(root, path) as k:
                    i = 0
                    while True:
                        try:
                            n, v, _ = winreg.EnumValue(k, i); cur[f"{path.split(chr(92))[-1]}:{n}"] = str(v); i += 1
                        except OSError:
                            break
            except OSError:
                pass
        if last is not None:
            for k, v in cur.items():
                if k not in last:
                    insight("warn", "autorun-new", f"New startup entry: {k}", v)
            for k in last:
                if k not in cur:
                    log("autorun", f"startup entry removed: {k}", "info")
        STATE["autoruns"] = len(cur)
        STATE["startup"] = [{"name": k.split(":",1)[1], "cmd": v, "where": k.split(":",1)[0]} for k, v in cur.items()]
        last = cur
        heartbeat("autorun watcher (registry)", 60, f"{len(cur)} startup entries")
        sleep_to(t0, 60.0)


_seen_evt = set()


def _parse_event_xml(fragment: str) -> dict:
    """Extract a small, allowlisted Event Viewer record; discard raw XML."""
    root = ET.fromstring(fragment)
    system = next((node for node in root.iter() if node.tag.endswith("System")), None)
    if system is None:
        return {}
    children = {node.tag.rsplit("}", 1)[-1]: node for node in list(system)}
    provider_node = children.get("Provider")
    provider = str((provider_node.attrib or {}).get("Name") or "?") if provider_node is not None else "?"
    record_node = children.get("EventRecordID")
    event_node = children.get("EventID")
    level_node = children.get("Level")
    time_node = children.get("TimeCreated")
    event_id = (event_node.text or "").strip() if event_node is not None else ""
    record_id = (record_node.text or "").strip() if record_node is not None else ""
    level = (level_node.text or "").strip() if level_node is not None else "2"
    occurred_at = None
    if time_node is not None:
        raw_time = str((time_node.attrib or {}).get("SystemTime") or "")
        try:
            occurred_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            occurred_at = None

    allowed = {
        "appname", "applicationname", "faultingapplicationname", "faultingprocessname",
        "modulename", "faultingmodulename", "exceptioncode", "faultingprocessid",
        "processid", "bugcheckcode", "bugcheckparameter1", "bugcheckparameter2",
        "bugcheckparameter3", "bugcheckparameter4", "reportid", "updatetitle",
        "updateguid", "deviceinstanceid", "devicename", "deviceid", "drivername",
        "servicename", "taskname", "taskpath", "failurecode",
    }
    data = {}
    for node in root.iter():
        if not node.tag.endswith("Data"):
            continue
        name = str(node.attrib.get("Name") or "").strip()
        normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
        if normalized not in allowed or len(data) >= 8:
            continue
        value = " ".join(str(node.text or "").split())
        if not value:
            continue
        if any(token in normalized for token in ("appname", "applicationname", "processname", "modulename", "drivername")):
            value = value.replace("\\", "/").rsplit("/", 1)[-1]
        if re.search(r"(?i)(password|token|secret|credential|cookie|authorization|api.?key)", value):
            continue
        data[name[:40]] = value[:140]

    return {
        "provider": provider[:100], "event_id": event_id[:20], "record_id": record_id[:40],
        "level": level[:4], "occurred_at": occurred_at, "data": data,
    }


def _event_is_review_worthy(channel: str, event: dict) -> bool:
    provider = str(event.get("provider") or "").casefold()
    event_id = str(event.get("event_id") or "")
    return (
        (channel.casefold() == "application" and event_id in {"1000", "1001", "1002", "1026"})
        or "whea" in provider
        or "bugcheck" in provider
        or "wer-systemerrorreporting" in provider
        or "kernel-power" in provider and event_id in {"41", "6008"}
        or any(token in provider for token in ("disk", "ntfs", "storahci", "stornvme", "display", "nvlddmkm", "amdkmdag"))
        or "kernel-pnp" in provider and event.get("level") in {"1", "2"}
        or "windowsupdateclient" in provider and event.get("level") in {"1", "2"}
    )


def _event_summary(channel: str, event: dict, historical: bool) -> str:
    provider = str(event.get("provider") or "Unknown provider")
    event_id = str(event.get("event_id") or "?")
    label = {
        "1000": "Application Error",
        "1001": "Windows Error Reporting / BugCheck report",
        "1002": "Application Hang",
        "1026": ".NET Runtime failure",
        "41": "Kernel-Power unexpected restart",
        "6008": "Unexpected shutdown",
    }.get(event_id, "Windows event")
    parts = [label, f"Event ID {event_id}", f"Provider {provider}", f"Channel {channel}"]
    details = event.get("data") if isinstance(event.get("data"), dict) else {}
    for key in ("AppName", "ApplicationName", "FaultingApplicationName", "ModuleName",
                "FaultingModuleName", "ExceptionCode", "BugcheckCode", "DeviceName", "DriverName",
                "UpdateTitle", "ServiceName", "TaskName"):
        value = details.get(key)
        if value:
            parts.append(f"{key}={value}")
    if historical:
        parts.append("found in existing Event Viewer history at agent startup")
    return " · ".join(parts)[:900]


def evtlog_loop():
    if not IS_WIN:
        return
    queries = [
        ("System", "*[System[(Level=1 or Level=2)]]", 30),
        ("Application", "*[System[(EventID=1000 or EventID=1001 or EventID=1002 or EventID=1026)]]", 30),
        ("Microsoft-Windows-Diagnostics-Performance/Operational", "*[System[(EventID>=100 and EventID<=110)]]", 20),
        ("Microsoft-Windows-WindowsUpdateClient/Operational", "*[System[(Level=1 or Level=2)]]", 12),
        ("Microsoft-Windows-Kernel-PnP/Configuration", "*[System[(Level=1 or Level=2)]]", 12),
        ("Microsoft-Windows-TaskScheduler/Operational", "*[System[(Level=1 or Level=2)]]", 12),
    ]
    core.db("""CREATE TABLE IF NOT EXISTS windows_event_seen(
        channel TEXT NOT NULL, record_id TEXT NOT NULL, occurred_at REAL,
        seen_at REAL NOT NULL, PRIMARY KEY(channel,record_id))""")
    core.db("""CREATE TABLE IF NOT EXISTS windows_event_state(
        state_key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)""")
    baseline = bool(core.db("SELECT 1 FROM windows_event_state WHERE state_key='baseline_complete' LIMIT 1"))
    while True:
        t0 = time.time()
        if core.off("eventlog"):
            heartbeat("event logs (wevtutil)", 60, "disabled in Feature Control"); time.sleep(5); continue
        n_new, n_historical, n_errors = 0, 0, 0
        channels_ok = 0
        for channel, xpath, cap in queries:
            output = run(["wevtutil", "qe", channel, f"/q:{xpath}", f"/c:{cap}",
                          "/rd:true", "/f:xml"], 18)
            if output.startswith("[SENTINEL_COMMAND_ERROR:") or "No events were found" in output:
                if output.startswith("[SENTINEL_COMMAND_ERROR:"):
                    n_errors += 1
                else:
                    channels_ok += 1
                continue
            fragments = re.findall(r"<Event(?:\s[^>]*)?>.*?</Event>", output, re.S)
            if fragments:
                channels_ok += 1
            for fragment in fragments:
                try:
                    event = _parse_event_xml(fragment)
                except (ET.ParseError, TypeError, ValueError):
                    continue
                record_id = event.get("record_id")
                event_id = event.get("event_id")
                if not record_id or not event_id:
                    continue
                key = (channel, record_id)
                if key in _seen_evt:
                    continue
                if core.db("SELECT 1 FROM windows_event_seen WHERE channel=? AND record_id=? LIMIT 1", key):
                    _seen_evt.add(key)
                    continue
                now = time.time()
                core.db("INSERT OR IGNORE INTO windows_event_seen(channel,record_id,occurred_at,seen_at) VALUES(?,?,?,?)",
                        (channel, record_id, event.get("occurred_at"), now))
                _seen_evt.add(key)

                historical = not baseline
                important = _event_is_review_worthy(channel, event)
                # Initial import examines existing crash/hardware/update faults without
                # replaying every old informational or generic service warning.
                if historical and not important:
                    n_historical += 1
                    continue

                provider = str(event.get("provider") or "?")
                summary = _event_summary(channel, event, historical)
                severity = "error" if event.get("level") in {"1", "2"} and important else (
                    "warn" if event.get("level") in {"1", "2", "3"} else "info"
                )
                payload = {
                    "provider": provider, "event_id": event_id, "channel": channel,
                    "record_id": record_id, "occurred_at": event.get("occurred_at"),
                    "historical_backfill": historical, "event_data": event.get("data") or {},
                }
                log("eventlog", summary, severity, **payload)
                if "whea" in provider.casefold():
                    insight("high", "whea", "Windows hardware error reported (WHEA)", summary, provider,
                            event_id=event_id, channel=channel)
                elif any(token in provider.casefold() for token in ("nvlddmkm", "amdkmdag", "display")):
                    insight("high", "gpu-tdr", "GPU driver reset/error (TDR)", summary, provider,
                            event_id=event_id, channel=channel)
                elif any(token in provider.casefold() for token in ("disk", "ntfs", "storahci", "stornvme")):
                    insight("high", "disk-err", "Disk/storage error", summary, provider,
                            event_id=event_id, channel=channel)
                n_new += 1
        if not baseline:
            core.db("INSERT INTO windows_event_state(state_key,value,updated_at) VALUES('baseline_complete','1',?) "
                    "ON CONFLICT(state_key) DO UPDATE SET value='1',updated_at=excluded.updated_at",
                    (time.time(),))
            baseline = True
        core.db("DELETE FROM windows_event_seen WHERE seen_at<?", (time.time() - 30 * 86400,))
        if len(_seen_evt) > 5000:
            _seen_evt.clear()
        STATE["eventlog"] = {
            "channels_configured": len(queries), "channels_responding": channels_ok,
            "new_records": n_new, "historical_noncritical_skipped": n_historical,
            "source_errors": n_errors, "last_scan_at": time.time(),
        }
        heartbeat("event logs (wevtutil)", 60,
                  f"{n_new} records · {channels_ok}/{len(queries)} channels responded · {n_errors} source errors")
        sleep_to(t0, 60.0)


def config_loop():
    """Slow-moving system facts: power plan, battery, uptime, Defender, VBS."""
    while True:
        t0 = time.time()
        if core.off("system"):
            heartbeat("system config", 300, "disabled in Feature Control"); time.sleep(5); continue
        info = {"uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1),
                "cpu_physical": psutil.cpu_count(logical=False), "cpu_logical": psutil.cpu_count(),
                "ram_total_gb": round(psutil.virtual_memory().total / 2**30, 2),
                "ram_available_gb": round(psutil.virtual_memory().available / 2**30, 2),
                "boot_time": psutil.boot_time()}
        try:
            b = psutil.sensors_battery()
            if b:
                info["battery"] = {"pct": round(b.percent), "plugged": b.power_plugged}
        except Exception:
            pass
        if IS_WIN:
            m = re.search(r"\(([^)]+)\)", run(["powercfg", "/getactivescheme"], 5))
            info["power_plan"] = m.group(1) if m else "?"
            out = run(["powershell", "-NoProfile", "-Command",
                       "(Get-CimInstance -Namespace root\\Microsoft\\Windows\\DeviceGuard -ClassName Win32_DeviceGuard).VirtualizationBasedSecurityStatus;"
                       "(Get-MpComputerStatus).RealTimeProtectionEnabled"], 25).split()
            if len(out) >= 1:
                info["vbs"] = out[0] == "2"
            if len(out) >= 2:
                info["defender_rt"] = out[1].lower() == "true"
        STATE["system"] = info
        try: core.persist_snapshot("system.latest", {"captured_at": time.time(), **info})
        except Exception as store_exc: log("storage", f"system snapshot persistence failed: {type(store_exc).__name__}", "warn")
        heartbeat("system config", 300, f"plan={info.get('power_plan','-')} vbs={info.get('vbs','-')}")
        sleep_to(t0, 300.0)


def maintenance_loop():
    while True:
        time.sleep(1)
        core.flush_metrics()
        heartbeat("storage writer", 1, "SQLite flush")
        if int(time.time()) % 3600 == 0:
            core.prune()


# ------------------------------------------------------------------ demo (non-Windows / --demo)
def _build_demo_process_rows(names, spike=False):
    """Build unmistakably synthetic process rows for dashboard preview only."""
    return [
        {"pid": 1000 + i, "create_time": float(1_700_000_000 + i), "name": name,
         "exe": "", "path_state": "synthetic demo (no host path)",
         "parent_pid": None, "parent_name": "synthetic demo",
         "username": "synthetic demo", "status": "running",
         "session_id": None, "visible_windows": 0, "onscreen_windows": 0,
         "cloaked_windows": 0, "foreground": False,
         "app_kind": "synthetic demo process (not a host process)",
         "cpu": round(random.random() * (18 if "VALORANT" in name else 6) + (22 if spike and name == "chrome.exe" else 0), 1),
         "mem": int(random.random() * 1400 + 120), "io": round(random.random() * 3, 2),
         "thr": int(random.random() * 60 + 4), "handles": None,
         "bg": name.lower() in BG_NAMES}
        for i, name in enumerate(names)
    ]


def demo_loop():
    log("demo", "DEMO MODE - synthetic telemetry (no real Windows data)", "warn")
    t = 0
    names = ["chrome.exe", "discord.exe", "VALORANT-Win64-Shipping.exe", "msedge.exe", "steamwebhelper.exe",
             "MsMpEng.exe", "explorer.exe", "dwm.exe", "OneDrive.exe", "Spotify.exe", "RiotClientServices.exe", "vgc.exe"]
    STATE["game"] = {"name": "VALORANT-Win64-Shipping.exe", "pid": 4242, "since": time.time(), "cpu": 21, "mem": 3100}
    STATE["system"] = {"uptime_h": 31.4, "power_plan": "Balanced", "vbs": True, "defender_rt": True, "battery": None}
    STATE["services"] = {"running": 112, "total": 241, "vanguard": {"vgc": "running", "vgk": "running"}}
    STATE["gpu"] = {"name": "NVIDIA GeForce RTX 3060", "temp": "61", "util": "74", "clk": "1815", "maxclk": "1950",
                    "pwr": "112", "pwrlim": "170", "vram": "4210", "vramtot": "12288", "throttle": []}
    STATE["autoruns"] = 17
    # Values plotted below are deliberately synthetic; never advertise them as
    # live PDH or kernel ETW. WPR status has not been queried in demo mode.
    STATE["kernel"] = {
        "pdh": {"available": False, "state": "synthetic_demo", "source": "synthetic demo telemetry (not PDH)",
                "samples": 0, "counters": [], "error": "Windows PDH counters are not queried in demo mode"},
        "etw": {"available": False, "recording": None, "state": "unknown",
                "source": "Windows Performance Recorder / ETW", "error": "not queried in demo mode"},
    }
    cores = NCPU
    while True:
        t0 = time.time(); t += 1
        spike = (t % 47 in (0, 1, 2))
        cpu = 34 + 10 * math.sin(t / 9) + random.random() * 6 + (45 if spike else 0)
        metric("cpu", min(100, cpu)); metric("mem", 71 + 2 * math.sin(t / 40) + random.random())
        metric("mem_free_mb", 2900 - 200 * math.sin(t / 40)); metric("swap", 38 + random.random())
        metric("dpc", 0.6 + random.random() * 0.8 + (11 if spike else 0)); metric("irq", 0.4 + random.random() * 0.3)
        metric("pagesin", 180 + random.random() * 300 + (4000 if t % 60 < 3 else 0)); metric("pagesout", random.random() * 20)
        metric("pagereads", 40 + random.random() * 80); metric("dlat", 0.4 + random.random() * 0.7 + (9 if spike else 0))
        metric("cpuperf", 100 - (28 if spike else 0) + random.random() * 3); metric("runq", random.random() * 4)
        metric("gpu", 70 + 8 * math.sin(t / 6) + random.random() * 4); metric("gputemp", 60 + random.random() * 3)
        metric("gpumem", 34 + random.random()); metric("gpuclk", 1800 + random.random() * 40); metric("gpupwr", 110 + random.random() * 6)
        metric("netdown", 3 + random.random() * 2); metric("netup", 1 + random.random()); metric("diskr", random.random() * 30)
        metric("diskw", random.random() * 6); metric("ping", 21 + random.random() * 2 + (14 if spike else 0))
        metric("jitter", random.random() * 1.5 + (9 if spike else 0)); metric("loss", 0); metric("conns", 38 + int(random.random() * 4))
        metric("ctx", 52000 + random.random() * 9000); metric("ints", 31000 + random.random() * 4000); metric("procs", 214)
        STATE["cores"] = [round(max(0, min(100, cpu + random.uniform(-25, 25))), 1) for _ in range(cores)]
        demo_processes = _build_demo_process_rows(names, spike=spike)
        STATE["procs"] = sorted(demo_processes, key=lambda r: -r["cpu"])
        STATE["proc_total"] = len(demo_processes)
        STATE["net"] = [{"proc": "VALORANT-Win64-Shipping.exe", "pid": 4242, "ip": "104.160.131.3", "port": 443},
                        {"proc": "discord.exe", "pid": 3311, "ip": "162.159.135.234", "port": 443},
                        {"proc": "chrome.exe", "pid": 2210, "ip": "142.250.77.46", "port": 443}]
        if spike and t % 47 == 0:
            log("procwatch", "spawn MoUsoCoreWorker.exe (pid 9100) <- svchost.exe", "debug")
            log("eventlog", "Windows event 10016 from DistributedCOM (System)", "warn")
        for nme, ev in (("system+processes", 1), ("kernel-counters (PDH)", 1), ("gpu (nvidia-smi)", 2), ("latency probe (ping)", 1),
                        ("network connections", 5), ("services (SCM)", 30), ("autorun watcher (registry)", 60),
                        ("event logs (wevtutil)", 30), ("system config", 300), ("storage writer", 1)):
            heartbeat(nme, ev, "demo")
        core.flush_metrics()
        sleep_to(t0, 1.0)


def start_all(demo=False):
    T = core.thread
    from . import inventory
    T(inventory.loop, "inventory")
    if demo or not IS_WIN:
        T(demo_loop, "demo")
        return
    for fn in (fast_loop, typeperf_loop, etw_status_loop, gpu_loop, ping_loop, net_loop, service_loop, autorun_loop, evtlog_loop,
               config_loop, maintenance_loop):
        T(fn, fn.__name__)
