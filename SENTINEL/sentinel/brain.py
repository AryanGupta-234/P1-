"""Sentinel brain: rule-based detectors, lag index, culprit attribution, reflex actions.
Runs without any LLM; the AI council (ai.py) layers on top of the insights raised here."""
import time
from collections import Counter
from . import core, actions
from .core import CFG, STATE, LIVE, metric, insight, log, heartbeat, window

COOL = {}
CULPRITS = Counter()
STATE["culprits"] = []


def cool(key, secs=180):
    now = time.time()
    if now - COOL.get(key, 0) < secs:
        return False
    COOL[key] = now
    return True


def avg(k, s):
    w = window(k, s)
    return sum(w) / len(w) if w else None


def mx(k, s):
    w = window(k, s)
    return max(w) if w else None


def top_nongame(field="cpu", floor=6):
    g = (STATE.get("game") or {}).get("name", "").lower()
    c = [p for p in STATE.get("procs", []) if p["name"].lower() != g and p[field] >= floor]
    return max(c, key=lambda p: p[field]) if c else None


def lag_index():
    """0 = perfect, 100 = awful. Weighted blend of the things that actually cause frame-time stutter."""
    def norm(v, lo, hi):
        return 0 if v is None else max(0.0, min(1.0, (v - lo) / (hi - lo)))
    cpu = norm(avg("cpu", 5), 70, 100)
    dpc = norm(mx("dpc", 10), 2, 15)
    pag = norm(avg("pagesout", 10), 20, 500)
    memlow = norm(2500 - (avg("mem_free_mb", 10) or 9999), 0, 2000)
    dsk = norm(mx("dlat", 10), 8, 60)
    jit = norm(avg("jitter", 10), 4, 25) * 0.9 + norm(avg("loss", 10), 0, 5) * 0.4
    thr = norm(100 - (avg("cpuperf", 10) or 100), 5, 45) if (avg("cpu", 10) or 0) > 35 else 0
    gtemp = norm(mx("gputemp", 10), 80, 92)
    s = 100 * (0.22 * cpu + 0.20 * dpc + 0.12 * pag + 0.10 * memlow + 0.12 * dsk + 0.14 * min(1, jit) + 0.06 * thr + 0.04 * gtemp)
    return round(min(100, s * 1.6), 1)


def detect():
    gaming = bool(STATE.get("game"))
    cpu10, cpuP = avg("cpu", 10), mx("cpu", 3)
    # CPU saturation with attribution
    if cpuP is not None and cpuP > 92 and cool("cpu-sat", 60):
        c = top_nongame("cpu", 8)
        if c:
            CULPRITS[c["name"]] += 1
            insight("warn" if gaming else "info", "cpu-culprit", f"CPU spike caused by {c['name']} ({c['cpu']}% of all cores)",
                    f"Total CPU hit {cpuP:.0f}%. Background process is competing with the game.", c["name"])
        elif gaming:
            insight("info", "cpu-game", f"CPU saturated by the game itself ({cpuP:.0f}%)", "Single-thread bound; background is not the cause.")
    # DPC / interrupt latency = driver problem
    d = avg("dpc", 10); dm = mx("dpc", 10)
    if d is not None and (d > 4 or dm > 15) and cool("dpc", 240):
        insight("high", "dpc", f"Driver latency: DPC time {d:.1f}% avg / {dm:.0f}% peak",
                "A driver (network, audio, GPU, USB, chipset) is monopolising a core - classic stutter cause.", "driver")
        if CFG["autopilot"].get("wpr_trace"):
            actions.propose("wpr_trace", origin="brain", reason="DPC spike - capture kernel trace to name the driver")
    # clock throttling
    perf, cpu30 = avg("cpuperf", 10), avg("cpu", 10)
    if perf is not None and cpu30 and perf < 60 and cpu30 > 40 and cool("throttle", 300):
        insight("high", "cpu-throttle", f"CPU running at {perf:.0f}% of base clock under load",
                "Thermal or power throttling. Check cooling, charger (laptops) and power plan.", "cpu")
    # memory: separate normal asset loading from real pressure
    pin, pout, free = avg("pagesin", 10), avg("pagesout", 10), avg("mem_free_mb", 10)
    if free is not None and ((free < 1500) or (pout is not None and pout > 300)) and cool("mem", 240):
        c = top_nongame("mem", 400)
        insight("high" if free < 800 else "warn", "mem", f"Real memory pressure: {free:.0f} MB free, {pout or 0:.0f} pages/s evicted",
                "Windows is pushing live pages to the pagefile.", c["name"] if c else "")
        actions.propose("bg_priority", origin="brain", reason="protect game pages by evicting background apps first")
        if free < 1000:
            actions.propose("trim_bg", origin="brain", reason="free RAM now")
    elif pin is not None and pin > 1500 and (pout or 0) < 50 and (free or 9999) > 2000 and cool("assetload", 600):
        insight("info", "assetload", f"Hard faults {pin:.0f}/s but nothing evicted - normal game asset loading",
                "File-backed reads, not a RAM shortage. Install the game on an NVMe/SSD to shorten them.")
    # disk stall
    dl, dlm = avg("dlat", 10), mx("dlat", 10)
    if dlm is not None and dlm > 40 and cool("disk", 180):
        c = top_nongame("io", 15)
        insight("warn", "disk", f"Disk latency spike: {dlm:.0f} ms (avg {dl:.0f} ms)", "Storage stalls freeze the game while assets stream in.", c["name"] if c else "")
    # network
    j, loss, png = avg("jitter", 15), avg("loss", 15), avg("ping", 15)
    if ((j or 0) > 15 or (loss or 0) > 3) and cool("net", 180):
        insight("high" if (loss or 0) > 3 else "warn", "net", f"Network unstable: jitter {j or 0:.0f} ms, loss {loss or 0:.0f}%, ping {png or 0:.0f} ms",
                "Use Ethernet / 5 GHz and stop downloads while gaming.", "network")
        actions.propose("flush_dns", origin="brain", reason="cheap first step on unstable network")
    # GPU
    g = STATE.get("gpu") or {}
    if g.get("throttle") and cool("gpu-thr", 300):
        insight("high", "gpu-throttle", "GPU throttling: " + ", ".join(g["throttle"]), f"{g.get('temp')} C, {g.get('pwr')}/{g.get('pwrlim')} W", "gpu")
    # config nags (only once an hour, only while gaming)
    sysd = STATE.get("system") or {}
    if gaming and sysd.get("power_plan", "").lower().startswith("balanced") and cool("plan", 3600):
        insight("warn", "plan", "Power plan is Balanced while gaming", "CPU clocks ramp slowly -> frame-time stutter.", "power")
        actions.propose("power_plan", origin="brain", reason="High performance plan while a game is running")
    if gaming and sysd.get("vbs") and cool("vbs", 86400):
        insight("warn", "vbs", "Memory Integrity / VBS is ON", "Costs 5-15% CPU in games. Turn off in Windows Security > Core isolation (needs reboot).", "config")


def reflex():
    """Game-mode reflex: keep background apps de-prioritised as new ones appear."""
    if STATE.get("game") and CFG["autopilot"].get("bg_priority") and cool("reflex-bg", 20):
        if any(p.get("bg") and p["pid"] not in actions._handled for p in STATE.get("procs", [])):
            actions.propose("bg_priority", origin="reflex", reason="new background apps appeared during game")


def brain_loop():
    time.sleep(3)
    log("brain", "Brain online: detectors armed (CPU, DPC, throttle, memory, disk, network, GPU, config)", "ok")
    while True:
        t0 = time.time()
        try:
            li = lag_index()
            metric("lag_index", li)
            detect()
            reflex()
            STATE["culprits"] = [{"name": k, "n": v} for k, v in CULPRITS.most_common(8)]
            heartbeat("brain (detectors)", 1, f"lag index {li}")
        except Exception as e:
            log("brain", f"detector error {e!r}", "error")
        d = 1.0 - (time.time() - t0)
        if d > 0:
            time.sleep(d)