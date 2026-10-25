"use strict";
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const qs = new URLSearchParams(location.search);
let TOKEN = qs.get("t") || ""; try { if (TOKEN) localStorage.setItem("st", TOKEN); else TOKEN = localStorage.getItem("st") || ""; } catch (e) { }
const API_CONCURRENCY = 4;
const API_TIMEOUT_MS = 16000;
let apiActive = 0;
const apiWaiters = [];
async function acquireApiSlot() {
  if (apiActive < API_CONCURRENCY) {
    apiActive++;
    return;
  }
  // A queued caller receives the released permit directly. Do not decrement
  // and increment around the hand-off: that creates a brief over-admission race.
  await new Promise(resolve => apiWaiters.push(resolve));
}
function releaseApiSlot() {
  const next = apiWaiters.shift();
  if (next) next();
  else apiActive = Math.max(0, apiActive - 1);
}
async function api(p, body) {
  await acquireApiSlot();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const response = await fetch(p, {
      method: body ? "POST" : "GET",
      headers: { "X-Sentinel-Token": TOKEN, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
      signal: controller.signal
    });
    let payload;
    try { payload = await response.json(); }
    catch { throw new Error("Local agent returned invalid JSON (HTTP " + response.status + ")"); }
    if (!response.ok && !payload?.error) payload.error = "Local agent returned HTTP " + response.status;
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("Local request timed out: " + p);
    throw error;
  } finally {
    clearTimeout(timeout);
    releaseApiSlot();
  }
}
async function apiRetry(path, attempts = 2) {
  let lastError;
  for (let attempt = 0; attempt <= attempts; attempt++) {
    try {
      const result = await api(path);
      if (result?.error) throw new Error(result.error);
      return result;
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await new Promise(resolve => setTimeout(resolve, 350 * (attempt + 1)));
    }
  }
  throw lastError;
}

const H = {}, MAXH = 300; let S = null, view = "cmd";
const LOGS = []; let paused = false, lastLogId = 0;
const lv = { info: 1, ok: 1, warn: 1, error: 1, debug: 1 };
const fmt = (v, d = 0) => v == null || isNaN(v) ? "--" : (+v).toFixed(d);
const hms = ts => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
const dur = s => { s = Math.floor(s); const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return (d ? d + "d " : "") + (h || d ? h + "h " : "") + m + "m " + (s % 60) + "s"; };

/* ---------- P1 shell: titles, toasts, splash, starfield ---------- */
const TITLES = { cmd: "COMMAND", eng: "ENGINE DECK", agent: "AGENT", sys: "SYSTEM", act: "ACTIVITY", activityx: "ACTIVITY INTELLIGENCE", proc: "PROCESSES", net: "NETWORK", ker: "KERNEL", adv: "TUNER / THERMAL", evi: "EVIDENCE", intelx: "INTELLIGENCE", int: "INTEL FEED", ai: "AI CORE", ctl: "CONTROL", fc: "FEATURES", tsk: "TASKS", maint: "MAINTENANCE" };
const VKEYS = Object.keys(TITLES);
let bootDone = false;
let bootInProgress = true;
const deferredToasts = [];
function toast(msg, kind = "") {
  if (bootInProgress) {
    if (kind === "bad" || kind === "warn") {
      deferredToasts.push({ msg: String(msg), kind });
      while (deferredToasts.length > 8) deferredToasts.shift();
    }
    return;
  }
  const b = document.createElement("div");
  b.className = "toast " + kind;
  b.textContent = msg;
  $("#toasts").append(b);
  setTimeout(() => b.remove(), 5200);
}
const PAGE_WARMED = Object.create(null);
const PAGE_WARM_TTL_MS = 20000;
function pageIsWarm(key) {
  return Date.now() - Number(PAGE_WARMED[key] || 0) < PAGE_WARM_TTL_MS;
}
function markPageWarm(key) {
  PAGE_WARMED[key] = Date.now();
}
function bp(p, stage, msg, cls = "") {
  const progress = $("#bootProgress"), pct = $("#bootPct"), stageNode = $("#bootStage");
  if (progress) { const value = Math.max(0, Math.min(100, p)); progress.style.width = value + "%"; progress.setAttribute("aria-valuenow", String(Math.round(value))); const gauge = $("#bootGauge"); if (gauge) gauge.style.strokeDashoffset = String(295.3 * (1 - value / 100)); }
  if (pct) pct.textContent = String(Math.round(p)).padStart(2, "0") + "%";
  const nodeState = $("#bootNodeState");
  if (nodeState && stage) nodeState.textContent = stage;
  const lanes = $$(".boot-lanes > div");
  const activeLane = p < 16 ? 0 : p < 32 ? 1 : p < 48 ? 2 : p < 64 ? 3 : p < 82 ? 4 : 5;
  lanes.forEach((lane, index) => lane.classList.toggle("active", index === activeLane));
  if (stage && stageNode) stageNode.textContent = stage;
  const detail = $("#bootDetail");
  if (msg && detail) detail.textContent = msg;
  if (msg) {
    const log = $("#bootLog");
    if (log) {
      const item = document.createElement("div");
      item.className = "boot-log-line " + cls;
      item.textContent = msg;
      log.append(item);
      while (log.children.length > 10) log.firstElementChild.remove();
      log.scrollTop = log.scrollHeight;
    }
  }
}
function bootModule(key, label, state = "WAITING", detail = "Queued for initialization") {
  const host = $("#bootModules");
  if (!host) return;
  const item = document.createElement("div");
  item.className = "boot-module";
  item.dataset.bootModule = key;
  item.innerHTML = '<span class="boot-module-dot"></span><span class="boot-module-copy"><b></b><small></small></span><strong></strong>';
  item.querySelector("b").textContent = label;
  item.querySelector("small").textContent = detail;
  item.querySelector("strong").textContent = state;
  host.append(item);
}
function bootModuleState(key, state, detail = "") {
  const item = document.querySelector('[data-boot-module="' + key + '"]');
  if (!item) return;
  item.classList.remove("loading", "ready", "warn");
  const normalized = String(state || "").toLowerCase();
  if (normalized === "loading") item.classList.add("loading");
  else if (normalized === "ready") item.classList.add("ready");
  else if (["degraded", "blocked", "warn", "error"].includes(normalized)) item.classList.add("warn");
  const status = item.querySelector("strong");
  const note = item.querySelector("small");
  if (status) status.textContent = String(state || "").toUpperCase();
  if (note && detail) note.textContent = detail;
}
function endBoot() {
  if (bootDone) return;
  bootDone = true;
  bootInProgress = false;
  $("#boot").classList.add("done");
  $("#app").classList.add("ready");
  const notices = deferredToasts.splice(0);
  for (const notice of notices.slice(-4)) toast(notice.msg, notice.kind);
}
function showBootRetry(stage, message) {
  bp(100, stage, String(message || "The local agent did not return a complete startup snapshot").slice(0, 180), "warn");
  $("#boot").classList.add("boot-error");
  const retry = $("#bootRetry");
  if (retry) {
    retry.hidden = false;
    retry.onclick = () => location.reload();
  }
}
function updateBootTelemetry() {
  const live = S && typeof S.live === "object" ? S.live : {};
  const definitions = [
    ["cpu", "bootCpuValue", "%", 100, 0],
    ["mem", "bootRamValue", "%", 100, 0],
    ["gpu", "bootGpuValue", "%", 100, 0],
    ["dpc", "bootDpcValue", "%", 8, 2]
  ];
  for (const [key, id, suffix, max, precision] of definitions) {
    const raw = live[key];
    const value = Number(raw);
    const valid = raw != null && Number.isFinite(value);
    const node = document.getElementById(id);
    const bar = document.querySelector('[data-boot-bar="' + (key === "mem" ? "ram" : key) + '"]');
    if (node) node.textContent = valid ? value.toFixed(precision) + suffix : "--";
    if (bar) bar.style.width = valid ? Math.max(0, Math.min(100, value / max * 100)) + "%" : "0%";
  }
  const processCount = document.getElementById("bootProcessCount");
  if (processCount && Number(S?.proc_total || 0) > 0) processCount.textContent = Number(S.proc_total).toLocaleString() + " PROCESSES";
}

function starfield() {
  const c = $("#starfield"), x = c.getContext("2d"); if (matchMedia("(prefers-reduced-motion:reduce)").matches) return;
  let w, h, st = [], frame = 0, lastPaint = 0;
  const resize = () => { w = c.width = innerWidth; h = c.height = innerHeight; st = Array.from({ length: Math.min(48, Math.ceil(w * h / 28000)) }, () => ({ x: Math.random() * w, y: Math.random() * h, r: Math.random() * 1.1 + .3, v: Math.random() * .1 + .02 })); };
  const draw = timestamp => {
    frame = 0;
    if (document.visibilityState !== "visible") return;
    if (timestamp - lastPaint >= 42) {
      lastPaint = timestamp; x.clearRect(0, 0, w, h); x.fillStyle = "#B9AEA2";
      for (const star of st) { star.y -= star.v; if (star.y < 0) { star.y = h; star.x = Math.random() * w; } x.globalAlpha = .25 + star.r / 2; x.beginPath(); x.arc(star.x, star.y, star.r, 0, 6.3); x.fill(); }
    }
    frame = requestAnimationFrame(draw);
  };
  const resume = () => { if (document.visibilityState === "visible" && !frame) frame = requestAnimationFrame(draw); };
  resize(); addEventListener("resize", resize, { passive: true }); document.addEventListener("visibilitychange", resume); resume();
}

/* ---------- charts ---------- */
function prep(c) { const r = devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight; if (c.width !== w * r || c.height !== h * r) { c.width = w * r; c.height = h * r; } const x = c.getContext("2d"); x.setTransform(r, 0, 0, r, 0, 0); x.clearRect(0, 0, w, h); return [x, w, h]; }
function line(x, d, w, h, col, lo, hi, fill) {
  if (!d.length) return; const n = Math.max(d.length, 60), st = w / (n - 1), off = n - d.length; x.beginPath();
  d.forEach((v, i) => { const px = (off + i) * st, py = h - 2 - (Math.min(hi, Math.max(lo, v)) - lo) / ((hi - lo) || 1) * (h - 4); i ? x.lineTo(px, py) : x.moveTo(px, py); });
  x.strokeStyle = col; x.lineWidth = 1.6; x.shadowColor = col; x.shadowBlur = 6; x.stroke(); x.shadowBlur = 0;
  if (fill) { x.lineTo(w, h); x.lineTo(off * st, h); x.closePath(); const g = x.createLinearGradient(0, 0, 0, h); g.addColorStop(0, col + "55"); g.addColorStop(1, col + "00"); x.fillStyle = g; x.fill(); }
}
function spark(c, k, col, lo, hi) { const [x, w, h] = prep(c); const d = H[k] || []; if (hi == null) hi = Math.max(lo + 1, ...d) * 1.1; line(x, d, w, h, col, lo, hi, true); }
function big(c, series, opts = {}) {
  const [x, w, h] = prep(c); const all = series.flatMap(s => H[s.k] || []); let hi = opts.hi ?? Math.max(1, ...all) * 1.15, lo = opts.lo ?? 0;
  x.strokeStyle = "rgba(184,230,91,.08)"; x.fillStyle = "#5a6a60"; x.font = "10px 'Share Tech Mono',monospace";
  for (let i = 0; i <= 4; i++) { const y = 4 + i * (h - 8) / 4; x.beginPath(); x.moveTo(0, y); x.lineTo(w, y); x.stroke(); x.fillText(fmt(hi - (hi - lo) * i / 4, hi < 10 ? 1 : 0), 4, y - 2); }
  series.forEach((s, i) => { line(x, H[s.k] || [], w, h, s.c, lo, hi, i === 0); x.fillStyle = s.c; x.fillText(s.l, w - 90, 14 + i * 12); });
}

function updateSignalTile(prefix, raw, unit, scale, precision = 1) {
  const value = Number(raw);
  const valid = raw != null && Number.isFinite(value);
  const output = document.getElementById(prefix + "-value");
  const bar = document.getElementById(prefix + "-bar");
  const tile = bar?.closest(".signal-tile");
  if (output) output.textContent = valid ? value.toFixed(precision) + unit : "--";
  if (bar) {
    bar.style.width = "100%";
    bar.style.setProperty("--signal-level", valid ? Math.max(0, Math.min(100, value / Math.max(1, scale) * 100)) + "%" : "0%");
  }
  if (tile) {
    tile.classList.toggle("unavailable", !valid);
    tile.classList.toggle("elevated", valid && value / Math.max(1, scale) >= 0.8);
  }
  return valid;
}
function renderNetworkSignals() {
  if (!S) return false;
  const live = S.live || {};
  updateSignalTile("net-ping", live.ping, " ms", 120, 1);
  updateSignalTile("net-jitter", live.jitter, " ms", 40, 1);
  const throughput = [Number(live.netdown), Number(live.netup)].filter(Number.isFinite);
  const transferScale = Math.max(1, ...throughput);
  updateSignalTile("net-down", live.netdown, " Mb/s", transferScale, 1);
  updateSignalTile("net-up", live.netup, " Mb/s", transferScale, 1);
  updateSignalTile("net-conn", Array.isArray(S.net) ? S.net.length : null, "", 100, 0);
  const state = document.getElementById("net-live-state");
  if (state) {
    state.textContent = Array.isArray(S.net) ? "LIVE · " + S.net.length + " CONNECTIONS" : "WAITING FOR CONNECTIONS";
    state.className = "pill " + (Array.isArray(S.net) ? "ok" : "off");
  }
  return true;
}
function renderKernelSignals() {
  if (!S) return false;
  const live = S.live || {};
  const defs = [
    ["kernel-dpc", live.dpc, "%", 8, 2],
    ["kernel-irq", live.irq, "%", 8, 2],
    ["kernel-pagesin", live.pagesin, "/s", 1200, 0],
    ["kernel-pagesout", live.pagesout, "/s", 1200, 0],
    ["kernel-dlat", live.dlat, " ms", 40, 1]
  ];
  for (const [prefix, value, unit, scale, precision] of defs) updateSignalTile(prefix, value, unit, scale, precision);
  const pdh = S.kernel?.pdh || {};
  const state = document.getElementById("kernel-live-state");
  if (state) {
    const ready = pdh.available === true && pdh.state === "streaming";
    state.textContent = ready ? "COUNTERS STREAMING" : String(pdh.state || "COLLECTING").replaceAll("_", " ").toUpperCase();
    state.className = "pill " + (ready ? "ok" : "off");
  }
  return true;
}
function renderCommandVisuals() {
  if (!S) return false;
  const live = S.live || {};
  const specs = [
    ["cpu", "cmd-cpu-value", "cmd-cpu-note", 100, "%", 0, "Host processor load"],
    ["mem", "cmd-mem-value", "cmd-mem-note", 100, "%", 0, "Physical memory pressure"],
    ["gpu", "cmd-gpu-value", "cmd-gpu-note", 100, "%", 0, "Graphics processor load"],
    ["dpc", "cmd-dpc-value", "cmd-dpc-note", 8, "%", 2, "Deferred procedure calls"]
  ];
  for (const [key, valueId, noteId, scale, suffix, precision, description] of specs) {
    const raw = live[key];
    const value = Number(raw);
    const valid = raw != null && Number.isFinite(value);
    const percent = valid ? Math.max(0, Math.min(100, value / scale * 100)) : 0;
    const ring = document.querySelector('[data-cmd-gauge="' + key + '"]');
    if (ring) {
      ring.style.setProperty("--gauge-fill", percent + "%");
      ring.classList.toggle("unavailable", !valid);
      ring.classList.toggle("elevated", valid && percent >= 80);
    }
    const output = document.getElementById(valueId);
    if (output) output.textContent = valid ? value.toFixed(precision) + suffix : "--";
    const note = document.getElementById(noteId);
    if (note) note.textContent = valid ? description : "No current sample";
  }
  const score = Number(live.lag_index);
  const scoreNode = document.getElementById("cmd-node-score");
  if (scoreNode) scoreNode.textContent = Number.isFinite(score) ? Math.round(score) : "--";
  const nodeState = document.getElementById("cmd-node-state");
  if (nodeState) {
    nodeState.textContent = S.game ? "GAME SESSION" : "SYSTEM MONITORING";
    nodeState.dataset.state = S.game ? "game" : "ready";
  }
  const nodeSub = document.getElementById("cmd-node-sub");
  if (nodeSub) nodeSub.textContent = S.game?.name ? String(S.game.name).replace(/\.exe$/i, "") : "Local telemetry stream active";
  const gameState = document.getElementById("cmd-game-state");
  if (gameState) gameState.textContent = S.game ? "GAME ACTIVE" : "DESKTOP";
  const processes = document.getElementById("cmd-node-processes");
  if (processes) processes.textContent = Number(S.proc_total || (S.procs || []).length || 0).toLocaleString();
  const cores = document.getElementById("cmd-node-cores");
  if (cores) cores.textContent = (S.cores || []).length || "--";
  const uptime = document.getElementById("cmd-node-uptime");
  if (uptime) uptime.textContent = dur(Number(S.uptime || 0));
  const canvas = document.getElementById("cmd-performance-chart");
  if (canvas) big(canvas, [
    { k: "cpu", c: "#8B9B8E", l: "CPU" },
    { k: "mem", c: "#8E9B89", l: "MEMORY" },
    { k: "gpu", c: "#909B94", l: "GPU" },
    { k: "dpc", c: "#B58D7D", l: "DPC" }
  ], { lo: 0, hi: 100 });
  return true;
}

/* ---------- tiles ---------- */
const TILES = [
  { k: "cpu", l: "CPU", u: "%", c: "#8E9B89", lo: 0, hi: 100, w: 75, b: 92 },
  { k: "dpc", l: "DPC TIME", u: "%", c: "#B18D84", lo: 0, hi: null, w: 3, b: 8, d: 1 },
  { k: "mem_free_mb", l: "FREE RAM", u: "MB", c: "#879889", lo: 0, hi: null, w: 2500, b: 1200, inv: 1 },
  { k: "pagesout", l: "PAGE EVICT", u: "/s", c: "#A31C1B", lo: 0, hi: null, w: 100, b: 400 },
  { k: "dlat", l: "DISK LATENCY", u: "ms", c: "#A31C1B", lo: 0, hi: null, w: 12, b: 40, d: 1 },
  { k: "gpu", l: "GPU 3D", u: "%", c: "#8E9B89", lo: 0, hi: 100, w: 999, b: 999 },
  { k: "gputemp", l: "GPU TEMP", u: "°C", c: "#A31C1B", lo: 30, hi: 100, w: 80, b: 87 },
  { k: "ping", l: "PING", u: "ms", c: "#879889", lo: 0, hi: null, w: 40, b: 80, d: 1 },
  { k: "jitter", l: "JITTER", u: "ms", c: "#A31C1B", lo: 0, hi: null, w: 8, b: 20, d: 1 },
  { k: "cpuperf", l: "CPU CLOCK", u: "%", c: "#8E9B89", lo: 0, hi: 130, w: 80, b: 60, inv: 1 },
  { k: "pagesin", l: "HARD FAULTS", u: "/s", c: "#B18D84", lo: 0, hi: null, w: 1500, b: 5000 },
  { k: "netdown", l: "NET DOWN", u: "Mb/s", c: "#879889", lo: 0, hi: null, w: 9e9, b: 9e9, d: 1 },
];
function buildTiles() { $("#tiles").innerHTML = TILES.map(t => `<div class="tile" id="t-${t.k}"><div class="k"><span>${t.l}</span><span id="tk-${t.k}"></span></div><div class="v"><span id="tv-${t.k}">--</span><small>${t.u}</small></div><canvas id="tc-${t.k}"></canvas></div>`).join(""); }
function updTiles() {
  TILES.forEach(t => {
    const v = S.live[t.k]; if (v == null) { $("#t-" + t.k).style.opacity = .35; return; } $("#t-" + t.k).style.opacity = 1;
    $("#tv-" + t.k).textContent = fmt(v, t.d || 0);
    const bad = t.inv ? v < t.b : v > t.b, warn = t.inv ? v < t.w : v > t.w;
    $("#t-" + t.k).className = "tile" + (bad ? " bad" : warn ? " warn" : "");
    spark($("#tc-" + t.k), t.k, bad ? "#C35A54" : warn ? "#A31C1B" : t.c, t.lo, t.hi);
  });
}

/* ---------- command view ---------- */
function updHero() {
  const v = S.live.lag_index ?? 0, col = v < 20 ? "#8E9B89" : v < 45 ? "#A31C1B" : "#C35A54";
  $("#arc").style.strokeDashoffset = 653.5 * (1 - v / 100); $("#arc").style.stroke = col;
  $("#c-num").textContent = fmt(v); $("#h-lag").textContent = fmt(v);
  const st = $("#c-st"); st.textContent = v < 12 ? "OPTIMAL" : v < 25 ? "NOMINAL" : v < 45 ? "ELEVATED" : v < 70 ? "DEGRADED" : "CRITICAL"; st.setAttribute("fill", col);
  const g = S.game; $("#c-game").textContent = g ? g.name.replace(".exe", "") + " · " + fmt(g.cpu, 0) + "% CPU · " + fmt(g.mem) + " MB" : "no game detected";
  const p = $("#p-game"); p.textContent = g ? "GAME MODE · " + g.name.replace(/-Win64.*|\.exe/g, "") : "STANDBY"; p.className = "pill " + (g ? "game" : "off");
  const a = S.ai, pa = $("#p-ai"); pa.textContent = a.online ? "AI · " + (a.busy ? a.busy.toUpperCase() + " THINKING" : "ONLINE") : "AI OFFLINE"; pa.className = "pill " + (a.online ? "ok" : "off");
  const sy = S.system || {};
  $("#c-plan").textContent = "PLAN " + (sy.power_plan || "--").toUpperCase(); $("#c-plan").className = "pill" + (/balanced|saver/i.test(sy.power_plan || "") ? " game" : "");
  $("#c-vbs").textContent = "VBS " + (sy.vbs == null ? "--" : sy.vbs ? "ON" : "OFF"); $("#c-vbs").className = "pill" + (sy.vbs ? " game" : "");
  const vg = (S.services.vanguard || {}); $("#c-vg").textContent = "VANGUARD " + (vg.vgk || "--").toUpperCase(); $("#c-vg").className = "pill " + (vg.vgk === "running" ? "ok" : "off");
  const cs = S.cores || []; $("#c-cores").textContent = cs.length + " logical";
  const box = $("#cores"); if (box.children.length !== cs.length) box.innerHTML = cs.map(() => "<i></i>").join("");
  cs.forEach((c, i) => { box.children[i].style.height = Math.max(3, c * .64) + "px"; box.children[i].className = c > 85 ? "h" : ""; });
  $("#culp").innerHTML = (S.culprits || []).map(c => `<div class="act"><div class="d"><b>${esc(c.name)}</b><span>caused ${c.n} spike${c.n > 1 ? "s" : ""}</span></div><div class="bar" style="width:90px"><i style="width:${Math.min(100, c.n * 12)}%;background:linear-gradient(90deg,#A31C1B,#A31C1B)"></i></div></div>`).join("") || '<div class="empty">no culprits caught yet - background is clean</div>';
}

/* ---------- activity ---------- */
function lnHTML(r) { return `<div class="ln ${esc(r.level)}"><span class="t">${hms(r.ts)}</span><span class="s">${esc(r.src)}</span><span class="m">${esc(r.msg)}</span></div>`; }
function buildChips() { $("#chips").innerHTML = Object.keys(lv).map(k => `<button class="chip on" data-l="${k}">${k.toUpperCase()}</button>`).join(""); $$("#chips .chip").forEach(b => b.onclick = () => { lv[b.dataset.l] ^= 1; b.classList.toggle("on", !!lv[b.dataset.l]); renderFeed(); }); }
function renderFeed() { const q = $("#a-q").value.toLowerCase(); const rows = LOGS.filter(r => lv[r.level] && (!q || (r.src + r.msg).toLowerCase().includes(q))).slice(-400); const f = $("#feed"); const stick = f.scrollTop + f.clientHeight >= f.scrollHeight - 30; f.innerHTML = rows.map(lnHTML).join(""); if (stick) f.scrollTop = f.scrollHeight; $("#a-n").textContent = LOGS.length + " events"; }
function addLog(r) { LOGS.push(r); if (LOGS.length > 1500) LOGS.shift(); const t = $("#ticker"); t.insertAdjacentHTML("beforeend", lnHTML(r)); while (t.children.length > 40) t.firstChild.remove(); t.scrollTop = t.scrollHeight; if (view === "act" && !paused) renderFeed(); }
function updHeart() {
  const now = S.now, rows = Object.entries(S.heart).sort();
  $("#heart").innerHTML = "<tr><th>Collector</th><th>Every</th><th>Runs</th><th>Last</th><th>Detail</th></tr>" + rows.map(([n, h]) => {
    const age = now - h.last, st = h.every === 0 ? "late" : age < h.every * 2.5 + 3 ? "" : age < h.every * 6 + 10 ? "late" : "dead";
    return `<tr><td><span class="dot ${st}"></span>${esc(n)}</td><td>${h.every ? h.every + "s" : "-"}</td><td>${h.runs}</td><td>${fmt(age, 0)}s ago</td><td style="color:${h.err ? "#C35A54" : "#829087"}">${esc(h.err || h.note)}</td></tr>`;
  }).join("");
}

/* ---------- insights ---------- */
let INS = [];
function renderIns() { $("#ins").innerHTML = INS.slice(0, 7).map(i => `<div class="ins ${esc(i.sev)}"><time>${hms(i.ts)}</time><b>${esc(i.title)}</b><span>${esc(i.detail)}${i.culprit ? " · " + esc(i.culprit) : ""}</span></div>`).join("") || '<div class="empty">all clear - no problems detected</div>'; $("#i-n").textContent = INS.length + " total"; }

/* ---------- processes: full identity, path and interactive-session facts ---------- */
let sortK = "cpu", sortD = -1, PROC_ROWS = [], PROC_META = { total: 0, matched: 0, sampled_at: 0, updated_at: 0 }, procFetchBusy = false, procLastFetch = 0, procQueryTimer = 0;
function procIdentity(r) { return `${r.pid}:${Number(r.create_time || 0).toPrecision(15)}`; }
function updProc() {
  const rows = PROC_ROWS.slice().sort((a, b) => {
    const av = a[sortK] ?? "", bv = b[sortK] ?? "";
    return (typeof av === "string" ? String(av).localeCompare(String(bv)) : Number(av) - Number(bv)) * sortD;
  });
  const mx = Math.max(1, ...rows.map(r => Number(r.cpu || 0)));
  const recs = S?.proc_recommendations || [];
  const recKeys = new Set(recs.map(procIdentity));
  const header = [["name", "PROCESS / PATH"], ["pid", "PID"], ["cpu", "CPU %"], ["mem", "RAM MB"], ["io", "IO MB/s"], ["thr", "THREADS"], ["session_id", "SESSION / WINDOWS"]];
  const body = rows.map(r => {
    const app = r.app_kind || (r.session_id === 0 ? "SESSION 0 · SERVICE / SYSTEM" : "SESSION UNKNOWN");
    const canReview = r.onscreen_windows > 0 && r.session_id > 0 && r.path_state === "present" && r.exe;
    // Process termination is a dangerous, intentionally disabled action tier.
    const review = canReview ? `<span class="tag warn" title="Arbitrary process close is disabled by the dangerous-action policy">CLOSE DISABLED · DANGEROUS</span>` : `<span class="tag mu">NO GUI CLOSE</span>`;
    return `<tr><td style="min-width:270px;max-width:560px"><b>${esc(r.name)}</b> ${recKeys.has(procIdentity(r)) ? '<span class="tag warn">RESOURCE REVIEW</span>' : ""}<small class="proc-path" title="${esc(r.exe || "Executable path unavailable")}">${esc(r.exe || "Executable path unavailable")}</small><small>${esc(r.path_state || "path unknown")} · parent ${esc(r.parent_name || "--")} (${esc(r.parent_pid ?? "--")})</small></td><td>${r.pid}<small>${fmt(r.create_time, 3)}</small></td><td><div class="bar"><i style="width:${Math.min(100, Number(r.cpu || 0) / mx * 100)}%"></i></div>${fmt(r.cpu, 1)}</td><td>${fmt(r.mem)}</td><td>${fmt(r.io, 3)}</td><td>${esc(r.thr ?? "--")} / ${esc(r.handles ?? "--")} handles</td><td>${esc(r.session_id ?? "unknown")}<small>${esc(app)} · ${r.visible_windows || 0} visible / ${r.onscreen_windows || 0} on-screen · ${r.cloaked_windows || 0} cloaked${r.foreground ? " · FOREGROUND" : ""}</small>${review}</td></tr>`;
  }).join("");
  const q = document.querySelector("#ptab");
  q.innerHTML = "<tr>" + header.map(([k,l]) => `<th data-k="${k}">${l}${sortK === k ? (sortD < 0 ? " ▼" : " ▲") : ""}</th>`).join("") + "</tr>" + (body || '<tr><td colspan="7"><div class="empty">No processes match this filter.</div></td></tr>');
  $$("#ptab th[data-k]").forEach(t => t.onclick = () => { sortD = sortK === t.dataset.k ? -sortD : -1; sortK = t.dataset.k; updProc(); });
  const fresh = PROC_META.updated_at ? new Date(PROC_META.updated_at * 1000).toLocaleTimeString() : "not yet sampled";
  $("#p-n").textContent = `${PROC_META.matched}/${PROC_META.total} process records · ${PROC_META.inaccessible || 0} metadata-inaccessible · refreshed ${fresh}`;
  const reviewRows = recs.filter(r => PROC_ROWS.some(p => procIdentity(p) === procIdentity(r)));
  const visibleCount = PROC_ROWS.filter(row => Number(row.session_id) > 0 && Number(row.onscreen_windows || 0) > 0).length;
  const serviceCount = PROC_ROWS.filter(row => Number(row.session_id) === 0).length;
  const setProcessValue = (id, value) => { const element = document.getElementById(id); if (element) element.textContent = Number(value || 0).toLocaleString(); };
  setProcessValue("proc-live-total", PROC_META.total);
  setProcessValue("proc-live-visible", visibleCount);
  setProcessValue("proc-live-services", serviceCount);
  setProcessValue("proc-live-review", reviewRows.length);
  const liveState = document.getElementById("proc-live-state");
  if (liveState) {
    liveState.textContent = PROC_META.sampled_at ? "LIVE SNAPSHOT" : "WAITING";
    liveState.className = "pill " + (PROC_META.sampled_at ? "ok" : "off");
  }
  const bars = document.getElementById("proc-load-bars");
  if (bars) {
    const top = PROC_ROWS.slice().sort((a,b) => Number(b.cpu || 0) - Number(a.cpu || 0)).slice(0, 12);
    const peak = Math.max(1, ...top.map(row => Number(row.cpu || 0)));
    bars.innerHTML = top.map((row, index) => {
      const value = Math.max(2, Math.min(100, Number(row.cpu || 0) / peak * 100));
      return `<div class="proc-load-item" title="${esc(row.name)} · ${fmt(row.cpu,1)}% CPU"><span>${String(index+1).padStart(2,"0")}</span><i style="--proc-level:${value}%"></i><b>${esc(String(row.name || "process").replace(/\.exe$/i,""))}</b><small>${fmt(row.cpu,1)}%</small></div>`;
    }).join("") || '<span class="empty">No process samples are available yet.</span>';
  }
  const box = $("#proc-recs");
  if (box) box.innerHTML = reviewRows.map(r => `<div class="row"><div><b>${esc(r.name)} · PID ${r.pid}</b><small>${esc(r.reason)} · CPU ${fmt(r.cpu,1)}% · RAM ${r.mem} MB · ${r.observations} consecutive samples</small><small class="proc-path">${esc(r.exe)}</small></div><span class="tag warn">REVIEW ONLY</span></div>`).join("") || '<div class="empty">No sustained background resource-use candidate currently meets the conservative review threshold.</div>';
}
async function loadProcesses(force = false) {
  if (procFetchBusy || (view !== "proc" && !force)) return PROC_META.sampled_at > 0;
  const q = $("#p-q")?.value || "";
  if (!force && Date.now() - procLastFetch < 4500) { updProc(); return PROC_META.sampled_at > 0; }
  procFetchBusy = true;
  try {
    const endpoint = "/api/processes?limit=2000&q=" + encodeURIComponent(q);
    let d = await api(endpoint);
    // The agent collector owns process enumeration. If the page races the
    // collector's first Windows scan, wait briefly for its real snapshot.
    for (let attempt = 0; force && !d.error && !d.sampled_at && attempt < 16; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 250));
      d = await api(endpoint);
    }
    if (d.error) throw new Error(d.error);
    // Deduplicate on process-instance identity, not PID (Windows reuses PIDs).
    const unique = new Map();
    for (const row of (d.rows || [])) unique.set(procIdentity(row), row);
    PROC_ROWS = [...unique.values()]; PROC_META = { total: d.total || 0, matched: d.matched ?? PROC_ROWS.length, inaccessible: d.inaccessible || 0, sampled_at: d.sampled_at || 0, updated_at: d.updated_at || 0 };
    updProc(); procLastFetch = Date.now();
    return PROC_META.sampled_at > 0;
  } catch (e) { toast("Process inventory: " + e.message, "warn"); return false; }
  finally { procFetchBusy = false; }
}
function maybeRefreshProcesses() { if (view === "proc" && Date.now() - procLastFetch > 5000) loadProcesses(true); }

function updNet() {
  renderNetworkSignals();
  $("#ntab").innerHTML = "<tr><th>Process</th><th>Remote</th><th>Port</th></tr>" + S.net.filter(c => { const q = ($("#n-q").value || "").toLowerCase(); return !q || (c.proc + " " + c.ip + " " + c.port).toLowerCase().includes(q); }).map(c => `<tr><td>${esc(c.proc)}</td><td>${esc(c.ip)}</td><td>${c.port}</td></tr>`).join(""); $("#n-n").textContent = S.net.length + " established";
  big($("#nc-ping"), [{ k: "ping", c: "#879889", l: "PING ms" }, { k: "jitter", c: "#A31C1B", l: "JITTER ms" }]);
  big($("#nc-thr"), [{ k: "netdown", c: "#8E9B89", l: "DOWN Mb/s" }, { k: "netup", c: "#A31C1B", l: "UP Mb/s" }]);
}
let kernelArchiveLast = 0;
async function loadKernelArchive() {
  kernelArchiveLast = Date.now();
  const key = $("#kernel-archive-key")?.value || "dpc";
  const table = $("#kernel-archive");
  if (!table) return;
  table.innerHTML = '<tr><td>Loading archived samples…</td></tr>';
  try {
    const d = await api("/api/metrics/archive?metric=" + encodeURIComponent(key) + "&limit=500");
    if (d.error) throw new Error(d.error);
    table.innerHTML = "<tr><th>HOUR (LOCAL)</th><th>SAMPLES</th><th>AVG</th><th>MIN</th><th>MAX</th></tr>" +
      (d.rows || []).map(r => `<tr><td>${new Date(r.hour_epoch * 3600000).toLocaleString()}</td><td>${esc(r.samples)}</td><td>${fmt(r.avg, 3)}</td><td>${fmt(r.min, 3)}</td><td>${fmt(r.max, 3)}</td></tr>`).join("") ||
      '<tr><td colspan="5"><div class="empty">No archived samples yet. Hourly rollups appear after raw samples age beyond the retention window.</div></td></tr>';
    return true;
  } catch (e) {
    table.innerHTML = `<tr><td>${esc(e.message || "archive unavailable")}</td></tr>`;
    return false;
  }
}
function updKer() {
  renderKernelSignals();
  big($("#kc-dpc"), [{ k: "dpc", c: "#B18D84", l: "PDH DPC %" }, { k: "irq", c: "#A31C1B", l: "PDH IRQ %" }]);
  big($("#kc-pg"), [{ k: "pagesin", c: "#8E9B89", l: "PAGES IN/s" }, { k: "pagesout", c: "#A31C1B", l: "PAGES OUT/s" }, { k: "pagefaults", c: "#B18D84", l: "PAGE FAULTS/s" }]);
  const k = S.kernel || {}, pdh = k.pdh || {}, etw = k.etw || {};
  const age = pdh.last_sample ? `${Math.max(0, Math.round(Date.now()/1000-pdh.last_sample))}s ago` : "no samples yet";
  $("#kernel-health").innerHTML = `<div class="row"><b>PDH / typeperf counters</b><span class="tag ${pdh.available && pdh.state === "streaming" ? "ok" : "bad"}">${esc(pdh.state || "unknown")}</span></div><small>${esc(pdh.source || "No source reported")} · ${esc(pdh.samples || 0)} samples · ${esc(age)}</small><small>${esc(pdh.counters?.length || 0)} requested counter(s) · ${esc(pdh.unsupported?.length || 0)} unsupported · ${esc(pdh.error || "")}</small><div class="row"><b>WPR / ETW session</b><span class="tag ${etw.recording === true ? "ok" : etw.recording === false ? "mu" : "bad"}">${etw.recording === true ? "RECORDING" : etw.recording === false ? "IDLE" : "UNKNOWN"}</span></div><small>${esc(etw.source || "Windows Performance Recorder")} · checked ${etw.checked_at ? new Date(etw.checked_at*1000).toLocaleTimeString() : "never"}</small><small>${esc(etw.error || "")}</small><small class="proc-path">${esc(etw.status_text || "No WPR status output available")}</small><small>Live paging/DPC values are PDH counters. ETW event payloads are not decoded into a live paging timeline yet; approved WPR captures are retained as ETL for WPA/GPUView analysis.</small>`;
  const g = S.gpu || {}, kv = o => Object.entries(o).map(([k, v]) => `<i>${k}</i><span>${esc(v)}</span>`).join("");
  $("#gpu").innerHTML = g.name ? kv({ Model: g.name, Temp: g.temp + " °C", Load: g.util + " %", Clock: g.clk + " / " + g.maxclk + " MHz", Power: g.pwr + " / " + g.pwrlim + " W", VRAM: g.vram + " / " + g.vramtot + " MB", Throttle: (g.throttle || []).join(", ") || "none" }) : '<span class="empty">No NVIDIA GPU telemetry; adapter may be non-NVIDIA or driver tool unavailable.</span>';
  const sy = S.system || {}, vg = S.services.vanguard || {};
  $("#sys").innerHTML = kv({ "Power plan": sy.power_plan || "--", "VBS / HVCI": sy.vbs == null ? "unknown" : sy.vbs ? "ON" : "OFF", "Defender RT": sy.defender_rt == null ? "unknown" : sy.defender_rt ? "ON" : "OFF", "OS uptime": (sy.uptime_h ?? "--") + " h", Battery: sy.battery ? sy.battery.pct + "% " + (sy.battery.plugged ? "plugged" : "ON BATTERY") : "n/a", Services: (S.services.running ?? "--") + " / " + (S.services.total ?? "--"), "vgc / vgk": (vg.vgc || "--") + " / " + (vg.vgk || "--"), "Autoruns": S.autoruns ?? "--", Processes: S.proc_total });
  $("#traces").innerHTML = (S.traces || []).slice().reverse().map(t => `<div class="act"><div class="d"><b>${esc(String(t.file || "trace").split(/[\\/]/).pop())}</b><span>${t.mb} MB · ${hms(t.ts)} · ${t.exists === false ? "FILE MISSING" : "FILE PRESENT"}</span><small class="proc-path">${esc(t.file || "")}</small></div></div>`).join("") || '<div class="empty">No captured ETL traces. PDH graphs above do not mean ETW is recording.</div>';
}

/* ---------- intel / ai / control ---------- */
async function loadIntel() { const d = await apiRetry("/api/intel", 1); if (d.error || !Array.isArray(d)) throw new Error(d.error || "Invalid intelligence feed"); $("#intel").innerHTML = d.map(g => `<div style="margin-bottom:14px"><div style="font:12px var(--mo);color:var(--or);letter-spacing:.1em">&gt; ${esc(g.q)}</div>` + g.items.map(i => `<div class="ref"><b><a href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a></b><span>${esc(i.src)} · ${esc(i.snippet)}</span></div>`).join("") + "</div>").join("") || '<div class="empty">crawler is warming up - first results in ~30 s. Or search above.</div>'; return true; }
function addTr(t) { const d = document.createElement("div"); d.className = "msg " + t.role; d.innerHTML = `<small>${esc(t.role === "user" ? "you" : t.role + " · " + t.model)} · ${hms(t.ts)}</small>${esc(t.text)}`; const b = $("#tr"); b.appendChild(d); b.scrollTop = b.scrollHeight; }
function updAI() {
  const a = S.ai || {}, u = a.usage || {}, rt = ST?.agent || {};
  $("#m-fast").textContent = a.fast || "--"; $("#m-deep").textContent = a.deep || "--"; $("#n-fast").classList.toggle("act", a.busy === "fast"); $("#n-deep").classList.toggle("act", a.busy === "deep"); $("#lnk").classList.toggle("on", !!a.busy);
  if (a.status) $("#ai-status").textContent = a.status; $("#ai-url").textContent = a.online ? a.models.length + " models installed" : (a.error || "Ollama offline");
  if ($("#ai-runtime")) $("#ai-runtime").innerHTML = `<div class="row"><b>Agent process</b><span class="tag ${rt.pid ? "ok" : "bad"}">${rt.pid ? "RUNNING" : "UNKNOWN"}</span></div><small>PID ${esc(rt.pid ?? "--")} · ${esc(rt.execution_context || "context unknown")} · desktop access ${rt.desktop_access_expected ? "available in this session" : "not expected"}</small><small>${esc(rt.executable || "")} · ${esc(rt.username || "")}</small><small>Agent CPU ${fmt(rt.cpu_percent, 1)}% · RAM ${fmt(rt.rss_mb, 1)} MB (${fmt(rt.memory_percent, 2)}%) · ${esc(rt.threads ?? "--")} threads · ${esc(rt.handles ?? "--")} handles</small><small>Agent I/O read ${esc(rt.io_read_bytes == null ? "unknown" : (rt.io_read_bytes / 1048576).toFixed(1) + " MB")} · write ${esc(rt.io_write_bytes == null ? "unknown" : (rt.io_write_bytes / 1048576).toFixed(1) + " MB")}</small><div class="row"><b>Inference</b><span class="tag ${a.online ? "ok" : "bad"}">${a.busy ? "BUSY · " + esc(a.busy) : a.online ? "IDLE / READY" : "OFFLINE"}</span></div><small>Current task: ${esc(a.current_task || "none")} · model: ${esc(a.current_model || "none")}</small><small>Requests ${u.requests || 0} · success ${u.successes || 0} · failures ${u.failures || 0} · last latency ${fmt(u.last_duration_s, 2)}s</small><small>Usage history persists across agent restarts · retention: ${esc(u.history_limit || "all stored requests")}</small><small>Prompt tokens ${esc(u.last_prompt_tokens ?? "unknown")} · output tokens ${esc(u.last_output_tokens ?? "unknown")} · last model ${esc(u.last_model || "--")}</small><small>RAM headroom ${fmt(a.model_policy?.available_memory_gib, 2)} GiB · route ${esc(a.model_policy?.reason || "not evaluated")}</small>`;
}
const NICE = { wpr_trace: "Capture WPR diagnostic trace", etw_capture: "Capture kernel ETW window" };
let ACTION_ROWS = [];
let actionsLoaded = false;
let actionsFetchPromise = null;
async function getActionRows(force = false) {
  if (!force && actionsLoaded) return ACTION_ROWS;
  if (actionsFetchPromise) return actionsFetchPromise;
  actionsFetchPromise = (async () => {
    const rows = await apiRetry("/api/actions", 1);
    if (!Array.isArray(rows)) throw new Error(rows?.error || "Invalid action history response");
    ACTION_ROWS = rows;
    actionsLoaded = true;
    return ACTION_ROWS;
  })();
  try { return await actionsFetchPromise; }
  finally { actionsFetchPromise = null; }
}
async function loadActions() {
  const a = await getActionRows(true), p = a.filter(x => x.state === "pending");
  $("#b-act").hidden = !p.length; $("#b-act").textContent = p.length;
  $("#pend").innerHTML = p.map(x => `<div class="act"><div class="d"><b>${esc(x.desc)}</b><span>${esc(x.risk || "unknown risk")} · risk ${esc(x.risk_score ?? "--")}/100 · ${esc(x.priority || "normal")} priority · confidence ${Math.round(Number(x.confidence || 0) * 100)}% · ${esc(x.origin)}</span><small>${esc(x.approval_decision || "manual_approval")} · ${esc(x.approval_reason || x.result || "")}</small></div>${x.approval_decision === "blocked" ? '<span class="tag bad">BLOCKED</span>' : x.approval_decision === "auto_approved" ? '<span class="tag ok">AUTO APPROVED</span>' : `<button class="btn sm" data-r="${x.id}">APPROVE</button>`}<button class="btn sm or" data-d="${x.id}">DISMISS</button></div>`).join("") || '<div class="empty">nothing waiting for approval</div>';
  $$("[data-r]").forEach(b => b.onclick = async () => {
    const item = p.find(x => x.id === +b.dataset.r);
    let confirmed = false;
    if (item?.risk === "medium") confirmed = confirm("Approve this MEDIUM-RISK system adjustment? SENTINEL captured a before-state and will offer rollback. Review its reason before continuing.");
    else if (item?.kind === "terminate_process") confirmed = confirm("Approve a graceful WM_CLOSE request for this reviewed GUI app? SENTINEL will not force-kill it.");
    else confirmed = true;
    if (!confirmed) return;
    const result = await api("/api/action/run", { id: +b.dataset.r, confirmed: item?.risk === "medium" || item?.kind === "terminate_process" });
    if (result.result?.startsWith("rejected")) toast(result.result, "bad");
    else toast(result.result || "Action submitted", "ok");
    loadActions();
  });
  $$("[data-d]").forEach(b => b.onclick = async () => { await api("/api/action/dismiss", { id: +b.dataset.d }); loadActions(); });
  $("#hist").innerHTML = a.filter(x => x.state !== "pending").slice(0, 14).map(x => `<div class="act"><div class="d"><b>${esc(x.desc)}</b><span>${esc(x.state)} · ${esc(x.origin)} · ${esc(x.result || "")}</span></div><span class="tag">${hms(x.ts)}</span></div>`).join("") || '<div class="empty">no actions yet</div>';
  return true;
}
function buildCtl() {
  const ap = S.autopilot, policy = S.approval_policy || {}, lab = { wpr_trace: ["Auto WPR diagnostic", "bounded, read-only capture; never stops an existing trace"], etw_capture: ["Auto kernel ETW windows", "short trace windows only while a game is active"] };
  $("#auto").innerHTML = Object.keys(lab).map(k => `<label class="tog"><span>${lab[k][0]}<small>${lab[k][1]}</small></span><input type="checkbox" class="sw" data-ap="${k}" ${ap[k] ? "checked" : ""}></label>`).join("")
    + `<div class="ph" style="padding:12px 0 4px;border-top:1px solid var(--line)">AUTONOMY MASTER CONTROL<em>global execution gate</em></div><label class="tog"><span>Enable autonomous execution<small>Required before any safe autopilot or eligible reversible medium-risk action can run without a click. Safeguard checks, action budgets and rollback gates remain mandatory.</small></span><input type="checkbox" class="sw" id="auto-master" ${S.automation_master ? "checked" : ""}></label>`
    + `<div class="ph" style="padding:12px 0 4px;border-top:1px solid var(--line)">AUTONOMOUS APPROVAL POLICY<em>risk-scored · reversible only</em></div><label class="tog"><span>Auto-approve eligible medium-risk changes<small>Only reversible allowlisted game profiles, power plan, timer and Wi-Fi policy; requires five consecutive measured improvements for the same action and game, risk ≤25, confidence ≥92%, a fresh safeguard pass and a verified undo snapshot. Updater pauses and dangerous actions remain manual/blocked.</small></span><input type="checkbox" class="sw" id="auto-medium" ${policy.auto_approve_reversible_medium !== false ? "checked" : ""}></label>`;
  $("#auto-master").onchange = async () => { const control=$("#auto-master"); control.disabled=true; const r=await api("/api/profile",{profile:{automation:control.checked}}); control.disabled=false; if(r.error){control.checked=!control.checked;toast(r.error,"bad");}else{S.automation_master=control.checked;toast("Autonomous execution "+(control.checked?"enabled":"disabled"),"ok");} };
  $("#auto-medium").onchange = async () => { const control=$("#auto-medium"); control.disabled=true; const r=await api("/api/config",{approval_policy:{auto_approve_reversible_medium:control.checked}}); control.disabled=false; if(r.error){control.checked=!control.checked;toast(r.error,"bad");}else{S.approval_policy=S.approval_policy||{};S.approval_policy.auto_approve_reversible_medium=control.checked;toast("Reversible medium-risk approval policy "+(control.checked?"enabled":"disabled"),"ok");} };
  $$("[data-ap]").forEach(c => c.onchange = async () => { c.disabled = true; const r = await api("/api/config", { autopilot: { [c.dataset.ap]: c.checked } }); c.disabled = false; if (r.error) { c.checked = !c.checked; toast(r.error, "bad"); } else toast(`${c.dataset.ap} ${c.checked ? "enabled" : "disabled"} and saved`, "ok"); });
  const a = S.ai, opt = cur => '<option value="">auto</option>' + a.models.map(m => `<option ${m.name === cur ? "selected" : ""} value="${esc(m.name)}">${esc(m.name)} (${m.gb} GB)</option>`).join("");
  $("#cfg").innerHTML = `<div class="tog"><span>FAST model<small>triage every minute</small></span><select id="cf-f">${opt(a.fast)}</select></div><div class="tog"><span>DEEP model<small>verifies serious problems</small></span><select id="cf-d">${opt(a.deep)}</select></div><div class="tog"><span>Ollama URL</span><input id="cf-u" value="${esc(S.cfg.ollama_url)}"></div><label class="tog"><span>Sleep local AI while gaming<small>keeps your GPU/CPU free</small></span><input type="checkbox" class="sw" id="cf-p" ${S.cfg.pause ? "checked" : ""}></label><div class="ph" style="padding:10px 0 4px;border:0">Free cloud deep model<em>Groq / Cerebras / OpenRouter</em></div><label class="tog"><span>Use cloud for DEEP<small>IPs are redacted before sending</small></span><input type="checkbox" class="sw" id="cf-ce" ${S.cfg.cloud.enabled ? "checked" : ""}></label><div class="tog"><span>API URL</span><input id="cf-cu" value="${esc(S.cfg.cloud.url)}"></div><div class="tog"><span>Model</span><input id="cf-cm" value="${esc(S.cfg.cloud.model)}"></div><div class="tog"><span>API key</span><input id="cf-ck" type="password" placeholder="${S.cfg.has_key ? "DPAPI-protected key saved - paste to replace" : "paste key (protected locally on Windows)"}"></div><div style="padding-top:10px"><button class="btn" id="cf-s">SAVE</button></div>`;
  $("#cf-s").onclick = async () => { const b = $("#cf-s"); b.disabled = true; const r = await api("/api/config", { model_fast: $("#cf-f").value, model_deep: $("#cf-d").value, ollama_url: $("#cf-u").value, pause_ai_when_gaming: $("#cf-p").checked, cloud: { enabled: $("#cf-ce").checked, url: $("#cf-cu").value, model: $("#cf-cm").value, key: $("#cf-ck").value } }); b.disabled = false; if (r.error) toast(r.error, "bad"); else { toast(`AI settings saved to SQLite · revision ${r.revision?.revision ?? "?"}`, "ok"); S.cfg.ollama_url = $("#cf-u").value; S.cfg.pause = $("#cf-p").checked; S.cfg.cloud.enabled = $("#cf-ce").checked; S.cfg.cloud.url = $("#cf-cu").value; S.cfg.cloud.model = $("#cf-cm").value; S.cfg.has_key = Boolean(S.cfg.has_key || $("#cf-ck").value.trim()); } };
  $("#runnow").innerHTML = Object.keys(NICE).map(k => `<button class="btn sm" data-k="${k}">${NICE[k]}</button>`).join("");
  $$("#runnow [data-k]").forEach(b => b.onclick = async () => { const r = await api("/api/action/propose", { kind: b.dataset.k }); if (r.id) { await api("/api/action/run", { id: r.id }); toast("Ran: " + NICE[b.dataset.k], "ok"); } loadActions(); });
}

/* ---------- agent runtime, footprint and lifecycle ---------- */
let AGENT_DETAIL = null, agentBusy = false, agentLastLoad = 0;
const AGENT_CPU_HISTORY = [], AGENT_RAM_HISTORY = [];

function agentBytes(value) {
  if (value == null || !Number.isFinite(Number(value))) return "--";
  const n = Number(value);
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(2) + " GB";
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(1) + " MB";
  return (n / 1024).toFixed(1) + " KB";
}
function agentTime(value) {
  if (!value) return "--";
  return new Date(Number(value) * 1000).toLocaleString();
}
function agentSpark(id, values) {
  const svg = $("#" + id);
  if (!svg) return;
  const data = values.slice(-90).filter(Number.isFinite);
  if (data.length < 2) {
    svg.innerHTML = "";
    return;
  }
  const low = Math.min(...data), high = Math.max(...data), span = high - low || 1;
  const points = data.map((v, i) =>
    (i / (data.length - 1) * 356 + 2).toFixed(1) + "," + (39 - (v - low) / span * 33).toFixed(1)
  ).join(" ");
  svg.innerHTML = "<polyline points=\"" + points + "\"></polyline>";
}
function agentPushSample(runtime) {
  if (!runtime) return;
  const cpu = Number(runtime.cpu_percent);
  const ram = Number(runtime.rss_mb);
  if (Number.isFinite(cpu)) {
    AGENT_CPU_HISTORY.push(cpu);
    if (AGENT_CPU_HISTORY.length > 90) AGENT_CPU_HISTORY.shift();
  }
  if (Number.isFinite(ram)) {
    AGENT_RAM_HISTORY.push(ram);
    if (AGENT_RAM_HISTORY.length > 90) AGENT_RAM_HISTORY.shift();
  }
}
function agentStateClass(state) {
  if (state === "healthy" || state === "operational" || state === "running") return "ok";
  if (state === "degraded" || state === "stale") return "warn";
  if (state === "unavailable" || state === "stopped" || state === "error") return "bad";
  return "mu";
}
function renderAgentHealthMap(matrix) {
  const data = matrix && typeof matrix === "object" ? matrix : {};
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const host = document.getElementById("ag-source-map");
  const summary = document.getElementById("ag-map-summary");
  if (!host) return;
  const healthy = Number(data.healthy || 0);
  const degraded = Number(data.degraded || 0) + Number(data.stale || 0);
  const unavailable = Number(data.unavailable || 0);
  const total = Number(data.total || rows.length || 0);
  const toneFor = state => {
    const value = String(state || "").toLowerCase();
    if (["healthy", "operational", "running"].includes(value)) return "healthy";
    if (["degraded", "stale"].includes(value)) return "degraded";
    if (["unavailable", "stopped", "error"].includes(value)) return "unavailable";
    return "unknown";
  };
  if (summary) summary.textContent = total
    ? healthy + " / " + total + " HEALTHY · " + degraded + " NEED ATTENTION · " + unavailable + " UNAVAILABLE"
    : "AWAITING FIRST HEARTBEAT";
  if (!rows.length) {
    host.innerHTML = '<div class="empty">Collector health has not reported a source map yet.</div>';
    return;
  }
  host.innerHTML = rows.map(worker => {
    const tone = toneFor(worker.state);
    const age = worker.age_s == null ? "NO HEARTBEAT" : Math.max(0, Math.round(Number(worker.age_s))) + "s AGO";
    const interval = Number(worker.every_s || 0);
    const note = worker.error || worker.note || "No additional detail";
    return '<article class="agent-source-card ' + tone + '" title="' + esc(note) + '">' +
      '<div class="agent-source-head"><i></i><span>' + esc(String(worker.state || "unknown").toUpperCase()) +
      '</span><small>' + esc(age) + '</small></div>' +
      '<b>' + esc(worker.name || "Collector") + '</b>' +
      '<div class="agent-source-foot"><span>' + (interval > 0 ? "EVERY " + interval + "s" : "EVENT DRIVEN") +
      '</span><small>' + Number(worker.runs || 0).toLocaleString() + ' RUNS</small></div>' +
      '</article>';
  }).join("");
}

function updateAgentView(runtime, matrix, runs, storage) {
  if (!runtime) return;
  const logical = Math.max(1, Number(runtime.logical_processors || 1));
  const cpu = runtime.cpu_percent == null ? null : Number(runtime.cpu_percent);
  const cpuCore = runtime.cpu_one_core_percent == null ? null : Number(runtime.cpu_one_core_percent);
  const ram = runtime.rss_mb == null ? null : Number(runtime.rss_mb);
  const memory = runtime.host_memory || {};
  const totalRam = Number(memory.total_mb || 0);
  const ramShare = ram != null && totalRam > 0 ? ram / totalRam * 100 : null;
  const state = runtime.state || "unknown";
  const stateEl = $("#ag-state");
  stateEl.textContent = state.toUpperCase();
  stateEl.className = "pill " + agentStateClass(state);
  $("#ag-cpu").textContent = cpu == null ? "--" : cpu.toFixed(2) + "%";
  $("#ag-cpu-sub").textContent = cpuCore == null ? "Sampling process CPU" : cpuCore.toFixed(1) + "% of one logical CPU";
  $("#ag-cpu-meter").style.width = Math.max(0, Math.min(100, cpu || 0)) + "%";
  $("#ag-ram").textContent = ram == null ? "--" : ram.toFixed(1) + " MB";
  $("#ag-ram-sub").textContent = runtime.memory_percent == null ? "Agent working set" : Number(runtime.memory_percent).toFixed(2) + "% of host RAM";
  $("#ag-ram-meter").style.width = Math.max(0, Math.min(100, ramShare || 0)) + "%";
  const threadCount = Number(runtime.threads || 0);
  $("#ag-threads").textContent = runtime.threads == null ? "--" : String(threadCount);
  $("#ag-threads-sub").textContent = (runtime.worker_threads || []).length + " named background workers";
  $("#ag-threads-meter").style.width = Math.max(0, Math.min(100, threadCount / Math.max(1, logical * 8) * 100)) + "%";
  $("#ag-handles").textContent = runtime.handles == null ? "--" : Number(runtime.handles).toLocaleString();
  $("#ag-handles-sub").textContent = "Operating-system handles";
  $("#ag-handles-meter").style.width = Math.max(0, Math.min(100, Number(runtime.handles || 0) / 100)) + "%";
  const uptime = Number(runtime.uptime_s || 0);
  $("#ag-uptime").textContent = dur(uptime);
  $("#ag-uptime-sub").textContent = "PID " + (runtime.pid ?? "--") + " · started " + agentTime(runtime.process_started_at);
  $("#ag-uptime-meter").style.width = Math.max(2, Math.min(100, uptime / 86400 * 100)) + "%";

  $("#ag-cpu-core").textContent = cpuCore == null ? "--" : cpuCore.toFixed(1) + "%";
  $("#ag-cpu-core-note").textContent = logical + " logical processor(s) · raw process CPU";
  $("#ag-host-cpu").textContent = runtime.host_cpu_percent == null ? "--" : Number(runtime.host_cpu_percent).toFixed(1) + "%";
  $("#ag-ram-share").textContent = ramShare == null ? "--" : ramShare.toFixed(3) + "%";
  $("#ag-host-ram").textContent = memory.percent == null ? "--" : Number(memory.percent).toFixed(1) + "%";
  $("#ag-host-ram-note").textContent = memory.available_mb == null ? "Host memory unavailable" : Number(memory.available_mb).toLocaleString() + " MB available";
  $("#ag-read").textContent = agentBytes(runtime.io_read_bytes);
  $("#ag-write").textContent = agentBytes(runtime.io_write_bytes);
  $("#ag-logical").textContent = logical;
  agentSpark("ag-cpu-chart", AGENT_CPU_HISTORY);
  agentSpark("ag-ram-chart", AGENT_RAM_HISTORY);

  const currentRun = runtime.run || {};
  $("#ag-run-state").textContent = currentRun.id ? "RUN #" + currentRun.id + " · " + (currentRun.mode || "unknown mode") : "run record unavailable";
  $("#ag-identity").innerHTML = Object.entries({
    "Release version": runtime.version,
    "Administrator token": runtime.is_elevated == null ? "unknown" : (runtime.is_elevated ? "elevated" : "not elevated"),
    "Process ID": runtime.pid,
    "Parent PID": runtime.parent_pid,
    "User": runtime.username,
    "Windows session": runtime.session_id ?? "unknown",
    "Execution context": runtime.execution_context,
    "Desktop access": runtime.desktop_access_expected ? "interactive desktop" : "not confirmed",
    "Python": runtime.python,
    "Platform": runtime.platform,
    "Executable": runtime.executable,
    "Started": agentTime(runtime.process_started_at)
  }).map(([key, value]) => "<i>" + esc(key) + "</i><span>" + esc(value ?? "--") + "</span>").join("");
  $("#ag-storage").innerHTML = storage
    ? "<b>Durable local store</b><br>" + esc(storage.home || "--") + "<br><small>SQLite: " + esc(storage.database || "--") + "</small>"
    : "";

  matrix = matrix || {status:"pending",healthy:0,degraded:0,stale:0,unavailable:0,total:0,rows:[]};
  $("#ag-health-summary").textContent = (matrix.status || "pending") + " · " + (matrix.total || 0) + " monitored functions";
  $("#ag-health-counts").innerHTML = [
    ["HEALTHY", matrix.healthy || 0, "ok"],
    ["DEGRADED", matrix.degraded || 0, "warn"],
    ["STALE", matrix.stale || 0, "warn"],
    ["UNAVAILABLE", matrix.unavailable || 0, "mu"]
  ].map(([label, count, tone]) => "<span class=\"tag " + tone + "\">" + label + " " + count + "</span>").join("");
  const workers = matrix.rows || [];
  renderAgentHealthMap(matrix);
  $("#ag-workers").innerHTML = "<tr><th>STATE</th><th>FUNCTION / COLLECTOR</th><th>INTERVAL</th><th>RUNS</th><th>LAST HEARTBEAT / DETAIL</th></tr>"
    + workers.map(worker => {
      const tone = agentStateClass(worker.state);
      const dot = worker.state === "healthy" ? "" : worker.state === "degraded" || worker.state === "stale" ? "late" : worker.state === "unavailable" ? "off" : "dead";
      const age = worker.age_s == null ? "never" : worker.age_s + "s ago";
      const detail = worker.error || worker.note || "No detail reported";
      return "<tr><td><span class=\"dot " + dot + "\"></span><span class=\"tag " + tone + "\">" + esc(worker.state) + "</span></td>"
        + "<td><b>" + esc(worker.name) + "</b></td><td>" + (worker.every_s ? worker.every_s + "s" : "--") + "</td>"
        + "<td>" + Number(worker.runs || 0).toLocaleString() + "</td><td>" + esc(age) + "<small>" + esc(detail) + "</small></td></tr>";
    }).join("") || "<tr><td colspan=\"5\"><div class=\"empty\">No background functions have reported a heartbeat yet.</div></td></tr>";

  const threads = runtime.worker_threads || [];
  $("#ag-thread-count").textContent = threads.length + " named threads · " + (runtime.threads ?? "--") + " total OS threads";
  $("#ag-threads-list").innerHTML = threads.map(thread =>
    "<div class=\"adv-row\"><div><b>" + esc(thread.name) + "</b><small>" + (thread.daemon ? "Background daemon worker" : "Non-daemon thread") + "</small></div>"
    + "<span class=\"tag " + (thread.alive ? "ok" : "bad") + "\">" + (thread.alive ? "ALIVE" : "STOPPED") + "</span></div>"
  ).join("") || "<div class=\"empty\">The API worker list is not available yet.</div>";

  const runRows = runs || [];
  $("#ag-runs").innerHTML = runRows.map(run => {
    const active = !!run.active;
    return "<div class=\"agent-run\"><span class=\"run-id\">#" + run.id + "</span>"
      + "<div class=\"run-detail\"><b>" + esc(run.mode || "unknown run mode") + " · PID " + esc(run.pid) + "</b>"
      + "<small>" + esc(agentTime(run.started_at)) + " · " + esc(run.executable || "") + "</small>"
      + "<small>" + esc(run.exit_reason || (active ? "Current process is active" : "No exit reason recorded")) + "</small></div>"
      + "<div class=\"run-age\"><span class=\"tag " + (active ? "ok" : "mu") + "\">" + (active ? "ACTIVE" : "CLOSED") + "</span><br>" + dur(Number(run.duration_s || 0)) + "</div></div>";
  }).join("") || "<div class=\"empty\">No agent run history is available.</div>";
}
async function loadAgent(force = false) {
  if (agentBusy || (!force && Date.now() - agentLastLoad < 6000)) return !!AGENT_DETAIL;
  agentBusy = true;
  agentLastLoad = Date.now();
  try {
    const data = await api("/api/agent");
    if (data.error) throw new Error(data.error);
    AGENT_DETAIL = data;
    if (data.runtime) agentPushSample(data.runtime);
    updateAgentView(data.runtime, data.sensor_matrix, data.runs, data.storage);
    return true;
  } catch (error) {
    $("#ag-state").textContent = "API LOST";
    $("#ag-state").className = "pill bad";
    toast("Agent overview unavailable: " + error.message, "warn");
    return false;
  } finally {
    agentBusy = false;
  }
}
function initAgent() {
  $("#ag-refresh").onclick = () => loadAgent(true);
}

/* ---------- main tick ---------- */
let ctlInitialized = false;
function onTick(d) {
  S = d; for (const [k, v] of Object.entries(d.live || {})) { (H[k] ||= []).push(v); if (H[k].length > MAXH) H[k].shift(); }
  if (d.agent) {
    agentPushSample(d.agent);
    if (view === "agent") {
      const previous = AGENT_DETAIL?.runtime || {};
      const runtime = { ...previous, ...d.agent };
      if (!d.agent.run) runtime.run = previous.run;
      if (!d.agent.worker_threads?.length) runtime.worker_threads = previous.worker_threads || [];
      updateAgentView(runtime, d.sensor_matrix || AGENT_DETAIL?.sensor_matrix, AGENT_DETAIL?.runs, AGENT_DETAIL?.storage);
      if (Date.now() - agentLastLoad > 8000) loadAgent();
    }
  }
  $("#h-up").textContent = dur(d.uptime); updHero();
  if (view === "cmd") { updTiles(); updMetrics(); renderCommandVisuals(); }
  if (view === "tsk") updTasks();
  if (view === "act") updHeart();
  if (view === "proc") maybeRefreshProcesses();
  if (view === "net") updNet();
  if (view === "ker") { updKer(); if (Date.now() - kernelArchiveLast > 30000) loadKernelArchive(); }
  if (view === "adv" && Date.now() - advLastLoad > 8000) loadAdvanced();
  if (view === "ai") updAI();
  if (view === "sys") maybeRefreshSystem();
  if (view === "ctl" && !ctlInitialized) { buildCtl(); loadActions(); ctlInitialized = true; }
}
function show(v) {
  if (!TITLES[v]) return;
  view = v;
  $("#vtitle").textContent = TITLES[v];
  try { localStorage.setItem("sv", v); } catch (e) { }
  $$(".view").forEach(element => element.classList.toggle("on", element.id === "v-" + v));
  $$("#nav button[data-v]").forEach(button => {
    const selected = button.dataset.v === v;
    button.classList.toggle("on", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });

  // Recently opened workspaces render from their short-lived local cache;
  // inactive screens fetch only when requested.
  if (pageIsWarm(v)) {
    if (v === "cmd") { updHero(); updTiles(); updMetrics(); renderCommandVisuals(); }
    else if (v === "act") { updHeart(); renderFeed(); }
    else if (v === "net" && S) updNet();
    else if (v === "ai" && S) updAI();
    else if (v === "tsk" && S) updTasks();
    else if (v === "maint") loadMaintenance(false);
    return;
  }

  if (!S) {
    if (v === "eng") loadEngines();
    else if (v === "agent") loadAgent(true);
    else if (v === "activityx") loadActivityIntelligence(true);
    else if (v === "intelx") loadIntelligence();
    else if (v === "ker") loadKernelArchive();
    else if (v === "adv") loadAdvanced(true);
    else if (v === "sys") loadSys(true);
    else if (v === "proc") loadProcesses(true);
    else if (v === "evi") loadEvi();
    else if (v === "fc") loadFC();
    else if (v === "int") loadIntel();
    else if (v === "tsk") loadHist();
    else if (v === "act") renderFeed();
    else if (v === "ctl") { buildCtl(); loadActions(); ctlInitialized = true; }
    else if (v === "maint") loadMaintenance(false);
    return;
  }
  ({
    cmd: () => { updTiles(); updMetrics(); renderCommandVisuals(); },
    eng: loadEngines,
    agent: () => loadAgent(true),
    act: () => { updHeart(); renderFeed(); },
    proc: () => loadProcesses(true),
    net: updNet,
    ker: () => { updKer(); loadKernelArchive(); },
    adv: () => loadAdvanced(true),
    int: loadIntel,
    activityx: () => loadActivityIntelligence(true),
    intelx: loadIntelligence,
    ai: updAI,
    ctl: () => { buildCtl(); loadActions(); ctlInitialized = true; },
    sys: () => loadSys(true),
    evi: loadEvi,
    tsk: () => { updTasks(); loadHist(); },
    fc: loadFC,
    maint: () => loadMaintenance(false)
  })[v]?.();
}

/* ---------- Windows maintenance workspace ---------- */
let MNT=null,MNT_JOURNAL=[],MNT_DIGEST=null,MNT_POLLING=Object.create(null);
function maintSetOptions(id,rows,value,label,emptyLabel){
  const node=document.getElementById(id);if(!node)return;
  const selected=node.value;
  const options=(rows||[]).map((row,index)=>'<option value="'+esc(String(value(row,index)??""))+'">'+esc(String(label(row,index)))+'</option>');
  node.innerHTML=options.length?options.join(""):'<option value="">'+esc(emptyLabel||"No entries available")+'</option>';
  if((rows||[]).some((row,index)=>String(value(row,index)??"")===selected))node.value=selected;
}
function maintState(state){return ({collecting:"COLLECTING",refreshing:"SCANNING",ready:"READY",degraded:"DEGRADED",unsupported:"WINDOWS ONLY"})[state]||String(state||"UNKNOWN").toUpperCase();}
function renderMaintenance(){
  if(!MNT)return;
  const d=MNT,put=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  put("maint-state",maintState(d.diagnostics_state));
  put("maint-state-note",d.updated_at?"Last scan "+new Date(d.updated_at*1000).toLocaleTimeString():"Read-only inventory is being prepared");
  const privilege=d.privilege||{};
  const elevated=privilege.agent_elevated===true||d.administrator===true;
  put("maint-admin",elevated?"ELEVATED":"STANDARD USER");
  put("maint-admin-note",elevated?"This process has an elevated Windows token.":"UAC is requested only for approved administrator actions.");
  put("maint-budget",String(d.budget?.available_hour??"--")+"/"+String(d.budget?.hour_limit??"--")+" / HR");
  put("maint-budget-note",String(d.budget?.available_day??"--")+" actions available today");
  const guard=d.safeguard||{};
  put("maint-guard",guard.valorant_active?"GAME ACTIVE":(guard.process_detection_complete===false?"UNCERTAIN":"ARMED"));
  put("maint-guard-note",guard.reason||"Mutation gate checks VALORANT and process-observer health");
  put("maint-diag-status",maintState(d.diagnostics_state));
  const kill=document.getElementById("maint-kill-switch"),scheduler=document.getElementById("maint-scheduler");
  const weekly=document.getElementById("maint-weekly"),idle=document.getElementById("maint-idle-minutes");
  if(kill)kill.checked=!!d.kill_switch;
  if(scheduler)scheduler.checked=!!d.scheduler?.scheduler_enabled;
  if(weekly)weekly.checked=d.scheduler?.weekly_diagnostics!==false;
  if(idle&&d.scheduler?.idle_minutes)idle.value=d.scheduler.idle_minutes;
  put("maint-policy-state",d.kill_switch?"ACTIONS BLOCKED":"MANUAL ACTIONS ENABLED");
  maintSetOptions("maint-startup-entry",(d.startup||[]).filter(x=>!x.protected),x=>x.name,x=>x.name+" · "+x.scope,"No eligible startup entries");
  maintSetOptions("maint-adapter",(d.adapters||[]).filter(x=>String(x.Status||"").toLowerCase()==="up"),x=>x.Name,x=>x.Name+" · "+(x.InterfaceDescription||"physical adapter"),"No connected physical adapters");
  const choices=[];
  (d.driver_updates||[]).forEach(update=>{
    const ids=Array.isArray(update.hardware_ids)?update.hardware_ids:[];
    const device=(d.drivers||[]).find(row=>{
      const id=String(row.DeviceID||"").toLowerCase();
      return id&&ids.some(value=>{const hardware=String(value||"").trim().toLowerCase();return hardware&&(id===hardware||id.startsWith(hardware+"\\"));});
    });
    if(device)choices.push({update,device});
  });
  MNT.driverChoices=choices;
  maintSetOptions("maint-driver-choice",choices,(x,i)=>String(i),x=>x.update.title+" · "+x.device.DeviceName,"No hardware-matched driver offers");
  maintSetOptions("maint-driver-rollback",(d.journal||[]).filter(x=>x.action==="driver_install"&&x.undo_available&&x.status==="done"),x=>x.id,x=>"#"+x.id+" · "+(x.result||"exported previous driver"),"No exported previous driver package");
  maintSetOptions("maint-trim-drive",(d.volumes||[]).filter(x=>String(x.filesystem||"").toLowerCase()==="ntfs"),x=>String(x.device||x.mountpoint||"").replace(":\\",""),x=>(x.device||x.mountpoint)+" · "+x.free_gib+" GiB free","No NTFS volumes found");
  maintSetOptions("maint-process",d.top_memory_processes||[],(x,i)=>String(i),x=>x.name+" · "+x.rss_mb+" MiB · PID "+x.pid,"Process inventory not ready");
  const host=document.getElementById("maint-diagnostics");
  if(host){
    const volumes=(d.volumes||[]).map(x=>'<div class="maint-mini-stat"><small>'+esc(x.mountpoint||x.device)+'</small><b>'+esc(x.free_gib)+' GiB FREE</b><span>'+esc(x.used_percent)+'% used · '+esc(x.filesystem||"unknown")+'</span></div>');
    const adapters=(d.adapters||[]).map(x=>'<div class="maint-data-row"><div><b>'+esc(x.Name)+'</b><small>'+esc(x.InterfaceDescription||"Physical adapter")+'</small></div><span class="tag">'+esc(x.Status)+'</span></div>');
    const dns=(d.dns||[]).map(x=>'<div class="maint-data-row"><div><b>'+esc(x.InterfaceAlias)+' · '+esc(x.AddressFamily)+'</b><small>'+esc((x.ServerAddresses||[]).join(" · ")||"Automatic")+'</small></div><span class="tag">DNS</span></div>');
    const processes=(d.top_memory_processes||[]).slice(0,6).map(x=>'<div class="maint-data-row"><div><b>'+esc(x.name)+'</b><small>PID '+esc(x.pid)+' · '+esc(x.exe||"")+'</small></div><span class="tag">'+esc(x.rss_mb)+' MiB</span></div>');
    const drivers=(d.driver_updates||[]).map(x=>'<div class="maint-data-row"><div><b>'+esc(x.title)+'</b><small>Windows Update driver · '+esc((x.hardware_ids||[]).length)+' hardware ID(s)</small></div><span class="tag">OFFERED</span></div>');
    const predictive=(d.predictive||[]).map(x=>'<div class="maint-data-row"><div><b>'+esc(x.kind)+' · '+esc(x.mountpoint||x.sensor||"System")+'</b><small>'+esc(x.note||"Predictive alert only")+'</small></div><span class="tag">'+esc(x.free_gib??x.celsius??"--")+(x.free_gib!=null?" GiB":x.celsius!=null?" °C":"")+'</span></div>');
    const errors=Object.entries(d.source_errors||{}).map(([key,value])=>'<div class="msg warn"><small>'+esc(key)+' DEFERRED / DEGRADED</small>'+esc(value)+'</div>');
    const guided=d.guided_recovery||{},vendor=d.vendor_fan_control||{};
    host.innerHTML=
      '<div class="maint-diag-card"><div class="maint-diag-title">STORAGE / CAPACITY</div><div class="maint-mini-grid">'+(volumes.join("")||'<div class="empty">Volume data unavailable.</div>')+'</div></div>'+
      '<div class="maint-diag-card"><div class="maint-diag-title">PHYSICAL ADAPTERS / DNS</div>'+(adapters.join("")||'<div class="empty">No adapter inventory.</div>')+(dns.join("")||'<div class="empty">No DNS inventory.</div>')+'</div>'+
      '<div class="maint-diag-card"><div class="maint-diag-title">MEMORY CONSUMERS</div>'+(processes.join("")||'<div class="empty">Process data deferred or unavailable.</div>')+'</div>'+
      '<div class="maint-diag-card"><div class="maint-diag-title">DRIVER OFFERS</div>'+(drivers.join("")||'<div class="empty">No hardware-matched update offers.</div>')+'</div>'+
      '<div class="maint-diag-card maint-wide"><div class="maint-diag-title">PREDICTIVE SIGNALS</div>'+(predictive.join("")||'<div class="empty">No disk or thermal threshold approaching. Trends improve as local samples accumulate.</div>')+'</div>'+
      '<div class="maint-diag-card"><div class="maint-diag-title">OEM FAN CONTROL</div><b>'+esc(vendor.manufacturer||"Manufacturer not detected")+'</b><small>'+esc(vendor.model||"")+'</small><p>'+esc(vendor.message||"Use the signed OEM fan utility. Firmware writes are disabled.")+'</p></div>'+
      '<div class="maint-diag-card"><div class="maint-diag-title">GUIDED RECOVERY</div><p>'+esc(guided.game_relocation||"Use the Steam/Epic/Xbox library manager for game relocation.")+'</p><p>'+esc(guided.bios_secure_boot||"BIOS/Secure Boot remain read-only.")+'</p></div>'+
      (errors.length?'<div class="maint-diag-card maint-wide"><div class="maint-diag-title">DEFERRED SOURCES</div>'+errors.join("")+'</div>':"");
  }
  renderMaintenanceIntelligence();
  renderMaintenanceJournal();renderMaintenanceDigest();
}

function renderMaintenanceIntelligence(){
  if(!MNT)return;
  const d=MNT,health=d.system_health||{};
  const host=document.getElementById("maint-health-report");
  if(host){
    const findings=(health.findings||[]).map(item=>
      '<div class="maint-health-row"><span class="maint-severity '+esc(item.severity)+'"></span><div>'+
      '<b>'+esc(item.title)+'</b><small>'+esc(item.detail||"")+'</small>'+
      '<small>Confidence '+Math.round(Number(item.confidence||0)*100)+'% · '+esc((item.allowed_actions||[]).join(", ")||"Guided / observation only")+'</small>'+
      '</div></div>').join("");
    const coverage=Object.entries(health.coverage||{}).filter(([,value])=>value).map(([key])=>key);
    const coverageCount=Number.isFinite(Number(health.coverage_count))?Number(health.coverage_count):coverage.length;
    host.innerHTML='<div class="maint-health-head"><div><small>LOCAL EVIDENCE HEALTH</small>'+
      '<b>'+esc(health.health_score==null?"--":health.health_score+"/100")+'</b>'+
      '<span>'+esc(String(health.state||"collecting").replaceAll("_"," ").toUpperCase())+'</span></div>'+
      '<div class="maint-health-coverage">'+coverageCount+' evidence domains · '+esc(coverage.join(" / ")||"waiting for telemetry")+'</div></div>'+
      (findings||'<div class="empty">No monitored threshold is currently crossed, or more telemetry is needed.</div>')+
      '<small class="maint-health-note">'+esc(health.note||"Local evidence summary. No system changes are made by this report.")+'</small>';
  }
  maintSetOptions("maint-game-choice",d.game_libraries||[],x=>x.game_id,
    x=>x.launcher+" · "+x.name,"No Steam / Epic game manifests discovered");
  const targets=(d.volumes||[]).filter(x=>String(x.filesystem||"").toLowerCase()==="ntfs");
  maintSetOptions("maint-game-target",targets,x=>{
    const value=String(x.device||x.mountpoint||"");
    const match=value.match(/^([A-Z]):/i);
    return match?match[1].toUpperCase():"";
  },x=>x.device+" · "+x.free_gib+" GiB free","No NTFS target volumes detected");
}

function renderMaintenanceJournal(){
  const host=document.getElementById("maint-journal");if(!host)return;
  const rows=MNT_JOURNAL||[];
  host.innerHTML=rows.length?rows.map(row=>{
    const canUndo=row.undo_available&&row.status==="done";
    return '<div class="maint-journal-row"><div><b>'+esc(row.action)+'</b><small>#'+esc(row.id)+' · '+esc(row.status)+' · '+new Date(row.created_at*1000).toLocaleString()+'</small><small>'+esc(row.result||"")+'</small></div><div class="maint-row-actions">'+(canUndo?'<button class="btn sm" data-maint-undo="'+esc(row.id)+'">UNDO</button>':'<span class="tag">GUIDED / NO UNDO</span>')+'</div></div>';
  }).join(""):'<div class="empty">No maintenance operations recorded.</div>';
  host.querySelectorAll("[data-maint-undo]").forEach(button=>button.onclick=async()=>{
    if(!confirm("Undo this change? Current state is checked first; later user changes are preserved."))return;
    try{
      const result=await api("/api/maintenance/undo",{journal_id:Number(button.dataset.maintUndo),confirmed:true});
      if(result.error)throw new Error(result.error);
      toast("Maintenance change reverted","ok");await loadMaintenance(true);
    }catch(error){toast(error.message||String(error),"bad");}
  });
}
function renderMaintenanceDigest(){
  const host=document.getElementById("maint-digest");if(!host||!MNT_DIGEST)return;
  const d=MNT_DIGEST;
  host.innerHTML='<div class="maint-digest-grid"><div><small>COMPLETED</small><b>'+esc(d.completed)+'</b></div><div><small>BLOCKED</small><b>'+esc(d.blocked)+'</b></div><div><small>PENDING</small><b>'+esc(d.pending_approvals)+'</b></div><div><small>FAILED</small><b>'+esc(d.failed)+'</b></div></div><div class="msg"><small>LAST 24 HOURS · '+esc(d.day)+'</small>Completed, blocked, pending and failed operations.</div>';
}
async function loadMaintenance(refresh=false){
  try{
    const suffix=refresh?"?refresh=1":"";
    const values=await Promise.all([api("/api/maintenance/status"+suffix),api("/api/maintenance/journal?limit=50"),api("/api/maintenance/digest"),api("/api/maintenance/privilege")]);
    if(values[0].error)throw new Error(values[0].error);
    MNT=values[0];MNT.privilege=values[3]||{};MNT_JOURNAL=Array.isArray(values[1])?values[1]:[];MNT_DIGEST=values[2]||null;
    renderMaintenance();return true;
  }catch(error){
    const label=document.getElementById("maint-diag-status");if(label)label.textContent="DIAGNOSTICS UNAVAILABLE";
    const host=document.getElementById("maint-diagnostics");if(host)host.innerHTML='<div class="msg warn">'+esc(error.message||error)+'</div>';
    return false;
  }
}
async function maintenancePreview(action,args,label){
  const button=document.activeElement;if(button&&button.tagName==="BUTTON")button.disabled=true;
  try{
    const preview=await api("/api/maintenance/preview",{action,args});
    if(preview.error)throw new Error(preview.error);
    const lines=[label||action].concat(preview.changes||[],preview.warnings||[]);
    if(preview.administrator_required)lines.push("Administrator rights are required.");
    if(preview.restore_point_required)lines.push("A restore point must succeed before the operation begins.");
    if(!confirm(lines.join("\n\n")+"\n\nContinue to final confirmation?"))return;
    const danger=preview.risk==="dangerous"?"\n\nDANGEROUS OPERATION: check the target and consequences.":"";
    if(!confirm("FINAL CONFIRMATION\n\n"+(label||action)+danger+"\n\nExecute this exact one-time preview?"))return;
    const result=await api("/api/maintenance/execute",{preview_token:preview.preview_token,confirmed:true});
    if(result.error)throw new Error(result.error);
    toast(result.elevation_required?"Windows UAC approval requested":"Maintenance job queued","warn");watchMaintenanceJob(result.job_id);
  }catch(error){toast(error.message||String(error),"bad");}
  finally{if(button&&button.tagName==="BUTTON")button.disabled=false;}
}
function watchMaintenanceJob(jobId,attempt=0){
  if(!jobId||attempt>=450||MNT_POLLING[jobId])return;
  MNT_POLLING[jobId]=true;
  setTimeout(async()=>{
    delete MNT_POLLING[jobId];
    try{
      const job=await api("/api/maintenance/job?id="+encodeURIComponent(jobId));
      if(job.error)throw new Error(job.error);
      const title=String(job.state||"queued").toUpperCase();
      const host=document.getElementById("maint-job-list");
      if(host)host.innerHTML='<div class="maint-journal-row"><div><b>'+esc(job.action)+' · '+title+'</b><small>'+esc(job.job_id)+'</small><small>'+esc(job.result||job.error||"")+'</small></div><span class="tag">'+title+'</span></div>'+(host.innerHTML||"");
      const badge=document.getElementById("maint-last-job-state");if(badge)badge.textContent=title;
      if(["done","failed","cancelled","rolled_back"].includes(job.state)){
        toast(job.result||job.error||"Maintenance job "+title,job.state==="done"?"ok":"warn");
        if("Notification"in window&&Notification.permission==="granted"&&document.hidden){try{new Notification("SENTINEL maintenance "+title.toLowerCase(),{body:job.result||job.error||job.action});}catch(e){}}
        await loadMaintenance(true);return;
      }
      watchMaintenanceJob(jobId,attempt+1);
    }catch(error){toast(error.message||String(error),"bad");}
  },4000);
}
function onMaintenanceJob(payload){
  if(!payload)return;
  const badge=document.getElementById("maint-last-job-state");if(badge)badge.textContent=String(payload.state||"UPDATED").toUpperCase();
  if(["done","failed","cancelled","rolled_back"].includes(payload.state)){
    toast(payload.result||payload.error||"Maintenance job updated",payload.state==="done"?"ok":"warn");
    if("Notification"in window&&Notification.permission==="granted"&&document.hidden){try{new Notification("SENTINEL maintenance",{body:payload.result||payload.error||payload.state});}catch(e){}}
    loadMaintenance(true);
  }
}
function initMaintenance(){
  const bind=(id,fn)=>{const node=document.getElementById(id);if(node)node.onclick=fn;};
  bind("maint-refresh",()=>loadMaintenance(true));bind("maint-inventory-refresh",()=>loadMaintenance(true));
  bind("maint-goal-run",async()=>{
    const goal=document.getElementById("maint-goal")?.value.trim()||"";if(!goal)return toast("Describe the goal first","warn");
    try{
      const result=await api("/api/maintenance/goal",{goal});if(result.error)throw new Error(result.error);
      const host=document.getElementById("maint-goal-result");if(!host)return;
      const findings=(result.findings||[]).map(x=>'<div class="maint-data-row"><b>'+esc(x.name||x.type||x.pid||"Finding")+'</b><span>'+esc(x.rss_mb==null?"":x.rss_mb+" MiB")+'</span></div>').join("");
      const recommendations=(result.recommendations||[]).map(x=>'<div class="maint-plan-item"><i></i><span>'+esc(x)+'</span></div>').join("");
      host.innerHTML='<div class="maint-plan"><span class="maint-kicker">LOCAL RULE PLAN · '+esc(result.generated_by)+'</span>'+findings+recommendations+'<div class="msg"><small>CONTROL ENGINE</small>No action was executed. Select a specific operation below to preview it.</div></div>';
    }catch(error){toast(error.message||String(error),"bad");}
  });
  bind("maint-policy-save",async()=>{
    const kill=!!document.getElementById("maint-kill-switch").checked;
    if(MNT?.kill_switch&&!kill&&!confirm("Release the maintenance kill switch? Mutations still require previews, confirmation and the Vanguard safeguard."))return;
    const result=await api("/api/maintenance/policy",{kill_switch:kill,scheduler_enabled:!!document.getElementById("maint-scheduler").checked,
      weekly_diagnostics:!!document.getElementById("maint-weekly").checked,idle_minutes:Number(document.getElementById("maint-idle-minutes").value||15),confirmed:true});
    if(result.error)return toast(result.error,"bad");
    toast("Maintenance safety policy saved","ok");await loadMaintenance(false);
  });
  bind("maint-cleanup-run",()=>maintenancePreview("cleanup",{scope:document.getElementById("maint-cleanup-scope").value},"Temporary / shader cache cleanup"));
  bind("maint-startup-run",()=>{
    const name=document.getElementById("maint-startup-entry").value;if(!name)return toast("Choose a startup entry","warn");
    maintenancePreview("startup_disable",{name},"Disable selected startup app");
  });
  bind("maint-dns-test",async()=>{
    const servers=(document.getElementById("maint-dns-servers").value||"").split(",").map(x=>x.trim()).filter(Boolean);
    const host=document.getElementById("maint-dns-results");
    try{
      const result=await api("/api/maintenance/dns-test",{servers});if(result.error)throw new Error(result.error);
      const rows=(result.results||[]).map(x=>'<div class="maint-data-row"><b>'+esc(x.server)+'</b><span>'+(x.successful>0?esc(x.average_ms)+" ms avg · "+esc(x.successful)+"/3":"FAILED")+'</span></div>').join("");
      if(host)host.innerHTML='<small>RESOLVER BENCHMARK · '+esc(result.query)+'</small>'+rows+'<div class="msg">Fastest responder: '+esc(result.recommended||"none")+'. No settings changed.</div>';
    }catch(error){if(host)host.textContent=error.message||String(error);toast(error.message||String(error),"bad");}
  });
  bind("maint-dns-run",()=>{
    const servers=(document.getElementById("maint-dns-servers").value||"").split(",").map(x=>x.trim()).filter(Boolean);
    const adapter=document.getElementById("maint-adapter").value;if(!adapter)return toast("Choose a connected physical adapter","warn");
    maintenancePreview("dns_set",{interface:adapter,family:document.getElementById("maint-dns-family").value,servers},"Change DNS resolvers");
  });
  bind("maint-adapter-run",()=>{
    const adapter=document.getElementById("maint-adapter").value;if(!adapter)return toast("Choose a connected physical adapter","warn");
    maintenancePreview("adapter_restart",{interface:adapter},"Restart physical network adapter");
  });
  bind("maint-winsock-run",()=>maintenancePreview("winsock_reset",{},"Reset Winsock and TCP/IP"));
  bind("maint-driver-run",()=>{
    const candidate=MNT?.driverChoices?.[Number(document.getElementById("maint-driver-choice").value)];
    if(!candidate)return toast("Select a hardware-matched driver update","warn");
    maintenancePreview("driver_install",{update_id:candidate.update.update_id,device_id:candidate.device.DeviceID},"Install selected Windows Update driver");
  });
  bind("maint-driver-rollback-run",()=>{
    const id=Number(document.getElementById("maint-driver-rollback").value);if(!id)return toast("Select an exported previous driver","warn");
    maintenancePreview("driver_rollback",{journal_id:id},"Restore exported driver package");
  });
  bind("maint-repair-run",()=>maintenancePreview("windows_repair",{target:document.getElementById("maint-repair-target").value},"Run Windows repair"));
  bind("maint-service-run",()=>maintenancePreview("service_restart",{service:document.getElementById("maint-service").value},"Restart allowlisted Windows service"));
  bind("maint-power-run",()=>maintenancePreview("power_mode",{mode:document.getElementById("maint-power-mode").value},"Change Windows power profile"));
  bind("maint-trim-run",()=>{
    const drive=document.getElementById("maint-trim-drive").value;if(!drive)return toast("Select an NTFS volume","warn");
    maintenancePreview("trim_volume",{drive},"Run SSD retrim");
  });
  bind("maint-process-run",()=>{
    const process=MNT?.top_memory_processes?.[Number(document.getElementById("maint-process").value)];
    if(!process)return toast("Select a process from inventory","warn");
    const raw=document.getElementById("maint-affinity").value.trim();let affinity=null;
    if(raw){affinity=raw.split(",").map(x=>Number(x.trim()));if(affinity.some(x=>!Number.isInteger(x)))return toast("Affinity must be comma-separated logical CPU indexes","bad");}
    maintenancePreview("process_tune",{pid:process.pid,create_time:process.create_time,exe:process.exe,priority:document.getElementById("maint-priority").value,affinity},"Tune selected process");
  });
  bind("maint-game-plan",async()=>{
    const gameId=document.getElementById("maint-game-choice").value;
    const targetDrive=document.getElementById("maint-game-target").value;
    const host=document.getElementById("maint-game-plan-result");
    if(!gameId)return toast("Select an installed Steam/Epic game","warn");
    if(!targetDrive)return toast("Select an NTFS target volume","warn");
    try{
      const result=await api("/api/maintenance/game-relocation/plan",{game_id:gameId,target_drive:targetDrive});
      if(result.error)throw new Error(result.error);
      const game=result.game||{};
      const steps=(result.instructions||[]).map(step=>'<div class="maint-plan-item"><i></i><span>'+esc(step)+'</span></div>').join("");
      const size=Number(result.size_bytes||0)/1073741824;
      const free=Number(result.available_free_bytes||0)/1073741824;
      host.innerHTML='<small>READ-ONLY RELOCATION PLAN · '+esc(game.launcher)+' · '+esc(game.name)+'</small>'+
        '<div class="maint-data-row"><b>Source</b><span>'+esc(game.install_path||"")+'</span></div>'+
        '<div class="maint-data-row"><b>Target volume</b><span>'+esc(result.target_drive)+':</span></div>'+
        '<div class="maint-data-row"><b>Manifest size</b><span>'+size.toFixed(1)+' GiB</span></div>'+
        '<div class="maint-data-row"><b>Free space</b><span>'+free.toFixed(1)+' GiB</span></div>'+
        steps+'<div class="msg">'+esc(result.safety_note||"The launcher owns the actual move; SENTINEL will not modify its files or manifests.")+'</div>';
    }catch(error){host.textContent=error.message||String(error);toast(error.message||String(error),"bad");}
  });
  bind("maint-revert-all",async()=>{
    if(!confirm("Revert all outstanding reversible SENTINEL changes? Irreversible actions and externally changed values will be skipped."))return;
    try{
      const result=await api("/api/maintenance/revert-all",{confirmed:true});if(result.error)throw new Error(result.error);
      toast("Reverted "+(result.reverted||[]).length+" · skipped "+(result.skipped||[]).length+" · failed "+(result.failed||[]).length,result.failed?.length?"warn":"ok");
      await loadMaintenance(true);
    }catch(error){toast(error.message||String(error),"bad");}
  });
}
function initVoice(){
  const button=document.getElementById("ai-voice");if(!button)return;
  button.onclick=()=>{
    const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
    if(!Recognition)return toast("Speech recognition is not available in this browser","warn");
    if(button.dataset.active==="true")return;
    const recognition=new Recognition();recognition.lang=navigator.language||"en-US";
    recognition.interimResults=false;recognition.maxAlternatives=1;
    button.dataset.active="true";button.disabled=true;button.textContent="LISTENING…";
    recognition.onresult=event=>{
      const spoken=event.results?.[0]?.[0]?.transcript||"";
      const input=document.getElementById("ai-in");if(input){input.value=(input.value?input.value+" ":"")+spoken;input.focus();}
    };
    recognition.onerror=event=>toast("Voice input: "+event.error,"warn");
    recognition.onend=()=>{button.dataset.active="false";button.disabled=false;button.textContent="VOICE";};
    try{recognition.start();}
    catch(error){button.dataset.active="false";button.disabled=false;button.textContent="VOICE";toast(error.message,"warn");}
  };
}

async function boot() {
  const bootStartedAt = performance.now();
  starfield();
  bp(3, "POWERING SENTINEL", "Preparing the local command environment");
  buildTiles();
  buildChips();
  $$("#nav button[data-v]").forEach(button => {
    const label = button.querySelector(".lb")?.textContent?.trim() || TITLES[button.dataset.v] || button.dataset.v;
    button.setAttribute("aria-label", label);
    button.title = label;
    if (button.dataset.v === view) button.setAttribute("aria-current", "page");
    button.onclick = () => show(button.dataset.v);
  });

  const modules = [
    ["core", "SESSION", "Authenticated local node snapshot"],
    ["command", "COMMAND DECK", "Live performance and visual telemetry"],
    ["agent", "AGENT RUNTIME", "Process footprint and collector health"],
    ["sys", "SYSTEM MAP", "Platform, storage and security inventory"],
    ["proc", "PROCESS FIELD", "Windows process list and identities"],
    ["net", "NETWORK", "Connections and latency charts"],
    ["adv", "THERMAL / ETW", "Thermal sensors and kernel diagnostics"],
    ["eng", "ENGINE DECK", "Safeguards, runtime and memory policy"],
    ["health", "SOURCE HEALTH", "Runtime and collector source status"],
    ["stream", "LIVE LINK", "Event stream and heartbeat"],
    ["ker", "KERNEL ARCHIVE", "Historical counter samples"],
    ["activityx", "USAGE INTELLIGENCE", "Foreground activity and learned routines"],
    ["intelx", "INTELLIGENCE MEMORY", "Memories, goals and ranked context"],
    ["int", "INTELLIGENCE FEED", "Local intelligence results"],
    ["ai", "AI COUNCIL", "Model availability and conversation history"],
    ["evi", "EVIDENCE VAULT", "Searchable event records"],
    ["ctl", "ACTION CONTROL", "Pending approvals and action history"],
    ["fc", "FEATURE CONFIG", "Saved preferences and audit history"],
    ["tsk", "TASK CENTER", "Jobs and action run history"],
    ["act", "ACTIVITY STREAM", "Events and collector heartbeats"],
    ["maint", "MAINTENANCE", "Read-only inventory, safety policy and operations"]
  ];
  $("#bootModules").replaceChildren();
  modules.forEach(([key, label, detail]) => bootModule(key, label, "WAITING", detail));
  bp(9, "AUTHENTICATING", TOKEN ? "Local session token accepted" : "No local session token found", TOKEN ? "ok" : "warn");
  if (!TOKEN) {
    bootModuleState("core", "BLOCKED", "Open SENTINEL using the installed desktop shortcut");
    bp(100, "AUTHENTICATION REQUIRED", "Open SENTINEL from its installed desktop shortcut", "warn");
    $("#boot").classList.add("boot-error");
    return;
  }

  const degradedModules = new Set();
  const markDataFailure = (key, detail) => {
    degradedModules.add(key);
    bootModuleState(key, "DEGRADED", String(detail || "Data source unavailable").slice(0, 120));
  };
  const markDataReady = (key, detail) => {
    degradedModules.delete(key);
    bootModuleState(key, "READY", detail || "Data synchronized");
    markPageWarm(key);
  };

  bootModuleState("core", "LOADING", "Reading the authenticated Windows node snapshot");
  bp(14, "SYNCHRONIZING LOCAL NODE", "Restoring live measurements and host state");
  let initial;
  try {
    initial = await apiRetry("/api/snapshot", 2);
    if (initial?.error) throw new Error(initial.error);
  } catch (error) {
    markDataFailure("core", error.message || "Local agent is unavailable");
    showBootRetry("LOCAL AGENT UNAVAILABLE", error.message || "Open the SENTINEL agent and retry");
    return;
  }

  S = initial;
  if (S?.live && typeof S.live === "object") {
    for (const [key, value] of Object.entries(S.live)) {
      if (Number.isFinite(Number(value)) && !(H[key] || []).length) H[key] = [Number(value)];
    }
  }
  INS = [];
  renderIns();
  updateBootTelemetry();
  markDataReady("core", "Snapshot loaded · " + Number(S.proc_total || 0).toLocaleString() + " cached process records");
  bp(20, "LOADING FOUNDATION DATA", "History, events, policy, runtime status and AI transcript");

  const foundation = await Promise.allSettled([
    apiRetry("/api/history?secs=300", 1),
    apiRetry("/api/events?limit=300", 1),
    apiRetry("/api/insights", 1),
    apiRetry("/api/engines", 1),
    apiRetry("/api/status", 1),
    apiRetry("/api/ai", 1)
  ]);
  let foundationDegraded = 0;
  const readFoundation = (index, key, validate, apply, label) => {
    const result = foundation[index];
    if (result.status !== "fulfilled" || result.value?.error || !validate(result.value)) {
      const reason = result.status === "rejected" ? result.reason?.message : result.value?.error || "Unexpected data format";
      foundationDegraded++;
      markDataFailure(key, reason || (label + " unavailable"));
      return false;
    }
    apply(result.value);
    degradedModules.delete(key);
    bootModuleState(key, "READY", label + " synchronized");
    return true;
  };
  const historyReady = readFoundation(0, "command", value => value && typeof value === "object" && !Array.isArray(value),
    history => {
      for (const [key, samples] of Object.entries(history)) {
        if (Array.isArray(samples)) H[key] = samples.map(point => Number(point[1])).filter(Number.isFinite).slice(-MAXH);
      }
    }, "Telemetry history");
  const eventsReady = readFoundation(1, "act", Array.isArray,
    events => events.forEach(addLog), "Recent event stream");
  const insightsReady = readFoundation(2, "command", Array.isArray,
    insights => { INS = insights; renderIns(); }, "Performance insights");
  const enginesReady = readFoundation(3, "eng", value => value && typeof value === "object",
    engines => renderEngines(engines), "Safeguards and engine policies");
  const statusReady = readFoundation(4, "health", value => value && typeof value === "object",
    status => { ST = status; }, "Runtime and source status");
  const aiReady = readFoundation(5, "ai", value => value && typeof value === "object",
    transcript => (transcript.transcript || []).forEach(addTr), "AI transcript");
  if (S?.live) {
    for (const [key, value] of Object.entries(S.live)) {
      if (Number.isFinite(Number(value)) && !(H[key] || []).length) H[key] = [Number(value)];
    }
  }

  // Initialize interactions once. Workspace jobs below own the first data read.
  $("#a-q").oninput = renderFeed;
  $("#a-pause").onclick = event => {
    paused = !paused;
    event.target.textContent = paused ? "RESUME" : "PAUSE";
    if (!paused) renderFeed();
  };
  $("#i-go").onclick = async () => {
    const query = $("#i-q").value.trim();
    if (query) { await api("/api/intel/search", { q: query }); setTimeout(loadIntel, 4000); }
  };
  const send = () => {
    const message = $("#ai-in").value.trim();
    if (message) { api("/api/chat", { msg: message, mode: $("#ai-mode").value }); $("#ai-in").value = ""; }
  };
  $("#ai-go").onclick = send;
  $("#ai-in").onkeydown = event => event.key === "Enter" && send();
  $("#p-q").oninput = () => { clearTimeout(procQueryTimer); procQueryTimer = setTimeout(() => loadProcesses(true), 260); };
  $("#p-refresh").onclick = () => loadProcesses(true);
  $("#n-q").oninput = () => S && updNet();
  $$("[data-command-route]").forEach(button => button.onclick = () => show(button.dataset.commandRoute));
  $("#a-exp").onclick = () => {
    const content = LOGS.map(row => `${new Date(row.ts * 1000).toISOString()}\t${row.level}\t${row.src}\t${row.msg}`).join("\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([content], { type: "text/plain" }));
    link.download = "sentinel-activity-" + Date.now() + ".log";
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 2000);
    toast("Exported " + LOGS.length + " events", "ok");
  };
  initPalette(); initNotify(); initFC(); initIntelligence(); initActivityIntelligence();
  initAdvanced(); initAgent(); initEngines(); initMaintenance(); initWindowsKnowledge(); initVoice(); bindJ("#metrics");
  $("#e-go").onclick = loadEvi;
  $("#e-csv").onclick = csvExport;
  $("#e-q").onkeydown = event => event.key === "Enter" && loadEvi();
  $("#e-lv").onchange = $("#e-src").onchange = loadEvi;
  $("#sys-refresh").onclick = async () => {
    const button = $("#sys-refresh");
    button.disabled = true;
    button.textContent = "SCANNING…";
    const result = await api("/api/inventory/refresh", {});
    button.disabled = false;
    button.textContent = "REFRESH INVENTORY";
    if (result.error) toast(result.error, "bad");
    else { toast("System inventory refreshed", "ok"); loadSys(true); }
  };
  $("#kernel-capture").onclick = async () => {
    const result = await api("/api/action/propose", { kind: "wpr_trace", reason: "User requested a bounded 15-second Windows Performance Recorder ETW trace" });
    if (result.error) return toast(result.error, "bad");
    toast("ETW trace queued. Approve it in CONTROL; an existing WPR recording will not be interrupted.", "warn");
    loadActions();
  };
  $("#kernel-archive-load").onclick = loadKernelArchive;
  $("#kernel-archive-key").onchange = loadKernelArchive;
  addEventListener("keydown", event => {
    const tag = event.target?.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || event.ctrlKey || event.metaKey || event.altKey) return;
    const number = Number(event.key);
    if (number >= 1 && number <= VKEYS.length) show(VKEYS[number - 1]);
  });
  setInterval(() => $("#h-clock").textContent = new Date().toLocaleTimeString([], { hour12: false }), 1000);
  setInterval(() => {
    if (view === "int") loadIntel();
    if (view === "activityx") loadActivityIntelligence();
    if (view === "ctl") loadActions();
    if (view === "agent") loadAgent();
  }, 10000);
  setInterval(loadStatus, 15000);
  setInterval(() => { if (view === "eng") loadEngines(); }, 8000);

  bootModuleState("stream", "LOADING", "Opening the local event stream");
  const stream = new EventSource("/api/stream?t=" + encodeURIComponent(TOKEN));
  let streamSettled = false;
  let resolveStream;
  const streamReady = new Promise(resolve => { resolveStream = resolve; });
  const streamTimer = setTimeout(() => {
    if (streamSettled) return;
    streamSettled = true;
    resolveStream(false);
  }, 1800);
  stream.addEventListener("open", () => {
    if (streamSettled) {
      degradedModules.delete("stream");
      bootModuleState("stream", "READY", "Local event channel reconnected");
      $("#p-online").className = "pill ok";
      $("#p-online").textContent = "AGENT ONLINE";
      return;
    }
    streamSettled = true;
    clearTimeout(streamTimer);
    resolveStream(true);
  });
  stream.addEventListener("error", () => {
    $("#p-online").className = "pill bad";
    $("#p-online").textContent = "LINK RETRYING";
  });
  stream.onmessage = message => {
    try {
      const packet = JSON.parse(message.data);
      if (packet.t === "tick") {
        $("#p-online").className = "pill ok";
        $("#p-online").textContent = "AGENT ONLINE";
        onTick(packet.d);
        updateBootTelemetry();
      } else if (packet.t === "log") addLog(packet.d);
      else if (packet.t === "insight") { INS.unshift(packet.d); renderIns(); alertInsight(packet.d); }
      else if (packet.t === "action") { actionsLoaded = false; loadActions(); }
      else if (packet.t === "ai") addTr(packet.d);
      else if (packet.t === "ai_status") $("#ai-status").textContent = packet.d.text;
      else if (packet.t === "intel" && view === "int") loadIntel();
      else if (packet.t === "maintenance_job") onMaintenanceJob(packet.d);
      else if (packet.t === "maintenance_status" || packet.t === "maintenance_digest") {
        MNT = null;
        if (view === "maint") loadMaintenance(false);
      }
    } catch (error) { console.error("Invalid SENTINEL stream event", error); }
  };

  const jobs = [
    ["command", "COMMAND DECK", async () => {
      updHero(); updTiles(); updMetrics(); renderCommandVisuals();
      return historyReady && insightsReady;
    }],
    ["net", "NETWORK", async () => {
      if (!Array.isArray(S?.net)) throw new Error("Initial connection snapshot is unavailable");
      updNet(); return true;
    }],
    ["eng", "ENGINE DECK", async () => enginesReady || await loadEngines()],
    ["agent", "AGENT RUNTIME", () => loadAgent(true)],
    ["sys", "SYSTEM INVENTORY", () => loadSys(true)],
    ["proc", "WINDOWS PROCESS FIELD", () => loadProcesses(true)],
    ["adv", "THERMAL / ETW", () => loadAdvanced(true)]
  ];
  const secondaryJobs = [
    ["ker", "KERNEL ARCHIVE", async () => { updKer(); return await loadKernelArchive(); }],
    ["activityx", "USAGE INTELLIGENCE", () => loadActivityIntelligence(true)],
    ["intelx", "INTELLIGENCE MEMORY", () => loadIntelligence()],
    ["int", "INTELLIGENCE FEED", () => loadIntel()],
    ["ai", "AI COUNCIL", async () => { updAI(); return aiReady; }],
    ["evi", "EVIDENCE VAULT", () => loadEvi()],
    ["ctl", "ACTION CONTROL", async () => { buildCtl(); ctlInitialized = true; return await loadActions(); }],
    ["fc", "FEATURE CONFIGURATION", () => loadFC()],
    ["tsk", "TASK CENTER", () => loadHist()],
    ["act", "ACTIVITY STREAM", async () => { updHeart(); renderFeed(); return eventsReady; }],
    ["maint", "MAINTENANCE", async () => await loadMaintenance(false)]
  ];
  const allJobs = [...jobs, ...secondaryJobs];
  let completed = 0;
  const total = allJobs.length;
  const runJob = async ([key, label, work]) => {
    bootModuleState(key, "LOADING", "Loading " + label.toLowerCase());
    try {
      const result = await work();
      if (result === false) throw new Error("Data request completed without a usable dataset");
      degradedModules.delete(key);
      markPageWarm(key);
      completed++;
      const detail = key === "proc"
        ? `${PROC_META.matched}/${PROC_META.total} processes · ${PROC_META.inaccessible || 0} restricted`
        : key === "adv"
          ? (ADV?.hardware_sensors?.available ? `${ADV.hardware_sensors.sensor_count || 0} sensor readings` : "Thermal source checked · unavailable sensors are identified")
          : "Data and controls synchronized";
      if (key === "proc") $("#bootProcessCount").textContent = `${PROC_META.total.toLocaleString()} PROCESSES`;
      bootModuleState(key, "READY", detail);
      bp(24 + completed / total * 72, "LOADING " + label, label + " data synchronized", "ok");
      return true;
    } catch (error) {
      completed++;
      markDataFailure(key, error?.message || "Dataset unavailable");
      bp(24 + completed / total * 72, "SOURCE DEGRADED · " + label, error?.message || "Dataset unavailable", "warn");
      return false;
    }
  };
  const runPool = async queue => {
    let next = 0;
    const worker = async () => {
      while (next < queue.length) {
        const job = queue[next++];
        await runJob(job);
      }
    };
    await Promise.all(Array.from({ length: Math.min(API_CONCURRENCY, queue.length) }, worker));
  };

  // Primary operational datasets first; all remaining pages hydrate before first paint.
  bp(22, "HYDRATING OPERATIONAL DATA", "Four bounded request workers · no duplicate agent collectors");
  await runPool(jobs);
  const streamConnected = await streamReady;
  if (!streamSettled) {
    streamSettled = true;
    clearTimeout(streamTimer);
    resolveStream(false);
  }
  bootModuleState("stream", streamConnected ? "READY" : "DEGRADED",
    streamConnected ? "Local event channel opened" : "Live link will reconnect in the background");
  if (!streamConnected) markDataFailure("stream", "The event channel did not open before the splash timeout");
  else degradedModules.delete("stream");
  bp(72, "HYDRATING WORKSPACES", "Loading intelligence, evidence, action and history datasets");
  await runPool(secondaryJobs);

  // Bring the command canvas up with the loaded history and current snapshot.
  if (S) {
    updHero();
    updTiles();
    updMetrics();
    renderCommandVisuals();
  }
  const degraded = degradedModules.size;
  if (degraded) bp(98, "READY WITH DEGRADED SOURCES", degraded + " module(s) could not return complete data", "warn");
  else bp(99, "ALL DATASETS SYNCHRONIZED", "Every workspace was queried and its result rendered", "ok");

  let savedView = "cmd";
  try { savedView = localStorage.getItem("sv") || "cmd"; } catch (error) { }
  if (TITLES[savedView] && savedView !== "cmd") show(savedView);
  const minimumDisplayMs = 900;
  const remaining = minimumDisplayMs - (performance.now() - bootStartedAt);
  if (remaining > 0) await new Promise(resolve => setTimeout(resolve, remaining));
  bp(100, degraded ? "SENTINEL ONLINE · CHECK SOURCES" : "SENTINEL ONLINE",
    degraded ? "All workspaces were checked. Unavailable sources are marked for retry." : "All workspace data is ready for navigation.",
    degraded ? "warn" : "ok");
  endBoot();
}
/* ---------- reversible performance intelligence / thermal workspace ---------- */
let ADV = null, advLastLoad = 0, advBusy = false, advRetryTimer = null;
function selectAdvWorkspace(group) {
  const valid = ["overview", "thermal", "diagnostics", "tuning", "controls"].includes(group) ? group : "overview";
  $$("#v-adv .adv-grid > .panel[data-adv-group]").forEach(panel => { panel.hidden = panel.dataset.advGroup !== valid; });
  $$("#advWorkspaceTabs [data-adv-tab]").forEach(button => {
    const active = button.dataset.advTab === valid;
    button.classList.toggle("on", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  try { localStorage.setItem("adv-workspace", valid); } catch (error) { }
}
const avNum = (v, d = 1, suffix = "") => v == null || !Number.isFinite(Number(v)) ? "--" : Number(v).toFixed(d) + suffix;
function advGauge(id, temp, threshold, valId, sourceId, source) {
  const dial = $("#" + id), value = $("#" + valId), src = $("#" + sourceId);
  if (!dial || !value || !src) return;
  if (temp == null || !Number.isFinite(Number(temp))) {
    dial.style.setProperty("--heat", 0); dial.style.setProperty("--heat-color", "#526879");
    value.textContent = "--"; src.textContent = source || "Sensor unavailable"; return;
  }
  const n = Number(temp), color = n >= threshold ? "#C35A54" : n >= threshold - 10 ? "#B58D7D" : "#9BAA98";
  dial.style.setProperty("--heat", Math.max(0, Math.min(100, n / 105 * 100)));
  dial.style.setProperty("--heat-color", color); value.textContent = n.toFixed(1) + "°";
  src.textContent = source || "Measured Windows sensor";
}
function advSpark(id, key) {
  const svg = $("#" + id); if (!svg) return;
  const values = (H[key] || []).map(Number).filter(Number.isFinite).slice(-80);
  if (values.length < 2) { svg.innerHTML = ""; return; }
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const points = values.map((v, i) => `${(i / (values.length - 1) * 258 + 1).toFixed(1)},${(39 - (v - lo) / span * 34).toFixed(1)}`).join(" ");
  svg.innerHTML = `<polyline points="${points}"></polyline>`;
}
function advPowerClockWaterfall() {
  const svg = $("#adv-power-clock-waterfall");
  if (!svg) return;
  const clocks = (H.gpuclk || []).map(Number).filter(Number.isFinite).slice(-60);
  const power = (H.gpupwr || []).map(Number).filter(Number.isFinite).slice(-60);
  const count = Math.min(clocks.length, power.length);
  if (count < 2) {
    svg.innerHTML = '<text x="12" y="72" class="adv-waterfall-empty">Collecting aligned GPU clock and power samples…</text>';
    return;
  }
  const renderLane = (values, y, label, unit, color) => {
    const data = values.slice(-count);
    const lo = Math.min(...data), hi = Math.max(...data), span = hi - lo || 1;
    const left = 92, width = 452, top = y + 17, height = 30, base = top + height;
    const step = width / data.length;
    const bars = data.map((value, index) => {
      const norm = (value - lo) / span;
      const barHeight = 3 + norm * (height - 3);
      const x = left + index * step + 0.6;
      const w = Math.max(1, step - 1.2);
      const yy = base - barHeight;
      return `<rect x="${x.toFixed(2)}" y="${yy.toFixed(2)}" width="${w.toFixed(2)}" height="${barHeight.toFixed(2)}" rx="1" fill="${color}" opacity="${(0.48 + norm * 0.48).toFixed(2)}"></rect>`;
    }).join("");
    return `<g><text x="8" y="${y + 29}" class="adv-waterfall-label">${label}</text><text x="8" y="${y + 43}" class="adv-waterfall-unit">${unit}</text><line x1="${left}" y1="${base}" x2="${left + width}" y2="${base}" class="adv-waterfall-axis"></line>${bars}<text x="${left}" y="${base + 12}" class="adv-waterfall-range">${lo.toFixed(0)}</text><text x="${left + width}" y="${base + 12}" text-anchor="end" class="adv-waterfall-range">${hi.toFixed(0)}</text></g>`;
  };
  svg.innerHTML = renderLane(clocks, 0, "CLOCK", "MHz", "#82917D")
    + renderLane(power, 72, "POWER", "W", "#909B94");
}
function advRows(rows, empty) {
  return rows.length ? rows.join("") : `<div class="empty">${esc(empty)}</div>`;
}
function renderAdvLiveMetrics(metrics) {
  const definitions = [
    ["cpu", "CPU LOAD", "%", 1], ["mem", "MEMORY", "%", 1],
    ["gpu", "GPU LOAD", "%", 1], ["gputemp", "GPU TEMP", "°C", 1],
    ["dpc", "DPC TIME", "%", 2], ["irq", "INTERRUPT TIME", "%", 2],
    ["pagesin", "HARD FAULTS", "/s", 1], ["pagesout", "PAGES OUT", "/s", 1],
    ["dlat", "DISK READ LATENCY", "ms", 2], ["ping", "PING", "ms", 1],
    ["jitter", "JITTER", "ms", 1], ["netdown", "NETWORK DOWN", "Mb/s", 1],
  ];
  const available = definitions.filter(([key]) => {
    const value = metrics?.[key]?.value;
    return value != null && Number.isFinite(Number(value));
  });
  $("#adv-live-meta").textContent = available.length
    ? `${available.length} live collector metric(s) · values are measured, not inferred`
    : "No live samples have arrived yet";
  $("#adv-live-metrics").innerHTML = available.length
    ? available.map(([key, label, unit, precision]) => {
        const item = metrics[key];
        const value = Number(item.value);
        const sampleAge = item.sampled_at
          ? `${Math.max(0, Math.floor(Date.now() / 1000 - Number(item.sampled_at)))}s ago`
          : "sample time unavailable";
        return `<div class="adv-live-cell"><small>${label}</small><b>${value.toFixed(precision)}${unit}</b><span>observed · ${esc(sampleAge)}</span></div>`;
      }).join("")
    : '<div class="empty">Waiting for CPU, memory, kernel, disk and network collectors. Game baselines and hardware temperatures are separate optional data sources.</div>';
}
async function loadAdvanced(force = false) {
  if (advBusy || (!force && Date.now() - advLastLoad < 5000)) return !!ADV;
  advBusy = true; advLastLoad = Date.now();
  try {
    const d = await apiRetry("/api/advanced", 2); ADV = d;
    const loadError = $("#adv-load-error");
    if (loadError) { loadError.hidden = true; loadError.classList.remove("stale"); }
    clearTimeout(advRetryTimer);
    renderAdvLiveMetrics(d.live_metrics || {});
    const game = d.game || null, gpu = d.gpu || {}, hs = d.hardware_sensors || {}, cfg = (d.settings || d.advanced_settings || {});
    const provider = d.hardware_provider || {};
    const pipeline = $("#sensor-pipeline");
    if (pipeline) pipeline.dataset.state = hs.available ? "connected" : provider.endpoint_state === "remote_server_not_started" ? "server-off" : provider.running ? "starting" : provider.installed ? "stopped" : "missing";
    const etw = d.etw_engine || {};
    $("#adv-game").textContent = game?.name || "STANDBY";
    $("#adv-session").textContent = d.sessions?.[0]?.status === "active" ? `Session #${d.sessions[0].id} · ${dur(Date.now()/1000 - d.sessions[0].started_at)}` : "No active session tracked";
    $("#adv-etw-state").textContent = (etw.state || (etw.available ? "idle" : "unavailable")).toUpperCase();
    const etwAutoState = etw.auto_state || (etw.enabled ? "armed" : "disabled");
    $("#adv-etw-meta").textContent = etw.available === false
      ? "WPR unavailable"
      : etw.xperf_optional_available ? `${etw.last_event_count || 0} decoded events · Xperf enhancement available`
      : `${etw.last_event_count || 0} decoded events · Xperf optional`;
    $("#adv-etw-status").textContent = etw.recording ? "RECORDING" :
      etwAutoState === "recording" ? "AUTO RECORDING" :
      etwAutoState === "queued" ? "AUTO QUEUED" :
      etwAutoState === "armed" ? "AUTO ARMED" :
      etwAutoState === "manual_only" ? "MANUAL ONLY" :
      etwAutoState === "blocked" ? "BLOCKED" :
      etwAutoState === "unavailable" ? "UNAVAILABLE" :
      etwAutoState === "error" ? "ERROR" : "DISABLED";
    $("#adv-etw-status").className = "tag " + (
      etw.recording || etwAutoState === "recording" || etwAutoState === "queued" ? "warn" :
      etwAutoState === "armed" ? "ok" :
      etwAutoState === "blocked" || etwAutoState === "error" || etwAutoState === "unavailable" ? "bad" : ""
    );
    $("#adv-etw-source").textContent = etw.source || "Windows Performance Recorder · GeneralProfile.Light";
    $("#adv-etw-note").textContent = etw.error || etw.auto_reason || (
      etw.available === false
        ? "Automatic and manual capture need Windows Performance Recorder (wpr.exe). Xperf is optional and only adds supplemental DPC/ISR driver-module decoding. PDH counters are separate from ETW."
        : etw.enabled && etw.auto_sampling_enabled
          ? `Automatic sampling is opted in. A 12-second WPR window runs at most once every ${etw.auto_interval_s || 300} seconds during a stable active game or foreground work session. Existing WPR/kernel logger sessions are never taken over.`
          : etw.enabled
            ? "The ETW engine is enabled, but automatic sampling is in manual-only mode. Turn on the dedicated automatic-sampling option to arm bounded WPR windows."
            : "The ETW engine is off. Enable the engine and the separate automatic-sampling option to start bounded diagnostics; the manual capture button remains available."
    );
    const baseEntries = Object.entries(d.baseline || {});
    $("#adv-baseline-count").textContent = baseEntries.reduce((n, [,x])=>n+(x.samples||0),0).toLocaleString();
    $("#adv-baseline-heading").textContent = `${d.game_key || "No active game"} · local hour ${d.baseline_hour ?? "--"}`;
    $("#adv-undo-count").textContent = (d.action_journal || []).filter(x=>x.undo_available && x.changed && !x.reverted_at).length;
    const cpuItems = Array.isArray(hs.cpu_temperatures) ? hs.cpu_temperatures : [];
    const firstReading = rows => Array.isArray(rows) ? rows.find(x => x && x.value != null && Number.isFinite(Number(x.value))) || null : null;
    const sensorDisplay = (sensor, fallback, unit) => sensor
      ? `${avNum(sensor.value, 1)} ${sensor.unit || unit || ""}`.trim()
      : fallback == null ? "unavailable" : `${fallback} ${unit || ""}`.trim();
    const cpuVals = cpuItems.map(x => Number(x.value)).filter(Number.isFinite);
    const cpuTemp = cpuVals.length ? Math.max(...cpuVals) : null;
    const sensorProvider = hs.provider || "External hardware monitor";
    const acpiZone = hs.cpu_source === "Windows ACPI WMI";
    if ($("#adv-cpu-title")) $("#adv-cpu-title").textContent = acpiZone ? "Platform thermal zone" : "CPU package";
    if ($("#adv-cpu-label")) $("#adv-cpu-label").textContent = acpiZone ? "ZONE °C" : "CPU °C";
    const cpuSrc = hs.available
      ? `${hs.source || hs.cpu_source || sensorProvider} · ${cpuItems.length} temperature reading(s)${hs.cpu_reason ? " · " + hs.cpu_reason : cpuItems.length ? "" : " · CPU sensor not exposed"}`
      : (hs.reason || "Optional sensor provider unavailable");
    advGauge("adv-cpu-dial", cpuTemp, Number(cfg.cpu_temp_warn_c || 88), "adv-cpu-temp", "adv-cpu-source", cpuSrc);
    const lhmGpuTemperature = firstReading(hs.gpu_temperatures);
    const gpuTemp = gpu.temp != null && Number.isFinite(Number(gpu.temp)) ? Number(gpu.temp)
      : lhmGpuTemperature ? Number(lhmGpuTemperature.value) : null;
    const gpuTempSource = lhmGpuTemperature ? `${sensorProvider} · ${lhmGpuTemperature.name}`
      : gpu.name ? `${gpu.name} · NVIDIA nvidia-smi` : "GPU temperature unavailable";
    advGauge("adv-gpu-dial", gpuTemp, Number(cfg.gpu_temp_warn_c || 82), "adv-gpu-temp", "adv-gpu-source", gpuTempSource);
    $("#adv-cpu-threshold-note").textContent = `Warning threshold ${fmt(cfg.cpu_temp_warn_c ?? 88, 0)} °C`;
    $("#adv-gpu-throttle").textContent = (gpu.throttle || []).length ? `Throttle flags: ${gpu.throttle.join(", ")}` : "No active NVIDIA throttle flag reported";
    const lhmFans = (Array.isArray(hs.fan_rpm) ? hs.fan_rpm : [])
      .filter(x => x && x.value != null && Number.isFinite(Number(x.value)) && Number(x.value) >= 0);
    const fanSensor = lhmFans[0] || null;
    const fanValue = fanSensor ? Number(fanSensor.value) : gpu.fan_speed_pct;
    const fanSource = fanSensor
      ? `${fanSensor.name || "Fan"} · ${sensorProvider} RPM`
      : (gpu.fan_speed_pct != null ? "GPU fan percentage (RPM not exposed)" : "Fan RPM unavailable");
    $("#adv-fan-value").textContent = fanSensor ? `${avNum(fanValue, 0)} RPM` : fanValue != null ? `${avNum(fanValue, 0)}%` : "NO SENSOR";
    $("#adv-fan-source").textContent = fanSource;
    const rotor = $("#adv-fan");
    rotor.title = hs.fan_reason || "Fan RPM sensor not exposed on this device.";
    $("#adv-fan-card")?.classList.toggle("unavailable", fanValue == null);
    const fanHz = fanSensor ? Math.max(.12, Math.min(3, 60 / Math.max(1, fanValue))) : fanValue != null ? Math.max(.45, 4 - Number(fanValue) * .035) : 1.5;
    rotor.style.animationDuration = `${fanHz}s`;
    rotor.classList.toggle("running", fanValue != null && Number(fanValue) > 0);
    const cores = Array.isArray(hs.per_core_temperatures) ? hs.per_core_temperatures : [];
    $("#adv-core-meta").textContent = cores.length ? `${cores.length} per-core temperature sensor(s)` : hs.available ? "Per-core sensors not exposed by this provider" : "Hardware temperature provider unavailable";
    $("#adv-core-map").innerHTML = cores.length ? cores.map((x,i)=>{const n=Number(x.value), pct=Math.max(0,Math.min(100,n/105*100)); return `<div class="core-cell"><b>${esc(x.name || `Core ${i}`)}</b><small>${avNum(n,1)} °C</small><div class="heat-bar"><i style="width:${pct}%"></i></div></div>`;}).join("") : `<div class="empty">${esc(hs.cpu_reason || "Per-core heat sensors are unavailable. Start the managed sensor provider to check hardware support.")}</div>`;
    const cpuClock = firstReading(hs.cpu_clocks), gpuClock = firstReading(hs.gpu_clocks);
    const cpuPower = firstReading(hs.cpu_power), gpuPower = firstReading(hs.gpu_power);
    const cpuVoltage = firstReading(hs.cpu_voltage), gpuVoltage = firstReading(hs.gpu_voltage);
    const cpuLoad = firstReading(hs.cpu_load), gpuLoad = firstReading(hs.gpu_load);
    const stats = [
      ["CPU clock", sensorDisplay(cpuClock, null, "MHz")],
      ["CPU package power", sensorDisplay(cpuPower, null, "W")],
      ["CPU voltage", sensorDisplay(cpuVoltage, null, "V")],
      ["CPU load sensor", sensorDisplay(cpuLoad, null, "%")],
      ["GPU clock", sensorDisplay(gpuClock, gpu.clk, "MHz")],
      ["GPU power", sensorDisplay(gpuPower, gpu.pwr, "W")],
      ["GPU power limit", gpu.pwrlim == null ? "unavailable" : `${gpu.pwrlim} W`],
      ["GPU voltage", sensorDisplay(gpuVoltage, null, "V")],
      ["GPU load", sensorDisplay(gpuLoad, gpu.util, "%")],
      ["VRAM", gpu.vram == null ? "unavailable" : `${gpu.vram} / ${gpu.vramtot ?? "--"} MiB`],
      ["Fan reading", fanSensor ? `${avNum(fanSensor.value, 0)} RPM` : gpu.fan_speed_pct == null ? "unavailable" : `${gpu.fan_speed_pct}% (GPU fan percentage)`],
    ];
    $("#adv-gpu-stats").innerHTML = stats.map(([label,value]) => `<div class="row"><b>${esc(label)}</b><span>${esc(value)}</span></div>`).join("");
    const listedSensors = Array.isArray(hs.sensors) ? hs.sensors : [];
    const sensorRows = listedSensors.length ? listedSensors : [
      ...(hs.cpu_temperatures || []), ...(hs.gpu_temperatures || []), ...(hs.fan_rpm || []),
      ...(hs.cpu_clocks || []), ...(hs.gpu_clocks || []), ...(hs.cpu_power || []),
      ...(hs.gpu_power || []), ...(hs.cpu_voltage || []), ...(hs.gpu_voltage || []),
    ];
    $("#adv-sensor-count").textContent = `${sensorRows.length} numeric reading(s) · ${sensorProvider}`;
    $("#adv-sensor-inventory").innerHTML = sensorRows.length
      ? sensorRows.slice(0,100).map(sensor => `<div class="sensor-row"><div><b>${esc(sensor.name || "Unnamed sensor")}</b><small>${esc(sensor.parent || sensor.device_class || sensorProvider)} · ${esc(sensor.type || "Sensor")} · ${esc(sensor.device_class || "platform")}</small></div><strong>${sensor.value == null ? "--" : avNum(sensor.value, 2)} ${esc(sensor.unit || (sensor.type === "Temperature" ? "°C" : ""))}</strong></div>`).join("") + (sensorRows.length > 100 ? `<div class="empty">${sensorRows.length - 100} additional sensor rows omitted from this view.</div>` : "")
      : `<div class="empty">${esc(hs.reason || "No numeric hardware sensors have been returned by the provider.")}</div>`;
    const providerButton = $("#adv-provider-install");
    if (providerButton) providerButton.textContent = provider.installed ? "REFRESH SENSOR STATUS" : "INSTALL SENSOR LIBRARY";
    const providerStatus = $("#adv-provider-status");
    if (providerStatus) providerStatus.textContent = provider.installed
      ? (hs.available
        ? `SENSOR FEED \u00b7 ${hs.sensor_count || 0} measured readings \u00b7 ${hs.sensor_backend || hs.provider || "thermal fallback"}`
        : (hs.reason || "Direct sensor reader is warming up; Windows ACPI and NVIDIA sources are also checked."))
      : (provider.next_step || "Not installed ? official package is checksum-verified before extraction.");
    advSpark("adv-clock-spark","gpuclk"); advSpark("adv-power-spark","gpupwr"); advPowerClockWaterfall();
    $("#adv-thermal-timeline").innerHTML = advRows((d.thermal_events || []).slice(0,16).map(x=>`<div class="event"><b>${esc(x.sensor)} · ${esc(x.event)}</b><small>${hms(x.ts)} · ${x.value==null?"value unavailable":avNum(x.value,1)+" °C"} ${esc(x.detail || "")}</small></div>`), "No thermal warning or GPU throttle transitions have been recorded.");
    const drivers = d.etw_engine?.driver_modules || [];
    $("#adv-drivers").innerHTML = drivers.length ? drivers.map(x=>`<div class="adv-row"><div><b>${esc(x.module)}</b><small>${esc(x.attribution)} · ${esc(x.line || "")}</small></div><span class="adv-badge">DRIVER MODULE</span></div>`).join("") : '<div class="empty">No .sys driver module resolved in the latest DPC/ISR report. This is not proof that no driver contributed.</div>';
    $("#adv-etw-events").innerHTML = (d.etw_events || []).slice(0,12).map(x=>`<div class="adv-row"><div><b>${esc(x.event)}</b><small>${esc(x.provider)} · PID ${esc(x.pid ?? "unknown")} ${esc(x.process || "unresolved")}</small></div><span class="adv-badge">${esc(x.attribution)}</span></div>`).join("") || '<div class="empty">No decoded event rows yet.</div>';
    $("#adv-baseline-table").innerHTML = baseEntries.length ? baseEntries.map(([k,x])=>`<div class="adv-row"><div><b>${esc(k)}</b><small>${x.samples} samples · mean ${fmt(x.mean,2)} · σ ${fmt(x.stddev,2)}</small></div><span class="adv-badge">${fmt(x.min,1)}–${fmt(x.max,1)}</span></div>`).join("") : '<div class="empty">Personal baseline learning starts when a supported game process is detected. Needs repeated samples before deviation alerts.</div>';
    const correlations = (d.correlation_events || []).slice(0,10);
    $("#adv-correlation").innerHTML = advRows(correlations.map(x=>`<div class="adv-row"><div><b>${esc(x.event)}</b><small>${hms(x.ts)} · ${esc(JSON.stringify(x.evidence || {}).slice(0,250))}</small></div><span class="adv-badge">TEMPORAL CANDIDATE</span></div>`), "No recent personal-baseline deviation events. Completed session reports also include preceding system changes.");
    $("#adv-sessions").innerHTML = advRows((d.session_reports || []).map(x=>{const delta=x.report?.delta||{}; const short=Object.entries(delta).slice(0,6).map(([k,v])=>`${k}: ${v.delta>0?"+":""}${v.delta}`).join(" · ");return `<div class="adv-row"><div><b>${esc(x.game)} · Session #${x.id}</b><small>${Math.round(x.report?.duration_seconds||0)}s · ${esc(short || "No comparable metrics")}</small><small>${esc((x.report?.limitations||[]).join(" "))}</small></div><span class="adv-badge">REPORT</span></div>`;}), "No completed sessions yet. A report is generated when a tracked game exits.");
    $("#adv-tuner-history").innerHTML = advRows((d.tuner_history || []).map(x=>`<div class="adv-row"><div><b>${esc(x.metric)} · ${esc(x.outcome.replaceAll("_"," "))}</b><small>${esc(x.detail || "")} · ${x.before==null?"--":fmt(x.before,2)} → ${x.after==null?"pending":fmt(x.after,2)}</small></div><span class="adv-badge">${x.delta_pct==null?"--":fmt(x.delta_pct,1)+"%"}</span></div>`), "No tuner experiments yet.");
    $("#adv-network-evidence").textContent = d.network_evidence?.supported ? `Ping mean ${fmt(d.network_evidence.ping_mean_ms,1)} ms · jitter mean ${fmt(d.network_evidence.jitter_mean_ms,1)} ms · ${d.network_evidence.candidate ? "latency elevation candidate" : "no sustained elevation"}` : (d.network_evidence?.reason || "Network evidence unavailable");
    $("#adv-journal").innerHTML = advRows((d.action_journal || []).map(x=>`<div class="adv-row"><div><b>#${x.action_id} · ${esc(x.kind.replaceAll("_"," "))}</b><small><span class="risk-${esc(x.risk)}">${esc(x.risk.toUpperCase())}</span> · ${esc(x.result || "prepared")}${x.reverted_at ? " · reverted" : ""}${x.revert_result ? " · " + esc(x.revert_result) : ""}</small><small>Snapshot before action: ${esc(JSON.stringify(x.before || {}).slice(0,240))}</small></div><div class="adv-actions">${x.undo_available && x.changed && !x.reverted_at ? `<button class="btn sm" data-adv-undo="${x.action_id}">UNDO</button>` : `<span class="adv-badge">${x.undo_available ? (x.reverted_at ? "REVERTED" : "NO CHANGE") : "NO AUTO-UNDO"}</span>`}</div></div>`), "No journaled SENTINEL changes yet.");
    $$('[data-adv-undo]').forEach(b=>b.onclick=async()=>{if(!confirm(`Undo action #${b.dataset.advUndo}?`))return;const r=await api("/api/advanced/undo",{action_id:+b.dataset.advUndo});toast(r.ok?r.result:r.error,r.ok?"ok":"bad");loadAdvanced(true);});
    const setToggle=(id,val)=>{const el=$("#"+id);if(el)el.checked=!!val;};
    setToggle("adv-etw-enabled",cfg.etw_enabled); setToggle("adv-lhm-enabled",cfg.lhm_enabled); setToggle("adv-etw-auto",!!S?.autopilot?.etw_capture);
    if(document.activeElement?.id!=="adv-cpu-threshold")$("#adv-cpu-threshold").value=cfg.cpu_temp_warn_c ?? 88;
    if(document.activeElement?.id!=="adv-gpu-threshold")$("#adv-gpu-threshold").value=cfg.gpu_temp_warn_c ?? 82;
    if(document.activeElement?.id!=="adv-lhm-port")$("#adv-lhm-port").value=cfg.lhm_http_port ?? 8085;
    if(document.activeElement?.id!=="adv-etw-interval")$("#adv-etw-interval").value=cfg.etw_auto_interval_s ?? 300;
    if(game && !$("#adv-profile-game").value)$("#adv-profile-game").value=game.name;
    return true;
  } catch(e) {
    const errorPanel = $("#adv-load-error");
    const errorText = $("#adv-load-error-text");
    if (errorPanel) { errorPanel.hidden = false; errorPanel.classList.toggle("stale", !!ADV); }
    if (errorText) errorText.textContent = ADV
      ? "Agent link interrupted · showing the latest sensor snapshot"
      : "Agent link interrupted · retrying connection";
    clearTimeout(advRetryTimer);
    if (view === "adv") advRetryTimer = setTimeout(() => loadAdvanced(true), ADV ? 5000 : 1800);
    return false;
  }
  finally { advBusy = false; }
}
function advProfilePayload(){
  const affinityText=$("#adv-affinity").value.trim();
  const affinity=affinityText?affinityText.split(",").map(x=>Number(x.trim())).filter(Number.isInteger):null;
  return {priority:$("#adv-priority").value, cpu_set_policy:$("#adv-cpu-sets").value, affinity,
    background_efficiency_allowlist:$("#adv-bg-allow").value.split(",").map(x=>x.trim()).filter(Boolean).slice(0,30),
    apply_power_plan:$("#adv-power-enable").checked, power_plan_guid:$("#adv-power-guid").value.trim(), timer_resolution_ms:Number($("#adv-timer").value)};
}
let advDryRun = null;
function initAdvanced(){
  let initialWorkspace = "overview";
  try { initialWorkspace = localStorage.getItem("adv-workspace") || "overview"; } catch (error) { }
  selectAdvWorkspace(initialWorkspace);
  $$("#advWorkspaceTabs [data-adv-tab]").forEach(button => button.onclick = () => selectAdvWorkspace(button.dataset.advTab));
  $("#adv-retry").onclick = () => loadAdvanced(true);
  $$("[data-tuner-direction]").forEach(button => button.onclick = () => {
    const direction = button.dataset.tunerDirection;
    $("#adv-tuner-direction").value = direction;
    $$("[data-tuner-direction]").forEach(item => item.classList.toggle("on", item === button));
  });
  $("#adv-refresh").onclick=()=>loadAdvanced(true);
  const providerButton = $("#adv-provider-install");
  if (providerButton) providerButton.onclick = async () => {
    const original = providerButton.textContent;
    let result = null;
    providerButton.disabled = true;
    providerButton.textContent = "CHECKING SENSOR LIBRARY…";
    try {
      result = await api("/api/hardware/provider/start", {});
      if (result.error) throw new Error(result.error);
      toast(result.message || "Sensor provider start request completed", result.connected ? "ok" : "warn");
      await loadAdvanced(true);
    } catch (error) {
      const message = error?.message || String(error);
      toast("Sensor provider: " + message, "bad");
      $("#adv-provider-status").textContent = message;
    } finally {
      providerButton.disabled = false;
      const state = result?.provider || {};
      providerButton.textContent = state.installed ? "REFRESH SENSOR STATUS" : original;
    }
  };
  $("#adv-profile-save").onclick=async()=>{const r=await api("/api/advanced/game-profile/save",{game:$("#adv-profile-game").value.trim(),profile:advProfilePayload()});if(r.error)return toast(r.error,"bad");toast("Per-game profile saved to SQLite","ok");loadAdvanced(true);};
  $("#adv-profile-propose").onclick=async()=>{const r=await api("/api/advanced/game-profile/propose-current",{});if(r.error)return toast(r.error,"bad");toast(`Profile proposal #${r.id} queued for approval in CONTROL`,"warn");loadActions();};
  $("#adv-tuner-start").onclick=async()=>{const kind=$("#adv-tuner-kind").value,args=kind==="timer_resolution"?{milliseconds:1}:{};const r=await api("/api/advanced/tuner/start",{kind,args,metric:$("#adv-tuner-metric").value,direction:$("#adv-tuner-direction").value});if(r.error)return toast(r.error,"bad");toast(`Experiment #${r.action_id} queued. Approve it in CONTROL to start the measured trial.`,"warn");loadActions();loadAdvanced(true);};
  $("#adv-wifi-propose").onclick=async()=>{const r=await api("/api/advanced/propose-wifi",{});if(r.error)return toast(r.error,"warn");toast(`Wi-Fi adjustment #${r.id} requires approval in CONTROL`,"warn");loadActions();};
  $("#adv-updater-propose").onclick=async()=>{const r=await api("/api/advanced/propose-updater",{service:$("#adv-updater").value});if(r.error)return toast(r.error,"bad");toast(`Updater pause #${r.id} requires approval in CONTROL`,"warn");loadActions();};
  $("#adv-etw-capture").onclick=async()=>{
    const button=$("#adv-etw-capture");
    button.disabled=true;
    const original=button.textContent;
    button.textContent="CHECKING ETW…";
    try {
      const proposal=await api("/api/advanced/propose-etw",{duration:12});
      if(proposal.error) { toast(proposal.error,"bad"); $("#adv-etw-note").textContent=proposal.error; return; }
      button.textContent="CAPTURING 12s…";
      const run=await api("/api/action/run",{id:proposal.id,confirmed:true});
      if(run.error) { toast(run.error,"bad"); $("#adv-etw-note").textContent=run.error; return; }
      const result=String(run.result || "ETW capture request accepted");
      toast(result,result.toLowerCase().includes("blocked") || result.toLowerCase().includes("failed") ? "bad" : "ok");
      $("#adv-etw-note").textContent=result;
      loadActions();
      loadAdvanced(true);
    } catch(error) {
      const message=error.message || String(error);
      toast("ETW capture failed: "+message,"bad");
      $("#adv-etw-note").textContent="ETW capture failed: "+message;
    } finally {
      button.disabled=false;
      button.textContent=original;
    }
  };
  $("#adv-settings-save").onclick=async()=>{
    const settings={etw_enabled:$("#adv-etw-enabled").checked,lhm_enabled:$("#adv-lhm-enabled").checked,lhm_http_port:Number($("#adv-lhm-port").value),cpu_temp_warn_c:Number($("#adv-cpu-threshold").value),gpu_temp_warn_c:Number($("#adv-gpu-threshold").value),etw_auto_interval_s:Number($("#adv-etw-interval").value)};
    const r=await api("/api/advanced/settings",settings);if(r.error)return toast(r.error,"bad");
    const a=await api("/api/config",{autopilot:{etw_capture:$("#adv-etw-auto").checked}});if(a.error)return toast(a.error,"bad");
    toast("Advanced sensor policy saved persistently","ok");loadAdvanced(true);
  };
  $("#adv-revert-all").onclick=async()=>{if(!confirm("Revert every outstanding change SENTINEL has a captured undo snapshot for? This does not undo third-party or user actions."))return;const r=await api("/api/advanced/revert-all",{confirmed:true});if(r.error)return toast(r.error,"bad");toast(`Rollback attempted ${r.attempted}; reverted ${r.reverted}`,r.reverted===r.attempted?"ok":"warn");loadAdvanced(true);};
  $("#adv-preview-kind").onchange=()=>{advDryRun=null;$("#adv-preview-propose").disabled=true;$("#adv-preview-output").innerHTML='<div class="empty">Run a fresh dry-run for the selected action.</div>';};
  $("#adv-preview-run").onclick=async()=>{
    const kind=$("#adv-preview-kind").value,args=kind==="timer_resolution"?{milliseconds:1}:{duration:12};
    const r=await api("/api/advanced/dry-run",{kind,args});advDryRun={kind,args,result:r};
    $("#adv-preview-output").innerHTML=`<pre>${esc(JSON.stringify(r,null,2))}</pre>`;
    $("#adv-preview-propose").disabled=!(r.supported===true);
  };
  $("#adv-preview-propose").onclick=async()=>{
    if(!advDryRun || advDryRun.kind!==$("#adv-preview-kind").value || advDryRun.result?.supported!==true)return toast("Run a successful dry-run for this exact action first","warn");
    const {kind,args}=advDryRun;
    const r=await api("/api/action/propose",{kind,args,reason:"Operator initiated after successful dry-run preview"});
    if(r.error)return toast(r.error,"bad");
    advDryRun=null;$("#adv-preview-propose").disabled=true;
    toast(`Action #${r.id} queued. Check CONTROL for its risk tier and approval requirements.`,"warn");
    loadActions();loadAdvanced(true);
  };
}

/* ---------- foreground activity intelligence ---------- */
let ACTIVITY = null, activityBusy = false, activityLastLoad = 0;
const activityDuration = seconds => {
  const n = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(n / 3600), m = Math.floor(n % 3600 / 60), s = n % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${s}s` : `${s}s`;
};
function renderActivityIntelligence(data) {
  const d = data && typeof data === "object" ? data : {};
  const current = d.current && typeof d.current === "object" ? d.current : {};
  const daily = d.daily && typeof d.daily === "object" ? d.daily : {};
  const apps = Array.isArray(d.apps) ? d.apps : [];
  const hourly = Array.isArray(d.hourly) ? d.hourly : [];
  const tasks = Array.isArray(d.tasks) ? d.tasks : [];
  const recent = Array.isArray(d.recent_sessions) ? d.recent_sessions : [];
  const suggestions = Array.isArray(d.suggestions) ? d.suggestions : [];
  const settings = d.settings && typeof d.settings === "object" ? d.settings : {};
  const state = String(d.state || (d.available ? "starting" : "unavailable")).toUpperCase();
  $("#ax-state").textContent = state;
  $("#ax-state").className = "pill " + (state === "ACTIVE" ? "ok" : state === "IDLE" ? "off" : state === "UNAVAILABLE" ? "bad" : "");
  $("#ax-sampled").textContent = d.sampled_at ? `sampled ${hms(d.sampled_at)}` : "awaiting foreground sample";
  $("#ax-active-today").textContent = activityDuration(daily.active_seconds);
  $("#ax-foreground-today").textContent = activityDuration(daily.foreground_seconds);
  const observedAppCount = Math.max(apps.length, Number(d.total_apps_observed || 0));
  $("#ax-app-count").textContent = observedAppCount.toLocaleString();
  $("#ax-task-count").textContent = tasks.length.toLocaleString();
  $("#ax-active-meter").style.width = Math.min(100, Number(daily.active_seconds || 0) / 28800 * 100) + "%";
  $("#ax-foreground-meter").style.width = Math.min(100, Number(daily.foreground_seconds || 0) / 43200 * 100) + "%";
  $("#ax-app-meter").style.width = Math.min(100, observedAppCount * 3) + "%";
  $("#ax-task-meter").style.width = Math.min(100, tasks.length * 6) + "%";

  $("#ax-current-app").textContent = current.app_name || "No foreground application";
  const wc = current.window_class ? ` · ${current.window_class}` : "";
  $("#ax-current-meta").textContent = current.app_name
    ? `PID ${current.pid ?? "unavailable"}${wc} · ${current.is_game ? "tracked game" : current.is_fullscreen ? "fullscreen foreground" : "foreground app"}`
    : (d.reason || "Switch to an application to begin a foreground session");
  $("#ax-focus-initial").textContent = String(current.app_name || "S").trim().slice(0,1).toUpperCase();
  $("#ax-focus-mode").textContent = current.is_active ? "USER ACTIVE" : current.app_name ? "FOREGROUND / IDLE" : "WAITING FOR USER ACTIVITY";
  $("#ax-current-foreground").textContent = activityDuration(current.foreground_seconds);
  $("#ax-current-active").textContent = activityDuration(current.active_seconds);
  $("#ax-current-idle").textContent = activityDuration(current.idle_seconds);
  const terms = Array.isArray(current.semantic_terms) ? current.semantic_terms : [];
  $("#ax-current-terms").innerHTML = terms.length
    ? terms.slice(0,18).map((term,i)=>`<span class="activity-token ${i<3?"primary":""}">${esc(term)}</span>`).join("")
    : '<span class="activity-token muted">No semantic terms observed</span>';
  $("#ax-current-task").textContent = current.task_label || "Task context forms as semantic terms repeat across sessions";

  const maxHour = Math.max(1, ...hourly.map(x => Number(x.active_seconds || 0)));
  $("#ax-hour-chart").innerHTML = hourly.length ? hourly.map(item => {
    const value = Math.max(0, Number(item.active_seconds || 0));
    const height = value > 0 ? Math.max(3, value / maxHour * 100) : 1.5;
    const hour = Number(item.hour || 0);
    return `<div class="activity-hour" title="${String(hour).padStart(2,"0")}:00 · ${activityDuration(value)} · ${Number(item.sessions||0)} session(s)"><i style="height:${height.toFixed(1)}%"></i><small>${hour%4===0?String(hour).padStart(2,"0"):""}</small></div>`;
  }).join("") : '<div class="empty">No hourly history yet.</div>';

  const maxApp = Math.max(1, ...apps.map(x => Number(x.active_seconds_7d || 0)));
  $("#ax-apps").innerHTML = apps.length ? apps.slice(0,14).map((item,index) => {
    const active = Number(item.active_seconds_7d || 0), foreground = Number(item.foreground_seconds_7d || 0);
    const percent = Math.min(100, active / maxApp * 100);
    return `<div class="activity-app-row"><div class="activity-rank">${String(index+1).padStart(2,"0")}</div><div class="activity-app-main"><div class="activity-app-head"><b>${esc(item.app_name||"Observed app")}</b><span>${activityDuration(active)}</span></div><div class="activity-app-track"><i style="width:${percent.toFixed(1)}%"></i></div><small>${Number(item.focus_sessions||0)} focus session(s) · ${activityDuration(foreground)} foreground · ${item.launchable?"observed EXE can be opened":"launch path unavailable"}</small></div></div>`;
  }).join("") : '<div class="empty">Application usage will appear after foreground sessions are observed.</div>';

  $("#ax-tasks").innerHTML = tasks.length ? tasks.map(task => {
    const taskTerms = Array.isArray(task.terms) ? task.terms : [];
    return `<div class="activity-task"><div class="activity-task-head"><b>${esc(task.label||"Observed task")}</b><span>${activityDuration(task.active_seconds)}</span></div><small>${Number(task.observations||0)} session observation(s) · ${Array.isArray(task.applications)?task.applications.length:0} application(s) · last ${task.last_seen?hms(task.last_seen):"unknown"}</small><div class="activity-token-list">${taskTerms.slice(0,8).map(term=>`<span class="activity-token">${esc(term)}</span>`).join("")}</div></div>`;
  }).join("") : '<div class="empty">Task clusters emerge from repeated co-occurring terms, not predefined app categories.</div>';

  $("#ax-suggestions").innerHTML = suggestions.length ? suggestions.map(item => {
    const confidence = Math.round(Math.max(0,Math.min(1,Number(item.confidence||0)))*100);
    const canLaunch = item.launchable && !item.already_running;
    return `<div class="activity-suggestion"><div class="activity-suggestion-top"><div><b>${esc(item.app_name||"Observed application")}</b><small>${esc(item.reason||"Learned transition")}</small></div><span class="activity-confidence">${confidence}%</span></div><div class="activity-app-track"><i style="width:${confidence}%"></i></div><div class="activity-suggestion-foot"><span class="activity-token ${item.auto_threshold?"primary":""}">${item.auto_threshold?"REPEATED PATTERN":"LEARNING"}</span><small>${Number(item.observations||0)} observations · ${item.already_running?"already running":canLaunch?"observed install":"not launchable"}</small>${canLaunch?`<button class="btn sm" data-activity-launch="${esc(item.app_key)}">OPEN APP</button>`:""}</div></div>`;
  }).join("") : '<div class="empty">The engine needs repeated transition observations before it can predict a useful next app.</div>';

  $("#ax-recent").innerHTML = recent.length ? recent.slice(0,30).map(session => {
    const sessionTerms = Array.isArray(session.semantic_terms) ? session.semantic_terms : [];
    const end = session.ended_at ? new Date(session.ended_at*1000).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}) : "current";
    return `<div class="activity-recent-row"><div class="activity-recent-time"><b>${new Date(session.started_at*1000).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}</b><small>${end}</small></div><div class="activity-recent-main"><b>${esc(session.app_name||"Application")}</b><small>${activityDuration(session.active_seconds)} active · ${activityDuration(session.idle_seconds)} idle · ${session.is_game?"GAME":session.is_fullscreen?"FULLSCREEN":"WINDOWED"}${session.interrupted?" · INTERRUPTED":""}</small><div class="activity-token-list">${sessionTerms.slice(0,5).map(term=>`<span class="activity-token">${esc(term)}</span>`).join("")}</div></div></div>`;
  }).join("") : '<div class="empty">Recent sessions appear as focus moves between applications.</div>';

  const toggles = [["ax-enabled","enabled"],["ax-semantic","semantic_context"],["ax-suggestions-enabled","suggestions_enabled"],["ax-auto-launch","auto_launch_learned_apps"]];
  for (const [id,key] of toggles) { const el=$("#"+id); if(el && document.activeElement!==el)el.checked=!!settings[key]; }
  const numeric = [["ax-interval","sample_interval_s"],["ax-idle","idle_after_seconds"],["ax-min-observations","min_launch_observations"],["ax-launch-cooldown","auto_launch_cooldown_s"]];
  for (const [id,key] of numeric) { const el=$("#"+id); if(el && document.activeElement!==el)el.value=Number(settings[key]||0); }
  $$("[data-activity-launch]").forEach(button => button.onclick = async () => {
    button.disabled = true; button.textContent = "OPENING…";
    try {
      const result = await api("/api/activity/launch", {app_key:button.dataset.activityLaunch});
      if (result.error) throw new Error(result.error);
      toast("Opened " + (result.app_name || "observed application"), "ok");
      await loadActivityIntelligence(true);
    } catch(error) { toast("Application launch: " + (error.message || String(error)), "warn"); }
    finally { button.disabled = false; button.textContent = "OPEN APP"; }
  });
}
async function loadActivityIntelligence(force=false) {
  if (activityBusy || (view !== "activityx" && !force)) return !!ACTIVITY;
  if (!force && Date.now() - activityLastLoad < 2500) return !!ACTIVITY;
  activityBusy = true; activityLastLoad = Date.now();
  try {
    const data = await api("/api/activity");
    if (data.error) throw new Error(data.error);
    ACTIVITY = data; renderActivityIntelligence(data);
    return true;
  } catch(error) { toast("Activity intelligence: " + (error.message || String(error)), "warn"); return false; }
  finally { activityBusy = false; }
}
function initActivityIntelligence() {
  $("#ax-refresh").onclick = () => loadActivityIntelligence(true);
  $("#ax-save-settings").onclick = async () => {
    const button = $("#ax-save-settings");
    const payload = {
      enabled: $("#ax-enabled").checked,
      semantic_context: $("#ax-semantic").checked,
      suggestions_enabled: $("#ax-suggestions-enabled").checked,
      auto_launch_learned_apps: $("#ax-auto-launch").checked,
      sample_interval_s: Number($("#ax-interval").value),
      idle_after_seconds: Number($("#ax-idle").value),
      min_launch_observations: Number($("#ax-min-observations").value),
      auto_launch_cooldown_s: Number($("#ax-launch-cooldown").value),
    };
    button.disabled = true; button.textContent = "SAVING…";
    try {
      const result = await api("/api/activity/settings", payload);
      if (result.error) throw new Error(result.error);
      $("#ax-policy-status").textContent = "Saved · activity samples and transition learning are local to this Windows profile.";
      toast("Activity learning policy saved locally", "ok");
      await loadActivityIntelligence(true);
    } catch(error) { toast("Activity policy: " + (error.message || String(error)), "bad"); }
    finally { button.disabled = false; button.textContent = "SAVE ACTIVITY POLICY"; }
  };
}

/* ---------- additive AIE intelligence: evidence, memory, planning and read-only UIA ---------- */
let IX = { state: [], memories: [], goals: [], runtime: {} };
let ixBusy = false, ixLoaded = false;
function ixList(value, ...keys) {
  if (Array.isArray(value)) return value.filter(item => item && typeof item === "object" && !Array.isArray(item));
  if (!value || typeof value !== "object") return [];
  for (const key of keys) {
    if (Array.isArray(value[key])) return value[key].filter(item => item && typeof item === "object" && !Array.isArray(item));
  }
  return [];
}
function ixObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}
async function loadIntelligence() {
  if (ixBusy) return ixLoaded;
  ixBusy = true;
  try {
    const [ctxRaw, memRaw, activeRaw, pausedRaw, completedRaw, runtimeRaw] = await Promise.all([
      apiRetry("/api/intelligence/context", 2), apiRetry("/api/intelligence/memories?limit=100", 2),
      apiRetry("/api/intelligence/goals?status=active", 2), apiRetry("/api/intelligence/goals?status=paused", 2),
      apiRetry("/api/intelligence/goals?status=completed", 2), apiRetry("/api/intelligence/runtime", 2)
    ]);
    const ctx = ixObject(ctxRaw);
    if (ctx.error) throw new Error(String(ctx.error));
    IX.state = ixList(ctx.ranked_state, "ranked_state", "items", "rows");
    IX.memories = ixList(memRaw, "memories", "items", "results", "rows");
    IX.goals = [
      ...ixList(activeRaw, "goals", "items", "rows"),
      ...ixList(pausedRaw, "goals", "items", "rows"),
      ...ixList(completedRaw, "goals", "items", "rows")
    ];
    IX.runtime = ixObject(runtimeRaw.error ? {} : runtimeRaw);
    const coverage = ixObject(ctx.coverage);
    const total = Object.values(coverage).reduce((sum, item) => {
      const count = Number(ixObject(item).observed_entities || 0);
      return sum + (Number.isFinite(count) ? count : 0);
    }, 0);
    $("#ix-count").textContent = total.toLocaleString();
    $("#ix-count-m").style.width = Math.min(100, total / 5) + "%";
    $("#ix-memory-count").textContent = IX.memories.length.toLocaleString();
    $("#ix-memory-m").style.width = Math.min(100, IX.memories.length * 2) + "%";
    const activeGoalCount = IX.goals.filter(goal => goal.status === "active").length;
    $("#ix-goal-count").textContent = activeGoalCount.toLocaleString();
    $("#ix-goal-m").style.width = Math.min(100, activeGoalCount * 10) + "%";
    $("#ix-state-meta").textContent = `${IX.state.length} ranked records · ${Number(ctx.new_evidence_records || 0)} new evidence events`;
    renderIXState();
    renderIXMemories();
    await renderIXGoals();
    renderIXRuntime();
    void loadWindowsKnowledgeStatus();
    const loadError = $("#ix-load-error");
    if (loadError) { loadError.hidden = true; loadError.classList.remove("stale"); }
    ixLoaded = true;
    return true;
  } catch (error) {
    const loadError = $("#ix-load-error");
    const errorText = $("#ix-load-error-text");
    const hasSnapshot = IX.state.length + IX.memories.length + IX.goals.length > 0;
    if (loadError) { loadError.hidden = false; loadError.classList.toggle("stale", hasSnapshot); }
    if (errorText) errorText.textContent = hasSnapshot
      ? "Agent link interrupted · showing the latest intelligence snapshot"
      : "Intelligence data is temporarily unavailable · retry the local agent link";
    toast("Intelligence refresh: " + (error?.message || String(error)), "warn");
    return false;
  } finally {
    ixBusy = false;
  }
}
let IX_KNOWLEDGE = { status: null, results: [] };
async function loadWindowsKnowledgeStatus(){
  const state=document.getElementById("ix-kb-state"),stats=document.getElementById("ix-kb-stats");
  try{
    const [data,sources]=await Promise.all([
      apiRetry("/api/knowledge/status",1),apiRetry("/api/knowledge/sources?limit=80",1)
    ]);
    if(data.error)throw new Error(data.error);
    IX_KNOWLEDGE.status=data;
    IX_KNOWLEDGE.sources=Array.isArray(sources)?sources:[];
    if(state)state.textContent=String(data.sources||0)+" SOURCES · "+String(data.chunks||0)+" CHUNKS";
    if(stats)stats.textContent=(data.documents||0)+" documents indexed across "+(data.sources||0)+
      " approved sources · "+(data.chunks||0)+" searchable chunks · Windows build "+
      (data.windows?.build||"unknown")+" · "+(data.windows?.edition||"edition unknown")+" · "+
      (data.windows?.architecture||"architecture unknown")+" · LOCAL ONLY";
    renderWindowsKnowledgeSources();
    return data;
  }catch(error){
    if(state)state.textContent="KNOWLEDGE INDEX UNAVAILABLE";
    if(stats)stats.textContent=error.message||String(error);
    return null;
  }
}
function renderWindowsKnowledgeSources(){
  const host=document.getElementById("ix-kb-sources");if(!host)return;
  const rows=Array.isArray(IX_KNOWLEDGE.sources)?IX_KNOWLEDGE.sources:[];
  host.innerHTML=rows.length?rows.map(source=>
    '<div class="ix-kb-source-row"><div><b>'+esc(source.title)+'</b><small>'+esc(source.publisher)+' · '+
    esc(source.component)+' · '+esc(source.windows_edition||"any edition")+' · '+
    esc(source.architecture||"any architecture")+' · '+esc(source.licence||"licence not recorded")+'</small><small>'+esc(source.url)+'</small></div>'+
    '<span>'+esc(String(source.document_count||0))+' DOC / '+esc(String(source.chunk_count||0))+
    ' CHUNKS</span></div>').join(""):'<div class="empty">No sources registered. Add a Microsoft or OEM documentation page above.</div>';
}
function renderWindowsKnowledgeResults(){
  const host=document.getElementById("ix-kb-results");if(!host)return;
  const rows=Array.isArray(IX_KNOWLEDGE.results)?IX_KNOWLEDGE.results:[];
  host.innerHTML=rows.length?rows.map(item=>{
    const src=item.source||{},doc=item.document||{},build=item.windows_build||{};
    return '<article class="ix-kb-result"><div class="ix-kb-result-head"><b>'+esc(doc.title||src.title||"Documentation chunk")+
      '</b><span>'+Math.round(Number(item.score||0)*100)+'% relevance</span></div>'+
      '<p>'+esc(item.snippet||"")+'</p><div class="ix-kb-source">'+esc(src.publisher||"Publisher unknown")+
      ' · '+esc(src.component||"other")+' · '+esc(build.compatibility||"build unknown")+'</div>'+
      '<small>'+esc(src.url||"")+' · '+esc(src.licence||"licence not recorded")+' · SHA-256 '+esc(String(doc.sha256||"").slice(0,16))+
      ' · '+esc(item.citation||"")+'</small><small>'+esc(item.windows_edition?.required||"any edition")+
      ' · '+esc(item.architecture?.required||"any architecture")+
      (item.api_version?" · API "+esc(item.api_version):"")+'</small></article>';
  }).join(""):'<div class="empty">No indexed passages matched. Add an approved source or use different technical terms.</div>';
}
async function searchWindowsKnowledge(){
  const query=document.getElementById("ix-kb-query")?.value.trim()||"";
  if(!query)return toast("Enter a Windows troubleshooting query first","warn");
  const button=document.getElementById("ix-kb-search");if(button){button.disabled=true;button.textContent="SEARCHING";}
  try{
    const data=await api("/api/knowledge/search?q="+encodeURIComponent(query)+"&limit=10");
    if(data.error)throw new Error(data.error);
    IX_KNOWLEDGE.results=Array.isArray(data.results)?data.results:[];
    renderWindowsKnowledgeResults();
    toast("Local knowledge search returned "+IX_KNOWLEDGE.results.length+" citations","ok");
  }catch(error){toast("Knowledge search: "+(error.message||String(error)),"bad");}
  finally{if(button){button.disabled=false;button.textContent="SEARCH LOCAL INDEX";}}
}
function renderWindowsSpecialist(result){
  const host=document.getElementById("ix-win-result");if(!host)return;
  const citations=Array.isArray(result.citations)?result.citations:[];
  const recs=Array.isArray(result.recommendations)?result.recommendations:[];
  const evidence=Array.isArray(result.telemetry_evidence?.metrics)?result.telemetry_evidence.metrics:[];
  host.innerHTML='<div class="ix-specialist-diagnosis"><div><small>'+esc(String(result.confidence||"unknown").toUpperCase())+' CONFIDENCE · '+esc(result.model||"LOCAL MODEL")+'</small><b>'+esc(result.diagnosis||"No diagnosis returned")+'</b><p>'+esc(result.uncertainty||"")+'</p></div></div>'+
    '<div class="ix-specialist-metrics">'+evidence.map(item=>'<span><small>'+esc(item.id.replace("metric.",""))+'</small><b>'+esc(String(item.value))+' '+esc(item.unit)+'</b></span>').join("")+'</div>'+
    '<div class="ix-specialist-recs">'+recs.map(item=>'<article><b>'+esc(item.title)+'</b><p>'+esc(item.rationale)+'</p><small>'+(item.action_id?'PREVIEW + EXPLICIT CONFIRMATION REQUIRED':'ADVISORY / NO ACTION')+'</small></article>').join("")+'</div>'+
    '<div class="ix-specialist-citations">'+citations.map(item=>'<a href="'+esc(item.url)+'" target="_blank" rel="noopener noreferrer"><b>'+esc(item.publisher)+' · '+esc(item.title)+'</b><small>'+esc(item.citation)+'</small></a>').join("")+'</div>'+
    '<div class="msg"><small>SAFETY BOUNDARY</small>Suggestions are not executed. Maintenance remains manual-only; every change requires a fresh preview and explicit confirmation. Model output cannot grant permissions.</div>';
}
function initWindowsKnowledge(){
  const diagnose=document.getElementById("ix-win-diagnose"),question=document.getElementById("ix-win-question");
  const runDiagnosis=async()=>{
    const value=question?.value.trim()||"";
    if(!value)return toast("Describe the Windows issue first","warn");
    if(diagnose){diagnose.disabled=true;diagnose.textContent="ANALYSING…";}
    const host=document.getElementById("ix-win-result");
    if(host)host.innerHTML='<div class="empty">Correlating local telemetry with version-matched documentation…</div>';
    try{
      const result=await api("/api/windows-intelligence/diagnose",{question:value});
      if(result.error)throw new Error(result.error);
      renderWindowsSpecialist(result);
      toast("Local Windows specialist analysis complete","ok");
    }catch(error){
      if(host)host.innerHTML='<div class="empty">'+esc(error.message||String(error))+'</div>';
      toast("Windows specialist: "+(error.message||String(error)),"warn");
    }finally{if(diagnose){diagnose.disabled=false;diagnose.textContent="ANALYSE WITH LOCAL MODEL";}}
  };
  if(diagnose)diagnose.onclick=runDiagnosis;
  if(question)question.addEventListener("keydown",event=>{if(event.key==="Enter")runDiagnosis();});
  const add=document.getElementById("ix-kb-add"),search=document.getElementById("ix-kb-search");
  if(search)search.onclick=searchWindowsKnowledge;
  const query=document.getElementById("ix-kb-query");
  if(query)query.addEventListener("keydown",event=>{if(event.key==="Enter")searchWindowsKnowledge();});
  if(add)add.onclick=async()=>{
    const url=document.getElementById("ix-kb-url")?.value.trim()||"";
    const title=document.getElementById("ix-kb-title")?.value.trim()||"";
    const component=document.getElementById("ix-kb-component")?.value||"other";
    const licence=document.getElementById("ix-kb-licence")?.value.trim()||"not_recorded";
    const windows_edition=document.getElementById("ix-kb-edition")?.value||null;
    const architecture=document.getElementById("ix-kb-architecture")?.value||null;
    const api_version=document.getElementById("ix-kb-api-version")?.value.trim()||null;
    const min_build=Number(document.getElementById("ix-kb-min-build")?.value)||null;
    const max_build=Number(document.getElementById("ix-kb-max-build")?.value)||null;
    if(!url||!title)return toast("Enter the official documentation URL and title","warn");
    add.disabled=true;add.textContent="REGISTERING SOURCE";
    try{
      const source=await api("/api/knowledge/source/register",{url,title,component,licence,windows_edition,architecture,api_version,min_build,max_build});
      if(source.error)throw new Error(source.error);
      add.textContent="INDEXING DOCUMENTATION";
      const indexed=await api("/api/knowledge/source/ingest",{source_id:source.source_id});
      if(indexed.error)throw new Error(indexed.error);
      document.getElementById("ix-kb-url").value="";
      document.getElementById("ix-kb-title").value="";
      document.getElementById("ix-kb-licence").value="";
      document.getElementById("ix-kb-api-version").value="";
      document.getElementById("ix-kb-min-build").value="";
      document.getElementById("ix-kb-max-build").value="";
      await loadWindowsKnowledgeStatus();
      toast(indexed.inserted?"Official page indexed locally":"This page version was already indexed","ok");
    }catch(error){toast("Knowledge ingestion: "+(error.message||String(error)),"bad");await loadWindowsKnowledgeStatus();}
    finally{add.disabled=false;add.textContent="ADD + INDEX OFFICIAL SOURCE";}
  };
}
function renderIXState() {
  const rows = Array.isArray(IX.state) ? IX.state.slice(0, 24) : [];
  $("#ix-state").innerHTML = rows.map((r, index) => {
    const evidenceIds = Array.isArray(r.evidence_ids) ? r.evidence_ids : [];
    const observed = r.last_observed ? new Date(Number(r.last_observed) * 1000).toLocaleString() : "observation time unavailable";
    return `<div class="act ix-state-row">
      <div class="d">
        <b>${esc(r.name || "Unnamed observation")}</b>
        <span>${esc(r.collection || "unknown collection")} · ${esc(r.status || "unknown")} · score ${fmt(r.score, 3)}</span>
        <small>${evidenceIds.length} evidence ref(s)${r.evidence_truncated ? " · older refs truncated" : ""} · observed ${esc(observed)}</small>
      </div>
      <div class="ix-actions">
        <span class="tag mu">${esc(r.evidence_kind || "observed")}</span>
        <button class="btn sm" data-state-evidence="${esc(evidenceIds.join(","))}" aria-expanded="false" ${evidenceIds.length ? "" : "disabled"}>${evidenceIds.length ? "VIEW EVIDENCE" : "NO EVIDENCE"}</button>
      </div>
      <div class="ix-evidence" hidden></div>
    </div>`;
  }).join("") || '<div class="empty">No evidence-backed environment rows yet. Refresh after collectors have completed an inventory scan.</div>';

  $$('[data-state-evidence]').forEach(button => {
    button.onclick = async () => {
      const card = button.closest(".ix-state-row");
      const box = card?.querySelector(".ix-evidence");
      if (!box || button.disabled) return;
      if (!box.hidden) {
        box.hidden = true;
        button.setAttribute("aria-expanded", "false");
        button.textContent = "VIEW EVIDENCE";
        return;
      }
      box.hidden = false;
      button.setAttribute("aria-expanded", "true");
      if (box.dataset.loaded === "1") {
        button.textContent = "HIDE EVIDENCE";
        return;
      }
      button.disabled = true;
      button.textContent = "LOADING…";
      box.innerHTML = '<div class="empty">Loading the observations referenced by this state row…</div>';
      try {
        const data = await api("/api/intelligence/observations?ids=" + encodeURIComponent(button.dataset.stateEvidence || ""));
        if (data.error) throw new Error(data.error);
        box.innerHTML = Array.isArray(data) && data.length
          ? data.map(item => `<div class="ix-revision"><small>${esc(item.event_type || "observation")} · ${esc(item.timestamp || "time unavailable")} · ${esc(item.source || "unknown source")}</small><span>${esc(JSON.stringify(item.payload ?? {}, null, 2))}</span></div>`).join("")
          : '<div class="empty">No retained observation rows were found for these evidence references.</div>';
        box.dataset.loaded = "1";
        button.textContent = "HIDE EVIDENCE";
      } catch (error) {
        box.innerHTML = `<div class="ix-revision"><small>EVIDENCE LOOKUP FAILED</small><span>${esc(error.message || String(error))}</span></div>`;
        button.textContent = "RETRY EVIDENCE";
      } finally {
        button.disabled = false;
      }
    };
  });
}
function renderIXMemories() {
  $("#ix-memories").innerHTML = IX.memories.map(m => `<div class="act ix-memory"><div class="d"><b>${esc(m.kind.toUpperCase())} · ${esc(m.verification.toUpperCase())}</b><span>${esc(m.content)}</span><small>${esc(m.sensitivity)} · confidence ${fmt(m.confidence, 2)} · ${m.revisions} revision(s) · ${esc(m.updated_at)}</small></div><div class="ix-actions"><button class="btn sm" data-memory-history="${esc(m.id)}">HISTORY</button><button class="btn sm" data-edit-memory="${esc(m.id)}">REVISE</button><button class="btn sm" data-del-memory="${esc(m.id)}">DELETE</button></div><div class="ix-revisions"></div></div>`).join("") || '<div class="empty">No matching non-sensitive memories. Add an explicit memory above.</div>';
  $$('[data-del-memory]').forEach(b => b.onclick = async () => { if (!confirm("Delete this memory and its revision history?")) return; const r = await api("/api/intelligence/memory/delete", { id: b.dataset.delMemory }); if (r.deleted) { toast("Memory deleted", "ok"); loadIntelligence(); } });
  $$('[data-edit-memory]').forEach(b => b.onclick = async () => { const item = IX.memories.find(x => x.id === b.dataset.editMemory); if (!item) return; const text = prompt("Revise this memory. The previous version will be retained in history.", item.content); if (text == null || !text.trim()) return; const r = await api("/api/intelligence/memory/revise", { id: item.id, content: text }); if (r.error) return toast(r.error, "bad"); toast("Memory revised; previous version preserved", "ok"); loadIntelligence(); });
  $$('[data-memory-history]').forEach(b => b.onclick = async () => { const d = await api("/api/intelligence/memory/history?id=" + encodeURIComponent(b.dataset.memoryHistory)); if (d.error) return toast(d.error, "warn"); const card = b.closest(".ix-memory"); const box = card && card.querySelector(".ix-revisions"); if (!box) return; box.innerHTML = d.length ? d.map(r => `<div class="ix-revision"><small>REVISION ${r.revision} · ${esc(new Date(r.revised_at).toLocaleString())}</small><span>${esc(r.previous.content)}</span></div>`).join("") : '<div class="empty">No previous revisions.</div>'; });
}
async function renderIXGoals() {
  const goalList = [];
  for (const raw of ixList(IX.goals, "goals")) {
    const progress = ixObject(raw.progress);
    const goal = {
      ...raw,
      progress: { completed: Number(progress.completed || 0) || 0, total: Number(progress.total || 0) || 0 },
      steps: ixList(raw.steps, "steps").map(step => ({
        ...step, dependencies: Array.isArray(step.dependencies) ? step.dependencies : [],
      })),
    };
    const response = await api("/api/intelligence/goal/plan-drafts?goal_id=" + encodeURIComponent(goal.id) + "&status=pending_review");
    const drafts = ixList(response, "drafts", "items", "rows").map(draft => {
      const plan = ixObject(draft.plan);
      return {
        ...draft,
        plan: {
          ...plan,
          steps: ixList(plan.steps, "steps").map(step => ({
            ...step, depends_on: Array.isArray(step.depends_on) ? step.depends_on : [],
          })),
        },
      };
    });
    goalList.push({ ...goal, drafts });
  }
  $("#ix-goals").innerHTML = goalList.map(g => `<div class="ix-goal">
    <div class="ix-goal-head"><div><b>${esc(g.title || "Untitled goal")}</b><small>${g.progress.completed}/${g.progress.total} steps completed · ${Math.round(g.progress.total ? g.progress.completed / g.progress.total * 100 : 0)}% · ${esc(g.status || "unknown")}</small></div>
      <div class="ix-actions"><button class="btn sm" data-plan="${esc(g.id)}" ${g.status !== "active" ? "disabled" : ""}>SUGGEST PLAN</button><button class="btn sm" data-add-step="${esc(g.id)}" ${g.status !== "active" ? "disabled" : ""}>ADD STEP</button>${g.status === "active" || g.status === "paused" ? `<button class="btn sm" data-goal-status="${esc(g.id)}" data-next-status="${g.status === "paused" ? "active" : "paused"}">${g.status === "paused" ? "RESUME" : "PAUSE"}</button>` : ""}<button class="btn sm" data-goal-history="${esc(g.id)}">HISTORY</button></div></div>
    <div class="ix-progress"><i style="width:${g.progress.total ? g.progress.completed / g.progress.total * 100 : 0}%"></i></div>
    <div class="ix-goal-history"></div>
    <div class="list">${g.steps.map(st => `<div class="row"><div><b>${esc(st.title || "Untitled step")}</b><small>${esc(st.status || "pending")}${st.dependencies.length ? " · depends on " + st.dependencies.length + " step(s)" : ""}</small></div><button class="btn sm" data-step-done="${esc(g.id)}" data-step-id="${esc(st.id)}" ${g.status !== "active" || st.status === "completed" || !st.ready ? "disabled" : ""}>${st.status === "completed" ? "DONE" : st.ready ? "COMPLETE" : "WAITING"}</button></div>`).join("") || '<div class="empty">No steps yet. Add a step or request a local plan suggestion.</div>'}</div>
    ${g.drafts.map(d => `<div class="ix-draft"><div class="ix-draft-head"><b>PLAN DRAFT · ${d.plan.steps.length} STEPS</b><span class="tag">REVIEW REQUIRED</span></div>${d.plan.steps.map((st,i) => `<div class="ix-plan-step"><b>${i+1}. ${esc(st.title || "Untitled step")}</b><small>${esc(st.description || "")}${st.depends_on.length ? " · depends on " + st.depends_on.map(x=>Number(x)+1).join(", ") : ""}</small></div>`).join("")}<div class="ix-actions"><button class="btn or sm" data-accept-draft="${esc(d.id)}">ACCEPT STEPS</button><button class="btn sm" data-reject-draft="${esc(d.id)}">REJECT</button></div></div>`).join("")}
    </div>`).join("") || '<div class="empty">No goals yet. Create a goal to begin prospective planning.</div>';
  $$('[data-plan]').forEach(b => b.onclick = async () => { b.disabled = true; b.textContent = "THINKING…"; const r = await api("/api/intelligence/goal/suggest-plan", { goal_id: b.dataset.plan }); if (r.error) toast(r.error, "warn"); else toast("Plan draft created — review before accepting", "ok"); loadIntelligence(); });
  $$('[data-add-step]').forEach(b => b.onclick = async () => { const title = prompt("Step title"); if (!title || !title.trim()) return; const r = await api("/api/intelligence/goal/step/add", { goal_id: b.dataset.addStep, title }); if (r.error) toast(r.error, "bad"); else loadIntelligence(); });
  $$('[data-goal-status]').forEach(b => b.onclick = async () => { const r = await api("/api/intelligence/goal/status", { goal_id: b.dataset.goalStatus, status: b.dataset.nextStatus }); if (r.error) toast(r.error, "bad"); else loadIntelligence(); });
  $$('[data-goal-history]').forEach(b => b.onclick = async () => { const d = await api("/api/intelligence/goal/history?id=" + encodeURIComponent(b.dataset.goalHistory)); if (d.error) return toast(d.error, "warn"); const rows = ixList(d, "history", "items", "rows"); const box = b.closest(".ix-goal")?.querySelector(".ix-goal-history"); if (!box) return; box.innerHTML = rows.length ? rows.map(r => `<div class="ix-revision"><small>${esc(r.event || "event")} · ${esc(new Date(r.occurred_at).toLocaleString())}</small><span>${esc(JSON.stringify(r.current ?? {}))}</span></div>`).join("") : '<div class="empty">No goal history.</div>'; });
  $$('[data-step-done]').forEach(b => b.onclick = async () => { const r = await api("/api/intelligence/goal/step/status", { goal_id: b.dataset.stepDone, step_id: b.dataset.stepId, status: "completed" }); if (r.error) toast(r.error, "warn"); else loadIntelligence(); });
  $$('[data-accept-draft]').forEach(b => b.onclick = async () => { if (!confirm("Accept this model-generated plan as goal steps? No system actions will be executed.")) return; const r = await api("/api/intelligence/goal/plan-draft/resolve", { draft_id: b.dataset.acceptDraft, decision: "accepted" }); if (r.error) toast(r.error, "bad"); else { toast("Reviewed plan accepted as goal steps only", "ok"); loadIntelligence(); } });
  $$('[data-reject-draft]').forEach(b => b.onclick = async () => { const r = await api("/api/intelligence/goal/plan-draft/resolve", { draft_id: b.dataset.rejectDraft, decision: "rejected" }); if (r.error) toast(r.error, "bad"); else loadIntelligence(); });
}
function renderIXRuntime() {
  const r = IX.runtime || {}; const rt = r.runtime || {}; const route = r.routing || {};
  $("#ix-ram").textContent = rt.memory_available_gib == null ? "--" : rt.memory_available_gib.toFixed(1) + " GB";
  $("#ix-pressure").textContent = rt.memory_pressure ? rt.memory_pressure.toUpperCase() + " MEMORY PRESSURE" : "runtime headroom";
  $("#ix-ram-m").style.width = rt.memory_total_gib ? Math.min(100, rt.memory_available_gib / rt.memory_total_gib * 100) + "%" : "0%";
  $("#ix-model").textContent = route.routine && route.routine.model ? route.routine.model.replace("qwen2.5:", "") : "UNAVAILABLE";
  $("#ix-model-sub").textContent = r.ollama && r.ollama.online ? `${r.ollama.models.length} local model(s) discovered` : "Ollama offline";
  $("#ix-model-m").style.width = route.routine && route.routine.available ? "100%" : "0%";
  $("#ix-ollama-state").textContent = r.ollama && r.ollama.online ? "LOOPBACK ONLINE" : "OFFLINE / UNAVAILABLE";
  const fields = [["Platform", rt.platform], ["CPU", (rt.cpu_physical ?? "--") + " physical / " + (rt.cpu_logical ?? "--") + " logical"], ["RAM total", rt.memory_total_gib == null ? "--" : rt.memory_total_gib + " GiB"], ["Available now", rt.memory_available_gib == null ? "--" : rt.memory_available_gib + " GiB"], ["Routine", route.routine?.model || "not installed"], ["Complex", route.complex?.model || "no eligible model"], ["Embeddings", route.embedding?.model || "not installed"], ["Active FAST", r.active_sentinel_models?.fast || "--"], ["Active DEEP", r.active_sentinel_models?.deep || "--"], ["DEEP guard", r.active_model_policy?.reason || "not reported"]];
  $("#ix-runtime").innerHTML = fields.map(([k,v]) => `<i>${esc(k)}</i><span>${esc(v ?? "--")}</span>`).join("");
}
function initIntelligence() {
  $("#ix-refresh-state").onclick = loadIntelligence;
  $("#ix-retry").onclick = loadIntelligence;
  $("#ix-memory-search").onclick = async () => { const q = $("#ix-memory-q").value.trim(); const include = $("#ix-include-sensitive")?.checked ? "&include_sensitive=1" : ""; const d = await api("/api/intelligence/memories?q=" + encodeURIComponent(q) + "&limit=100" + include); if (d.error) return toast(d.error, "warn"); IX.memories = ixList(d, "memories", "items", "results", "rows"); renderIXMemories(); };
  $("#ix-memory-semantic").onclick = async () => { const q = $("#ix-memory-q").value.trim(); if (!q) return toast("Enter a search query first", "warn"); const d = await api("/api/intelligence/memory/semantic?q=" + encodeURIComponent(q) + "&limit=30"); if (d.error) return toast(d.error, "warn"); IX.memories = ixList(d, "memories", "items", "results", "rows"); renderIXMemories(); toast("Local semantic retrieval complete", "ok"); };
  $("#ix-memory-add").onclick = async () => { const content = $("#ix-memory-content").value.trim(); if (!content) return toast("Enter memory content", "warn"); const r = await api("/api/intelligence/memory/add", { content, kind: $("#ix-memory-kind").value, sensitivity: $("#ix-memory-sensitivity").value, verification: "unverified", confidence: .5 }); if (r.error) return toast(r.error, "bad"); $("#ix-memory-content").value = ""; toast("Memory saved locally", "ok"); loadIntelligence(); };
  $("#ix-memory-index").onclick = async e => { e.currentTarget.disabled = true; const r = await api("/api/intelligence/memory/index", { limit: 100 }); e.currentTarget.disabled = false; if (r.error) return toast(r.error, "warn"); toast(`Indexed ${r.indexed} non-sensitive memories · ${r.model}`, "ok"); };
  $("#ix-goal-add").onclick = async () => { const title = $("#ix-goal-title").value.trim(); if (!title) return toast("Enter a goal title", "warn"); const r = await api("/api/intelligence/goal/create", { title, description: $("#ix-goal-desc").value }); if (r.error) return toast(r.error, "bad"); $("#ix-goal-title").value = ""; $("#ix-goal-desc").value = ""; toast("Goal created", "ok"); loadIntelligence(); };
  $("#ix-uia").onclick = async e => { const b = e.currentTarget; b.disabled = true; b.textContent = "INSPECTING…"; const r = await api("/api/intelligence/uia/inspect", { max_windows: 12, max_nodes: 250, max_depth: 5, timeout: 12 }); b.disabled = false; b.textContent = "INSPECT"; if (r.error) return toast(r.error, "warn");
    $("#ix-uia-result").innerHTML = !r.available ? `<div class="empty">UI Automation unavailable: ${esc(r.reason || "unknown reason")}</div>` : `<div class="row"><b>${r.nodes_inspected} structural nodes inspected</b><span class="tag ok">READ ONLY</span></div>` + (r.windows || []).map((w,i) => { const c = w.controls || [], root = c[0] || {}; const types = [...new Set(c.map(x => x.control_type).filter(Boolean))].slice(0,8); return `<div class="act"><div class="d"><b>Window ${i+1} · ${esc(root.process_name || "unknown process")}</b><span>${c.length} controls · ${esc(types.join(", "))}</span></div></div>`; }).join("") + (r.truncated ? '<div class="empty">Inspection reached a configured safety limit; output was truncated.</div>' : "");
    toast(r.available ? "Read-only UIA inspection complete" : "UIA inspection unavailable", r.available ? "ok" : "warn"); };
}

/* ---------- P1 ports: metric cards, system intelligence, evidence vault, task manager ---------- */
let ST = { events: 0 }; const mcard = (l, v, sub, pct, warn, j) => `<div class="metric${warn ? " warn" : ""}"${j ? ` data-j="${j}"` : ""}><small>${l}</small><b>${v}</b><span>${sub}</span><div class="meter"><i style="width:${Math.max(0, Math.min(100, pct || 0))}%"></i></div></div>`;
const bindJ = r => $$(r + " [data-j]").forEach(c => c.onclick = () => show(c.dataset.j));
function sensors() { const m = ST?.sensor_matrix || {}; return [m.healthy || 0, m.total || 0]; }
function setM(id, v, sub, pct, warn) { $("#m-" + id).textContent = v; const m = $("#m-" + id + "-m"); m.style.width = Math.max(0, Math.min(100, pct || 0)) + "%"; m.closest(".metric").classList.toggle("warn", !!warn); if (sub != null && $("#m-" + id + "-s")) $("#m-" + id + "-s").textContent = sub; }
function updMetrics() {
  if (!S) return; const L = S.live || {}, [ok, tot] = sensors(), posture = ST?.posture || {};
  setM("cpu", fmt(L.cpu) + "%", null, L.cpu, L.cpu > 85); setM("ram", fmt(L.mem_free_mb / 1024, 1) + " GB", "RAM headroom", 100 - (L.mem || 0), L.mem_free_mb < 1500);
  const eventCount = Number(ST?.events || 0); setM("evt", eventCount.toLocaleString(), null, Math.min(100, eventCount / 500)); setM("sen", ok + "/" + tot, "collectors healthy", tot ? ok / tot * 100 : 0, ok < tot);
  const postVal = posture.status === "incomplete" || posture.count == null ? "UNKNOWN" : posture.count;
  setM("pos", postVal, posture.status === "incomplete" ? `${(posture.unknown_sources || []).length} source(s) unknown` : posture.status === "clear" ? "no rule-based findings" : "rule-based findings", Math.min(100, (posture.count || 0) * 12), posture.status !== "clear");
}
async function loadStatus() { try { ST = await api("/api/status"); } catch (e) { } if (S && view === "cmd") updMetrics(); if (S && view === "ai") updAI(); }
const tagOK = (ok, a = "OK", b = "OFF") => `<span class="tag ${ok ? "ok" : "bad"}">${ok ? a : b}</span>`;
let CAT = "processes";
const CATS = { processes: ["name", "pid"], apps: ["name", "version", "publisher"], drivers: ["name", "display", "state", "start"], services: ["name", "display", "state", "start"], tasks: ["name", "state", "path"], interfaces: ["name", "ip", "mbps", "up"], startup: ["name", "where", "cmd"] };
async function loadCat() {
  const d = await apiRetry("/api/catalog?kind=" + CAT + "&limit=150&q=" + encodeURIComponent($("#cat-q").value), 1);
  if (d.error) return false;
  const c = CATS[CAT];
  $("#cat-t").innerHTML = "<tr>" + c.map(k => `<th>${k.toUpperCase()}</th>`).join("") + "</tr>" + d.rows.map(r => "<tr>" + c.map(k => `<td>${esc(r[k])}</td>`).join("") + "</tr>").join("") || "";
  $("#cat-n").textContent = d.matched + " of " + d.total + " records";
  return true;
}
let sysLastFetch = 0, sysFetchBusy = false;
let SYS_SNAPSHOT = null;
async function loadSys(force = false) {
  if (sysFetchBusy || (!force && Date.now() - sysLastFetch < 15000)) return !!SYS_SNAPSHOT;
  sysFetchBusy = true; sysLastFetch = Date.now();
  try {

    const d = await apiRetry("/api/inventory", 1);
    if (d.error) throw new Error(d.error);
    SYS_SNAPSHOT = d;
    const c = d.counts || {}, p = d.platform || {}, sec = d.security || {}, health = d.health || {};
    const hostName = document.getElementById("sys-host-name");
    const hostPlatform = document.getElementById("sys-host-platform");
    const headroomValue = document.getElementById("sys-headroom-value");
    const headroomBar = document.getElementById("sys-headroom-bar");
    const secureBootValue = document.getElementById("sys-secureboot-value");
    const secureBootState = document.getElementById("sys-secureboot-state");
    const appsValue = document.getElementById("sys-app-count");
    if (hostName) hostName.textContent = p.host || "UNKNOWN WINDOWS NODE";
    if (hostPlatform) hostPlatform.textContent = [p.os, p.build ? "BUILD " + p.build : "", p.cpu].filter(Boolean).join(" · ") || "Platform details unavailable";
    const ramTotal = Number(p.ram_gb), ramAvailable = Number(p.ram_available_gb);
    const ramKnown = Number.isFinite(ramTotal) && ramTotal > 0 && Number.isFinite(ramAvailable);
    if (headroomValue) headroomValue.textContent = ramKnown ? ramAvailable.toFixed(1) + " / " + ramTotal.toFixed(1) + " GB" : "UNKNOWN";
    if (headroomBar) headroomBar.style.width = ramKnown ? Math.max(0, Math.min(100, ramAvailable / ramTotal * 100)) + "%" : "0%";
    if (secureBootValue) secureBootValue.textContent = sec.secure_boot == null ? "UNKNOWN" : sec.secure_boot ? "ENABLED" : "DISABLED";
    if (secureBootState) {
      secureBootState.textContent = sec.secure_boot == null ? "SOURCE UNKNOWN" : sec.secure_boot ? "PROTECTED" : "REVIEW";
      secureBootState.classList.toggle("ok", sec.secure_boot === true);
      secureBootState.classList.toggle("warn", sec.secure_boot === false);
      secureBootState.classList.toggle("unknown", sec.secure_boot == null);
    }
    if (appsValue) appsValue.textContent = Number(c.apps || 0).toLocaleString();
    $("#sys-m").innerHTML = [["PROCESSES", "processes"], ["INSTALLED APPS", "apps"], ["SYSTEM DRIVERS", "drivers"], ["SERVICES", "services"], ["STARTUP ENTRIES", "startup"]].map(([l, k]) => mcard(l, c[k] ?? "--", d.ts ? "latest snapshot" : "not scanned", Math.min(100, (c[k] || 0) / 3))).join("");
    $("#sys-ts").textContent = d.ts ? "scanned " + hms(d.ts) : "no successful snapshot";
    $("#sys-plat").innerHTML = Object.entries({ Host: p.host, OS: p.os, Build: p.build, CPU: p.cpu, Cores: p.cpus, RAM: p.ram_gb == null ? null : p.ram_gb + " GB", "Available RAM": p.ram_available_gb == null ? null : p.ram_available_gb + " GB", BIOS: p.bios, "BIOS date": (p.bios_date || "").slice(0, 10) }).map(([k,v]) => `<i>${esc(k)}</i><span>${esc(v ?? "UNKNOWN / NOT SAMPLED")}</span>`).join("") || '<div class="empty">platform details are not yet available</div>';
    const R = (t, h) => `<div class="row"><b>${t}</b>${h}</div>`, fw = sec.firewall || [], bl = sec.bitlocker || [];
    $("#sys-sec").innerHTML = (sec.defender_rt != null ? R("Defender real-time", tagOK(sec.defender_rt, "ON", "OFF")) : R("Defender real-time", '<span class="tag mu">UNKNOWN</span>')) + (sec.signature_age_days != null ? R("Signature age", `<span class="tag ${sec.signature_age_days > 7 ? "bad" : "ok"}">${sec.signature_age_days} d</span>`) : "") + fw.map(f => R("Firewall - " + esc(f.name), tagOK(f.on, "ON", "OFF"))).join("") + (sec.secure_boot != null ? R("Secure Boot", tagOK(sec.secure_boot, "ON", "OFF")) : R("Secure Boot", '<span class="tag mu">UNKNOWN</span>')) + bl.map(b => R("BitLocker " + esc(b.mount), `<span class="tag mu">${esc(b.status)}</span>`)).join("") || '<div class="empty">No security-provider data yet.</div>';
    $("#sys-vol").innerHTML = (d.volumes || []).map(v => `<div class="row"><div style="flex:1"><b>${esc(v.mount)}</b><small>${v.free_gb} / ${v.total_gb} GB free · ${esc(v.fs)}</small><div class="bar" style="margin-top:6px"><i style="width:${100 - v.free_pct}%;${v.free_pct < 10 ? "background:var(--or)" : ""}"></i></div></div>${tagOK(v.free_pct >= 10, v.free_pct + "% free", v.free_pct + "% free")}</div>`).join("") + (d.physical || []).map(x => `<div class="row"><div><b>${esc(x.name)}</b><small>${x.gb} GB · ${esc(x.type)} · ${esc(x.bus || "bus unknown")}</small></div>${tagOK(/healthy/i.test(x.health), esc(x.health), esc(x.health))}</div>`).join("") || '<div class="empty">Storage inventory unavailable or not sampled; inspect source health below.</div>';
    $("#sys-post").innerHTML = `<div class="row"><b>Posture signal</b><span class="tag ${d.posture_summary?.status === "clear" ? "ok" : d.posture_summary?.status === "findings" ? "warn" : "bad"}">${esc((d.posture_summary?.status || "unknown").toUpperCase())}</span></div><small>${d.posture_summary?.count ?? "unknown"} findings · unknown sources: ${esc((d.posture_summary?.unknown_sources || []).join(", ") || "none")}</small>` + (d.posture || []).map(x => `<div class="ins ${x.sev === "high" ? "high" : "warn"}"><b>${esc(x.title)}</b><span>${esc(x.detail)}</span></div>`).join("") || '<div class="empty">No rule-based findings were emitted. Incomplete source coverage is not treated as a clean posture.</div>';
    const healthRows = Object.entries(health).sort(([a],[b]) => a.localeCompare(b));
    $("#sys-health").innerHTML = healthRows.map(([name, h]) => `<div class="row"><div><b>${esc(name)}</b><small>${esc(h.mode || "source probe")} · ${h.count == null ? "count unknown" : h.count + " record(s)"}</small><small>${esc(h.error || (h.errors?.length ? h.errors.length + " isolated issue(s)" : ""))}</small></div><span class="tag ${h.ok ? "ok" : "bad"}">${h.ok ? "OK" : "UNKNOWN / FAILED"}</span></div>`).join("") || '<div class="empty">No system source results are available yet.</div>';
    const storage = await api("/api/storage");
    $("#sys-storage").innerHTML = `<div class="row"><b>SQLite database</b><span class="tag ${storage.database_exists ? "ok" : "bad"}">${storage.database_exists ? "PRESENT" : "MISSING"}</span></div><small>${esc(storage.database || "path unavailable")} · ${fmt((storage.database_bytes || 0) / 1048576, 2)} MB · config revision ${esc(storage.config_revision?.revision ?? "--")}</small><small>${(storage.snapshots || []).length} bounded latest-state snapshot(s)</small><small>${Object.entries(storage.rows || {}).map(([k,v]) => `${k}: ${v ?? "unavailable"}`).join(" · ")}</small>`;
    $("#cat-k").innerHTML = Object.keys(CATS).map(k => `<button class="chip${k === CAT ? " on" : ""}" data-k="${k}">${k.toUpperCase()}</button>`).join("");
    $$("#cat-k .chip").forEach(b => b.onclick = () => { CAT = b.dataset.k; loadCat(); $$("#cat-k .chip").forEach(x => x.classList.toggle("on", x === b)); });
    $("#cat-q").oninput = loadCat;
    const catalogReady = await loadCat();
    return catalogReady;
  } catch (e) {
    toast("System inventory: " + (e?.message || "source unavailable"), "warn");
    const box = $("#sys-health"); if (box) box.innerHTML = `<div class="empty">System inventory request failed: ${esc(e?.message || "unknown error")}. Source health remains unknown until a successful scan.</div>`;
    return false;
  } finally { sysFetchBusy = false; }
}
function maybeRefreshSystem() { if (view === "sys" && Date.now() - sysLastFetch >= 15000) loadSys(false); }

let evRows = [];
async function loadEvi() {
  if (ST?.sources && $("#e-src").options.length === 1) $("#e-src").innerHTML += ST.sources.map(x => `<option>${esc(x)}</option>`).join("");
  evRows = await apiRetry("/api/events?limit=600&q=" + encodeURIComponent($("#e-q").value) + "&level=" + $("#e-lv").value + "&src=" + $("#e-src").value, 1); if (!Array.isArray(evRows)) throw new Error(evRows?.error || "Invalid evidence response"); evRows.reverse();
  $("#e-t").innerHTML = "<tr><th>TIME</th><th>LEVEL</th><th>SOURCE</th><th>MESSAGE</th></tr>" + evRows.map(r => `<tr><td>${hms(r.ts)}</td><td><span class="tag ${r.level === "error" ? "bad" : r.level === "ok" ? "ok" : "mu"}">${esc(r.level)}</span></td><td>${esc(r.src)}</td><td>${esc(r.msg)}</td></tr>`).join("");
  $("#e-n").textContent = evRows.length + " shown of " + Number(ST?.events || 0).toLocaleString() + " stored";
  return true;
}
function csvExport() { const q = v => '"' + String(v).replace(/"/g, '""') + '"'; const t = "time,level,source,message\n" + evRows.map(r => [new Date(r.ts * 1000).toISOString(), r.level, r.src, r.msg].map(q).join(",")).join("\n"); const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([t], { type: "text/csv" })); a.download = "sentinel-evidence-" + Date.now() + ".csv"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); toast("Exported " + evRows.length + " records", "ok"); }
let HISTA = [];
async function loadHist() { HISTA = await getActionRows(false); updTasks(); return true; }
function updTasks() {
  if (!S) return; const [ok, tot] = sensors(), pend = HISTA.filter(a => a.state === "pending").length;
  $("#t-m").innerHTML = mcard("ACTIVE JOBS", ok, "collectors running", tot ? ok / tot * 100 : 0, ok < tot) + mcard("TOOLS", Object.keys(NICE).length, "allowlisted actions", 60) + mcard("ACTION RUNS", HISTA.length, "retained records", Math.min(100, HISTA.length * 5)) + mcard("AWAITING APPROVAL", pend, "open CONTROL to decide", Math.min(100, pend * 25), pend > 0) + mcard("INSIGHTS", INS.length, "this session", Math.min(100, INS.length * 4));
  const n = S.now; $("#t-jobs").innerHTML = "<tr><th></th><th>JOB</th><th>EVERY</th><th>RUNS</th><th>NOTE</th></tr>" + Object.entries(S.heart).map(([k, h]) => { const late = n - h.last > Math.max(8, h.every * 3); return `<tr><td><span class="dot ${h.err ? "dead" : late ? "late" : ""}"></span></td><td>${esc(k)}</td><td>${h.every}s</td><td>${h.runs}</td><td>${esc(h.err || h.note)}</td></tr>`; }).join("");
  $("#t-hist").innerHTML = HISTA.slice(0, 40).map(a => `<div class="row"><div><b>${esc(a.desc || a.kind)}</b><small>${esc(a.origin)} · ${esc(a.reason || "")}</small></div><span class="tag ${a.state === "pending" ? "" : a.state === "failed" ? "bad" : "mu"}">${esc(a.state)}</span></div>`).join("") || '<div class="empty">no actions yet</div>';
  if (!$("#t-dis").children.length) { $("#t-dis").innerHTML = Object.keys(NICE).map(k => `<button class="btn sm" data-k="${k}">${NICE[k]}</button>`).join(""); $$("#t-dis [data-k]").forEach(b => b.onclick = async () => { const r = await api("/api/action/propose", { kind: b.dataset.k }); if (r.id) { await api("/api/action/run", { id: r.id }); toast("Ran: " + NICE[b.dataset.k], "ok"); } loadHist(); }); }
}

/* ---------- Feature Control ---------- */
const SENS = [["processes", "Process inventory & lifecycle", "full process identity, executable path, session and resource sampling"], ["kernel", "Kernel counters & ETW status", "PDH performance counters plus separate WPR/ETW session status"], ["system", "System configuration", "power plan, battery, VBS/HVCI and Defender configuration"], ["gpu", "GPU telemetry", "nvidia-smi samples: load, clocks, temperature, throttling"], ["ping", "Latency & jitter probe", "ICMP ping to 1.1.1.1 every second"], ["net", "Network connections", "established connections per process - no packet payload"], ["services", "Service watcher", "new, stopped and changed Windows services"], ["autoruns", "Startup watcher", "registry Run keys - flags new startup entries"], ["eventlog", "Windows event logs", "metadata from allowlisted channels, no Security log"], ["inventory", "System inventory & posture", "apps, drivers, security posture, storage"]];
const NUMS = [["intervals", "inventory_min", "INVENTORY SCAN / MIN", 2, 120], ["thresholds", "disk_free_pct", "LOW DISK - FREE SPACE / %", 1, 30], ["thresholds", "battery_pct", "LOW BATTERY / %", 5, 40]];
const PRESETS = { "Deep Watch": { automation: true, sensors: {}, intervals: { inventory_min: 5 }, thresholds: { disk_free_pct: 15, battery_pct: 25 } }, "Balanced": { automation: true, sensors: {}, intervals: { inventory_min: 10 }, thresholds: { disk_free_pct: 10, battery_pct: 20 } }, "Low Impact": { automation: true, sensors: { gpu: false, net: false, eventlog: false }, intervals: { inventory_min: 30 }, thresholds: { disk_free_pct: 8, battery_pct: 15 } } };
let FC = null, FCsaved = null;
const fcRead = () => { const p = { automation: $("#fc-auto").checked, sensors: {}, intervals: {}, thresholds: {} }; $$("[data-s]").forEach(c => p.sensors[c.dataset.s] = c.checked); $$("[data-n]").forEach(c => { const [g, k] = c.dataset.n.split("."); p[g][k] = +c.value; }); return p; };
const fcDirty = () => { $("#fc-dirty").hidden = JSON.stringify(fcRead()) === JSON.stringify(FCsaved); };
function fcFill(p) {
  $("#fc-auto").checked = p.automation; $("#fc-state").textContent = p.automation ? "AUTOMATION ON" : "AUTOMATION OFF - APPROVAL ONLY";
  $("#fc-sens").innerHTML = SENS.map(([k, t, d]) => `<label class="tog"><span>${t}<small>${d}</small></span><input type="checkbox" class="sw" data-s="${k}" ${p.sensors[k] ? "checked" : ""}></label>`).join("");
  $("#fc-num").innerHTML = NUMS.map(([g, k, l, lo, hi]) => `<div class="tog"><span>${l}<small>allowed ${lo}-${hi}</small></span><input type="number" min="${lo}" max="${hi}" data-n="${g}.${k}" value="${p[g][k]}" style="width:90px"></div>`).join("");
  $$("#v-fc input").forEach(i => i.onchange = i.oninput = fcDirty); fcDirty();
}
async function loadFC(keepForm) {
  const d = await apiRetry("/api/profile", 1); if (d.error || !d.profile) throw new Error(d.error || "Feature profile is unavailable"); FC = d; FCsaved = d.profile; if (!keepForm) fcFill(d.profile);
  $("#fc-pre").innerHTML = Object.keys(PRESETS).map(k => `<button class="chip on" data-p="${k}">${k.toUpperCase()}</button>`).join("");
  $$("#fc-pre [data-p]").forEach(b => b.onclick = () => { const x = PRESETS[b.dataset.p], p = { automation: x.automation, sensors: Object.fromEntries(SENS.map(([k]) => [k, x.sensors[k] !== false])), intervals: x.intervals, thresholds: x.thresholds }; fcFill(p); toast(b.dataset.p + " loaded - review, then save", "warn"); });
  const audit = await apiRetry("/api/config/history", 1); if (audit.error) throw new Error(audit.error); const rows = audit.history || []; $("#fc-audit").innerHTML = rows.map(r => `<div class="ln info"><span class="t">${hms(r.ts)}</span><span class="s">rev ${r.revision}</span><span class="m">${esc((r.changed || []).join(", ") || "settings verified; no value changes")}</span></div>`).join("") || '<div class="empty">no configuration changes yet</div>';
  return true;
}
function initFC() {
  $("#fc-save").onclick = async () => { const b = $("#fc-save"); b.disabled = true; const r = await api("/api/profile", { profile: fcRead() }); b.disabled = false; if (r.error) return toast(r.error, "bad"); toast(r.changed && r.changed.length ? "Saved: " + r.changed.join(", ") : "No changes to save", "ok"); FCsaved = r.profile; fcFill(r.profile); loadFC(true); };
  $("#fc-reload").onclick = () => { loadFC(); toast("Reloaded saved settings"); };
}

/* ---------- palette + alerts ---------- */
/* ---------- independent Engine Deck ---------- */
let ENGINE = null, engineProcessRows = [];
const engineFacts = rows => rows.map(([label, value]) =>
  "<div><i>" + esc(label) + "</i><b>" + esc(value ?? "--") + "</b></div>"
).join("");

function setEnginePulse(key, value, tone = "unknown") {
  const card = document.querySelector('[data-engine-pulse="' + key + '"]');
  const output = document.getElementById("engine-pulse-" + key);
  if (output) output.textContent = String(value || "UNKNOWN").replaceAll("_", " ").toUpperCase();
  if (card) {
    card.classList.remove("online", "caution", "blocked", "unknown");
    card.classList.add(["online", "caution", "blocked"].includes(tone) ? tone : "unknown");
  }
}
function renderEngines(data) {
  ENGINE = data || {};
  const safe = data.safeguard || {}, runtime = data.runtime || {}, ai = data.ai || {}, mem = data.memory || {};
  const valorant = safe.mode === "valorant_read_only";
  $("#engine-health").textContent = valorant ? "VALORANT / READ ONLY" : safe.mode === "fail_closed_unknown" ? "FAIL-CLOSED" : "POLICY ONLINE";
  $("#engine-health").className = "pill " + (valorant ? "game" : safe.mode === "fail_closed_unknown" ? "bad" : "ok");
  $("#engine-guard-banner").classList.toggle("hot", valorant || safe.mode === "fail_closed_unknown");
  $("#engine-guard-title").textContent = valorant ? "VALORANT SAFETY INTERLOCK ACTIVE" : safe.mode === "fail_closed_unknown" ? "PROCESS STATE UNKNOWN · MUTATIONS LOCKED" : "SAFETY POLICY ONLINE";
  $("#engine-guard-detail").textContent = valorant
    ? "Telemetry only. No WPR/ETW capture, process tuning, power changes, service control or other system mutations."
    : safe.policy_note || "Backend action policy is active.";
  $("#engine-guard-mode").textContent = String(safe.mode || "UNKNOWN").replaceAll("_", " ").toUpperCase();
  $("#engine-safe-state").textContent = valorant ? "STRICT READ-ONLY" : safe.system_mutations_allowed ? "GUARDED / ACTIVE" : "FAIL-CLOSED";
  setEnginePulse("safeguard", valorant ? "READ ONLY" : safe.system_mutations_allowed ? "GUARDED" : "FAIL-CLOSED", safe.mode === "fail_closed_unknown" ? "blocked" : valorant ? "caution" : "online");
  $("#engine-safe-facts").innerHTML = engineFacts([
    ["VALORANT", safe.valorant_active ? "DETECTED" : "NOT DETECTED"],
    ["PROCESS MONITOR", safe.process_detection_complete ? "HEALTHY" : "UNKNOWN / DISABLED"],
    ["ADMIN CONTEXT", safe.administrator ? "ELEVATED" : "NOT ELEVATED"],
    ["KERNEL TRACE", safe.kernel_trace_allowed ? "PERMITTED BY POLICY" : "BLOCKED"],
    ["VANGUARD VGC", safe.vanguard_services?.vgc || "UNKNOWN"],
    ["VANGUARD VGK", safe.vanguard_services?.vgk || "UNKNOWN"]
  ]);
  $("#engine-runtime-state").textContent = String(runtime.mode || "UNKNOWN").replaceAll("_", " ").toUpperCase();
  setEnginePulse("runtime", runtime.mode || "UNKNOWN", ["resource_pressure", "reduced", "constrained"].includes(String(runtime.mode || "").toLowerCase()) ? "caution" : runtime.mode ? "online" : "unknown");
  $("#engine-runtime-facts").innerHTML = engineFacts([
    ["HOST CPU", runtime.cpu_percent == null ? "--" : fmt(runtime.cpu_percent, 1) + "%"],
    ["AVAILABLE RAM", runtime.available_memory_gib == null ? "--" : fmt(runtime.available_memory_gib, 2) + " GiB"],
    ["PROCESS SCAN", runtime.process_scan_interval_s == null ? "--" : fmt(runtime.process_scan_interval_s, 1) + " s"],
    ["INVENTORY SCALE", runtime.inventory_interval_multiplier == null ? "--" : runtime.inventory_interval_multiplier + "×"],
    ["FAST AI", runtime.fast_ai_allowed ? "ADMITTED" : "DEFERRED"],
    ["DEEP AI", runtime.deep_ai_allowed ? "ADMITTED" : "DEFERRED"]
  ]);
  $("#engine-ai-state").textContent = ai.fast_triage_allowed ? "ORCHESTRATOR READY" : "RESOURCE / GAME GATED";
  setEnginePulse("ai", ai.fast_triage_allowed ? "ADMITTED" : "DEFERRED", ai.fast_triage_allowed ? "online" : "caution");
  $("#engine-ai-facts").innerHTML = engineFacts([
    ["FAST TRIAGE", ai.fast_triage_allowed ? "ADMITTED" : "DEFERRED"],
    ["DEEP MODEL", ai.deep_allowed ? "ADMITTED" : "DEFERRED"],
    ["FAST REASON", ai.fast_triage_reason || "--"],
    ["DEEP REASON", ai.deep_reason || "--"],
    ["TRANSPORT", ai.model_transport || "AI CORE"],
    ["EXECUTION AUTHORITY", "DETERMINISTIC POLICY"]
  ]);
  $("#engine-memory-state").textContent = String(mem.level || "UNKNOWN").toUpperCase() + " MEMORY PRESSURE";
  const memoryLevel = String(mem.level || "").toLowerCase();
  setEnginePulse("memory", memoryLevel || "UNKNOWN", ["high", "critical", "constrained"].includes(memoryLevel) ? "caution" : memoryLevel ? "online" : "unknown");
  $("#engine-memory-facts").innerHTML = engineFacts([
    ["AVAILABLE RAM", mem.available_gib == null ? "--" : fmt(mem.available_gib, 2) + " GiB"],
    ["RAM USED", mem.used_percent == null ? "--" : fmt(mem.used_percent, 1) + "%"],
    ["CACHE", mem.cache_entries == null ? "--" : mem.cache_entries + " entries"],
    ["TRIAGE BUDGET", mem.budgets?.triage_chars ?? "--"],
    ["INVESTIGATION BUDGET", mem.budgets?.investigation_chars ?? "--"],
    ["DURABLE STORE", "SQLITE / PRESERVED"]
  ]);
  const process = data.process_intelligence || {};
  const recent = Array.isArray(process.recent) ? process.recent.slice(0, 8) : [];
  engineProcessRows = recent;
  $("#engine-process-summary").textContent = (process.observed || 0) + " process starts observed · " +
    (process.review_candidates || 0) + " review candidates this run · no automatic termination";
  $("#engine-process-list").innerHTML = recent.map((row, index) => {
    const risk = row.assessment || {}, tone = risk.level === "high" ? "bad" : risk.level === "review" ? "warn" : "mu";
    const userWindow = row.session_id != null && Number(row.session_id) > 0 &&
      Number(row.visible_windows || 0) > 0 && Number(row.onscreen_windows || 0) > 0 &&
      row.path_state === "present" && risk.level !== "protected" && !valorant;
    return '<div class="engine-process-row" data-process-card="' + index + '"><span class="tag ' + tone + '">' +
      esc((risk.level || "normal").toUpperCase()) + '</span><div><b>' +
      esc(row.name) + ' · PID ' + esc(row.pid) + '</b><small>' +
      esc((risk.reasons || []).join(" · ")) + '</small><small>' +
      esc(row.exe || "executable path unavailable") + ' · parent ' +
      esc(row.parent_name || "--") + '</small></div><span class="score">' +
      esc(risk.score ?? 0) + '/100</span><div class="engine-process-actions">' +
      '<button class="btn sm" data-process-inspect="signature" data-process-index="' + index + '">VERIFY SIGNATURE</button>' +
      '<button class="btn sm" data-process-inspect="sha256" data-process-index="' + index + '">SHA-256</button>' +
      '<button class="btn sm" data-process-inspect="open_location" data-process-index="' + index + '">OPEN LOCATION</button>' +
      (userWindow ? '<button class="btn sm or" data-process-close="' + index + '">REQUEST CLOSE</button>' : '') +
      '</div><small class="engine-inspect-result" aria-live="polite"></small></div>';
  }).join("") || '<div class="empty">No process-start review candidates yet. Lifecycle observations begin after the collector warm-up baseline.</div>';
  $$("#engine-process-list [data-process-inspect]").forEach(button => {
    button.onclick = () => inspectEngineProcess(+button.dataset.processIndex, button.dataset.processInspect);
  });
  $$("#engine-process-list [data-process-close]").forEach(button => {
    button.onclick = () => requestProcessClose(+button.dataset.processClose);
  });
  const wprAvailable = !!data.wpr?.available;
  const wprState = data.wpr?.state?.state || "idle";
  const wpr = valorant ? "DISABLED DURING VALORANT"
    : !wprAvailable ? "WINDOWS WPR.EXE UNAVAILABLE"
    : !safe.administrator ? "REQUIRES ELEVATION"
    : wprState === "recording" ? "ANOTHER WPR SESSION IS RECORDING"
    : safe.kernel_trace_allowed ? "READY · BOUNDED 12s CAPTURE" : "BLOCKED BY SAFEGUARD";
  $("#engine-wpr-state").textContent = wpr;
  setEnginePulse("wpr", wpr, wpr.startsWith("READY") ? "online" : valorant ? "caution" : wpr.includes("BLOCKED") || wpr.includes("UNAVAILABLE") ? "blocked" : "unknown");
  $("#engine-wpr").disabled = !safe.kernel_trace_allowed || !wprAvailable || wprState === "recording";
  $("#engine-wpr").title = valorant ? "Tracing is hard-disabled while VALORANT is running."
    : "Propose a bounded WPR trace; an existing recording is never stopped or replaced.";
}

async function loadEngines() {
  try {
    const data = await api("/api/engines");
    if (data.error) throw new Error(data.error);
    renderEngines(data);
    return true;
  } catch (error) {
    $("#engine-health").textContent = "ENGINE API UNAVAILABLE";
    $("#engine-health").className = "pill bad";
    toast("Engine status: " + (error.message || "unavailable"), "warn");
    return false;
  }
}

async function inspectEngineProcess(index, operation) {
  const row = engineProcessRows[index];
  if (!row || !row.pid || !row.create_time || !row.exe) return toast("Exact process identity is unavailable; refresh the process list.", "warn");
  if (operation === "sha256" && !confirm("Hash this executable file using streamed SHA-256? This reads the file (up to 2 GiB) and may use disk/CPU briefly.")) return;
  const card = document.querySelector('[data-process-card="' + index + '"]');
  const result = card?.querySelector(".engine-inspect-result");
  if (result) result.textContent = "INSPECTION RUNNING…";
  const controls = card ? Array.from(card.querySelectorAll("[data-process-inspect]")) : [];
  controls.forEach(control => control.disabled = true);
  try {
    const response = await api("/api/process-intelligence/inspect", {
      pid: row.pid, create_time: row.create_time, exe: row.exe, operation
    });
    if (response.error) throw new Error(response.error);
    let message = "";
    if (operation === "signature") {
      const signature = response.signature || {};
      message = "Authenticode: " + (signature.status || "Unknown") +
        (signature.signer ? " · " + signature.signer : "") +
        (signature.thumbprint ? " · " + signature.thumbprint : "");
    } else if (operation === "sha256") {
      message = "SHA-256: " + response.digest;
    } else {
      message = "Executable folder opened in Explorer.";
    }
    if (result) result.textContent = message + " · " + (response.interpretation || "");
    toast(operation === "open_location" ? "Opened executable location" : operation.toUpperCase() + " inspection complete", "ok");
  } catch (error) {
    if (result) result.textContent = "Inspection refused/failed: " + (error.message || "unknown error");
    toast(error.message || "Process inspection failed", "warn");
  } finally {
    controls.forEach(control => control.disabled = false);
  }
}

async function requestProcessClose(index) {
  const row = engineProcessRows[index];
  if (!row || !row.pid || !row.create_time || !row.exe) return toast("Exact process identity is unavailable.", "warn");
  if (!confirm("Send a normal WM_CLOSE request to " + row.name + " (PID " + row.pid + ")? The app may show a save prompt. SENTINEL will never force-kill it.")) return;
  const card = document.querySelector('[data-process-card="' + index + '"]');
  const result = card?.querySelector(".engine-inspect-result");
  if (result) result.textContent = "REQUESTING USER-APP CLOSE…";
  try {
    const proposed = await api("/api/action/propose", {
      kind: "terminate_process",
      args: { pid: row.pid, create_time: row.create_time, exe: row.exe },
      reason: "Operator explicitly requested graceful WM_CLOSE after process review"
    });
    if (proposed.error || !proposed.id) throw new Error(proposed.error || "Request was rejected by policy.");
    if (!confirm("Review request created. Confirm once more to send WM_CLOSE. No force-termination fallback exists.")) {
      await api("/api/action/dismiss", { id: proposed.id });
      if (result) result.textContent = "Close request dismissed; process was not touched.";
      return;
    }
    const outcome = await api("/api/action/run", { id: proposed.id, confirmed: true });
    if (outcome.error) throw new Error(outcome.error);
    if (result) result.textContent = outcome.result || "WM_CLOSE request processed. The application may remain open.";
    toast("Graceful close request processed · no force kill", "warn");
  } catch (error) {
    if (result) result.textContent = "Close request refused: " + (error.message || "unknown error");
    toast(error.message || "Close request failed", "bad");
  } finally {
    await loadEngines();
  }
}

function initEngines() {
  $("#engine-refresh").onclick = loadEngines;
  $("#engine-rebalance").onclick = async () => {
    const button = $("#engine-rebalance"); button.disabled = true;
    try {
      const result = await api("/api/engines/runtime/rebalance", {});
      if (result.error) throw new Error(result.error);
      toast("Adaptive runtime policy re-evaluated", "ok"); await loadEngines();
    } catch (error) { toast(error.message || "Policy refresh failed", "bad"); }
    finally { button.disabled = false; }
  };
  $("#engine-memory-trim").onclick = async () => {
    const button = $("#engine-memory-trim"); button.disabled = true;
    try {
      const result = await api("/api/engines/memory/trim", {});
      if (result.error) throw new Error(result.error);
      toast("Cleared " + (result.cleared || 0) + " working-cache entries · durable memories preserved", "ok");
      await loadEngines();
    } catch (error) { toast(error.message || "Memory cache cleanup failed", "bad"); }
    finally { button.disabled = false; }
  };
  $("#engine-process-view").onclick = () => show("proc");
  $("#engine-wpr").onclick = async () => {
    const button = $("#engine-wpr"); button.disabled = true;
    try {
      const result = await api("/api/advanced/propose-etw", { duration: 12 });
      if (result.error) throw new Error(result.error);
      toast("WPR trace proposal created. Open CONTROL to inspect its status.", "ok");
      await loadActions(); show("ctl");
    } catch (error) { toast(error.message || "WPR proposal rejected", "warn"); await loadEngines(); }
    finally { button.disabled = false; }
  };
}

let palSel = 0, palItems = [];
function palAll() { return [...VKEYS.map((k, i) => ({ g: "SCREENS", ic: String(i + 1), t: TITLES[k], d: "Open " + TITLES[k].toLowerCase(), tag: "OPEN", go: () => show(k) })), ...Object.keys(NICE).map(k => ({ g: "ACTIONS", ic: "RUN", t: NICE[k], d: "Propose and run on this PC (allowlisted)", tag: "RUN", go: async () => { const r = await api("/api/action/propose", { kind: k }); if (r.id) { await api("/api/action/run", { id: r.id }); toast("Ran: " + NICE[k], "ok"); } loadActions(); } })), { g: "ACTIONS", ic: "LOG", t: "Export activity log", d: "Download the stream as a text file", tag: "SAVE", go: () => $("#a-exp").click() }, { g: "ACTIONS", ic: "BELL", t: "Enable desktop alerts", d: "Notify on serious lag and process review insights", tag: "ASK", go: () => $("#notifyBtn").click() }]; }
function palRender() {
  const q = $("#pal-q").value.toLowerCase(); palItems = palAll().filter(i => (i.t + " " + i.d).toLowerCase().includes(q)); palSel = Math.min(palSel, Math.max(0, palItems.length - 1));
  let g = "", h = ""; palItems.forEach((i, n) => { if (i.g !== g) { g = i.g; h += `<div class="pal-g">${g}</div>`; } h += `<button class="pal-i${n === palSel ? " sel" : ""}" data-n="${n}"><i>${i.ic}</i><span><b>${esc(i.t)}</b><small>${esc(i.d)}</small></span><em>${i.tag}</em></button>`; });
  $("#pal-list").innerHTML = h || '<div class="empty" style="padding:20px">No match. Try a shorter search.</div>';
  $$("#pal-list .pal-i").forEach(b => b.onclick = () => palRun(+b.dataset.n)); const s = $("#pal-list .sel"); if (s) s.scrollIntoView({ block: "nearest" });
}
function palOpen() { $("#pal").classList.add("open"); $("#pal-q").value = ""; palSel = 0; palRender(); $("#pal-q").focus(); }
function palClose() { $("#pal").classList.remove("open"); }
function palRun(n) { const i = palItems[n]; if (!i) return; palClose(); i.go(); }
function initPalette() {
  $("#palBtn").onclick = palOpen; const deckCommand = $("#deckCommand"); if (deckCommand) deckCommand.onclick = palOpen; $("#pal").onclick = e => { if (e.target.id === "pal") palClose(); }; $("#pal-q").oninput = () => { palSel = 0; palRender(); };
  addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#pal").classList.contains("open") ? palClose() : palOpen(); return; }
    if (!$("#pal").classList.contains("open")) return;
    if (e.key === "Escape") palClose(); else if (e.key === "ArrowDown") { e.preventDefault(); palSel = Math.min(palItems.length - 1, palSel + 1); palRender(); } else if (e.key === "ArrowUp") { e.preventDefault(); palSel = Math.max(0, palSel - 1); palRender(); } else if (e.key === "Enter") palRun(palSel);
  });
}
function initNotify() {
  const b = $("#notifyBtn"), sync = () => { b.textContent = ("Notification" in window && Notification.permission === "granted") ? "\u260E ALERTS ON" : "\u260E ALERTS"; }; sync();
  b.onclick = async () => { if (!("Notification" in window)) return toast("Desktop alerts are not supported here", "warn"); if (Notification.permission === "denied") return toast("Alerts are blocked in browser settings", "warn"); const p = await Notification.requestPermission(); sync(); toast(p === "granted" ? "Desktop alerts enabled for serious lag and process review" : "Alerts not enabled", p === "granted" ? "ok" : "warn"); };
}
const notifiedInsights = new Set();
function alertInsight(i) {
  if (!i || (i.sev !== "high" && i.sev !== "warn")) return; toast((i.title || "Insight") + (i.culprit ? " - " + i.culprit : ""), i.sev === "high" ? "bad" : "warn");
  const review = String(i.key || "").startsWith("process-review-");
  const key = String(i.id || i.key || i.ts || i.title);
  if ((i.sev === "high" || review) && !notifiedInsights.has(key) && "Notification" in window && Notification.permission === "granted" && document.hidden) {
    notifiedInsights.add(key); try { new Notification(review ? "SENTINEL process review" : "SENTINEL: " + (i.title || "Serious lag"), { body: (i.detail || "") + (review ? " — advisory only; inspect the Process tab before requesting a close." : "") }); } catch (e) { }
  }
}
boot().catch(error => {
  const message = error && error.message ? error.message : String(error);
  console.error("SENTINEL startup failed", error);
  try {
    showBootRetry("STARTUP DATA SYNC FAILED", message);
  } catch (retryError) {
    console.error("SENTINEL could not initialize startup retry", retryError);
    const overlay = document.getElementById("boot");
    if (overlay) overlay.classList.add("boot-error");
  }
});
