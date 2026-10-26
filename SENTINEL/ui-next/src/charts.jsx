import React from "react";

// Catmull-Rom → cubic Bézier for a smooth, non-overshooting wave.
export function smooth(pts) {
  if (pts.length < 2) return "";
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const t = 0.18;
    d += `C${p1[0] + (p2[0] - p0[0]) * t},${p1[1] + (p2[1] - p0[1]) * t} ${p2[0] - (p3[0] - p1[0]) * t},${p2[1] - (p3[1] - p1[1]) * t} ${p2[0]},${p2[1]}`;
  }
  return d;
}

const down = (arr, n) => {
  if (arr.length <= n) return arr;
  const out = [], step = arr.length / n;
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * step), b = Math.max(a + 1, Math.floor((i + 1) * step));
    let s = 0; for (let j = a; j < b; j++) s += arr[j];
    out.push(s / (b - a));
  }
  return out;
};

/** Efficiency wave: area + line, with an optional highlighted time slice. */
export function Wave({ values, from = 0, to = 1, height = 220 }) {
  const W = 600, H = height, pad = 14;
  const v = down(values.length ? values : [50, 50], 60);
  let lo = Math.max(0, Math.min(...v) - 8), hi = Math.min(100, Math.max(...v) + 4);
  if (hi - lo < 24) { lo = Math.max(0, hi - 24); hi = lo + 24; }
  const pts = v.map((y, i) => [pad + (i / (v.length - 1)) * (W - pad * 2), pad + (1 - (Math.min(hi, Math.max(lo, y)) - lo) / (hi - lo)) * (H - pad * 2)]);
  const line = smooth(pts);
  const area = `${line}L${pts[pts.length - 1][0]},${H}L${pts[0][0]},${H}Z`;
  const x1 = pad + from * (W - pad * 2), x2 = pad + to * (W - pad * 2);
  const last = pts[pts.length - 1];
  return (
    <svg className="wave" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Efficiency over the last five minutes">
      <defs>
        <linearGradient id="wf" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#a31c1b" stopOpacity=".75" /><stop offset="1" stopColor="#a31c1b" stopOpacity="0" /></linearGradient>
        <linearGradient id="wl" x1="0" x2="1"><stop offset="0" stopColor="#8c9a88" /><stop offset=".6" stopColor="#e8ebe3" /><stop offset="1" stopColor="#ff6a5f" /></linearGradient>
        <clipPath id="slice"><rect x={x1} y="0" width={Math.max(2, x2 - x1)} height={H} /></clipPath>
      </defs>
      {[0.25, 0.5, 0.75].map(g => <line key={g} x1="0" x2={W} y1={H * g} y2={H * g} className="wgrid" />)}
      <path d={area} fill="url(#wf)" opacity=".5" />
      <g clipPath="url(#slice)"><path d={area} fill="url(#wf)" /></g>
      <rect x={x1} y="0" width={Math.max(2, x2 - x1)} height={H} className="wslice" />
      <path d={line} fill="none" stroke="url(#wl)" strokeWidth="2.5" vectorEffect="non-scaling-stroke" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="5" className="wdot" />
    </svg>
  );
}

export function Segments({ value, count = 28 }) {
  const on = Math.round((Math.min(100, Math.max(0, value)) / 100) * count);
  return <div className="segs" aria-hidden="true">{Array.from({ length: count }, (_, i) => <i key={i} className={i < on ? "on" : ""} style={{ "--i": i }} />)}</div>;
}
