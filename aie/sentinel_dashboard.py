"""Loopback-only Sentinel dashboard with a built-in, dependency-free web interface."""
from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any

from aie.config import set_observer_paused
from aie.store import EventStore


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>SENTINEL // AIE</title>
<style>
:root{--bg:#070c15;--panel:#0d1725;--panel2:#101e2e;--line:#20334a;--ink:#e7f2ff;--muted:#8195aa;--cyan:#53e4f2;--blue:#4e9eff;--amber:#ffbd69;--green:#5de0b0;--red:#ff657f;--radius:18px}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(ellipse at 67% -12%,#16304a 0,transparent 43%),linear-gradient(145deg,#070c15,#091321 65%,#09101a);color:var(--ink);font:14px/1.5 "Segoe UI",Inter,system-ui,sans-serif;min-height:100vh}
body:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.16;background-image:linear-gradient(#3e7890 1px,transparent 1px),linear-gradient(90deg,#3e7890 1px,transparent 1px);background-size:48px 48px;mask-image:linear-gradient(to bottom,black,transparent 72%)}
a{color:inherit;text-decoration:none}button{font:inherit;cursor:pointer}button:focus-visible,a:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}
.shell{display:grid;grid-template-columns:236px minmax(0,1fr);min-height:100vh;position:relative}.side{border-right:1px solid #1b2d41;background:#08111dce;backdrop-filter:blur(20px);padding:26px 17px;display:flex;flex-direction:column;gap:28px;position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:12px;padding:0 8px}.brand-mark{width:38px;height:38px;border:1px solid #4bcddb;border-radius:12px;display:grid;place-items:center;color:var(--cyan);box-shadow:0 0 28px #42d7e622,inset 0 0 20px #42d7e612;position:relative}.brand-mark:before{content:"";width:13px;height:13px;border:2px solid var(--cyan);transform:rotate(45deg);box-shadow:0 0 12px #53e4f2}.brand-name{font-size:13px;font-weight:800;letter-spacing:.19em}.brand-sub{font-size:9px;letter-spacing:.19em;color:var(--muted);margin-top:3px}
.nav-label{font-size:9px;letter-spacing:.2em;color:#627b93;padding:0 12px 8px}.nav{display:grid;gap:5px}.nav a{display:flex;align-items:center;gap:12px;padding:11px 12px;border-radius:11px;color:#9cafc3;font-size:12px;border:1px solid transparent;transition:.2s}.nav a:hover,.nav a.active{color:var(--ink);background:#13263a;border-color:#28465f}.nav a.active{box-shadow:inset 2px 0 0 var(--cyan),0 5px 20px #00101c}.nav-symbol{width:17px;text-align:center;color:var(--cyan);font-size:14px}.side-bottom{margin-top:auto;border:1px solid #263b50;border-radius:14px;padding:14px;background:linear-gradient(145deg,#14283a,#0c1724)}.side-bottom small{display:block;color:var(--muted);font-size:9px;letter-spacing:.15em}.side-bottom strong{display:block;font-size:12px;margin:7px 0 4px}.side-bottom p{color:#91a5b9;font-size:10px;margin:0}
main{min-width:0;max-width:1600px;width:100%;margin:auto;padding:27px clamp(18px,3vw,44px) 42px}.topbar{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:26px}.eyebrow{color:var(--cyan);font-size:9px;letter-spacing:.22em;font-weight:700}.page-title{font-size:21px;font-weight:700;letter-spacing:.025em;margin:3px 0}.top-right{display:flex;align-items:center;gap:11px}.clock{font:11px "Cascadia Code",Consolas,monospace;color:#9db2c8;text-align:right}.live{display:inline-flex;align-items:center;gap:7px;color:var(--green);font-size:10px;letter-spacing:.13em;font-weight:700;border:1px solid #24594d;border-radius:30px;padding:7px 11px;background:#10251f}.dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 12px var(--green);animation:pulse 1.8s infinite}@keyframes pulse{50%{opacity:.35;box-shadow:0 0 2px var(--green)}}
.hero{border:1px solid #2a4b64;border-radius:22px;overflow:hidden;background:linear-gradient(115deg,#112438 0%,#0b1826 58%,#0b1925);display:grid;grid-template-columns:minmax(0,1fr) 260px;min-height:205px;position:relative;box-shadow:0 20px 55px #0005}.hero:after{content:"";position:absolute;right:200px;top:-120px;width:420px;height:420px;border:1px solid #4fdbe51a;border-radius:50%;box-shadow:0 0 0 32px #4fdbe50a,0 0 0 70px #4fdbe506;pointer-events:none}
.hero-copy{padding:28px 30px;position:relative;z-index:1}.hero-kicker{font-size:9px;letter-spacing:.23em;color:#8ca9c2}.hero h1{font-size:clamp(25px,3vw,38px);letter-spacing:.06em;margin:12px 0 4px;font-weight:800}.hero h1 span{color:var(--cyan);text-shadow:0 0 24px #53e4f244}.hero-desc{font-size:12px;color:#9db1c6;max-width:580px;margin:6px 0 19px}.hero-meta{display:flex;gap:22px;flex-wrap:wrap}.meta-item small{display:block;font-size:8px;color:#7790a8;letter-spacing:.14em}.meta-item b{font:11px "Cascadia Code",Consolas,monospace;color:#dceaff}.hero-core{display:grid;place-items:center;position:relative;z-index:1}.core{width:146px;height:146px;border-radius:50%;position:relative;display:grid;place-items:center;background:radial-gradient(circle,#173d4c 0,#102536 38%,#091521 65%);border:1px solid #4bcddb77;box-shadow:0 0 36px #53e4f225,inset 0 0 30px #53e4f21b}.core:before,.core:after{content:"";position:absolute;inset:-10px;border:1px solid #53e4f255;border-radius:50%;border-left-color:transparent;border-right-color:transparent;animation:spin 12s linear infinite}.core:after{inset:-20px;border-color:#4e9eff55 transparent;animation-direction:reverse;animation-duration:18s}@keyframes spin{to{transform:rotate(360deg)}}.core-eye{width:65px;height:65px;border:1px solid #69e5f1;border-radius:22px 22px 22px 5px;transform:rotate(45deg);display:grid;place-items:center;box-shadow:0 0 27px #53e4f233}.core-eye span{width:23px;height:23px;border-radius:50%;background:radial-gradient(circle,#eaffff 0,#55e3ee 35%,#168da6 75%);box-shadow:0 0 20px #53e4f2;transform:rotate(-45deg)}
.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{border:1px solid #34516a;background:#13273a;color:#dceafa;padding:8px 12px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.04em;transition:.2s}.btn:hover{border-color:var(--cyan);background:#18334a}.btn.primary{background:linear-gradient(135deg,#156e7b,#164e6e);border-color:#35c4d4;color:white}.btn.warn{color:#ffb9c1;border-color:#713c4c;background:#2c1722}.btn:disabled{opacity:.4;cursor:not-allowed}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:15px 0}.stat{border:1px solid var(--line);border-radius:15px;background:linear-gradient(145deg,#101d2b,#0c1622);padding:15px 17px;min-width:0}.stat-top{display:flex;align-items:center;justify-content:space-between}.stat-label{color:#8ba1b7;font-size:9px;letter-spacing:.14em}.stat-icon{color:var(--cyan);font-size:15px}.stat-value{font:25px "Cascadia Code",Consolas,monospace;margin:9px 0 2px;white-space:nowrap}.stat-foot{font-size:9px;color:#70879d}.stat-meter{height:3px;background:#24384a;border-radius:10px;margin-top:10px;overflow:hidden}.stat-meter i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--blue),var(--cyan));box-shadow:0 0 9px var(--cyan)}
.grid-main{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(300px,.9fr);gap:14px}.panel{border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(145deg,#101d2b,#0c1622);padding:17px;min-width:0}.panel-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:14px}.panel-title{font-size:12px;font-weight:700;letter-spacing:.07em}.panel-sub{font-size:9px;color:var(--muted);margin-top:3px}.tag{font:9px "Cascadia Code",Consolas,monospace;color:var(--cyan);border:1px solid #2b5362;background:#102632;border-radius:20px;padding:4px 8px;white-space:nowrap}
.chart-wrap{height:140px;position:relative}.chart-wrap canvas{width:100%;height:100%}.chart-legend{display:flex;gap:15px;font-size:9px;color:#8ca1b6;margin-top:9px}.legend-dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:5px;background:var(--cyan)}.legend-dot.amber{background:var(--amber)}
.feed{display:grid;gap:7px;max-height:450px;overflow:auto;padding-right:4px}.event{display:grid;grid-template-columns:34px minmax(0,1fr) auto;gap:10px;align-items:start;padding:10px;border:1px solid #203347;border-radius:12px;background:#0a1420}.event:hover{border-color:#3e657e;background:#0e1d2c}.event-inspect{margin-top:7px;color:#6f91a8;font-size:8px}.event-inspect summary{cursor:pointer;letter-spacing:.12em;user-select:none}.event-json{white-space:pre-wrap;overflow-wrap:anywhere;max-height:230px;overflow:auto;margin:7px 0 0;padding:9px;border:1px solid #20374b;border-radius:8px;background:#07111b;color:#b5cadd;font:9px/1.5 "Cascadia Code",Consolas,monospace}.event-icon{width:32px;height:32px;border-radius:10px;background:#142b3b;color:var(--cyan);display:grid;place-items:center;font-size:13px}.event-name{font-size:10px;font-weight:700;overflow-wrap:anywhere}.event-desc{font-size:9px;color:#8da2b6;margin-top:3px;overflow-wrap:anywhere}.event-time{font:9px "Cascadia Code",Consolas,monospace;color:#6f879d;white-space:nowrap}.empty{padding:28px;text-align:center;color:var(--muted);font-size:11px;border:1px dashed #284056;border-radius:12px}
.model-box{border:1px solid #294356;background:linear-gradient(135deg,#122838,#0c1926);border-radius:13px;padding:13px;margin-bottom:10px}.model-top{display:flex;align-items:center;justify-content:space-between;gap:8px}.model-name{font-size:10px;font-weight:700}.model-role{color:#8fa9bf;font-size:9px}.model-state{font-size:8px;color:var(--green);letter-spacing:.12em}.model-result{font-size:10px;color:#c5d6e6;margin-top:8px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}.confidence{font:9px "Cascadia Code",Consolas,monospace;color:var(--amber)}
.provider-list{display:grid;gap:7px}.knowledge-search{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px;margin-top:15px}.knowledge-search input{min-width:0;border:1px solid #2a435a;border-radius:9px;background:#081522;color:var(--ink);padding:9px 10px;font:10px "Segoe UI",sans-serif}.knowledge-search button{border:1px solid #297d8a;border-radius:9px;padding:8px 12px;background:#123441;color:#d8faff;font-size:9px;font-weight:700}.knowledge-results{display:grid;gap:7px;margin-top:9px}.knowledge-result{border:1px solid #20384b;border-radius:10px;padding:9px;background:#0a1622}.knowledge-result strong{display:block;font-size:10px}.knowledge-result p{margin:5px 0;color:#8fa6b9;font-size:9px;line-height:1.5}.knowledge-result a{font-size:9px;color:var(--cyan);overflow-wrap:anywhere}.knowledge-meta{font-size:8px;color:#718ba2;letter-spacing:.08em}.model-references{display:grid;gap:5px;margin-top:9px}.model-references a{font-size:9px;color:var(--cyan);overflow-wrap:anywhere}.model-references small{color:#718ba2;font-size:8px}.provider{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;border-bottom:1px solid #1b2d40;padding:8px 2px}.provider:last-child{border-bottom:0}.provider strong{font-size:10px;font-weight:600}.provider small{display:block;color:var(--muted);font-size:9px;margin-top:2px}.provider-state{font:9px "Cascadia Code",Consolas,monospace;color:var(--green)}.provider-state.degraded{color:var(--amber)}
.lower{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(280px,.8fr);gap:14px;margin-top:14px}.privacy-note{font-size:10px;color:#93a9bd;line-height:1.6}.privacy-note b{color:#d4e6f4}.privacy-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:12px}.privacy-chip{font-size:9px;padding:8px 9px;border:1px solid #263b4e;border-radius:9px;color:#aec0d0;background:#0b1723}.privacy-chip:before{content:"✓";color:var(--green);margin-right:7px}
footer{font-size:9px;color:#5e748a;text-align:center;padding:23px 0 0;letter-spacing:.06em}
@media(max-width:1050px){.shell{grid-template-columns:68px minmax(0,1fr)}.side{padding:22px 10px;align-items:center}.brand{padding:0}.brand-name,.brand-sub,.nav-label,.nav a span:not(.nav-symbol),.side-bottom{display:none}.nav{width:100%}.nav a{justify-content:center;padding:12px 0}.grid-main{grid-template-columns:1fr}.lower{grid-template-columns:1fr}}
@media(max-width:680px){.shell{display:block}.side{position:relative;width:100%;height:auto;flex-direction:row;justify-content:space-between;padding:10px 15px;border-right:0;border-bottom:1px solid var(--line)}.brand-name,.brand-sub{display:block}.nav{display:flex;width:auto;gap:3px}.nav a{padding:9px}.nav a span:not(.nav-symbol){display:none}.topbar{margin-bottom:16px}.top-right .clock{display:none}main{padding:18px 13px 30px}.hero{grid-template-columns:1fr}.hero-copy{padding:22px}.hero-core{display:none}.hero h1{font-size:26px}.stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.stat{padding:12px}.stat-value{font-size:21px}.lower{grid-template-columns:1fr}.event{grid-template-columns:30px minmax(0,1fr)}.event-time{grid-column:2}.event-icon{width:29px;height:29px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;scroll-behavior:auto!important;transition:none!important}}
</style>
</head>
<body>
<div class="shell">
<aside class="side">
  <div class="brand"><div class="brand-mark"></div><div><div class="brand-name">SENTINEL</div><div class="brand-sub">AIE // CORE SYSTEM</div></div></div>
  <div style="width:100%">
    <div class="nav-label">COMMAND DECK</div>
    <nav class="nav">
      <a class="active" href="#overview"><span class="nav-symbol">◈</span><span>Overview</span></a>
      <a href="#activity"><span class="nav-symbol">⌁</span><span>Activity stream</span></a>
      <a href="#models"><span class="nav-symbol">⟡</span><span>Model fusion</span></a>
      <a href="#sensors"><span class="nav-symbol">⌖</span><span>Sensor matrix</span></a>
      <a href="#privacy"><span class="nav-symbol">◇</span><span>Privacy & control</span></a>
    </nav>
  </div>
  <div class="side-bottom"><small>LOCAL INTELLIGENCE</small><strong>Private by architecture</strong><p>Loopback inference · Local event store · No cloud telemetry</p></div>
</aside>
<main id="overview">
  <div class="topbar"><div><div class="eyebrow">AUTONOMOUS INTELLIGENCE ECOSYSTEM</div><div class="page-title">Sentinel command center</div></div><div class="top-right"><div class="clock" id="clock">--:--:--</div><div class="live" id="liveBadge"><i class="dot"></i><span>CONNECTING</span></div></div></div>
  <section class="hero">
    <div class="hero-copy">
      <div class="hero-kicker">SYSTEM PERCEPTION // CONTINUOUS MODE</div>
      <h1 id="heroTitle">SENTINEL <span>ONLINE</span></h1>
      <p class="hero-desc" id="heroDesc">A bounded, evidence-first watch over approved Windows signals. Every sensor reports its own health; every inference remains advisory.</p>
      <div class="hero-meta">
        <div class="meta-item"><small>RUNTIME PID</small><b id="pid">—</b></div>
        <div class="meta-item"><small>UPTIME</small><b id="uptime">—</b></div>
        <div class="meta-item"><small>LAST HEARTBEAT</small><b id="heartbeat">—</b></div>
      </div>
      <div class="actions" style="margin-top:18px">
        <button class="btn" id="pauseBtn">Ⅱ &nbsp; PAUSE SENSORS</button>
        <button class="btn primary" id="resumeBtn">▶ &nbsp; RESUME SENSORS</button>
        <button class="btn warn" id="stopBtn">■ &nbsp; STOP SENTINEL</button>
      </div>
    </div>
    <div class="hero-core"><div class="core"><div class="core-eye"><span></span></div></div></div>
  </section>
  <section class="stats">
    <div class="stat"><div class="stat-top"><div class="stat-label">CPU LOAD</div><div class="stat-icon">⌁</div></div><div class="stat-value" id="cpu">—%</div><div class="stat-foot">Host processor utilization</div><div class="stat-meter"><i id="cpuBar"></i></div></div>
    <div class="stat"><div class="stat-top"><div class="stat-label">RAM HEADROOM</div><div class="stat-icon">▤</div></div><div class="stat-value" id="ram">— GB</div><div class="stat-foot" id="ramFoot">Available system memory</div><div class="stat-meter"><i id="ramBar"></i></div></div>
    <div class="stat"><div class="stat-top"><div class="stat-label">EVENT VAULT</div><div class="stat-icon">◫</div></div><div class="stat-value" id="eventCount">—</div><div class="stat-foot">Locally persisted observations</div><div class="stat-meter"><i id="eventBar"></i></div></div>
    <div class="stat"><div class="stat-top"><div class="stat-label">SENSOR HEALTH</div><div class="stat-icon">✳</div></div><div class="stat-value" id="health">—</div><div class="stat-foot" id="healthFoot">Provider heartbeat status</div><div class="stat-meter"><i id="healthBar"></i></div></div>
  </section>
  <div class="grid-main">
    <section class="panel" id="telemetry">
      <div class="panel-head"><div><div class="panel-title">LIVE RESOURCE TELEMETRY</div><div class="panel-sub">Rolling host utilization · sampled locally</div></div><span class="tag">REALTIME / 2.5s</span></div>
      <div class="chart-wrap"><canvas id="resourceChart" width="900" height="240"></canvas></div>
      <div class="chart-legend"><span><i class="legend-dot"></i>CPU load</span><span><i class="legend-dot amber"></i>Memory used</span></div>
    </section>
    <section class="panel" id="models">
      <div class="panel-head"><div><div class="panel-title">COGNITIVE MODEL FUSION</div><div class="panel-sub">Local Ollama · serialized inference</div></div><span class="tag" id="modelState">LOCAL ONLY</span></div>
      <div class="model-box"><div class="model-top"><div><div class="model-name" id="triageModel">Fast model · discovering</div><div class="model-role">01 / SIGNAL TRIAGE</div></div><span class="model-state" id="triageState">READY</span></div><div class="model-result" id="triageResult">Waiting for the first evidence-backed assessment.</div></div>
      <div class="model-box"><div class="model-top"><div><div class="model-name" id="reviewModel">Deep model · discovering</div><div class="model-role">02 / INDEPENDENT REVIEW</div></div><span class="model-state" id="reviewState">READY</span></div><div class="model-result" id="reviewResult">The reviewer checks supported claims and uncertainty before anything is surfaced.</div></div>
      <div class="panel-sub" id="modelNote">No model is allowed to execute commands or change policy.</div><div class="model-references" id="modelReferences"></div>
    </section>
  </div>
  <div class="lower">
    <section class="panel" id="activity">
      <div class="panel-head"><div><div class="panel-title">BACKGROUND ACTIVITY STREAM</div><div class="panel-sub">Every persisted sensor event and observer cycle</div></div><span class="tag" id="feedCount">0 RECORDS</span></div>
      <div class="feed" id="eventFeed"><div class="empty">Connecting to the local event vault…</div></div>
    </section>
    <section class="panel" id="sensors">
      <div class="panel-head"><div><div class="panel-title">SENSOR MATRIX</div><div class="panel-sub">Per-provider health and collection cadence</div></div><span class="tag">READ ONLY</span></div>
      <div class="provider-list" id="providerList"><div class="empty">Awaiting provider heartbeat.</div></div>
    </section>
  </div>
  <div class="lower">
    <section class="panel" id="privacy">
      <div class="panel-head"><div><div class="panel-title">OBSERVATION BOUNDARIES</div><span class="tag">USER CONTROLLED</span></div></div>
      <div class="privacy-note">Sentinel watches <b>approved metadata signals</b>, not private content. It is deliberately unable to silently collect secrets, key presses, clipboard data or arbitrary screen contents. Pause and stop are always available from this console.</div>
      <div class="privacy-grid"><div class="privacy-chip">No keylogging or keystroke capture</div><div class="privacy-chip">No password, cookie or token collection</div><div class="privacy-chip">No continuous screenshots or microphone capture</div><div class="privacy-chip">No command lines or executable paths</div><div class="privacy-chip">No cloud upload or remote Ollama fallback</div><div class="privacy-chip">No model-triggered OS actions</div></div>
    </section>
    <section class="panel">
      <div class="panel-head"><div><div class="panel-title">WINDOWS INTERNALS & KNOWLEDGE</div><div class="panel-sub">Registry · CIM · kernel ETW · Microsoft documentation</div></div></div>
      <div class="provider-list" id="runtimeList"><div class="empty">Waiting for Windows internal collectors…</div></div>
      <div class="knowledge-search"><input id="knowledgeQuery" type="search" maxlength="180" placeholder="Search the local Microsoft knowledge vault…"><button id="knowledgeSearchBtn">SEARCH VAULT</button></div>
      <div class="knowledge-results" id="knowledgeResults"><div class="panel-sub">Searches only the locally indexed documents. It does not call the internet.</div></div>
    </section>
  </div>
  <footer>SENTINEL // AIE · WINDOWS PERCEPTION LAYER · LOCAL-FIRST / EVIDENCE-LED</footer>
</main>
</div>
<script>
const token=new URLSearchParams(location.hash.slice(1)).get("token")||"";
if(location.hash)history.replaceState(null,"",location.pathname+location.search);
const $=id=>document.getElementById(id);
let lastStatus=null,historyCpu=[],historyMem=[];
const headers={"X-AIE-Token":token};
function prettyAge(iso){if(!iso)return"—";const d=Math.max(0,Math.floor((Date.now()-new Date(iso).getTime())/1000));return d<60?d+"s ago":d<3600?Math.floor(d/60)+"m ago":Math.floor(d/3600)+"h ago"}
function uptime(iso){if(!iso)return"—";let n=Math.max(0,Math.floor((Date.now()-new Date(iso).getTime())/1000));const h=Math.floor(n/3600);n%=3600;const m=Math.floor(n/60);const s=n%60;return h+"h "+m+"m "+s+"s"}
function setBar(id,v){$(id).style.width=Math.max(0,Math.min(100,Number(v)||0))+"%"}
function create(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el}
function renderInternals(status){
 const list=$("runtimeList");
 list.replaceChildren();
 const registry=status.registry||{};
 const deep=status.deep_inventory||{};
 const knowledge=status.knowledge||{};
 const etw=status.features?.kernel_etw?((status.provider_health||{})["windows.etw.process"]||{}):null;
 const entries=[
  {name:"Registry intelligence",description:registry.status==="watching"?(registry.service_count||0)+" service keys · "+(registry.driver_service_count||0)+" driver entries · "+(registry.changed_sections||[]).length+" changed sections":(registry.error||"Read-only allowlisted snapshots"),state:registry.status||"scheduled"},
  {name:"CIM / driver / PnP inventory",description:deep.status==="available"?(deep.system_driver_count||0)+" system drivers · "+(deep.signed_pnp_driver_count||0)+" signed PnP records · "+(deep.fixed_disk_count||0)+" fixed disks":(deep.error||"Waiting for first inventory pass"),state:deep.status||"scheduled"},
  {name:"Kernel ETW process stream",description:status.features?.kernel_etw?(etw?.state||"elevated access required"):"Optional · disabled by default",state:status.features?.kernel_etw?(etw?.state||"degraded"):"optional"},
  {name:"Microsoft knowledge vault",description:(knowledge.documents||0)+" local documents · "+Object.keys(knowledge.sources||{}).length+" source groups · "+(knowledge.last_fetched_at?prettyAge(knowledge.last_fetched_at):"crawl scheduled"),state:knowledge.status||"scheduled"}
 ];
 for(const item of entries){
  const row=create("div","provider"),left=create("div"),name=create("strong",null,item.name),desc=create("small",null,item.description),state=create("span","provider-state"+(["degraded","partial"].includes(item.state)?" degraded":""),String(item.state).toUpperCase());
  left.append(name,desc);row.append(left,state);list.append(row);
 }
}
function renderKnowledgeResults(results){
 const target=$("knowledgeResults");target.replaceChildren();
 if(!results.length){target.append(create("div","panel-sub","No local documents matched. Run the Microsoft knowledge crawl first."));return}
 for(const item of results){
  const card=create("div","knowledge-result"),title=create("strong",null,item.title||"Untitled document"),meta=create("div","knowledge-meta",String(item.source||"source").replaceAll("_"," ").toUpperCase()+" · SCORE "+item.score),excerpt=create("p",null,item.excerpt||"");
  const link=create("a",null,item.url||"");
  if(item.url){link.href=item.url;link.target="_blank";link.rel="noopener noreferrer"}
  card.append(title,meta,excerpt,link);target.append(card);
 }
}
async function searchKnowledge(){
 const query=$("knowledgeQuery").value.trim();
 if(!query){$("knowledgeQuery").focus();return}
 const target=$("knowledgeResults");target.replaceChildren(create("div","panel-sub","Searching the local index…"));
 try{
  const result=await request("/api/knowledge/search?q="+encodeURIComponent(query)+"&limit=6");
  renderKnowledgeResults(result.results||[]);
 }catch(error){target.replaceChildren(create("div","panel-sub","Local knowledge search unavailable: "+error.message))}
}
function renderModelReferences(items){
 const target=$("modelReferences");
 target.replaceChildren();
 if(!Array.isArray(items)||!items.length)return;
 target.append(create("small",null,"MICROSOFT REFERENCES USED IN THIS REVIEW"));
 for(const item of items.slice(0,4)){
  if(!item||typeof item!=="object")continue;
  let url;
  try{url=new URL(item.url)}catch{continue}
  if(url.protocol!=="https:"||!["learn.microsoft.com","github.com"].includes(url.hostname))continue;
  const link=create("a",null,String(item.title||url.hostname).slice(0,140));
  link.href=url.href;link.target="_blank";link.rel="noopener noreferrer";
  target.append(link);
 }
}
function summaryData(status){const a=status.ai||{};const tri=a.triage||{};const rev=a.review||{};const models=a.models||{};renderModelReferences(a.knowledge_references||[]);$("triageModel").textContent=models.triage||"Fast model · unavailable";$("reviewModel").textContent=models.review||"Deep model · unavailable";$("triageState").textContent=models.triage?"ANALYZED":"WAITING";$("reviewState").textContent=models.independent_review_completed?"VERIFIED REVIEW":"SINGLE MODEL";$("triageResult").textContent=tri.summary||"Waiting for the next scheduled local assessment.";const assess=rev.assessment||"No independent review has been stored yet.";$("reviewResult").textContent=assess+((rev.confidence)?"  ·  "+rev.confidence.toUpperCase()+" CONFIDENCE":"");$("modelState").textContent=models.inference_mode==="local_ollama_only"?"LOCAL ONLY":"NO MODEL";$("modelNote").textContent=a.error?"Last model pass: "+a.error:"Model inference is advisory and runs serially to protect system memory."}
function renderProviders(status){const health=status.provider_health||{};const list=$("providerList");list.replaceChildren();const entries=Object.entries(health);if(!entries.length){list.append(create("div","empty","Provider health will appear after the first collection cycle."));return}for(const [name,item] of entries){const row=create("div","provider"),left=create("div"),title=create("strong",null,name.replaceAll("_"," ")),detail=create("small",null,(item.samples_succeeded||0)+"/"+(item.samples_attempted||0)+" samples · "+(item.events_emitted||0)+" events · "+(item.last_latency_ms??"—")+" ms");left.append(title,detail);const state=create("span","provider-state"+(item.state==="degraded"?" degraded":""),(item.state||"unknown").toUpperCase());row.append(left,state);list.append(row)}}
function renderStatus(s){lastStatus=s;const paused=s.observer_paused===true;const running=s.status==="running";$("liveBadge").innerHTML=running?'<i class="dot"></i><span>'+ (paused?"PAUSED":"LIVE")+'</span>':'<span style="color:var(--amber)">OFFLINE</span>';$("heroTitle").innerHTML="SENTINEL <span>"+(paused?"PAUSED":running?"ONLINE":"OFFLINE")+"</span>";$("heroDesc").textContent=paused?"Observation is paused. The local dashboard and event vault remain available.":running?"A bounded, evidence-first watch over approved Windows signals. Every sensor reports its own health; every inference remains advisory.":"Sentinel worker is not running. Start it from the CLI to resume the background watch.";$("pid").textContent=s.pid||"—";$("uptime").textContent=uptime(s.started_at);$("heartbeat").textContent=prettyAge(s.heartbeat_at);$("pauseBtn").disabled=!running||paused;$("resumeBtn").disabled=!running||!paused;$("stopBtn").disabled=!running;
const hw=s.hardware||{};const cpu=Number(s.cpu_percent)||0;const total=Number(hw.memory_total_gib)||0;const avail=Number(hw.memory_available_gib)||0;const used=total?Math.max(0,total-avail):0;const memPct=total?used/total*100:0;$("cpu").textContent=cpu.toFixed(0)+"%";$("ram").textContent=avail.toFixed(1)+" GB";$("ramFoot").textContent=used.toFixed(1)+" GB used of "+total.toFixed(1)+" GB";setBar("cpuBar",cpu);setBar("ramBar",memPct);historyCpu.push(cpu);historyMem.push(memPct);historyCpu=historyCpu.slice(-64);historyMem=historyMem.slice(-64);
$("eventCount").textContent=Number(s.event_count||0).toLocaleString();setBar("eventBar",Math.min(100,Number(s.event_count||0)/100));const providers=Object.values(s.provider_health||{});const bad=providers.filter(x=>x.state==="degraded").length;$("health").textContent=providers.length?(providers.length-bad)+"/"+providers.length:"—";$("healthFoot").textContent=bad?bad+" provider(s) degraded":"No active provider errors";setBar("healthBar",providers.length?(providers.length-bad)/providers.length*100:0);renderProviders(s);renderInternals(s);summaryData(s)}
function drawChart(){const canvas=$("resourceChart"),ctx=canvas.getContext("2d");const w=canvas.clientWidth*devicePixelRatio,h=canvas.clientHeight*devicePixelRatio;if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}ctx.clearRect(0,0,w,h);const pad=12*devicePixelRatio;ctx.strokeStyle="#20374b";ctx.lineWidth=devicePixelRatio;for(let i=0;i<5;i++){const y=pad+(h-2*pad)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke()}function line(data,color){if(data.length<2)return;ctx.strokeStyle=color;ctx.lineWidth=2*devicePixelRatio;ctx.beginPath();data.forEach((v,i)=>{const x=pad+(w-2*pad)*i/63;const y=h-pad-(h-2*pad)*Math.max(0,Math.min(100,v))/100;if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y)});ctx.stroke()}line(historyCpu,"#53e4f2");line(historyMem,"#ffbd69");requestAnimationFrame(()=>{});}
function renderEvents(events){
 const feed=$("eventFeed");
 feed.replaceChildren();
 $("feedCount").textContent=events.length+" RECORDS";
 if(!events.length){
  feed.append(create("div","empty","No events yet. The observer stream will appear here as Sentinel samples Windows."));
  return;
 }
 for(const ev of events){
  const row=create("article","event");
  const icon=create("div","event-icon",ev.event_type?.includes("network")?"⌁":ev.event_type?.includes("process")?"◉":ev.event_type?.includes("model")?"⟡":"◇");
  const body=create("div");
  const name=create("div","event-name",ev.event_type||"event");
  let desc=ev.entity?.name||ev.source||"system";
  const data=ev.data||{};
  if(ev.event_type==="observer.cycle"){
   const samples=data.providers||[];
   desc="Collected "+(data.events_collected||0)+" observations · "+samples.map(x=>x.provider).join(" / ");
  }else if(ev.event_type==="windows.system_inventory"){
   desc=(data.process_count||0)+" processes · "+(data.installed_application_count||0)+" apps · "+(data.service_count||0)+" services · "+(data.scheduled_task_count||0)+" scheduled tasks";
  }else if(ev.event_type==="sentinel.local_model_assessment"){
   desc="Local model review · "+(data.models?.triage||"triage model")+(data.models?.review?" + "+data.models.review:"");
  }else if(data.process_name){
   desc=data.process_name+(data.pid?" · PID "+data.pid:"");
  }else if(data.summary){
   desc=String(data.summary).slice(0,180);
  }
  const detail=create("div","event-desc",desc);
  const inspect=create("details","event-inspect");
  const inspectLabel=create("summary",null,"INSPECT EVENT DATA");
  const pre=create("pre","event-json",JSON.stringify({
   time:ev.timestamp,
   source:ev.source,
   type:ev.event_type,
   entity:ev.entity,
   confidence:ev.confidence,
   data:data
  },null,2).slice(0,12000));
  inspect.append(inspectLabel,pre);
  body.append(name,detail,inspect);
  const time=create("div","event-time",prettyAge(ev.timestamp));
  row.append(icon,body,time);
  feed.append(row);
 }
}
async function request(path,options={}){const response=await fetch(path,{...options,headers:{...headers,...(options.headers||{})},cache:"no-store"});if(!response.ok)throw new Error("Local API "+response.status);return response.json()}
async function refresh(){try{const [s,e]=await Promise.all([request("/api/status"),request("/api/events?limit=90")]);renderStatus(s);renderEvents(e.events||[]);drawChart()}catch(err){$("liveBadge").innerHTML='<span style="color:var(--amber)">RECONNECTING</span>'}}
async function control(action){if(action==="stop"&&!confirm("Stop the Sentinel background worker? You can start it again from the CLI."))return;try{await request("/api/control",{method:"POST",headers:{"Content-Type":"application/json","Origin":location.origin},body:JSON.stringify({action})});setTimeout(refresh,700)}catch(e){alert("Control request failed: "+e.message)}}
$("pauseBtn").addEventListener("click",()=>control("pause"));$("resumeBtn").addEventListener("click",()=>control("resume"));$("stopBtn").addEventListener("click",()=>control("stop"));
$("knowledgeSearchBtn").addEventListener("click",searchKnowledge);
$("knowledgeQuery").addEventListener("keydown",event=>{if(event.key==="Enter")searchKnowledge()});
$("clock").textContent=new Date().toLocaleTimeString();setInterval(()=>$("clock").textContent=new Date().toLocaleTimeString(),1000);setInterval(refresh,2500);window.addEventListener("resize",drawChart);refresh();
</script>
</body></html>"""


def _safe_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "[bounded]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, list):
        return [_safe_json_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, dict):
        blocked = (
            "password", "token", "secret", "command_line", "executable_path",
            "window_title", "clipboard", "message", "xml", "screenshot",
            "content", "text", "email", "cookie",
        )
        clean: dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            normalized = str(key).casefold()
            if any(part in normalized for part in blocked):
                continue
            clean[str(key)[:80]] = _safe_json_value(item, depth=depth + 1)
        return clean
    return str(type(value).__name__)


def _event_payload(event: Any) -> dict[str, Any] | None:
    if event.sensitivity == "sensitive":
        return None
    return {
        "event_id": event.event_id,
        "timestamp": event.timestamp.isoformat(),
        "source": event.source,
        "event_type": event.event_type,
        "entity": {"type": event.entity.type, "name": event.entity.name},
        "sensitivity": event.sensitivity,
        "confidence": event.confidence,
        "data": _safe_json_value(event.data),
    }


def make_dashboard_server(
    *,
    token: str,
    state_path: Path,
    stop_path: Path,
    db_path: Path,
    port: int = 8765,
) -> ThreadingHTTPServer:
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("dashboard token must contain at least 32 characters")

    class Handler(BaseHTTPRequestHandler):
        server_version = "AIE-Sentinel/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
                "img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            supplied = self.headers.get("X-AIE-Token", "")
            return hmac.compare_digest(supplied, token)

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(
                status,
                json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def do_GET(self) -> None:
            host_header = self.headers.get("Host", "")
            if not (host_header.startswith("127.0.0.1:") or host_header.startswith("localhost:")):
                self._json(403, {"error": "loopback host required"})
                return
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send(200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if not self._authorized():
                self._json(403, {"error": "invalid local dashboard token"})
                return
            if parsed.path == "/api/status":
                try:
                    payload = json.loads(state_path.read_text(encoding="utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("invalid status payload")
                    from aie.config import observer_is_paused
                    payload["observer_paused"] = observer_is_paused()
                    self._json(200, payload)
                except (OSError, ValueError, json.JSONDecodeError):
                    self._json(503, {"error": "Sentinel status is not available yet"})
                return
            if parsed.path == "/api/knowledge/search":
                try:
                    from aie.config import data_dir
                    from aie.knowledge.crawler import KnowledgeStore
                    query = parse_qs(parsed.query).get("q", [""])[0].strip()
                    limit_value = int(parse_qs(parsed.query).get("limit", ["6"])[0])
                    if not query or len(query) > 180:
                        self._json(400, {"error": "query must contain 1-180 characters"})
                        return
                    results = KnowledgeStore(
                        data_dir() / "knowledge" / "microsoft-knowledge.sqlite3"
                    ).search(query, limit=max(1, min(10, limit_value)))
                    self._json(200, {"results": results})
                except (OSError, ValueError):
                    self._json(503, {"error": "Local knowledge index is unavailable"})
                return
            if parsed.path == "/api/events":
                try:
                    values = parse_qs(parsed.query).get("limit", ["90"])
                    limit = max(1, min(200, int(values[0])))
                    store = EventStore(db_path)
                    events = [
                        value for event in store.recent(min(1000, limit * 2))
                        if (value := _event_payload(event)) is not None
                    ][:limit]
                    self._json(200, {"events": events})
                except (OSError, ValueError):
                    self._json(503, {"error": "Event store is not available"})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            host_header = self.headers.get("Host", "")
            if not (host_header.startswith("127.0.0.1:") or host_header.startswith("localhost:")):
                self._json(403, {"error": "loopback host required"})
                return
            expected_origin = f"http://{host_header}"
            if self.headers.get("Origin") != expected_origin or not self._authorized():
                self._json(403, {"error": "origin or token rejected"})
                return
            if urlparse(self.path).path != "/api/control":
                self._json(404, {"error": "not found"})
                return
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError:
                length = 0
            if not 1 <= length <= 1024:
                self._json(400, {"error": "invalid request size"})
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self._json(400, {"error": "invalid JSON"})
                return
            action = body.get("action") if isinstance(body, dict) else None
            if action == "pause":
                set_observer_paused(True)
            elif action == "resume":
                set_observer_paused(False)
            elif action == "stop":
                stop_path.touch(exist_ok=True)
            else:
                self._json(400, {"error": "unsupported control action"})
                return
            self._json(200, {"accepted": action})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def start_dashboard_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(
        target=server.serve_forever,
        name="aie-sentinel-dashboard",
        daemon=True,
    )
    thread.start()
    return thread
