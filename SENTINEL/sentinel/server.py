"""HTTP + Server-Sent-Events API. Binds 127.0.0.1 only; every /api call needs the install token."""
import json, os, threading, time, urllib.parse, psutil, platform, sys, hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import core, actions, ai, intel, inventory, intelligence
from .core import CFG, STATE, LIVE, HIST, HEART, START, db, log, save_cfg

UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml"}
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


def agent_runtime():
    process = psutil.Process(os.getpid())
    try: executable = process.exe()
    except Exception: executable = sys.executable
    try: username = process.username()
    except Exception: username = "unavailable"
    try: rss = round(process.memory_info().rss / 2**20, 1)
    except Exception: rss = None
    try: memory_pct = round(process.memory_percent(), 2)
    except Exception: memory_pct = None
    try: cpu_pct = round(process.cpu_percent(interval=None), 2)
    except Exception: cpu_pct = None
    try: threads = process.num_threads()
    except Exception: threads = None
    try: handles = process.num_handles() if core.IS_WIN else None
    except Exception: handles = None
    try:
        io = process.io_counters()
        io_read, io_write = int(io.read_bytes), int(io.write_bytes)
    except Exception:
        io_read = io_write = None
    try:
        from .collectors import _session_id
        session_id = _session_id(os.getpid())
    except Exception:
        session_id = None
    return {"pid": os.getpid(), "parent_pid": os.getppid(), "executable": executable,
        "username": username, "session_id": session_id,
        "execution_context": "interactive Windows session" if core.IS_WIN and session_id not in (None, 0) else ("Session 0 / non-interactive" if core.IS_WIN else "non-Windows / demo"),
        "desktop_access_expected": bool(core.IS_WIN and session_id not in (None, 0)),
        "uptime_s": round(time.time() - START, 1), "cpu_percent": cpu_pct,
        "rss_mb": rss, "memory_percent": memory_pct, "threads": threads, "handles": handles,
        "io_read_bytes": io_read, "io_write_bytes": io_write,
        "run": (lambda rows: ({"id": rows[0][0], "started_at": rows[0][1], "mode": rows[0][2],
            "exit_reason": rows[0][3]} if rows else None))(core.db("SELECT id,started_at,run_mode,exit_reason FROM agent_runs ORDER BY id DESC LIMIT 1")),
        "python": platform.python_version(), "platform": platform.platform()}


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
        if p == "/api/snapshot":
            return self._json(snapshot())
        if p == "/api/processes":
            query = (qs.get("q") or [""])[0][:240].casefold()
            limit = min(2000, max(1, int((qs.get("limit") or ["1200"])[0])))
            rows = STATE.get("procs", [])
            if query:
                rows = [row for row in rows if query in " ".join(str(row.get(key) or "") for key in
                    ("name", "pid", "exe", "parent_name", "parent_pid", "username", "app_kind", "status", "path_state", "session_id")).casefold()]
            return self._json({"updated_at": time.time(), "total": int(STATE.get("proc_total", len(STATE.get("procs", []))) or 0),
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
        if p == "/api/action/run":
            confirmed = body.get("confirmed") is True
            return self._json({"result": actions.execute(int(body.get("id", 0)), user_confirmed=confirmed)})
        if p == "/api/action/dismiss":
            actions.dismiss(int(body.get("id", 0))); return self._json({"ok": True})
        if p == "/api/action/propose":
            kind = str(body.get("kind", ""))
            args = body.get("args") if isinstance(body.get("args"), dict) else {}
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
    srv = ThreadingHTTPServer(("127.0.0.1", CFG["port"]), H)
    srv.daemon_threads = True
    log("server", f"HUD online at http://127.0.0.1:{CFG['port']}", "ok")
    srv.serve_forever()