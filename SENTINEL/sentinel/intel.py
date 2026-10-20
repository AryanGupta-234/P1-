"""Knowledge feed: Microsoft Learn + GitHub issues, cached 24 h, queried when the brain sees a problem
and on a slow watch-list schedule."""
import json, time, urllib.parse, urllib.request
from . import core
from .core import db, log, publish, heartbeat

UA = {"User-Agent": "Sentinel-Agent/1.0 (local diagnostics)", "Accept": "application/json"}
TTL = 24 * 3600
WATCH = [
    "Valorant stuttering Windows 11 fix",
    "Windows 11 gaming performance regression update",
    "DPC latency high driver Windows gaming",
    "Vanguard VAN error Windows memory integrity",
]


def _get(url, timeout=9):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def lookup(q, force=False):
    q = q.strip()[:140]
    row = db("SELECT ts,json FROM intel WHERE q=?", (q,))
    if row and not force and time.time() - row[0][0] < TTL:
        return json.loads(row[0][1])
    out = []
    try:
        d = _get("https://learn.microsoft.com/api/search?" + urllib.parse.urlencode(
            {"search": q, "locale": "en-us", "$top": 4}))
        for r in (d.get("results") or [])[:4]:
            out.append({"src": "Microsoft Learn", "title": r.get("title", ""), "url": r.get("url", ""),
                        "snippet": (r.get("description") or "")[:220]})
    except Exception as e:
        log("intel", f"Microsoft Learn lookup failed: {str(e)[:60]}", "debug")
    try:
        d = _get("https://api.github.com/search/issues?" + urllib.parse.urlencode(
            {"q": q + " is:issue", "sort": "updated", "per_page": 4}))
        for r in (d.get("items") or [])[:4]:
            out.append({"src": "GitHub", "title": r.get("title", ""), "url": r.get("html_url", ""),
                        "snippet": f"{r.get('state','')} | {(r.get('repository_url') or '').split('repos/')[-1]} | updated {str(r.get('updated_at',''))[:10]}"})
    except Exception as e:
        log("intel", f"GitHub lookup failed: {str(e)[:60]}", "debug")
    if out:
        db("INSERT OR REPLACE INTO intel(q,ts,json) VALUES(?,?,?)", (q, time.time(), json.dumps(out)))
        log("intel", f"'{q[:50]}' -> {len(out)} references (Microsoft Learn + GitHub)", "info")
        publish("intel", {"q": q, "items": out})
    return out


def recent(limit=12):
    rows = db("SELECT q,ts,json FROM intel ORDER BY ts DESC LIMIT ?", (limit,))
    return [{"q": r[0], "ts": r[1], "items": json.loads(r[2])} for r in rows]


def watch_loop():
    time.sleep(20)
    while True:
        for q in WATCH:
            try:
                lookup(q)
            except Exception:
                pass
            time.sleep(8)
        heartbeat("intel crawler (MS Learn + GitHub)", 21600, f"{len(WATCH)} watch topics")
        time.sleep(6 * 3600)