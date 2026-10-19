"""Loopback-only Sentinel dashboard with a built-in, dependency-free web interface."""
from __future__ import annotations

import hmac
import json
import queue
import re
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
<title>AIE // SENTINEL TITAN</title>
<style>
:root{--void:#05080f;--deep:#09111c;--plate:#0d1927;--plate2:#122437;--plate3:#172d41;--line:#284256;--line2:#46647a;--ink:#e9f4fc;--soft:#adc2d2;--muted:#718a9e;--cyan:#70eaff;--blue:#4e9fd2;--ice:#b9f6ff;--red:#ff536d;--amber:#ffc16e;--green:#61e0b6;--danger:#ff6d7e;--radius:16px;--mono:"Cascadia Code",Consolas,monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--void);color:var(--ink);font:13px/1.5 "Segoe UI",Inter,system-ui,sans-serif;min-height:100vh;overflow-x:hidden}
button,input,select,textarea{font:inherit}button{cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}a{color:var(--cyan);text-decoration:none}
#starfield{position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:0;opacity:.24}
.ambient{position:fixed;inset:0;pointer-events:none;z-index:0;background:radial-gradient(ellipse at 76% 8%,#173b50 0,transparent 32%),radial-gradient(ellipse at 15% 74%,#401b2b45 0,transparent 30%),linear-gradient(145deg,#05080f,#091321 60%,#080d17)}
.ambient:before{content:"";position:absolute;inset:0;opacity:.12;background-image:linear-gradient(#5eb2d0 1px,transparent 1px),linear-gradient(90deg,#5eb2d0 1px,transparent 1px);background-size:52px 52px;mask-image:linear-gradient(to bottom,#000,transparent 86%)}
.ambient:after{content:"";position:absolute;inset:0;opacity:.05;background:repeating-linear-gradient(0deg,transparent 0 3px,#a8eaff 4px,transparent 5px);animation:scanline 16s linear infinite}
@keyframes scanline{to{transform:translateY(12px)}}
@keyframes pulse{50%{opacity:.32;filter:blur(1px)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes spinBack{to{transform:rotate(-360deg)}}
@keyframes flare{0%,100%{opacity:.6;transform:scale(.95)}50%{opacity:1;transform:scale(1.08)}}
@keyframes shimmer{0%{background-position:140% 0}100%{background-position:-100% 0}}
@keyframes rise{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
@keyframes bootSweep{from{transform:translateX(-110%)}to{transform:translateX(110%)}}
@keyframes glitch{0%,92%,100%{transform:translateX(0)}94%{transform:translateX(2px)}96%{transform:translateX(-2px)}}
.boot{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;background:radial-gradient(ellipse at 50% 42%,#16364a 0,#091320 42%,#04070d 80%);transition:opacity .8s ease,visibility .8s ease}
.boot.done{opacity:0;visibility:hidden;pointer-events:none}
.boot-grid{position:absolute;inset:0;opacity:.2;background-image:linear-gradient(#6ee8ff1b 1px,transparent 1px),linear-gradient(90deg,#6ee8ff1b 1px,transparent 1px);background-size:48px 48px;transform:perspective(500px) rotateX(58deg) scale(1.7);transform-origin:bottom}
.boot-card{width:min(600px,calc(100vw - 34px));position:relative;text-align:center;padding:32px 34px 28px;border:1px solid #4b7186;border-radius:20px;background:linear-gradient(145deg,#12283aeb,#09131ff2);box-shadow:0 30px 100px #000b,0 0 55px #4ddbf21b,inset 0 1px #efffff1b;overflow:hidden}
.boot-card:before{content:"";position:absolute;left:0;right:0;top:0;height:1px;background:linear-gradient(90deg,transparent,var(--cyan),var(--red),transparent)}
.boot-emblem{width:110px;height:110px;margin:0 auto 16px;position:relative;display:grid;place-items:center}
.boot-emblem:before,.boot-emblem:after{content:"";position:absolute;inset:1px;border:1px solid #6feaff80;border-radius:50%;border-left-color:transparent;border-right-color:transparent;animation:spin 7s linear infinite}
.boot-emblem:after{inset:-9px;border-color:#ff5a7160 transparent;animation:spinBack 11s linear infinite}
.boot-face{position:relative;width:62px;height:72px;clip-path:polygon(50% 0,88% 10%,100% 55%,75% 92%,50% 100%,25% 92%,0 55%,12% 10%);background:linear-gradient(145deg,#8cb1c4 0,#2c4e65 34%,#101d2e 72%);border:1px solid #91eaff;filter:drop-shadow(0 0 16px #70eaff88)}
.boot-face:before{content:"";position:absolute;left:13%;right:13%;top:26%;height:9px;background:linear-gradient(90deg,var(--red),#d4fbff 48%,var(--red));clip-path:polygon(0 0,100% 0,80% 100%,20% 100%);box-shadow:0 0 22px var(--cyan)}
.boot-face:after{content:"";position:absolute;left:29%;right:29%;bottom:9%;height:18px;border-left:2px solid #ff7182;border-right:2px solid #ff7182;background:#0c1723;clip-path:polygon(0 0,100% 0,72% 100%,28% 100%)}
.boot-title{font:800 23px/1.2 "Segoe UI",sans-serif;letter-spacing:.28em;text-shadow:0 0 24px #6ae7ff45}
.boot-sub{font:9px var(--mono);letter-spacing:.25em;color:#ff899a;margin-top:8px}
.boot-copy{color:#93afc4;font-size:11px;margin:20px 0 24px}
.boot-track{height:5px;background:#1b3245;border-radius:8px;overflow:hidden;position:relative}
.boot-progress{height:100%;width:0;background:linear-gradient(90deg,#367fb1,var(--cyan),#fff,var(--red));box-shadow:0 0 16px var(--cyan);transition:width .35s ease}
.boot-stage{display:flex;justify-content:space-between;gap:12px;margin-top:10px;color:#7998af;font:9px var(--mono);letter-spacing:.08em}
.boot-log{height:72px;overflow:hidden;text-align:left;border:1px solid #274258;border-radius:9px;background:#07111b;margin-top:20px;padding:9px 11px;color:#80c6df;font:9px/1.7 var(--mono)}
.boot-log div:before{content:"> ";color:var(--red)}
.boot-skip{border:0;background:transparent;color:#7897ae;font-size:9px;letter-spacing:.16em;margin-top:15px}
.app{position:relative;z-index:1;display:grid;grid-template-columns:86px minmax(0,1fr);min-height:100vh;opacity:0;transform:scale(.995);transition:opacity .65s ease,transform .65s ease}
.app.ready{opacity:1;transform:scale(1)}
.rail{position:sticky;top:0;height:100vh;display:flex;flex-direction:column;align-items:center;gap:11px;padding:17px 10px;border-right:1px solid #294155;background:linear-gradient(180deg,#08121ff2,#070d17f8);backdrop-filter:blur(18px);z-index:30}
.rail-brand{width:48px;height:48px;display:grid;place-items:center;border:1px solid #6bdcf0;border-radius:13px;background:linear-gradient(145deg,#27495d,#0c1928);box-shadow:0 0 28px #6de9ff25,inset 0 0 18px #f6ffff0c;margin-bottom:13px}
.brand-mini{width:22px;height:26px;position:relative;clip-path:polygon(50% 0,90% 12%,100% 72%,50% 100%,0 72%,10% 12%);background:linear-gradient(150deg,#b8d4e2,#345773 45%,#101b2a)}
.brand-mini:after{content:"";position:absolute;left:10%;right:10%;top:35%;height:4px;background:linear-gradient(90deg,var(--red),#dfffff,var(--red))}
.nav-btn{width:55px;height:53px;display:grid;place-items:center;gap:2px;border:1px solid transparent;border-radius:12px;background:transparent;color:#7693a8;transition:.22s;position:relative}
.nav-btn .nav-icon{font-size:19px;line-height:1}
.nav-btn small{font-size:7px;letter-spacing:.1em}
.nav-btn:hover{color:#d9f6ff;background:#13283a;border-color:#31556d;transform:translateY(-2px)}
.nav-btn.active{color:var(--ice);background:linear-gradient(145deg,#18384b,#102235);border-color:#5bd9ec;box-shadow:0 0 22px #5ce7ff1b,inset 0 0 20px #5ce7ff0c}
.nav-btn.active:before{content:"";position:absolute;left:-10px;top:13px;bottom:13px;width:3px;background:var(--cyan);box-shadow:0 0 12px var(--cyan)}
.rail-spacer{flex:1}
.rail-state{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 15px var(--green);animation:pulse 1.8s infinite}
.rail-bottom{color:#617f95;font:8px var(--mono);letter-spacing:.1em;writing-mode:vertical-rl;transform:rotate(180deg);margin:8px 0}
main{min-width:0;padding:18px clamp(14px,2.1vw,32px) 40px;max-width:1900px;width:100%;margin:auto}
.topbar{height:54px;display:flex;align-items:center;justify-content:space-between;gap:14px;padding:0 2px;margin-bottom:17px;border-bottom:1px solid #223c50}
.top-left{display:flex;align-items:center;gap:13px}.top-mark{height:27px;width:3px;background:linear-gradient(var(--cyan),var(--red));box-shadow:0 0 12px var(--cyan)}
.eyebrow{color:#7c9cb2;font:8px var(--mono);letter-spacing:.22em}.view-title{font-size:18px;font-weight:800;letter-spacing:.12em;margin-top:2px}
.top-right{display:flex;align-items:center;gap:13px}.clock{font:10px var(--mono);color:#9bb4c6}.system-badge{display:inline-flex;align-items:center;gap:8px;border:1px solid #2d6a5b;border-radius:30px;padding:6px 11px;background:#10271f;color:#80edc5;font:9px var(--mono);letter-spacing:.13em}.led{width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:0 0 10px currentColor;animation:pulse 1.7s infinite}
.icon-btn{border:1px solid #2a465c;background:#102033;color:#9bb9ce;border-radius:9px;padding:7px 10px;font-size:10px;transition:.2s}.icon-btn:hover{border-color:var(--cyan);color:white;background:#173149}
.screen{display:none;animation:rise .38s ease}.screen.active{display:block}
.section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin:5px 0 13px}
.section-label{color:var(--cyan);font:9px var(--mono);letter-spacing:.2em}.section-title{font-size:18px;letter-spacing:.08em;font-weight:800;margin-top:3px}.section-description{font-size:10px;color:var(--muted);max-width:540px}
.tag{font:8px var(--mono);letter-spacing:.1em;color:#9defff;border:1px solid #315a6e;background:#102a39;border-radius:30px;padding:5px 9px;white-space:nowrap}
.hero{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:20px;min-height:252px;border:1px solid #41647c;border-radius:18px;overflow:hidden;padding:25px 28px;background:linear-gradient(112deg,#162f42 0,#0d1d2d 55%,#191a2a);box-shadow:0 22px 70px #0008,inset 0 1px #dffaff17}
.hero:before{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(110deg,transparent 15%,#9cecff0b 43%,transparent 65%);background-size:220% 100%;animation:shimmer 12s linear infinite}
.hero:after{content:"";position:absolute;right:160px;top:-210px;width:520px;height:520px;border:1px solid #6beaff2c;border-radius:50%;box-shadow:0 0 0 40px #6beaff08,0 0 0 85px #ff627808,0 0 80px #5eeaff13;pointer-events:none}
.hero-copy{position:relative;z-index:1}.hero-kicker{font:9px var(--mono);letter-spacing:.25em;color:#ff8294}.hero h1{font-size:clamp(28px,4vw,48px);line-height:1.05;letter-spacing:.14em;margin:15px 0 9px;text-shadow:0 4px 26px #0008}.hero h1 span{color:#9aeeff;text-shadow:0 0 26px #60dfff77}.hero p{color:#9db5c8;font-size:11px;max-width:590px;margin:0 0 18px}
.hero-meta{display:flex;gap:25px;flex-wrap:wrap}.meta-item small{display:block;color:#6f90a7;font:7px var(--mono);letter-spacing:.16em}.meta-item b{display:block;color:#e1f3ff;font:10px var(--mono);margin-top:3px}
.hero-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}
.mecha-stage{position:relative;z-index:1;display:grid;place-items:center;min-height:200px}
.mecha-ring{position:absolute;width:210px;height:210px;border:1px solid #75eaff66;border-radius:50%;border-left-color:transparent;border-right-color:transparent;animation:spin 13s linear infinite;box-shadow:0 0 24px #5ceaff12}
.mecha-ring:before,.mecha-ring:after{content:"";position:absolute;inset:12px;border:1px dashed #ff667355;border-radius:50%;animation:spinBack 18s linear infinite}
.mecha-ring:after{inset:26px;border-style:solid;border-color:#8beeff2d transparent}
.mecha-head{width:145px;height:174px;position:relative;filter:drop-shadow(0 0 24px #60e7ff2b);animation:floatHead 5s ease-in-out infinite}
@keyframes floatHead{50%{transform:translateY(-5px)}}
.helmet{position:absolute;inset:7px 10px 5px;background:linear-gradient(135deg,#8baec0 0,#355a73 23%,#172d43 52%,#0c1828 100%);clip-path:polygon(50% 0,78% 5%,96% 18%,100% 65%,78% 91%,50% 100%,22% 91%,0 65%,4% 18%,22% 5%);border:1px solid #a9efff;box-shadow:inset 0 0 28px #d7f9ff1c}
.helmet:before{content:"";position:absolute;left:8%;right:8%;top:8%;height:20%;background:linear-gradient(90deg,#6b95aa,#d8f7ff,#38566a);clip-path:polygon(0 0,100% 0,86% 100%,14% 100%)}
.helmet:after{content:"";position:absolute;left:28%;right:28%;bottom:9%;height:24%;background:linear-gradient(90deg,#101c2a,#7a9eae,#101c2a);clip-path:polygon(0 0,100% 0,70% 100%,30% 100%)}
.helmet-side{position:absolute;top:50px;width:24px;height:66px;background:linear-gradient(90deg,#233f56,#8caebc,#172d43);border:1px solid #6fdff1;clip-path:polygon(25% 0,100% 10%,84% 100%,0 85%)}
.helmet-side.left{left:1px}.helmet-side.right{right:1px;transform:scaleX(-1)}
.helmet-eye{position:absolute;z-index:2;top:60px;width:39px;height:13px;background:linear-gradient(90deg,#ff536d,#d9fcff,#68eaff);clip-path:polygon(0 0,100% 12%,78% 100%,12% 75%);box-shadow:0 0 22px #7feeff;animation:flare 2.8s ease-in-out infinite}
.helmet-eye.left{left:30px}.helmet-eye.right{right:30px}
.helmet-mask{position:absolute;z-index:3;left:49px;top:80px;width:47px;height:49px;background:linear-gradient(145deg,#6a8ca0,#14263a);clip-path:polygon(0 0,100% 0,85% 78%,50% 100%,15% 78%);border:1px solid #a7e9f8}
.helmet-mask:before{content:"";position:absolute;left:44%;top:5px;width:6px;height:28px;background:linear-gradient(var(--red),#0b1522);box-shadow:0 0 8px #ff5a72}
.btn{border:1px solid #3c5c73;border-radius:9px;background:linear-gradient(145deg,#1a3549,#102235);color:#dcedf8;padding:8px 12px;font-size:9px;font-weight:750;letter-spacing:.08em;box-shadow:inset 0 1px #efffff14,0 4px 14px #0004;transition:.2s}
.btn:hover{transform:translateY(-2px);border-color:var(--cyan);box-shadow:0 7px 20px #52def51c,inset 0 1px #fff2}.btn.primary{background:linear-gradient(115deg,#126e83,#1a4d70 65%,#633347);border-color:#5ddbf0;box-shadow:0 0 23px #5edff329}.btn.danger{color:#ffacb7;border-color:#864555;background:linear-gradient(120deg,#3b1b2a,#211520)}.btn.ghost{background:transparent;border-color:#365168;color:#a8c1d2}.btn:disabled{opacity:.38;cursor:not-allowed;transform:none}
.btn.active{border-color:var(--cyan);color:var(--ice);background:linear-gradient(120deg,#17445a,#172d40);box-shadow:0 0 14px #61dff51d}
.metric-row{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:13px 0}
.metric{position:relative;border:1px solid #29475e;border-radius:13px;background:linear-gradient(145deg,#14283b,#0a1623);padding:13px 14px;min-width:0;overflow:hidden;box-shadow:0 9px 28px #0003,inset 0 1px #fff1;transition:.2s}
.metric:hover{border-color:#63dced;transform:translateY(-3px)}.metric:after{content:"";position:absolute;right:-30px;top:-30px;width:80px;height:80px;border:1px solid #6feaff18;border-radius:50%;box-shadow:0 0 0 14px #6feaff08}
.metric-label{color:#819eb2;font:8px var(--mono);letter-spacing:.15em}.metric-value{font:23px var(--mono);margin:6px 0 2px;white-space:nowrap;text-shadow:0 0 16px #6feaff16}.metric-foot{font-size:8px;color:#718b9f}.meter{height:3px;background:#20394c;border-radius:8px;margin-top:9px;overflow:hidden}.meter i{display:block;height:100%;width:0;background:linear-gradient(90deg,#4587ba,#70eaff,#f2ffff);box-shadow:0 0 11px var(--cyan);transition:width .6s ease}
.grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(280px,.8fr);gap:12px}.grid.equal{grid-template-columns:repeat(2,minmax(0,1fr))}.grid.triple{grid-template-columns:repeat(3,minmax(0,1fr))}
.panel{position:relative;border:1px solid #294459;border-radius:15px;background:linear-gradient(145deg,#122437ed,#0a1521f5);padding:15px;min-width:0;box-shadow:0 12px 34px #0004,inset 0 1px #eaffff0a;overflow:hidden;transition:border-color .2s,transform .2s}
.panel:before{content:"";position:absolute;top:0;left:15px;right:15px;height:1px;background:linear-gradient(90deg,transparent,#7feaff7c,#ff6b7a50,transparent)}
.panel:hover{border-color:#456d86}.panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:13px}.panel-title{font-size:10px;font-weight:800;letter-spacing:.15em}.panel-sub{font-size:9px;color:#819db1;margin-top:4px}
.chart-wrap{height:190px;position:relative}.chart-wrap canvas{width:100%;height:100%}.legend{display:flex;gap:15px;flex-wrap:wrap;color:#89a5b8;font:8px var(--mono);margin-top:9px}.legend i{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;background:var(--cyan)}.legend i.red{background:var(--red)}
.sensor-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.sensor{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:9px 10px;border:1px solid #263f53;border-radius:10px;background:#0a1724}.sensor strong{display:block;font-size:9px}.sensor small{display:block;color:#7793a8;font-size:8px;margin-top:3px}.sensor-state{font:8px var(--mono);color:var(--green)}.sensor-state.degraded,.sensor-state.partial{color:var(--amber)}.sensor-state.disabled,.sensor-state.optional{color:#718a9e}
.alert-list,.event-list,.driver-list,.result-list,.audit-list,.insight-list{display:grid;gap:7px}
.alert-card{border:1px solid #344d61;border-left:3px solid var(--amber);border-radius:10px;padding:10px;background:linear-gradient(100deg,#172638,#0a1724)}
.alert-card.critical{border-left-color:var(--red)}.alert-card.info{border-left-color:var(--cyan)}.alert-card.medium{border-left-color:#d4a76c}
.alert-row{display:flex;align-items:center;justify-content:space-between;gap:8px}.alert-row strong{font-size:9px}.alert-sev{color:var(--amber);font:8px var(--mono);letter-spacing:.1em}.alert-card.critical .alert-sev{color:var(--red)}.alert-card p{font-size:9px;color:#91aabd;margin:6px 0 0}
.event{display:grid;grid-template-columns:32px minmax(0,1fr) auto;gap:9px;align-items:start;padding:9px 10px;border:1px solid #243d51;border-radius:10px;background:#0a1622;transition:.18s}
.event:hover{border-color:#52809b;background:#102238}.event-icon{width:30px;height:30px;display:grid;place-items:center;border-radius:8px;background:#153044;color:var(--cyan);font-size:12px}.event-name{font-size:9px;font-weight:800;overflow-wrap:anywhere}.event-desc{font-size:8px;color:#8ba4b7;margin-top:3px;overflow-wrap:anywhere}.event-time{font:8px var(--mono);color:#748da1;white-space:nowrap}.event details{margin-top:5px;color:#7192a8;font-size:8px}.event summary{cursor:pointer;letter-spacing:.1em}.event pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto;background:#050d17;border:1px solid #294357;padding:8px;border-radius:8px;color:#a9c4d5;font:8px/1.5 var(--mono)}
.scroll-list{max-height:440px;overflow:auto;padding-right:3px}.empty{border:1px dashed #345268;border-radius:10px;padding:18px;text-align:center;color:#7e98ab;font-size:9px}
.search-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px;margin-bottom:10px}.field,.select,.textarea{width:100%;min-width:0;border:1px solid #304e64;border-radius:9px;background:#07131f;color:#e7f4fc;padding:9px 10px;font:10px "Segoe UI",sans-serif}.textarea{min-height:96px;resize:vertical;line-height:1.55}.field:focus,.select:focus,.textarea:focus{border-color:var(--cyan)}
.system-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.info-card{border:1px solid #29475b;border-radius:11px;padding:11px;background:linear-gradient(135deg,#112538,#091622)}.info-card small{display:block;color:#7c99ae;font:8px var(--mono);letter-spacing:.12em}.info-card strong{display:block;font-size:11px;margin-top:5px;overflow-wrap:anywhere}.info-card p{color:#8ba5b8;font-size:8px;margin:4px 0 0;overflow-wrap:anywhere}
.disk-item{border:1px solid #294257;background:#0a1723;padding:9px;border-radius:9px}.disk-top{display:flex;justify-content:space-between;gap:8px}.disk-top strong{font-size:9px}.disk-top small{font:8px var(--mono);color:#8ca9bd}.disk-meter{height:5px;background:#243b4d;border-radius:8px;margin-top:8px;overflow:hidden}.disk-meter i{display:block;height:100%;background:linear-gradient(90deg,#4187b4,#70eaff,#ff6d83)}
.driver-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:9px;padding:8px;border:1px solid #294256;border-radius:8px;background:#0a1723;align-items:center}.driver-row strong{display:block;font-size:8px;overflow-wrap:anywhere}.driver-row small{display:block;color:#829db0;font-size:8px;margin-top:2px}.driver-state{font:8px var(--mono);color:var(--green)}.driver-state.unsigned{color:var(--red)}
.status-pills{display:flex;flex-wrap:wrap;gap:6px}.pill{border:1px solid #36556b;border-radius:30px;padding:5px 8px;font-size:8px;color:#adcad9;background:#102438}.pill.warn{color:#ffce86;border-color:#795936}.pill.bad{color:#ffabb9;border-color:#814454}.pill.good{color:#8bf0ce;border-color:#316b59}
.ai-shell{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(280px,.75fr);gap:12px}.ai-answer{border:1px solid #31546d;background:linear-gradient(140deg,#13283b,#0a1724);border-radius:12px;padding:14px;min-height:110px;font-size:10px;line-height:1.65;color:#c8dce9;white-space:pre-wrap;overflow-wrap:anywhere}.ai-reference{display:block;color:var(--cyan);font-size:8px;overflow-wrap:anywhere;margin-top:5px}
.model-card{padding:11px;border:1px solid #2a475d;border-radius:10px;background:#0c1b2a}.model-card strong{display:block;font-size:9px}.model-card small{display:block;color:#809cb0;font-size:8px;margin-top:3px}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.toggle{display:flex;gap:9px;align-items:flex-start;border:1px solid #2b465b;border-radius:10px;padding:10px;background:#0a1724}.toggle input{accent-color:#70eaff;margin-top:2px}.toggle strong{display:block;font-size:9px}.toggle small{display:block;color:#819db0;font-size:8px;margin-top:3px;line-height:1.5}
.interval-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:12px 0}.interval label{display:block;color:#8ca7bb;font:8px var(--mono);margin-bottom:5px}.interval input{width:100%;min-width:0;border:1px solid #304a5f;border-radius:8px;padding:8px;background:#07131e;color:#e7f4fc;font:10px var(--mono)}
.action-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.action-tile{border:1px solid #315168;background:linear-gradient(145deg,#142c40,#0a1725);color:#d5eaf7;border-radius:10px;padding:13px;text-align:left;transition:.2s}.action-tile:hover{transform:translateY(-2px);border-color:var(--cyan);box-shadow:0 0 18px #60e9ff17}.action-tile b{display:block;font-size:9px;letter-spacing:.07em}.action-tile small{display:block;margin-top:5px;color:#819db1;font-size:8px;line-height:1.45}
.command-line{display:flex;justify-content:space-between;align-items:center;gap:9px;border-bottom:1px solid #233c50;padding:8px 2px}.command-line strong{font-size:8px}.command-line small{color:#819cb0;font:8px var(--mono)}
.knowledge-card{border:1px solid #2b465b;border-radius:10px;padding:10px;background:#0a1723}.knowledge-card strong{display:block;font-size:9px}.knowledge-card p{color:#8da7b9;font-size:8px;line-height:1.5;margin:5px 0}.knowledge-card small{font:8px var(--mono);color:#7191a6}
.note{font-size:8px;color:#7894a9;line-height:1.6;margin-top:10px}.button-row{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.statline{display:flex;gap:10px;align-items:center}.statline strong{font:10px var(--mono)}.statline span{font-size:8px;color:#829caf}
.toast-stack{position:fixed;right:18px;bottom:18px;z-index:200;display:grid;gap:8px;width:min(350px,calc(100vw - 36px))}.toast{border:1px solid #41647b;border-left:3px solid var(--cyan);border-radius:10px;background:#0d1d2cf2;box-shadow:0 12px 35px #0008;padding:11px 13px;color:#dff2fb;font-size:9px;animation:rise .2s ease}.toast.error{border-left-color:var(--red)}.toast.warn{border-left-color:var(--amber)}
@media(max-width:1200px){.metric-row{grid-template-columns:repeat(3,minmax(0,1fr))}.grid.triple{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:900px){.hero{grid-template-columns:1fr}.mecha-stage{display:none}.grid,.grid.equal,.ai-shell{grid-template-columns:1fr}.interval-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.action-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:650px){.app{grid-template-columns:1fr}.rail{position:fixed;bottom:0;top:auto;left:0;right:0;width:100%;height:65px;flex-direction:row;justify-content:space-around;padding:5px 7px;border-right:0;border-top:1px solid #315067}.rail-brand,.rail-spacer,.rail-state,.rail-bottom{display:none}.nav-btn{width:12.5%;height:48px}.nav-btn small{font-size:6px}.nav-btn .nav-icon{font-size:16px}main{padding:14px 10px 84px}.topbar{height:auto;padding:4px 1px 12px}.clock{display:none}.view-title{font-size:15px}.hero{padding:19px;min-height:0}.hero h1{font-size:29px}.metric-row{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.metric{padding:10px}.metric-value{font-size:19px}.system-cards{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.action-grid{grid-template-columns:1fr 1fr}.section-description{display:none}.event{grid-template-columns:29px minmax(0,1fr)}.event-time{grid-column:2}.driver-row{grid-template-columns:minmax(0,1fr) auto}.driver-row small:last-child{display:none}.boot-card{padding:25px 18px}.boot-title{font-size:20px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;scroll-behavior:auto!important;transition:none!important}}
</style>
</head>
<body>
<div class="ambient"></div><canvas id="starfield"></canvas>
<div class="boot" id="boot">
 <div class="boot-grid"></div>
 <div class="boot-card">
  <div class="boot-emblem"><div class="boot-face"></div></div>
  <div class="boot-title">A I E // SENTINEL</div>
  <div class="boot-sub">TITAN SYSTEM INITIALIZATION</div>
  <div class="boot-copy">Establishing local command link · Mounting evidence vault · Bringing Windows perception online</div>
  <div class="boot-track"><div class="boot-progress" id="bootProgress"></div></div>
  <div class="boot-stage"><span id="bootStage">INITIALIZING CORE</span><b id="bootPercent">00%</b></div>
  <div class="boot-log" id="bootLog"><div>Sentinel interface loader ready</div></div>
  <button class="boot-skip" id="bootSkip">ENTER COMMAND DECK &gt;&gt;</button>
 </div>
</div>
<div class="app" id="app">
 <aside class="rail">
  <div class="rail-brand"><div class="brand-mini"></div></div>
  <button class="nav-btn active" data-view="cockpit" title="Command Center"><span class="nav-icon">◈</span><small>CORE</small></button>
  <button class="nav-btn" data-view="system" title="System Intelligence"><span class="nav-icon">⌖</span><small>SYSTEM</small></button>
  <button class="nav-btn" data-view="telemetry" title="Telemetry"><span class="nav-icon">⌁</span><small>FLOW</small></button>
  <button class="nav-btn" data-view="evidence" title="Evidence Vault"><span class="nav-icon">▤</span><small>VAULT</small></button>
  <button class="nav-btn" data-view="ai" title="AI Laboratory"><span class="nav-icon">✳</span><small>AI LAB</small></button>
  <button class="nav-btn" data-view="autonomy" title="Automation"><span class="nav-icon">⚙</span><small>AUTO</small></button>
  <button class="nav-btn" data-view="knowledge" title="Knowledge"><span class="nav-icon">⌘</span><small>CODEX</small></button>
  <div class="rail-spacer"></div><div class="rail-state" id="railLed"></div><div class="rail-bottom">WINDOWS // LOCAL-FIRST</div>
 </aside>
 <main>
  <header class="topbar">
   <div class="top-left"><div class="top-mark"></div><div><div class="eyebrow">AUTONOMOUS INTELLIGENCE ECOSYSTEM / TITAN DIVISION</div><div class="view-title" id="viewTitle">COMMAND CENTER</div></div></div>
   <div class="top-right"><span class="clock" id="clock">--:--:--</span><button class="icon-btn" id="notifyBtn">◉ ALERTS</button><button class="icon-btn" id="refreshBtn">↻ SYNC</button><button class="icon-btn" id="stopBtn" style="border-color:#824454;color:#ff9eae">■ STOP</button><span class="system-badge" id="liveBadge"><i class="led"></i>CONNECTING</span></div>
  </header>

  <section class="screen active" data-screen="cockpit">
   <div class="hero">
    <div class="hero-copy">
     <div class="hero-kicker">SENTINEL / PERCEPTION CORE / CONTINUOUS WATCH</div>
     <h1>THE SYSTEM<br><span>IS AWAKE.</span></h1>
     <p id="heroDesc">A live Windows intelligence layer. Sensors observe, the knowledge vault contextualizes and local AI reviews evidence. All remediation remains under your control.</p>
     <div class="hero-meta">
      <div class="meta-item"><small>WORKER PID</small><b id="pid">—</b></div>
      <div class="meta-item"><small>UPTIME</small><b id="uptime">—</b></div>
      <div class="meta-item"><small>HEARTBEAT</small><b id="heartbeat">—</b></div>
      <div class="meta-item"><small>WINDOWS BUILD</small><b id="heroBuild">—</b></div>
     </div>
     <div class="hero-actions">
      <button class="btn primary" data-command="scan_now">◈ FULL SYSTEM SWEEP</button>
      <button class="btn" data-command="ai_review_now">✳ THINK / REVIEW</button>
      <button class="btn danger" id="pauseBtn">Ⅱ PAUSE WATCH</button>
      <button class="btn ghost" id="resumeBtn">▶ RESUME</button>
     </div>
    </div>
    <div class="mecha-stage"><div class="mecha-ring"></div><div class="mecha-head"><div class="helmet"></div><div class="helmet-side left"></div><div class="helmet-side right"></div><div class="helmet-eye left"></div><div class="helmet-eye right"></div><div class="helmet-mask"></div></div></div>
   </div>
   <div class="metric-row">
    <div class="metric"><div class="metric-label">CPU LOAD</div><div class="metric-value" id="cpuValue">—%</div><div class="metric-foot">Host processor · live sample</div><div class="meter"><i id="cpuMeter"></i></div></div>
    <div class="metric"><div class="metric-label">MEMORY AVAILABLE</div><div class="metric-value" id="ramValue">— GB</div><div class="metric-foot" id="ramSub">System RAM headroom</div><div class="meter"><i id="ramMeter"></i></div></div>
    <div class="metric"><div class="metric-label">EVIDENCE RECORDS</div><div class="metric-value" id="eventValue">—</div><div class="metric-foot">Local SQLite event vault</div><div class="meter"><i id="eventMeter"></i></div></div>
    <div class="metric"><div class="metric-label">SENSOR MATRIX</div><div class="metric-value" id="sensorValue">—</div><div class="metric-foot" id="sensorSub">Provider availability</div><div class="meter"><i id="sensorMeter"></i></div></div>
    <div class="metric"><div class="metric-label">POSTURE SIGNALS</div><div class="metric-value" id="alertValue">—</div><div class="metric-foot" id="alertSub">Awaiting deep inventory</div><div class="meter"><i id="alertMeter"></i></div></div>
   </div>
   <div class="grid">
    <section class="panel">
     <div class="panel-head"><div><div class="panel-title">LIVE RESOURCE SIGNATURE</div><div class="panel-sub">CPU / RAM waveform · real local samples · 3-second refresh</div></div><span class="tag">HOST TELEMETRY</span></div>
     <div class="chart-wrap"><canvas id="mainChart" width="1100" height="300"></canvas></div>
     <div class="legend"><span><i></i>CPU LOAD</span><span><i class="red"></i>MEMORY USED</span></div>
    </section>
    <section class="panel">
     <div class="panel-head"><div><div class="panel-title">AUTONOMY PULSE</div><div class="panel-sub">Background intelligence subsystems</div></div><span class="tag">LIVE STATE</span></div>
     <div class="sensor-grid" id="sensorGrid"><div class="empty">Waiting for collector heartbeat.</div></div>
     <div class="button-row" style="margin-top:12px"><button class="btn" data-view-jump="autonomy">OPEN AUTONOMY DECK →</button><button class="btn ghost" id="notifyEnable">ENABLE DESKTOP ALERTS</button></div>
    </section>
   </div>
   <div class="grid equal" style="margin-top:12px">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">THREAT / HEALTH WATCHTOWER</div><div class="panel-sub">Rule-based Windows signals, not model speculation</div></div><button class="btn ghost" data-view-jump="system">DETAILS →</button></div><div class="alert-list" id="cockpitAlerts"><div class="empty">No posture snapshot yet.</div></div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">RECENT ACTIVITY</div><div class="panel-sub">Latest persisted evidence and command audit events</div></div><button class="btn ghost" data-view-jump="evidence">OPEN EVIDENCE VAULT →</button></div><div class="event-list" id="cockpitEvents"><div class="empty">No events loaded.</div></div></section>
   </div>
  </section>

  <section class="screen" data-screen="system">
   <div class="section-head"><div><div class="section-label">WINDOWS INTERNALS / HARDWARE INTELLIGENCE</div><div class="section-title">SYSTEM DEEP DIVE</div><div class="section-description">CIM inventory, firmware, physical storage, BitLocker, Defender, firewall, signed drivers and PnP state.</div></div><button class="btn primary" data-command="deep_scan_now">⟲ REFRESH DEEP SNAPSHOT</button></div>
   <div class="metric-row" id="systemMetrics">
    <div class="metric"><div class="metric-label">PROCESS CATALOG</div><div class="metric-value" id="metricProcesses">—</div><div class="metric-foot">Last inventory snapshot</div></div>
    <div class="metric"><div class="metric-label">INSTALLED APPS</div><div class="metric-value" id="metricApps">—</div><div class="metric-foot">Registry inventory</div></div>
    <div class="metric"><div class="metric-label">SYSTEM DRIVERS</div><div class="metric-value" id="metricDrivers">—</div><div class="metric-foot">Win32_SystemDriver records</div></div>
    <div class="metric"><div class="metric-label">SIGNED PNP</div><div class="metric-value" id="metricPnp">—</div><div class="metric-foot">Present device inventory</div></div>
    <div class="metric"><div class="metric-label">PHYSICAL DISKS</div><div class="metric-value" id="metricPhysical">—</div><div class="metric-foot">Storage provider view</div></div>
   </div>
   <div class="grid equal">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">PLATFORM / FIRMWARE</div><div class="panel-sub">OS, CPU, BIOS and boot integrity</div></div><span class="tag">CIM</span></div><div class="system-cards" id="platformCards"><div class="empty">Waiting for a deep snapshot.</div></div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">SECURITY POSTURE</div><div class="panel-sub">Defender, firewall, Secure Boot, BitLocker</div></div><span class="tag">WINDOWS SECURITY</span></div><div class="result-list" id="securityDetails"><div class="empty">Waiting for security metadata.</div></div></section>
   </div>
   <div class="grid equal" style="margin-top:12px">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">VOLUME / PHYSICAL STORAGE</div><div class="panel-sub">Capacity, free space and reported health</div></div></div><div class="result-list" id="diskDetails"><div class="empty">Waiting for storage inventory.</div></div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">BITLOCKER / BATTERY</div><div class="panel-sub">Encryption status and battery telemetry where available</div></div></div><div class="result-list" id="encryptionBattery"><div class="empty">Waiting for device metadata.</div></div></section>
   </div>
   <section class="panel" style="margin-top:12px"><div class="panel-head"><div><div class="panel-title">SIGNED DRIVER INTELLIGENCE</div><div class="panel-sub">Search the last local PnP driver snapshot; this is inventory, not a compatibility verdict.</div></div><span class="tag" id="driverCount">NO SNAPSHOT</span></div><div class="search-row"><input class="field" id="driverQuery" maxlength="100" placeholder="Search device name, provider or version…"><button class="btn" id="driverSearch">FILTER DRIVERS</button></div><div class="driver-list scroll-list" id="driverResults"><div class="empty">Run a deep system scan to populate the driver explorer.</div></div></section>
   <section class="panel" style="margin-top:12px"><div class="panel-head"><div><div class="panel-title">SYSTEM INVENTORY EXPLORER</div><div class="panel-sub">Bounded local records · process, application, service, task and interface catalogs</div></div><span class="tag" id="catalogSnapshot">NO SNAPSHOT</span></div>
    <div class="button-row" style="margin-bottom:10px" id="catalogKinds">
     <button class="btn active" data-catalog="processes">PROCESSES</button><button class="btn" data-catalog="applications">APPLICATIONS</button><button class="btn" data-catalog="services">SERVICES</button><button class="btn" data-catalog="tasks">SCHEDULED TASKS</button><button class="btn" data-catalog="interfaces">INTERFACES</button>
    </div>
    <div class="search-row"><input class="field" id="catalogQuery" maxlength="100" placeholder="Filter this inventory catalog…"><button class="btn" id="catalogSearch">SEARCH</button></div>
    <div class="panel-sub" id="catalogMeta">Select a catalog to inspect the latest inventory snapshot.</div>
    <div class="result-list scroll-list" id="catalogResults" style="margin-top:9px"><div class="empty">No inventory catalog loaded yet.</div></div>
   </section>
  </section>

  <section class="screen" data-screen="telemetry">
   <div class="section-head"><div><div class="section-label">LIVE PROVIDER INTELLIGENCE</div><div class="section-title">TELEMETRY & SENSOR MATRIX</div><div class="section-description">Live host performance history, provider health, collection timing and internal sensor snapshots.</div></div><span class="tag" id="telemetryFreshness">WAITING FOR SAMPLE</span></div>
   <div class="grid equal">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">RESOURCE HISTORY</div><div class="panel-sub">Recent local CPU and memory samples</div></div></div><div class="chart-wrap" style="height:260px"><canvas id="telemetryChart" width="1000" height="330"></canvas></div><div class="legend"><span><i></i>CPU</span><span><i class="red"></i>RAM USED</span></div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">COLLECTOR HEALTH</div><div class="panel-sub">Successes, samples, latency and reported state</div></div></div><div class="result-list" id="providerDetails"><div class="empty">Provider status pending.</div></div></section>
   </div>
   <div class="grid equal" style="margin-top:12px">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">WINDOWS INTERNAL WATCHERS</div><div class="panel-sub">Registry, CIM, ETW and Microsoft knowledge</div></div></div><div class="result-list" id="internalWatchers"><div class="empty">Waiting for watcher state.</div></div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">RUNTIME PROFILE</div><div class="panel-sub">Host hardware and Sentinel worker resource envelope</div></div></div><div class="system-cards" id="runtimeProfile"><div class="empty">Waiting for host runtime profile.</div></div></section>
   </div>
  </section>

  <section class="screen" data-screen="evidence">
   <div class="section-head"><div><div class="section-label">LOCAL SQLITE / AUDIT TRAIL</div><div class="section-title">EVIDENCE VAULT</div><div class="section-description">Inspect collected events, system snapshots, automation triggers and manual command dispatch records.</div></div><span class="tag" id="vaultCount">0 RECORDS</span></div>
   <section class="panel"><div class="search-row"><input class="field" id="eventQuery" maxlength="120" placeholder="Search event name, source, entity or safe metadata…"><select class="select" id="eventTypeFilter" style="max-width:210px"><option value="">ALL EVENT TYPES</option><option value="registry">REGISTRY</option><option value="process">PROCESS</option><option value="network">NETWORK</option><option value="inventory">INVENTORY</option><option value="command">COMMANDS</option><option value="automation">AUTOMATION</option><option value="model">AI ASSESSMENTS</option><option value="deep">DEEP INVENTORY</option></select></div><div class="button-row" style="margin-bottom:10px"><button class="btn" id="eventSearch">SEARCH VAULT</button><button class="btn ghost" id="eventRefresh">REFRESH EVENTS</button><span class="panel-sub" id="eventMeta">Filtered locally from the recent event window.</span></div><div class="event-list scroll-list" id="eventList"><div class="empty">Loading event vault…</div></div></section>
  </section>

  <section class="screen" data-screen="ai">
   <div class="section-head"><div><div class="section-label">LOCAL MODEL ORCHESTRATION</div><div class="section-title">SENTINEL AI LAB</div><div class="section-description">Ask specialist questions, inspect installed Ollama models, launch evidence reviews and read the latest AI findings.</div></div><button class="btn primary" data-command="ai_review_now">✳ RUN EVIDENCE REVIEW</button></div>
   <div class="ai-shell">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">ASK SENTINEL / SPECIALIST MODE</div><div class="panel-sub">Local 3B/4B model · evidence packet · local Microsoft knowledge references</div></div><span class="tag">NO CLOUD FALLBACK</span></div>
     <div class="form-grid"><div><label class="panel-sub" for="aiMode">DIAGNOSTIC SPECIALIST</label><select class="select" id="aiMode"><option value="general">General Windows analyst</option><option value="security">Security & protection analyst</option><option value="performance">Performance engineer</option><option value="drivers">Drivers & Plug-and-Play</option><option value="storage">Storage & battery specialist</option><option value="network">Network diagnostician</option></select></div><div><label class="panel-sub" for="aiQuestion">PROMPT</label><input class="field" id="aiQuestion" maxlength="500" placeholder="What should Sentinel investigate?"></div></div>
     <div class="button-row" style="margin-top:10px"><button class="btn primary" id="askBtn">✳ ASK LOCAL AI</button><span class="panel-sub" id="aiRequestState">Inference shares one memory lock with scheduled AI analysis.</span></div>
     <div class="ai-answer" id="aiAnswer" style="margin-top:12px">Select a specialist and ask a question about your machine's observed metadata.</div>
     <div id="aiReferences" class="result-list" style="margin-top:9px"></div>
    </section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">LOCAL MODEL INVENTORY</div><div class="panel-sub">Installed models only · discovered from local Ollama</div></div><button class="btn ghost" id="modelRefresh">↻ DISCOVER</button></div><div class="result-list" id="modelList"><div class="empty">Discovering installed Ollama models…</div></div><div class="note" id="modelMemory">RAM profile unavailable.</div></section>
   </div>
   <div class="grid equal" style="margin-top:12px">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">FAST TRIAGE / SIGNALS</div><div class="panel-sub" id="triageModel">Awaiting local analysis</div></div><span class="tag" id="triageState">IDLE</span></div><div class="ai-answer" id="triageResult">No assessment stored.</div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">INDEPENDENT REVIEW</div><div class="panel-sub" id="reviewModel">Awaiting reviewer</div></div><span class="tag" id="reviewState">IDLE</span></div><div class="ai-answer" id="reviewResult">No reviewer assessment stored.</div></section>
   </div>
  </section>

  <section class="screen" data-screen="autonomy">
   <div class="section-head"><div><div class="section-label">POLICY / SCHEDULE / AUTOMATION</div><div class="section-title">AUTONOMY CONTROL DECK</div><div class="section-description">Configure background collection and evidence-triggered AI reviews. All automatic intelligence remains advisory.</div></div><span class="tag">LOCAL CONFIG</span></div>
   <div class="grid">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">AUTOMATED SENSOR PROFILE</div><div class="panel-sub">Saved locally and applied by the Sentinel worker</div></div><span class="tag">PROFILE / v2</span></div>
     <div class="form-grid">
      <label class="toggle"><input type="checkbox" id="cfgRegistry"><span><strong>Registry intelligence</strong><small>Read-only key snapshots, autorun-name changes and service metadata</small></span></label>
      <label class="toggle"><input type="checkbox" id="cfgDeep"><span><strong>Deep Windows inventory</strong><small>Drivers, devices, disks, Defender, firewall, BitLocker and firmware</small></span></label>
      <label class="toggle"><input type="checkbox" id="cfgKnowledge"><span><strong>Microsoft knowledge crawler</strong><small>Learn and approved Microsoft GitHub sources, indexed locally</small></span></label>
      <label class="toggle"><input type="checkbox" id="cfgAI"><span><strong>Scheduled local AI review</strong><small>Local 4B triage and optional independent 6B reviewer</small></span></label>
      <label class="toggle"><input type="checkbox" id="cfgPostureReview"><span><strong>Auto-review posture findings</strong><small>Queue local AI review when a new high/critical system finding appears</small></span></label>
      <label class="toggle"><input type="checkbox" id="cfgRegistryReview"><span><strong>Review registry changes</strong><small>Queue local AI review after a configuration-change event</small></span></label>
     </div>
     <div class="interval-grid">
      <div class="interval"><label>REGISTRY / SEC</label><input id="cfgRegistryInterval" type="number" min="60" max="3600" step="30"></div>
      <div class="interval"><label>DEEP SCAN / SEC</label><input id="cfgDeepInterval" type="number" min="300" max="7200" step="60"></div>
      <div class="interval"><label>KNOWLEDGE / SEC</label><input id="cfgKnowledgeInterval" type="number" min="3600" max="604800" step="1800"></div>
      <div class="interval"><label>AI REVIEW / SEC</label><input id="cfgAIInterval" type="number" min="60" max="3600" step="30"></div>
      <div class="interval"><label>LOW DISK / FREE %</label><input id="cfgDiskThreshold" type="number" min="1" max="30"></div>
      <div class="interval"><label>LOW BATTERY / %</label><input id="cfgBatteryThreshold" type="number" min="5" max="40"></div>
     </div>
     <div class="panel-head" style="margin-top:15px"><div><div class="panel-title">ADVANCED WINDOWS SENSORS</div><div class="panel-sub">Explicit opt-in collection · stored for the next worker restart</div></div><span class="tag">RESTART REQUIRED</span></div>
     <div class="form-grid">
      <label class="toggle"><input type="checkbox" id="cfgEventLogs"><span><strong>Application / System Event Log</strong><small>Metadata only; no message text, XML or Security log.</small></span></label>
      <label class="toggle"><input type="checkbox" id="cfgEtw"><span><strong>ETW process lifecycle</strong><small>Process lifecycle provider only; elevation may be required.</small></span></label>
      <label class="toggle"><input type="checkbox" id="cfgWindowTitles"><span><strong>Foreground window titles</strong><small>Sensitive data. Disabled unless explicitly enabled here.</small></span></label>
      <div><label class="panel-sub" for="cfgUITreeApps">UI AUTOMATION APP ALLOWLIST</label><input class="field" id="cfgUITreeApps" maxlength="300" placeholder="notepad.exe, explorer.exe"><div class="note">Structural metadata for named applications only; no control text, values or passwords.</div></div>
     </div>
     <div class="note">Advanced settings are written to the local profile. Stop and start Sentinel after saving to reinitialize these collector pipelines.</div>
     <div class="button-row"><button class="btn primary" id="saveProfile">SAVE PROFILE</button><button class="btn ghost" id="reloadProfile">RELOAD SAVED</button></div><div class="note" id="profileNote">Live worker controls refresh on an observer cycle. Sensitive collectors remain explicit opt-ins.</div>
    </section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">MISSION DISPATCH</div><div class="panel-sub">Queue on-demand collector and intelligence jobs</div></div><span class="tag">ACTION QUEUE</span></div>
     <div class="action-grid">
      <button class="action-tile" data-command="scan_now"><b>◈ FULL SYSTEM SWEEP</b><small>Inventory + deep CIM + registry snapshot</small></button>
      <button class="action-tile" data-command="deep_scan_now"><b>⌖ DEEP HARDWARE SCAN</b><small>Drivers, PnP, storage and security posture</small></button>
      <button class="action-tile" data-command="registry_scan_now"><b>▤ REGISTRY SNAPSHOT</b><small>Compare allowlisted system configuration</small></button>
      <button class="action-tile" data-command="ai_review_now"><b>✳ AI EVIDENCE REVIEW</b><small>Local triage and independent review</small></button>
      <button class="action-tile" data-command="knowledge_crawl_now"><b>⌘ KNOWLEDGE SYNC</b><small>Refresh public Microsoft reference index</small></button>
     </div>
     <div class="panel-head" style="margin-top:17px"><div><div class="panel-title">LAST COMMAND</div><div class="panel-sub">Worker dispatch result</div></div><span class="tag" id="lastCommandState">IDLE</span></div><div class="ai-answer" id="lastCommand">No command has been dispatched in this worker session.</div>
     <div class="note">A queued job may be deferred while its collector or local model is busy. The worker records dispatched actions in the evidence vault.</div>
    </section>
   </div>
   <section class="panel" style="margin-top:12px"><div class="panel-head"><div><div class="panel-title">AUTOMATION AUDIT TIMELINE</div><div class="panel-sub">Command dispatch and posture automation events</div></div><button class="btn ghost" data-view-jump="evidence">OPEN FULL AUDIT →</button></div><div class="audit-list" id="automationAudit"><div class="empty">No automation records yet.</div></div></section>
  </section>

  <section class="screen" data-screen="knowledge">
   <div class="section-head"><div><div class="section-label">MICROSOFT LEARN / MICROSOFTDOCS / LOCAL SQLITE</div><div class="section-title">TECHNICAL CODEX</div><div class="section-description">Search locally indexed Windows engineering references; refresh the bounded public-source crawler from the command deck.</div></div><button class="btn primary" data-command="knowledge_crawl_now">⌘ SYNC CODEX</button></div>
   <div class="grid">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">LOCAL DOCUMENT SEARCH</div><div class="panel-sub">Queries the local index only; not a live web search.</div></div><span class="tag">OFFLINE SEARCH</span></div><div class="search-row"><input class="field" id="knowledgeQuery" maxlength="180" placeholder="Try: ETW registry callback, PnP driver, BitLocker…"><button class="btn primary" id="knowledgeSearch">SEARCH CODEX</button></div><div class="result-list scroll-list" id="knowledgeResults"><div class="empty">Search the local technical knowledge vault.</div></div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">KNOWLEDGE INGESTION</div><div class="panel-sub">Last bounded crawler pass</div></div><span class="tag" id="knowledgeState">WAITING</span></div><div class="system-cards" id="knowledgeStats"><div class="empty">No crawl statistics yet.</div></div><div class="note">Only allowlisted Microsoft Learn and Microsoft-owned GitHub content is fetched. The crawler does not transmit machine telemetry.</div></section>
   </div>
  </section>

  <div class="note" style="padding:22px 2px 0;text-align:center;letter-spacing:.12em">AIE // SENTINEL TITAN COMMAND DECK · LOCAL INTELLIGENCE · WINDOWS 11 · EVIDENCE FIRST</div>
 </main>
</div>
<div class="toast-stack" id="toastStack"></div>

<script>
"use strict";
const token=new URLSearchParams(location.hash.slice(1)).get("token")||"";
if(location.hash)history.replaceState(null,"",location.pathname+location.search);
const $=id=>document.getElementById(id);
const headers={"X-AIE-Token":token};
let currentView="cockpit",lastStatus=null,lastInventory=null,lastEvents=[],lastConfig=null,lastAlertKeys=null;
let cpuHistory=[],memHistory=[],lastInventoryFetch=0,lastEventsFetch=0,lastModelsFetch=0;
const titles={cockpit:"COMMAND CENTER",system:"SYSTEM DEEP DIVE",telemetry:"TELEMETRY MATRIX",evidence:"EVIDENCE VAULT",ai:"SENTINEL AI LAB",autonomy:"AUTONOMY CONTROL DECK",knowledge:"TECHNICAL CODEX"};
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}
function toast(message,kind=""){const stack=$("toastStack"),box=el("div","toast "+kind,message);stack.append(box);setTimeout(()=>box.remove(),5200)}
function age(iso){if(!iso)return"—";const t=new Date(iso).getTime();if(!Number.isFinite(t))return"—";const s=Math.max(0,Math.floor((Date.now()-t)/1000));return s<60?s+"s ago":s<3600?Math.floor(s/60)+"m ago":Math.floor(s/3600)+"h ago"}
function uptime(iso){if(!iso)return"—";let n=Math.max(0,Math.floor((Date.now()-new Date(iso).getTime())/1000));const h=Math.floor(n/3600);n%=3600;const m=Math.floor(n/60);return h+"h "+m+"m "+(n%60)+"s"}
function setMeter(id,value){const node=$(id);if(node)node.style.width=Math.max(0,Math.min(100,Number(value)||0))+"%"}
function statusTone(value){const s=String(value||"unknown").toLowerCase();return ["degraded","partial","warning","disabled","unavailable","critical"].includes(s)?"degraded":s==="available"||s==="watching"||s==="running"||s==="ok"?"":"optional"}
async function request(path,options={}){const response=await fetch(path,{...options,headers:{...headers,...(options.headers||{})},cache:"no-store"});let payload={};try{payload=await response.json()}catch{}if(!response.ok)throw new Error(payload.error||("Local API "+response.status));return payload}
function post(path,data){return request(path,{method:"POST",headers:{"Content-Type":"application/json","Origin":location.origin},body:JSON.stringify(data)})}
function switchView(view){if(!titles[view])return;currentView=view;document.querySelectorAll("[data-screen]").forEach(n=>n.classList.toggle("active",n.dataset.screen===view));document.querySelectorAll(".nav-btn").forEach(n=>n.classList.toggle("active",n.dataset.view===view));$("viewTitle").textContent=titles[view];if(view==="ai")loadModels();if(view==="autonomy")loadProfile();if(view==="system"){loadInventory(true);loadCatalog("processes");}if(view==="evidence")loadEvents(true);if(view==="knowledge")renderKnowledgeStats()}
document.querySelectorAll(".nav-btn").forEach(n=>n.addEventListener("click",()=>switchView(n.dataset.view)));
document.querySelectorAll("[data-view-jump]").forEach(n=>n.addEventListener("click",()=>switchView(n.dataset.viewJump)));
function drawCanvas(id,dataA,dataB){const canvas=$(id);if(!canvas)return;const rect=canvas.getBoundingClientRect();const w=Math.max(320,Math.round(rect.width*devicePixelRatio)),h=Math.max(150,Math.round(rect.height*devicePixelRatio));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}const ctx=canvas.getContext("2d");ctx.clearRect(0,0,w,h);const pad=18*devicePixelRatio;ctx.strokeStyle="#264257";ctx.lineWidth=devicePixelRatio;for(let i=0;i<=4;i++){const y=pad+(h-2*pad)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke()}function line(values,color){if(values.length<2)return;ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=2*devicePixelRatio;ctx.shadowBlur=8*devicePixelRatio;ctx.shadowColor=color;values.forEach((value,index)=>{const x=pad+(w-2*pad)*index/Math.max(1,values.length-1);const y=h-pad-(h-2*pad)*Math.max(0,Math.min(100,Number(value)||0))/100;if(index===0)ctx.moveTo(x,y);else ctx.lineTo(x,y)});ctx.stroke();ctx.shadowBlur=0}line(dataA,"#70eaff");line(dataB,"#ff637b")}
function drawCharts(){drawCanvas("mainChart",cpuHistory,memHistory);drawCanvas("telemetryChart",cpuHistory,memHistory)}
function addSample(s){const cpu=Number(s.cpu_percent)||0,total=Number(s.hardware?.memory_total_gib)||0,avail=Number(s.hardware?.memory_available_gib)||0;cpuHistory.push(cpu);memHistory.push(total?Math.max(0,(total-avail)/total*100):0);cpuHistory=cpuHistory.slice(-70);memHistory=memHistory.slice(-70);drawCharts()}
function renderStatus(s){
 lastStatus=s;const running=s.status==="running",paused=s.observer_paused===true,features=s.features||{},health=s.provider_health||{},providers=Object.values(health),bad=providers.filter(p=>p.state==="degraded").length,deep=s.deep_inventory||{},alerts=Array.isArray(deep.posture_alerts)?deep.posture_alerts:[];
 $("liveBadge").innerHTML=running?'<i class="led"></i>'+(paused?"PAUSED":"LIVE"):'<i class="led" style="background:var(--amber);color:var(--amber)"></i>OFFLINE';
 $("railLed").style.background=running?(paused?"var(--amber)":"var(--green)"):"var(--red)";
 $("heroDesc").textContent=paused?"Observation is paused. The dashboard and local evidence vault remain available.":running?"Windows perception is online. Local sensors are sampling approved system metadata; AI is evidence-led and advisory.":"The Sentinel worker is offline. Start it using the AIE CLI, then reopen this command deck.";
 $("pid").textContent=s.pid||"—";$("uptime").textContent=uptime(s.started_at);$("heartbeat").textContent=age(s.heartbeat_at);
 $("pauseBtn").disabled=!running||paused;$("resumeBtn").disabled=!running||!paused;
 const os=deep.operating_system||{};$("heroBuild").textContent=os.BuildNumber||"—";
 const cpu=Number(s.cpu_percent)||0,total=Number(s.hardware?.memory_total_gib)||0,available=Number(s.hardware?.memory_available_gib)||0,used=total?Math.max(0,total-available):0,memPct=total?used/total*100:0;
 $("cpuValue").textContent=cpu.toFixed(0)+"%";$("ramValue").textContent=total?available.toFixed(1)+" GB":"—";$("ramSub").textContent=total?used.toFixed(1)+" GB used / "+total.toFixed(1)+" GB":"Memory data unavailable";
 $("eventValue").textContent=Number(s.event_count||0).toLocaleString();$("sensorValue").textContent=providers.length?((providers.length-bad)+"/"+providers.length):"—";$("sensorSub").textContent=bad?bad+" degraded":"Provider heartbeat";
 $("alertValue").textContent=deep.last_snapshot_at?String(alerts.length):"—";$("alertSub").textContent=deep.last_snapshot_at?(alerts.filter(a=>a.severity==="critical").length+" critical · "+alerts.filter(a=>a.severity==="high").length+" high"):"No deep snapshot";
 setMeter("cpuMeter",cpu);setMeter("ramMeter",memPct);setMeter("eventMeter",Math.min(100,Number(s.event_count||0)/250));setMeter("sensorMeter",providers.length?(providers.length-bad)/providers.length*100:0);setMeter("alertMeter",Math.min(100,alerts.length*12));
 addSample(s);renderSensors(s);renderAlerts(alerts);renderAI(s.ai||{});renderCommand(s.last_command||null);renderKnowledgeStats();
 $("telemetryFreshness").textContent="HEARTBEAT "+age(s.heartbeat_at).toUpperCase();
 if(currentView==="autonomy")renderAudit(lastEvents);
}
function renderSensors(s){const health=s.provider_health||{},entries=Object.entries(health);const target=$("sensorGrid");target.replaceChildren();if(!entries.length){target.append(el("div","empty","Provider heartbeats will appear after the first collection cycle."));return}for(const [name,item] of entries.slice(0,14)){const row=el("div","sensor"),left=el("div"),strong=el("strong",null,name.replaceAll("_"," ").toUpperCase()),detail=el("small",null,(item.samples_succeeded||0)+"/"+(item.samples_attempted||0)+" samples · "+(item.last_latency_ms??"—")+" ms"),state=el("span","sensor-state "+statusTone(item.state),String(item.state||"unknown").toUpperCase());left.append(strong,detail);row.append(left,state);target.append(row)}}
function renderAlerts(alerts){const targets=[$("cockpitAlerts")];targets.forEach(target=>{target.replaceChildren();if(!alerts.length){target.append(el("div","empty","No rule-based posture alerts in the latest snapshot. This is not a guarantee of security."));return}for(const item of alerts.slice(0,5)){const card=el("article","alert-card "+String(item.severity||"info")),top=el("div","alert-row"),title=el("strong",null,item.title||"System finding"),sev=el("span","alert-sev",String(item.severity||"info").toUpperCase()+" · "+String(item.category||"SYSTEM").toUpperCase()),body=el("p",null,item.detail||"");top.append(title,sev);card.append(top,body);target.append(card)}});if(lastInventory)renderSystem(lastInventory.data||{})}
function renderAI(ai){const models=ai.models||{},tri=ai.triage||{},rev=ai.review||{};$("triageModel").textContent=models.triage||"No triage model recorded";$("reviewModel").textContent=models.review||"No independent reviewer recorded";$("triageState").textContent=models.triage?"ANALYZED":"IDLE";$("reviewState").textContent=models.independent_review_completed?"REVIEW COMPLETED":"REVIEW UNAVAILABLE";$("triageResult").textContent=tri.summary||"Waiting for the next local evidence review.";const items=[];for(const item of (tri.signals||[]).slice(0,4))items.push("SIGNAL · "+(typeof item==="string"?item:JSON.stringify(item)));for(const item of (tri.hypotheses||[]).slice(0,4))items.push("HYPOTHESIS · "+(typeof item==="string"?item:JSON.stringify(item)));$("reviewResult").textContent=(rev.assessment||"The independent reviewer has not completed a pass.")+(rev.confidence?" · "+rev.confidence.toUpperCase()+" CONFIDENCE":"");}
function infoCard(label,value,detail=""){const card=el("div","info-card"),small=el("small",null,label),strong=el("strong",null,value==null||value===""?"Unavailable":String(value)),p=el("p",null,detail);card.append(small,strong,p);return card}
function renderSystem(data){
 const os=data.operating_system||{},computer=data.computer||{},bios=data.bios||{},secure=data.secure_boot||{},def=data.defender_status||{};
 const platform=$("platformCards");platform.replaceChildren(
  infoCard("OPERATING SYSTEM",os.Caption,["Version "+(os.Version||"—"),"Build "+(os.BuildNumber||"—"),os.OSArchitecture||"—"].join(" · ")),
  infoCard("PROCESSOR",Array.isArray(data.processors)?(data.processors[0]?.Name||"Processor unavailable"):"—",(computer.NumberOfLogicalProcessors??"—")+" logical processors · hypervisor "+(computer.HypervisorPresent===true?"present":computer.HypervisorPresent===false?"not reported":"unknown")),
  infoCard("BIOS / FIRMWARE",bios.SMBIOSBIOSVersion||bios.Manufacturer,bios.ReleaseDate||"Firmware metadata only; serials excluded"),
  infoCard("SECURE BOOT",secure.supported===true?(secure.enabled?"ENABLED":"DISABLED"):"UNAVAILABLE",secure.supported===false?"Platform did not expose UEFI confirmation":"UEFI status where supported")
 );
 const security=$("securityDetails");security.replaceChildren();
 const entries=[
  ["Microsoft Defender",def.AntivirusEnabled],["Real-time protection",def.RealTimeProtectionEnabled],["Behavior monitor",def.BehaviorMonitorEnabled],["Network inspection",def.NISEnabled],
  ...((Array.isArray(data.firewall_profiles)?data.firewall_profiles:[]).map(x=>["Firewall "+(x.Name||"profile"),x.Enabled])),
  ["Secure Boot",secure.supported===true?secure.enabled:null]
 ];
 for(const [name,value] of entries){const pill=el("div","command-line"),label=el("strong",null,name),state=el("small",null,value===true?"ENABLED":value===false?"DISABLED":"UNKNOWN");if(value===false)state.style.color="var(--red)";pill.append(label,state);security.append(pill)}
 const disks=$("diskDetails");disks.replaceChildren();for(const disk of (data.fixed_disks||[])){const size=Number(disk.Size)||0,free=Number(disk.FreeSpace)||0,pct=size?Math.max(0,Math.min(100,(size-free)/size*100)):0,card=el("div","disk-item"),top=el("div","disk-top"),label=el("strong",null,(disk.DeviceID||"Volume")+" · "+(disk.FileSystem||"—")),info=el("small",null,(free/1073741824).toFixed(1)+" / "+(size/1073741824).toFixed(1)+" GiB free"),meter=el("div","disk-meter"),bar=el("i");bar.style.width=pct+"%";top.append(label,info);meter.append(bar);card.append(top,meter);disks.append(card)}
 for(const disk of (data.physical_disks||[])){const card=infoCard("PHYSICAL DISK / "+(disk.MediaType||"—"),disk.FriendlyName,(disk.HealthStatus||"health unknown")+" · "+(disk.BusType||"bus unavailable")+" · "+(disk.OperationalStatus||"")) ;disks.append(card)}
 if(!disks.children.length)disks.append(el("div","empty","No disk metadata returned."));
 const enc=$("encryptionBattery");enc.replaceChildren();
 for(const volume of (data.bitlocker_volumes||[]))enc.append(infoCard("BITLOCKER "+(volume.MountPoint||""),volume.ProtectionStatus||"Unknown",String(volume.VolumeStatus||"")+" · "+String(volume.EncryptionPercentage??"—")+"% encrypted · "+String(volume.EncryptionMethod||"—")));
 for(const battery of (data.batteries||[]))enc.append(infoCard("BATTERY",battery.EstimatedChargeRemaining==null?"Present":battery.EstimatedChargeRemaining+"%",(battery.Status||"")+" · runtime "+String(battery.EstimatedRunTime??"—")+" min · design/full "+String(battery.DesignCapacity??"—")+"/"+String(battery.FullChargeCapacity??"—")));
 if(!enc.children.length)enc.append(el("div","empty","BitLocker and battery metadata unavailable on this device."));
 $("metricProcesses").textContent=lastStatus?.inventory_summary?.processes??"—";$("metricApps").textContent=lastStatus?.inventory_summary?.applications??"—";$("metricDrivers").textContent=data.system_driver_count??"—";$("metricPnp").textContent=data.pnp_device_count??"—";$("metricPhysical").textContent=(data.physical_disks||[]).length||"—";
}
async function loadInventory(force=false){if(!force&&Date.now()-lastInventoryFetch<25000)return;lastInventoryFetch=Date.now();try{lastInventory=await request("/api/inventory");if(lastInventory.available)renderSystem(lastInventory.data||{});else{$("platformCards").replaceChildren(el("div","empty","Run a deep hardware scan to populate this workspace."))}}catch(e){toast("Inventory: "+e.message,"warn")}}
function renderEvents(events,targetId="eventList"){const target=$(targetId);if(!target)return;target.replaceChildren();if(!events.length){target.append(el("div","empty","No records match this filter."));return}for(const ev of events){const row=el("article","event"),icon=el("div","event-icon",ev.event_type?.includes("registry")?"⌘":ev.event_type?.includes("process")?"◉":ev.event_type?.includes("command")?"⚙":ev.event_type?.includes("model")?"✳":"◇"),body=el("div"),name=el("div","event-name",ev.event_type||"event"),desc=el("div","event-desc",(ev.entity?.name||ev.source||"system")+" · "+(ev.source||"")),details=el("details"),summary=el("summary",null,"INSPECT SAFE EVENT DATA"),pre=el("pre",null,JSON.stringify({time:ev.timestamp,source:ev.source,type:ev.event_type,entity:ev.entity,confidence:ev.confidence,data:ev.data},null,2)),time=el("div","event-time",age(ev.timestamp));details.append(summary,pre);body.append(name,desc,details);row.append(icon,body,time);target.append(row)}}
async function loadEvents(force=false){if(!force&&Date.now()-lastEventsFetch<7500)return;lastEventsFetch=Date.now();try{const r=await request("/api/events?limit=220");lastEvents=r.events||[];$("vaultCount").textContent=(r.returned??lastEvents.length)+" RECORDS";renderEvents(lastEvents,"eventList");renderEvents(lastEvents.slice(0,5),"cockpitEvents");renderAudit(lastEvents)}catch(e){toast("Event vault: "+e.message,"warn")}}
function renderAudit(events){const target=$("automationAudit");if(!target)return;target.replaceChildren();const rows=(events||[]).filter(e=>e.event_type?.includes("command_dispatched")||e.event_type?.includes("automation_triggered")).slice(0,12);if(!rows.length){target.append(el("div","empty","Automation and command dispatch events will appear here."));return}for(const ev of rows){const row=el("div","command-line"),left=el("strong",null,ev.event_type.replaceAll("."," / ").toUpperCase()+" · "+(ev.entity?.name||"")),right=el("small",null,age(ev.timestamp));row.append(left,right);target.append(row)}}
function renderCommand(command){if(!command)return;$("lastCommandState").textContent=String(command.status||"queued").toUpperCase();$("lastCommand").textContent=JSON.stringify(command,null,2)}
function renderWatchers(s){const target=$("internalWatchers");target.replaceChildren();const rows=[
 ["Registry observer",s.registry],["Deep CIM / device inventory",s.deep_inventory],["Microsoft knowledge crawler",s.knowledge],
 ["ETW process provider",(s.provider_health||{})["windows.etw.process"]]
 ];for(const [name,item] of rows){const row=el("div","command-line"),left=el("strong",null,name),right=el("small",null,item?.status||item?.state||(item?"available":"not configured"));row.append(left,right);target.append(row)}}
function renderRuntime(s){const target=$("runtimeProfile");target.replaceChildren();const hw=s.hardware||{};const entries=[["CPU LOGICAL COUNT",hw.cpu_count],["TOTAL MEMORY",hw.memory_total_gib==null?null:hw.memory_total_gib+" GiB"],["AVAILABLE MEMORY",hw.memory_available_gib==null?null:hw.memory_available_gib+" GiB"],["WORKER THREAD",s.pid]];for(const [name,value] of entries)target.append(infoCard(name,value,"Locally reported runtime profile"))}
function renderKnowledgeStats(){const k=lastStatus?.knowledge||{};$("knowledgeState").textContent=String(k.status||"NOT STARTED").toUpperCase();const target=$("knowledgeStats");if(!target)return;target.replaceChildren(infoCard("LOCAL DOCUMENTS",k.documents??"—","Indexed SQLite corpus"),infoCard("ADDED / UPDATED",(k.documents_added??"—")+" / "+(k.documents_updated??"—"),"Last crawler pass"),infoCard("SOURCE GROUPS",Object.keys(k.sources||{}).length,"Allowlisted Microsoft sources"),infoCard("LAST CRAWL",age(k.last_fetched_at),"Local status"))}
async function loadProfile(){try{const r=await request("/api/config");lastConfig=r.profile||{};renderProfile(lastConfig)}catch(e){$("profileNote").textContent="Profile load failed: "+e.message}}
function renderProfile(p){$("cfgRegistry").checked=p.registry_enabled===true;$("cfgDeep").checked=p.deep_inventory_enabled===true;$("cfgKnowledge").checked=p.knowledge_enabled===true;$("cfgAI").checked=p.ai_enabled===true;$("cfgPostureReview").checked=p.auto_review_on_posture_alerts===true;$("cfgRegistryReview").checked=p.auto_review_on_registry_changes===true;$("cfgRegistryInterval").value=p.registry_interval_seconds??180;$("cfgDeepInterval").value=p.deep_inventory_interval_seconds??900;$("cfgKnowledgeInterval").value=p.knowledge_interval_seconds??21600;$("cfgAIInterval").value=p.analysis_interval_seconds??300;$("cfgDiskThreshold").value=p.low_disk_alert_percent??10;$("cfgBatteryThreshold").value=p.low_battery_alert_percent??15;$("cfgEventLogs").checked=p.include_event_logs===true;$("cfgEtw").checked=p.include_etw===true;$("cfgWindowTitles").checked=p.include_window_titles===true;$("cfgUITreeApps").value=Array.isArray(p.ui_tree_apps)?p.ui_tree_apps.join(", "):""}
async function saveProfile(){const integer=id=>Number.parseInt($(id).value,10);const values={
 registry_enabled:$("cfgRegistry").checked,deep_inventory_enabled:$("cfgDeep").checked,knowledge_enabled:$("cfgKnowledge").checked,ai_enabled:$("cfgAI").checked,
 auto_review_on_posture_alerts:$("cfgPostureReview").checked,auto_review_on_registry_changes:$("cfgRegistryReview").checked,
 registry_interval_seconds:integer("cfgRegistryInterval"),deep_inventory_interval_seconds:integer("cfgDeepInterval"),knowledge_interval_seconds:integer("cfgKnowledgeInterval"),analysis_interval_seconds:integer("cfgAIInterval"),
 low_disk_alert_percent:integer("cfgDiskThreshold"),low_battery_alert_percent:integer("cfgBatteryThreshold"),
 include_event_logs:$("cfgEventLogs").checked,include_etw:$("cfgEtw").checked,include_window_titles:$("cfgWindowTitles").checked,
 ui_tree_apps:$("cfgUITreeApps").value.split(",").map(x=>x.trim().toLowerCase()).filter(Boolean)
};const prior=lastConfig||{};const advancedChanged=["include_event_logs","include_etw","include_window_titles"].some(k=>prior[k]!==values[k])||JSON.stringify(prior.ui_tree_apps||[])!==JSON.stringify(values.ui_tree_apps);$("saveProfile").disabled=true;try{const r=await post("/api/config",{values});lastConfig=r.profile;renderProfile(r.profile);$("profileNote").textContent=advancedChanged?"Profile saved. Advanced sensor changes require aie sentinel stop then aie sentinel start to reinitialize collectors.":"Profile saved to the local AIE config. Scheduler and automation rules will be adopted on the next observer cycle.";toast("Automation profile saved.");}catch(e){$("profileNote").textContent=e.message;toast("Profile save failed: "+e.message,"error")}finally{$("saveProfile").disabled=false}}
async function runCommand(action){try{const r=await post("/api/command",{action});toast("Command accepted · "+r.queued);setTimeout(()=>refresh(false),1100)}catch(e){toast(e.message,"error")}}
let catalogKind="processes";
async function loadCatalog(kind=catalogKind){
 catalogKind=kind;
 document.querySelectorAll("[data-catalog]").forEach(button=>button.classList.toggle("active",button.dataset.catalog===kind));
 const query=$("catalogQuery").value.trim(),target=$("catalogResults");
 target.replaceChildren(el("div","empty","Querying the latest local inventory…"));
 try{
  const result=await request("/api/catalog?kind="+encodeURIComponent(kind)+"&q="+encodeURIComponent(query)+"&limit=120");
  target.replaceChildren();
  $("catalogSnapshot").textContent=result.snapshot_at?"SNAPSHOT "+age(result.snapshot_at).toUpperCase():"NO SNAPSHOT";
  $("catalogMeta").textContent=result.available?(result.matched+" displayed / "+result.total+" records · "+(result.truncated||0)+" omitted by collector bounds"):"Run a full system scan to populate this catalog.";
  if(!result.items?.length){target.append(el("div","empty","No records match this filter."));return}
  for(const item of result.items){
   const card=el("div","info-card");
   const entries=Object.entries(item).filter(([key,value])=>value!==null&&value!==undefined);
   const first=entries[0]||["Record","—"];
   const title=el("small",null,String(first[0]).replaceAll("_"," ").toUpperCase());
   const strong=el("strong",null,String(first[1]));
   const detail=entries.slice(1).map(([key,value])=>key.replaceAll("_"," ")+": "+String(value)).join(" · ");
   const p=el("p",null,detail);
   card.append(title,strong,p);target.append(card);
  }
 }catch(error){target.replaceChildren(el("div","empty",error.message))}
}
async function searchDrivers(){const q=$("driverQuery").value.trim();const target=$("driverResults");target.replaceChildren(el("div","empty","Searching local signed-PnP snapshot…"));try{const r=await request("/api/drivers?q="+encodeURIComponent(q));target.replaceChildren();$("driverCount").textContent=(r.total||0)+" TOTAL / "+(r.matched||0)+" MATCHED";if(!r.drivers?.length){target.append(el("div","empty","No driver records matched. Run a deep scan first."));return}for(const d of r.drivers){const row=el("div","driver-row"),left=el("div"),name=el("strong",null,d.device),sub=el("small",null,d.provider+" · "+d.version),date=el("small",null,d.driver_date),signed=el("span","driver-state"+(d.signed===false?" unsigned":""),d.signed===true?"SIGNED":d.signed===false?"UNSIGNED":"UNKNOWN");left.append(name,sub);row.append(left,date,signed);target.append(row)}}catch(e){target.replaceChildren(el("div","empty",e.message))}}
async function loadModels(){if(Date.now()-lastModelsFetch<10000)return;lastModelsFetch=Date.now();const target=$("modelList");target.replaceChildren(el("div","empty","Discovering locally installed Ollama models…"));try{const r=await request("/api/ai/models");target.replaceChildren();$("modelMemory").textContent="Available system RAM: "+(r.memory_available_gib??"—")+" GiB · local-only inference";if(!r.models?.length){target.append(el("div","empty",r.error||"No installed local Ollama models were discovered."));return}for(const m of r.models){const item=el("div","model-card"),name=el("strong",null,m),detail=el("small",null,(r.triage_candidates.includes(m)?"3B/4B Ask + triage candidate · ":"")+(r.review_candidates.includes(m)?"6B/7B reviewer candidate":"Installed local model"));item.append(name,detail);target.append(item)}}catch(e){target.replaceChildren(el("div","empty",e.message))}}
async function askSentinel(){const question=$("aiQuestion").value.trim(),mode=$("aiMode").value;if(!question){$("aiQuestion").focus();return}const btn=$("askBtn");btn.disabled=true;btn.textContent="RUNNING LOCAL INFERENCE…";$("aiAnswer").textContent="Preparing the bounded evidence packet and local reference context. Waiting for local Ollama…";$("aiReferences").replaceChildren();try{const r=await post("/api/ask",{question,mode});$("aiAnswer").textContent=r.answer||"No answer returned.";const meta=el("div","panel-sub","SPECIALIST "+String(r.specialist_mode||mode).toUpperCase()+" · "+String(r.model||"LOCAL MODEL")+" · "+String(r.confidence||"low").toUpperCase()+" CONFIDENCE · "+(r.evidence_ids||[]).length+" EVIDENCE IDS");$("aiReferences").append(meta);if(r.evidence_ids?.length)$("aiReferences").append(el("div","panel-sub","EVIDENCE IDS · "+r.evidence_ids.join(", ")));for(const ref of r.references||[]){try{const url=new URL(ref.url);if(url.protocol==="https:"&&["learn.microsoft.com","github.com"].includes(url.hostname)){const a=el("a","ai-reference",ref.title||url.hostname);a.href=url.href;a.target="_blank";a.rel="noopener noreferrer";$("aiReferences").append(a)}}catch{}}toast("Local specialist response ready.")}catch(e){$("aiAnswer").textContent="Sentinel AI unavailable: "+e.message;toast(e.message,"error")}finally{btn.disabled=false;btn.textContent="✳ ASK LOCAL AI"}}
async function searchKnowledge(){const q=$("knowledgeQuery").value.trim();if(!q){$("knowledgeQuery").focus();return}const target=$("knowledgeResults");target.replaceChildren(el("div","empty","Searching local documentation index…"));try{const r=await request("/api/knowledge/search?q="+encodeURIComponent(q)+"&limit=8");target.replaceChildren();if(!r.results?.length){target.append(el("div","empty","No indexed document matched. Run a knowledge sync."));return}for(const item of r.results){const card=el("div","knowledge-card"),title=el("strong",null,item.title||"Untitled document"),meta=el("small",null,String(item.source||"").toUpperCase()+" · SCORE "+item.score),p=el("p",null,item.excerpt||""),a=el("a","ai-reference",item.url||"");if(item.url){a.href=item.url;a.target="_blank";a.rel="noopener noreferrer"}card.append(title,meta,p,a);target.append(card)}}catch(e){target.replaceChildren(el("div","empty",e.message))}}
let notifiedReady=false;
async function enableNotifications(){if(!("Notification"in window)){toast("This browser does not support desktop notifications.","warn");return}const result=await Notification.requestPermission();notifiedReady=result==="granted";toast(notifiedReady?"Desktop posture alerts enabled.":"Notification permission was not granted.",notifiedReady?"":"warn")}
function notifyNewPosture(status){const alerts=status.deep_inventory?.posture_alerts||[],keys=alerts.map(a=>[a.severity,a.category,a.title].join("|"));if(lastAlertKeys===null){lastAlertKeys=new Set(keys);return}const newly=alerts.filter(a=>!lastAlertKeys.has([a.severity,a.category,a.title].join("|")));lastAlertKeys=new Set(keys);for(const item of newly){toast(item.title+" · "+(item.detail||""),item.severity==="critical"||item.severity==="high"?"error":"warn");if(notifiedReady&&("Notification"in window))new Notification("Sentinel · "+String(item.severity||"INFO").toUpperCase(),{body:item.title+" — "+(item.detail||"")})}}
async function refresh(forceInventory=false){try{const s=await request("/api/status");renderStatus(s);notifyNewPosture(s);if(forceInventory||Date.now()-lastInventoryFetch>26000)await loadInventory(true);if(Date.now()-lastEventsFetch>7500||!lastEvents.length)await loadEvents(true);if(currentView==="system"&&lastInventory)renderSystem(lastInventory.data||{});if(currentView==="autonomy")renderAudit(lastEvents);return true}catch(e){$("liveBadge").textContent="RECONNECTING";$("heroDesc").textContent="Unable to contact the local Sentinel worker. Reconnecting…";return false}}
function bootProgress(value,stage,line){$("bootProgress").style.width=value+"%";$("bootPercent").textContent=String(value).padStart(2,"0")+"%";$("bootStage").textContent=stage;if(line){const row=el("div",null,line);$("bootLog").append(row);while($("bootLog").children.length>4)$("bootLog").firstChild.remove()}}
function finishBoot(){ $("boot").classList.add("done");$("app").classList.add("ready");setTimeout(()=>$("boot").remove(),950)}
async function startBoot(){bootProgress(12,"OPENING LOCAL LINK","loopback command channel initializing");await new Promise(r=>setTimeout(r,240));const connected=await refresh(true);if(!connected){bootProgress(100,"WORKER OFFLINE","interface loaded · waiting for Sentinel worker");setTimeout(finishBoot,520);return}bootProgress(66,"MOUNTING EVIDENCE","SQLite event vault synchronized");await loadProfile();bootProgress(84,"DISCOVERING INTELLIGENCE","collector profile and subsystem status synchronized");await loadModels();bootProgress(100,"TITAN ONLINE","command deck ready · local-only intelligence");setTimeout(finishBoot,520)}
function drawStars(){const canvas=$("starfield");if(!canvas)return;const ctx=canvas.getContext("2d");let points=[];function resize(){canvas.width=Math.max(320,innerWidth*devicePixelRatio);canvas.height=Math.max(300,innerHeight*devicePixelRatio);points=Array.from({length:72},()=>({x:Math.random()*canvas.width,y:Math.random()*canvas.height,r:Math.random()*1.4+.3,s:Math.random()*.18+.04}))}function paint(move){ctx.clearRect(0,0,canvas.width,canvas.height);for(const p of points){ctx.fillStyle="rgba(130,221,245,.65)";ctx.beginPath();ctx.arc(p.x,p.y,p.r*devicePixelRatio,0,Math.PI*2);ctx.fill();if(move){p.y+=p.s*devicePixelRatio;if(p.y>canvas.height)p.y=0}}if(move)requestAnimationFrame(()=>paint(true))}resize();addEventListener("resize",()=>{resize();paint(false)});paint(!matchMedia("(prefers-reduced-motion: reduce)").matches)}
$("pauseBtn").addEventListener("click",async()=>{try{await post("/api/control",{action:"pause"});toast("Sensor pause requested.");refresh()}catch(e){toast(e.message,"error")}});
$("stopBtn").addEventListener("click",async()=>{if(!confirm("Stop the Sentinel background worker? The dashboard will disconnect until it is started again."))return;try{await post("/api/control",{action:"stop"});toast("Stop request sent. The local dashboard will close when the worker exits.","warn")}catch(e){toast(e.message,"error")}});
$("resumeBtn").addEventListener("click",async()=>{try{await post("/api/control",{action:"resume"});toast("Sentinel watch resumed.");refresh()}catch(e){toast(e.message,"error")}});
$("notifyBtn").addEventListener("click",enableNotifications);$("notifyEnable").addEventListener("click",enableNotifications);
$("refreshBtn").addEventListener("click",()=>refresh(true));$("modelRefresh").addEventListener("click",()=>{lastModelsFetch=0;loadModels()});
$("saveProfile").addEventListener("click",saveProfile);$("reloadProfile").addEventListener("click",loadProfile);
$("askBtn").addEventListener("click",askSentinel);$("aiQuestion").addEventListener("keydown",e=>{if(e.key==="Enter")askSentinel()});
$("driverSearch").addEventListener("click",searchDrivers);$("driverQuery").addEventListener("keydown",e=>{if(e.key==="Enter")searchDrivers()});
$("catalogSearch").addEventListener("click",()=>loadCatalog());
$("catalogQuery").addEventListener("keydown",e=>{if(e.key==="Enter")loadCatalog()});
document.querySelectorAll("[data-catalog]").forEach(button=>button.addEventListener("click",()=>loadCatalog(button.dataset.catalog)));
$("knowledgeSearch").addEventListener("click",searchKnowledge);$("knowledgeQuery").addEventListener("keydown",e=>{if(e.key==="Enter")searchKnowledge()});
$("eventSearch").addEventListener("click",async()=>{const q=$("eventQuery").value.trim(),type=$("eventTypeFilter").value;try{const r=await request("/api/events?limit=250&q="+encodeURIComponent(q)+"&type="+encodeURIComponent(type));lastEvents=r.events||[];$("eventMeta").textContent=(r.returned||0)+" matches in the recent searchable window";renderEvents(lastEvents)}catch(e){toast(e.message,"error")}});
$("eventRefresh").addEventListener("click",()=>loadEvents(true));
document.querySelectorAll("[data-command]").forEach(n=>n.addEventListener("click",()=>runCommand(n.dataset.command)));
$("clock").textContent=new Date().toLocaleTimeString();setInterval(()=>$("clock").textContent=new Date().toLocaleTimeString(),1000);
addEventListener("resize",drawCharts);drawStars();startBoot();setInterval(()=>refresh(false),3000);
$("bootSkip").addEventListener("click",finishBoot);
</script>
</body>
</html>"""


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
                        "analysis_interval_seconds", "auto_review_on_posture_alerts",
                        "auto_review_on_registry_changes", "low_disk_alert_percent",
                        "low_battery_alert_percent", "include_event_logs",
                        "include_etw", "include_window_titles", "ui_tree_apps",
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
            if parsed.path == "/api/catalog":
                try:
                    params = parse_qs(parsed.query)
                    kind = params.get("kind", ["services"])[0].strip().casefold()
                    allowed = {
                        "processes": "processes",
                        "applications": "installed_applications",
                        "services": "services",
                        "tasks": "scheduled_tasks",
                        "interfaces": "network_interfaces",
                    }
                    if kind not in allowed:
                        self._json(400, {"error": "unsupported inventory catalog"})
                        return
                    query = params.get("q", [""])[0].strip().casefold()[:100]
                    limit = max(1, min(200, int(params.get("limit", ["80"])[0])))
                    latest = next(
                        (
                            event for event in EventStore(db_path).recent(1500)
                            if event.event_type == "windows.system_inventory"
                        ),
                        None,
                    )
                    if latest is None:
                        self._json(200, {"available": False, "snapshot_at": None, "total": 0, "matched": 0, "items": []})
                        return
                    records = latest.data.get(allowed[kind], [])
                    records = records if isinstance(records, list) else []
                    matched = []
                    for record in records:
                        if not isinstance(record, dict):
                            continue
                        if query and query not in json.dumps(record, ensure_ascii=True).casefold():
                            continue
                        matched.append(_safe_json_value(record))
                        if len(matched) >= limit:
                            break
                    truncated = latest.data.get("truncated", {})
                    truncated_key = {
                        "processes": "processes",
                        "applications": "applications",
                        "services": "services",
                        "tasks": "scheduled_tasks",
                        "interfaces": "network_interfaces",
                    }[kind]
                    self._json(200, {
                        "available": True,
                        "snapshot_at": latest.timestamp.isoformat(),
                        "kind": kind,
                        "total": len(records),
                        "matched": len(matched),
                        "items": matched,
                        "truncated": truncated.get(truncated_key, 0) if isinstance(truncated, dict) else 0,
                        "inventory_summary": {
                            "processes": latest.data.get("process_count", 0),
                            "applications": latest.data.get("installed_application_count", 0),
                            "services": latest.data.get("service_count", 0),
                            "scheduled_tasks": latest.data.get("scheduled_task_count", 0),
                            "interfaces": len(latest.data.get("network_interfaces", [])) if isinstance(latest.data.get("network_interfaces"), list) else 0,
                        },
                    })
                except (OSError, ValueError):
                    self._json(503, {"error": "System inventory catalog is unavailable"})
                return
            if parsed.path == "/api/ai/models":
                try:
                    from aie.models.ollama import OllamaClient
                    from aie.hardware import runtime_profile
                    models = OllamaClient(default_timeout=8.0).list_models(timeout=5.0)
                    profile = runtime_profile()
                    self._json(200, {
                        "available": bool(models),
                        "models": models[:40],
                        "memory_available_gib": profile.get("memory_available_gib"),
                        "triage_candidates": [name for name in models if any(token in name.casefold() for token in ("3b", "4b"))],
                        "review_candidates": [name for name in models if any(token in name.casefold() for token in ("6b", "7b", "8b"))],
                        "inference_mode": "local_ollama_only",
                    })
                except Exception as exc:  # noqa: BLE001 - discovery is an optional dashboard surface.
                    self._json(200, {"available": False, "models": [], "error": type(exc).__name__})
                return
            if parsed.path == "/api/inventory":
                try:
                    latest = next(
                        (
                            event for event in EventStore(db_path).recent(1500)
                            if event.event_type == "windows.deep_inventory"
                        ),
                        None,
                    )
                    if latest is None:
                        self._json(200, {"available": False, "snapshot_at": None, "data": {}})
                        return
                    self._json(200, {
                        "available": True,
                        "snapshot_at": latest.timestamp.isoformat(),
                        "data": _safe_json_value(latest.data),
                    })
                except (OSError, ValueError):
                    self._json(503, {"error": "Deep inventory snapshot is unavailable"})
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
                    params = parse_qs(parsed.query)
                    limit = max(1, min(250, int(params.get("limit", ["120"])[0])))
                    query = params.get("q", [""])[0].strip().casefold()[:120]
                    event_type = params.get("type", [""])[0].strip().casefold()[:100]
                    store = EventStore(db_path)
                    events = []
                    for event in store.recent(min(1500, limit * 5)):
                        payload = _event_payload(event)
                        if payload is None:
                            continue
                        if event_type and event_type not in event.event_type.casefold():
                            continue
                        if query:
                            haystack = " ".join((
                                event.event_type, event.source, event.entity.name,
                                json.dumps(payload["data"], ensure_ascii=True),
                            )).casefold()
                            if query not in haystack:
                                continue
                        events.append(payload)
                        if len(events) >= limit:
                            break
                    self._json(200, {"events": events, "returned": len(events), "query": query})
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
                    "registry_enabled", "deep_inventory_enabled", "knowledge_enabled", "ai_enabled",
                    "auto_review_on_posture_alerts", "auto_review_on_registry_changes",
                    "include_event_logs", "include_etw", "include_window_titles",
                }
                integer_ranges = {
                    "registry_interval_seconds": (60, 3600),
                    "deep_inventory_interval_seconds": (300, 7200),
                    "knowledge_interval_seconds": (3600, 604800),
                    "analysis_interval_seconds": (60, 3600),
                    "low_disk_alert_percent": (1, 30),
                    "low_battery_alert_percent": (5, 40),
                }
                if any(key not in boolean_fields and key not in integer_ranges and key != "ui_tree_apps" for key in values):
                    self._json(400, {"error": "profile contains an unsupported setting"})
                    return
                if "ui_tree_apps" in values:
                    apps = values["ui_tree_apps"]
                    if (
                        not isinstance(apps, list)
                        or len(apps) > 20
                        or any(
                            not isinstance(name, str)
                            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}\.exe", name, re.IGNORECASE)
                            for name in apps
                        )
                    ):
                        self._json(400, {"error": "UI Automation allowlist must contain up to 20 executable names such as notepad.exe"})
                        return
                    values["ui_tree_apps"] = sorted({name.casefold() for name in apps})
                for key, value in values.items():
                    if key == "ui_tree_apps":
                        continue
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
                    fields = tuple(boolean_fields | set(integer_ranges) | {"ui_tree_apps"})
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
                if action in {"ai_review_now", "knowledge_crawl_now", "registry_scan_now"}:
                    try:
                        active_profile = config_loader() if config_loader is not None else {}
                    except (OSError, RuntimeError, ValueError):
                        self._json(503, {"error": "Sentinel profile is unavailable"})
                        return
                    required_flag = {
                        "ai_review_now": "ai_enabled",
                        "knowledge_crawl_now": "knowledge_enabled",
                        "registry_scan_now": "registry_enabled",
                    }[action]
                    if active_profile.get(required_flag) is not True:
                        self._json(409, {"error": required_flag.replace("_", " ") + " is disabled in the current profile"})
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
                mode = body.get("mode", "general")
                allowed_modes = {"general", "security", "performance", "drivers", "storage", "network"}
                if not isinstance(question, str) or not question.strip() or len(question) > 500:
                    self._json(400, {"error": "question must contain 1-500 characters"})
                    return
                if not isinstance(mode, str) or mode not in allowed_modes:
                    self._json(400, {"error": "unsupported diagnostic specialist"})
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
                        EventStore(db_path).recent(160),
                        mode=mode,
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
