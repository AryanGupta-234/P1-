"""Two-model Ollama council. FAST model triages continuously; DEEP model verifies and decides on real problems.
Models are auto-selected from whatever is installed (smallest = fast, largest = deep) unless set in config."""
import json, os, re, threading, time, urllib.request
from urllib.parse import urlparse
import psutil
from . import core, actions, intel, ai_engine
from .core import CFG, STATE, HIST, LIVE, db, log, publish, heartbeat, window

SYS_FAST = ("You are SENTINEL-FAST, a Windows gaming-performance triage agent. You receive live telemetry. "
            "Reply with at most 3 short bullet lines: what is happening, what is abnormal, what to watch. No fluff.")
SYS_DEEP = ("You are SENTINEL-DEEP, a senior Windows performance engineer. You receive telemetry, a fast triage draft and "
            "reference links. Verify or correct the draft, name the most likely root cause, and propose fixes. "
            "Reply ONLY with JSON: {\"diagnosis\":str,\"root_cause\":str,\"confidence\":0-1,\"actions\":[{\"kind\":str,\"why\":str}],"
            "\"manual\":[str]}. Allowed action kinds: bg_priority, flush_dns, power_plan, wpr_trace, trim_bg. "
            "Put anything else (BIOS, driver updates, Memory Integrity, Ethernet) in manual.")
_lock = threading.Lock()
_inference_lock = threading.Lock()
STATE["ai"] = {"online": False, "fast": "", "deep": "", "models": [], "status": "", "transcript": [], "busy": "",
               "current_task": "", "current_model": "", "last_started_at": None, "last_finished_at": None,
               "usage": {"requests": 0, "successes": 0, "failures": 0, "last_duration_s": None,
                         "last_model": "", "last_prompt_tokens": None, "last_output_tokens": None,
                         "last_at": None}}
try:
    _history = db("SELECT ts,role,model,content FROM ai_messages ORDER BY id DESC LIMIT 60")
    STATE["ai"]["transcript"] = [{"ts": r[0], "role": r[1], "model": r[2], "text": r[3]} for r in reversed(_history)]
except Exception:
    pass

# Rehydrate lifetime usage counters after an agent restart. AI usage rows are
# durable and are not truncated by the maintenance job.
try:
    _usage = db("SELECT COUNT(*), COALESCE(SUM(succeeded),0), COALESCE(SUM(CASE WHEN succeeded=0 THEN 1 ELSE 0 END),0) FROM ai_usage_history")
    _last_usage = db("SELECT ts,model,duration_s,prompt_tokens,output_tokens,error FROM ai_usage_history ORDER BY id DESC LIMIT 1")
    if _usage:
        STATE["ai"]["usage"].update({
            "requests": int(_usage[0][0] or 0),
            "successes": int(_usage[0][1] or 0),
            "failures": int(_usage[0][2] or 0),
            "history_limit": "all stored requests",
            "history_rehydrated": True,
        })
    if _last_usage:
        row = _last_usage[0]
        STATE["ai"]["usage"].update({
            "last_at": row[0], "last_model": row[1], "last_duration_s": row[2],
            "last_prompt_tokens": row[3], "last_output_tokens": row[4],
            "last_error": row[5] or "",
        })
except Exception as _usage_exc:
    STATE["ai"]["usage"]["history_error"] = type(_usage_exc).__name__

DEEP_MODEL_MIN_FREE_GIB = 7.5
DEEP_MODEL_RESUME_GIB = 8.0


def _available_memory_gib():
    try:
        return max(0.0, psutil.virtual_memory().available / (1024 ** 3))
    except Exception:
        return 0.0


def _route_deep_model():
    """Re-evaluate the local DEEP slot against live memory headroom before inference."""
    a = STATE["ai"]
    requested = a.get("deep_requested") or a.get("deep") or ""
    if not requested or requested.startswith(CLOUD):
        return requested
    available = _available_memory_gib()
    current = a.get("deep") or requested
    if available < DEEP_MODEL_MIN_FREE_GIB:
        active = a.get("fast") or requested
        reason = "low-memory fallback to FAST model"
    elif available >= DEEP_MODEL_RESUME_GIB:
        active = requested
        reason = "RAM headroom recovered"
    else:
        active = current
        reason = "holding previous route inside hysteresis band"
    policy = {
        "available_memory_gib": round(available, 2),
        "minimum_deep_memory_gib": DEEP_MODEL_MIN_FREE_GIB,
        "resume_memory_gib": DEEP_MODEL_RESUME_GIB,
        "requested_deep": requested,
        "active_deep": active,
        "fallback_active": active != requested,
        "reason": reason,
    }
    a["model_policy"] = policy
    if active != current:
        a["deep"] = active
        log("ai", f"hardware-aware model route: DEEP={active} ({reason}; {available:.1f} GiB available)", "info")
    return active


class _NoLocalRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A local Ollama endpoint must not redirect prompts/telemetry off-device.
        return None


_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoLocalRedirect())


def _http(path, body=None, timeout=120):
    base = str(CFG.get("ollama_url") or "").rstrip("/")
    parsed = urlparse(base)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("invalid local Ollama URL") from exc
    if (parsed.scheme not in ("http", "https")
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or parsed.username is not None or parsed.password is not None
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)):
        raise RuntimeError("local Ollama transport is restricted to a loopback origin")
    if not isinstance(path, str) or not path.startswith("/") or "\\" in path:
        raise ValueError("invalid local Ollama API path")
    url = base + path
    data = json.dumps(body, allow_nan=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Accept": "application/json"})
    with _LOCAL_OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


CLOUD = "\u2601 "


def cloud_ready():
    c = CFG["cloud"]
    return bool(c.get("enabled") and (os.environ.get("SENTINEL_CLOUD_KEY") or c.get("key")))


def redact(t):
    t = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "x.x.x.x", t)
    return re.sub(r"(?i)[a-z]:\\users\\[^\\\s\"']+", r"C:\\Users\\<user>", t)


def local_ok(model, slot="fast"):
    allowed, reason = ai_engine.inference_allowed(
        model, cloud=model.startswith(CLOUD),
        pause_when_gaming=bool(CFG.get("pause_ai_when_gaming", True)), slot=slot,
    )
    STATE.setdefault("ai", {})["admission"] = {
        "allowed": allowed, "reason": reason, "slot": slot, "checked_at": time.time()
    }
    return allowed


def cloud_gen(prompt, system, fmt, timeout):
    c = CFG["cloud"]
    body = {"model": c["model"], "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": redact(prompt)}]}
    if fmt == "json":
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(c["url"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Sentinel-Agent/1.0",
                                          "Authorization": "Bearer " + (os.environ.get("SENTINEL_CLOUD_KEY") or c["key"])})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()


def refresh_models():
    cloud = cloud_ready()
    try:
        tags = _http("/api/tags", timeout=4).get("models", [])
    except Exception:
        if cloud:
            a = STATE["ai"]; a["online"] = True; a["models"] = []
            a["fast"] = a["deep"] = CLOUD + CFG["cloud"]["model"]
            return True
        STATE["ai"]["online"] = False
        return False
    ms = sorted([(m["name"], m.get("size", 0)) for m in tags if "embed" not in m["name"].lower()], key=lambda x: x[1])
    a = STATE["ai"]
    a["online"] = bool(ms) or cloud
    a["models"] = [{"name": n, "gb": round(s / 1e9, 1)} for n, s in ms]
    a["fast"] = CFG["model_fast"] or (ms[0][0] if ms else "")
    requested_deep = (CLOUD + CFG["cloud"]["model"]) if cloud else (CFG["model_deep"] or (ms[-1][0] if ms else ""))
    a["deep_requested"] = requested_deep
    a["deep"] = requested_deep
    if requested_deep and not requested_deep.startswith(CLOUD):
        _route_deep_model()
    else:
        a["model_policy"] = {"requested_deep": requested_deep, "active_deep": requested_deep,
                              "fallback_active": False, "reason": "cloud provider selected explicitly" if cloud else "no local deep model"}
    if not a["online"]:
        a["error"] = "Ollama reachable but no local chat model is installed" if tags else "Ollama is offline"
    else:
        a.pop("error", None)
    return a["online"]


def gen(model, prompt, system, fmt=None, timeout=180, slot=None):
    """Serialize local inference and expose measurable request/usage state to the HUD."""
    if slot == "deep":
        model = _route_deep_model()
    if not model:
        raise RuntimeError("no eligible model is selected")
    a = STATE["ai"]
    started = time.time()
    start_mono = time.monotonic()
    a["last_started_at"] = started
    a["current_task"] = slot or "inference"
    a["current_model"] = model
    a["busy"] = slot or "inference"
    a["usage"]["requests"] = int(a["usage"].get("requests", 0)) + 1
    try:
        with _inference_lock:
            if model.startswith(CLOUD):
                output = cloud_gen(prompt, system, fmt, timeout)
                prompt_tokens = output_tokens = None
            else:
                if not local_ok(model):
                    raise RuntimeError("local model paused while gaming")
                body = {"model": model, "prompt": prompt, "system": system, "stream": False,
                        "options": {"temperature": 0.2, "num_ctx": 4096}}
                if fmt:
                    body["format"] = fmt
                payload = _http("/api/generate", body, timeout)
                output = str(payload.get("response", "")).strip()
                prompt_tokens = payload.get("prompt_eval_count")
                output_tokens = payload.get("eval_count")
                duration_ns = payload.get("total_duration")
                if isinstance(duration_ns, (int, float)) and duration_ns > 0:
                    a["usage"]["ollama_duration_s"] = round(duration_ns / 1e9, 3)
        duration = round(time.monotonic() - start_mono, 3)
        a["usage"].update(successes=int(a["usage"].get("successes", 0)) + 1,
            last_duration_s=duration, last_model=model, last_prompt_tokens=prompt_tokens,
            last_output_tokens=output_tokens, last_at=time.time(), last_error="")
        a["last_finished_at"] = time.time()
        try:
            db("INSERT INTO ai_usage_history(ts,model,task,succeeded,duration_s,prompt_tokens,output_tokens,error) VALUES(?,?,?,?,?,?,?,?)",
               (a["last_finished_at"], model, str(slot or "inference"), 1, duration, prompt_tokens, output_tokens, ""))
        except Exception as store_exc:
            log("storage", f"AI usage history persistence failed: {type(store_exc).__name__}", "warn")
        publish("ai_usage", {"usage": a["usage"], "current_task": "", "current_model": model})
        return output
    except Exception as exc:
        duration = round(time.monotonic() - start_mono, 3)
        a["usage"].update(failures=int(a["usage"].get("failures", 0)) + 1,
            last_duration_s=duration, last_model=model, last_at=time.time(),
            last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
        a["last_finished_at"] = time.time()
        try:
            db("INSERT INTO ai_usage_history(ts,model,task,succeeded,duration_s,prompt_tokens,output_tokens,error) VALUES(?,?,?,?,?,?,?,?)",
               (a["last_finished_at"], model, str(slot or "inference"), 0, duration, None, None, a["usage"]["last_error"]))
        except Exception as store_exc:
            log("storage", f"AI failure history persistence failed: {type(store_exc).__name__}", "warn")
        publish("ai_usage", {"usage": a["usage"], "current_task": "", "current_model": model})
        raise
    finally:
        a["busy"] = ""
        a["current_task"] = ""
        a["current_model"] = ""


def snapshot():
    def avg(k, s=30):
        w = window(k, s); return round(sum(w) / len(w), 1) if w else None
    def mx(k, s=30):
        w = window(k, s); return round(max(w), 1) if w else None
    procs = [f"{p['name']} cpu{p['cpu']}% mem{p['mem']}MB io{p['io']}MB/s" for p in STATE.get("procs", [])[:6]]
    payload = {
        "game": (STATE.get("game") or {}).get("name"),
        "30s": {"cpu_avg": avg("cpu"), "cpu_max": mx("cpu"), "dpc_avg": avg("dpc"), "dpc_max": mx("dpc"),
                "irq_avg": avg("irq"), "free_ram_mb": avg("mem_free_mb"), "pages_in": avg("pagesin"),
                "pages_out": avg("pagesout"), "disk_lat_ms": avg("dlat"), "disk_lat_max": mx("dlat"),
                "gpu": avg("gpu"), "gpu_temp": mx("gputemp"), "ping": avg("ping"), "jitter": avg("jitter"),
                "cpu_clock_pct": avg("cpuperf")},
        "top_processes": procs, "system": STATE.get("system"), "gpu": STATE.get("gpu"),
        "lag_index": LIVE.get("lag_index"),
    }
    return ai_engine.compose_context(payload, purpose="triage")


def _say(role, model, text):
    t = {"ts": time.time(), "role": role, "model": model, "text": str(text)[:12000]}
    tr = STATE["ai"]["transcript"]; tr.append(t); del tr[:-60]
    try:
        db("INSERT INTO ai_messages(ts,role,model,content) VALUES(?,?,?,?)", (t["ts"], role, str(model)[:160], t["text"]))
    except Exception as exc:
        log("ai", f"AI transcript persistence failed: {type(exc).__name__}", "error")
    publish("ai", t)


def _parse_json(s):
    m = re.search(r"\{.*\}", s, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def investigate(ins):
    """fast drafts -> deep verifies -> safe actions proposed."""
    if not CFG["ai_enabled"] or not STATE["ai"]["online"]:
        return
    a = STATE["ai"]
    if not a["deep"]:
        return
    with _lock:
        snap = snapshot()
        refs = intel.lookup(f"{ins['title']} Windows", False)[:4] if ins.get("title") else []
        refs_txt = "\n".join(f"- {r['src']}: {r['title']} ({r['url']})" for r in refs)
        ctx = json.dumps(snap)[:2500]
        a["busy"] = "fast"
        try:
            draft = gen(a["fast"], f"Problem detected: {ins['title']} | {ins.get('detail','')} | culprit: {ins.get('culprit','')}\nTelemetry: {ctx}", SYS_FAST, timeout=90, slot="fast")
        except Exception as e:
            draft = f"(fast model unavailable: {str(e)[:60]})"
        _say("fast", a["fast"], draft)
        a["busy"] = "deep"
        try:
            raw = gen(a["deep"], f"Problem: {ins['title']} | {ins.get('detail','')}\nFast draft:\n{draft}\nTelemetry: {ctx}\nReferences:\n{refs_txt}", SYS_DEEP, fmt="json", timeout=240, slot="deep")
        except Exception as e:
            a["busy"] = ""
            _say("deep", a["deep"], f"(deep model unavailable: {str(e)[:60]})")
            return
        a["busy"] = ""
        j = _parse_json(raw)
        if not j:
            _say("deep", a["deep"], raw[:600]); return
        txt = f"{j.get('diagnosis','')}\nRoot cause: {j.get('root_cause','')} (confidence {j.get('confidence','?')})"
        if j.get("manual"):
            txt += "\nManual: " + "; ".join(str(x) for x in j["manual"][:5])
        _say("deep", a["deep"], txt)
        for act in (j.get("actions") or [])[:3]:
            if isinstance(act, dict) and act.get("kind"):
                actions.propose(str(act["kind"]), {}, origin=f"ai:{a['deep']}", reason=str(act.get("why", ""))[:140])


def chat(msg, mode="council"):
    a = STATE["ai"]
    from . import advanced
    if not a["online"] and not refresh_models():
        return "Ollama is not reachable at " + CFG["ollama_url"] + ". Start Ollama and install a local model."
    _say("user", "you", msg)
    if mode in advanced.SPECIALISTS:
        # Specialist modes are advisory only. Their output is never passed into
        # the action layer; deterministic allowlists and risk policy remain authoritative.
        status = advanced.status()
        packet = {
            "live": {k: LIVE.get(k) for k in ("cpu", "mem", "gpu", "gputemp", "gpuclk", "gpupwr", "dpc", "irq", "pagesin", "pagesout", "dlat", "ping", "jitter", "loss") if LIVE.get(k) is not None},
            "game": STATE.get("game"), "gpu": STATE.get("gpu", {}), "cores": STATE.get("cores", []),
            "kernel": STATE.get("kernel", {}), "personal_baseline": status.get("baseline", {}),
            "network_evidence": status.get("network_evidence", {}), "hardware_sensors": status.get("hardware_sensors", {}),
            "recent_etw_events": status.get("etw_events", [])[:12], "thermal_events": status.get("thermal_events", [])[:12],
            "session_reports": status.get("session_reports", [])[:2],
        }
        q = f"Specialist task: {mode}\nUser question: {msg}\nMeasured local evidence (JSON): {json.dumps(packet, default=str)[:10000]}"
        sysq = ("You are one of SENTINEL's specialist analysts. " + advanced.SPECIALISTS[mode] +
                " Use only evidence in the payload, clearly label missing/unknown measurements, state confidence and limitations. "
                "Return diagnosis and at most three proposed next steps. Do not emit shell commands, scripts, registry edits or executable action payloads. "
                "You cannot approve or execute changes: SENTINEL's deterministic rule engine and explicit user approvals decide all actions.")
        model = a.get("deep") or a.get("fast")
        slot = "deep" if model == a.get("deep") else "fast"
        out = gen(model, q, sysq, timeout=240 if slot == "deep" else 120, slot=slot)
        _say(mode, model, out)
        return out
    ctx = json.dumps(snapshot())[:2500]
    q = f"User question: {msg}\nLive telemetry: {ctx}"
    sysq = "You are SENTINEL, the user's Windows gaming-performance agent. Answer concisely and concretely using the telemetry."
    if mode == "fast" or a["fast"] == a["deep"]:
        out = gen(a["fast"], q, sysq, timeout=120, slot="fast"); _say("fast", a["fast"], out); return out
    if mode == "deep":
        out = gen(a["deep"], q, sysq, timeout=240, slot="deep"); _say("deep", a["deep"], out); return out
    draft = gen(a["fast"], q, sysq, timeout=120, slot="fast"); _say("fast", a["fast"], draft)
    out = gen(a["deep"], q + f"\nA fast model drafted this answer:\n{draft}\nImprove it: fix mistakes, add what is missing, stay concise.", sysq, timeout=240, slot="deep")
    _say("deep", a["deep"], out)
    return out


def ai_loop():
    """Continuous: attach to Ollama, run fast triage every minute, deep investigation on notable insights."""
    q = core.subscribe()
    last_triage = 0
    cool = {}
    deferred = []
    while True:
        if not CFG.get("ai_enabled", True):
            STATE["ai"]["status"] = "AI council disabled in settings"
            heartbeat("AI council (Ollama)", 60, "disabled in settings")
            time.sleep(5); continue
        if not STATE["ai"]["online"]:
            if refresh_models():
                a = STATE["ai"]
                log("ai", f"Ollama online. FAST={a['fast']}  DEEP={a['deep']}  ({len(a['models'])} models installed)", "ok")
            else:
                heartbeat("AI council (Ollama)", 60, "Ollama offline - waiting")
                time.sleep(15); continue
        try:
            m = q.get(timeout=5)
            d = json.loads(m)
            if d["t"] == "insight" and d["d"]["sev"] in ("high", "warn") and time.time() - cool.get(d["d"]["key"], 0) > 300:
                cool[d["d"]["key"]] = time.time()
                if local_ok(STATE["ai"]["deep"], "deep"):
                    investigate(d["d"])
                else:
                    deferred.append(d["d"])
                    log("ai", f"local AI sleeping during game - '{d['d']['title']}' queued for after the session", "info")
        except Exception:
            pass
        if deferred and local_ok(STATE["ai"]["deep"], "deep"):
            for ins in deferred[:3]:
                investigate(ins)
            deferred.clear()
        triage_allowed, triage_reason = ai_engine.triage_allowed()
        if CFG["ai_enabled"] and time.time() - last_triage > 60 and STATE["ai"]["fast"] and triage_allowed and local_ok(STATE["ai"]["fast"], "fast"):
            last_triage = time.time()
            STATE["ai"]["admission"] = {"allowed": True, "reason": triage_reason, "slot": "fast", "checked_at": last_triage}
            STATE["ai"]["busy"] = "fast"
            try:
                s = gen(STATE["ai"]["fast"], "Telemetry: " + json.dumps(snapshot())[:2500], SYS_FAST, timeout=60, slot="fast")
                STATE["ai"]["status"] = s
                publish("ai_status", {"text": s, "ts": time.time()})
                heartbeat("AI council (Ollama)", 60, f"fast={STATE['ai']['fast']} deep={STATE['ai']['deep']}")
            except Exception as e:
                STATE["ai"]["online"] = False
                log("ai", f"Ollama lost: {str(e)[:60]}", "warn")
            STATE["ai"]["busy"] = ""