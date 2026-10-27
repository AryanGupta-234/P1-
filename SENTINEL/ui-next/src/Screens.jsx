import React, { useEffect, useState } from "react";

export const GROUPS = [
  ["Operate", [["cmd", "Command deck"], ["eng", "Engine deck"], ["agent", "Agent runtime"], ["act", "Activity stream"], ["activityx", "Usage intelligence"]]],
  ["Diagnose", [["proc", "Processes"], ["net", "Network"], ["ker", "Kernel archive"], ["adv", "Thermal & tuning"], ["evi", "Evidence vault"]]],
  ["Intelligence", [["intelx", "Intelligence memory"], ["int", "Intel feed"], ["ai", "AI council"]]],
  ["Manage", [["maint", "Maintenance"], ["ctl", "Action control"], ["fc", "Features"], ["tsk", "Task center"], ["sys", "System inventory"]]]
];
export const NAMES = Object.fromEntries(GROUPS.flatMap(([, items]) => items));

/** Hosts every full-featured screen inside the shell. The frame is same-origin,
 *  chrome-less (embed mode) and re-skinned by nocturne.css, so nothing drops you
 *  back into the classic layout. */
export default function Screens({ view, setView }) {
  const [state, setState] = useState("loading"); // loading | ready | slow
  useEffect(() => {
    setState("loading");
    const t = setTimeout(() => setState(s => (s === "loading" ? "slow" : s)), 12000);
    return () => clearTimeout(t);
  }, [view]);
  const src = `../?classic=1&embed=1&v=${encodeURIComponent(view)}`;
  return (
    <div className="screens">
      <aside className="slist" aria-label="Screens">
        {GROUPS.map(([group, items]) => (
          <div key={group}>
            <span className="eyebrow">{group}</span>
            {items.map(([k, n]) => <button key={k} className={k === view ? "on" : ""} aria-current={k === view ? "page" : undefined} onClick={() => setView(k)}>{n}</button>)}
          </div>
        ))}
      </aside>
      <section className="sframe">
        <header><b>{NAMES[view]}</b><a className="btn ghost sm" href={src.replace("&embed=1", "")} target="_blank" rel="noreferrer">Pop out ↗</a></header>
        <div className="sbody">
          <iframe key={view} title={NAMES[view]} src={src} onLoad={() => setState("ready")} />
          {state !== "ready" && (
            <div className="sload" role="status">
              <i />
              <p>{state === "slow" ? "This screen is taking longer than usual." : "Opening " + NAMES[view] + "…"}</p>
              {state === "slow" && <a className="btn solid sm" href={src.replace("&embed=1", "")} target="_blank" rel="noreferrer">Open in a new window</a>}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
