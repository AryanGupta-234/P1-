"""HTTP + Server-Sent-Events API. Binds 127.0.0.1 only; every /api call needs the install token."""
import ctypes, json, os, threading, time, urllib.parse, psutil, platform, sys, hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import core, actions, ai, intel, inventory, intelligence, advanced, activity_engine
from . import safeguard, runtime_engine, memory_engine, ai_engine, security_engine, hardware_provider, maintenance
from .core import CFG, STATE, LIVE, HIST, HEART, START, db, log, save_cfg

UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml"}
_AGENT_PROCESS = psutil.Process(os.getpid())
_HTTP_SERVER = None
_HTTP_SERVER_LOCK = threading.Lock()
SPARK_KEYS = ["cpu", "dpc", "mem", "mem_free_mb", "pagesin", "pagesout", "pagereads", "pagefaults", "transitionfaults",
              "availablemb", "pagefilepct", "dlat", "dlatxfer", "disk_busy", "gpu", "gputemp", "ping", "jitter",
              "netdown", "netup", "lag_index", "cpuperf", "diskr", "diskw", "irq", "ctx", "conns"]


def sensor_matrix():
    now = time.time()
    rows, healthy, degraded, stale, unavailable = [], 0, 0, 0, 0
    for name, item in sorted(HEART.items()):
        every = max(0.0, float(item.get("every", 0) or 0))
        last = float(item.get("last", 0) or 0)
        age = max(0.0, now - last) if last else None
        if every == 0:
            state = "unavailable"
            unavailable += 1
        elif item.get("err"):
            state = "degraded"
            degraded += 1
        elif age is None or age > max(8.0, every * 3):
            state = "stale"
            stale += 1
        else:
            state = "healthy"
            healthy += 1
        rows.append({"name": name, "state": state, "every_s": every,
            "last_seen": last or None, "age_s": round(age, 1) if age is not None else None,
            "runs": int(item.get("runs", 0) or 0), "note": item.get("note", ""), "error": item.get("err", "")})
    return {"healthy": healthy, "degraded": degraded, "stale": stale, "unavailable": unavailable,
            "total": len(rows), "rows": rows,
            "status": "pending" if not rows else ("degraded" if degraded or stale or unavailable else "operational")}


def find_reviewable_process(pid, created, exe, rows):
    """Resolve an exact, currently visible GUI process instance for a close proposal."""
    try:
        pid = int(pid); created = float(created); exe = os.path.normcase(os.path.abspath(str(exe or "")))
    except (TypeError, ValueError, OSError):
        return None
    if pid <= 4 or not exe or not os.path.isabs(exe):
        return None
    for row in rows:
        try:
            if (int(row.get("pid", -1)) == pid
                and abs(float(row.get("create_time", -1)) - created) <= 0.01
                and os.path.normcase(os.path.abspath(str(row.get("exe") or ""))) == exe
                and row.get("session_id") not in (None, 0)
                and int(row.get("visible_windows") or 0) > 0
                and int(row.get("onscreen_windows") or 0) > 0
                and row.get("path_state") == "present"):
                return row
        except (TypeError, ValueError, OSError):
            continue
    return None


def agent_runtime(*, include_threads=True, include_io=True, include_run=True):
    """Measured resource footprint for this agent process, separate from whole-host load.

    cpu_percent is the share of total logical-processor capacity; cpu_one_core_percent
    is psutil's conventional per-core figure and can exceed 100 on multi-core hosts.
    """
    process = _AGENT_PROCESS
    try: executable = process.exe()
    except Exception: executable = sys.executable
    try: username = process.username()
    except Exception: username = "unavailable"
    try:
        is_elevated = bool(ctypes.windll.shell32.IsUserAnAdmin()) if core.IS_WIN else None
    except Exception:
        is_elevated = None
    try:
        memory = process.memory_info()
        rss = round(memory.rss / 2**20, 1)
    except Exception:
        rss = None
    try: memory_pct = round(process.memory_percent(), 3)
    except Exception: memory_pct = None
    try:
        cpu_one_core = round(process.cpu_percent(interval=None), 2)
    except Exception:
        cpu_one_core = None
    logical = max(1, int(psutil.cpu_count(logical=True) or 1))
    cpu_host = round(cpu_one_core / logical, 3) if cpu_one_core is not None else None
    try: host_cpu = round(psutil.cpu_percent(interval=None), 1)
    except Exception: host_cpu = None
    try:
        host_memory = psutil.virtual_memory()
        host_ram = {
            "total_mb": round(host_memory.total / 2**20),
            "used_mb": round(host_memory.used / 2**20),
            "available_mb": round(host_memory.available / 2**20),
            "percent": round(host_memory.percent, 1),
        }
    except Exception:
        host_ram = None
    try: threads = process.num_threads()
    except Exception: threads = None
    try: handles = process.num_handles() if core.IS_WIN else None
    except Exception: handles = None
    try: process_started_at = float(process.create_time())
    except Exception: process_started_at = START
    try: username = process.username()
    except Exception: username = "unavailable"
    try:
        from .collectors import _session_id
        session_id = _session_id(os.getpid())
    except Exception:
        session_id = None
    io_read = io_write = None
    if include_io:
        try:
            io = process.io_counters()
            io_read, io_write = int(io.read_bytes), int(io.write_bytes)
        except Exception:
            pass
    worker_threads = None
    if include_threads:
        worker_threads = []
        for thread in threading.enumerate():
            if thread.name == "MainThread" or thread.name.startswith("Thread-"):
                continue
            worker_threads.append({
                "name": thread.name,
                "alive": bool(thread.is_alive()),
                "daemon": bool(thread.daemon),
            })
        worker_threads.sort(key=lambda row: row["name"].casefold())
    run = None
    if include_run:
        run_rows = core.db("SELECT id,started_at,run_mode,exit_reason FROM agent_runs WHERE pid=? ORDER BY id DESC LIMIT 1", (os.getpid(),))
        if run_rows:
            run = {"id": run_rows[0][0], "started_at": run_rows[0][1], "mode": run_rows[0][2],
                   "exit_reason": run_rows[0][3]}
    try: is_running = bool(process.is_running() and process.status() != psutil.STATUS_ZOMBIE)
    except Exception: is_running = True
    return {
        "state": "running" if is_running else "stopped",
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "executable": executable,
        "username": username,
        "version": os.environ.get("SENTINEL_VERSION", "unknown"),
        "is_elevated": is_elevated,
        "session_id": session_id,
        "execution_context": "interactive Windows session" if core.IS_WIN and session_id not in (None, 0) else ("Session 0 / non-interactive" if core.IS_WIN else "non-Windows / demo"),
        "desktop_access_expected": bool(core.IS_WIN and session_id not in (None, 0)),
        "process_started_at": process_started_at,
        "uptime_s": round(max(0.0, time.time() - process_started_at), 1),
        "cpu_percent": cpu_host,
        "cpu_one_core_percent": cpu_one_core,
        "logical_processors": logical,
        "host_cpu_percent": host_cpu,
        "rss_mb": rss,
        "memory_percent": memory_pct,
        "host_memory": host_ram,
        "threads": threads,
        "worker_threads": worker_threads,
        "handles": handles,
        "io_read_bytes": io_read,
        "io_write_bytes": io_write,
        "run": run,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def agent_run_history(limit=12):
    limit = min(50, max(1, int(limit)))
    rows = core.db(
        "SELECT id,started_at,stopped_at,pid,executable,run_mode,exit_reason "
        "FROM agent_runs ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    now = time.time()
    return [{
        "id": row[0], "started_at": row[1], "stopped_at": row[2],
        "pid": row[3], "executable": row[4], "mode": row[5],
        "exit_reason": row[6],
        "duration_s": round(max(0.0, (float(row[2]) if row[2] else now) - float(row[1])), 1),
        "active": row[2] is None,
    } for row in rows]


def request_shutdown():
    """Ask the serving loop to stop from a different thread after replying to HTTP."""
    with _HTTP_SERVER_LOCK:
        server = _HTTP_SERVER
    if server is None:
        return False
    threading.Thread(target=server.shutdown, name="agent-shutdown-request", daemon=True).start()
    return True


def snapshot():
    return {
        "now": time.time(), "uptime": time.time() - START, "live": LIVE, "cores": STATE.get("cores", []),
        "procs": STATE.get("procs", [])[:80], "proc_total": STATE.get("proc_total", 0),
        "proc_recommendations": STATE.get("proc_recommendations", []), "net": STATE.get("net", []),
        "gpu": STATE.get("gpu", {}), "game": STATE.get("game"), "system": STATE.get("system", {}),
        "services": STATE.get("services", {}), "culprits": STATE.get("culprits", []),
        "kernel": STATE.get("kernel", {}),
        "autoruns": STATE.get("autoruns"), "ai": {k: v for k, v in STATE["ai"].items() if k != "transcript"},
        "heart": HEART, "traces": STATE.get("traces", []), "autopilot": CFG["autopilot"],
        "approval_policy": CFG.get("approval_policy", {"auto_approve_reversible_medium": False}),
        "automation_master": core.get_profile()["automation"],
        "agent": agent_runtime(include_threads=False, include_io=False, include_run=False),
        "sensor_matrix": sensor_matrix(),
        "cfg": {"pause": CFG["pause_ai_when_gaming"], "ollama_url": CFG["ollama_url"], "cloud": {k: CFG["cloud"][k] for k in ("enabled", "url", "model")}, "has_key": bool(CFG["cloud"]["key"])},
    }


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers()
        self.wfile.write(b)

    def _authed(self, qs):
        t = self.headers.get("X-Sentinel-Token") or (qs.get("t") or [""])[0]
        expected = str(CFG.get("token") or "")
        return bool(expected and isinstance(t, str) and hmac.compare_digest(t, expected))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query)
        if not u.path.startswith("/api/"):
            name = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            f = os.path.normpath(os.path.join(UI, name))
            try:
                inside_ui = os.path.commonpath([os.path.abspath(UI), os.path.abspath(f)]) == os.path.abspath(UI)
            except ValueError:
                inside_ui = False
            if not inside_ui or not os.path.isfile(f):
                self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
            b = open(f, "rb").read()
            self.send_response(200); self.send_header("Content-Type", MIME.get(os.path.splitext(f)[1], "application/octet-stream"))
            self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(b); return
        if not self._authed(qs):
            return self._json({"error": "unauthorized"}, 401)
        p = u.path
        if p == "/api/maintenance/status":
            try: return self._json(maintenance.status(refresh=(qs.get("refresh") or ["0"])[0] == "1"))
            except Exception as exc: return self._json({"error": f"{type(exc).__name__}: {str(exc)[:240]}"}, 503)
        if p == "/api/maintenance/job":
            try: return self._json(maintenance.job((qs.get("id") or [""])[0]))
            except (ValueError, TypeError) as exc: return self._json({"error": str(exc)}, 404)
        if p == "/api/maintenance/journal":
            try: return self._json(maintenance.journal(min(100, int((qs.get("limit") or ["50"])[0]))))
            except (ValueError, TypeError) as exc: return self._json({"error": str(exc)}, 400)
        if p == "/api/maintenance/digest":
            return self._json(maintenance.daily_digest())
        if p == "/api/snapshot":
            return self._json(snapshot())
        if p == "/api/processes":
            query = (qs.get("q") or [""])[0][:240].casefold()
            limit = min(2000, max(1, int((qs.get("limit") or ["1200"])[0])))
            rows = STATE.get("procs", [])
            if query:
                rows = [row for row in rows if query in " ".join(str(row.get(key) or "") for key in
                    ("name", "pid", "exe", "parent_name", "parent_pid", "username", "app_kind", "status", "path_state", "session_id")).casefold()]
            return self._json({"updated_at": time.time(), "sampled_at": float(STATE.get("proc_scan_at", 0) or 0),
                "total": int(STATE.get("proc_total", len(STATE.get("procs", []))) or 0),
                "matched": len(rows), "rows": rows[:limit],
                "inaccessible": int(STATE.get("proc_inaccessible", 0) or 0),
                "recommendations": STATE.get("proc_recommendations", [])})
        if p == "/api/kernel":
            return self._json({"sources": STATE.get("kernel", {}), "metrics": {key: LIVE.get(key) for key in
                ("dpc", "irq", "pagesin", "pagesout", "pagereads", "pagefaults", "transitionfaults",
                 "availablemb", "committedbytes", "commitlimit", "pagefilepct", "dlat", "dlatxfer", "disk_busy")}})
        if p == "/api/history":
            secs = int((qs.get("secs") or ["300"])[0]); now = time.time()
            return self._json({k: [[round(t - now, 1), round(v, 2)] for t, v in HIST.get(k, []) if now - t <= secs] for k in SPARK_KEYS})
        if p == "/api/events":
            lim = min(2000, int((qs.get("limit") or ["300"])[0])); minid = int((qs.get("after") or ["0"])[0])
            q = (qs.get("q") or [""])[0][:100]; lvl = (qs.get("level") or [""])[0]; src = (qs.get("src") or [""])[0]
            sql, a = "SELECT id,ts,level,src,msg FROM events WHERE id>?", [minid]
            if q: sql += " AND (msg LIKE ? OR src LIKE ?)"; a += [f"%{q}%", f"%{q}%"]
            if lvl: sql += " AND level=?"; a.append(lvl)
            if src: sql += " AND src=?"; a.append(src)
            rows = db(sql + " ORDER BY id DESC LIMIT ?", tuple(a + [lim]))
            return self._json([{"id": r[0], "ts": r[1], "level": r[2], "src": r[3], "msg": r[4]} for r in rows][::-1])
        if p == "/api/agent":
            runtime = agent_runtime(include_threads=True, include_io=True, include_run=True)
            matrix = sensor_matrix()
            runtime["health"] = matrix["status"]
            return self._json({
                "runtime": runtime,
                "sensor_matrix": matrix,
                "runs": agent_run_history(20),
                "storage": {"home": core.HOME, "database": core.DB_PATH},
                "lifecycle": {
                    "agent_run": runtime.get("run"),
                    "workers": len(runtime.get("worker_threads") or []),
                    "monitored_functions": matrix["total"],
                    "health": matrix["status"],
                },
            })
        if p == "/api/status":
            me = psutil.Process()
            n = db("SELECT COUNT(*) FROM events")[0][0]
            srcs = [r[0] for r in db("SELECT DISTINCT src FROM events ORDER BY src")]
            try: posture = inventory.INV.get("posture_summary") or {"count": None, "status": "pending", "unknown_sources": []}
            except Exception: posture = {"count": None, "status": "unavailable", "unknown_sources": ["inventory"]}
            matrix = sensor_matrix()
            runtime = agent_runtime()
            ai_usage = STATE.get("ai", {}).get("usage", {})
            # Keep a compact, integrity-stamped latest snapshot for post-restart diagnosis.
            try:
                core.persist_snapshot("agent.latest", {
                    "captured_at": time.time(), "agent": runtime,
                    "sensor_matrix": matrix, "posture": posture,
                    "ai_usage": ai_usage,
                    "inventory_health": inventory.INV.get("health", {}),
                })
            except Exception as exc:
                log("storage", f"agent status snapshot failed: {type(exc).__name__}", "warn")
            return self._json({"pid": os.getpid(), "uptime": time.time() - START, "events": n, "sources": srcs,
                "rss_mb": round(me.memory_info().rss / 2**20), "threads": me.num_threads(),
                "build": inventory.INV.get("platform", {}).get("build", "-"), "demo": not core.IS_WIN,
                "agent": runtime, "sensor_matrix": matrix, "posture": posture,
                "inventory_health": inventory.INV.get("health", {}), "ai_usage": ai_usage})
        if p == "/api/config/history":
            rows = db("SELECT ts,revision,sha256,changed_keys FROM config_history ORDER BY id DESC LIMIT 100")
            history = []
            for row in rows:
                try: changed = json.loads(row[3])
                except Exception: changed = []
                history.append({"ts": row[0], "revision": row[1], "sha256": row[2], "changed": changed})
            return self._json({"revision": core.config_revision(), "history": history})
        if p == "/api/storage":
            counts = {}
            for table in ("metrics", "metrics_hourly_archive", "events", "insights", "actions", "intel", "settings", "config_history", "ai_messages", "ai_usage_history", "trace_archive",
                          "intel_memories", "intel_memory_revisions", "intel_memory_embeddings", "intel_goals", "intel_goal_steps",
                          "intel_goal_history", "intel_plan_drafts", "intel_plan_history", "intel_observations"):
                try: counts[table] = int(db(f"SELECT COUNT(*) FROM {table}")[0][0])
                except Exception: counts[table] = None
            sqlite_files = [core.DB_PATH, core.DB_PATH + "-wal", core.DB_PATH + "-shm"]
            sqlite_bytes = sum(os.path.getsize(path) for path in sqlite_files if os.path.isfile(path))
            return self._json({"database": core.DB_PATH, "database_exists": os.path.isfile(core.DB_PATH),
                "database_bytes": sqlite_bytes,
                "config_revision": core.config_revision(), "snapshots": core.runtime_snapshot_info(), "rows": counts,
                "note": "SQLite is the durable local source. Events, actions, insights, AI transcripts/usage, settings, memories, goals and trace metadata persist until explicitly deleted. Raw metrics age into permanent hourly aggregates; latest-state snapshots are bounded and keyed."})
        if p == "/api/metrics/archive":
            metric_key = (qs.get("metric") or [""])[0][:64]
            if not metric_key:
                return self._json({"error": "metric is required"}, 400)
            try:
                end_hour = int((qs.get("to") or [str(int(time.time() // 3600))])[0])
                start_raw = (qs.get("from") or [None])[0]
                start_hour = max(0, int(start_raw)) if start_raw is not None else max(0, end_hour - 24 * 30)
                limit = min(2000, max(1, int((qs.get("limit") or ["500"])[0])))
            except (TypeError, ValueError):
                return self._json({"error": "from, to and limit must be integers"}, 400)
            if end_hour < start_hour or end_hour - start_hour > 24 * 366 * 5:
                return self._json({"error": "archive range must be ordered and no longer than five years"}, 400)
            rows = db(
                "SELECT hour_epoch,sample_count,sum_v,min_v,max_v FROM metrics_hourly_archive "
                "WHERE k=? AND hour_epoch BETWEEN ? AND ? ORDER BY hour_epoch DESC LIMIT ?",
                (metric_key, start_hour, end_hour, limit)
            )
            return self._json({"metric": metric_key, "rows": [
                {"hour_epoch": r[0], "samples": r[1], "avg": r[2] / max(1, r[1]), "min": r[3], "max": r[4]}
                for r in rows
            ]})
        if p == "/api/ai/usage":
            rows = db("SELECT ts,model,task,succeeded,duration_s,prompt_tokens,output_tokens,error FROM ai_usage_history ORDER BY id DESC LIMIT 100")
            return self._json([{ "ts": r[0], "model": r[1], "task": r[2], "succeeded": bool(r[3]), "duration_s": r[4],
                "prompt_tokens": r[5], "output_tokens": r[6], "error": r[7]} for r in rows])
        if p == "/api/profile":
            return self._json({"profile": core.get_profile(), "defaults": core.PROFILE_DEFAULTS})
        if p == "/api/inventory":
            return self._json(inventory.summary())
        if p == "/api/catalog":
            k = (qs.get("kind") or ["processes"])[0]
            if k not in ("processes", "apps", "drivers", "services", "tasks", "interfaces", "startup"): return self._json({"error": "bad kind"}, 400)
            return self._json(inventory.catalog(k, (qs.get("q") or [""])[0][:100], min(500, int((qs.get("limit") or ["120"])[0]))))
        if p == "/api/insights":
            rows = db("SELECT id,ts,sev,key,title,detail,culprit FROM insights ORDER BY id DESC LIMIT 60")
            return self._json([dict(zip(("id", "ts", "sev", "key", "title", "detail", "culprit"), r)) for r in rows])
        if p == "/api/actions":
            return self._json(actions.list_actions())
        if p == "/api/engines":
            return self._json({
                "safeguard": safeguard.snapshot(),
                "runtime": runtime_engine.snapshot(),
                "ai": ai_engine.status(),
                "memory": memory_engine.status(),
                "process_intelligence": security_engine.snapshot(30),
                "wpr": {
                    "available": bool(advanced.locate_wpr()),
                    "recorder": "Windows Performance Recorder / GeneralProfile.Light",
                    "optional_xperf": bool(advanced.locate_xperf()),
                    "state": core.STATE.get("kernel", {}).get("etw_engine", {}),
                },
            })
        if p == "/api/process-intelligence":
            return self._json(security_engine.snapshot(min(120, int((qs.get("limit") or ["40"])[0]))))
        if p == "/api/hardware/provider":
            return self._json(hardware_provider.status())
        if p == "/api/activity":
            try:
                return self._json(activity_engine.snapshot())
            except Exception as exc:
                log("activity", f"activity snapshot failed: {type(exc).__name__}: {str(exc)[:180]}", "error")
                return self._json({"error": f"{type(exc).__name__}: {str(exc)[:180]}"}, 503)
        if p == "/api/advanced":
            try:
                payload = advanced.status()
                payload["hardware_provider"] = hardware_provider.status()
                return self._json(payload)
            except Exception as exc:
                log("advanced", f"performance status payload failed: {type(exc).__name__}: {str(exc)[:260]}", "error")
                return self._json({
                    "error": f"Performance telemetry could not be assembled: {type(exc).__name__}: {str(exc)[:220]}",
                    "code": "advanced_status_failed",
                }, 503)
        if p == "/api/advanced/journal":
            return self._json(advanced.list_journal(min(500, int((qs.get("limit") or ["100"])[0]))))
        if p == "/api/intel":
            return self._json(intel.recent())
        if p == "/api/ai":
            return self._json({**{k: v for k, v in STATE["ai"].items()}})
        if p == "/api/intelligence/context":
            return self._json(intelligence.environment_context())
        if p == "/api/intelligence/state":
            return self._json(intelligence.STORE.environment_state(limit=min(500, int((qs.get("limit") or ["100"])[0])), half_life_hours=float((qs.get("half_life") or ["24"])[0])))
        if p == "/api/intelligence/observations":
            ids = (qs.get("ids") or [""])[0]
            if ids:
                try: return self._json(intelligence.STORE.observations_by_ids(ids.split(",")))
                except ValueError as e: return self._json({"error": str(e)}, 400)
            return self._json(intelligence.STORE.recent_observations(min(500, int((qs.get("limit") or ["100"])[0]))))
        if p == "/api/intelligence/runtime":
            try: return self._json(intelligence.model_recommendations())
            except (ValueError, RuntimeError) as e: return self._json({"error": str(e)}, 503)
        if p == "/api/intelligence/memories":
            return self._json(intelligence.STORE.memory_search((qs.get("q") or [""])[0][:1000], include_sensitive=(qs.get("include_sensitive") or ["0"])[0] == "1", limit=min(100, int((qs.get("limit") or ["20"])[0]))))
        if p == "/api/intelligence/memory/history":
            return self._json(intelligence.STORE.memory_history((qs.get("id") or [""])[0], min(100, int((qs.get("limit") or ["20"])[0]))))
        if p == "/api/intelligence/memory/semantic":
            try: return self._json(intelligence.STORE.memory_semantic_search((qs.get("q") or [""])[0], limit=min(100, int((qs.get("limit") or ["20"])[0]))))
            except (ValueError, RuntimeError) as e: return self._json({"error": str(e)}, 503)
        if p == "/api/intelligence/goals":
            return self._json(intelligence.STORE.goal_list((qs.get("status") or [None])[0]))
        if p == "/api/intelligence/goal/history":
            try: return self._json(intelligence.STORE.goal_history((qs.get("id") or [""])[0], min(500, int((qs.get("limit") or ["100"])[0]))))
            except (ValueError, TypeError) as e: return self._json({"error": str(e)}, 400)
        if p == "/api/intelligence/goal/plan-drafts":
            return self._json(intelligence.STORE.plan_draft_list((qs.get("goal_id") or [""])[0], (qs.get("status") or [None])[0]))
        if p == "/api/stream":
            return self._sse()
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query)
        if not self._authed(qs):
            return self._json({"error": "unauthorized"}, 401)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return self._json({"error": "invalid Content-Length"}, 400)
        if n < 0 or n > 65536:
            return self._json({"error": "request body must not exceed 64 KiB"}, 413)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, UnicodeDecodeError):
            return self._json({"error": "request body must be valid JSON"}, 400)
        if not isinstance(body, dict):
            return self._json({"error": "request body must be a JSON object"}, 400)
        p = u.path
        if p == "/api/maintenance/preview":
            try:
                action = str(body.get("action") or "")
                args = body.get("args") if isinstance(body.get("args"), dict) else {}
                return self._json(maintenance.preview_action(action, args), 201)
            except PermissionError as exc: return self._json({"error": str(exc)}, 403)
            except (ValueError, TypeError) as exc: return self._json({"error": str(exc)}, 400)
            except Exception as exc: return self._json({"error": f"{type(exc).__name__}: {str(exc)[:260]}"}, 409)
        if p == "/api/maintenance/execute":
            try:
                return self._json(maintenance.execute_preview(str(body.get("preview_token") or ""),
                                                               confirmed=body.get("confirmed") is True), 202)
            except PermissionError as exc: return self._json({"error": str(exc)}, 403)
            except (ValueError, TypeError) as exc: return self._json({"error": str(exc)}, 400)
            except Exception as exc: return self._json({"error": f"{type(exc).__name__}: {str(exc)[:260]}"}, 409)
        if p == "/api/maintenance/undo":
            try: return self._json(maintenance.undo(int(body.get("journal_id", 0)), confirmed=body.get("confirmed") is True))
            except PermissionError as exc: return self._json({"error": str(exc)}, 403)
            except (ValueError, TypeError) as exc: return self._json({"error": str(exc)}, 400)
            except Exception as exc: return self._json({"error": f"{type(exc).__name__}: {str(exc)[:260]}"}, 409)
        if p == "/api/maintenance/policy":
            try: return self._json(maintenance.update_policy(body))
            except PermissionError as exc: return self._json({"error": str(exc)}, 403)
            except (ValueError, TypeError) as exc: return self._json({"error": str(exc)}, 400)
        if p == "/api/maintenance/goal":
            try: return self._json(maintenance.goal_plan(str(body.get("goal") or "")))
            except (ValueError, TypeError) as exc: return self._json({"error": str(exc)}, 400)
        if p == "/api/hardware/provider/start":
            try:
                result = hardware_provider.install_and_start()
                if result.get("installed"):
                    settings = CFG.setdefault("advanced", {})
                    settings["lhm_enabled"] = True
                    settings["lhm_http_port"] = int(result.get("port") or 8085)
                    save_cfg(CFG)
                STATE["hardware_provider"] = hardware_provider.status()
                log("hardware-provider", result.get("message", "LibreHardwareMonitor start requested"),
                    "ok" if result.get("connected") else "warn",
                    version=result.get("version"), connected=bool(result.get("connected")),
                    sensor_count=int(result.get("sensor_count") or 0))
                return self._json({**result, "provider": STATE["hardware_provider"]},
                                  200 if result.get("connected") else 202)
            except PermissionError as exc:
                return self._json({"error": str(exc)}, 403)
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
            except Exception as exc:
                log("hardware-provider", f"provider installation/start failed: {type(exc).__name__}: {str(exc)[:200]}", "error")
                return self._json({"error": f"{type(exc).__name__}: {str(exc)[:220]}"}, 503)
        if p == "/api/process-intelligence/inspect":
            try:
                result = security_engine.inspect_process(
                    int(body.get("pid", 0)),
                    float(body.get("create_time", 0)),
                    str(body.get("exe") or ""),
                    str(body.get("operation") or ""),
                )
                log("process-security", f"user requested {result['operation']} inspection for PID {result['pid']}",
                    "info", executable=result["executable"])
                return self._json({"ok": True, **result})
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
            except PermissionError as exc:
                return self._json({"error": str(exc)}, 409)
            except Exception as exc:
                log("process-security", f"process inspection failed: {type(exc).__name__}: {str(exc)[:180]}", "warn")
                return self._json({"error": f"{type(exc).__name__}: {str(exc)[:200]}"}, 503)
        if p == "/api/engines/memory/trim":
            result = memory_engine.clear_working_cache()
            log("memory", f"cleared {result['cleared']} volatile retrieval cache entries; durable memory unchanged", "info")
            return self._json({"ok": True, **result})
        if p == "/api/engines/runtime/rebalance":
            policy = runtime_engine.evaluate()
            policy["updated_at"] = time.time()
            core.STATE["runtime_engine"] = policy
            return self._json({"ok": True, "runtime": policy})
        if p == "/api/agent/shutdown":
            if body.get("confirmed") is not True:
                return self._json({"error": "explicit confirmation is required to stop the SENTINEL agent"}, 400)
            accepted = request_shutdown()
            return self._json({"ok": accepted, "message": "SENTINEL is shutting down gracefully" if accepted else "agent server is not active"}, 202 if accepted else 409)
        if p == "/api/action/run":
            confirmed = body.get("confirmed") is True
            return self._json({"result": actions.execute(int(body.get("id", 0)), user_confirmed=confirmed)})
        if p == "/api/action/dismiss":
            actions.dismiss(int(body.get("id", 0))); return self._json({"ok": True})
        if p == "/api/action/propose":
            kind = str(body.get("kind", ""))
            args = body.get("args") if isinstance(body.get("args"), dict) else {}
            if body.get("dry_run") is True:
                try: return self._json(advanced.action_preview(kind, args))
                except (ValueError, TypeError) as exc: return self._json({"error": str(exc)}, 400)
            if kind == "terminate_process":
                try:
                    pid, created, exe = int(args.get("pid")), float(args.get("create_time")), str(args.get("exe") or "")
                    current = find_reviewable_process(pid, created, exe, STATE.get("procs", []))
                    if not current:
                        return self._json({"error": "process must be the same live process instance, in the interactive session, with a visible window and a verified executable path"}, 409)
                    args = {"pid": pid, "create_time": created, "exe": exe}
                except (TypeError, ValueError):
                    return self._json({"error": "valid pid, creation time and executable path are required"}, 400)
            aid = actions.propose(kind, args, origin="user", reason=str(body.get("reason", "manual review"))[:240])
            if aid is None: return self._json({"error": "action is not allowlisted"}, 400)
            return self._json({"id": aid, "requires_confirmation": kind == "terminate_process"}, 201)
        if p == "/api/advanced/dry-run":
            try:
                return self._json(advanced.action_preview(str(body.get("kind", "")), body.get("args") if isinstance(body.get("args"), dict) else {}))
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
        if p == "/api/advanced/undo":
            try: return self._json(advanced.undo_action(int(body.get("action_id", 0))))
            except (TypeError, ValueError) as exc: return self._json({"error": str(exc)}, 400)
        if p == "/api/advanced/revert-all":
            if body.get("confirmed") is not True:
                return self._json({"error": "explicit confirmation is required to revert every outstanding SENTINEL change"}, 400)
            return self._json(advanced.revert_all())
        if p == "/api/activity/settings":
            try:
                result = activity_engine.update_settings(body)
                log("activity", "foreground activity policy updated", "info",
                    semantic_context=result["settings"]["semantic_context"],
                    suggestions_enabled=result["settings"]["suggestions_enabled"],
                    auto_launch=result["settings"]["auto_launch_learned_apps"])
                return self._json(result)
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
        if p == "/api/activity/launch":
            try:
                result = activity_engine.launch_app(str(body.get("app_key", "")))
                return self._json(result, 200 if result.get("ok") else 409)
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
        if p == "/api/advanced/settings":
            try: return self._json(advanced.settings_update(body))
            except (ValueError, TypeError) as exc: return self._json({"error": str(exc)}, 400)
        if p == "/api/advanced/game-profile/save":
            try: return self._json(advanced.save_game_profile(str(body.get("game", "")), body.get("profile") if isinstance(body.get("profile"), dict) else {}))
            except (ValueError, TypeError) as exc: return self._json({"error": str(exc)}, 400)
        if p == "/api/advanced/game-profile/propose-current":
            game = STATE.get("game") if isinstance(STATE.get("game"), dict) else None
            if not game: return self._json({"error": "no active game process was detected"}, 409)
            profile = advanced.get_game_profile(str(game.get("name") or ""))
            if not profile: return self._json({"error": "no saved profile exists for the active game"}, 404)
            aid = actions.propose("game_profile_apply", {"pid": game.get("pid"), "create_time": game.get("create_time"), "exe": game.get("exe"), "profile": profile}, origin="profile-tuner", reason="Operator requested the saved profile for the active game")
            if not aid: return self._json({"error": "risk policy refused this profile action"}, 409)
            return self._json({"id": aid, "risk": "medium", "requires_confirmation": True}, 201)
        if p == "/api/advanced/tuner/start":
            try:
                result = advanced.start_tuner_experiment(str(body.get("kind", "")), body.get("args") if isinstance(body.get("args"), dict) else {}, str(body.get("metric", "")), str(body.get("direction", "lower")))
                return self._json(result, 201)
            except (ValueError, TypeError, RuntimeError) as exc:
                return self._json({"error": str(exc)}, 400)
        if p == "/api/advanced/propose-wifi":
            if not core.STATE.get("advanced", {}).get("active_session_id"):
                return self._json({"error": "Wi-Fi tuning is scoped to an active tracked game session"}, 409)
            evidence = advanced._check_network_evidence()
            if not evidence.get("candidate"):
                return self._json({"error": "no persistent ping/jitter elevation; Wi-Fi tuning was not proposed", "evidence": evidence}, 409)
            if not advanced.wifi_connected():
                return self._json({"error": "no active Wi-Fi adapter detected; no network tuning proposed", "evidence": evidence}, 409)
            aid = actions.propose("wifi_max_performance", {}, origin="network-evidence", reason=f"Measured ping {evidence.get('ping_mean_ms')} ms / jitter {evidence.get('jitter_mean_ms')} ms; approval required")
            if not aid: return self._json({"error": "risk policy refused Wi-Fi adjustment"}, 409)
            return self._json({"id": aid, "risk": "medium", "requires_confirmation": True, "evidence": evidence}, 201)
        if p == "/api/advanced/propose-updater":
            if not core.STATE.get("advanced", {}).get("active_session_id"):
                return self._json({"error": "Updater pausing is scoped to an active tracked game session"}, 409)
            service = str(body.get("service", "")).casefold()
            if service not in advanced.UPDATER_SERVICES:
                return self._json({"error": "service is not on the explicit third-party updater allowlist"}, 400)
            aid = actions.propose("pause_updater_service", {"service": service}, origin="user", reason="Pause allowlisted updater during a game; operator approval required")
            if not aid: return self._json({"error": "risk policy refused updater action"}, 409)
            return self._json({"id": aid, "risk": "medium", "requires_confirmation": True}, 201)
        if p == "/api/advanced/propose-etw":
            try:
                duration = max(5, min(15, int(body.get("duration", 12))))
            except (TypeError, ValueError):
                return self._json({"error": "WPR capture duration must be an integer between 5 and 15 seconds"}, 400)
            preview = advanced.action_preview("etw_capture", {"duration": duration})
            if not preview.get("supported"):
                warnings = preview.get("warnings") or []
                detail = "; ".join(str(item) for item in warnings if item)
                guard = preview.get("safeguard") or {}
                code = guard.get("code") or ("wpr_unavailable" if not advanced.locate_wpr() else "wpr_policy_refused")
                return self._json({
                    "error": "WPR capture unavailable: " + (detail or "The current safeguard or Windows environment does not permit this capture."),
                    "code": code,
                    "requirement": "Windows Performance Recorder (wpr.exe); Xperf is optional",
                    "risk": preview.get("risk", "safe"),
                }, 409)
            aid = actions.propose(
                "etw_capture", {"duration": duration}, origin="user",
                reason="Operator requested a bounded inbox WPR ETW diagnostic sample",
            )
            if not aid:
                return self._json({"error": "SENTINEL policy refused the WPR proposal.", "code": "wpr_policy_refused"}, 409)
            return self._json({
                "id": aid, "risk": "safe", "requires_confirmation": False,
                "duration": duration, "source": "Windows Performance Recorder / GeneralProfile.Light",
                "xperf_optional": bool(advanced.locate_xperf()),
            }, 201)
        if p == "/api/inventory/refresh":
            try:
                data = inventory.scan()
                log("inventory", "user requested a manual system inventory refresh", "ok", duration_s=data.get("duration_s"))
                return self._json(inventory.summary())
            except Exception as exc:
                log("inventory", f"manual inventory refresh failed: {type(exc).__name__}: {str(exc)[:180]}", "error")
                return self._json({"error": f"{type(exc).__name__}: {str(exc)[:200]}"}, 503)
        if p == "/api/chat":
            def work():
                try:
                    out = ai.chat(str(body.get("msg", ""))[:2000], str(body.get("mode", "council")))
                except Exception as e:
                    out = f"AI error: {e!r}"
                    log("ai", out, "error")
            threading.Thread(target=work, daemon=True).start()
            return self._json({"ok": True})
        if p == "/api/config":
            try:
                if not isinstance(body, dict): raise ValueError("settings payload must be an object")
                for key in ("pause_ai_when_gaming", "ai_enabled"):
                    if key in body and not isinstance(body[key], bool): raise ValueError(f"{key} must be a boolean")
                if "ollama_url" in body:
                    raw_url = body["ollama_url"]
                    if not core.valid_local_ollama_url(raw_url):
                        raise ValueError("Ollama must be a direct loopback origin without credentials, path, query or fragment; cloud inference has a separate explicit setting")
                    CFG["ollama_url"] = raw_url.strip().rstrip("/")
                for key in ("model_fast", "model_deep"):
                    if key in body:
                        if not isinstance(body[key], str) or len(body[key]) > 160: raise ValueError(f"{key} must be a string under 160 characters")
                        CFG[key] = body[key]
                if "ai_enabled" in body: CFG["ai_enabled"] = body["ai_enabled"]
                if "pause_ai_when_gaming" in body: CFG["pause_ai_when_gaming"] = body["pause_ai_when_gaming"]
                cloud = body.get("cloud")
                if cloud is not None:
                    if not isinstance(cloud, dict): raise ValueError("cloud settings must be an object")
                    if "enabled" in cloud and not isinstance(cloud["enabled"], bool): raise ValueError("cloud.enabled must be a boolean")
                    for key in ("url", "model", "key"):
                        if key in cloud:
                            if not isinstance(cloud[key], str) or len(cloud[key]) > 4000: raise ValueError(f"cloud.{key} must be a string under 4000 characters")
                            if not (key == "key" and not cloud[key]): CFG["cloud"][key] = cloud[key]
                    if "enabled" in cloud: CFG["cloud"]["enabled"] = cloud["enabled"]
                autopilot = body.get("autopilot")
                if autopilot is not None:
                    if not isinstance(autopilot, dict): raise ValueError("autopilot settings must be an object")
                    for key, value in autopilot.items():
                        if key not in CFG["autopilot"]: raise ValueError(f"unknown autopilot setting: {key}")
                        if not isinstance(value, bool): raise ValueError(f"autopilot.{key} must be a boolean")
                        CFG["autopilot"][key] = value
                approval_policy = body.get("approval_policy")
                if approval_policy is not None:
                    if not isinstance(approval_policy, dict): raise ValueError("approval_policy settings must be an object")
                    allowed_policy_keys = {"auto_approve_reversible_medium"}
                    for key, value in approval_policy.items():
                        if key not in allowed_policy_keys: raise ValueError(f"unknown approval policy setting: {key}")
                        if not isinstance(value, bool): raise ValueError(f"approval_policy.{key} must be a boolean")
                        CFG.setdefault("approval_policy", {})[key] = value
                save_cfg(CFG)
                ai.refresh_models()
                revision = core.config_revision()
                log("config", "settings updated from UI and persisted to SQLite", "info", revision=revision["revision"])
                return self._json({"ok": True, "persisted": "sqlite", "revision": revision,
                    "model_refresh": STATE.get("ai", {}).get("online", False)})
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
        if p == "/api/profile":
            try:
                ch = core.set_profile(body.get("profile") or {})
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            log("config", "feature profile saved to SQLite: " + (", ".join(ch) if ch else "no changes"), "info")
            return self._json({"ok": True, "changed": ch, "profile": core.get_profile(), "persisted": "sqlite"})
        if p == "/api/intel/search":
            q = str(body.get("q", ""))[:140]
            threading.Thread(target=lambda: intel.lookup(q, True), daemon=True).start()
            return self._json({"ok": True})
        if p == "/api/intelligence/memory/add":
            try:
                item = intelligence.STORE.memory_add(str(body.get("content", "")), kind=body.get("kind", "episodic"), sensitivity=body.get("sensitivity", "internal"), verification=body.get("verification", "unverified"), confidence=body.get("confidence", .5), tags=body.get("tags"), provenance=body.get("provenance"), ttl_days=body.get("ttl_days"))
                log("intelligence", "user added an explicit local memory", "ok", memory_id=item["id"])
                return self._json(item, 201)
            except (ValueError, TypeError) as e: return self._json({"error": str(e)}, 400)
        if p == "/api/intelligence/memory/delete":
            return self._json({"deleted": intelligence.STORE.memory_delete(str(body.get("id", "")))})
        if p == "/api/intelligence/memory/revise":
            try: return self._json(intelligence.STORE.memory_revise(str(body.get("id", "")), body.get("content"), verification=body.get("verification"), confidence=body.get("confidence"), tags=body.get("tags")))
            except (ValueError, TypeError) as e: return self._json({"error": str(e)}, 400)
        if p == "/api/intelligence/memory/index":
            try: return self._json(intelligence.STORE.memory_index(body.get("model"), min(500, int(body.get("limit", 100)))))
            except (ValueError, RuntimeError) as e: return self._json({"error": str(e)}, 503)
        if p == "/api/intelligence/goal/create":
            try: return self._json(intelligence.STORE.goal_create(str(body.get("title", "")), str(body.get("description", ""))), 201)
            except (ValueError, TypeError) as e: return self._json({"error": str(e)}, 400)
        if p == "/api/intelligence/goal/step/add":
            try: return self._json(intelligence.STORE.goal_add_step(str(body.get("goal_id", "")), str(body.get("title", "")), str(body.get("description", "")), body.get("dependencies")))
            except (ValueError, TypeError) as e: return self._json({"error": str(e)}, 400)
        if p == "/api/intelligence/goal/step/status":
            try: return self._json(intelligence.STORE.goal_step_status(str(body.get("goal_id", "")), str(body.get("step_id", "")), str(body.get("status", ""))))
            except (ValueError, TypeError) as e: return self._json({"error": str(e)}, 400)
        if p == "/api/intelligence/goal/status":
            try: return self._json(intelligence.STORE.goal_set_status(str(body.get("goal_id", "")), str(body.get("status", ""))))
            except (ValueError, TypeError) as e: return self._json({"error": str(e)}, 400)
        if p == "/api/intelligence/goal/suggest-plan":
            try:
                draft = intelligence.suggest_goal_plan(str(body.get("goal_id", "")))
                log("intelligence", "local model created a plan draft for user review", "ok", draft_id=draft["id"], goal_id=draft["goal_id"])
                return self._json(draft, 201)
            except (ValueError, RuntimeError) as e: return self._json({"error": str(e)}, 503)
        if p == "/api/intelligence/goal/plan-draft/resolve":
            try:
                result = intelligence.STORE.resolve_plan_draft(str(body.get("draft_id", "")), str(body.get("decision", "")))
                log("intelligence", "goal plan draft " + str(body.get("decision", "reviewed")), "ok", draft_id=body.get("draft_id"), goal_id=result["goal"]["id"])
                return self._json(result)
            except (ValueError, TypeError) as e: return self._json({"error": str(e)}, 400)
        if p == "/api/intelligence/uia/inspect":
            try:
                from .uia import inspect_windows
                result = inspect_windows(max_windows=min(40, int(body.get("max_windows", 12))), max_nodes=min(1000, int(body.get("max_nodes", 250))), max_depth=min(8, int(body.get("max_depth", 5))), timeout=min(30, float(body.get("timeout", 12))))
                log("intelligence", "read-only UI Automation structure inspection completed" if result.available else "read-only UI Automation inspection unavailable", "ok" if result.available else "warn", nodes=result.nodes_inspected, truncated=result.truncated)
                return self._json({"available": result.available, "reason": result.reason, "windows": result.windows, "nodes_inspected": result.nodes_inspected, "truncated": result.truncated, "text_values_collected": False, "password_values_collected": False})
            except (ValueError, TypeError) as e: return self._json({"error": str(e)}, 400)
        self._json({"error": "not found"}, 404)

    def _sse(self):
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store"); self.send_header("Connection", "keep-alive"); self.end_headers()
        q = core.subscribe(); last = 0
        try:
            while True:
                try:
                    m = q.get(timeout=1)
                    self.wfile.write(f"data: {m}\n\n".encode()); self.wfile.flush()
                except Exception as e:
                    if isinstance(e, (BrokenPipeError, ConnectionError, OSError)):
                        break
                if time.time() - last >= 1:
                    last = time.time()
                    self.wfile.write(f"data: {json.dumps({'t': 'tick', 'd': snapshot()}, separators=(',', ':'))}\n\n".encode())
                    self.wfile.flush()
        except Exception:
            pass
        finally:
            core.unsubscribe(q)


def serve():
    global _HTTP_SERVER
    srv = ThreadingHTTPServer(("127.0.0.1", CFG["port"]), H)
    srv.daemon_threads = True
    with _HTTP_SERVER_LOCK:
        _HTTP_SERVER = srv
    log("server", f"HUD online at http://127.0.0.1:{CFG['port']}", "ok")
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        with _HTTP_SERVER_LOCK:
            if _HTTP_SERVER is srv:
                _HTTP_SERVER = None
