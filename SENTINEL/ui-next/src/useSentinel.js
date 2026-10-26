import { useEffect, useRef, useState, useCallback } from "react";
import { api, openStream, hasToken, wantsDemo, demoTick, demoHistory, DEMO_INSIGHTS } from "./api.js";

const MAXH = 300;
const push = (H, key, v) => {
  if (!Number.isFinite(Number(v))) return;
  const a = H[key] || (H[key] = []);
  a.push(Number(v));
  if (a.length > MAXH) a.shift();
};

/**
 * Boot is deliberately thin: ONE request (/api/snapshot) gates the UI.
 * History, insights and the live stream hydrate after first paint, and every
 * other screen loads on demand — nothing else blocks startup.
 */
export function useSentinel() {
  const [phase, setPhase] = useState("connecting"); // connecting | ready | offline
  const [mode, setMode] = useState(wantsDemo() || !hasToken() ? "demo" : "live");
  const [snap, setSnap] = useState(null);
  const [rev, setRev] = useState(0);
  const [insights, setInsights] = useState([]);
  const [linked, setLinked] = useState(false);
  const [reply, setReply] = useState("");
  const H = useRef({});
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => { setPhase("connecting"); setAttempt(n => n + 1); }, []);
  const goDemo = useCallback(() => { setMode("demo"); setPhase("connecting"); setAttempt(n => n + 1); }, []);

  useEffect(() => {
    let dead = false, stop = () => {}, timer = 0;
    const absorb = s => {
      if (dead || !s) return;
      for (const [k, v] of Object.entries(s.live || {})) push(H.current, k, v);
      setSnap(s); setRev(r => r + 1);
    };

    if (mode === "demo") {
      H.current = demoHistory();
      setInsights(DEMO_INSIGHTS);
      absorb(demoTick());
      setLinked(true); setPhase("ready");
      timer = setInterval(() => absorb(demoTick()), 1000);
      return () => { dead = true; clearInterval(timer); };
    }

    (async () => {
      let first;
      try { first = await api("/api/snapshot", null, 5000); }
      catch { try { await new Promise(r => setTimeout(r, 250)); first = await api("/api/snapshot", null, 5000); } catch { if (!dead) setPhase("offline"); return; } }
      if (dead) return;
      absorb(first); setPhase("ready");
      // Background hydration — never blocks the UI.
      api("/api/history?secs=300").then(h => {
        if (dead || !h) return;
        for (const [k, pts] of Object.entries(h)) if (Array.isArray(pts)) H.current[k] = pts.map(p => Number(p[1])).filter(Number.isFinite).slice(-MAXH);
        setRev(r => r + 1);
      }).catch(() => {});
      api("/api/insights").then(i => { if (!dead && Array.isArray(i)) setInsights(i); }).catch(() => {});
      stop = openStream(absorb, p => {
        if (p.t === "insight") setInsights(list => [p.d, ...list].slice(0, 20));
        else if (p.t === "ai" && p.d) setReply(String(p.d.text || p.d.msg || p.d.content || ""));
      }, setLinked);
    })();
    return () => { dead = true; stop(); };
  }, [mode, attempt]);

  return { phase, mode, snap, hist: H.current, rev, insights, linked, reply, retry, goDemo };
}
