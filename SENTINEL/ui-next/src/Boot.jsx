import React, { useEffect, useRef, useState } from "react";

const FEATURES = [
  { k: "Sensors", at: 0.2, line: "Waking the sensors" },
  { k: "Live link", at: 0.45, line: "Opening the live link" },
  { k: "Safeguards", at: 0.7, line: "Arming safeguards" },
  { k: "Intelligence", at: 0.92, line: "Bringing intelligence online" }
];
const R = 92, C = 2 * Math.PI * R;
const MIN_MS = 820;

export default function Boot({ phase, onDone, onRetry, onDemo }) {
  const [p, setP] = useState(0);
  const [out, setOut] = useState(false);
  const t0 = useRef(performance.now());
  const done = useRef(false);

  useEffect(() => {
    if (phase === "offline") return;
    let raf;
    const step = () => {
      setP(prev => {
        const elapsed = performance.now() - t0.current;
        // Honest progress: crawl to 55% while waiting on the agent, then finish.
        const ceiling = phase === "ready" ? Math.min(1, elapsed / MIN_MS) : 0.55;
        const target = phase === "ready" ? Math.max(ceiling, 0.55) : ceiling;
        const next = prev + Math.max(0.0035, (target - prev) * 0.1);
        return Math.min(next, target >= 1 ? 1 : target);
      });
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [phase]);

  useEffect(() => {
    if (p >= 0.999 && phase === "ready" && !done.current) {
      done.current = true;
      setOut(true);
      setTimeout(onDone, 480);
    }
  }, [p, phase, onDone]);

  const active = [...FEATURES].reverse().find(f => p >= f.at - 0.2) || FEATURES[0];
  const offline = phase === "offline";

  return (
    <div className={"boot" + (out ? " out" : "") + (offline ? " offline" : "")} role="status" aria-live="polite" aria-label="SENTINEL is starting">
      <div className="boot-bg" aria-hidden="true" />
      <div className="boot-stage">
        <svg className="iris" viewBox="0 0 220 220" aria-hidden="true">
          <defs>
            <radialGradient id="core" cx=".5" cy=".5" r=".5"><stop offset="0" stopColor="#ff7a6e" /><stop offset=".45" stopColor="#a31c1b" /><stop offset="1" stopColor="#a31c1b" stopOpacity="0" /></radialGradient>
            <linearGradient id="sweep" x1="0" x2="1"><stop offset="0" stopColor="#8c9a88" stopOpacity="0" /><stop offset="1" stopColor="#e8ebe3" stopOpacity=".9" /></linearGradient>
          </defs>
          <g className="ring r1"><circle cx="110" cy="110" r="104" /><circle cx="110" cy="110" r="104" className="ticks" /></g>
          <g className="ring r2"><circle cx="110" cy="110" r="76" className="dash" /></g>
          <g className="ring r3"><circle cx="110" cy="110" r="56" /><circle cx="110" cy="54" r="3.4" className="sat" /></g>
          <circle cx="110" cy="110" r={R} className="track" />
          <circle cx="110" cy="110" r={R} className="prog" strokeDasharray={C} strokeDashoffset={C * (1 - p)} transform="rotate(-90 110 110)" />
          <g className="sweep"><path d="M110 110 L110 6 A104 104 0 0 1 188 40 Z" fill="url(#sweep)" opacity=".16" /></g>
          <circle cx="110" cy="110" r="30" fill="url(#core)" className="core" />
          <circle cx="110" cy="110" r="7" className="nucleus" />
        </svg>

        <h1 className="boot-word" aria-label="SENTINEL">{"SENTINEL".split("").map((c, i) => <span key={i} style={{ "--d": i * 45 + "ms" }}>{c}</span>)}</h1>
        <p className="boot-line" key={offline ? "off" : active.k}>{offline ? "Can’t reach the local agent" : p >= 0.999 ? "Ready" : active.line}</p>

        {!offline ? (
          <>
            <ul className="boot-feats">
              {FEATURES.map(f => <li key={f.k} className={p >= f.at ? "on" : p >= f.at - 0.2 ? "now" : ""}><i />{f.k}</li>)}
            </ul>
            <div className="boot-pct" aria-hidden="true">{String(Math.round(p * 100)).padStart(2, "0")}</div>
          </>
        ) : (
          <div className="boot-actions">
            <button className="btn solid" onClick={onRetry}>Retry</button>
            <button className="btn ghost" onClick={onDemo}>Explore demo</button>
          </div>
        )}
      </div>
    </div>
  );
}
