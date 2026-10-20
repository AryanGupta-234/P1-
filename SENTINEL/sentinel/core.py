"""Sentinel core: config, SQLite store, event bus, heartbeat registry."""
import copy, json, os, secrets, sqlite3, threading, time, queue, sys, math
from urllib.parse import urlparse

IS_WIN = os.name == "nt"
# SENTINEL_HOME is selected by the launcher for isolated modes (notably --demo).
# Normal installed Windows runs continue to use the secured ProgramData store.
_HOME_OVERRIDE = os.environ.get("SENTINEL_HOME", "").strip()
if _HOME_OVERRIDE:
    HOME = os.path.abspath(os.path.expandvars(os.path.expanduser(_HOME_OVERRIDE)))
elif IS_WIN:
    HOME = os.path.join(os.environ.get("ProgramData", os.path.expanduser("~")), "Sentinel")
else:
    HOME = os.path.expanduser("~/.sentinel")
os.makedirs(HOME, exist_ok=True)
CFG_PATH = os.path.join(HOME, "config.json")
DB_PATH = os.path.join(HOME, "sentinel.db")
TRACE_DIR = os.path.join(HOME, "traces")
os.makedirs(TRACE_DIR, exist_ok=True)

DEFAULTS = {
    "port": 8765,
    "token": "",
    "game_processes": ["VALORANT-Win64-Shipping.exe"],
    "ollama_url": "http://127.0.0.1:11434",
    "model_fast": "",      # empty = auto-pick smallest installed model
    "model_deep": "",      # empty = auto-pick largest installed model
    "ai_enabled": True,
    "pause_ai_when_gaming": True,   # local models sleep while a game runs (they would steal GPU/CPU)
    "cloud": {                      # optional free cloud DEEP model (OpenAI-compatible: Groq, Cerebras, OpenRouter, GitHub Models)
        "enabled": False, "url": "https://api.groq.com/openai/v1", "key": "", "model": "llama-3.3-70b-versatile",
    },
    "autopilot": {          # explicit opt-in per action; safe defaults require approval
        "bg_priority": False,
        "flush_dns": False,
        "power_plan": False,
        "wpr_trace": False,
        "etw_capture": False,
    },
    "retention_days": 14,
    "advanced": {
        "etw_enabled": False, "lhm_enabled": False, "cpu_temp_warn_c": 88.0,
        "gpu_temp_warn_c": 82.0, "auto_report_sessions": True,
    },
}


def valid_local_ollama_url(value):
    """Accept only a direct loopback Ollama origin; never trust proxy/DNS URLs."""
    if not isinstance(value, str) or len(value) > 300:
        return False
    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme in ("http", "https")
        and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        and parsed.username is None and parsed.password is None
        and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
        and (port is None or 1 <= port <= 65535)
    )




_DPAPI_PREFIX = "dpapi:v1:"

def _dpapi_transform(raw: bytes, *, protect: bool) -> bytes:
    """Use the current Windows user's DPAPI profile for small secret values."""
    if not IS_WIN:
        raise RuntimeError("Windows DPAPI is not available on this platform")
    import base64  # kept local: non-Windows/demo runs do not need this code path
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    source_buffer = ctypes.create_string_buffer(raw)
    source = DATA_BLOB(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = DATA_BLOB()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if protect:
        fn = crypt32.CryptProtectData
        fn.argtypes = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        fn.restype = wintypes.BOOL
        ok = fn(ctypes.byref(source), "SENTINEL cloud inference key", None, None, None, flags, ctypes.byref(target))
    else:
        description = wintypes.LPWSTR()
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB),
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        fn.restype = wintypes.BOOL
        ok = fn(ctypes.byref(source), ctypes.byref(description), None, None, None, flags, ctypes.byref(target))
    if not ok:
        raise OSError(ctypes.get_last_error(), "Windows DPAPI operation failed")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        if target.pbData:
            kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))
        if not protect and 'description' in locals() and description:
            kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))


def _config_for_storage(cfg):
    """Copy config and protect cloud credentials before either durable write."""
    stored = copy.deepcopy(cfg)
    cloud = stored.get("cloud")
    if isinstance(cloud, dict) and cloud.get("key"):
        if IS_WIN:
            try:
                cipher = _dpapi_transform(str(cloud["key"]).encode("utf-8"), protect=True)
                cloud["key"] = _DPAPI_PREFIX + __import__("base64").b64encode(cipher).decode("ascii")
            except Exception as exc:
                # Never fall back to plaintext if the current user profile cannot protect it.
                cloud["key"] = ""
                try: log("security", f"cloud key not persisted: DPAPI unavailable ({type(exc).__name__})", "error")
                except Exception: pass
        # Non-Windows/demo mode retains its existing local-only config behavior.
    return stored


def _config_from_storage(cfg):
    """Decrypt current-user DPAPI values; migrate legacy plaintext on next save."""
    restored = copy.deepcopy(cfg)
    cloud = restored.get("cloud")
    if isinstance(cloud, dict) and isinstance(cloud.get("key"), str) and cloud["key"].startswith(_DPAPI_PREFIX):
        try:
            import base64
            encoded = cloud["key"][len(_DPAPI_PREFIX):]
            cloud["key"] = _dpapi_transform(base64.b64decode(encoded, validate=True), protect=False).decode("utf-8")
        except Exception:
            cloud["key"] = ""
    return restored


def load_cfg():
    """Load settings with a recursive defaults merge and fail-safe type handling."""
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            loaded = _config_from_storage(loaded)
            def merge(base, incoming):
                for key, value in incoming.items():
                    if isinstance(value, dict) and isinstance(base.get(key), dict):
                        merge(base[key], value)
                    else:
                        base[key] = value
            merge(cfg, loaded)
    except (OSError, ValueError, TypeError):
        pass
    if not valid_local_ollama_url(cfg.get("ollama_url")):
        # Legacy or tampered config must never redirect local prompts to a remote host.
        cfg["ollama_url"] = DEFAULTS["ollama_url"]
    else:
        cfg["ollama_url"] = cfg["ollama_url"].strip().rstrip("/")
    if not isinstance(cfg.get("token"), str) or not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(18)
    # Invalid stored automation flags must never become truthy by string coercion.
    if not isinstance(cfg.get("ai_enabled"), bool): cfg["ai_enabled"] = DEFAULTS["ai_enabled"]
    if not isinstance(cfg.get("pause_ai_when_gaming"), bool): cfg["pause_ai_when_gaming"] = DEFAULTS["pause_ai_when_gaming"]
    if not isinstance(cfg.get("autopilot"), dict): cfg["autopilot"] = copy.deepcopy(DEFAULTS["autopilot"])
    else:
        for key, default in DEFAULTS["autopilot"].items():
            if not isinstance(cfg["autopilot"].get(key), bool): cfg["autopilot"][key] = default
    if not isinstance(cfg.get("advanced"), dict): cfg["advanced"] = copy.deepcopy(DEFAULTS["advanced"])
    else:
        for key, default in DEFAULTS["advanced"].items():
            value = cfg["advanced"].get(key, default)
            if isinstance(default, bool):
                cfg["advanced"][key] = value if isinstance(value, bool) else default
            else:
                try:
                    number = float(value)
                    cfg["advanced"][key] = max(50.0, min(110.0, number)) if math.isfinite(number) else default
                except (TypeError, ValueError, OverflowError):
                    cfg["advanced"][key] = default
    save_cfg(cfg)
    return cfg


def save_cfg(cfg):
    """Persist settings in SQLite and a protected JSON recovery mirror.

    The cloud API key is DPAPI-protected on Windows. Change history compares
    restored values so randomized ciphertext does not create fake revisions.
    """
    plain_payload = json.dumps(cfg, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    stored_cfg = _config_for_storage(cfg)
    payload = json.dumps(stored_cfg, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(stored_cfg, f, indent=2, ensure_ascii=False)
        if IS_WIN:
            try: os.chmod(CFG_PATH, 0o600)
            except OSError: pass
    except Exception as exc:
        # The database remains the primary durable copy once initialized.
        if "_db" not in globals():
            return
        log("config", f"settings JSON mirror failed: {type(exc).__name__}", "warn")
    if "_db" in globals():
        try:
            digest = __import__("hashlib").sha256(plain_payload.encode("utf-8")).hexdigest()
            with _db_lock:
                row = _db.execute("SELECT value_json, revision FROM settings WHERE setting_key='config'").fetchone()
                revision = (int(row[1]) + 1) if row else 1
                try:
                    previous_stored = json.loads(row[0]) if row else {}
                    previous = _config_from_storage(previous_stored) if isinstance(previous_stored, dict) else {}
                except Exception:
                    previous = {}
                def changed_paths(before, after, prefix=""):
                    if isinstance(before, dict) and isinstance(after, dict):
                        paths = []
                        for child in sorted(set(before) | set(after)):
                            name = f"{prefix}.{child}" if prefix else str(child)
                            if child not in before or child not in after:
                                paths.append(name)
                            else:
                                paths.extend(changed_paths(before[child], after[child], name))
                        return paths
                    return [] if before == after else [prefix]
                changed = sorted(changed_paths(previous, cfg))
                if row and not changed:
                    return
                _db.execute(
                    "INSERT INTO settings(setting_key,value_json,revision,updated_at) VALUES('config',?,?,?) "
                    "ON CONFLICT(setting_key) DO UPDATE SET value_json=excluded.value_json, revision=excluded.revision, updated_at=excluded.updated_at",
                    (payload, revision, time.time()),
                )
                _db.execute(
                    "INSERT INTO config_history(ts,revision,sha256,changed_keys) VALUES(?,?,?,?)",
                    (time.time(), revision, digest, json.dumps(changed)),
                )
                _db.commit()
        except Exception as exc:
            log("config", f"SQLite settings persistence failed: {type(exc).__name__}: {exc}", "error")


PROFILE_DEFAULTS = {
    "automation": False,   # master switch: off = nothing runs on autopilot, actions wait for approval
    "sensors": {"processes": True, "kernel": True, "system": True, "gpu": True, "ping": True, "net": True, "services": True, "autoruns": True, "eventlog": True, "inventory": True},
    "intervals": {"inventory_min": 10},
    "thresholds": {"disk_free_pct": 10, "battery_pct": 20},
}
LIMITS = {"inventory_min": (2, 120), "disk_free_pct": (1, 30), "battery_pct": (5, 40)}


def get_profile():
    user = CFG.get("profile") if isinstance(CFG.get("profile"), dict) else {}
    automation = user.get("automation", PROFILE_DEFAULTS["automation"])
    out = {"automation": automation if isinstance(automation, bool) else PROFILE_DEFAULTS["automation"]}
    for group in ("sensors", "intervals", "thresholds"):
        values = user.get(group) if isinstance(user.get(group), dict) else {}
        out[group] = {}
        for key, default in PROFILE_DEFAULTS[group].items():
            value = values.get(key, default)
            if isinstance(default, bool):
                out[group][key] = value if isinstance(value, bool) else default
            else:
                try: out[group][key] = max(LIMITS[key][0], min(LIMITS[key][1], int(float(value))))
                except (TypeError, ValueError, OverflowError): out[group][key] = default
    return out


def set_profile(new):
    if not isinstance(new, dict):
        raise ValueError("profile must be an object")
    cur, changed = get_profile(), []
    if "automation" in new:
        if not isinstance(new["automation"], bool):
            raise ValueError("automation must be true or false")
        if new["automation"] != cur["automation"]:
            cur["automation"] = new["automation"]; changed.append("automation")
    for g, dflt in PROFILE_DEFAULTS.items():
        if g == "automation" or not isinstance(new.get(g), dict):
            continue
        for k in dflt:
            if k not in new[g]:
                continue
            v = new[g][k]
            if isinstance(dflt[k], bool):
                if not isinstance(v, bool):
                    raise ValueError(f"{g}.{k} must be true or false")
            else:
                try: v = max(LIMITS[k][0], min(LIMITS[k][1], int(float(v))))
                except (TypeError, ValueError): raise ValueError(f"{g}.{k} must be numeric")
            if cur[g][k] != v:
                cur[g][k] = v; changed.append(f"{g}.{k}={v}")
    CFG["profile"] = cur
    save_cfg(CFG)
    return changed


def off(sensor):
    return not get_profile()["sensors"].get(sensor, True)


def prof(group, key):
    return get_profile()[group][key]


CFG = load_cfg()
START = time.time()

# ---------------------------------------------------------------- store
_db_lock = threading.Lock()
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.execute("PRAGMA journal_mode=WAL")
_db.executescript("""
CREATE TABLE IF NOT EXISTS metrics(ts REAL, k TEXT, v REAL);
CREATE INDEX IF NOT EXISTS ix_m ON metrics(k, ts);
CREATE TABLE IF NOT EXISTS metrics_hourly_archive(
    hour_epoch INTEGER NOT NULL, k TEXT NOT NULL, sample_count INTEGER NOT NULL,
    sum_v REAL NOT NULL, min_v REAL NOT NULL, max_v REAL NOT NULL,
    PRIMARY KEY(hour_epoch,k)
);
CREATE INDEX IF NOT EXISTS ix_metrics_archive_key_hour ON metrics_hourly_archive(k,hour_epoch);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT, src TEXT, msg TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS ix_e ON events(ts);
CREATE TABLE IF NOT EXISTS insights(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, sev TEXT, key TEXT, title TEXT, detail TEXT, culprit TEXT);
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, args TEXT, state TEXT, origin TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS intel(q TEXT PRIMARY KEY, ts REAL, json TEXT);
CREATE TABLE IF NOT EXISTS settings(setting_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS config_history(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, revision INTEGER NOT NULL, sha256 TEXT NOT NULL, changed_keys TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, role TEXT NOT NULL, model TEXT NOT NULL, content TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_ai_messages_ts ON ai_messages(ts);
CREATE TABLE IF NOT EXISTS agent_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, started_at REAL NOT NULL, stopped_at REAL, pid INTEGER NOT NULL, executable TEXT NOT NULL, run_mode TEXT NOT NULL, exit_reason TEXT);
CREATE TABLE IF NOT EXISTS runtime_snapshots(snapshot_key TEXT PRIMARY KEY, collected_at REAL NOT NULL, payload_json TEXT NOT NULL, sha256 TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ai_usage_history(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, model TEXT, task TEXT, succeeded INTEGER NOT NULL, duration_s REAL, prompt_tokens INTEGER, output_tokens INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS ix_ai_usage_ts ON ai_usage_history(ts);
CREATE TABLE IF NOT EXISTS trace_archive(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, file_path TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'captured'
);
CREATE INDEX IF NOT EXISTS ix_trace_archive_ts ON trace_archive(ts);
CREATE TABLE IF NOT EXISTS game_profiles(game_key TEXT PRIMARY KEY,display_name TEXT NOT NULL,profile_json TEXT NOT NULL,updated_at REAL NOT NULL);
""")
_db.commit()

# SQLite is authoritative after migration. JSON remains a portable recovery mirror.
try:
    _stored = _db.execute("SELECT value_json FROM settings WHERE setting_key='config'").fetchone()
    if _stored:
        _disk_cfg = _config_from_storage(json.loads(_stored[0]))
        if isinstance(_disk_cfg, dict):
            CFG.update(_disk_cfg)
            save_cfg(CFG)
    else:
        save_cfg(CFG)
except Exception as _cfg_exc:
    # This code runs before log() is defined during module import.
    try:
        _db.execute("INSERT INTO events(ts,level,src,msg,data) VALUES(?,?,?,?,?)",
                    (time.time(), "error", "config", f"SQLite settings migration failed: {type(_cfg_exc).__name__}", ""))
        _db.commit()
    except Exception:
        pass


def db(sql, args=(), many=False):
    with _db_lock:
        cur = _db.execute(sql, args)
        rows = cur.fetchall() if sql.lstrip().upper().startswith("SELECT") else []
        _db.commit()
        return rows

def persist_snapshot(key, payload):
    """Persist the latest bounded runtime view by key; avoids unbounded per-second history."""
    if not isinstance(key, str) or not key or len(key) > 64:
        raise ValueError("snapshot key must contain 1..64 characters")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    if len(raw.encode("utf-8")) > 8 * 1024 * 1024:
        raise ValueError("runtime snapshot exceeds the 8 MiB storage limit")
    digest = __import__("hashlib").sha256(raw.encode("utf-8")).hexdigest()
    now = time.time()
    db("INSERT INTO runtime_snapshots(snapshot_key,collected_at,payload_json,sha256,updated_at) VALUES(?,?,?,?,?) "
       "ON CONFLICT(snapshot_key) DO UPDATE SET collected_at=excluded.collected_at,payload_json=excluded.payload_json,sha256=excluded.sha256,updated_at=excluded.updated_at",
       (key, now, raw, digest, now))
    return {"key": key, "collected_at": now, "sha256": digest, "bytes": len(raw.encode("utf-8"))}


def runtime_snapshot_info():
    rows = db("SELECT snapshot_key,collected_at,sha256,length(payload_json) FROM runtime_snapshots ORDER BY snapshot_key")
    return [{"key": r[0], "collected_at": r[1], "sha256": r[2], "bytes": r[3]} for r in rows]


def config_revision():
    row = db("SELECT revision,updated_at FROM settings WHERE setting_key='config'")
    return {"revision": int(row[0][0]), "updated_at": row[0][1]} if row else {"revision": 0, "updated_at": None}


# ---------------------------------------------------------------- live state + bus
LIVE = {}                 # latest value per metric key
HIST = {}                 # key -> list[(ts, v)] ring for the UI (last 10 min @1s)
HIST_MAX = 600
STATE = {"procs": [], "proc_total": 0, "proc_recommendations": [], "net": [], "services": {}, "services_catalog": [], "gpu": {}, "game": None, "ai": {}, "traces": [], "kernel": {}, "cores": [], "advanced": {}, "hardware_sensors": {"available": False, "reason": "not sampled"}}
_subs = []
_subs_lock = threading.Lock()
HEART = {}                # collector name -> dict(last, every, runs, note, err)
_pending_metrics = []
_pm_lock = threading.Lock()


def subscribe():
    q = queue.Queue(maxsize=500)
    with _subs_lock:
        _subs.append(q)
    return q


def unsubscribe(q):
    with _subs_lock:
        if q in _subs:
            _subs.remove(q)


def publish(kind, payload):
    msg = json.dumps({"t": kind, "d": payload}, separators=(",", ":"))
    with _subs_lock:
        for q in list(_subs):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


def metric(k, v, ts=None):
    ts = ts or time.time()
    try:
        v = float(v)
    except Exception:
        return
    LIVE[k] = v
    h = HIST.setdefault(k, [])
    h.append((ts, v))
    if len(h) > HIST_MAX:
        del h[: len(h) - HIST_MAX]
    with _pm_lock:
        _pending_metrics.append((ts, k, v))


def flush_metrics():
    with _pm_lock:
        rows = _pending_metrics[:]
        del _pending_metrics[:]
    if rows:
        with _db_lock:
            _db.executemany("INSERT INTO metrics VALUES(?,?,?)", rows)
            _db.commit()


def log(src, msg, level="info", **data):
    """Everything the agent does or notices goes through here -> activity feed."""
    ts = time.time()
    row = {"ts": ts, "level": level, "src": src, "msg": msg, "data": data}
    db("INSERT INTO events(ts,level,src,msg,data) VALUES(?,?,?,?,?)",
       (ts, level, src, msg, json.dumps(data) if data else ""))
    publish("log", row)
    return row


def insight(sev, key, title, detail="", culprit=""):
    ts = time.time()
    db("INSERT INTO insights(ts,sev,key,title,detail,culprit) VALUES(?,?,?,?,?,?)",
       (ts, sev, key, title, detail, culprit))
    row = {"ts": ts, "sev": sev, "key": key, "title": title, "detail": detail, "culprit": culprit}
    publish("insight", row)
    log("brain", f"[{sev.upper()}] {title}", "warn" if sev != "info" else "info", culprit=culprit)
    return row


def heartbeat(name, every, note="", err=""):
    h = HEART.setdefault(name, {"runs": 0, "every": every, "last": 0, "note": "", "err": ""})
    h.update(last=time.time(), every=every, note=note, err=err)
    h["runs"] += 1


def window(k, secs):
    now = time.time()
    return [v for t, v in HIST.get(k, []) if now - t <= secs]


def prune():
    """Archive high-frequency samples; keep durable event and AI histories indefinitely.

    Raw metrics are intentionally bounded (default 14 days) because one-second
    sampling would otherwise grow without limit. Before raw samples are removed,
    their hourly count/sum/min/max are merged into a permanent archive. Events,
    actions, insights, settings, config history, memories, AI transcripts/usage,
    agent runs and trace metadata are never pruned by this maintenance function.
    """
    retention_days = int(CFG.get("retention_days", 14) or 0)
    if retention_days <= 0:
        return {"archived_rows": 0, "deleted_raw_rows": 0, "events_retained": True}
    cut = time.time() - retention_days * 86400
    rows = db(
        "SELECT CAST(ts / 3600 AS INTEGER) AS hour_epoch,k,COUNT(*),SUM(v),MIN(v),MAX(v) "
        "FROM metrics WHERE ts<? GROUP BY hour_epoch,k", (cut,)
    )
    archived = 0
    if rows:
        with _db_lock:
            _db.executemany(
                "INSERT INTO metrics_hourly_archive(hour_epoch,k,sample_count,sum_v,min_v,max_v) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(hour_epoch,k) DO UPDATE SET "
                "sample_count=sample_count+excluded.sample_count,sum_v=sum_v+excluded.sum_v, "
                "min_v=MIN(min_v,excluded.min_v),max_v=MAX(max_v,excluded.max_v)", rows
            )
            archived = sum(int(row[2]) for row in rows)
            _db.execute("DELETE FROM metrics WHERE ts<?", (cut,))
            _db.commit()
    return {"archived_rows": archived, "deleted_raw_rows": archived, "events_retained": True}


def thread(fn, name):
    def run():
        while True:
            try:
                fn()
            except Exception as e:  # collectors must never die
                log("core", f"{name} crashed: {e!r} - restarting in 5s", "error")
                time.sleep(5)
            else:
                return
    t = threading.Thread(target=run, name=name, daemon=True)
    t.start()
    return t