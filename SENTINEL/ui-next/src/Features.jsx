import React, { useState } from "react";

/* Seeded RNG so every card paints the same picture each visit. */
const rng = s => () => (s = (s * 16807) % 2147483647) / 2147483647;
const SAGE = "#8c9a88", BONE = "#e8ebe3", RED = "#a31c1b";

/** 820×440 artwork. The frame crops it from the centre, so widening the
 *  frame reveals more of the picture instead of stretching it. */
function Art({ kind, seed }) {
  const r = rng(seed), els = [];
  const L = (k, p) => els.push(React.createElement(p[0], { key: k, ...p[1] }));
  if (kind === "perf") {
    for (let i = 0; i < 9; i++) L("a" + i, ["circle", { cx: 410, cy: 250, r: 48 + i * 22, fill: "none", stroke: i === 5 ? RED : SAGE, strokeOpacity: i === 5 ? 0.95 : 0.35, strokeWidth: i === 5 ? 6 : 1.4, strokeDasharray: i % 2 ? "3 9" : "none" }]);
    for (let i = 0; i < 48; i++) { const a = (i / 48) * Math.PI * 2; L("t" + i, ["line", { x1: 410 + Math.cos(a) * 232, y1: 250 + Math.sin(a) * 232, x2: 410 + Math.cos(a) * (i % 4 ? 242 : 256), y2: 250 + Math.sin(a) * (i % 4 ? 242 : 256), stroke: BONE, strokeOpacity: 0.4 }]); }
    L("n", ["path", { d: "M410 250 L520 140", stroke: BONE, strokeWidth: 3, strokeLinecap: "round" }]); L("h", ["circle", { cx: 410, cy: 250, r: 11, fill: RED }]);
  } else if (kind === "thermal") {
    for (let i = 0; i < 16; i++) { const y = 40 + i * 24, amp = 6 + r() * 16; let d = `M0 ${y}`; for (let x = 0; x <= 820; x += 41) d += `L${x} ${y + Math.sin(x / 60 + i) * amp}`; L("w" + i, ["path", { d, fill: "none", stroke: i >= 6 && i <= 9 ? RED : SAGE, strokeOpacity: i >= 6 && i <= 9 ? 0.4 + (i - 6) * 0.15 : 0.3, strokeWidth: i >= 6 && i <= 9 ? 5 : 1.5 }]); }
  } else if (kind === "net") {
    const pts = Array.from({ length: 22 }, () => [60 + r() * 700, 40 + r() * 360]);
    pts.forEach((p, i) => { L("l" + i, ["line", { x1: 410, y1: 220, x2: p[0], y2: p[1], stroke: SAGE, strokeOpacity: 0.28 }]); L("p" + i, ["circle", { cx: p[0], cy: p[1], r: 3 + r() * 6, fill: i % 7 === 0 ? RED : BONE, fillOpacity: i % 7 === 0 ? 0.95 : 0.55 }]); });
    L("c", ["circle", { cx: 410, cy: 220, r: 20, fill: RED }]); L("c2", ["circle", { cx: 410, cy: 220, r: 44, fill: "none", stroke: RED, strokeOpacity: 0.5 }]);
  } else if (kind === "proc") {
    for (let y = 0; y < 9; y++) for (let x = 0; x < 20; x++) { const v = r(); L(`s${x}_${y}`, ["rect", { x: 14 + x * 40, y: 22 + y * 45, width: 30, height: 34, rx: 4, fill: v > 0.9 ? RED : SAGE, fillOpacity: v > 0.9 ? 0.95 : 0.08 + v * 0.35 }]); }
  } else if (kind === "maint") {
    for (let i = 0; i < 5; i++) L("g" + i, ["circle", { cx: 410, cy: 220, r: 40 + i * 38, fill: "none", stroke: i === 2 ? RED : SAGE, strokeWidth: i === 2 ? 14 : 8, strokeOpacity: i === 2 ? 0.9 : 0.25, strokeDasharray: `${6 + i * 3} ${10 + i * 4}` }]);
    L("v", ["line", { x1: 410, y1: 0, x2: 410, y2: 440, stroke: BONE, strokeOpacity: 0.25 }]); L("h", ["line", { x1: 0, y1: 220, x2: 820, y2: 220, stroke: BONE, strokeOpacity: 0.25 }]);
  } else {
    for (let i = 0; i < 4; i++) L("o" + i, ["ellipse", { cx: 410, cy: 220, rx: 90 + i * 70, ry: 40 + i * 30, fill: "none", stroke: SAGE, strokeOpacity: 0.35, transform: `rotate(${-24 + i * 16} 410 220)` }]);
    let d = "M0 220"; for (let x = 0; x <= 820; x += 8) d += `L${x} ${220 + Math.sin(x / 22) * Math.sin(x / 130) * 70}`;
    L("wv", ["path", { d, fill: "none", stroke: BONE, strokeWidth: 2, strokeOpacity: 0.85 }]); L("c", ["circle", { cx: 410, cy: 220, r: 26, fill: RED }]);
  }
  return (
    <svg viewBox="0 0 820 440" width="820" height="440" aria-hidden="true">
      <defs><linearGradient id={"bg" + seed} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#0c2219" /><stop offset="1" stopColor="#171717" /></linearGradient></defs>
      <rect width="820" height="440" fill={`url(#bg${seed})`} />{els}
    </svg>
  );
}

const ITEMS = [
  { id: "perf", n: "01", t: "Performance Guard", d: "Watches lag index, DPC time and frame-time pressure, then tells you what is stealing your frames.", v: "cmd" },
  { id: "thermal", n: "02", t: "Thermal Watch", d: "CPU and GPU temperatures, fan speed and throttle flags in one calm view.", v: "adv" },
  { id: "net", n: "03", t: "Network Fabric", d: "Latency, jitter and live connections — spot the process that spikes your ping.", v: "net" },
  { id: "proc", n: "04", t: "Process Intelligence", d: "New-spawn monitoring and resource review. Advisory only; nothing is killed silently.", v: "proc" },
  { id: "maint", n: "05", t: "Maintenance", d: "Preview every change first. Reversible actions, restore points, a full journal.", v: "maint" },
  { id: "ai", n: "06", t: "AI Core", d: "A local council of models that explains problems in plain language.", v: "ai" }
];

export default function Features({ onOpen }) {
  const [open, setOpen] = useState(2);
  const key = e => {
    if (e.key === "ArrowRight") setOpen(o => Math.min(ITEMS.length - 1, o + 1));
    if (e.key === "ArrowLeft") setOpen(o => Math.max(0, o - 1));
  };
  return (
    <div className="feat">
      <div className="feat-head">
        <span className="eyebrow">Capabilities</span>
        <h2>Everything Sentinel keeps an eye on.</h2>
        <p>Hover, focus or tap a frame to open it. Arrow keys move along the rail.</p>
      </div>
      <div className="shingle" role="tablist" aria-label="Sentinel capabilities" onKeyDown={key}>
        {ITEMS.map((it, i) => (
          <article key={it.id} role="tab" tabIndex={0} aria-selected={i === open}
            className={"frame" + (i === open ? " open" : "")}
            style={{ "--tilt": (i % 2 ? 1 : -1) * (1.6 + (i % 3) * 0.7) + "deg", "--z": i === open ? 20 : 10 - Math.abs(i - open) }}
            onMouseEnter={() => setOpen(i)} onFocus={() => setOpen(i)} onClick={() => setOpen(i)}>
            <div className="mat">
              <div className="crop"><div className="art"><Art kind={it.id} seed={11 + i * 7} /></div></div>
              <span className="num">{it.n}</span>
              <div className="cap">
                <h3>{it.t}</h3>
                <p>{it.d}</p>
                <button className="btn solid sm" tabIndex={i === open ? 0 : -1} onClick={e => { e.stopPropagation(); onOpen(it.v); }}>Open screen →</button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
