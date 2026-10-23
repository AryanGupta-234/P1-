"use strict";
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const qs = new URLSearchParams(location.search);
let TOKEN = qs.get("t") || ""; try { if (TOKEN) localStorage.setItem("st", TOKEN); else TOKEN = localStorage.getItem("st") || ""; } catch (e) { }
const api = (p, body) => fetch(p, { method: body ? "POST" : "GET", headers: { "X-Sentinel-Token": TOKEN, "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json());
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
const TITLES = { cmd: "COMMAND", eng: "ENGINE DECK", agent: "AGENT", sys: "SYSTEM", act: "ACTIVITY", activityx: "ACTIVITY INTELLIGENCE", proc: "PROCESSES", net: "NETWORK", ker: "KERNEL", adv: "TUNER / THERMAL", evi: "EVIDENCE", intelx: "INTELLIGENCE", int: "INTEL FEED", ai: "AI CORE", ctl: "CONTROL", fc: "FEATURES", tsk: "TASKS" };
const VKEYS = Object.keys(TITLES);
function toast(msg, kind = "") { const b = document.createElement("div"); b.className = "toast " + kind; b.textContent = msg; $("#toasts").append(b); setTimeout(() => b.remove(), 5200); }
let bootDone = false;
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
  $("#boot").classList.add("done");
  $("#app").classList.add("ready");
}
function starfield() {
  const c = $("#starfield"), x = c.getContext("2d"); if (matchMedia("(prefers-reduced-motion:reduce)").matches) return;
  let w, h, st = [], frame = 0, lastPaint = 0;
  const resize = () => { w = c.width = innerWidth; h = c.height = innerHeight; st = Array.from({ length: Math.min(48, Math.ceil(w * h / 28000)) }, () => ({ x: Math.random() * w, y: Math.random() * h, r: Math.random() * 1.1 + .3, v: Math.random() * .1 + .02 })); };
  const draw = timestamp => {
    frame = 0;
    if (document.visibilityState !== "visible") return;
    if (timestamp - lastPaint >= 42) {
      lastPaint = timestamp; x.clearRect(0, 0, w, h); x.fillStyle = "#cfe8a0";
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

/* ---------- tiles ---------- */
const TILES = [
  { k: "cpu", l: "CPU", u: "%", c: "#b8e65b", lo: 0, hi: 100, w: 75, b: 92 },
  { k: "dpc", l: "DPC TIME", u: "%", c: "#a99bff", lo: 0, hi: null, w: 3, b: 8, d: 1 },
  { k: "mem_free_mb", l: "FREE RAM", u: "MB", c: "#7cd59c", lo: 0, hi: null, w: 2500, b: 1200, inv: 1 },
  { k: "pagesout", l: "PAGE EVICT", u: "/s", c: "#ff6b38", lo: 0, hi: null, w: 100, b: 400 },
  { k: "dlat", l: "DISK LATENCY", u: "ms", c: "#ff6b38", lo: 0, hi: null, w: 12, b: 40, d: 1 },
  { k: "gpu", l: "GPU 3D", u: "%", c: "#b8e65b", lo: 0, hi: 100, w: 999, b: 999 },
  { k: "gputemp", l: "GPU TEMP", u: "°C", c: "#ff6b38", lo: 30, hi: 100, w: 80, b: 87 },
  { k: "ping", l: "PING", u: "ms", c: "#7cd59c", lo: 0, hi: null, w: 40, b: 80, d: 1 },
  { k: "jitter", l: "JITTER", u: "ms", c: "#ff6b38", lo: 0, hi: null, w: 8, b: 20, d: 1 },
  { k: "cpuperf", l: "CPU CLOCK", u: "%", c: "#b8e65b", lo: 0, hi: 130, w: 80, b: 60, inv: 1 },
  { k: "pagesin", l: "HARD FAULTS", u: "/s", c: "#a99bff", lo: 0, hi: null, w: 1500, b: 5000 },
  { k: "netdown", l: "NET DOWN", u: "Mb/s", c: "#7cd59c", lo: 0, hi: null, w: 9e9, b: 9e9, d: 1 },
];
function buildTiles() { $("#tiles").innerHTML = TILES.map(t => `<div class="tile" id="t-${t.k}"><div class="k"><span>${t.l}</span><span id="tk-${t.k}"></span></div><div class="v"><span id="tv-${t.k}">--</span><small>${t.u}</small></div><canvas id="tc-${t.k}"></canvas></div>`).join(""); }
function updTiles() {
  TILES.forEach(t => {
    const v = S.live[t.k]; if (v == null) { $("#t-" + t.k).style.opacity = .35; return; } $("#t-" + t.k).style.opacity = 1;
    $("#tv-" + t.k).textContent = fmt(v, t.d || 0);
    const bad = t.inv ? v < t.b : v > t.b, warn = t.inv ? v < t.w : v > t.w;
    $("#t-" + t.k).className = "tile" + (bad ? " bad" : warn ? " warn" : "");
    spark($("#tc-" + t.k), t.k, bad ? "#f05252" : warn ? "#ff6b38" : t.c, t.lo, t.hi);
  });
}

/* ---------- command view ---------- */
function updHero() {
  const v = S.live.lag_index ?? 0, col = v < 20 ? "#b8e65b" : v < 45 ? "#ff6b38" : "#f05252";
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
  $("#culp").innerHTML = (S.culprits || []).map(c => `<div class="act"><div class="d"><b>${esc(c.name)}</b><span>caused ${c.n} spike${c.n > 1 ? "s" : ""}</span></div><div class="bar" style="width:90px"><i style="width:${Math.min(100, c.n * 12)}%;background:linear-gradient(90deg,#ff6b38,#ff6b38)"></i></div></div>`).join("") || '<div class="empty">no culprits caught yet - background is clean</div>';
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
    return `<tr><td><span class="dot ${st}"></span>${esc(n)}</td><td>${h.every ? h.every + "s" : "-"}</td><td>${h.runs}</td><td>${fmt(age, 0)}s ago</td><td style="color:${h.err ? "#f05252" : "#829087"}">${esc(h.err || h.note)}</td></tr>`;
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
  const box = $("#proc-recs");
  if (box) box.innerHTML = reviewRows.map(r => `<div class="row"><div><b>${esc(r.name)} · PID ${r.pid}</b><small>${esc(r.reason)} · CPU ${fmt(r.cpu,1)}% · RAM ${r.mem} MB · ${r.observations} consecutive samples</small><small class="proc-path">${esc(r.exe)}</small></div><span class="tag warn">REVIEW ONLY</span></div>`).join("") || '<div class="empty">No sustained background resource-use candidate currently meets the conservative review threshold.</div>';
}
async function loadProcesses(force = false) {
  if (procFetchBusy || (view !== "proc" && !force)) return;
  const q = $("#p-q")?.value || "";
  if (!force && Date.now() - procLastFetch < 4500) { updProc(); return; }
  procFetchBusy = true;
  try {
    const endpoint = "/api/processes?limit=2000&q=" + encodeURIComponent(q);
    let d = await api(endpoint);
    // The agent collector owns process enumeration. If the page races the
    // collector's first Windows scan, wait briefly for its real snapshot.
    for (let attempt = 0; force && !d.error && !d.sampled_at && attempt < 6; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 250));
      d = await api(endpoint);
    }
    if (d.error) throw new Error(d.error);
    // Deduplicate on process-instance identity, not PID (Windows reuses PIDs).
    const unique = new Map();
    for (const row of (d.rows || [])) unique.set(procIdentity(row), row);
    PROC_ROWS = [...unique.values()]; PROC_META = { total: d.total || 0, matched: d.matched ?? PROC_ROWS.length, inaccessible: d.inaccessible || 0, sampled_at: d.sampled_at || 0, updated_at: d.updated_at || 0 };
    updProc(); procLastFetch = Date.now();
  } catch (e) { toast("Process inventory: " + e.message, "warn"); }
  finally { procFetchBusy = false; }
}
function maybeRefreshProcesses() { if (view === "proc" && Date.now() - procLastFetch > 5000) loadProcesses(true); }

function updNet() {
  $("#ntab").innerHTML = "<tr><th>Process</th><th>Remote</th><th>Port</th></tr>" + S.net.filter(c => { const q = ($("#n-q").value || "").toLowerCase(); return !q || (c.proc + " " + c.ip + " " + c.port).toLowerCase().includes(q); }).map(c => `<tr><td>${esc(c.proc)}</td><td>${esc(c.ip)}</td><td>${c.port}</td></tr>`).join(""); $("#n-n").textContent = S.net.length + " established";
  big($("#nc-ping"), [{ k: "ping", c: "#7cd59c", l: "PING ms" }, { k: "jitter", c: "#ff6b38", l: "JITTER ms" }]);
  big($("#nc-thr"), [{ k: "netdown", c: "#b8e65b", l: "DOWN Mb/s" }, { k: "netup", c: "#ff6b38", l: "UP Mb/s" }]);
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
  } catch (e) {
    table.innerHTML = `<tr><td>${esc(e.message || "archive unavailable")}</td></tr>`;
  }
}
function updKer() {
  big($("#kc-dpc"), [{ k: "dpc", c: "#a99bff", l: "PDH DPC %" }, { k: "irq", c: "#ff6b38", l: "PDH IRQ %" }]);
  big($("#kc-pg"), [{ k: "pagesin", c: "#b8e65b", l: "PAGES IN/s" }, { k: "pagesout", c: "#ff6b38", l: "PAGES OUT/s" }, { k: "pagefaults", c: "#a99bff", l: "PAGE FAULTS/s" }]);
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
async function loadIntel() { const d = await api("/api/intel"); $("#intel").innerHTML = d.map(g => `<div style="margin-bottom:14px"><div style="font:12px var(--mo);color:var(--or);letter-spacing:.1em">&gt; ${esc(g.q)}</div>` + g.items.map(i => `<div class="ref"><b><a href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a></b><span>${esc(i.src)} · ${esc(i.snippet)}</span></div>`).join("") + "</div>").join("") || '<div class="empty">crawler is warming up - first results in ~30 s. Or search above.</div>'; }
function addTr(t) { const d = document.createElement("div"); d.className = "msg " + t.role; d.innerHTML = `<small>${esc(t.role === "user" ? "you" : t.role + " · " + t.model)} · ${hms(t.ts)}</small>${esc(t.text)}`; const b = $("#tr"); b.appendChild(d); b.scrollTop = b.scrollHeight; }
function updAI() {
  const a = S.ai || {}, u = a.usage || {}, rt = ST?.agent || {};
  $("#m-fast").textContent = a.fast || "--"; $("#m-deep").textContent = a.deep || "--"; $("#n-fast").classList.toggle("act", a.busy === "fast"); $("#n-deep").classList.toggle("act", a.busy === "deep"); $("#lnk").classList.toggle("on", !!a.busy);
  if (a.status) $("#ai-status").textContent = a.status; $("#ai-url").textContent = a.online ? a.models.length + " models installed" : (a.error || "Ollama offline");
  if ($("#ai-runtime")) $("#ai-runtime").innerHTML = `<div class="row"><b>Agent process</b><span class="tag ${rt.pid ? "ok" : "bad"}">${rt.pid ? "RUNNING" : "UNKNOWN"}</span></div><small>PID ${esc(rt.pid ?? "--")} · ${esc(rt.execution_context || "context unknown")} · desktop access ${rt.desktop_access_expected ? "available in this session" : "not expected"}</small><small>${esc(rt.executable || "")} · ${esc(rt.username || "")}</small><small>Agent CPU ${fmt(rt.cpu_percent, 1)}% · RAM ${fmt(rt.rss_mb, 1)} MB (${fmt(rt.memory_percent, 2)}%) · ${esc(rt.threads ?? "--")} threads · ${esc(rt.handles ?? "--")} handles</small><small>Agent I/O read ${esc(rt.io_read_bytes == null ? "unknown" : (rt.io_read_bytes / 1048576).toFixed(1) + " MB")} · write ${esc(rt.io_write_bytes == null ? "unknown" : (rt.io_write_bytes / 1048576).toFixed(1) + " MB")}</small><div class="row"><b>Inference</b><span class="tag ${a.online ? "ok" : "bad"}">${a.busy ? "BUSY · " + esc(a.busy) : a.online ? "IDLE / READY" : "OFFLINE"}</span></div><small>Current task: ${esc(a.current_task || "none")} · model: ${esc(a.current_model || "none")}</small><small>Requests ${u.requests || 0} · success ${u.successes || 0} · failures ${u.failures || 0} · last latency ${fmt(u.last_duration_s, 2)}s</small><small>Usage history persists across agent restarts · retention: ${esc(u.history_limit || "all stored requests")}</small><small>Prompt tokens ${esc(u.last_prompt_tokens ?? "unknown")} · output tokens ${esc(u.last_output_tokens ?? "unknown")} · last model ${esc(u.last_model || "--")}</small><small>RAM headroom ${fmt(a.model_policy?.available_memory_gib, 2)} GiB · route ${esc(a.model_policy?.reason || "not evaluated")}</small>`;
}
const NICE = { wpr_trace: "Capture WPR diagnostic trace", etw_capture: "Capture kernel ETW window" };
async function loadActions() {
  const a = await api("/api/actions"), p = a.filter(x => x.state === "pending");
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
}
function buildCtl() {
  const ap = S.autopilot, policy = S.approval_policy || {}, lab = { wpr_trace: ["Auto WPR diagnostic", "bounded, read-only capture; never stops an existing trace"], etw_capture: ["Auto kernel ETW windows", "short trace windows only while a game is active"] };
  $("#auto").innerHTML = Object.keys(lab).map(k => `<label class="tog"><span>${lab[k][0]}<small>${lab[k][1]}</small></span><input type="checkbox" class="sw" data-ap="${k}" ${ap[k] ? "checked" : ""}></label>`).join("")
    + `<div class="ph" style="padding:12px 0 4px;border-top:1px solid var(--line)">AUTONOMY MASTER CONTROL<em>global execution gate</em></div><label class="tog"><span>Enable autonomous execution<small>Required before any safe autopilot or eligible reversible medium-risk action can run without a click. Safeguard checks, action budgets and rollback gates remain mandatory.</small></span><input type="checkbox" class="sw" id="auto-master" ${S.automation_master ? "checked" : ""}></label>`
    + `<div class="ph" style="padding:12px 0 4px;border-top:1px solid var(--line)">AUTONOMOUS APPROVAL POLICY<em>risk-scored · reversible only</em></div><label class="tog"><span>Auto-approve eligible medium-risk changes<small>Only game profiles, power plan, timer and Wi-Fi policy; risk ≤25, confidence ≥92%, a fresh safeguard pass and a verified undo snapshot. Updater pauses and dangerous actions remain manual/blocked.</small></span><input type="checkbox" class="sw" id="auto-medium" ${policy.auto_approve_reversible_medium !== false ? "checked" : ""}></label>`;
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
  if (agentBusy || (!force && Date.now() - agentLastLoad < 6000)) return;
  agentBusy = true;
  agentLastLoad = Date.now();
  try {
    const data = await api("/api/agent");
    if (data.error) throw new Error(data.error);
    AGENT_DETAIL = data;
    if (data.runtime) agentPushSample(data.runtime);
    updateAgentView(data.runtime, data.sensor_matrix, data.runs, data.storage);
  } catch (error) {
    $("#ag-state").textContent = "API LOST";
    $("#ag-state").className = "pill bad";
    toast("Agent overview unavailable: " + error.message, "warn");
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
  if (view === "cmd") { updTiles(); updMetrics(); }
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
  $$("#nav button").forEach(button => {
    const selected = button.dataset.v === v;
    button.classList.toggle("on", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });

  // Recently opened workspaces render from their short-lived local cache;
  // inactive screens fetch only when requested.
  if (pageIsWarm(v)) {
    if (v === "cmd") { updHero(); updTiles(); updMetrics(); }
    else if (v === "act") { updHeart(); renderFeed(); }
    else if (v === "net" && S) updNet();
    else if (v === "ai" && S) updAI();
    else if (v === "tsk" && S) updTasks();
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
    return;
  }
  ({
    cmd: () => { updTiles(); updMetrics(); },
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
    fc: loadFC
  })[v]?.();
}
async function boot() {
  const bootStartedAt = performance.now();
  starfield();
  bp(4, "POWERING SENTINEL", "Preparing the local command environment");
  buildTiles();
  buildChips();
  $$("#nav button").forEach(button => {
    const label = button.querySelector(".lb")?.textContent?.trim() || TITLES[button.dataset.v] || button.dataset.v;
    button.setAttribute("aria-label", label); button.title = label;
    if (button.dataset.v === view) button.setAttribute("aria-current", "page");
    button.onclick = () => show(button.dataset.v);
  });

  const moduleDefinitions = [
    ["core", "SESSION", "Local auth and system state"],
    ["command", "COMMAND", "Live metrics and visual layers"],
    ["agent", "RUNTIME", "Collector workers and heartbeat"],
    ["sys", "SYSTEM MAP", "Windows platform inventory"],
    ["proc", "PROCESS FIELD", "Live Windows process scan"],
    ["net", "NETWORK", "Interfaces and connections"],
    ["adv", "THERMAL / ETW", "Hardware and kernel telemetry"],
    ["stream", "LIVE LINK", "Agent event channel"]
  ];
  $("#bootModules").replaceChildren();
  moduleDefinitions.forEach(([key, label, detail]) => bootModule(key, label, "WAITING", detail));

  bp(10, "AUTHENTICATING", TOKEN ? "Local session token accepted" : "No local session token found", TOKEN ? "ok" : "bad");
    if (!TOKEN) {
    bp(100, "AUTHENTICATION REQUIRED", "Open SENTINEL from its installed desktop shortcut", "warn");
    $("#bootDetail").textContent = "Authentication required · use the installed desktop shortcut";
    $("#boot").classList.add("boot-error");
    return;
  }

  // The live process snapshot gates first paint; history and secondary panels
  // hydrate behind it so slow endpoints cannot hold the splash open.
  bootModuleState("core", "LOADING", "Authenticating and synchronizing local telemetry");
  bootModuleState("eng", "LOADING", "Reading safeguards and policy state");
  bp(18, "SYNCHRONIZING LOCAL NODE", "Agent remains online while the dashboard reads process and system state");
  const initial = await api("/api/snapshot");
  if (initial?.error) {
    const reason = initial.error || "The local agent rejected this session.";
    bootModuleState("core", "BLOCKED", String(reason).slice(0, 100));
    bp(100, "LOCAL SESSION REJECTED", String(reason).slice(0, 160), "warn");
    $("#boot").classList.add("boot-error");
    return;
  }

  S = initial;
  if (S?.live) {
    for (const [key, value] of Object.entries(S.live)) {
      if (Number.isFinite(Number(value)) && !(H[key] || []).length) H[key] = [Number(value)];
    }
  }
  INS = []; renderIns();
  bootModuleState("core", "READY", "Live process and system snapshot ready");
  void Promise.allSettled([
    api("/api/history?secs=300"), api("/api/events?limit=300"),
    api("/api/engines"), api("/api/status")
  ]).then(([historyResult, eventResult, engineResult, statusResult]) => {
    const history = historyResult.status === "fulfilled" ? historyResult.value : null;
    const events = eventResult.status === "fulfilled" ? eventResult.value : [];
    const engines = engineResult.status === "fulfilled" ? engineResult.value : null;
    const status = statusResult.status === "fulfilled" ? statusResult.value : null;
    for (const [key, samples] of Object.entries(history || {})) {
      if (Array.isArray(samples)) H[key] = samples.map(point => Number(point[1])).filter(Number.isFinite).slice(-MAXH);
    }
    (Array.isArray(events) ? events : []).forEach(addLog);
    if (engines && !engines.error) { renderEngines(engines); bootModuleState("eng", "READY", "Safeguards and policy state online"); markPageWarm("eng"); }
    else bootModuleState("eng", "DEGRADED", "Engine state is still loading");
    ST = status && !status.error ? status : null;
    if (view === "cmd") { updMetrics(); updTiles(); }
  });

  // Initialize every interaction before the views are painted.
  $("#a-q").oninput = renderFeed;
  $("#a-pause").onclick = event => { paused = !paused; event.target.textContent = paused ? "RESUME" : "PAUSE"; if (!paused) renderFeed(); };
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

  setInterval(() => $("#h-clock").textContent = new Date().toLocaleTimeString([], { hour12: false }), 1000);
  setInterval(() => {
    if (view === "int") loadIntel();
    if (view === "activityx") loadActivityIntelligence();
    if (view === "ctl") loadActions();
    if (view === "agent") loadAgent();
  }, 10000);
  $("#p-q").oninput = () => { clearTimeout(procQueryTimer); procQueryTimer = setTimeout(() => loadProcesses(true), 260); };
  $("#p-refresh").onclick = () => loadProcesses(true);
  $("#n-q").oninput = () => S && updNet();
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
  initAdvanced(); initAgent(); initEngines(); bindJ("#metrics");
  setInterval(loadStatus, 15000);
  setInterval(() => { if (view === "eng") loadEngines(); }, 8000);
  $("#e-go").onclick = loadEvi;
  $("#e-csv").onclick = csvExport;
  $("#e-q").onkeydown = event => event.key === "Enter" && loadEvi();
  $("#e-lv").onchange = $("#e-src").onchange = loadEvi;
  $("#sys-refresh").onclick = async () => {
    const button = $("#sys-refresh"); button.disabled = true; button.textContent = "SCANNING…";
    const result = await api("/api/inventory/refresh", {});
    button.disabled = false; button.textContent = "REFRESH INVENTORY";
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

  // Keep the local live feed attached while workspace requests are in flight.
  bootModuleState("stream", "LOADING", "Opening the local event stream");
  const stream = new EventSource("/api/stream?t=" + encodeURIComponent(TOKEN));
  stream.addEventListener("error", () => {
    $("#p-online").className = "pill bad";
    $("#p-online").textContent = "LINK RETRYING";
  });
  stream.onmessage = message => {
    try {
      const packet = JSON.parse(message.data);
      if (packet.t === "tick") {
        $("#p-online").className = "pill ok"; $("#p-online").textContent = "AGENT ONLINE";
        onTick(packet.d); bootModuleState("stream", "READY", "Live agent heartbeat received");
      } else if (packet.t === "log") addLog(packet.d);
      else if (packet.t === "insight") { INS.unshift(packet.d); renderIns(); alertInsight(packet.d); }
      else if (packet.t === "action") loadActions();
      else if (packet.t === "ai") addTr(packet.d);
      else if (packet.t === "ai_status") $("#ai-status").textContent = packet.d.text;
      else if (packet.t === "intel" && view === "int") loadIntel();
    } catch (error) { console.error("Invalid SENTINEL stream event", error); }
  };

  bp(26, "STARTING WORKSPACE THREADS", "Reading the process inventory, thermal sensors and intelligence stores");
  updHero(); updTiles(); updMetrics();
  $("#kernel-capture").disabled = false;
  const jobs = [
    ["command", "COMMAND DECK", async () => { updHero(); updTiles(); updMetrics(); }],
    ["agent", "AGENT RUNTIME", () => loadAgent(true)],
    ["sys", "SYSTEM INVENTORY", () => loadSys(true)],
    ["proc", "WINDOWS PROCESS RADAR", () => loadProcesses(true)],
    ["net", "NETWORK VIEW", async () => { updNet(); }],
    ["ker", "KERNEL ARCHIVE", async () => { updKer(); await loadKernelArchive(); }],
    ["adv", "THERMAL / ETW", () => loadAdvanced(true)],
    ["activityx", "USAGE INTELLIGENCE", () => loadActivityIntelligence(true)],
    ["intelx", "INTELLIGENCE MEMORY", () => loadIntelligence()],
    ["int", "INTELLIGENCE FEED", () => loadIntel()],
    ["ai", "AI COUNCIL", async () => { updAI(); }],
    ["evi", "EVIDENCE VAULT", () => loadEvi()],
    ["ctl", "ACTION CONTROL", async () => { buildCtl(); await loadActions(); ctlInitialized = true; }],
    ["fc", "FEATURE CONFIGURATION", () => loadFC()],
    ["tsk", "TASK CENTER", () => loadHist()],
    ["act", "ACTIVITY STREAM", async () => { updHeart(); renderFeed(); }]
  ];
  const criticalKeys = new Set(["command", "net"]);
  const criticalJobs = jobs.filter(([key]) => criticalKeys.has(key));
  const warmJobs = jobs.filter(([key]) => !criticalKeys.has(key));
  let completed = 0;
  const runJob = async ([key, label, work]) => {
    bootModuleState(key, "LOADING", "Synchronizing " + label.toLowerCase());
    try {
      await work();
      if (key === "proc" && !PROC_META.sampled_at) throw new Error("Windows process collector has not published a snapshot yet");
      markPageWarm(key);
      const detail = key === "proc"
        ? `${PROC_META.matched}/${PROC_META.total} active process records · ${PROC_META.inaccessible || 0} restricted`
        : "Live data and controls synchronized";
      if (key === "proc") $("#bootProcessCount").textContent = `${PROC_META.total.toLocaleString()} PROCESSES`;
      bootModuleState(key, "READY", detail);
      if (!bootDone) bp(26 + (++completed / criticalJobs.length) * 68, "INITIALIZING " + label, label + " is online", "ok");
      return { key, ok: true };
    } catch (error) {
      bootModuleState(key, "DEGRADED", (error?.message || String(error)).slice(0, 110));
      bp(26 + (++completed / jobs.length) * 68, "DEGRADED · " + label, (error?.message || String(error)).slice(0, 150), "warn");
      return { key, ok: false };
    }
  };
  const runBatch = async (queue) => {
    let next = 0;
    const worker = async () => { while (next < queue.length) await runJob(queue[next++]); };
    await Promise.all(Array.from({ length: Math.min(6, queue.length) }, worker));
  };
  void runBatch(criticalJobs);
  const degraded = 0;
  if (!PROC_META.total) $("#bootProcessCount").textContent = "PROCESS DATA LIMITED";
  if (degraded) bp(98, "ONLINE · DEGRADED MODULES", degraded + " workspace(s) need attention", "warn");
  else bp(99, "ALL WORKSPACES ONLINE", "Windows process and telemetry views are ready", "ok");
  let savedView = "cmd";
  try { savedView = localStorage.getItem("sv") || "cmd"; } catch (e) { }
  if (TITLES[savedView] && savedView !== "cmd") show(savedView);
  const minSplashMs = 120, remaining = minSplashMs - (performance.now() - bootStartedAt);
  if (remaining > 0) await new Promise(resolve => setTimeout(resolve, remaining));
  bp(100, "SENTINEL ONLINE", "Live collectors continue syncing in the background", "ok");
  endBoot();
  void runBatch([...criticalJobs.filter(([key]) => !["command", "net"].includes(key)), ...warmJobs]);
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
  const n = Number(temp), color = n >= threshold ? "#f05252" : n >= threshold - 10 ? "#f5a64a" : "#a7dc62";
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
  svg.innerHTML = renderLane(clocks, 0, "CLOCK", "MHz", "#b6e66a")
    + renderLane(power, 72, "POWER", "W", "#62c7e8");
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
  if (advBusy || (!force && Date.now() - advLastLoad < 5000)) return;
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
  } catch(e) {
    const errorPanel = $("#adv-load-error");
    const errorText = $("#adv-load-error-text");
    if (errorPanel) { errorPanel.hidden = false; errorPanel.classList.toggle("stale", !!ADV); }
    if (errorText) errorText.textContent = ADV
      ? "Agent link interrupted · showing the latest sensor snapshot"
      : "Agent link interrupted · retrying connection";
    clearTimeout(advRetryTimer);
    if (view === "adv") advRetryTimer = setTimeout(() => loadAdvanced(true), ADV ? 5000 : 1800);
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
  if (activityBusy || (view !== "activityx" && !force)) return;
  if (!force && Date.now() - activityLastLoad < 2500) return;
  activityBusy = true; activityLastLoad = Date.now();
  try {
    const data = await api("/api/activity");
    if (data.error) throw new Error(data.error);
    ACTIVITY = data; renderActivityIntelligence(data);
  } catch(error) { toast("Activity intelligence: " + (error.message || String(error)), "warn"); }
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
let ixBusy = false;
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
  if (ixBusy) return;
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
    const loadError = $("#ix-load-error");
    if (loadError) { loadError.hidden = true; loadError.classList.remove("stale"); }
  } catch (error) {
    const loadError = $("#ix-load-error");
    const errorText = $("#ix-load-error-text");
    const hasSnapshot = IX.state.length + IX.memories.length + IX.goals.length > 0;
    if (loadError) { loadError.hidden = false; loadError.classList.toggle("stale", hasSnapshot); }
    if (errorText) errorText.textContent = hasSnapshot
      ? "Agent link interrupted · showing the latest intelligence snapshot"
      : "Intelligence data is temporarily unavailable · retry the local agent link";
    toast("Intelligence refresh: " + (error?.message || String(error)), "warn");
  } finally {
    ixBusy = false;
  }
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
  const d = await api("/api/catalog?kind=" + CAT + "&limit=150&q=" + encodeURIComponent($("#cat-q").value)); if (d.error) return; const c = CATS[CAT];
  $("#cat-t").innerHTML = "<tr>" + c.map(k => `<th>${k.toUpperCase()}</th>`).join("") + "</tr>" + d.rows.map(r => "<tr>" + c.map(k => `<td>${esc(r[k])}</td>`).join("") + "</tr>").join("") || "";
  $("#cat-n").textContent = d.matched + " of " + d.total + " records";
}
let sysLastFetch = 0, sysFetchBusy = false;
async function loadSys(force = false) {
  if (sysFetchBusy || (!force && Date.now() - sysLastFetch < 15000)) return;
  sysFetchBusy = true; sysLastFetch = Date.now();
  try {

    const d = await api("/api/inventory");
    const c = d.counts || {}, p = d.platform || {}, sec = d.security || {}, health = d.health || {};
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
    $("#cat-q").oninput = loadCat; loadCat();
  } catch (e) {
    toast("System inventory: " + (e?.message || "source unavailable"), "warn");
    const box = $("#sys-health"); if (box) box.innerHTML = `<div class="empty">System inventory request failed: ${esc(e?.message || "unknown error")}. Source health remains unknown until a successful scan.</div>`;
  } finally { sysFetchBusy = false; }
}
function maybeRefreshSystem() { if (view === "sys" && Date.now() - sysLastFetch >= 15000) loadSys(false); }

let evRows = [];
async function loadEvi() {
  if (ST?.sources && $("#e-src").options.length === 1) $("#e-src").innerHTML += ST.sources.map(x => `<option>${esc(x)}</option>`).join("");
  evRows = await api("/api/events?limit=600&q=" + encodeURIComponent($("#e-q").value) + "&level=" + $("#e-lv").value + "&src=" + $("#e-src").value); evRows.reverse();
  $("#e-t").innerHTML = "<tr><th>TIME</th><th>LEVEL</th><th>SOURCE</th><th>MESSAGE</th></tr>" + evRows.map(r => `<tr><td>${hms(r.ts)}</td><td><span class="tag ${r.level === "error" ? "bad" : r.level === "ok" ? "ok" : "mu"}">${esc(r.level)}</span></td><td>${esc(r.src)}</td><td>${esc(r.msg)}</td></tr>`).join("");
  $("#e-n").textContent = evRows.length + " shown of " + Number(ST?.events || 0).toLocaleString() + " stored";
}
function csvExport() { const q = v => '"' + String(v).replace(/"/g, '""') + '"'; const t = "time,level,source,message\n" + evRows.map(r => [new Date(r.ts * 1000).toISOString(), r.level, r.src, r.msg].map(q).join(",")).join("\n"); const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([t], { type: "text/csv" })); a.download = "sentinel-evidence-" + Date.now() + ".csv"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); toast("Exported " + evRows.length + " records", "ok"); }
let HISTA = [];
async function loadHist() { HISTA = await api("/api/actions"); updTasks(); }
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
  const d = await api("/api/profile"); FC = d; FCsaved = d.profile; if (!keepForm) fcFill(d.profile);
  $("#fc-pre").innerHTML = Object.keys(PRESETS).map(k => `<button class="chip on" data-p="${k}">${k.toUpperCase()}</button>`).join("");
  $$("#fc-pre [data-p]").forEach(b => b.onclick = () => { const x = PRESETS[b.dataset.p], p = { automation: x.automation, sensors: Object.fromEntries(SENS.map(([k]) => [k, x.sensors[k] !== false])), intervals: x.intervals, thresholds: x.thresholds }; fcFill(p); toast(b.dataset.p + " loaded - review, then save", "warn"); });
  const audit = await api("/api/config/history"); const rows = audit.history || []; $("#fc-audit").innerHTML = rows.map(r => `<div class="ln info"><span class="t">${hms(r.ts)}</span><span class="s">rev ${r.revision}</span><span class="m">${esc((r.changed || []).join(", ") || "settings verified; no value changes")}</span></div>`).join("") || '<div class="empty">no configuration changes yet</div>';
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
  $("#engine-safe-facts").innerHTML = engineFacts([
    ["VALORANT", safe.valorant_active ? "DETECTED" : "NOT DETECTED"],
    ["PROCESS MONITOR", safe.process_detection_complete ? "HEALTHY" : "UNKNOWN / DISABLED"],
    ["ADMIN CONTEXT", safe.administrator ? "ELEVATED" : "NOT ELEVATED"],
    ["KERNEL TRACE", safe.kernel_trace_allowed ? "PERMITTED BY POLICY" : "BLOCKED"],
    ["VANGUARD VGC", safe.vanguard_services?.vgc || "UNKNOWN"],
    ["VANGUARD VGK", safe.vanguard_services?.vgk || "UNKNOWN"]
  ]);
  $("#engine-runtime-state").textContent = String(runtime.mode || "UNKNOWN").replaceAll("_", " ").toUpperCase();
  $("#engine-runtime-facts").innerHTML = engineFacts([
    ["HOST CPU", runtime.cpu_percent == null ? "--" : fmt(runtime.cpu_percent, 1) + "%"],
    ["AVAILABLE RAM", runtime.available_memory_gib == null ? "--" : fmt(runtime.available_memory_gib, 2) + " GiB"],
    ["PROCESS SCAN", runtime.process_scan_interval_s == null ? "--" : fmt(runtime.process_scan_interval_s, 1) + " s"],
    ["INVENTORY SCALE", runtime.inventory_interval_multiplier == null ? "--" : runtime.inventory_interval_multiplier + "×"],
    ["FAST AI", runtime.fast_ai_allowed ? "ADMITTED" : "DEFERRED"],
    ["DEEP AI", runtime.deep_ai_allowed ? "ADMITTED" : "DEFERRED"]
  ]);
  $("#engine-ai-state").textContent = ai.fast_triage_allowed ? "ORCHESTRATOR READY" : "RESOURCE / GAME GATED";
  $("#engine-ai-facts").innerHTML = engineFacts([
    ["FAST TRIAGE", ai.fast_triage_allowed ? "ADMITTED" : "DEFERRED"],
    ["DEEP MODEL", ai.deep_allowed ? "ADMITTED" : "DEFERRED"],
    ["FAST REASON", ai.fast_triage_reason || "--"],
    ["DEEP REASON", ai.deep_reason || "--"],
    ["TRANSPORT", ai.model_transport || "AI CORE"],
    ["EXECUTION AUTHORITY", "DETERMINISTIC POLICY"]
  ]);
  $("#engine-memory-state").textContent = String(mem.level || "UNKNOWN").toUpperCase() + " MEMORY PRESSURE";
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
  $("#engine-wpr").disabled = !safe.kernel_trace_allowed || !wprAvailable || wprState === "recording";
  $("#engine-wpr").title = valorant ? "Tracing is hard-disabled while VALORANT is running."
    : "Propose a bounded WPR trace; an existing recording is never stopped or replaced.";
}

async function loadEngines() {
  try {
    const data = await api("/api/engines");
    if (data.error) throw new Error(data.error);
    renderEngines(data);
  } catch (error) {
    $("#engine-health").textContent = "ENGINE API UNAVAILABLE";
    $("#engine-health").className = "pill bad";
    toast("Engine status: " + (error.message || "unavailable"), "warn");
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
  $("#palBtn").onclick = palOpen; $("#pal").onclick = e => { if (e.target.id === "pal") palClose(); }; $("#pal-q").oninput = () => { palSel = 0; palRender(); };
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
    const stage = $("#bootStage");
    if (stage) stage.textContent = "STARTUP DEGRADED";
    endBoot();
  } catch (endError) {
    console.error("SENTINEL could not close its startup overlay", endError);
    const overlay = document.getElementById("boot");
    if (overlay) overlay.classList.add("done");
  }
  toast("Startup incomplete: " + message.slice(0, 180), "bad");
});
