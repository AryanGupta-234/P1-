// Local agent client. Same auth contract as the classic dashboard:
// token arrives as ?t=… once and is remembered in localStorage ("st").
const qs = new URLSearchParams(location.search);
let TOKEN = qs.get("t") || "";
try {
  if (TOKEN) localStorage.setItem("st", TOKEN);
  else TOKEN = localStorage.getItem("st") || "";
} catch { /* storage may be blocked */ }

export const hasToken = () => !!TOKEN;
export const wantsDemo = () => qs.get("demo") === "1";

export async function api(path, body, timeout = 6000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try {
    const res = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: { "X-Sentinel-Token": TOKEN, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
      signal: ctl.signal
    });
    const data = await res.json();
    if (!res.ok || data?.error) throw new Error(data?.error || "HTTP " + res.status);
    return data;
  } finally {
    clearTimeout(timer);
  }
}

export function openStream(onTick, onEvent, onState) {
  const es = new EventSource("/api/stream?t=" + encodeURIComponent(TOKEN));
  es.addEventListener("open", () => onState(true));
  es.addEventListener("error", () => onState(false));
  es.onmessage = m => {
    try {
      const p = JSON.parse(m.data);
      if (p.t === "tick") onTick(p.d);
      else onEvent(p);
    } catch { /* ignore malformed packets */ }
  };
  return () => es.close();
}

export function openClassic(view) {
  try { if (view) localStorage.setItem("sv", view); } catch { /* ignore */ }
  location.href = "../?classic=1";
}

/* ---------------- demo data (no agent needed) ---------------- */
const HEART = ["sensors_cpu","sensors_gpu","sensors_mem","net_ping","net_conn","proc_scan","proc_spawn","kernel_pdh","kernel_dpc","ai_triage","ai_deep","inventory_win","thermal_lhm","safeguard_vgk"];
let t0 = Date.now(), seed = 7;
const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
let walk = { cpu: 28, mem: 54, gpu: 22, dpc: 0.8, lag_index: 14, ping: 18, netdown: 3.2, netup: 0.6 };
export function demoTick() {
  const w = walk, jig = (v, s, lo, hi) => Math.min(hi, Math.max(lo, v + (rnd() - 0.5) * s));
  w.cpu = jig(w.cpu, 12, 4, 96); w.mem = jig(w.mem, 1.2, 38, 82); w.gpu = jig(w.gpu, 10, 2, 92);
  w.dpc = jig(w.dpc, 0.6, 0.1, 6); w.ping = jig(w.ping, 6, 9, 60); w.netdown = jig(w.netdown, 2, 0, 40); w.netup = jig(w.netup, 0.5, 0, 6);
  w.lag_index = Math.max(2, Math.min(90, w.cpu * 0.22 + w.dpc * 4 + (w.ping - 15) * 0.2 + rnd() * 3));
  const now = Date.now() / 1000;
  const heart = {};
  HEART.forEach((n, i) => {
    const bad = (i === 4 && Math.floor(now / 20) % 3 === 0) ? "timeout" : "";
    heart[n] = { last: now - rnd() * 1.6, every: 2 + (i % 3), runs: Math.floor((Date.now() - t0) / 1000 / (2 + (i % 3))), err: bad, note: "ok" };
  });
  return {
    now, uptime: (Date.now() - t0) / 1000 + 5400, live: { ...w },
    cores: Array.from({ length: 12 }, () => Math.round(rnd() * 100)),
    game: null, proc_total: 212, heart,
    ai: { online: true, busy: rnd() > 0.85 ? "fast" : "" },
    system: { power_plan: "High performance" }, services: { vanguard: { vgk: "running" } }
  };
}
export function demoHistory(n = 300) {
  const out = {}; const keys = Object.keys(walk);
  keys.forEach(k => out[k] = []);
  const saved = { ...walk };
  for (let i = n; i > 0; i--) {
    const s = demoTick();
    keys.forEach(k => out[k].push(s.live[k]));
  }
  walk = saved; return out;
}
export const DEMO_INSIGHTS = [{ msg: "All collectors healthy. No stutter sources detected in the last five minutes." }];
