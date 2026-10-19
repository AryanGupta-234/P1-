"""Loopback-only Sentinel dashboard with a built-in, dependency-free web interface."""
from __future__ import annotations

import hmac
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any, Callable

from aie.config import set_observer_paused
from aie.store import EventStore


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>SENTINEL // AIE</title>
<style>
.core-eye{width:78px;height:78px;transform:none;position:relative;clip-path:polygon(50% 0,88% 12%,100% 42%,87% 83%,50% 100%,13% 83%,0 42%,12% 12%);border:2px solid #7feaff;background:linear-gradient(155deg,#4a7184 0%,#1a3447 30%,#081725 75%);box-shadow:0 0 30px #53e4f277,inset 0 0 20px #ff647633}
.core-eye:before{content:"";position:absolute;left:15%;right:15%;top:16%;height:18%;background:linear-gradient(90deg,#ff6a7e,#8eeeff 48%,#ff6a7e);clip-path:polygon(0 0,100% 0,82% 100%,18% 100%);opacity:.92}
.core-eye:after{content:"";position:absolute;left:26%;right:26%;bottom:10%;height:19%;background:linear-gradient(90deg,#ff6476,#304f64,#ff6476);clip-path:polygon(0 0,100% 0,72% 100%,28% 100%);border:1px solid #ff6376}
.core-eye span{position:relative;z-index:1;width:22px;height:22px;transform:none;border:3px solid #eaffff;background:radial-gradient(circle,#fff 0,#70edff 38%,#1686a2 75%);box-shadow:0 0 24px #6cefff,0 0 42px #ff526d66}
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

/* TITAN DECK visual system — cinematic motion, readable data, reduced-motion safe. */
:root{--red:#ff526d;--steel:#a9c4d7;--electric:#69e8ff;--line:#25435a}
body{background:radial-gradient(ellipse at 74% -10%,#1c3e58 0,transparent 40%),radial-gradient(ellipse at 8% 28%,#36192555 0,transparent 34%),linear-gradient(145deg,#050a12,#0a1725 56%,#080e18)}
body:after{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.075;background:repeating-linear-gradient(0deg,transparent 0 3px,#a7efff 4px,transparent 5px);mix-blend-mode:screen;animation:scan-drift 14s linear infinite}
.shell{z-index:1}
.side{background:linear-gradient(180deg,#0a1522ed,#080e19f2);border-right-color:#2a4053;box-shadow:12px 0 38px #0004}
.brand-mark{border-radius:10px;background:linear-gradient(145deg,#152d40,#07111c);box-shadow:0 0 30px #55dff12b,inset 0 0 24px #e0f9ff18}
.brand-mark:after{content:"";position:absolute;inset:5px;border:1px solid #ff64764c;transform:rotate(45deg)}
.nav a.active{background:linear-gradient(90deg,#163449,#172438);box-shadow:inset 2px 0 0 var(--electric),0 8px 24px #0004}
.hero{background:linear-gradient(112deg,#172b3d 0%,#0c1b2a 48%,#191925 100%);border-color:#42627a;box-shadow:0 22px 70px #0008,inset 0 1px #b2eaff12}
.hero:before{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(110deg,transparent 22%,#9beeff09 42%,transparent 60%);background-size:220% 100%;animation:armor-sheen 9s ease-in-out infinite}
.hero:after{border-color:#83eaff24;box-shadow:0 0 0 32px #58dff20d,0 0 0 70px #ff536d08,0 0 55px #5fe8ff0b}
.hero h1{letter-spacing:.12em;text-shadow:0 3px 24px #0008}
.hero h1 span{color:#8cecff;text-shadow:0 0 20px #5fe7ff77}
.hero-kicker{color:#ff8192}
.core{width:168px;height:168px;border-color:#8cecffaa;box-shadow:0 0 48px #48dffa38,inset 0 0 45px #55dff52c,0 0 0 1px #ff536d1c;animation:reactor-breathe 4s ease-in-out infinite}
.core:before{border-top-color:#ff687d;border-bottom-color:#78eaff;inset:-12px;animation-duration:10s}
.core:after{inset:-24px;border-width:2px;border-color:#6ce8ff75 transparent #ff647655;animation-duration:17s}
.core-eye{border-radius:17px 17px 17px 5px;background:linear-gradient(145deg,#29495b,#0b1b2a);box-shadow:0 0 28px #53e4f255,inset 0 0 14px #ff5f7522}
.core-eye span{width:28px;height:28px;box-shadow:0 0 24px #63efff,0 0 48px #ff526d4d;animation:optic-pulse 2.8s ease-in-out infinite}
.panel,.stat{background:linear-gradient(145deg,#132334ed,#0a1421f5);border-color:#29465d;box-shadow:0 12px 34px #0003,inset 0 1px #d3f6ff0a;transition:transform .25s ease,border-color .25s ease,box-shadow .25s ease}
.panel{position:relative;overflow:hidden}
.panel:before{content:"";position:absolute;left:18px;right:18px;top:0;height:1px;background:linear-gradient(90deg,transparent,#81e9ff88,#ff637355,transparent);opacity:.55}
.panel:hover,.stat:hover{transform:translateY(-2px);border-color:#4a7896;box-shadow:0 16px 38px #0005,0 0 20px #57dff20b}
.stat-value{letter-spacing:-.04em;text-shadow:0 0 18px #63ddff18}
.btn{border-color:#456077;background:linear-gradient(145deg,#1a3348,#102236);box-shadow:inset 0 1px #e7f9ff16,0 4px 12px #0003}
.btn.primary{background:linear-gradient(120deg,#167a92,#234f78 62%,#713847);border-color:#67dff0;box-shadow:0 0 20px #54def52b,inset 0 1px #fff4}
.btn.warn{background:linear-gradient(120deg,#3a1b2a,#251522);border-color:#8d4658}
.tag{color:#a9f2ff;border-color:#3f7181;background:#102b39}
.command-strip{display:grid;grid-template-columns:minmax(180px,.75fr) minmax(0,1.8fr);gap:16px;align-items:center;padding:15px 18px;margin:14px 0;border:1px solid #375970;border-radius:17px;background:linear-gradient(105deg,#101f30,#142a3b 54%,#241a27);box-shadow:0 10px 30px #0005;position:relative;overflow:hidden}
.command-strip:after{content:"";position:absolute;right:-60px;top:-95px;width:230px;height:230px;border:1px solid #65e5ff27;border-radius:50%;box-shadow:0 0 0 22px #65e5ff08,0 0 0 48px #ff536d08;pointer-events:none}
.command-heading{font-size:10px;font-weight:800;letter-spacing:.18em;color:#c9e7f8}
.command-caption{font-size:9px;color:#8ca9bf;margin-top:4px;line-height:1.5}
.command-actions{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;z-index:1}
.command-feedback{grid-column:1/-1;font-size:9px;color:#87dcec;min-height:13px;letter-spacing:.06em}
.feature-grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(290px,.85fr);gap:14px;margin-top:14px}
.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:8px 0 13px}
.metric-tile{padding:11px;border:1px solid #29455b;border-radius:11px;background:#0a1724}
.metric-tile small{display:block;color:#7f9bb1;font-size:8px;letter-spacing:.13em}
.metric-tile strong{display:block;color:#e5f6ff;font:17px "Cascadia Code",Consolas,monospace;margin-top:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.deep-columns{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.deep-subhead{font-size:9px;color:#91b4c8;letter-spacing:.12em;margin:5px 0 8px}
.disk-list,.security-list,.insight-list{display:grid;gap:7px}
.disk-row,.security-row,.insight-item{border:1px solid #243e53;background:#0b1825;border-radius:10px;padding:9px}
.disk-top,.security-row{display:flex;align-items:center;justify-content:space-between;gap:9px}
.disk-top strong,.security-row strong{font-size:9px}
.disk-top small,.security-row span{font:9px "Cascadia Code",Consolas,monospace;color:#8ca9bf}
.disk-meter{height:4px;background:#26394b;border-radius:9px;margin:8px 0 5px;overflow:hidden}
.disk-meter i{display:block;height:100%;background:linear-gradient(90deg,#438dba,#67eaff,#ff7587);box-shadow:0 0 10px #5fe5ff55}
.pnp-pills{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.driver-list{display:grid;gap:6px;margin-top:8px;max-height:290px;overflow:auto;padding-right:3px}
.health-good{color:#75e8c4!important}.health-warn{color:#ffcb79!important}.health-bad{color:#ff93a4!important}
.alert-card{border:1px solid #3a4c5e;background:linear-gradient(110deg,#0d1925,#132333);border-radius:10px;padding:10px}
.alert-card.high{border-left:3px solid #ffbd69}.alert-card.critical{border-left:3px solid #ff536d}.alert-card.info{border-left:3px solid #6dcfee}
.alert-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.alert-top strong{font-size:9px}.alert-severity{font:8px "Cascadia Code",Consolas,monospace;color:#ffcc84;letter-spacing:.1em}
.alert-card.critical .alert-severity{color:#ff8da0}.alert-card.info .alert-severity{color:#80dfff}
.alert-card p{margin:5px 0 0;color:#9bb1c4;font-size:9px;line-height:1.5}

.health-detail{font-size:8px;color:#819bb0;margin-top:4px;line-height:1.45}

.driver-row{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,.8fr) auto;gap:8px;align-items:center;border:1px solid #243e53;border-radius:9px;padding:8px;background:#0a1723}
.driver-row strong{display:block;font-size:9px;overflow-wrap:anywhere}
.driver-row small{display:block;color:#7f9bb1;font-size:8px;margin-top:3px;overflow-wrap:anywhere}
.driver-state{font:8px "Cascadia Code",Consolas,monospace;color:#72e6c4}
.driver-state.unsigned{color:#ff9cad}

.pnp-pill{font-size:8px;padding:5px 8px;border-radius:20px;background:#142a3b;border:1px solid #35546b;color:#b6d2e4}
.pnp-pill.bad{border-color:#8b4957;color:#ffabb7;background:#301c27}
.profile-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.profile-toggle{display:flex;align-items:flex-start;gap:9px;border:1px solid #29445a;border-radius:10px;background:#0b1825;padding:10px}
.profile-toggle input{accent-color:#65e8ff;margin-top:2px}
.profile-toggle strong{display:block;font-size:9px}
.profile-toggle small{display:block;color:#819cb1;font-size:8px;margin-top:3px;line-height:1.45}
.interval-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:13px 0}
.interval-field label{display:block;font-size:8px;color:#8ba6bb;margin-bottom:5px}
.interval-field input{width:100%;min-width:0;padding:8px 7px;border:1px solid #304b61;border-radius:8px;background:#07131f;color:#e5f4ff;font:10px "Cascadia Code",Consolas,monospace}
.profile-note{font-size:9px;color:#7f9cb2;line-height:1.55;margin-top:10px}
.ask-form{display:grid;gap:8px}
.ask-form textarea{width:100%;min-height:75px;resize:vertical;background:#07131f;border:1px solid #35536b;border-radius:10px;color:#e9f7ff;padding:10px;font:11px/1.5 "Segoe UI",sans-serif}
.ask-result{margin-top:11px;padding:11px;border:1px solid #29465c;border-radius:11px;background:#0a1724;min-height:45px;color:#bfd4e5;font-size:10px;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}
.ask-result a{display:block;color:#7beaff;margin-top:6px;font-size:9px;overflow-wrap:anywhere}
.insight-item strong{display:block;font-size:9px;color:#d7edfa}
.insight-item p{margin:5px 0 0;font-size:9px;color:#93aec1;line-height:1.5}
.command-feedback.good{color:#76e8c1}.command-feedback.bad{color:#ff9bab}
@keyframes scan-drift{to{transform:translateY(9px)}}
@keyframes armor-sheen{0%,100%{background-position:120% 0}50%{background-position:-30% 0}}
@keyframes reactor-breathe{50%{box-shadow:0 0 68px #48dffa52,inset 0 0 50px #55dff548,0 0 0 1px #ff536d33}}
@keyframes optic-pulse{50%{transform:scale(1.17);opacity:.78}}
@media(max-width:1050px){.feature-grid{grid-template-columns:1fr}.interval-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:680px){.command-strip{grid-template-columns:1fr}.command-actions{justify-content:flex-start}.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.deep-columns{grid-template-columns:1fr}.profile-grid{grid-template-columns:1fr}.interval-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(prefers-reduced-motion:reduce){body:after{animation:none}.core,.core-eye span{animation:none}.hero:before{animation:none}.panel,.stat{transition:none}}

</style>
</head>
<body>
<div class="shell">
<aside class="side">
  <div class="brand"><div class="brand-mark"></div><div><div class="brand-name">SENTINEL</div><div class="brand-sub">AIE // CORE SYSTEM</div></div></div>
  <div style="width:100%">
    <div class="nav-label">COMMAND DECK</div>
    <nav class="nav">
      <a class="active" href="#overview"><span class="nav-symbol">◈</span><span>Command center</span></a>
      <a href="#deepdiagnostics"><span class="nav-symbol">⌖</span><span>Deep diagnostics</span></a>
      <a href="#activity"><span class="nav-symbol">⌁</span><span>Activity stream</span></a>
      <a href="#models"><span class="nav-symbol">⟡</span><span>AI fusion</span></a>
      <a href="#ask"><span class="nav-symbol">✳</span><span>Ask Sentinel</span></a>
      <a href="#profile"><span class="nav-symbol">⚙</span><span>Autonomous profile</span></a>
      <a href="#privacy"><span class="nav-symbol">◇</span><span>Privacy</span></a>
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
  <section class="command-strip" id="autopilot">
    <div><div class="command-heading">MISSION CONTROL // LIVE OPERATIONS</div><div class="command-caption">Queue bounded diagnostics, request an evidence review or refresh the local knowledge vault. Actions stay local and advisory.</div></div>
    <div class="command-actions">
      <button class="btn primary" id="scanNowBtn">◈ &nbsp; FULL SYSTEM SCAN</button>
      <button class="btn" id="aiNowBtn">✳ &nbsp; AI REVIEW NOW</button>
      <button class="btn" id="crawlNowBtn">⌁ &nbsp; SYNC KNOWLEDGE</button>
    </div>
    <div class="command-feedback" id="commandFeedback">COMMAND CHANNEL READY · LOCAL QUEUE</div>
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
  <div class="feature-grid">
    <section class="panel" id="deepdiagnostics">
      <div class="panel-head"><div><div class="panel-title">DEEP SYSTEM DIAGNOSTICS</div><div class="panel-sub">CIM · storage · drivers · PnP · Defender · firewall</div></div><span class="tag">WINDOWS INTERNALS</span></div>
      <div class="metric-grid">
        <div class="metric-tile"><small>PROCESSES</small><strong id="metricProcesses">—</strong></div>
        <div class="metric-tile"><small>INSTALLED APPS</small><strong id="metricApps">—</strong></div>
        <div class="metric-tile"><small>SERVICES</small><strong id="metricServices">—</strong></div>
        <div class="metric-tile"><small>SCHEDULED TASKS</small><strong id="metricTasks">—</strong></div>
        <div class="metric-tile"><small>DRIVER CATALOG</small><strong id="metricDrivers">—</strong></div>
        <div class="metric-tile"><small>PNP DEVICES</small><strong id="metricPnp">—</strong></div>
        <div class="metric-tile"><small>FIREWALL PROFILES</small><strong id="metricFirewall">—</strong></div>
        <div class="metric-tile"><small>WINDOWS BUILD</small><strong id="metricBuild">—</strong></div>
        <div class="metric-tile"><small>PHYSICAL DISKS</small><strong id="metricPhysicalDisks">—</strong></div>
        <div class="metric-tile"><small>BITLOCKER VOLUMES</small><strong id="metricBitlocker">—</strong></div>
        <div class="metric-tile"><small>BATTERY</small><strong id="metricBattery">—</strong></div>
        <div class="metric-tile"><small>HYPERVISOR</small><strong id="metricHypervisor">—</strong></div>
      </div>
      <div class="deep-columns">
        <div><div class="deep-subhead">FIXED STORAGE</div><div id="diskList" class="disk-list"><div class="panel-sub">Waiting for a CIM snapshot.</div></div>
          <div class="deep-subhead" style="margin-top:16px">PHYSICAL STORAGE HEALTH</div><div id="physicalHealthList" class="disk-list"><div class="panel-sub">Storage health metadata appears when Windows exposes the Storage module.</div></div>
          <div class="deep-subhead" style="margin-top:16px">SIGNED DRIVER / DEVICE EXPLORER</div>
          <div class="knowledge-search"><input id="driverQuery" type="search" maxlength="100" placeholder="Filter device or driver provider…"><button id="driverSearchBtn">FILTER</button></div>
          <div class="driver-list" id="driverResults"><div class="panel-sub">Searches the latest local signed-PnP inventory snapshot.</div></div>
        </div>
        <div><div class="deep-subhead">SECURITY & DEVICE HEALTH</div><div id="securityList" class="security-list"><div class="panel-sub">Waiting for Defender / firewall status.</div></div><div class="deep-subhead" style="margin-top:14px">BITLOCKER ENCRYPTION</div><div id="encryptionList" class="security-list"><div class="panel-sub">Volume encryption metadata appears when available.</div></div>
          <div class="deep-subhead" style="margin-top:14px">BATTERY STATUS</div><div id="batteryList" class="security-list"><div class="panel-sub">Battery telemetry appears when a battery is present.</div></div>
          <div id="pnpSummary" class="pnp-pills"></div></div>
      </div>
    </section>
    <section class="panel" id="insights">
      <div class="panel-head"><div><div class="panel-title">AUTONOMOUS HEALTH WATCH</div><div class="panel-sub">Rule-based posture alerts · local AI corroboration</div></div><span class="tag">ADVISORY ONLY</span></div>
      <div class="deep-subhead">WINDOWS POSTURE ALERTS</div>
      <div class="insight-list" id="healthAlerts"><div class="empty">Waiting for a deep system snapshot.</div></div>
      <div class="deep-subhead" style="margin-top:15px">LOCAL AI CORROBORATION</div>
      <div class="insight-list" id="aiInsights"><div class="empty">Waiting for the next local model assessment.</div></div>
      <div class="profile-note">The model cannot run commands, alter Windows settings or remediate automatically. Every signal is shown as a hypothesis unless supported by collected evidence.</div>
    </section>
  </div>
  <div class="feature-grid">
    <section class="panel" id="ask">
      <div class="panel-head"><div><div class="panel-title">ASK SENTINEL // LOCAL AI</div><div class="panel-sub">Ask about the latest approved telemetry and indexed Microsoft references</div></div><span class="tag">OLLAMA / LOCAL</span></div>
      <div class="ask-form">
        <textarea id="askQuestion" maxlength="500" placeholder="Example: What changed in the last registry snapshot, and what evidence supports it?"></textarea>
        <div class="actions"><button class="btn primary" id="askButton">✳ &nbsp; ASK LOCAL SENTINEL</button><span class="panel-sub" id="askMeta">Uses an installed 3B/4B model; no cloud fallback or model download.</span></div>
      </div>
      <div class="ask-result" id="askResult">Your answer will appear here with evidence IDs and any matching local Microsoft references.</div>
    </section>
    <section class="panel" id="profile">
      <div class="panel-head"><div><div class="panel-title">AUTONOMOUS SENSOR PROFILE</div><div class="panel-sub">Live controls · saved locally · applied on next observer cycle</div></div><span class="tag">PROFILE CONTROL</span></div>
      <div class="profile-grid">
        <label class="profile-toggle"><input type="checkbox" id="cfgRegistry"><span><strong>Registry intelligence</strong><small>Allowlisted read-only registry snapshots and autorun change detection</small></span></label>
        <label class="profile-toggle"><input type="checkbox" id="cfgDeep"><span><strong>Deep Windows inventory</strong><small>Drivers, signed PnP, storage, Defender and firewall metadata</small></span></label>
        <label class="profile-toggle"><input type="checkbox" id="cfgKnowledge"><span><strong>Microsoft knowledge crawler</strong><small>Public Learn and selected Microsoft GitHub docs, indexed locally</small></span></label>
        <label class="profile-toggle"><input type="checkbox" id="cfgAI"><span><strong>Local AI analysis</strong><small>Scheduled 4B triage / independent reviewer when resources permit</small></span></label>
      </div>
      <div class="interval-grid">
        <div class="interval-field"><label for="cfgRegistryInterval">REGISTRY SEC</label><input id="cfgRegistryInterval" type="number" min="60" max="3600" step="30"></div>
        <div class="interval-field"><label for="cfgDeepInterval">DEEP SCAN SEC</label><input id="cfgDeepInterval" type="number" min="300" max="7200" step="60"></div>
        <div class="interval-field"><label for="cfgKnowledgeInterval">KNOWLEDGE SEC</label><input id="cfgKnowledgeInterval" type="number" min="3600" max="604800" step="1800"></div>
        <div class="interval-field"><label for="cfgAIInterval">AI REVIEW SEC</label><input id="cfgAIInterval" type="number" min="60" max="3600" step="30"></div>
      </div>
      <div class="actions"><button class="btn primary" id="saveProfileBtn">SAVE & APPLY PROFILE</button><button class="btn" id="reloadProfileBtn">RELOAD SAVED</button></div>
      <div class="profile-note" id="profileNote">Sensitive foreground titles, Event Log, UI Automation and ETW remain opt-in through the CLI. These controls do not silently enable them.</div>
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
async function searchDrivers(){
 const query=$("driverQuery").value.trim(),target=$("driverResults");
 target.replaceChildren(create("div","panel-sub","Searching the latest local driver snapshot…"));
 try{
  const result=await request("/api/drivers?q="+encodeURIComponent(query));
  target.replaceChildren();
  if(!result.drivers?.length){target.append(create("div","panel-sub",result.snapshot_at?"No signed-PnP records matched this filter.":"Run a deep system scan to collect driver metadata."));return}
  for(const item of result.drivers){
   const row=create("div","driver-row"),left=create("div"),name=create("strong",null,item.device),sub=create("small",null,item.provider+" · "+item.version),date=create("small",null,item.driver_date),signature=create("span","driver-state"+(item.signed===false?" unsigned":""),item.signed===true?"SIGNED":item.signed===false?"UNSIGNED":"UNKNOWN");
   left.append(name,sub);row.append(left,date,signature);target.append(row);
  }
  const meta=create("div","knowledge-meta","MATCHED "+result.matched+" / "+result.total+" · SNAPSHOT "+prettyAge(result.snapshot_at));meta.style.marginTop="7px";target.prepend(meta);
 }catch(error){target.replaceChildren(create("div","panel-sub","Driver lookup unavailable: "+error.message))}
}
function renderDeepDiagnostics(status){
 const inv=status.inventory_summary||{},deep=status.deep_inventory||{},osInfo=deep.operating_system||{},defender=deep.defender||{};
 $("metricProcesses").textContent=inv.processes??"—";
 $("metricApps").textContent=inv.applications??"—";
 $("metricServices").textContent=inv.services??"—";
 $("metricTasks").textContent=inv.scheduled_tasks??"—";
 $("metricDrivers").textContent=deep.system_driver_count??"—";
 $("metricPnp").textContent=deep.pnp_device_count??"—";
 $("metricFirewall").textContent=deep.firewall_profile_count??"—";
 $("metricBuild").textContent=[osInfo.Caption,osInfo.BuildNumber].filter(Boolean).join(" · ")||"—";
 const physical=Array.isArray(deep.physical_disks)?deep.physical_disks:[];
 const encryption=Array.isArray(deep.bitlocker_volumes)?deep.bitlocker_volumes:[];
 const batteries=Array.isArray(deep.batteries)?deep.batteries:[];
 $("metricPhysicalDisks").textContent=deep.last_snapshot_at?(deep.physical_disk_count??physical.length):"—";
 $("metricBitlocker").textContent=deep.last_snapshot_at?(deep.bitlocker_volume_count??encryption.length):"—";
 $("metricBattery").textContent=!deep.last_snapshot_at?"—":batteries.length?(batteries[0].charge_percent==null?"Present":batteries[0].charge_percent+"%"):"N/A";
 $("metricHypervisor").textContent=deep.hypervisor_present===true?"DETECTED":deep.hypervisor_present===false?"NO":"—";
 const physicalTarget=$("physicalHealthList");physicalTarget.replaceChildren();
 if(!physical.length)physicalTarget.append(create("div","panel-sub","Physical disk health is not exposed by this Windows configuration."));
 for(const disk of physical){
  const health=String(disk.health||"UNKNOWN").toLowerCase();
  const healthClass=health==="healthy"?"good":health==="warning"?"warn":health==="unhealthy"||health==="critical"?"bad":"";
  const row=create("div","disk-row"),top=create("div","disk-top"),name=create("strong",null,disk.name||"Physical disk"),state=create("small",healthClass?"health-"+healthClass:"",health.toUpperCase());
  top.append(name,state);row.append(top,create("div","health-detail",(disk.media_type||"—")+" · "+(disk.bus_type||"—")+" · "+(disk.operational||"—")+" · "+(disk.size_gib||0)+" GiB"));physicalTarget.append(row);
 }
 const encryptionTarget=$("encryptionList");encryptionTarget.replaceChildren();
 if(!encryption.length)encryptionTarget.append(create("div","panel-sub","BitLocker status is unavailable or no BitLocker volumes were returned."));
 for(const volume of encryption){
  const row=create("div","security-row"),left=create("div"),name=create("strong",null,(volume.mount||"Volume")+" · "+(volume.volume_status||"Unknown")),detail=create("small","health-detail",(volume.encryption_percent??"—")+"% encrypted · "+(volume.method||"—")),state=create("span","provider-state"+(String(volume.protection||"").toLowerCase()==="on"?"":" degraded"),String(volume.protection||"UNKNOWN").toUpperCase());
  left.append(name,detail);row.append(left,state);encryptionTarget.append(row);
 }
 const batteryTarget=$("batteryList");batteryTarget.replaceChildren();
 if(!batteries.length)batteryTarget.append(create("div","panel-sub","No battery telemetry is available."));
 for(const battery of batteries){
  const row=create("div","security-row"),name=create("strong",null,battery.name||"Battery"),statusText=create("span","provider-state",battery.charge_percent==null?"UNKNOWN":battery.charge_percent+"%");
  row.append(name,statusText,battery.estimated_runtime_minutes==null?create("small","health-detail",battery.health_status||""):create("small","health-detail","Estimated runtime "+battery.estimated_runtime_minutes+" min"));batteryTarget.append(row);
 }
 const disks=$("diskList");disks.replaceChildren();
 const diskItems=Array.isArray(deep.disks)?deep.disks:[];
 if(!diskItems.length)disks.append(create("div","panel-sub","Disk inventory will appear after the next CIM scan."));
 for(const disk of diskItems){
  const row=create("div","disk-row"),top=create("div","disk-top"),name=create("strong",null,(disk.drive||"Drive")+" · "+(disk.filesystem||"—")),detail=create("small",null,(disk.free_gib??"—")+" / "+(disk.size_gib??"—")+" GB free");
  const meter=create("div","disk-meter"),bar=create("i");bar.style.width=Math.max(0,Math.min(100,Number(disk.used_percent)||0))+"%";meter.append(bar);
  top.append(name,detail);row.append(top,meter,create("div","panel-sub",(Number(disk.used_percent)||0).toFixed(1)+"% used"));disks.append(row);
 }
 const security=$("securityList");security.replaceChildren();
 const securityItems=[
  ["Microsoft Defender",defender.AntivirusEnabled],
  ["Real-time protection",defender.RealTimeProtectionEnabled],
  ["Behavior monitoring",defender.BehaviorMonitorEnabled],
  ["Network inspection",defender.NISEnabled]
 ];
 const firewall=Array.isArray(deep.firewall_profiles)?deep.firewall_profiles:[];
 for(const item of firewall)securityItems.push(["Firewall "+(item.name||"profile"),item.enabled]);
 if(!securityItems.length)security.append(create("div","panel-sub","Security status is not yet available."));
 for(const item of securityItems){
  const row=create("div","security-row"),label=create("strong",null,item[0]),state=create("span",null,item[1]===true?"ENABLED":item[1]===false?"DISABLED":"UNKNOWN");
  if(item[1]===false)state.style.color="var(--red)";
  row.append(label,state);security.append(row);
 }
 const pnp=$("pnpSummary");pnp.replaceChildren();
 for(const item of (Array.isArray(deep.pnp_status_counts)?deep.pnp_status_counts:[]).slice(0,8)){
  const statusName=String(item.status||"unknown"),pill=create("span","pnp-pill"+(statusName.toLowerCase()!=="ok"&&statusName.toLowerCase()!=="unknown"?" bad":""),statusName.toUpperCase()+" · "+item.count);
  pnp.append(pill);
 }
}
function renderHealthAlerts(status){
 const target=$("healthAlerts"),deep=status.deep_inventory||{},alerts=Array.isArray(deep.posture_alerts)?deep.posture_alerts:[];
 target.replaceChildren();
 if(!deep.last_snapshot_at){target.append(create("div","empty","A posture snapshot has not completed yet."));return}
 if(!alerts.length){target.append(create("div","alert-card info", "No rule-based alerts in the latest snapshot. This is not a guarantee of security."));return}
 for(const item of alerts.slice(0,12)){
  const severity=["critical","high","info"].includes(String(item.severity||"").toLowerCase())?String(item.severity).toLowerCase():"info";
  const card=create("article","alert-card "+severity),top=create("div","alert-top"),title=create("strong",null,item.title||"System posture signal"),badge=create("span","alert-severity",severity.toUpperCase()+" · "+String(item.category||"SYSTEM").toUpperCase()),detail=create("p",null,item.detail||"");
  top.append(title,badge);card.append(top,detail);target.append(card);
 }
}
function renderAIInsights(status){
 const target=$("aiInsights");target.replaceChildren();
 const ai=status.ai||{},tri=ai.triage||{},review=ai.review||{};
 const entries=[];
 for(const item of (Array.isArray(tri.signals)?tri.signals:[]).slice(0,3))entries.push({title:"OBSERVED SIGNAL",body:typeof item==="string"?item:JSON.stringify(item)});
 for(const item of (Array.isArray(tri.hypotheses)?tri.hypotheses:[]).slice(0,3))entries.push({title:"MODEL HYPOTHESIS",body:typeof item==="string"?item:JSON.stringify(item)});
 for(const item of (Array.isArray(review.uncertainties)?review.uncertainties:[]).slice(0,2))entries.push({title:"REVIEW UNCERTAINTY",body:typeof item==="string"?item:JSON.stringify(item)});
 if(!entries.length){target.append(create("div","empty",ai.error?"Local AI unavailable: "+ai.error:"No AI findings have been stored yet."));return}
 for(const entry of entries){const card=create("div","insight-item"),title=create("strong",null,entry.title),body=create("p",null,entry.body.slice(0,500));card.append(title,body);target.append(card)}
}
function renderProfile(profile){
 if(!profile)return;
 $("cfgRegistry").checked=profile.registry_enabled===true;
 $("cfgDeep").checked=profile.deep_inventory_enabled===true;
 $("cfgKnowledge").checked=profile.knowledge_enabled===true;
 $("cfgAI").checked=profile.ai_enabled===true;
 $("cfgRegistryInterval").value=profile.registry_interval_seconds??180;
 $("cfgDeepInterval").value=profile.deep_inventory_interval_seconds??900;
 $("cfgKnowledgeInterval").value=profile.knowledge_interval_seconds??21600;
 $("cfgAIInterval").value=profile.analysis_interval_seconds??300;
}
async function loadProfile(){
 try{const result=await request("/api/config");renderProfile(result.profile);$("profileNote").textContent="Saved profile loaded · changes apply on the next observer cycle."}
 catch(error){$("profileNote").textContent="Profile unavailable: "+error.message}
}
async function saveProfile(){
 const integer=id=>Number.parseInt($(id).value,10);
 const values={
  registry_enabled:$("cfgRegistry").checked,
  deep_inventory_enabled:$("cfgDeep").checked,
  knowledge_enabled:$("cfgKnowledge").checked,
  ai_enabled:$("cfgAI").checked,
  registry_interval_seconds:integer("cfgRegistryInterval"),
  deep_inventory_interval_seconds:integer("cfgDeepInterval"),
  knowledge_interval_seconds:integer("cfgKnowledgeInterval"),
  analysis_interval_seconds:integer("cfgAIInterval")
 };
 $("saveProfileBtn").disabled=true;
 try{
  const result=await request("/api/config",{method:"POST",headers:{"Content-Type":"application/json","Origin":location.origin},body:JSON.stringify({values})});
  renderProfile(result.profile);$("profileNote").textContent="PROFILE SAVED · SENTINEL WILL APPLY IT ON THE NEXT OBSERVER CYCLE";notifyCommand("Autonomous sensor profile saved and queued for live application.",true);
 }catch(error){$("profileNote").textContent="Save failed: "+error.message;notifyCommand("Profile save failed: "+error.message,false)}
 finally{$("saveProfileBtn").disabled=false}
}
function notifyCommand(message,good){
 const target=$("commandFeedback");target.textContent=message;target.className="command-feedback "+(good?"good":"bad");
}
async function runCommand(action){
 const labels={scan_now:"Full system scan",ai_review_now:"Local AI review",knowledge_crawl_now:"Microsoft knowledge crawl",deep_scan_now:"Deep CIM scan",registry_scan_now:"Registry scan"};
 try{const result=await request("/api/command",{method:"POST",headers:{"Content-Type":"application/json","Origin":location.origin},body:JSON.stringify({action})});notifyCommand((labels[action]||"Command")+" queued · "+(result.queued||action),true);setTimeout(refresh,1200)}
 catch(error){notifyCommand("Command rejected: "+error.message,false)}
}
async function askSentinel(){
 const question=$("askQuestion").value.trim();if(!question){$("askQuestion").focus();return}
 const button=$("askButton"),target=$("askResult");button.disabled=true;button.textContent="PROCESSING LOCALLY…";target.textContent="Running local inference against bounded event evidence and the local Microsoft index. This may take a little while.";
 try{
  const result=await request("/api/ask",{method:"POST",headers:{"Content-Type":"application/json","Origin":location.origin},body:JSON.stringify({question})});
  target.replaceChildren();
  const answer=create("div",null,result.answer||"No answer returned.");target.append(answer);
  const meta=create("div","knowledge-meta","CONFIDENCE "+String(result.confidence||"low").toUpperCase()+" · "+(result.model||"LOCAL MODEL")+" · "+(result.evidence_ids||[]).length+" EVIDENCE IDS");meta.style.marginTop="9px";target.append(meta);
  if((result.evidence_ids||[]).length){const ids=create("div","knowledge-meta","EVIDENCE: "+result.evidence_ids.join(", "));ids.style.marginTop="5px";target.append(ids)}
  for(const ref of (result.references||[])){try{const url=new URL(ref.url);if(url.protocol==="https:"&&["learn.microsoft.com","github.com"].includes(url.hostname)){const link=create("a",null,ref.title||url.hostname);link.href=url.href;link.target="_blank";link.rel="noopener noreferrer";target.append(link)}}catch{}}
  $("askMeta").textContent="Answered locally · no remote inference or automatic remediation.";
 }catch(error){target.textContent="Ask Sentinel unavailable: "+error.message+" · Confirm Ollama is running and a 3B/4B model is already installed."}
 finally{button.disabled=false;button.textContent="✳  ASK LOCAL SENTINEL"}
}
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
$("eventCount").textContent=Number(s.event_count||0).toLocaleString();setBar("eventBar",Math.min(100,Number(s.event_count||0)/100));const providers=Object.values(s.provider_health||{});const bad=providers.filter(x=>x.state==="degraded").length;$("health").textContent=providers.length?(providers.length-bad)+"/"+providers.length:"—";$("healthFoot").textContent=bad?bad+" provider(s) degraded":"No active provider errors";setBar("healthBar",providers.length?(providers.length-bad)/providers.length*100:0);renderProviders(s);renderInternals(s);summaryData(s);renderDeepDiagnostics(s);renderHealthAlerts(s);renderAIInsights(s);if(s.last_command){const cmd=s.last_command;notifyCommand(String(cmd.action||'Command').replaceAll('_',' ').toUpperCase()+' · '+String(cmd.status||'queued').toUpperCase(),cmd.status==='started')}}
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
$("scanNowBtn").addEventListener("click",()=>runCommand("scan_now"));
$("aiNowBtn").addEventListener("click",()=>runCommand("ai_review_now"));
$("crawlNowBtn").addEventListener("click",()=>runCommand("knowledge_crawl_now"));
$("saveProfileBtn").addEventListener("click",saveProfile);
$("reloadProfileBtn").addEventListener("click",loadProfile);
$("askButton").addEventListener("click",askSentinel);
$("driverSearchBtn").addEventListener("click",searchDrivers);
$("driverQuery").addEventListener("keydown",event=>{if(event.key==="Enter")searchDrivers()});
$("askQuestion").addEventListener("keydown",event=>{if(event.key==="Enter"&&(event.ctrlKey||event.metaKey))askSentinel()});
$("knowledgeQuery").addEventListener("keydown",event=>{if(event.key==="Enter")searchKnowledge()});
$("clock").textContent=new Date().toLocaleTimeString();setInterval(()=>$("clock").textContent=new Date().toLocaleTimeString(),1000);setInterval(refresh,2500);loadProfile();window.addEventListener("resize",drawChart);refresh();
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
    command_queue: queue.Queue[str] | None = None,
    config_loader: Callable[[], dict[str, Any]] | None = None,
    config_saver: Callable[[dict[str, Any]], None] | None = None,
    inference_lock: Any = None,
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
            if parsed.path == "/api/config":
                try:
                    if config_loader is None:
                        raise RuntimeError("profile provider unavailable")
                    config = config_loader()
                    fields = (
                        "registry_enabled", "deep_inventory_enabled", "knowledge_enabled",
                        "ai_enabled", "registry_interval_seconds",
                        "deep_inventory_interval_seconds", "knowledge_interval_seconds",
                        "analysis_interval_seconds",
                    )
                    self._json(200, {"profile": {key: config[key] for key in fields}})
                except (OSError, RuntimeError, ValueError):
                    self._json(503, {"error": "Sentinel profile is unavailable"})
                return
            if parsed.path == "/api/drivers":
                try:
                    query = parse_qs(parsed.query).get("q", [""])[0].strip().casefold()[:100]
                    latest = next(
                        (
                            event for event in EventStore(db_path).recent(1000)
                            if event.event_type == "windows.deep_inventory"
                        ),
                        None,
                    )
                    if latest is None:
                        self._json(200, {"snapshot_at": None, "total": 0, "drivers": []})
                        return
                    raw_drivers = latest.data.get("signed_pnp_drivers", [])
                    drivers = []
                    driver_records = raw_drivers if isinstance(raw_drivers, list) else []
                    for item in driver_records:
                        if not isinstance(item, dict):
                            continue
                        device = str(item.get("DeviceName") or "Unknown device")[:140]
                        provider = str(item.get("DriverProviderName") or "Unknown provider")[:100]
                        version = str(item.get("DriverVersion") or "—")[:60]
                        if query and query not in " ".join((device, provider, version)).casefold():
                            continue
                        drivers.append({
                            "device": device,
                            "provider": provider,
                            "version": version,
                            "signed": item.get("IsSigned") if isinstance(item.get("IsSigned"), bool) else None,
                            "driver_date": str(item.get("DriverDate") or "—")[:32],
                        })
                    self._json(200, {
                        "snapshot_at": latest.timestamp.isoformat(),
                        "total": len(raw_drivers) if isinstance(raw_drivers, list) else 0,
                        "matched": len(drivers),
                        "drivers": drivers[:80],
                    })
                except (OSError, ValueError):
                    self._json(503, {"error": "Local driver inventory is unavailable"})
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
            path = urlparse(self.path).path
            if path not in {"/api/control", "/api/config", "/api/command", "/api/ask"}:
                self._json(404, {"error": "not found"})
                return
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError:
                length = 0
            if not 1 <= length <= 4096:
                self._json(400, {"error": "invalid request size"})
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self._json(400, {"error": "invalid JSON"})
                return
            if not isinstance(body, dict):
                self._json(400, {"error": "JSON object required"})
                return

            if path == "/api/config":
                values = body.get("values")
                if not isinstance(values, dict) or not values:
                    self._json(400, {"error": "profile values are required"})
                    return
                boolean_fields = {
                    "registry_enabled", "deep_inventory_enabled", "knowledge_enabled", "ai_enabled"
                }
                integer_ranges = {
                    "registry_interval_seconds": (60, 3600),
                    "deep_inventory_interval_seconds": (300, 7200),
                    "knowledge_interval_seconds": (3600, 604800),
                    "analysis_interval_seconds": (60, 3600),
                }
                if any(key not in boolean_fields and key not in integer_ranges for key in values):
                    self._json(400, {"error": "profile contains an unsupported setting"})
                    return
                for key, value in values.items():
                    if key in boolean_fields:
                        if not isinstance(value, bool):
                            self._json(400, {"error": "boolean setting has an invalid value"})
                            return
                    else:
                        minimum, maximum = integer_ranges[key]
                        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                            self._json(400, {"error": "interval is outside its supported range"})
                            return
                try:
                    if config_loader is None or config_saver is None:
                        raise RuntimeError("profile provider unavailable")
                    config = config_loader()
                    config.update(values)
                    config_saver(config)
                    fields = tuple(boolean_fields | set(integer_ranges))
                    self._json(200, {"saved": True, "profile": {key: config[key] for key in fields}})
                except (OSError, RuntimeError, ValueError):
                    self._json(503, {"error": "Unable to save the Sentinel profile"})
                return

            if path == "/api/command":
                action = body.get("action")
                allowed = {
                    "scan_now", "deep_scan_now", "registry_scan_now",
                    "ai_review_now", "knowledge_crawl_now",
                }
                if not isinstance(action, str) or action not in allowed or command_queue is None:
                    self._json(400, {"error": "unsupported command"})
                    return
                try:
                    command_queue.put_nowait(action)
                except queue.Full:
                    self._json(429, {"error": "Sentinel command queue is busy"})
                    return
                self._json(202, {"queued": action})
                return

            if path == "/api/ask":
                question = body.get("question")
                if not isinstance(question, str) or not question.strip() or len(question) > 500:
                    self._json(400, {"error": "question must contain 1-500 characters"})
                    return
                acquired = False
                try:
                    if inference_lock is not None:
                        acquired = inference_lock.acquire(blocking=False)
                        if not acquired:
                            self._json(409, {"error": "Local AI engine is busy with another inference."})
                            return
                    from aie.sentinel_ai import SentinelModelCollaborator
                    answer = SentinelModelCollaborator().ask(
                        question,
                        EventStore(db_path).recent(120),
                    )
                    self._json(200, answer)
                except Exception as exc:  # noqa: BLE001 - local inference errors stay within this request.
                    self._json(503, {"error": type(exc).__name__})
                finally:
                    if acquired and inference_lock is not None:
                        inference_lock.release()
                return

            action = body.get("action")
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
