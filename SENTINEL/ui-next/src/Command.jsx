import React, { useEffect, useMemo, useRef, useState } from "react";
import { Wave, Segments } from "./charts.jsx";
import { api } from "./api.js";

const fmt = (v, d = 0) => (v == null || Number.isNaN(+v) ? "--" : (+v).toFixed(d));
const dur = s => { s = Math.floor(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h}h ${m}m` : `${m}m ${s % 60}s`; };
const label = lag => lag < 12 ? "Optimal" : lag < 25 ? "Nominal" : lag < 45 ? "Elevated" : lag < 70 ? "Degraded" : "Critical";
const ago = (now, t) => { const s = Math.max(0, Math.round(now - t)); return s < 5 ? "Now" : "−" + Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };

export default function Command({ snap, hist, insights, mode, reply }) {
  const live = snap.live || {};
  const lag = Number(live.lag_index ?? 0);
  const eff = Math.max(0, Math.min(100, 100 - lag));
  const effSeries = useMemo(() => (hist.lag_index || []).map(v => 100 - v), [snap]); // eslint-disable-line
  const [sel, setSel] = useState(-1); // -1 = live / last slice

  /* 12 five-minute-window slices for the carousel */
  const slices = useMemo(() => {
    const a = effSeries, n = 12, out = [];
    if (!a.length) return out;
    const size = a.length / n, now = snap.now || Date.now() / 1000, span = a.length;
    for (let i = 0; i < n; i++) {
      const lo = Math.floor(i * size), hi = Math.max(lo + 1, Math.floor((i + 1) * size));
      let s = 0; for (let j = lo; j < hi; j++) s += a[j];
      out.push({ v: s / (hi - lo), t: now - (span - hi), lo: i / n, hi: (i + 1) / n });
    }
    return out;
  }, [effSeries, snap.now]);
  const active = sel < 0 ? slices.length - 1 : sel;
  const cur = slices[active];
  const rail = useRef(null);
  const nudge = d => rail.current?.scrollBy({ left: d * 220, behavior: "smooth" });
  const seeded = useRef(false);
  useEffect(() => { if (slices.length && !seeded.current && rail.current) { seeded.current = true; rail.current.scrollLeft = rail.current.scrollWidth; } }, [slices.length]);

  return (
    <div className="cmd">
      {/* ── Node health (progress card) ── */}
      <section className="card health" aria-label="Node health">
        <header><span className="eyebrow">Node health</span><span className={"chip" + (snap.game ? " hot" : "")}>{snap.game ? "Game mode" : "Standby"}</span></header>
        <div className="health-main">
          <div className="big">{fmt(eff)}<small>%</small></div>
          <div className="health-state"><b>{label(lag)}</b><span>Lag index {fmt(lag)} · up {dur(snap.uptime)}</span></div>
        </div>
        <Segments value={eff} />
        <div className="stats">
          {[["CPU", live.cpu, "%"], ["Memory", live.mem, "%"], ["GPU", live.gpu, "%"], ["DPC", live.dpc, "%"]].map(([k, v, u]) => (
            <div key={k}><small>{k}</small><b>{fmt(v, k === "DPC" ? 1 : 0)}<i>{u}</i></b><em><u style={{ width: Math.min(100, (v ?? 0) * (k === "DPC" ? 12 : 1)) + "%" }} /></em></div>
          ))}
        </div>
      </section>

      {/* ── Horizontal time carousel ── */}
      <section className="card rail-card" aria-label="Recent time slices">
        <header><span className="eyebrow">Last five minutes</span>
          <div className="arrows"><button aria-label="Scroll earlier" onClick={() => nudge(-1)}>‹</button><button aria-label="Scroll later" onClick={() => nudge(1)}>›</button></div>
        </header>
        <div className="rail" ref={rail}>
          {slices.map((s, i) => (
            <button key={i} className={"slice" + (i === active ? " on" : "")} onClick={() => setSel(i === slices.length - 1 ? -1 : i)} aria-pressed={i === active}>
              <small>{i === slices.length - 1 ? "Now" : ago(snap.now, s.t)}</small>
              <b>{fmt(s.v)}</b>
              <i style={{ height: Math.max(8, s.v * 0.5) + "%" }} />
            </button>
          ))}
        </div>
      </section>

      {/* ── Roadmap: stacked collector tracks ── */}
      <Tracks heart={snap.heart || {}} now={snap.now} />

      {/* ── Efficiency wave ── */}
      <section className="card wave-card" aria-label="Efficiency">
        <header><span className="eyebrow">Efficiency</span><span className="chip ghost">{mode === "demo" ? "Demo data" : "Live"}</span></header>
        <div className="wave-head"><b>{fmt(cur ? cur.v : eff)}<small>%</small></b><span>{sel < 0 ? "current window" : "window " + ago(snap.now, cur.t)}</span></div>
        <Wave values={effSeries} from={cur ? cur.lo : 0} to={cur ? cur.hi : 1} />
        <footer><span>−5 min</span><span>now</span></footer>
      </section>

      <Assistant snap={snap} insights={insights} mode={mode} reply={reply} />
    </div>
  );
}

function Tracks({ heart, now }) {
  const groups = useMemo(() => {
    const g = {};
    Object.entries(heart).forEach(([name, h]) => {
      const key = name.split(/[_\-. :]/)[0] || name;
      (g[key] ||= []).push({ name, h });
    });
    return Object.entries(g).sort((a, b) => b[1].length - a[1].length).slice(0, 5);
  }, [heart]);
  const state = ({ h }) => h.err ? "bad" : (h.every && now - h.last > h.every * 6 + 10) ? "late" : "ok";
  return (
    <section className="card tracks" aria-label="Collector tracks">
      <header><span className="eyebrow">Engine roadmap</span><span className="chip ghost">{Object.keys(heart).length} collectors</span></header>
      <div className="track-list">
        {groups.length === 0 && <p className="muted">Waiting for the first collector heartbeats…</p>}
        {groups.map(([key, items], r) => {
          const ok = items.filter(i => state(i) === "ok").length, pct = Math.round((ok / items.length) * 100);
          const start = (r * 13) % 34, width = 52 + Math.min(items.length, 4) * 6;
          return (
            <div className="track" key={key}>
              <span className="track-name">{key}</span>
              <div className="track-lane">
                <div className="bar" style={{ left: start + "%", width: width + "%" }}>
                  <u style={{ width: pct + "%" }} />
                  <span>{pct}%</span>
                  <div className="avatars">
                    {items.slice(0, 4).map(i => <em key={i.name} className={state(i)} title={`${i.name} — ${state(i) === "ok" ? "healthy" : state(i) === "late" ? "late" : "error"}`}>{i.name.split(/[_\-. :]/).slice(-1)[0].slice(0, 2).toUpperCase()}</em>)}
                    {items.length > 4 && <em className="more">+{items.length - 4}</em>}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Assistant({ snap, insights, mode, reply }) {
  const [msg, setMsg] = useState(""), [busy, setBusy] = useState(false), [local, setLocal] = useState("");
  const ai = snap.ai || {};
  const i0 = insights[0], hint = i0 && (i0.msg || i0.text || i0.title || i0.summary);
  const send = async e => {
    e.preventDefault();
    const text = msg.trim(); if (!text || busy) return;
    setMsg(""); setBusy(true); setLocal("");
    try {
      if (mode === "demo") { await new Promise(r => setTimeout(r, 700)); setLocal("Demo mode — connect the agent to ask live questions about your PC."); }
      else { await api("/api/chat", { msg: text, mode: "council" }); setLocal("Sent. The answer appears here when the council replies."); }
    } catch (err) { setLocal(String(err.message || err)); }
    setBusy(false);
  };
  return (
    <section className="card assist" aria-label="Assistant">
      <header><span className="eyebrow">Assistant</span><span className={"dot" + (ai.online ? " on" : "")}>{ai.online ? (ai.busy ? "Thinking" : "Online") : "Offline"}</span></header>
      <p className="say">{local || reply || hint || "Ask me about lag, thermals or what’s running."}</p>
      <form onSubmit={send}>
        <input value={msg} onChange={e => setMsg(e.target.value)} placeholder="Ask Sentinel…" aria-label="Ask Sentinel" />
        <button aria-label="Send" disabled={busy}>{busy ? "…" : "→"}</button>
      </form>
    </section>
  );
}
