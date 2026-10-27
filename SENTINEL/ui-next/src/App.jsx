import React, { useEffect, useState } from "react";
import Boot from "./Boot.jsx";
import Command from "./Command.jsx";
import Features from "./Features.jsx";
import Screens, { GROUPS } from "./Screens.jsx";
import { useSentinel } from "./useSentinel.js";
import { openClassic } from "./api.js";

const Icon = ({ d }) => <svg viewBox="0 0 24 24" aria-hidden="true"><path d={d} /></svg>;

export default function App() {
  const s = useSentinel();
  const [booted, setBooted] = useState(false);
  const hashScreen = location.hash.startsWith("#screens/") ? location.hash.slice(9) : "";
  const [page, setPage] = useState(() => (hashScreen ? "screens" : location.hash === "#features" ? "features" : "command"));
  const [view, setView] = useState(hashScreen || "net");
  const openScreen = v => { setView(v); setPage("screens"); setMenu(false); };
  const [menu, setMenu] = useState(false);
  const [now, setNow] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => { location.hash = page === "features" ? "features" : page === "screens" ? "screens/" + view : ""; }, [page, view]);
  useEffect(() => { const k = e => e.key === "Escape" && setMenu(false); addEventListener("keydown", k); return () => removeEventListener("keydown", k); }, []);

  const snap = s.snap, lag = Number(snap?.live?.lag_index ?? 0);
  return (
    <>
      {snap && (
        <div className={"app" + (booted ? " in" : "")}>
          <nav className="rail-nav" aria-label="Primary">
            <div className="logo" aria-hidden="true"><i /></div>
            <button className={page === "command" ? "on" : ""} onClick={() => setPage("command")} aria-label="Command" title="Command"><Icon d="M3 13h4l2-7 4 14 2-7h6" /></button>
            <button className={page === "features" ? "on" : ""} onClick={() => setPage("features")} aria-label="Capabilities" title="Capabilities"><Icon d="M4 5h4v14H4zM10 3h4v18h-4zM16 7h4v10h-4z" /></button>
            <span className="sp" />
            <button className={page === "screens" ? "on" : ""} onClick={() => setPage("screens")} aria-label="Screens" title="Screens"><Icon d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" /></button>
            <span className="sp" />
            <button onClick={() => setMenu(m => !m)} aria-label="Quick jump" aria-expanded={menu} title="All screens"><Icon d="M5 12h14M12 5l7 7-7 7" /></button>
          </nav>
          {menu && (
            <div className="menu" role="menu" onMouseLeave={() => setMenu(false)}>
              <b>Jump to</b>
              <div>{GROUPS.flatMap(([, items]) => items).map(([k, n]) => <button role="menuitem" key={k} onClick={() => openScreen(k)}>{n}</button>)}</div>
            </div>
          )}
          <header className="top">
            <div><span className="eyebrow">Sentinel / Windows node</span><h1>{page === "command" ? "Command" : page === "features" ? "Capabilities" : "Screens"}</h1></div>
            <span className="sp" />
            <span className={"pill " + (s.linked ? "ok" : "bad")}>{s.mode === "demo" ? "Demo" : s.linked ? "Live link" : "Reconnecting"}</span>
            <span className={"pill " + (lag < 25 ? "ok" : lag < 45 ? "warn" : "bad")}>Lag {Math.round(lag)}</span>
            <time>{now.toLocaleTimeString([], { hour12: false })}</time>
            <button className="btn ghost sm" onClick={() => openClassic()}>Classic UI ↗</button>
          </header>
          <main className={page === "screens" ? "flush" : ""}>{page === "command" ? <Command snap={snap} hist={s.hist} insights={s.insights} mode={s.mode} reply={s.reply} /> : page === "features" ? <Features onOpen={openScreen} /> : <Screens view={view} setView={setView} />}</main>
        </div>
      )}
      {!booted && <Boot phase={s.phase} onDone={() => setBooted(true)} onRetry={s.retry} onDemo={s.goDemo} />}
    </>
  );
}
