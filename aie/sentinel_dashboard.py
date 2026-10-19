"""Loopback-only Sentinel dashboard with a built-in, dependency-free web interface."""
from __future__ import annotations

import hmac
import json
import queue
import re
import sqlite3
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
<title>AIE // SENTINEL FIELD SYSTEM</title>
<style>

:root{
  color-scheme:dark;
  --bg:#07101c;
  --bg2:#0b1726;
  --panel:#101f31;
  --panel2:#152941;
  --line:#263d56;
  --line2:#385673;
  --text:#edf5ff;
  --soft:#c0d0e2;
  --muted:#8499ae;
  --orange:#ff645d;
  --orange2:#ca454a;
  --lime:#8bdcff;
  --red:#ff5d63;
  --amber:#f4bd69;
  --green:#73e0b1;
  --display:"Segoe UI Variable Display","Aptos Display","Segoe UI",Arial,sans-serif;
  --mono:"Cascadia Code","Consolas",monospace;
  --radius:22px;
  --radius-sm:14px;
  --shadow-card:0 18px 55px rgba(0,0,0,.22);
  --shadow-float:0 26px 80px rgba(0,0,0,.34);
}
*{box-sizing:border-box}
html{min-height:100%;scroll-behavior:smooth;background:var(--bg)}
body{
  margin:0;min-height:100vh;overflow-x:hidden;
  background:var(--bg);color:var(--text);
  font:14px/1.6 "Segoe UI Variable","Aptos","Segoe UI",Arial,sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
}
button,input,select,textarea{font:inherit}
button{cursor:pointer}
button:disabled{cursor:not-allowed}
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,[tabindex="0"]:focus-visible{
  outline:2px solid var(--lime);outline-offset:3px
}
a{color:var(--lime);text-decoration:none}
::selection{background:#8bdcff44;color:#fff}
#starfield{position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:0;opacity:.34}
.ambient{
  position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden;
  background:
    radial-gradient(ellipse at 10% 0%,rgba(39,118,170,.16),transparent 34%),
    radial-gradient(ellipse at 92% 18%,rgba(255,100,93,.085),transparent 29%),
    radial-gradient(ellipse at 58% 100%,rgba(31,102,160,.10),transparent 42%),
    linear-gradient(135deg,#07101c 0%,#091728 48%,#07111f 100%);
}
.ambient:before{
  content:"";position:absolute;inset:0;opacity:.17;
  background-image:linear-gradient(rgba(139,220,255,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(139,220,255,.055) 1px,transparent 1px);
  background-size:48px 48px;
  mask-image:radial-gradient(ellipse at 50% 20%,#000,transparent 82%);
}
.ambient:after{
  content:"";position:absolute;left:0;right:0;top:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--lime),rgba(255,100,93,.65),transparent);
  opacity:.68;
}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
@keyframes softPulse{0%,100%{opacity:1}50%{opacity:.55}}
@keyframes orbit{to{transform:rotate(360deg)}}
@keyframes reverseOrbit{to{transform:rotate(-360deg)}}
@keyframes coreBreathe{0%,100%{transform:scale(.98);filter:brightness(.96)}50%{transform:scale(1.035);filter:brightness(1.14)}}
@keyframes shimmer{0%{background-position:180% 0}100%{background-position:-180% 0}}
@keyframes scanSweep{0%{transform:translateY(-120%);opacity:0}15%{opacity:.55}85%{opacity:.22}100%{transform:translateY(120%);opacity:0}}
@keyframes paletteIn{from{opacity:0;transform:translateY(12px) scale(.985)}to{opacity:1;transform:none}}
@keyframes toastIn{from{opacity:0;transform:translateX(12px)}to{opacity:1;transform:none}}
.boot{
  position:fixed;inset:0;z-index:1000;display:grid;place-items:center;
  background:radial-gradient(ellipse at 50% 34%,#102a43,#07101c 66%);
  transition:opacity .45s ease,visibility .45s ease;
}
.boot.done{opacity:0;visibility:hidden;pointer-events:none}
.boot-grid{
  position:absolute;inset:0;opacity:.2;
  background-image:linear-gradient(rgba(139,220,255,.09) 1px,transparent 1px),linear-gradient(90deg,rgba(139,220,255,.09) 1px,transparent 1px);
  background-size:42px 42px;mask-image:linear-gradient(transparent,#000 30%,#000);
}
.boot-card{
  width:min(720px,calc(100vw - 34px));position:relative;overflow:hidden;
  padding:clamp(26px,5vw,46px);border:1px solid #42627e;border-radius:30px;
  background:linear-gradient(145deg,rgba(20,47,73,.96),rgba(9,23,40,.97) 68%);
  box-shadow:0 38px 110px #0009,inset 0 1px 0 rgba(255,255,255,.07);
}
.boot-card:before{
  content:"";position:absolute;inset:0;pointer-events:none;opacity:.48;
  background:radial-gradient(circle at 88% 10%,rgba(139,220,255,.18),transparent 35%),linear-gradient(115deg,transparent 52%,rgba(255,100,93,.06));
}
.boot-card:after{
  content:"";position:absolute;right:-100px;top:-120px;width:330px;height:330px;border:1px solid #8bdcff30;
  border-radius:50%;box-shadow:0 0 0 22px #8bdcff08,0 0 0 48px #8bdcff06,0 0 80px #8bdcff12;pointer-events:none;
}
.boot-emblem{
  width:76px;height:76px;margin:0 0 24px;display:grid;place-items:center;position:relative;
  border:1px solid #8bdcff88;border-radius:23px;
  background:linear-gradient(145deg,#1e4c70,#112b46);
  box-shadow:0 12px 35px #0005,inset 0 0 25px #8bdcff15;
}
.boot-emblem:before,.boot-emblem:after{content:"";position:absolute;inset:9px;border:1px solid #9ce5ff;transform:rotate(45deg);border-radius:8px}
.boot-emblem:after{inset:20px;border:2px solid var(--orange);transform:rotate(0);border-radius:6px;box-shadow:0 0 20px #ff645d50}
.boot-mark{position:relative;z-index:1;color:#fff;font:900 18px var(--display);letter-spacing:.1em}
.boot-title{position:relative;z-index:1;font:800 clamp(25px,4vw,38px)/1.08 var(--display);letter-spacing:.035em}
.boot-sub{position:relative;z-index:1;color:var(--lime);font:10px var(--mono);letter-spacing:.14em;margin-top:11px}
.boot-copy{position:relative;z-index:1;max-width:550px;color:#b0c5d9;font-size:13px;margin:19px 0 24px}
.boot-track{height:5px;position:relative;z-index:1;background:#203c56;overflow:hidden;border-radius:99px}
.boot-progress{height:100%;width:0;background:linear-gradient(90deg,#4695c8,var(--lime),#ff7774);border-radius:99px;transition:width .32s ease}
.boot-stage{position:relative;z-index:1;display:flex;justify-content:space-between;gap:12px;margin-top:11px;color:#93acc1;font:10px var(--mono);letter-spacing:.09em}
.boot-stage b{color:var(--lime)}
.boot-log{position:relative;z-index:1;height:68px;overflow:hidden;text-align:left;border:1px solid #355572;border-radius:13px;background:#091a2a;margin-top:20px;padding:10px 12px;color:#a4bfd4;font:10px/1.65 var(--mono)}
.boot-log div:before{content:"› ";color:var(--orange)}
.boot-skip{
  position:relative;z-index:1;border:1px solid #527897;border-radius:12px;background:#173653;color:#d9f3ff;
  font:700 10px var(--mono);letter-spacing:.1em;padding:11px 15px;margin-top:15px;text-transform:uppercase;transition:.2s;
}
.boot-skip:hover{border-color:var(--lime);background:#1c496d;color:#fff;transform:translateY(-1px)}
.app{
  position:relative;z-index:1;display:grid;grid-template-columns:272px minmax(0,1fr);
  min-height:100vh;opacity:0;transform:translateY(5px);transition:opacity .42s ease,transform .42s ease;
}
.app.ready{opacity:1;transform:none}
.rail{
  position:sticky;top:0;height:100vh;min-height:620px;display:flex;flex-direction:column;gap:12px;
  padding:20px 15px 16px;border-right:1px solid rgba(93,139,174,.2);
  background:linear-gradient(180deg,rgba(9,23,39,.96),rgba(7,17,30,.94));
  backdrop-filter:blur(18px);z-index:30;
}
.rail-brand{
  min-height:78px;display:flex;align-items:center;gap:14px;padding:8px 12px 17px;margin-bottom:5px;
  border-bottom:1px solid rgba(112,159,194,.2);
}
.brand-mini{
  width:44px;height:44px;flex:0 0 44px;position:relative;border-radius:14px;
  border:1px solid #6e9dbd;background:linear-gradient(145deg,#214d70,#10283f);
  box-shadow:0 9px 24px #0004,inset 0 0 18px #8bdcff1a;
}
.brand-mini:before{
  content:"";position:absolute;inset:9px;border:1px solid var(--lime);border-radius:6px;transform:rotate(45deg);
  box-shadow:0 0 16px #8bdcff22;
}
.brand-mini:after{content:"";position:absolute;width:7px;height:7px;left:18px;top:18px;border-radius:50%;background:var(--orange);box-shadow:0 0 13px #ff645d99}
.brand-lockup strong{display:block;font:800 16px/1.05 var(--display);letter-spacing:.11em;color:#f1f7ff}
.brand-lockup small{display:block;color:#91abc2;font:9px var(--mono);letter-spacing:.12em;margin-top:7px}
.rail-nav{display:flex;flex-direction:column;gap:16px;min-height:0;overflow:auto;padding:3px 1px 8px;scrollbar-width:thin;scrollbar-color:#385873 transparent}
.nav-group{display:grid;gap:5px}
.nav-group-label{padding:0 12px 5px;color:#6f8ba5;font:9px var(--mono);letter-spacing:.16em;text-transform:uppercase}
.nav-btn{
  width:100%;min-height:47px;display:flex;align-items:center;gap:13px;padding:0 12px;
  border:1px solid transparent;border-radius:14px;background:transparent;color:#9eb2c6;text-align:left;
  transition:background .2s ease,border-color .2s ease,color .2s ease,transform .2s ease,box-shadow .2s ease;
}
.nav-btn .nav-icon{
  width:31px;height:31px;flex:0 0 31px;display:grid;place-items:center;border:1px solid #2e4b66;
  border-radius:10px;background:rgba(20,45,68,.7);color:#8aaac3;font:10px var(--mono);text-align:center;
}
.nav-btn small{font:700 11px var(--display);letter-spacing:.055em}
.nav-btn:hover{background:rgba(34,75,108,.28);border-color:#355b79;color:#f1f8ff;transform:translateX(2px)}
.nav-btn:hover .nav-icon{border-color:#6299bc;color:var(--lime);background:#1b3b58}
.nav-btn.active{
  background:linear-gradient(105deg,rgba(45,102,145,.38),rgba(21,51,77,.24));
  border-color:#436c8a;color:#fff;box-shadow:inset 3px 0 0 var(--orange),0 8px 22px #0002;
}
.nav-btn.active .nav-icon{background:linear-gradient(145deg,#1f557b,#183a5b);border-color:#72b4d8;color:#eafaff;box-shadow:0 0 18px #8bdcff1b}
.rail-spacer{flex:1;min-height:12px}
.rail-state{width:9px;height:9px;flex:0 0 9px;border-radius:50%;background:var(--green);box-shadow:0 0 0 5px #73e0b118,0 0 20px #73e0b155;animation:softPulse 2.8s infinite;margin:0 0 3px 7px}
.rail-bottom{color:#6f8ba5;font:9px/1.6 var(--mono);letter-spacing:.1em;padding:13px 8px 3px;border-top:1px solid rgba(112,159,194,.2)}
main{min-width:0;width:100%;max-width:1840px;margin:0 auto;padding:0 clamp(18px,2.4vw,38px) 42px}
.topbar{
  min-height:82px;position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:18px;
  padding:13px 0;margin-bottom:25px;background:linear-gradient(180deg,rgba(7,16,28,.96),rgba(7,16,28,.78));
  backdrop-filter:blur(18px);border-bottom:1px solid rgba(106,154,191,.2);
}
.top-left{display:flex;align-items:center;gap:14px;min-width:0}
.top-mark{height:40px;width:4px;border-radius:99px;background:linear-gradient(180deg,var(--orange),var(--lime));box-shadow:0 0 20px #8bdcff44}
.eyebrow{color:#7896b0;font:9px var(--mono);letter-spacing:.12em;text-transform:uppercase}
.view-title{font:750 22px/1.16 var(--display);letter-spacing:.025em;margin-top:4px;color:#f0f7ff}
.top-right{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.clock{font:11px var(--mono);color:#94acc2;padding:0 8px;white-space:nowrap}
.system-badge{
  display:inline-flex;align-items:center;gap:9px;border:1px solid #345e7d;border-radius:999px;
  padding:8px 12px;background:rgba(16,43,66,.78);color:var(--lime);font:10px var(--mono);letter-spacing:.08em;white-space:nowrap;
}
.led{width:7px;height:7px;flex:0 0 7px;border-radius:50%;background:currentColor;box-shadow:0 0 0 4px #8bdcff17,0 0 15px currentColor;animation:softPulse 2.2s infinite}
.icon-btn{
  display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:39px;
  border:1px solid #34516d;border-radius:12px;background:rgba(17,39,61,.9);color:#c5d9e9;
  padding:9px 12px;font:700 10px var(--mono);letter-spacing:.055em;white-space:nowrap;transition:.18s ease;
}
.icon-btn:hover{border-color:#75b5d8;color:#fff;background:#173a59;transform:translateY(-1px);box-shadow:0 8px 22px #0003}
#stopBtn{border-color:#78474d!important;color:#ffaaa8!important;background:rgba(79,31,39,.42)!important}
#stopBtn:hover{border-color:var(--red)!important;background:rgba(108,39,47,.62)!important}
kbd{font:9px var(--mono);color:#8faec4;border:1px solid #42617a;border-radius:6px;padding:2px 5px;background:#0a1b2b}
.screen{display:none;animation:fadeUp .28s cubic-bezier(.2,.7,.2,1)}
.screen.active{display:block}
.section-head{
  display:flex;justify-content:space-between;align-items:flex-end;gap:18px;
  margin:3px 0 18px;padding:0 0 17px;border-bottom:1px solid rgba(105,151,188,.2);
}
.section-label{color:var(--lime);font:10px var(--mono);letter-spacing:.13em;text-transform:uppercase}
.section-title{font:760 clamp(23px,2.3vw,31px)/1.12 var(--display);letter-spacing:.005em;margin-top:6px;color:#f0f7ff}
.section-description{font-size:13px;line-height:1.58;color:#a3b8cc;max-width:850px;margin-top:8px}
.tag{
  display:inline-flex;align-items:center;gap:6px;font:9px var(--mono);letter-spacing:.08em;color:#b9d8ed;
  border:1px solid #3b6381;background:rgba(20,48,73,.76);border-radius:999px;padding:7px 11px;white-space:nowrap;text-transform:uppercase;
}
.hero{
  position:relative;isolation:isolate;display:grid;grid-template-columns:minmax(0,1fr) minmax(265px,310px);gap:28px;
  min-height:278px;border:1px solid #3d6888;border-radius:28px;overflow:hidden;padding:clamp(24px,3vw,38px);
  background:
    radial-gradient(ellipse at 88% 10%,rgba(139,220,255,.19),transparent 32%),
    radial-gradient(ellipse at 8% 110%,rgba(255,100,93,.10),transparent 38%),
    linear-gradient(120deg,rgba(22,53,80,.98),rgba(13,34,55,.97) 57%,rgba(11,27,45,.98));
  box-shadow:var(--shadow-card),inset 0 1px 0 rgba(255,255,255,.08);
}
.hero:before{
  content:"";position:absolute;inset:0;z-index:-1;pointer-events:none;opacity:.28;
  background-image:linear-gradient(rgba(153,210,242,.12) 1px,transparent 1px),linear-gradient(90deg,rgba(153,210,242,.12) 1px,transparent 1px);
  background-size:34px 34px;mask-image:linear-gradient(100deg,#000,transparent 86%);
}
.hero:after{
  content:"SENTINEL";position:absolute;right:240px;bottom:-60px;z-index:-1;pointer-events:none;
  color:rgba(226,244,255,.035);font:900 clamp(100px,14vw,205px)/1 var(--display);letter-spacing:.04em;
}
.hero-copy{position:relative;z-index:1;min-width:0}
.hero-kicker{font:10px var(--mono);letter-spacing:.14em;color:#a5e6ff;text-transform:uppercase}
.hero h1{font:850 clamp(36px,4.3vw,58px)/.99 var(--display);letter-spacing:-.035em;margin:17px 0 13px;text-transform:uppercase;color:#f7fbff}
.hero h1 span{background:linear-gradient(90deg,#8bdcff 0%,#d5f3ff 48%,#ff9a92 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{color:#b8cadb;font-size:13px;line-height:1.65;max-width:670px;margin:0 0 16px}
.hero-meta{display:flex;gap:clamp(14px,2.2vw,28px);flex-wrap:wrap}
.meta-item small{display:block;color:#89a8c0;font:9px var(--mono);letter-spacing:.1em}
.meta-item b{display:block;color:#f0f7ff;font:650 12px var(--mono);margin-top:5px}
.hero-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:20px}
.hero-aside{
  position:relative;z-index:1;display:grid;grid-template-columns:124px 1fr;align-items:center;gap:18px;
  border-left:1px solid rgba(146,198,230,.25);padding-left:22px;
}
.core-visual{
  width:118px;height:118px;display:grid;place-items:center;position:relative;border:1px solid #77b9df;border-radius:34px;
  background:radial-gradient(circle at 50% 45%,rgba(139,220,255,.18),transparent 56%),linear-gradient(145deg,#1a4569,#102943);
  box-shadow:0 0 0 8px rgba(139,220,255,.035),0 18px 44px #0005,inset 0 0 28px rgba(139,220,255,.14);
  animation:coreBreathe 5s ease-in-out infinite;
}
.core-visual:before{content:"";position:absolute;inset:15px;border:1px solid #a5e5ff;border-radius:16px;transform:rotate(45deg);box-shadow:0 0 18px #8bdcff25}
.core-visual:after{content:"";position:absolute;inset:36px;border:2px solid var(--orange);border-radius:10px;box-shadow:0 0 22px #ff645d55;transform:rotate(0)}
.core-ring{position:absolute;inset:5px;border:1px dashed #bdeaff9c;border-radius:28px;animation:orbit 24s linear infinite}
.core-ring:after{content:"";position:absolute;width:7px;height:7px;left:50%;top:-4px;border-radius:50%;background:var(--lime);box-shadow:0 0 13px var(--lime)}
.core-center{position:relative;z-index:2;color:#f3fbff;font:900 17px var(--mono);letter-spacing:-.07em;text-shadow:0 0 15px #8bdcff55}
.core-readout{display:grid;gap:14px;min-width:0}
.core-state{border-bottom:1px solid rgba(149,191,220,.2);padding-bottom:9px;color:#8eaec5;font:9px var(--mono);letter-spacing:.09em}
.core-state b{display:block;color:#edf7ff;font:700 11px var(--display);letter-spacing:.035em;margin-top:5px;line-height:1.3}
.core-state b .state-dot{display:inline-block;width:7px;height:7px;background:var(--lime);border-radius:50%;box-shadow:0 0 10px var(--lime);margin:0 7px 1px 0}
.core-state b .state-dot.red{background:var(--orange);box-shadow:0 0 10px var(--orange)}
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:41px;
  border:1px solid #456985;border-radius:12px;background:linear-gradient(180deg,#1a3a58,#142e48);
  color:#d5e7f5;padding:10px 14px;font:750 10px var(--display);letter-spacing:.065em;text-transform:uppercase;
  box-shadow:0 5px 15px rgba(0,0,0,.12);transition:background .18s ease,border-color .18s ease,color .18s ease,transform .18s ease,box-shadow .18s ease;
}
.btn:hover{transform:translateY(-2px);border-color:#83c6eb;color:#fff;background:linear-gradient(180deg,#245274,#193b5c);box-shadow:0 10px 25px rgba(0,0,0,.22)}
.btn:active{transform:translateY(0) scale(.985)}
.btn.primary{background:linear-gradient(115deg,#62b7e3,#8bdcff);border-color:#9ce6ff;color:#071a2c;box-shadow:0 7px 22px rgba(73,166,214,.22)}
.btn.primary:hover{background:linear-gradient(115deg,#8bdcff,#c3f0ff);border-color:#d2f5ff;color:#061725;box-shadow:0 12px 28px rgba(73,166,214,.3)}
.btn.danger{color:#ffb4b2;border-color:#89525a;background:linear-gradient(180deg,#512b38,#341c2a)}
.btn.danger:hover{background:linear-gradient(180deg,#713747,#492331);border-color:#ff8580;color:#fff}
.btn.ghost{background:rgba(9,25,42,.48);border-color:#385a75;color:#a9c3d7;box-shadow:none}
.btn.active{border-color:var(--lime);color:var(--lime);background:#173b57}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none;box-shadow:none}
.metric-row{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:16px 0 17px}
.metric{
  position:relative;isolation:isolate;min-width:0;overflow:hidden;padding:17px 17px 15px;
  border:1px solid rgba(86,132,168,.38);border-radius:19px;
  background:linear-gradient(145deg,rgba(19,43,66,.94),rgba(12,29,48,.96));
  box-shadow:0 11px 30px rgba(0,0,0,.15),inset 0 1px 0 rgba(255,255,255,.035);
  transition:transform .2s ease,border-color .2s ease,background .2s ease,box-shadow .2s ease;
}
.metric:before{content:"";position:absolute;z-index:-1;right:-30px;top:-45px;width:120px;height:120px;border:1px solid rgba(139,220,255,.11);border-radius:50%;box-shadow:0 0 0 13px rgba(139,220,255,.025),0 0 0 27px rgba(139,220,255,.018)}
.metric:after{content:"";position:absolute;left:17px;right:17px;bottom:0;height:2px;background:linear-gradient(90deg,var(--lime),transparent 76%);opacity:.48}
.metric:hover{transform:translateY(-3px);border-color:#5e9ac0;background:linear-gradient(145deg,rgba(25,57,84,.98),rgba(13,34,55,.98));box-shadow:0 18px 38px rgba(0,0,0,.24)}
.metric-action{cursor:pointer}
.metric-action:focus-visible{outline-offset:4px}
.metric-label{color:#91acc3;font:9px var(--mono);letter-spacing:.11em}
.metric-value{font:760 clamp(21px,2vw,28px)/1.12 var(--display);margin:9px 0 4px;white-space:nowrap;color:#f1f8ff;font-variant-numeric:tabular-nums}
.metric-foot{font-size:11px;color:#93a9bd;line-height:1.4;min-height:16px}
.meter{height:5px;background:#223d57;border-radius:99px;margin-top:12px;overflow:hidden}
.meter i{display:block;height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,#4a9dcb,var(--lime),#ff7774);box-shadow:0 0 12px #8bdcff55;transition:width .55s cubic-bezier(.2,.7,.2,1)}
.grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(290px,.85fr);gap:14px}
.grid.equal{grid-template-columns:repeat(2,minmax(0,1fr))}
.grid.triple{grid-template-columns:repeat(3,minmax(0,1fr))}
.panel{
  position:relative;min-width:0;overflow:hidden;padding:21px;border:1px solid rgba(76,122,157,.37);border-radius:22px;
  background:linear-gradient(145deg,rgba(16,34,54,.96),rgba(11,27,45,.97));
  box-shadow:var(--shadow-card),inset 0 1px 0 rgba(255,255,255,.035);
  transition:border-color .22s ease,transform .22s ease,box-shadow .22s ease;
}
.panel:before{content:"";position:absolute;top:0;left:24px;right:24px;height:1px;background:linear-gradient(90deg,transparent,rgba(139,220,255,.48),transparent);opacity:.7}
.panel:hover{border-color:rgba(111,168,207,.62);box-shadow:0 20px 52px rgba(0,0,0,.23),inset 0 1px 0 rgba(255,255,255,.045)}
.panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:15px;padding-bottom:14px;border-bottom:1px solid rgba(98,144,178,.2)}
.panel-title{font:760 12px var(--display);letter-spacing:.085em;color:#edf6ff;text-transform:uppercase}
.panel-sub{font-size:11px;line-height:1.5;color:#9ab0c4;margin-top:5px}
.chart-wrap{height:210px;position:relative}
.chart-wrap canvas{display:block;width:100%;height:100%}
.legend{display:flex;gap:17px;flex-wrap:wrap;color:#9bb0c3;font:9px var(--mono);margin-top:11px}
.legend i{display:inline-block;width:10px;height:3px;border-radius:99px;margin-right:6px;background:var(--lime);vertical-align:middle;box-shadow:0 0 8px #8bdcff66}
.legend i.red{background:#ff7774;box-shadow:0 0 8px #ff777455}
.sensor-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.sensor{display:flex;justify-content:space-between;align-items:center;gap:10px;min-width:0;padding:11px 12px;border:1px solid #304e69;border-radius:13px;background:rgba(20,43,65,.8);transition:.18s}
.sensor:hover{border-color:#6298bb;background:rgba(26,57,84,.9)}
.sensor strong{display:block;font:700 10px var(--display);letter-spacing:.035em;color:#e4f1fb}
.sensor small{display:block;color:#92a9bf;font-size:10px;margin-top:4px;line-height:1.4}
.sensor-state{font:9px var(--mono);color:var(--lime);white-space:nowrap}
.sensor-state.degraded,.sensor-state.partial{color:var(--amber)}
.sensor-state.disabled,.sensor-state.optional{color:#829bb0}
.alert-list,.event-list,.driver-list,.result-list,.audit-list,.insight-list{display:grid;gap:8px}
.alert-card{
  border:1px solid #40536a;border-left:3px solid var(--amber);border-radius:14px;
  padding:12px 14px;background:rgba(27,43,61,.78);transition:background .18s,border-color .18s;
}
.alert-card:hover{background:rgba(34,55,77,.88);border-color:#58718d}
.alert-card.critical{border-left-color:var(--red)}
.alert-card.info{border-left-color:var(--lime)}
.alert-card.medium{border-left-color:var(--amber)}
.alert-row{display:flex;align-items:center;justify-content:space-between;gap:10px}
.alert-row strong{font:700 12px var(--display);letter-spacing:.01em;color:#f1f7ff}
.alert-sev{color:var(--amber);font:9px var(--mono);letter-spacing:.07em;white-space:nowrap}
.alert-card.critical .alert-sev{color:var(--red)}
.alert-card p{font-size:11px;line-height:1.5;color:#aabdd0;margin:7px 0 0}
.event{
  display:grid;grid-template-columns:38px minmax(0,1fr) auto;gap:11px;align-items:start;
  padding:12px;border:1px solid #2d4b67;border-radius:15px;background:rgba(18,39,60,.84);
  transition:background .18s,border-color .18s,transform .18s;
}
.event:hover{border-color:#6599bd;background:rgba(25,52,77,.95);transform:translateY(-1px)}
.event-icon{width:36px;height:36px;display:grid;place-items:center;border:1px solid #426b8a;border-radius:11px;background:#193b59;color:var(--lime);font:11px var(--mono)}
.event-name{font:700 11px var(--display);letter-spacing:.01em;overflow-wrap:anywhere;color:#eaf4fc}
.event-desc{font-size:10px;line-height:1.5;color:#92abc0;margin-top:4px;overflow-wrap:anywhere}
.event-time{font:9px var(--mono);color:#839db4;white-space:nowrap}
.event details{margin-top:8px;color:#a3b8ca;font-size:10px}
.event summary{cursor:pointer;letter-spacing:.06em;color:var(--lime);font:700 9px var(--mono)}
.event pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:280px;overflow:auto;background:#081828;border:1px solid #2e4d68;padding:12px;border-radius:12px;color:#c7dced;font:10px/1.55 var(--mono)}
.scroll-list{max-height:560px;overflow:auto;padding-right:4px;scrollbar-width:thin;scrollbar-color:#456a87 transparent}
.empty{border:1px dashed #45627c;border-radius:16px;padding:24px 17px;text-align:center;color:#9ab0c5;font-size:12px;line-height:1.55;background:rgba(12,29,47,.75)}
.search-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:9px;margin-bottom:13px}
.field,.select,.textarea{
  width:100%;min-width:0;border:1px solid #3a5c78;border-radius:12px;background:#091b2c;color:#edf6ff;
  padding:11px 13px;font:12px "Segoe UI Variable","Aptos","Segoe UI",sans-serif;transition:border-color .18s,box-shadow .18s,background .18s;
}
.field::placeholder,.textarea::placeholder{color:#7894ac}
.field:focus,.select:focus,.textarea:focus{border-color:var(--lime);outline:none;box-shadow:0 0 0 3px #8bdcff18;background:#0b2033}
.textarea{min-height:110px;resize:vertical;line-height:1.6}
.system-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.info-card{border:1px solid #304e69;border-radius:15px;padding:14px;background:linear-gradient(145deg,rgba(22,46,69,.88),rgba(15,34,54,.88));min-width:0;transition:border-color .18s,transform .18s}
.info-card:hover{border-color:#5b8caf;transform:translateY(-2px)}
.info-card small{display:block;color:#90a9bf;font:9px var(--mono);letter-spacing:.09em}
.info-card strong{display:block;font:700 13px var(--display);margin-top:7px;overflow-wrap:anywhere;color:#edf6ff}
.info-card p{font-size:11px;line-height:1.5;color:#9bb1c5;margin:6px 0 0;overflow-wrap:anywhere}
.button-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.section-head .btn{flex:0 0 auto}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px;margin:13px 0}
.form-grid label,.model-select-grid label{display:block;color:#a9bfd2;font:10px var(--mono);letter-spacing:.06em;margin-bottom:7px}
.toggle{
  display:flex;align-items:flex-start;gap:11px;padding:14px;border:1px solid #34536f;
  background:linear-gradient(145deg,rgba(21,44,67,.94),rgba(14,32,51,.92));border-radius:15px;min-width:0;
  transition:border-color .18s,background .18s,transform .18s;
}
.toggle:hover{border-color:#6195b9;background:linear-gradient(145deg,rgba(27,57,84,.96),rgba(16,39,60,.94));transform:translateY(-1px)}
.toggle input{accent-color:var(--lime);width:16px;height:16px;flex:0 0 16px;margin:3px 0 0}
.toggle strong{display:block;font:700 12px var(--display);letter-spacing:.005em;color:#e9f4fd}
.toggle small{display:block;color:#9cb2c6;font-size:10px;margin-top:5px;line-height:1.5}
.interval-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:14px 0}
.interval{padding:12px;border:1px solid #304e69;background:rgba(17,39,60,.82);border-radius:14px}
.interval label{display:block;color:#9db5c9;font:9px var(--mono);letter-spacing:.065em;margin-bottom:8px}
.interval input{width:100%;background:#091b2c;border:1px solid #3a5a76;color:#edf6ff;padding:9px 10px;font:11px var(--mono);border-radius:10px}
.action-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.action-tile{
  display:flex;flex-direction:column;align-items:flex-start;min-height:91px;text-align:left;padding:15px;
  border:1px solid #3b5a75;border-radius:16px;background:linear-gradient(145deg,#183b5a,#112b45);color:#e5f2fc;
  transition:border-color .18s,background .18s,transform .18s,box-shadow .18s;
}
.action-tile:hover{border-color:#8bdcff;background:linear-gradient(145deg,#205176,#173a5b);transform:translateY(-2px);box-shadow:0 12px 27px #0003}
.action-tile:active{transform:scale(.99)}
.action-tile b{font:750 11px var(--display);letter-spacing:.04em}
.action-tile small{font-size:10px;line-height:1.45;color:#a6c0d5;margin-top:7px}
.note{font-size:11px;color:#9bb1c5;padding:9px 0;line-height:1.55}
.ai-shell{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(285px,.85fr);gap:14px}
.ai-answer{
  border:1px solid #3a5f7d;border-left:3px solid var(--lime);border-radius:16px;
  background:linear-gradient(145deg,#0b1c2d,#10263c);padding:16px;color:#d8e7f3;
  font:12px/1.7 "Segoe UI Variable","Aptos","Segoe UI",sans-serif;white-space:pre-wrap;overflow-wrap:anywhere;min-height:100px;
}
.ai-reference{display:block;border:1px solid #345570;border-radius:12px;padding:10px 12px;color:var(--lime);font-size:11px;background:#122b43}
.ai-reference:hover{border-color:var(--lime);color:#fff;background:#183b59}
.model-card{border:1px solid #345570;padding:13px;background:#142c43;border-radius:14px}
.model-card strong{display:block;color:#edf6ff;font:700 11px var(--mono);overflow-wrap:anywhere}
.model-card small{display:block;color:#9ab1c5;font-size:10px;margin-top:5px}
.driver-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:12px;align-items:center;border:1px solid #304e69;border-radius:13px;padding:11px 13px;background:#142a40}
.driver-row strong{display:block;font:700 11px var(--display);overflow-wrap:anywhere;color:#eaf4fc}
.driver-row small{display:block;color:#94acc1;font-size:10px;margin-top:4px}
.driver-state{font:9px var(--mono);color:var(--lime)}
.driver-state.unsigned{color:var(--red)}
.disk-item{border:1px solid #304e69;background:#142a40;padding:13px;border-radius:14px}
.disk-top{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:11px}
.disk-meter{height:6px;background:#2b4863;margin-top:10px;border-radius:99px;overflow:hidden}
.disk-meter i{display:block;height:100%;background:linear-gradient(90deg,#539acb,var(--lime));border-radius:99px}
.knowledge-card{border:1px solid #304e69;background:#142a40;padding:14px;border-radius:15px}
.knowledge-card strong{display:block;font:700 12px var(--display);color:#edf6ff}
.knowledge-card small{display:block;color:#8eaac1;font:9px var(--mono);margin-top:5px}
.knowledge-card p{font-size:11px;color:#adc0d1;line-height:1.55}
.command-line{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:11px 13px;border:1px solid #304e69;border-radius:13px;background:#142a40}
.command-line strong{font:700 11px var(--display);letter-spacing:.015em;color:#eaf4fc}
.command-line small{font:9px var(--mono);color:#91a9bf}
.audit-list .command-line{border-left:3px solid #4d7898}
.control-stack{display:grid;gap:13px}
.control-panel .panel-head{margin-bottom:16px}
.control-master{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:20px;padding:18px;border:1px solid #3e6685;border-radius:18px;background:linear-gradient(125deg,rgba(29,67,98,.75),rgba(17,42,65,.82))}
.control-master h3{font:750 19px var(--display);margin:5px 0 7px;color:#eff7ff}
.control-master p{font-size:12px;line-height:1.6;color:#b2c7d9;margin:0;max-width:760px}
.master-switch{display:flex;align-items:center;justify-content:center;gap:9px;min-width:166px;border:1px solid #517a99;border-radius:14px;padding:12px;background:#102941;color:#a8c4d9;font:700 10px var(--mono);letter-spacing:.055em}
.master-switch input{accent-color:var(--lime);width:17px;height:17px}
.master-switch span{white-space:nowrap}
.control-copy{font-size:12px;color:#b5c8d9;line-height:1.55}
.control-divider{height:1px;background:rgba(109,153,187,.2);margin:15px 0}
.control-group-title{font:750 12px var(--display);color:#e9f4fc;letter-spacing:.055em;text-transform:uppercase}
.control-footnote{margin-top:12px;padding:11px 13px;border:1px solid #34546f;border-radius:13px;background:rgba(13,32,51,.72);color:#a2b8cb;font-size:11px;line-height:1.55}
.control-footnote.warning{border-color:#705b42;background:rgba(65,49,32,.25);color:#e6c99b}
.control-footnote.privacy{border-color:#426b69;background:rgba(20,58,57,.24);color:#a8d9d2}
.control-status{font:9px var(--mono);color:#92aac0;letter-spacing:.08em}
.control-savebar{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap}
.control-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.model-select-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}
.feature-command-disabled{opacity:.42;filter:saturate(.6)}
.task-list{display:grid;gap:8px}
.task-row,.task-history-row{
  border:1px solid #304e69;border-radius:14px;background:rgba(19,42,64,.88);padding:13px;transition:border-color .18s,background .18s;
}
.task-row:hover,.task-history-row:hover{border-color:#5f91b5;background:rgba(25,53,79,.96)}
.task-row-head,.task-history-row{display:flex;justify-content:space-between;align-items:center;gap:12px}
.task-row-head>div,.task-history-row>div{display:grid;gap:4px;min-width:0}
.task-row-head strong,.task-history-row strong,.process-row strong{font:700 12px var(--display);color:#edf6ff}
.task-row-head small,.task-history-row small,.process-row small{font-size:10px;color:#97aec2;line-height:1.4}
.task-meta,.task-tool-meta{padding-top:10px;margin-top:10px;border-top:1px solid rgba(111,158,191,.2);font-size:10px;color:#9fb6ca;line-height:1.55}
.task-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}
.task-actions .btn{min-height:34px;padding:7px 10px;font-size:9px}
.task-pill{display:inline-flex;align-items:center;border:1px solid #456782;border-radius:999px;padding:5px 9px;font:9px var(--mono);white-space:nowrap;color:#b5c9da;background:#17324d}
.task-pill.running,.task-pill.watching{border-color:#4b8494;color:#8ee8d8;background:#123c45}
.task-pill.completed,.task-pill.available{border-color:#3f8277;color:#9aebcb;background:#12392f}
.task-pill.completed-with-warnings,.task-pill.partial,.task-pill.degraded{border-color:#846d47;color:#f5d08e;background:#3a3021}
.task-pill.failed,.task-pill.unavailable,.task-pill.critical{border-color:#8a4e55;color:#ffaaa9;background:#42242d}
.task-pill.disabled,.task-pill.manual-only,.task-pill.unknown{border-color:#4b6175;color:#a0b2c2;background:#1a2c3d}
.task-tool{border:1px solid #304e69;border-radius:14px;background:#122a41;padding:13px}
.task-tool summary{display:flex;align-items:center;justify-content:space-between;gap:10px;cursor:pointer;list-style:none;color:#e5f1fa;font-size:11px}
.task-tool summary::-webkit-details-marker{display:none}
.task-tool summary:after{content:"＋";font:13px var(--mono);color:var(--lime);margin-left:8px}
.task-tool[open] summary:after{content:"−"}
.task-tool summary strong{font:700 12px var(--display);color:#ecf5ff;text-transform:capitalize}
.task-tool-meta{padding-top:10px;margin-top:10px;border-top:1px solid #324e68}
.process-row{display:flex;justify-content:space-between;align-items:center;gap:10px;border:1px solid #304b66;border-radius:12px;background:#14283d;padding:10px 12px}
.process-row>div{display:grid;gap:2px}
.process-row>small{font:10px var(--mono);color:#91abc2;text-align:right}
.ai-suggestion{border:1px solid #457596;border-radius:15px;background:linear-gradient(145deg,#173a58,#102a43);padding:14px}
.ai-suggestion p{font-size:11px;line-height:1.5;color:#b4cada}
.toast-stack{position:fixed;z-index:1200;right:20px;bottom:20px;display:grid;gap:9px;width:min(390px,calc(100vw - 40px))}
.toast{border:1px solid #54718c;border-left:3px solid var(--lime);border-radius:14px;background:rgba(13,31,49,.97);color:#e7f2fb;padding:13px 15px;font-size:12px;box-shadow:0 17px 45px #0008;backdrop-filter:blur(15px);animation:toastIn .2s ease}
.toast.warn{border-left-color:var(--amber)}
.toast.error{border-left-color:var(--red)}
/* Searchable command palette */
.command-overlay{
  position:fixed;inset:0;z-index:1150;display:none;place-items:start center;padding:12vh 18px 24px;
  background:rgba(3,10,18,.72);backdrop-filter:blur(12px);
}
.command-overlay.open{display:grid}
.command-dialog{
  width:min(650px,100%);max-height:min(72vh,720px);display:flex;flex-direction:column;overflow:hidden;
  border:1px solid #527b9a;border-radius:24px;background:linear-gradient(145deg,#132d46,#0b1d30);
  box-shadow:0 35px 100px #000a,inset 0 1px 0 rgba(255,255,255,.06);animation:paletteIn .2s ease;
}
.command-dialog-head{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:18px 20px 12px}
.palette-eyebrow{font:9px var(--mono);color:#8eabc2;letter-spacing:.13em}
.palette-title{font:700 16px var(--display);color:#eff7ff;margin-top:3px}
.palette-close{width:34px;height:34px;border:1px solid #3b5d78;border-radius:10px;background:#10263b;color:#a8c2d6;font:16px var(--mono)}
.palette-close:hover{border-color:var(--lime);color:#fff}
.palette-input-wrap{display:flex;align-items:center;gap:11px;margin:0 18px 12px;padding:0 14px;border:1px solid #527996;border-radius:14px;background:#081a2b}
.palette-search-icon{font:20px var(--mono);color:var(--lime)}
.palette-input{width:100%;height:52px;border:0!important;outline:0!important;box-shadow:none!important;background:transparent!important;color:#eff8ff;font-size:14px}
.command-results{display:grid;gap:5px;overflow:auto;padding:0 12px 12px;scrollbar-width:thin;scrollbar-color:#4d7593 transparent}
.palette-group-label{padding:11px 9px 5px;color:#7694ad;font:9px var(--mono);letter-spacing:.12em;text-transform:uppercase}
.palette-item{
  display:grid;grid-template-columns:38px minmax(0,1fr) auto;align-items:center;gap:12px;width:100%;text-align:left;
  border:1px solid transparent;border-radius:13px;background:transparent;color:#d8e8f5;padding:10px 11px;transition:.15s;
}
.palette-item:hover,.palette-item.selected{border-color:#446a88;background:#1b3b59}
.palette-item:disabled{opacity:.38;cursor:not-allowed}
.palette-icon{width:36px;height:36px;display:grid;place-items:center;border:1px solid #385e7b;border-radius:11px;background:#153651;color:var(--lime);font:10px var(--mono)}
.palette-item strong{display:block;font:700 12px var(--display);color:#edf6ff}
.palette-item small{display:block;font-size:10px;color:#94adc2;margin-top:3px;line-height:1.35}
.palette-shortcut{font:9px var(--mono);color:#7f9bb2}
.palette-empty{padding:24px 12px;text-align:center;color:#9bb2c7;font-size:12px}
.palette-footer{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:12px 19px;border-top:1px solid #2b4a65;color:#8da8bd;font:9px var(--mono)}
@media(max-width:1320px){
  .app{grid-template-columns:246px minmax(0,1fr)}
  .metric-row{grid-template-columns:repeat(3,minmax(0,1fr))}
  .hero{grid-template-columns:minmax(0,1fr) 270px}
  .grid.triple{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:1060px){
  .app{grid-template-columns:82px minmax(0,1fr)}
  .rail{padding:17px 9px}
  .rail-brand{justify-content:center;padding:8px 0 16px}
  .brand-lockup,.nav-group-label,.rail-bottom{display:none}
  .nav-group{gap:7px}
  .nav-btn{justify-content:center;padding:0 6px}
  .nav-btn .nav-icon{width:38px;height:38px;flex-basis:38px}
  .nav-btn small{display:none}
  .hero{grid-template-columns:1fr}
  .hero-aside{border-left:0;border-top:1px solid rgba(146,198,230,.25);padding:18px 0 0;grid-template-columns:118px 1fr}
  .grid,.grid.equal,.ai-shell{grid-template-columns:1fr}
}
@media(max-width:760px){
  .app{display:block;padding-bottom:77px}
  .rail{
    position:fixed;top:auto;bottom:0;left:0;right:0;width:100%;height:72px;min-height:0;
    flex-direction:row;justify-content:flex-start;gap:0;padding:7px 7px calc(7px + env(safe-area-inset-bottom));
    border-right:0;border-top:1px solid #3c607d;background:rgba(7,20,34,.97);backdrop-filter:blur(18px);
  }
  .rail-brand,.rail-spacer,.rail-state,.rail-bottom{display:none}
  .rail-nav{width:100%;display:flex;flex-direction:row;overflow-x:auto;overflow-y:hidden;gap:8px;padding:0;scrollbar-width:none}
  .rail-nav::-webkit-scrollbar{display:none}
  .nav-group{display:contents}
  .nav-btn{min-width:74px;width:auto;min-height:56px;flex:0 0 auto;display:flex;flex-direction:column;justify-content:center;gap:3px;padding:5px 8px;border-radius:12px}
  .nav-btn .nav-icon{width:25px;height:23px;flex:0 0 23px;border:0;background:transparent;font-size:9px}
  .nav-btn small{display:block;font-size:8px;letter-spacing:.025em;white-space:nowrap}
  main{padding:0 13px 28px}
  .topbar{position:relative;min-height:0;align-items:flex-start;flex-direction:column;gap:12px;padding:17px 0;margin-bottom:18px}
  .top-right{width:100%;justify-content:flex-start;gap:6px}
  .top-right .clock{margin-right:auto}
  .icon-btn{min-height:36px;padding:8px 10px;font-size:9px}
  .view-title{font-size:20px}
  .section-head{align-items:flex-start;flex-direction:column;gap:12px}
  .section-head .btn{width:100%}
  .hero{min-height:0;padding:21px;border-radius:22px;gap:20px}
  .hero h1{font-size:clamp(34px,9vw,46px)}
  .hero-aside{grid-template-columns:92px 1fr}
  .core-visual{width:88px;height:88px;border-radius:25px}
  .core-visual:before{inset:12px}.core-visual:after{inset:27px}
  .core-state{font-size:8px}.core-state b{font-size:10px}
  .metric-row{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
  .metric{padding:14px}
  .metric-value{font-size:23px}
  .grid,.grid.equal,.grid.triple,.ai-shell{grid-template-columns:1fr}
  .form-grid,.system-cards,.control-grid,.model-select-grid{grid-template-columns:1fr}
  .interval-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .panel{padding:16px;border-radius:18px}
  .panel-head{gap:8px}
  .panel-title{font-size:11px}
  .panel-sub{font-size:10px}
  .section-title{font-size:25px}
  .section-description{font-size:12px}
  .event{grid-template-columns:34px minmax(0,1fr)}
  .event-time{grid-column:2}
  .driver-row{grid-template-columns:minmax(0,1fr) auto}
  .driver-row>small{grid-column:1}
  .control-master{grid-template-columns:1fr}
  .master-switch{width:100%}
  .search-row{grid-template-columns:minmax(0,1fr)}
  .command-overlay{padding-top:7vh}
}
@media(max-width:430px){
  .metric-row{grid-template-columns:repeat(2,minmax(0,1fr))}
  .interval-grid,.control-grid,.model-select-grid{grid-template-columns:1fr}
  .hero-actions .btn{flex:1 1 100%}
  .hero-meta{gap:12px}
  .hero-aside{grid-template-columns:78px 1fr;gap:12px}
  .core-visual{width:74px;height:74px;border-radius:21px}
  .core-visual:before{inset:10px}.core-visual:after{inset:23px}
  .core-center{font-size:13px}
  .core-state b{font-size:9px}
  .palette-shortcut{display:none}
  .command-dialog{border-radius:19px}
}
@media(prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.01ms!important}
}

</style>
</head>
<body>
<div class="ambient"></div><canvas id="starfield"></canvas>
<div class="boot" id="boot">
 <div class="boot-grid"></div>
 <div class="boot-card">
  <div class="boot-emblem"><div class="boot-mark">AIE</div></div>
  <div class="boot-title">SENTINEL / COMMAND CORE</div>
  <div class="boot-sub">NATIVE WINDOWS INTELLIGENCE PLATFORM / NODE 01</div>
  <div class="boot-copy">Establishing the local command channel. Mounting persistent evidence. Initializing approved Windows observers and local intelligence services.</div>
  <div class="boot-track"><div class="boot-progress" id="bootProgress"></div></div>
  <div class="boot-stage"><span id="bootStage">INITIALIZING CORE</span><b id="bootPercent">00%</b></div>
  <div class="boot-log" id="bootLog"><div>Sentinel interface loader ready</div></div>
  <button class="boot-skip" id="bootSkip">ENTER COMMAND DECK &gt;&gt;</button>
 </div>
</div>
<div class="app" id="app">
 <aside class="rail">
  <div class="rail-brand"><div class="brand-mini"></div><div class="brand-lockup"><strong>AIE / SENTINEL</strong><small>PRIME SYSTEMS CONSOLE</small></div></div>
  <nav class="rail-nav" aria-label="Sentinel workspaces">
   <div class="nav-group">
    <div class="nav-group-label">WORKSPACE</div>
    <button class="nav-btn active" data-view="cockpit" title="Command Center" aria-current="page"><span class="nav-icon">01</span><small>COMMAND</small></button>
    <button class="nav-btn" data-view="system" title="System Intelligence"><span class="nav-icon">02</span><small>SYSTEM INTELLIGENCE</small></button>
    <button class="nav-btn" data-view="telemetry" title="Telemetry"><span class="nav-icon">03</span><small>TELEMETRY</small></button>
   </div>
   <div class="nav-group">
    <div class="nav-group-label">INTELLIGENCE</div>
    <button class="nav-btn" data-view="evidence" title="Evidence Vault"><span class="nav-icon">04</span><small>EVIDENCE VAULT</small></button>
    <button class="nav-btn" data-view="ai" title="AI Laboratory"><span class="nav-icon">05</span><small>AI LABORATORY</small></button>
    <button class="nav-btn" data-view="knowledge" title="Knowledge Base"><span class="nav-icon">08</span><small>KNOWLEDGE BASE</small></button>
   </div>
   <div class="nav-group">
    <div class="nav-group-label">OPERATIONS</div>
    <button class="nav-btn" data-view="autonomy" title="Feature controls and automation"><span class="nav-icon">06</span><small>FEATURE CONTROL</small></button>
    <button class="nav-btn" data-view="tasks" title="Agent Task Manager"><span class="nav-icon">07</span><small>TASK MANAGER</small></button>
   </div>
  </nav>
  <div class="rail-spacer"></div><div class="rail-state" id="railLed"></div><div class="rail-bottom">WINDOWS 11 / LOCAL EXECUTION / USER CONTROL</div>
 </aside>
 <main>
  <header class="topbar">
   <div class="top-left"><div class="top-mark"></div><div><div class="eyebrow">AIE / SENTINEL PRIME — WINDOWS NODE / 01</div><div class="view-title" id="viewTitle">COMMAND CENTER</div></div></div>
   <div class="top-right"><span class="clock" id="clock">--:--:--</span><button class="icon-btn" id="paletteBtn" title="Open searchable command palette" aria-label="Open command palette">⌕ COMMANDS <kbd>Ctrl K</kbd></button><span class="system-badge" id="liveBadge"><i class="led"></i>CONNECTING</span><button class="icon-btn" id="notifyBtn">ALERTS</button><button class="icon-btn" id="refreshBtn">SYNC / F5</button><button class="icon-btn" id="stopBtn" style="border-color:#713e37;color:#ffaaa0">STOP WORKER</button></div>
  </header>

  <section class="screen active" data-screen="cockpit">
   <div class="hero">
    <div class="hero-copy">
     <div class="hero-kicker">SENTINEL PRIME / AUTONOMOUS SYSTEM INTELLIGENCE</div>
      <h1>YOUR SYSTEM.<br><span>IN COMMAND.</span></h1>
      <p id="heroDesc">Local Windows observation, persistent evidence and specialist AI analysis. Diagnostics run locally; changes to your operating system remain under your control.</p>
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
    <div class="hero-aside">
      <div class="core-visual"><div class="core-ring"></div><div class="core-center">AIE/01</div></div>
      <div class="core-readout">
       <div class="core-state">OBSERVATION<b><i class="state-dot"></i>USER MODE</b></div>
       <div class="core-state">INTELLIGENCE<b><i class="state-dot"></i>LOCAL MODEL PATH</b></div>
       <div class="core-state">EXECUTION<b><i class="state-dot red"></i>READ-ONLY DIAGNOSTICS</b></div>
      </div>
     </div>
   </div>
   <div class="metric-row">
    <div class="metric metric-action" data-view-jump="telemetry" role="button" tabindex="0" aria-label="Open resource telemetry"><div class="metric-label">CPU LOAD</div><div class="metric-value" id="cpuValue">—%</div><div class="metric-foot">Host processor · live sample</div><div class="meter"><i id="cpuMeter"></i></div></div>
    <div class="metric metric-action" data-view-jump="telemetry" role="button" tabindex="0" aria-label="Open resource telemetry"><div class="metric-label">MEMORY AVAILABLE</div><div class="metric-value" id="ramValue">— GB</div><div class="metric-foot" id="ramSub">System RAM headroom</div><div class="meter"><i id="ramMeter"></i></div></div>
    <div class="metric metric-action" data-view-jump="evidence" role="button" tabindex="0" aria-label="Open evidence vault"><div class="metric-label">EVIDENCE RECORDS</div><div class="metric-value" id="eventValue">—</div><div class="metric-foot">Local SQLite event vault</div><div class="meter"><i id="eventMeter"></i></div></div>
    <div class="metric metric-action" data-view-jump="autonomy" role="button" tabindex="0" aria-label="Open feature control"><div class="metric-label">SENSOR MATRIX</div><div class="metric-value" id="sensorValue">—</div><div class="metric-foot" id="sensorSub">Provider availability</div><div class="meter"><i id="sensorMeter"></i></div></div>
    <div class="metric metric-action" data-view-jump="system" role="button" tabindex="0" aria-label="Open system intelligence"><div class="metric-label">POSTURE SIGNALS</div><div class="metric-value" id="alertValue">—</div><div class="metric-foot" id="alertSub">Awaiting deep inventory</div><div class="meter"><i id="alertMeter"></i></div></div>
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
     <div class="form-grid"><div><label class="panel-sub" for="aiMode">DIAGNOSTIC SPECIALIST</label><select class="select" id="aiMode"><option value="general">General Windows analyst</option><option value="security">Security & protection analyst</option><option value="performance">Performance engineer</option><option value="drivers">Drivers & Plug-and-Play</option><option value="storage">Storage & battery specialist</option><option value="network">Network diagnostician</option><option value="maintenance">Maintenance &amp; settings advisor</option></select></div><div><label class="panel-sub" for="aiQuestion">PROMPT</label><input class="field" id="aiQuestion" maxlength="500" placeholder="What should Sentinel investigate?"></div></div>
     <div class="button-row" style="margin-top:10px"><button class="btn primary" id="askBtn">✳ ASK LOCAL AI</button><span class="panel-sub" id="aiRequestState">Inference shares one memory lock with scheduled AI analysis.</span></div>
     <div class="ai-answer" id="aiAnswer" style="margin-top:12px">Select a specialist and ask a question about your machine's observed metadata.</div>
     <div id="aiReferences" class="result-list" style="margin-top:9px"></div><div class="control-footnote warning">Maintenance mode can suggest Sentinel profile changes for you to review and save. Windows security settings, registry values, services and processes are never changed automatically.</div>
    </section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">LOCAL MODEL INVENTORY</div><div class="panel-sub">Installed models only · discovered from local Ollama</div></div><button class="btn ghost" id="modelRefresh">↻ DISCOVER</button></div><div class="result-list" id="modelList"><div class="empty">Discovering installed Ollama models…</div></div><div class="note" id="modelMemory">RAM profile unavailable.</div></section>
   </div>
   <div class="grid equal" style="margin-top:12px">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">FAST TRIAGE / SIGNALS</div><div class="panel-sub" id="triageModel">Awaiting local analysis</div></div><span class="tag" id="triageState">IDLE</span></div><div class="ai-answer" id="triageResult">No assessment stored.</div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">INDEPENDENT REVIEW</div><div class="panel-sub" id="reviewModel">Awaiting reviewer</div></div><span class="tag" id="reviewState">IDLE</span></div><div class="ai-answer" id="reviewResult">No reviewer assessment stored.</div></section>
   </div>
  </section>

  <section class="screen" data-screen="autonomy">
   <div class="section-head"><div><div class="section-label">SENSOR SETTINGS / SCHEDULES / AUTOMATION</div><div class="section-title">FEATURES &amp; AUTOMATION</div><div class="section-description">Enable or disable each collector, choose when jobs run, configure automatic review triggers, and inspect what Sentinel will do. Background schedules only run while the worker is online and observation is not paused. Sentinel remains read-only and advisory.</div></div><span class="tag">LOCAL CONFIG</span></div>
   <div class="grid">
    <div class="control-stack">
     <section class="panel control-panel">
      <div class="panel-head"><div><div class="panel-title">AUTOMATION MASTER CONTROL</div><div class="panel-sub">One switch for scheduled jobs and event-driven AI reviews. Baseline sensors remain governed by their own switches.</div></div><span class="tag" id="automationLive">CHECKING PROFILE</span></div>
      <div class="control-master">
       <div><div class="section-label">AUTONOMOUS OPERATION</div><h3>Let Sentinel run its scheduled work</h3><p>When enabled, Sentinel runs the configured inventory, registry, deep Windows, knowledge and local AI schedules. New qualifying posture or registry findings can also queue an AI review when their individual trigger switches are enabled.</p></div>
       <label class="master-switch"><input type="checkbox" id="cfgAutomation"><span id="automationSwitchText">AUTOMATION ON</span></label>
      </div>
      <div class="control-footnote" id="automationExplanation">Turning this master switch off stops periodic jobs and automatic review triggers. The live observer and enabled baseline sensors continue; you can still launch allowed one-time jobs manually.</div>
     </section>

     <div class="grid equal">
      <section class="panel control-panel">
       <div class="panel-head"><div><div class="panel-title">CONTINUOUS WINDOWS SENSORS</div><div class="panel-sub">These collectors observe system metadata during the active Sentinel worker session.</div></div><span class="tag">WORKER RESTART</span></div>
       <div class="form-grid">
        <label class="toggle"><input type="checkbox" id="cfgNetwork"><span><strong>Network telemetry</strong><small>Interface counters, TCP connection-establishment timing and DNS timing. No packet payload capture.</small></span></label>
        <label class="toggle"><input type="checkbox" id="cfgForeground"><span><strong>Foreground application changes</strong><small>Observe foreground application transitions. Window titles are a separate sensitive opt-in below.</small></span></label>
        <label class="toggle"><input type="checkbox" id="cfgProcessResources"><span><strong>Process resource sampling</strong><small>Bounded CPU, memory, thread and I/O metadata. No command lines or executable paths.</small></span></label>
       </div>
       <div class="control-group-title">Sampling cadence</div>
       <div class="interval-grid">
        <div class="interval"><label for="cfgSampleInterval">OBSERVER SAMPLE / SECONDS</label><input id="cfgSampleInterval" type="number" min="0.5" max="30" step="0.5"></div>
        <div class="interval"><label for="cfgNetworkInterval">NETWORK SAMPLE / SECONDS</label><input id="cfgNetworkInterval" type="number" min="5" max="300" step="5"></div>
        <div class="interval"><label for="cfgProcessInterval">PROCESS SAMPLE / SECONDS</label><input id="cfgProcessInterval" type="number" min="2" max="300" step="1"></div>
       </div>
       <div class="control-footnote warning">Changes to continuous sensor switches or sampling intervals require a Sentinel worker restart. Save first, then restart Sentinel so the collector pipelines are re-created with the new settings.</div>
      </section>

      <section class="panel control-panel">
       <div class="panel-head"><div><div class="panel-title">SCHEDULED INTELLIGENCE JOBS</div><div class="panel-sub">Each job can be enabled independently. The master switch above controls whether any schedule fires.</div></div><span class="tag">LIVE PROFILE</span></div>
       <div class="form-grid">
        <label class="toggle"><input type="checkbox" id="cfgInventory"><span><strong>System inventory</strong><small>Processes, installed applications, services, scheduled tasks and network interfaces.</small></span></label>
        <label class="toggle"><input type="checkbox" id="cfgRegistry"><span><strong>Registry intelligence</strong><small>Read-only allowlisted configuration snapshots and change detection.</small></span></label>
        <label class="toggle"><input type="checkbox" id="cfgDeep"><span><strong>Deep Windows inventory</strong><small>CIM, firmware, drivers, PnP, disks, BitLocker, Defender and firewall posture.</small></span></label>
        <label class="toggle"><input type="checkbox" id="cfgKnowledge"><span><strong>Microsoft knowledge crawler</strong><small>Refresh approved Microsoft Learn and Microsoft-owned GitHub references into local SQLite.</small></span></label>
        <label class="toggle"><input type="checkbox" id="cfgAI"><span><strong>Scheduled local AI review</strong><small>Evidence triage and optional independent reviewer using installed local Ollama models only.</small></span></label>
       </div>
       <div class="control-group-title">Run intervals — use minutes or hours, not raw seconds</div>
       <div class="interval-grid">
        <div class="interval"><label for="cfgInventoryInterval">SYSTEM INVENTORY / MIN</label><input id="cfgInventoryInterval" type="number" min="5" max="120" step="5"></div>
        <div class="interval"><label for="cfgRegistryInterval">REGISTRY SNAPSHOT / MIN</label><input id="cfgRegistryInterval" type="number" min="1" max="60" step="1"></div>
        <div class="interval"><label for="cfgDeepInterval">DEEP INVENTORY / MIN</label><input id="cfgDeepInterval" type="number" min="5" max="120" step="5"></div>
        <div class="interval"><label for="cfgKnowledgeInterval">KNOWLEDGE REFRESH / HOURS</label><input id="cfgKnowledgeInterval" type="number" min="1" max="168" step="1"></div>
        <div class="interval"><label for="cfgAIInterval">LOCAL AI REVIEW / MIN</label><input id="cfgAIInterval" type="number" min="1" max="60" step="1"></div>
       </div>
       <div class="control-footnote">Schedules are adopted on the next observer cycle. Jobs are bounded and independent; a busy collector is not started twice. Knowledge refresh needs outbound internet access. AI jobs need a compatible installed model and sufficient free RAM.</div>
      </section>
     </div>

     <div class="grid equal">
      <section class="panel control-panel">
       <div class="panel-head"><div><div class="panel-title">AUTOMATIC TRIGGER RULES</div><div class="panel-sub">Event-driven rules can queue local AI analysis. They do not repair or modify Windows.</div></div><span class="tag">ADVISORY ONLY</span></div>
       <div class="form-grid">
        <label class="toggle"><input type="checkbox" id="cfgPostureReview"><span><strong>Review new posture findings</strong><small>Queue an AI review when the deep inventory identifies new high or critical posture findings.</small></span></label>
        <label class="toggle"><input type="checkbox" id="cfgRegistryReview"><span><strong>Review registry configuration changes</strong><small>Queue an AI review when the registry observer reports a configuration-change event.</small></span></label>
       </div>
       <div class="control-group-title">Local posture thresholds</div>
       <div class="interval-grid">
        <div class="interval"><label for="cfgDiskThreshold">LOW DISK — FREE SPACE / %</label><input id="cfgDiskThreshold" type="number" min="1" max="30" step="1"></div>
        <div class="interval"><label for="cfgBatteryThreshold">LOW BATTERY / %</label><input id="cfgBatteryThreshold" type="number" min="5" max="40" step="1"></div>
       </div>
       <div class="control-footnote">A trigger only runs when Automation Master and Local AI are both enabled. Findings remain evidence-backed suggestions. No automatic remediation is performed.</div>
      </section>

      <section class="panel control-panel">
       <div class="panel-head"><div><div class="panel-title">ADVANCED / PRIVACY-SENSITIVE SENSORS</div><div class="panel-sub">Explicit opt-in only. All four controls require a worker restart after saving.</div></div><span class="tag">OPT-IN / RESTART</span></div>
       <div class="form-grid">
        <label class="toggle"><input type="checkbox" id="cfgEventLogs"><span><strong>Application and System Event Logs</strong><small>Metadata from allowlisted Application/System channels. No Security log, event message text or XML.</small></span></label>
        <label class="toggle"><input type="checkbox" id="cfgEtw"><span><strong>ETW process lifecycle</strong><small>Process start/stop metadata only. Availability can depend on ETW permissions and installed dependency.</small></span></label>
        <label class="toggle"><input type="checkbox" id="cfgWindowTitles"><span><strong>Foreground window titles</strong><small>Potentially sensitive title text. Disabled by default; app names alone remain separate.</small></span></label>
        <label class="toggle"><input type="checkbox" id="cfgUITree"><span><strong>UI Automation structure</strong><small>Read structural metadata only for the executable allowlist below. No control text, values or passwords.</small></span></label>
       </div>
       <div><label class="panel-sub" for="cfgUITreeApps">ALLOWED APPLICATION EXECUTABLES</label><input class="field" id="cfgUITreeApps" maxlength="300" placeholder="notepad.exe, explorer.exe"><div class="note">Use executable names only, separated by commas. Up to 20 names. The UI Automation switch stays off unless at least one allowed executable is supplied.</div></div>
       <div class="control-footnote privacy">Sentinel does not capture keystrokes, screenshots, clipboard contents, passwords, cookies, form values or window text. Keep these sensors off unless their specific metadata is needed.</div>
      </section>
     </div>

     <div class="grid equal">
      <section class="panel control-panel">
       <div class="panel-head"><div><div class="panel-title">LOCAL MODEL ROUTING</div><div class="panel-sub">Select already-installed Ollama models. Sentinel never downloads a model automatically.</div></div><button class="btn ghost" id="cfgModelRefresh">↻ DISCOVER MODELS</button></div>
       <div class="model-select-grid">
        <div><label for="cfgFastModel">FAST MODEL — ASK / TRIAGE</label><select class="select" id="cfgFastModel"><option value="">Automatic — best compatible installed model</option></select><div class="note">Prefer a compatible 3B/4B model. Ask and scheduled triage need available memory.</div></div>
        <div><label for="cfgDeepModel">INDEPENDENT REVIEW MODEL</label><select class="select" id="cfgDeepModel"><option value="">Automatic — best compatible reviewer</option></select><div class="note">Prefer a distinct 6B+ model when memory permits. Review can remain unavailable on a constrained machine.</div></div>
       </div>
       <div class="control-footnote">Model availability is discovered from the local Ollama endpoint. Choosing a model does not install it or guarantee that it will fit in currently available RAM.</div>
      </section>
      <section class="panel control-panel">
       <div class="panel-head"><div><div class="panel-title">KNOWLEDGE CRAWLER BOUNDS</div><div class="panel-sub">Tune the size of each scheduled public-reference crawl.</div></div><span class="tag">ALLOWLISTED SOURCES</span></div>
       <div class="interval-grid">
        <div class="interval"><label for="cfgKnowledgeLearnTop">LEARN RESULTS / QUERY</label><input id="cfgKnowledgeLearnTop" type="number" min="1" max="10" step="1"></div>
        <div class="interval"><label for="cfgKnowledgeGithubFiles">GITHUB FILES / REPO</label><input id="cfgKnowledgeGithubFiles" type="number" min="1" max="20" step="1"></div>
       </div>
       <div class="control-footnote">The crawler only reads approved Microsoft Learn and Microsoft-owned GitHub content. Retrieved pages are indexed in the local knowledge database; local search does not require internet after ingestion.</div>
      </section>
     </div>

     <section class="panel control-panel">
      <div class="panel-head"><div><div class="panel-title">PROFILE PRESETS & SAVE</div><div class="panel-sub">Presets only change this form. Review the switches before saving.</div></div><span class="tag">LOCAL CONFIGURATION</span></div>
      <div class="button-row" style="margin-bottom:12px"><button class="btn" data-preset="deep">⚡ DEEP WATCH</button><button class="btn" data-preset="balanced">◈ BALANCED</button><button class="btn" data-preset="quiet">◌ LOW IMPACT</button></div>
      <div class="control-copy" id="presetNote">Choose a preset, inspect the settings, then save. Sensitive sensors remain off unless you explicitly enable them.</div>
      <div class="control-divider"></div>
      <div class="control-savebar"><div class="button-row"><button class="btn primary" id="saveProfile">SAVE ALL SETTINGS</button><button class="btn ghost" id="reloadProfile">RELOAD SAVED SETTINGS</button></div><span class="control-status" id="profileSaveState">NOT SAVED</span></div>
      <div class="note" id="profileNote">Settings are read from the worker's local profile. Changes requiring collector reinitialization are clearly marked above.</div>
     </section>
    </div>
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
   <div class="control-footnote" style="margin-top:12px">Automatic sign-in startup is separate from the schedule switch. To start Sentinel whenever this Windows user signs in, run <code>aie sentinel install</code> once from PowerShell. It registers a current-user, limited-permission Task Scheduler entry; it does not install a SYSTEM service.</div>
   <section class="panel" style="margin-top:12px"><div class="panel-head"><div><div class="panel-title">AUTOMATION AUDIT TIMELINE</div><div class="panel-sub">Command dispatch and posture automation events</div></div><button class="btn ghost" data-view-jump="evidence">OPEN FULL AUDIT →</button></div><div class="audit-list" id="automationAudit"><div class="empty">No automation records yet.</div></div></section>
  </section>

  <section class="screen" data-screen="tasks">
   <div class="section-head"><div><div class="section-label">AGENT RUNTIME / INTERNAL TOOLS / JOB CONTROL</div><div class="section-title">TASK MANAGER</div><div class="section-description">Live view of actual Sentinel worker jobs, the Windows sensor/provider matrix, job history, and the latest bounded process inventory. Runtime states are recorded by the worker; progress is never simulated.</div></div><div class="button-row"><button class="btn ghost" id="taskRefresh">↻ REFRESH TASKS</button><button class="btn" data-view-jump="autonomy">FEATURE CONTROL →</button></div></div>
   <div class="metric-row">
    <div class="metric"><div class="metric-label">ACTIVE JOBS</div><div class="metric-value" id="taskActiveCount">—</div><div class="metric-foot">Background jobs running now</div></div>
    <div class="metric"><div class="metric-label">AVAILABLE TOOLS</div><div class="metric-value" id="taskToolCount">—</div><div class="metric-foot">Registered Windows providers</div></div>
    <div class="metric"><div class="metric-label">RECENT RUNS</div><div class="metric-value" id="taskRunCount">—</div><div class="metric-foot">Retained worker task records</div></div>
    <div class="metric"><div class="metric-label">QUEUED COMMANDS</div><div class="metric-value" id="taskQueueCount">—</div><div class="metric-foot">Awaiting observer dispatch</div></div>
   </div>
   <div class="grid equal task-layout">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">LIVE AGENT JOBS</div><div class="panel-sub">Real worker threads · one active run per collector</div></div><span class="tag" id="taskWorkerState">WORKER STATE UNKNOWN</span></div><div class="task-list" id="taskLiveList"><div class="empty">Waiting for worker task state.</div></div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">INTERNAL SENSOR / TOOL MATRIX</div><div class="panel-sub">Collectors and providers reported by the active Windows observer</div></div><span class="tag" id="taskProviderState">NO PROVIDER DATA</span></div><div class="task-list" id="taskToolsList"><div class="empty">Provider details will appear after the first observer cycle.</div></div></section>
   </div>
   <div class="grid equal" style="margin-top:14px">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">TASK RUN HISTORY</div><div class="panel-sub">Last 60 completed and failed worker jobs</div></div><select id="taskHistoryFilter" class="select" style="max-width:190px"><option value="all">All runs</option><option value="completed">Completed</option><option value="warnings">Warnings</option><option value="failed">Failed</option></select></div><div class="task-list scroll-list" id="taskHistoryList"><div class="empty">No task runs have been recorded yet.</div></div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">WINDOWS PROCESS SNAPSHOT</div><div class="panel-sub">Read-only inventory · process name and PID only</div></div><span class="tag" id="processSnapshotTag">NO SNAPSHOT</span></div><div class="search-row"><input class="field" id="taskProcessQuery" maxlength="100" placeholder="Filter by process name or PID"><button class="btn primary" id="taskProcessSearch">SEARCH</button></div><div class="panel-sub" id="taskProcessMeta">Run a system inventory to populate this list.</div><div class="task-list scroll-list" id="taskProcessList"><div class="empty">Process catalog not loaded.</div></div><div class="control-footnote">This is not a process-kill console. Only a bounded, privacy-filtered snapshot is shown; no command lines, paths, environment variables or process memory are exposed.</div></section>
   </div>
   <section class="panel" style="margin-top:14px"><div class="panel-head"><div><div class="panel-title">QUICK JOB DISPATCH</div><div class="panel-sub">Launch a one-time job. Its feature must be enabled in Feature Control.</div></div><span class="tag">MANUAL RUN</span></div>
    <div class="action-grid">
     <button class="action-tile" data-command="scan_now"><b>◈ SYSTEM INVENTORY</b><small>Processes, applications, services and scheduled tasks</small></button>
     <button class="action-tile" data-command="deep_scan_now"><b>⌖ DEEP WINDOWS SCAN</b><small>Hardware, drivers, storage and security posture</small></button>
     <button class="action-tile" data-command="registry_scan_now"><b>▤ REGISTRY SNAPSHOT</b><small>Read-only configuration and change detection</small></button>
     <button class="action-tile" data-command="ai_review_now"><b>✳ LOCAL AI REVIEW</b><small>Evidence triage using installed Ollama models</small></button>
     <button class="action-tile" data-command="knowledge_crawl_now"><b>⌘ KNOWLEDGE REFRESH</b><small>Fetch allowlisted public Microsoft references</small></button>
    </div>
    <div class="control-footnote warning">Active Python threads are not force-killed from this screen. Disable a feature to prevent its next scheduled run; a job already in progress is allowed to finish. Pause Watch stops observer-driven schedules, and Stop Worker shuts down Sentinel gracefully.</div>
   </section>
  </section>

  <section class="screen" data-screen="knowledge">
   <div class="section-head"><div><div class="section-label">MICROSOFT LEARN / MICROSOFTDOCS / LOCAL SQLITE</div><div class="section-title">TECHNICAL CODEX</div><div class="section-description">Search locally indexed Windows engineering references; refresh the bounded public-source crawler from the command deck.</div></div><button class="btn primary" data-command="knowledge_crawl_now">⌘ SYNC CODEX</button></div>
   <div class="grid">
    <section class="panel"><div class="panel-head"><div><div class="panel-title">LOCAL DOCUMENT SEARCH</div><div class="panel-sub">Queries the local index only; not a live web search.</div></div><span class="tag">OFFLINE SEARCH</span></div><div class="search-row"><input class="field" id="knowledgeQuery" maxlength="180" placeholder="Try: ETW registry callback, PnP driver, BitLocker…"><button class="btn primary" id="knowledgeSearch">SEARCH CODEX</button></div><div class="result-list scroll-list" id="knowledgeResults"><div class="empty">Search the local technical knowledge vault.</div></div></section>
    <section class="panel"><div class="panel-head"><div><div class="panel-title">KNOWLEDGE INGESTION</div><div class="panel-sub">Last bounded crawler pass</div></div><span class="tag" id="knowledgeState">WAITING</span></div><div class="system-cards" id="knowledgeStats"><div class="empty">No crawl statistics yet.</div></div><div class="note">Only allowlisted Microsoft Learn and Microsoft-owned GitHub content is fetched. The crawler does not transmit machine telemetry.</div></section>
   </div>
  </section>

  <div class="note" style="padding:22px 2px 0;text-align:center;letter-spacing:.12em">SENTINEL PRIME · LOCAL OBSERVATION · EVIDENCE FIRST · USER-CONTROLLED EXECUTION</div>
 </main>
</div>

<div class="command-overlay" id="commandOverlay" aria-hidden="true">
 <div class="command-dialog" role="dialog" aria-modal="true" aria-labelledby="paletteTitle" tabindex="-1">
  <div class="command-dialog-head">
   <div><div class="palette-eyebrow">SENTINEL / QUICK ACCESS</div><div class="palette-title" id="paletteTitle">Find a workspace or run a job</div></div>
   <button class="palette-close" id="paletteClose" type="button" aria-label="Close command palette">×</button>
  </div>
  <div class="palette-input-wrap"><span class="palette-search-icon">⌕</span><input class="field palette-input" id="commandSearch" type="search" autocomplete="off" spellcheck="false" placeholder="Search screens, diagnostics and actions…"></div>
  <div class="command-results" id="commandResults" role="listbox" aria-label="Command results"></div>
  <div class="palette-footer"><span>↑ ↓ Navigate&nbsp;&nbsp; ENTER Open&nbsp;&nbsp; ESC Close</span><span>LOCAL COMMANDS ONLY</span></div>
 </div>
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
const titles={cockpit:"COMMAND CENTER",system:"SYSTEM DEEP DIVE",telemetry:"TELEMETRY MATRIX",evidence:"EVIDENCE VAULT",ai:"SENTINEL AI LAB",autonomy:"FEATURES & AUTOMATION",tasks:"TASK MANAGER",knowledge:"TECHNICAL CODEX"};
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}
function toast(message,kind=""){const stack=$("toastStack"),box=el("div","toast "+kind,message);stack.append(box);setTimeout(()=>box.remove(),5200)}
function age(iso){if(!iso)return"—";const t=new Date(iso).getTime();if(!Number.isFinite(t))return"—";const s=Math.max(0,Math.floor((Date.now()-t)/1000));return s<60?s+"s ago":s<3600?Math.floor(s/60)+"m ago":Math.floor(s/3600)+"h ago"}
function uptime(iso){if(!iso)return"—";let n=Math.max(0,Math.floor((Date.now()-new Date(iso).getTime())/1000));const h=Math.floor(n/3600);n%=3600;const m=Math.floor(n/60);return h+"h "+m+"m "+(n%60)+"s"}
function setMeter(id,value){const node=$(id);if(node)node.style.width=Math.max(0,Math.min(100,Number(value)||0))+"%"}
function statusTone(value){const s=String(value||"unknown").toLowerCase();return ["degraded","partial","warning","disabled","unavailable","critical"].includes(s)?"degraded":s==="available"||s==="watching"||s==="running"||s==="ok"?"":"optional"}
async function request(path,options={}){const response=await fetch(path,{...options,headers:{...headers,...(options.headers||{})},cache:"no-store"});let payload={};try{payload=await response.json()}catch{}if(!response.ok)throw new Error(payload.error||("Local API "+response.status));return payload}
function post(path,data){return request(path,{method:"POST",headers:{"Content-Type":"application/json","Origin":location.origin},body:JSON.stringify(data)})}
function switchView(view){
 if(!titles[view])return;
 currentView=view;
 document.querySelectorAll("[data-screen]").forEach(n=>{const active=n.dataset.screen===view;n.classList.toggle("active",active);n.setAttribute("aria-hidden",String(!active))});
 document.querySelectorAll(".nav-btn").forEach(n=>{const active=n.dataset.view===view;n.classList.toggle("active",active);if(active)n.setAttribute("aria-current","page");else n.removeAttribute("aria-current")});
 $("viewTitle").textContent=titles[view];
 document.body.dataset.view=view;
 closeCommandPalette(false);
 if(view==="ai")loadModels();
 if(view==="autonomy"){if(lastConfig===null)loadProfile();loadModels()}
 if(view==="tasks"){refresh(false);loadTaskProcesses()}
 if(view==="system"){loadInventory(true);loadCatalog("processes")}
 if(view==="evidence")loadEvents(true);
 if(view==="knowledge")renderKnowledgeStats();
}
document.querySelectorAll(".nav-btn").forEach(n=>n.addEventListener("click",()=>switchView(n.dataset.view)));
document.querySelectorAll("[data-view-jump]").forEach(n=>n.addEventListener("click",()=>switchView(n.dataset.viewJump)));
document.querySelectorAll(".metric-action").forEach(n=>n.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();switchView(n.dataset.viewJump)}}));

const paletteActions=[
 {label:"Full system sweep",detail:"Run the enabled inventory, deep inventory and registry collectors",command:"scan_now",icon:"01"},
 {label:"Deep Windows scan",detail:"Inspect hardware, drivers, storage and security posture",command:"deep_scan_now",icon:"02"},
 {label:"Registry snapshot",detail:"Run the approved read-only registry inventory",command:"registry_scan_now",icon:"03"},
 {label:"Local AI review",detail:"Queue a local evidence-led Ollama review",command:"ai_review_now",icon:"AI"},
 {label:"Knowledge sync",detail:"Refresh the bounded Microsoft reference index",command:"knowledge_crawl_now",icon:"KB"}
];
let paletteMatches=[];
let paletteActiveIndex=0;
function closeCommandPalette(restoreFocus=true){
 const overlay=$("commandOverlay");if(!overlay)return;
 overlay.classList.remove("open");overlay.setAttribute("aria-hidden","true");
 if(restoreFocus&&$("paletteBtn"))$("paletteBtn").focus();
}
function selectPaletteItem(item){
 if(!item||item.disabled)return;
 closeCommandPalette();
 if(item.kind==="view"){switchView(item.view);return}
 const trigger=Array.from(document.querySelectorAll("[data-command]")).find(n=>n.dataset.command===item.command&&!n.disabled);
 if(trigger)trigger.click();else toast("Enable this subsystem in Feature Control before dispatching the job.","warn");
}
function renderCommandPalette(){
 const query=($("commandSearch").value||"").trim().toLowerCase();
 const views=Array.from(document.querySelectorAll(".nav-btn")).map(n=>({
  kind:"view",view:n.dataset.view,label:(n.querySelector("small")?.textContent||titles[n.dataset.view]||n.dataset.view).trim(),
  detail:titles[n.dataset.view]||"Open workspace",icon:n.querySelector(".nav-icon")?.textContent||"•"
 }));
 const actions=paletteActions.map(item=>{
  const targets=Array.from(document.querySelectorAll("[data-command]")).filter(n=>n.dataset.command===item.command);
  return {...item,kind:"command",disabled:!targets.some(n=>!n.disabled),state:targets.some(n=>!n.disabled)?"READY":"DISABLED"};
 });
 const all=[...views,...actions];
 paletteMatches=all.filter(item=>(item.label+" "+item.detail).toLowerCase().includes(query));
 paletteActiveIndex=Math.min(paletteActiveIndex,Math.max(0,paletteMatches.length-1));
 const target=$("commandResults");target.replaceChildren();
 if(!paletteMatches.length){target.append(el("div","palette-empty","No matching workspace or action. Try a shorter search."));return}
 let lastKind="";
 paletteMatches.forEach((item,index)=>{
  if(item.kind!==lastKind){target.append(el("div","palette-group-label",item.kind==="view"?"WORKSPACES":"DISPATCH ACTIONS"));lastKind=item.kind}
  const button=el("button","palette-item"+(index===paletteActiveIndex?" selected":"" ));
  button.type="button";button.disabled=!!item.disabled;button.setAttribute("role","option");button.setAttribute("aria-selected",String(index===paletteActiveIndex));
  const icon=el("span","palette-icon",item.icon),copy=el("span"),title=el("strong",null,item.label),detail=el("small",null,item.detail),hint=el("span","palette-shortcut",item.disabled?"OFF":item.kind==="view"?"OPEN":"RUN");
  copy.append(title,detail);button.append(icon,copy,hint);button.addEventListener("click",()=>selectPaletteItem(item));target.append(button);
 });
 const selected=target.querySelector(".palette-item.selected");if(selected)selected.scrollIntoView({block:"nearest"});
}
function openCommandPalette(){
 const overlay=$("commandOverlay");if(!overlay)return;
 overlay.classList.add("open");overlay.setAttribute("aria-hidden","false");
 $("commandSearch").value="";paletteActiveIndex=0;renderCommandPalette();
 requestAnimationFrame(()=>$("commandSearch").focus());
}
$("paletteBtn").addEventListener("click",openCommandPalette);
$("paletteClose").addEventListener("click",()=>closeCommandPalette());
$("commandSearch").addEventListener("input",()=>{paletteActiveIndex=0;renderCommandPalette()});
$("commandOverlay").addEventListener("click",e=>{if(e.target===$("commandOverlay"))closeCommandPalette()});
$("commandSearch").addEventListener("keydown",e=>{
 if(e.key==="ArrowDown"||e.key==="ArrowUp"){
  e.preventDefault();if(!paletteMatches.length)return;
  paletteActiveIndex=(paletteActiveIndex+(e.key==="ArrowDown"?1:-1)+paletteMatches.length)%paletteMatches.length;
  renderCommandPalette();
 }else if(e.key==="Enter"){
  e.preventDefault();selectPaletteItem(paletteMatches[paletteActiveIndex]);
 }
});
document.addEventListener("keydown",e=>{
 if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();openCommandPalette();return}
 if(e.key==="Escape"&&$("commandOverlay").classList.contains("open")){e.preventDefault();closeCommandPalette();return}
 if((e.ctrlKey||e.metaKey)&&e.shiftKey&&/^[1-8]$/.test(e.key)){
  e.preventDefault();const nav=document.querySelectorAll(".nav-btn")[Number(e.key)-1];if(nav)switchView(nav.dataset.view);
 }
});
function drawCanvas(id,dataA,dataB){const canvas=$(id);if(!canvas)return;const rect=canvas.getBoundingClientRect();const w=Math.max(320,Math.round(rect.width*devicePixelRatio)),h=Math.max(150,Math.round(rect.height*devicePixelRatio));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}const ctx=canvas.getContext("2d");ctx.clearRect(0,0,w,h);const pad=18*devicePixelRatio;ctx.strokeStyle="rgba(130,165,194,.18)";ctx.lineWidth=devicePixelRatio;for(let i=0;i<=4;i++){const y=pad+(h-2*pad)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke()}function line(values,color){if(values.length<2)return;ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=2*devicePixelRatio;ctx.shadowBlur=8*devicePixelRatio;ctx.shadowColor=color;values.forEach((value,index)=>{const x=pad+(w-2*pad)*index/Math.max(1,values.length-1);const y=h-pad-(h-2*pad)*Math.max(0,Math.min(100,Number(value)||0))/100;if(index===0)ctx.moveTo(x,y);else ctx.lineTo(x,y)});ctx.stroke();ctx.shadowBlur=0}line(dataA,"#8bdcff");line(dataB,"#ff7774")}
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
 addSample(s);renderSensors(s);renderProviderDetails(s);renderWatchers(s);renderRuntime(s);renderAlerts(alerts);renderAI(s.ai||{});renderCommand(s.last_command||null);renderKnowledgeStats();renderAutomationState(s);
 $("telemetryFreshness").textContent="HEARTBEAT "+age(s.heartbeat_at).toUpperCase();
 if(currentView==="autonomy")renderAudit(lastEvents);
 if(currentView==="tasks")renderTaskManager(s);
}
function renderSensors(s){const health=s.provider_health||{},entries=Object.entries(health);const target=$("sensorGrid");target.replaceChildren();if(!entries.length){target.append(el("div","empty","Provider heartbeats will appear after the first collection cycle."));return}for(const [name,item] of entries.slice(0,14)){const row=el("div","sensor"),left=el("div"),strong=el("strong",null,name.replaceAll("_"," ").toUpperCase()),detail=el("small",null,(item.samples_succeeded||0)+"/"+(item.samples_attempted||0)+" samples · "+(item.last_latency_ms??"—")+" ms"),state=el("span","sensor-state "+statusTone(item.state),String(item.state||"unknown").toUpperCase());left.append(strong,detail);row.append(left,state);target.append(row)}}
function renderAlerts(alerts){const targets=[$("cockpitAlerts")];targets.forEach(target=>{target.replaceChildren();if(!alerts.length){target.append(el("div","empty","No rule-based posture alerts in the latest snapshot. This is not a guarantee of security."));return}for(const item of alerts.slice(0,5)){const card=el("article","alert-card "+String(item.severity||"info")),top=el("div","alert-row"),title=el("strong",null,item.title||"System finding"),sev=el("span","alert-sev",String(item.severity||"info").toUpperCase()+" · "+String(item.category||"SYSTEM").toUpperCase()),body=el("p",null,item.detail||"");top.append(title,sev);card.append(top,body);target.append(card)}});if(lastInventory)renderSystem(lastInventory.data||{})}
function renderAI(ai){
 const models=ai.models||{},tri=ai.triage||{},rev=ai.review||{};
 $("triageModel").textContent=models.triage||"No triage model recorded";
 $("reviewModel").textContent=models.review||"No independent reviewer recorded";
 $("triageState").textContent=models.triage?"ANALYZED":"IDLE";
 $("reviewState").textContent=models.independent_review_completed?"REVIEW COMPLETED":"REVIEW UNAVAILABLE";
 const describe=item=>typeof item==="string"?item:JSON.stringify(item);
 const section=(label,values)=>Array.isArray(values)&&values.length?label+"\n"+values.slice(0,4).map(value=>"• "+describe(value)).join("\n"):"";
 $("triageResult").textContent=[tri.summary||"Waiting for the next local evidence review.",section("SIGNALS",tri.signals),section("HYPOTHESES",tri.hypotheses),section("UNCERTAINTIES",tri.uncertainties)].filter(Boolean).join("\n\n");
 $("reviewResult").textContent=[(rev.assessment||"The independent reviewer has not completed a pass.")+(rev.confidence?" · "+String(rev.confidence).toUpperCase()+" CONFIDENCE":""),section("SUPPORTED FINDINGS",rev.supported_findings),section("REJECTED CLAIMS",rev.rejected_claims),section("UNCERTAINTIES",rev.uncertainties)].filter(Boolean).join("\n\n");
}
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
function renderProviderDetails(s){
 const target=$("providerDetails"),health=s.provider_health||{},entries=Object.entries(health);
 target.replaceChildren();
 if(!entries.length){target.append(el("div","empty","Provider samples have not been reported yet."));return}
 entries.sort((a,b)=>String(a[0]).localeCompare(String(b[0])));
 for(const [name,item] of entries){
  const row=el("div","command-line"),left=el("div"),title=el("strong",null,name.replaceAll("_"," ").toUpperCase());
  const details=[String(item.samples_succeeded??0)+"/"+String(item.samples_attempted??0)+" successful samples",String(item.errors??0)+" errors",String(item.event_loss??0)+" lost events",item.average_latency_ms==null?"average latency —":Number(item.average_latency_ms).toFixed(1)+" ms average"];
  const note=el("small",null,details.join(" · "));left.append(title,note);
  const state=el("small",null,String(item.state||"unknown").toUpperCase());
  if(item.state==="degraded")state.style.color="var(--red)";
  row.append(left,state);
  if(item.last_error_type)row.title="Last provider error: "+String(item.last_error_type);
  target.append(row);
 }
}
function renderWatchers(s){const target=$("internalWatchers");target.replaceChildren();const rows=[
 ["Registry observer",s.registry],["Deep CIM / device inventory",s.deep_inventory],["Microsoft knowledge crawler",s.knowledge],
 ["ETW process provider",(s.provider_health||{})["windows.etw.process"]]
 ];for(const [name,item] of rows){const row=el("div","command-line"),left=el("strong",null,name),right=el("small",null,item?.status||item?.state||(item?"available":"not configured"));row.append(left,right);target.append(row)}}
function renderRuntime(s){const target=$("runtimeProfile");target.replaceChildren();const hw=s.hardware||{};const entries=[["CPU LOGICAL COUNT",hw.cpu_count],["TOTAL MEMORY",hw.memory_total_gib==null?null:hw.memory_total_gib+" GiB"],["AVAILABLE MEMORY",hw.memory_available_gib==null?null:hw.memory_available_gib+" GiB"],["WORKER THREAD",s.pid]];for(const [name,value] of entries)target.append(infoCard(name,value,"Locally reported runtime profile"))}
function renderKnowledgeStats(){const k=lastStatus?.knowledge||{};$("knowledgeState").textContent=String(k.status||"NOT STARTED").toUpperCase();const target=$("knowledgeStats");if(!target)return;target.replaceChildren(infoCard("LOCAL DOCUMENTS",k.documents??"—","Indexed SQLite corpus"),infoCard("ADDED / UPDATED",(k.documents_added??"—")+" / "+(k.documents_updated??"—"),"Last crawler pass"),infoCard("SOURCE GROUPS",Object.keys(k.sources||{}).length,"Allowlisted Microsoft sources"),infoCard("LAST CRAWL",age(k.last_fetched_at),"Local status"))}
async function loadProfile(){try{const r=await request("/api/config");lastConfig=r.profile||{};renderProfile(lastConfig)}catch(e){$("profileNote").textContent="Profile load failed: "+e.message;$("profileSaveState").textContent="PROFILE UNAVAILABLE"}}
function renderProfile(p){
 const check=(id,key)=>$(id).checked=p[key]===true;
 const value=(id,v)=>$(id).value=v;
 check("cfgAutomation","automation_enabled");check("cfgInventory","inventory_enabled");
 check("cfgNetwork","include_network");check("cfgForeground","include_foreground");check("cfgProcessResources","include_process_resources");
 check("cfgRegistry","registry_enabled");check("cfgDeep","deep_inventory_enabled");check("cfgKnowledge","knowledge_enabled");check("cfgAI","ai_enabled");
 check("cfgPostureReview","auto_review_on_posture_alerts");check("cfgRegistryReview","auto_review_on_registry_changes");
 check("cfgEventLogs","include_event_logs");check("cfgEtw","include_etw");check("cfgWindowTitles","include_window_titles");check("cfgUITree","include_ui_tree");
 value("cfgSampleInterval",p.sample_interval_seconds??2);value("cfgNetworkInterval",p.network_interval_seconds??30);value("cfgProcessInterval",p.process_resource_interval_seconds??15);
 value("cfgInventoryInterval",Math.round((p.inventory_interval_seconds??900)/60));
 value("cfgRegistryInterval",Math.round((p.registry_interval_seconds??180)/60));
 value("cfgDeepInterval",Math.round((p.deep_inventory_interval_seconds??900)/60));
 value("cfgKnowledgeInterval",Math.round((p.knowledge_interval_seconds??21600)/3600));
 value("cfgAIInterval",Math.round((p.analysis_interval_seconds??300)/60));
 value("cfgDiskThreshold",p.low_disk_alert_percent??10);value("cfgBatteryThreshold",p.low_battery_alert_percent??15);
 value("cfgKnowledgeLearnTop",p.knowledge_learn_top_per_query??4);value("cfgKnowledgeGithubFiles",p.knowledge_github_files_per_repo??8);
 value("cfgUITreeApps",Array.isArray(p.ui_tree_apps)?p.ui_tree_apps.join(", "):"");
 value("cfgFastModel",p.fast_model||"");value("cfgDeepModel",p.deep_model||"");
 $("profileSaveState").textContent="PROFILE LOADED";
 updateCommandAvailability();renderAutomationState(lastStatus||{});
}
function applyPreset(name){
 const presets={
  deep:{inventory:5,registry:2,deep:5,knowledge:1,ai:2,posture:true,registryReview:true,disk:10,battery:15},
  balanced:{inventory:15,registry:3,deep:15,knowledge:6,ai:5,posture:true,registryReview:false,disk:10,battery:15},
  quiet:{inventory:30,registry:15,deep:60,knowledge:24,ai:15,posture:true,registryReview:false,disk:8,battery:12}
 };
 const p=presets[name];if(!p)return;
 $("cfgAutomation").checked=true;$("cfgInventory").checked=true;
 $("cfgNetwork").checked=true;$("cfgForeground").checked=true;$("cfgProcessResources").checked=true;
 $("cfgRegistry").checked=true;$("cfgDeep").checked=true;$("cfgKnowledge").checked=true;$("cfgAI").checked=true;
 $("cfgPostureReview").checked=p.posture;$("cfgRegistryReview").checked=p.registryReview;
 $("cfgInventoryInterval").value=p.inventory;$("cfgRegistryInterval").value=p.registry;$("cfgDeepInterval").value=p.deep;
 $("cfgKnowledgeInterval").value=p.knowledge;$("cfgAIInterval").value=p.ai;
 $("cfgSampleInterval").value=2;$("cfgNetworkInterval").value=30;$("cfgProcessInterval").value=15;
 $("cfgDiskThreshold").value=p.disk;$("cfgBatteryThreshold").value=p.battery;
 $("presetNote").textContent=name.toUpperCase()+" preset loaded. Scheduled jobs and baseline sensors are enabled; high-sensitivity sensors stay exactly as you set them. Save to apply.";
 renderAutomationState(lastStatus||{});updateCommandAvailability();
 toast(name.toUpperCase()+" preset loaded. Save settings to apply.");
}
async function saveProfile(){
 const integer=id=>Number.parseInt($(id).value,10),numeric=id=>Number.parseFloat($(id).value);
 const appAllowlist=$("cfgUITreeApps").value.split(",").map(x=>x.trim().toLowerCase()).filter(Boolean);
 const values={
  automation_enabled:$("cfgAutomation").checked,inventory_enabled:$("cfgInventory").checked,
  include_network:$("cfgNetwork").checked,include_foreground:$("cfgForeground").checked,include_process_resources:$("cfgProcessResources").checked,
  sample_interval_seconds:numeric("cfgSampleInterval"),network_interval_seconds:integer("cfgNetworkInterval"),process_resource_interval_seconds:integer("cfgProcessInterval"),
  inventory_interval_seconds:integer("cfgInventoryInterval")*60,
  registry_enabled:$("cfgRegistry").checked,deep_inventory_enabled:$("cfgDeep").checked,knowledge_enabled:$("cfgKnowledge").checked,ai_enabled:$("cfgAI").checked,
  auto_review_on_posture_alerts:$("cfgPostureReview").checked,auto_review_on_registry_changes:$("cfgRegistryReview").checked,
  registry_interval_seconds:integer("cfgRegistryInterval")*60,deep_inventory_interval_seconds:integer("cfgDeepInterval")*60,
  knowledge_interval_seconds:integer("cfgKnowledgeInterval")*3600,analysis_interval_seconds:integer("cfgAIInterval")*60,
  low_disk_alert_percent:integer("cfgDiskThreshold"),low_battery_alert_percent:integer("cfgBatteryThreshold"),
  include_event_logs:$("cfgEventLogs").checked,include_etw:$("cfgEtw").checked,include_window_titles:$("cfgWindowTitles").checked,
  include_ui_tree:$("cfgUITree").checked,ui_tree_apps:appAllowlist,
  knowledge_learn_top_per_query:integer("cfgKnowledgeLearnTop"),knowledge_github_files_per_repo:integer("cfgKnowledgeGithubFiles"),
  fast_model:$("cfgFastModel").value||null,deep_model:$("cfgDeepModel").value||null
 };
 const prior=lastConfig||{};
 const restartFields=["include_network","include_foreground","include_process_resources","sample_interval_seconds","network_interval_seconds","process_resource_interval_seconds","include_event_logs","include_etw","include_window_titles","include_ui_tree"];
 const restartChanged=restartFields.some(key=>prior[key]!==values[key])||JSON.stringify(prior.ui_tree_apps||[])!==JSON.stringify(values.ui_tree_apps);
 $("saveProfile").disabled=true;$("profileSaveState").textContent="SAVING…";
 try{
  const r=await post("/api/config",{values});lastConfig=r.profile;renderProfile(r.profile);
  $("profileSaveState").textContent="SAVED";
  $("profileNote").textContent=restartChanged?"Saved successfully. Restart Sentinel to reinitialize the continuous or advanced sensor pipelines. Scheduled job switches and intervals are adopted on the next observer cycle.":"Saved successfully. Scheduled collectors and automation rules will adopt these settings on the next observer cycle.";
  toast("Sentinel feature profile saved.");
 }catch(e){
  $("profileSaveState").textContent="SAVE FAILED";$("profileNote").textContent=e.message;toast("Profile save failed: "+e.message,"error");
 }finally{$("saveProfile").disabled=false}
}
function renderTaskManager(s){
 const history=Array.isArray(s.task_history)?s.task_history.slice().reverse():[];
 const health=s.provider_health||{},providers=Object.entries(health);
 const active=Object.values(s.tasks||{}).filter(task=>task.status==="running");
 $("taskActiveCount").textContent=active.length;$("taskToolCount").textContent=providers.length;
 $("taskRunCount").textContent=history.length;$("taskQueueCount").textContent=s.command_queue_depth??"—";
 $("taskWorkerState").textContent=s.status==="running"?(s.observer_paused?"OBSERVER PAUSED":"WORKER ONLINE"):"WORKER OFFLINE";
 $("taskProviderState").textContent=providers.length?providers.length+" PROVIDERS":"NO PROVIDER DATA";
 const definitions={
  inventory:["System inventory","scan_now","Processes, applications, services and scheduled tasks","inventory_enabled"],
  registry:["Registry intelligence","registry_scan_now","Read-only registry configuration snapshot","registry_enabled"],
  deep_inventory:["Deep Windows inventory","deep_scan_now","CIM, drivers, PnP, storage and security posture","deep_inventory_enabled"],
  knowledge:["Microsoft knowledge sync","knowledge_crawl_now","Allowlisted Microsoft documentation ingestion","knowledge_enabled"],
  ai_review:["Local AI evidence review","ai_review_now","Ollama evidence triage and independent review","ai_enabled"]
 };
 const live=$("taskLiveList");live.replaceChildren();
 for(const [key,meta] of Object.entries(definitions)){
  const task=s.tasks?.[key]||{},enabled=lastConfig?lastConfig[meta[3]]!==false:true;
  const row=el("article","task-row"),top=el("div","task-row-head"),left=el("div");
  left.append(el("strong",null,meta[0]),el("small",null,meta[2]));
  const state=task.status==="running"?"running":!enabled?"disabled":task.status||(s.features?.automation===false?"manual only":"scheduled");
  top.append(left,el("span","task-pill "+String(state).replaceAll("_","-"),String(state).replaceAll("_"," ").toUpperCase()));row.append(top);
  const details=[
   task.trigger?"Trigger: "+task.trigger:null,
   task.started_at?"Started: "+new Date(task.started_at).toLocaleString():null,
   task.finished_at?"Finished: "+new Date(task.finished_at).toLocaleString():null,
   task.duration_seconds!=null?"Duration: "+task.duration_seconds+" s":null,
   task.error_type?"Error: "+task.error_type:null
  ].filter(Boolean);
  row.append(el("div","task-meta",details.join(" · ")||"No run recorded in this worker session."));
  const actions=el("div","task-actions"),run=el("button","btn primary",task.status==="running"?"RUNNING":"RUN NOW"),toggle=el("button","btn ghost",enabled?"DISABLE":"ENABLE"),settings=el("button","btn ghost","ALL SETTINGS");
  run.type="button";run.disabled=!enabled||task.status==="running";run.addEventListener("click",()=>runCommand(meta[1]));
  toggle.type="button";toggle.addEventListener("click",()=>setTaskFeature(meta[3],!enabled));
  settings.type="button";settings.addEventListener("click",()=>switchView("autonomy"));
  actions.append(run,toggle,settings);row.append(actions);live.append(row);
 }
 if(s.inference_busy&&!s.tasks?.ai_review?.status?.includes("running")){
  const row=el("article","task-row"),top=el("div","task-row-head"),left=el("div");
  left.append(el("strong",null,"Interactive local AI inference"),el("small",null,"An Ask Sentinel request or model operation currently holds the shared inference lock."));
  top.append(left,el("span","task-pill running","INFERENCE BUSY"));row.append(top,el("div","task-meta","Local Ollama · request-level activity · completion is reported when the lock is released."));live.append(row);
 }
 const toolList=$("taskToolsList");toolList.replaceChildren();
 if(!providers.length)toolList.append(el("div","empty","No provider-health metrics have been reported yet."));
 for(const [name,item] of providers.sort((a,b)=>a[0].localeCompare(b[0]))){
  const row=el("details","task-tool"),summary=el("summary"),heading=el("strong",null,name.replaceAll("."," / ").replaceAll("_"," "));
  summary.append(heading,el("span","task-pill "+String(item.state||"unknown"),String(item.state||"UNKNOWN").toUpperCase()));
  const values=[
   "Samples "+String(item.samples_succeeded??0)+"/"+String(item.samples_attempted??0),
   "Errors "+String(item.errors??0),"Event loss "+String(item.event_loss??0),
   "Last latency "+String(item.last_latency_ms??"—")+" ms",
   "Average "+(item.average_latency_ms==null?"—":Number(item.average_latency_ms).toFixed(1)+" ms"),
   item.last_error_type?"Last error "+item.last_error_type:"No last error"
  ];
  row.append(summary,el("div","task-tool-meta",values.join(" · ")));toolList.append(row);
 }
 const historyTarget=$("taskHistoryList"),filter=$("taskHistoryFilter").value;historyTarget.replaceChildren();
 const filtered=history.filter(item=>filter==="all"||(filter==="warnings"&&item.status==="completed_with_warnings")||item.status===filter);
 if(!filtered.length)historyTarget.append(el("div","empty","No runs match this filter."));
 for(const item of filtered.slice(0,60)){
  const row=el("article","task-history-row"),left=el("div");
  left.append(el("strong",null,item.name||item.key),el("small",null,(item.trigger||"worker")+" · "+(item.started_at?new Date(item.started_at).toLocaleString():"time unavailable")));
  row.append(left,el("span","task-pill "+String(item.status||"unknown").replaceAll("_","-"),String(item.status||"UNKNOWN").replaceAll("_"," ").toUpperCase()));
  if(item.duration_seconds!=null)row.append(el("small","task-duration",item.duration_seconds+" s"));
  historyTarget.append(row);
 }
}
async function setTaskFeature(setting,enabled){
 const fieldToControl={
  inventory_enabled:"cfgInventory",registry_enabled:"cfgRegistry",
  deep_inventory_enabled:"cfgDeep",knowledge_enabled:"cfgKnowledge",ai_enabled:"cfgAI"
 };
 try{
  const result=await post("/api/config",{values:{[setting]:enabled}});
  lastConfig=result.profile;
  const input=$(fieldToControl[setting]);if(input)input.checked=enabled;
  $("profileSaveState").textContent="PROFILE SAVED FROM TASK MANAGER";
  updateCommandAvailability();
  if(lastStatus)renderTaskManager(lastStatus);
  toast(setting.replaceAll("_"," ")+(enabled?" enabled":" disabled")+" · saved for the next observer cycle.");
 }catch(error){toast("Feature update failed: "+error.message,"error")}
}
async function loadTaskProcesses(){
 const target=$("taskProcessList"),query=$("taskProcessQuery")?.value.trim()||"";
 if(!target)return;target.replaceChildren(el("div","empty","Loading latest bounded process snapshot…"));
 try{
  const result=await request("/api/catalog?kind=processes&q="+encodeURIComponent(query)+"&limit=120");
  $("processSnapshotTag").textContent=result.snapshot_at?"SNAPSHOT "+age(result.snapshot_at).toUpperCase():"NO SNAPSHOT";
  $("taskProcessMeta").textContent=result.available?String(result.matched)+" shown / "+String(result.total)+" processes · metadata only":"No system inventory snapshot yet. Run System Inventory.";
  target.replaceChildren();
  if(!result.items?.length){target.append(el("div","empty","No process rows found. Run an inventory or change the filter."));return}
  for(const process of result.items){
   const row=el("div","process-row"),left=el("div");
   left.append(el("strong",null,String(process.name||"Unknown process")),el("small",null,"PID "+String(process.pid??"—")));
   row.append(left,el("small",null,process.create_time?"Started "+new Date(process.create_time*1000).toLocaleString():"Start time unavailable"));target.append(row);
  }
 }catch(error){target.replaceChildren(el("div","empty","Process inventory unavailable: "+error.message))}
}
function renderAutomationState(s){
 const enabled=lastConfig?lastConfig.automation_enabled===true:s.features?.automation===true;
 const paused=s.observer_paused===true,active=s.status==="running";
 $("automationLive").textContent=!active?"WORKER OFFLINE":paused?"OBSERVER PAUSED":enabled?"SCHEDULES ENABLED":"MANUAL / SENSOR MODE";
 $("automationSwitchText").textContent=enabled?"AUTOMATION ON":"AUTOMATION OFF";
 $("automationExplanation").textContent=enabled
  ?"Scheduled jobs are enabled. Individual collector switches still apply, and the observer must be running (not paused) for scheduled work to fire. Manual one-time actions remain separately available."
  :"Scheduled inventory, registry, deep Windows, knowledge and periodic AI jobs are stopped. Event-driven AI reviews are also suppressed. Enabled continuous sensors keep observing, and allowed one-time jobs can still be launched manually.";
 updateCommandAvailability();
}
function updateCommandAvailability(){
 if(!lastConfig)return;
 const enabled={
  scan_now:["inventory_enabled","deep_inventory_enabled","registry_enabled"].some(key=>lastConfig[key]===true),
  deep_scan_now:lastConfig.deep_inventory_enabled===true,
  registry_scan_now:lastConfig.registry_enabled===true,
  ai_review_now:lastConfig.ai_enabled===true,
  knowledge_crawl_now:lastConfig.knowledge_enabled===true
 };
 document.querySelectorAll("[data-command]").forEach(button=>{
  const action=button.dataset.command,available=enabled[action]!==false;
  button.disabled=!available;button.classList.toggle("feature-command-disabled",!available);
  if(!available)button.title="Disabled in Feature Control. Enable this subsystem and save the profile to use it.";
  else if(button.title.includes("Disabled in Feature Control"))button.removeAttribute("title");
 });
}
async function runCommand(action){try{const r=await post("/api/command",{action});toast("Command queued · "+r.queued);setTimeout(()=>refresh(false),1100)}catch(e){toast(e.message,"error")}}
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
function populateModelSelect(id,models,selected){
 const select=$(id);if(!select)return;
 select.replaceChildren(new Option("Automatic — best compatible installed model",""));
 if(selected&&!models.includes(selected)){const option=new Option(selected+" (saved; not currently discovered)",selected);select.append(option)}
 for(const model of models)select.append(new Option(model,model));
 select.value=selected||"";
}
async function loadModels(){
 if(Date.now()-lastModelsFetch<10000)return;lastModelsFetch=Date.now();
 const target=$("modelList");target.replaceChildren(el("div","empty","Discovering locally installed Ollama models…"));
 try{
  const r=await request("/api/ai/models"),models=Array.isArray(r.models)?r.models:[];
  populateModelSelect("cfgFastModel",models,lastConfig?.fast_model||"");
  populateModelSelect("cfgDeepModel",models,lastConfig?.deep_model||"");
  target.replaceChildren();
  $("modelMemory").textContent="Available system RAM: "+(r.memory_available_gib??"—")+" GiB · local-only inference · "+models.length+" installed models";
  if(!models.length){target.append(el("div","empty",r.error||"No installed local Ollama models were discovered. Install or start Ollama before expecting AI jobs to run."));return}
  for(const model of models){
   const item=el("div","model-card"),name=el("strong",null,model);
   const triage=Array.isArray(r.triage_candidates)&&r.triage_candidates.includes(model),review=Array.isArray(r.review_candidates)&&r.review_candidates.includes(model);
   const detail=el("small",null,(triage?"3B/4B triage candidate · ":"")+(review?"6B+ review candidate":"Installed local model"));
   item.append(name,detail);target.append(item);
  }
 }catch(e){
  populateModelSelect("cfgFastModel",[],lastConfig?.fast_model||"");
  populateModelSelect("cfgDeepModel",[],lastConfig?.deep_model||"");
  target.replaceChildren(el("div","empty","Local Ollama discovery failed: "+e.message));
 }
}
const aiSuggestionControls={
 automation_enabled:"cfgAutomation",inventory_enabled:"cfgInventory",registry_enabled:"cfgRegistry",
 deep_inventory_enabled:"cfgDeep",knowledge_enabled:"cfgKnowledge",ai_enabled:"cfgAI",
 auto_review_on_posture_alerts:"cfgPostureReview",auto_review_on_registry_changes:"cfgRegistryReview",
 include_network:"cfgNetwork",include_foreground:"cfgForeground",include_process_resources:"cfgProcessResources"
};
async function stageProfileSuggestion(setting,value){
 const inputId=aiSuggestionControls[setting];
 if(!inputId||typeof value!=="boolean"){toast("This suggestion is not an approved Sentinel profile setting.","error");return}
 if(lastConfig===null)await loadProfile();
 switchView("autonomy");
 const input=$(inputId);
 if(!input){toast("The profile control was not found.","error");return}
 input.checked=value;
 $("profileSaveState").textContent="UNSAVED AI SUGGESTION";
 $("presetNote").textContent="An AI suggestion has been staged. Review the surrounding settings and save only if you agree.";
 $("profileNote").textContent="This change is only in the form. Nothing has been applied yet.";
 toast("Suggestion staged · review it and press SAVE ALL SETTINGS.");
}
async function askSentinel(){
 const question=$("aiQuestion").value.trim(),mode=$("aiMode").value;
 if(!question){$("aiQuestion").focus();return}
 const btn=$("askBtn");btn.disabled=true;btn.textContent="ANALYSING LOCAL EVIDENCE…";
 $("aiAnswer").textContent="Preparing the bounded, redacted evidence packet and local Microsoft references. Waiting for Ollama…";
 $("aiReferences").replaceChildren();
 try{
  const r=await post("/api/ask",{question,mode});
  $("aiAnswer").textContent=r.answer||"No answer returned.";
  const meta=el("div","panel-sub","SPECIALIST "+String(r.specialist_mode||mode).toUpperCase()+" · "+String(r.model||"LOCAL MODEL")+" · "+String(r.confidence||"low").toUpperCase()+" CONFIDENCE · "+(r.evidence_ids||[]).length+" EVIDENCE IDS");
  $("aiReferences").append(meta);
  if(r.evidence_ids?.length)$("aiReferences").append(el("div","panel-sub","EVIDENCE IDS · "+r.evidence_ids.join(", ")));
  for(const ref of r.references||[]){
   try{const url=new URL(ref.url);if(url.protocol==="https:"&&["learn.microsoft.com","github.com"].includes(url.hostname)){const a=el("a","ai-reference",ref.title||url.hostname);a.href=url.href;a.target="_blank";a.rel="noopener noreferrer";$("aiReferences").append(a)}}catch{}
  }
  const suggestions=Array.isArray(r.profile_suggestions)?r.profile_suggestions:[];
  if(mode==="maintenance"){
   $("aiReferences").append(el("div","control-group-title","Suggested Sentinel settings · review before applying"));
   if(!suggestions.length)$("aiReferences").append(el("div","empty","No Sentinel profile change is justified by the returned evidence. Follow the manual remediation guidance above."));
   for(const suggestion of suggestions){
    const card=el("div","ai-suggestion"),body=el("div"),title=el("strong",null,String(suggestion.setting||"Setting").replaceAll("_"," ")),value=el("span","task-pill",suggestion.value?"ENABLE":"DISABLE");
    body.append(title,el("p",null,String(suggestion.reason||"No rationale provided.")),el("small",null,(suggestion.requires_restart?"Worker restart required after saving":"Applied on the next observer cycle")+(suggestion.evidence_ids?.length?" · Evidence "+suggestion.evidence_ids.join(", "):"")));
    const top=el("div","task-row-head");top.append(body,value);card.append(top);
    const stage=el("button","btn primary","STAGE IN FEATURE CONTROL");stage.type="button";stage.addEventListener("click",()=>stageProfileSuggestion(suggestion.setting,suggestion.value));card.append(stage);$("aiReferences").append(card);
   }
  }
  toast("Local specialist response ready.");
 }catch(e){$("aiAnswer").textContent="Sentinel AI unavailable: "+e.message;toast(e.message,"error")}
 finally{btn.disabled=false;btn.textContent="✳ ASK LOCAL AI"}
}
async function searchKnowledge(){const q=$("knowledgeQuery").value.trim();if(!q){$("knowledgeQuery").focus();return}const target=$("knowledgeResults");target.replaceChildren(el("div","empty","Searching local documentation index…"));try{const r=await request("/api/knowledge/search?q="+encodeURIComponent(q)+"&limit=8");target.replaceChildren();if(!r.results?.length){target.append(el("div","empty","No indexed document matched. Run a knowledge sync."));return}for(const item of r.results){const card=el("div","knowledge-card"),title=el("strong",null,item.title||"Untitled document"),meta=el("small",null,String(item.source||"").toUpperCase()+" · SCORE "+item.score),p=el("p",null,item.excerpt||""),a=el("a","ai-reference",item.url||"");if(item.url){a.href=item.url;a.target="_blank";a.rel="noopener noreferrer"}card.append(title,meta,p,a);target.append(card)}}catch(e){target.replaceChildren(el("div","empty",e.message))}}
let notifiedReady=("Notification" in window)&&Notification.permission==="granted";
async function enableNotifications(){
 if(!("Notification"in window)){toast("This browser does not support desktop notifications.","warn");return}
 const result=Notification.permission==="granted"?"granted":await Notification.requestPermission();
 notifiedReady=result==="granted";
 toast(notifiedReady?"Desktop posture alerts enabled.":"Notification permission was not granted.",notifiedReady?"":"warn");
}
function notifyNewPosture(status){const alerts=status.deep_inventory?.posture_alerts||[],keys=alerts.map(a=>[a.severity,a.category,a.title].join("|"));if(lastAlertKeys===null){lastAlertKeys=new Set(keys);return}const newly=alerts.filter(a=>!lastAlertKeys.has([a.severity,a.category,a.title].join("|")));lastAlertKeys=new Set(keys);for(const item of newly){toast(item.title+" · "+(item.detail||""),item.severity==="critical"||item.severity==="high"?"error":"warn");if(notifiedReady&&("Notification"in window))new Notification("Sentinel · "+String(item.severity||"INFO").toUpperCase(),{body:item.title+" — "+(item.detail||"")})}}
async function refresh(forceInventory=false){try{const s=await request("/api/status");renderStatus(s);notifyNewPosture(s);if(forceInventory||Date.now()-lastInventoryFetch>26000)await loadInventory(true);if(Date.now()-lastEventsFetch>7500||!lastEvents.length)await loadEvents(true);if(currentView==="system"&&lastInventory)renderSystem(lastInventory.data||{});if(currentView==="autonomy")renderAudit(lastEvents);return true}catch(e){$("liveBadge").textContent="RECONNECTING";$("heroDesc").textContent="Unable to contact the local Sentinel worker. Reconnecting…";return false}}
function bootProgress(value,stage,line){$("bootProgress").style.width=value+"%";$("bootPercent").textContent=String(value).padStart(2,"0")+"%";$("bootStage").textContent=stage;if(line){const row=el("div",null,line);$("bootLog").append(row);while($("bootLog").children.length>4)$("bootLog").firstChild.remove()}}
function finishBoot(){ $("boot").classList.add("done");$("app").classList.add("ready");setTimeout(()=>$("boot").remove(),950)}
async function startBoot(){bootProgress(12,"OPENING LOCAL LINK","loopback command channel initializing");await new Promise(r=>setTimeout(r,240));const connected=await refresh(true);if(!connected){bootProgress(100,"WORKER OFFLINE","interface loaded · waiting for Sentinel worker");setTimeout(finishBoot,520);return}bootProgress(66,"MOUNTING EVIDENCE","checking local SQLite event and inventory APIs");await loadProfile();bootProgress(84,"DISCOVERING INTELLIGENCE","checking configured profile and installed local model endpoint");await loadModels();bootProgress(100,"COMMAND DECK READY","dashboard online · subsystem availability is reported independently");setTimeout(finishBoot,520)}
function drawStars(){const canvas=$("starfield");if(!canvas)return;const ctx=canvas.getContext("2d");let points=[];function resize(){canvas.width=Math.max(320,innerWidth*devicePixelRatio);canvas.height=Math.max(300,innerHeight*devicePixelRatio);points=Array.from({length:72},()=>({x:Math.random()*canvas.width,y:Math.random()*canvas.height,r:Math.random()*1.4+.3,s:Math.random()*.18+.04}))}function paint(move){ctx.clearRect(0,0,canvas.width,canvas.height);for(const p of points){ctx.fillStyle="rgba(139,220,255,.32)";ctx.beginPath();ctx.arc(p.x,p.y,p.r*devicePixelRatio,0,Math.PI*2);ctx.fill();if(move){p.y+=p.s*devicePixelRatio;if(p.y>canvas.height)p.y=0}}if(move)requestAnimationFrame(()=>paint(true))}resize();addEventListener("resize",()=>{resize();paint(false)});paint(!matchMedia("(prefers-reduced-motion: reduce)").matches)}
$("pauseBtn").addEventListener("click",async()=>{try{await post("/api/control",{action:"pause"});toast("Sensor pause requested.");refresh()}catch(e){toast(e.message,"error")}});
$("stopBtn").addEventListener("click",async()=>{if(!confirm("Stop the Sentinel background worker? The dashboard will disconnect until it is started again."))return;try{await post("/api/control",{action:"stop"});toast("Stop request sent. The local dashboard will close when the worker exits.","warn")}catch(e){toast(e.message,"error")}});
$("resumeBtn").addEventListener("click",async()=>{try{await post("/api/control",{action:"resume"});toast("Sentinel watch resumed.");refresh()}catch(e){toast(e.message,"error")}});
$("notifyBtn").addEventListener("click",enableNotifications);$("notifyEnable").addEventListener("click",enableNotifications);
$("refreshBtn").addEventListener("click",()=>refresh(true));$("modelRefresh").addEventListener("click",()=>{lastModelsFetch=0;loadModels()});$("cfgModelRefresh").addEventListener("click",()=>{lastModelsFetch=0;loadModels()});
$("saveProfile").addEventListener("click",saveProfile);$("reloadProfile").addEventListener("click",loadProfile);
document.querySelectorAll("[data-preset]").forEach(button=>button.addEventListener("click",()=>applyPreset(button.dataset.preset)));
$("askBtn").addEventListener("click",askSentinel);$("aiQuestion").addEventListener("keydown",e=>{if(e.key==="Enter")askSentinel()});
$("driverSearch").addEventListener("click",searchDrivers);$("driverQuery").addEventListener("keydown",e=>{if(e.key==="Enter")searchDrivers()});
$("catalogSearch").addEventListener("click",()=>loadCatalog());
$("catalogQuery").addEventListener("keydown",e=>{if(e.key==="Enter")loadCatalog()});
document.querySelectorAll("[data-catalog]").forEach(button=>button.addEventListener("click",()=>loadCatalog(button.dataset.catalog)));
$("knowledgeSearch").addEventListener("click",searchKnowledge);$("knowledgeQuery").addEventListener("keydown",e=>{if(e.key==="Enter")searchKnowledge()});
$("taskRefresh").addEventListener("click",()=>{refresh(true);loadTaskProcesses()});
$("taskProcessSearch").addEventListener("click",loadTaskProcesses);$("taskProcessQuery").addEventListener("keydown",e=>{if(e.key==="Enter")loadTaskProcesses()});
$("taskHistoryFilter").addEventListener("change",()=>{if(lastStatus)renderTaskManager(lastStatus)});
$("eventSearch").addEventListener("click",async()=>{
 const q=$("eventQuery").value.trim(),type=$("eventTypeFilter").value;
 try{
  const r=await request("/api/events?limit=250&q="+encodeURIComponent(q)+"&type="+encodeURIComponent(type));
  const filteredEvents=r.events||[];
  $("vaultCount").textContent=(r.returned||filteredEvents.length)+" MATCHES";
  $("eventMeta").textContent=(r.returned||0)+" matches in the recent searchable window";
  renderEvents(filteredEvents,"eventList");
 }catch(e){toast(e.message,"error")}
});
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


def _latest_event(db_path: Path, event_type: str) -> Any | None:
    """Fetch the newest matching event through the indexed event-type query."""
    matches = EventStore(db_path).query_events(event_types=(event_type,), limit=1)
    return matches[0] if matches else None


def make_dashboard_server(
    *,
    token: str,
    state_path: Path,
    stop_path: Path,
    db_path: Path,
    command_queue: queue.Queue[tuple[str, str]] | None = None,
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
                    payload["command_queue_depth"] = command_queue.qsize() if command_queue is not None else 0
                    payload["inference_busy"] = bool(inference_lock is not None and inference_lock.locked())
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
                        "automation_enabled", "inventory_enabled", "inventory_interval_seconds",
                        "sample_interval_seconds", "network_interval_seconds",
                        "process_resource_interval_seconds", "include_network",
                        "include_foreground", "include_process_resources",
                        "include_ui_tree", "registry_enabled", "deep_inventory_enabled", "knowledge_enabled",
                        "ai_enabled", "registry_interval_seconds",
                        "deep_inventory_interval_seconds", "knowledge_interval_seconds",
                        "analysis_interval_seconds", "auto_review_on_posture_alerts",
                        "auto_review_on_registry_changes", "low_disk_alert_percent",
                        "low_battery_alert_percent", "include_event_logs",
                        "include_etw", "include_window_titles", "ui_tree_apps",
                        "knowledge_learn_top_per_query", "knowledge_github_files_per_repo",
                        "fast_model", "deep_model",
                    )
                    self._json(200, {"profile": {key: config[key] for key in fields}})
                except (OSError, RuntimeError, ValueError):
                    self._json(503, {"error": "Sentinel profile is unavailable"})
                return
            if parsed.path == "/api/drivers":
                try:
                    query = parse_qs(parsed.query).get("q", [""])[0].strip().casefold()[:100]
                    latest = _latest_event(db_path, "windows.deep_inventory")
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
                except (OSError, ValueError, sqlite3.Error):
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
                    latest = _latest_event(db_path, "windows.system_inventory")
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
                except (OSError, ValueError, sqlite3.Error):
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
                    latest = _latest_event(db_path, "windows.deep_inventory")
                    if latest is None:
                        self._json(200, {"available": False, "snapshot_at": None, "data": {}})
                        return
                    self._json(200, {
                        "available": True,
                        "snapshot_at": latest.timestamp.isoformat(),
                        "data": _safe_json_value(latest.data),
                    })
                except (OSError, ValueError, sqlite3.Error):
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
                except (OSError, ValueError, sqlite3.Error):
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
                    for event in store.recent(min(1000, limit * 5)):
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
                except (OSError, ValueError, sqlite3.Error):
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
                    "automation_enabled", "inventory_enabled",
                    "include_network", "include_foreground", "include_process_resources",
                    "include_ui_tree", "registry_enabled", "deep_inventory_enabled", "knowledge_enabled", "ai_enabled",
                    "auto_review_on_posture_alerts", "auto_review_on_registry_changes",
                    "include_event_logs", "include_etw", "include_window_titles",
                }
                float_ranges = {"sample_interval_seconds": (0.5, 30.0)}
                integer_ranges = {
                    "network_interval_seconds": (5, 300),
                    "process_resource_interval_seconds": (2, 300),
                    "inventory_interval_seconds": (300, 7200),
                    "knowledge_learn_top_per_query": (1, 10),
                    "knowledge_github_files_per_repo": (1, 20),
                    "registry_interval_seconds": (60, 3600),
                    "deep_inventory_interval_seconds": (300, 7200),
                    "knowledge_interval_seconds": (3600, 604800),
                    "analysis_interval_seconds": (60, 3600),
                    "low_disk_alert_percent": (1, 30),
                    "low_battery_alert_percent": (5, 40),
                }
                model_fields = {"fast_model", "deep_model"}
                if any(key not in boolean_fields and key not in integer_ranges and key not in float_ranges and key not in model_fields and key != "ui_tree_apps" for key in values):
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
                if values.get("include_ui_tree") is True and not values.get("ui_tree_apps", []):
                    self._json(400, {"error": "Add at least one allowed executable before enabling UI Automation."})
                    return
                for key, value in values.items():
                    if key == "ui_tree_apps":
                        continue
                    if key in model_fields:
                        if value is not None and (
                            not isinstance(value, str) or not value.strip() or len(value) > 200
                        ):
                            self._json(400, {"error": "model setting must be null or an installed model tag"})
                            return
                    elif key in boolean_fields:
                        if not isinstance(value, bool):
                            self._json(400, {"error": "boolean setting has an invalid value"})
                            return
                    elif key in float_ranges:
                        minimum, maximum = float_ranges[key]
                        if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
                            self._json(400, {"error": "sampling interval is outside its supported range"})
                            return
                    else:
                        minimum, maximum = integer_ranges[key]
                        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                            self._json(400, {"error": "numeric setting is outside its supported range"})
                            return
                try:
                    if config_loader is None or config_saver is None:
                        raise RuntimeError("profile provider unavailable")
                    config = config_loader()
                    config.update(values)
                    config_saver(config)
                    fields = tuple(boolean_fields | set(integer_ranges) | set(float_ranges) | model_fields | {"ui_tree_apps"})
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
                required_flags = {
                    "deep_scan_now": "deep_inventory_enabled",
                    "ai_review_now": "ai_enabled",
                    "knowledge_crawl_now": "knowledge_enabled",
                    "registry_scan_now": "registry_enabled",
                }
                if action in set(required_flags) | {"scan_now"}:
                    try:
                        active_profile = config_loader() if config_loader is not None else {}
                    except (OSError, RuntimeError, ValueError):
                        self._json(503, {"error": "Sentinel profile is unavailable"})
                        return
                    required_flag = required_flags.get(action)
                    if required_flag and active_profile.get(required_flag) is not True:
                        self._json(409, {"error": required_flag.replace("_", " ") + " is disabled in the current profile"})
                        return
                    if action == "scan_now" and not any(
                        active_profile.get(key) is True
                        for key in ("inventory_enabled", "deep_inventory_enabled", "registry_enabled")
                    ):
                        self._json(409, {"error": "All system inventory collectors are disabled in the current profile"})
                        return
                try:
                    command_queue.put_nowait((action, "dashboard manual command"))
                except queue.Full:
                    self._json(429, {"error": "Sentinel command queue is busy"})
                    return
                self._json(202, {"queued": action})
                return

            if path == "/api/ask":
                question = body.get("question")
                mode = body.get("mode", "general")
                allowed_modes = {"general", "security", "performance", "drivers", "storage", "network", "maintenance"}
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
