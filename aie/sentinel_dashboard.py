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
:root{--bg:#080b0c;--bg2:#0d1112;--panel:#121819;--panel2:#171f20;--line:#2a3735;--line2:#405149;--text:#e4e9e3;--soft:#b5c0b9;--muted:#718079;--orange:#ff6b38;--orange2:#c94c2c;--lime:#b8e65b;--red:#f05252;--amber:#eab45e;--green:#7cd59c;--mono:"Cascadia Code",Consolas,monospace;--display:"Bahnschrift SemiCondensed","Arial Narrow","Segoe UI",sans-serif;--radius:3px}
*{box-sizing:border-box}html{scroll-behavior:smooth;background:var(--bg)}body{margin:0;min-height:100vh;overflow-x:hidden;background:var(--bg);color:var(--text);font:13px/1.5 "Segoe UI",Arial,sans-serif}button,input,select,textarea{font:inherit}button{cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--lime);outline-offset:3px}a{color:var(--lime);text-decoration:none}
#starfield{position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:0;opacity:.06}.ambient{position:fixed;inset:0;pointer-events:none;z-index:0;background:linear-gradient(120deg,#080b0c,#0d1212 52%,#090c0d)}.ambient:before{content:"";position:absolute;inset:0;opacity:.12;background-image:linear-gradient(90deg,#8fa69b12 1px,transparent 1px),linear-gradient(#8fa69b12 1px,transparent 1px);background-size:32px 32px;mask-image:linear-gradient(90deg,#000,transparent 92%)}.ambient:after{content:"";position:absolute;left:0;right:0;top:0;height:2px;background:linear-gradient(90deg,var(--orange) 0 12%,transparent 12%)}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}@keyframes pulse{50%{opacity:.35}}@keyframes spin{to{transform:rotate(360deg)}}
.boot{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;background:#070a0b;transition:opacity .45s,visibility .45s}.boot.done{opacity:0;visibility:hidden;pointer-events:none}.boot-grid{position:absolute;inset:0;opacity:.2;background-image:linear-gradient(90deg,#9cab9b16 1px,transparent 1px),linear-gradient(#9cab9b16 1px,transparent 1px);background-size:42px 42px;mask-image:linear-gradient(transparent,#000 30%,#000)}
.boot-card{width:min(760px,calc(100vw - 30px));position:relative;padding:34px 38px 30px;text-align:left;border:1px solid #40504a;border-left:4px solid var(--orange);border-radius:2px;background:linear-gradient(120deg,#141a1a,#0c1112 72%);box-shadow:0 30px 90px #000b;overflow:hidden}.boot-card:after{content:"";position:absolute;right:-80px;top:-110px;width:330px;height:330px;border:1px solid #a3b0a522;transform:rotate(45deg);box-shadow:0 0 0 30px #a3b0a508,0 0 0 60px #a3b0a506;pointer-events:none}
.boot-emblem{width:82px;height:82px;margin:0 0 22px;display:grid;place-items:center;position:relative;border:1px solid #596761;background:repeating-linear-gradient(135deg,#202a28 0 7px,#151d1c 7px 14px)}.boot-emblem:before,.boot-emblem:after{content:"";position:absolute;inset:7px;border:1px solid #73847b;transform:rotate(45deg)}.boot-emblem:after{inset:16px;border-color:var(--orange);opacity:.8}.boot-mark{position:relative;z-index:1;color:var(--text);font:900 17px var(--display);letter-spacing:.12em}.boot-title{font:900 clamp(22px,4vw,34px)/1 var(--display);letter-spacing:.12em;text-transform:uppercase}.boot-sub{color:var(--orange);font:10px var(--mono);letter-spacing:.2em;margin-top:10px}.boot-copy{max-width:520px;color:#8d9b93;font-size:11px;margin:18px 0 24px}.boot-track{height:4px;background:#27322e;overflow:hidden}.boot-progress{height:100%;width:0;background:linear-gradient(90deg,var(--orange2),var(--orange),var(--lime));transition:width .3s}.boot-stage{display:flex;justify-content:space-between;gap:12px;margin-top:10px;color:#89978f;font:9px var(--mono);letter-spacing:.12em}.boot-stage b{color:var(--lime)}.boot-log{height:65px;overflow:hidden;text-align:left;border:1px solid #2c3935;background:#090e0e;margin-top:18px;padding:8px 10px;color:#93a69a;font:9px/1.65 var(--mono)}.boot-log div:before{content:"// ";color:var(--orange)}.boot-skip{border:1px solid #46544d;background:#151d1a;color:#c1ccc3;font:9px var(--mono);letter-spacing:.12em;padding:9px 12px;margin-top:14px;text-transform:uppercase}.boot-skip:hover{border-color:var(--orange);color:#fff}
.app{position:relative;z-index:1;display:grid;grid-template-columns:226px minmax(0,1fr);min-height:100vh;opacity:0;transform:translateY(4px);transition:opacity .45s,transform .45s}.app.ready{opacity:1;transform:none}
.rail{position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:7px;padding:18px 13px 14px;border-right:1px solid #283330;background:#0c1111;z-index:30}.rail-brand{min-height:70px;display:flex;align-items:center;gap:13px;padding:8px 11px 16px;margin-bottom:13px;border-bottom:1px solid #2d3a35}.brand-mini{width:36px;height:39px;flex:0 0 36px;position:relative;background:#1b2522;border:1px solid #66736b;clip-path:polygon(0 0,75% 0,100% 25%,100% 100%,0 100%)}.brand-mini:before{content:"";position:absolute;left:7px;right:7px;top:10px;height:2px;background:var(--orange);box-shadow:0 7px 0 var(--lime),0 14px 0 #7f9085}.brand-lockup strong{display:block;font:900 17px/1 var(--display);letter-spacing:.2em;color:#eef1e8}.brand-lockup small{display:block;color:#819087;font:8px var(--mono);letter-spacing:.13em;margin-top:6px}
.nav-btn{width:100%;min-height:47px;display:flex;align-items:center;gap:12px;padding:0 11px;border:1px solid transparent;border-left:2px solid transparent;border-radius:2px;background:transparent;color:#87958c;text-align:left;transition:background .16s,border-color .16s,color .16s}.nav-btn .nav-icon{width:24px;flex:0 0 24px;color:#697970;font:10px var(--mono);text-align:left}.nav-btn small{font:700 10px var(--display);letter-spacing:.17em}.nav-btn:hover{background:#151d1b;border-color:#35423c;color:#e1e8df}.nav-btn:hover .nav-icon{color:var(--orange)}.nav-btn.active{background:#1a2320;border-color:#384840;border-left-color:var(--orange);color:#f2f3e9}.nav-btn.active .nav-icon{color:var(--lime)}.rail-spacer{flex:1}.rail-state{width:8px;height:8px;flex:0 0 8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px #7cd59c15;animation:pulse 2.4s infinite;margin:0 0 7px 5px}.rail-bottom{color:#68776e;font:8px var(--mono);letter-spacing:.17em;padding:9px 5px;border-top:1px solid #28352f}
main{min-width:0;width:100%;max-width:1840px;margin:0 auto;padding:0 clamp(15px,2vw,30px) 36px}.topbar{min-height:68px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 1px;margin-bottom:20px;border-bottom:1px solid #2b3934}.top-left{display:flex;align-items:center;gap:13px;min-width:0}.top-mark{height:31px;width:4px;background:var(--orange)}.eyebrow{color:#78867e;font:8px var(--mono);letter-spacing:.15em;text-transform:uppercase}.view-title{font:800 19px/1.1 var(--display);letter-spacing:.09em;margin-top:4px;text-transform:uppercase}.top-right{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}.clock{font:10px var(--mono);color:#8b9990;padding:0 9px}.system-badge{display:inline-flex;align-items:center;gap:8px;border:1px solid #48584e;border-radius:2px;padding:7px 10px;background:#18211c;color:var(--lime);font:9px var(--mono);letter-spacing:.12em}.led{width:6px;height:6px;flex:0 0 6px;border-radius:50%;background:currentColor;box-shadow:0 0 0 3px #b8e65b18;animation:pulse 2s infinite}.icon-btn{border:1px solid #36443d;background:#141b19;color:#aab6ac;border-radius:2px;padding:8px 11px;font:9px var(--mono);letter-spacing:.08em;transition:.16s}.icon-btn:hover{border-color:var(--orange);color:#fff;background:#202a25}
.screen{display:none;animation:rise .2s ease}.screen.active{display:block}.section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin:3px 0 13px;padding-bottom:12px;border-bottom:1px solid #27342f}.section-label{color:var(--orange);font:9px var(--mono);letter-spacing:.17em;text-transform:uppercase}.section-title{font:800 22px/1.1 var(--display);letter-spacing:.07em;margin-top:5px;text-transform:uppercase}.section-description{font-size:10px;color:#849188;max-width:650px;margin-top:6px}.tag{font:8px var(--mono);letter-spacing:.1em;color:#b7c6ba;border:1px solid #46574e;background:#18211d;border-radius:2px;padding:5px 8px;white-space:nowrap;text-transform:uppercase}
.hero{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:20px;min-height:230px;border:1px solid #3a4942;border-left:4px solid var(--orange);border-radius:2px;overflow:hidden;padding:24px 27px;background:linear-gradient(112deg,#1b2421,#121918 57%,#0f1514);box-shadow:0 14px 38px #0004}.hero:before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.25;background:repeating-linear-gradient(135deg,transparent 0 18px,#87978b09 18px 19px)}.hero:after{content:"01";position:absolute;right:235px;bottom:-67px;color:#ffffff06;font:900 220px/1 var(--display);pointer-events:none}.hero-copy{position:relative;z-index:1}.hero-kicker{font:9px var(--mono);letter-spacing:.17em;color:var(--orange);text-transform:uppercase}.hero h1{font:900 clamp(32px,4vw,52px)/.95 var(--display);letter-spacing:.035em;margin:17px 0 12px;text-transform:uppercase}.hero h1 span{color:var(--lime)}.hero p{color:#a4b0a7;font-size:11px;max-width:620px;margin:0 0 15px}.hero-meta{display:flex;gap:22px;flex-wrap:wrap}.meta-item small{display:block;color:#728078;font:8px var(--mono);letter-spacing:.12em}.meta-item b{display:block;color:#e1e8df;font:10px var(--mono);margin-top:4px}.hero-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:17px}
.hero-aside{position:relative;z-index:1;display:grid;grid-template-columns:108px 1fr;align-items:center;gap:15px;border-left:1px solid #39463f;padding-left:20px}.core-visual{width:104px;height:104px;display:grid;place-items:center;position:relative;border:1px solid #59675d;background:repeating-linear-gradient(135deg,#1b2521 0 8px,#151d1a 8px 16px)}.core-visual:before,.core-visual:after{content:"";position:absolute;inset:10px;border:1px solid #748278;transform:rotate(45deg)}.core-visual:after{inset:21px;border-color:var(--orange);opacity:.9}.core-ring{position:absolute;inset:4px;border:1px dashed #9cae9f80;border-radius:50%;animation:spin 28s linear infinite}.core-center{position:relative;z-index:2;color:var(--lime);font:900 18px var(--mono);letter-spacing:-.08em}.core-readout{display:grid;gap:13px;min-width:0}.core-state{border-bottom:1px solid #35423c;padding-bottom:8px;color:#8f9f94;font:8px var(--mono);letter-spacing:.1em}.core-state b{display:block;color:#e5e9df;font:800 11px var(--display);letter-spacing:.08em;margin-top:4px}.core-state b .state-dot{display:inline-block;width:6px;height:6px;background:var(--lime);margin:0 6px 1px 0}.core-state b .state-dot.red{background:var(--orange)}
.btn{border:1px solid #4a5a51;border-radius:2px;background:#202a25;color:#d5ddd4;padding:9px 12px;font:800 9px var(--display);letter-spacing:.1em;text-transform:uppercase;box-shadow:none;transition:background .15s,border-color .15s,color .15s,transform .15s}.btn:hover{transform:translateY(-1px);border-color:var(--lime);color:#fff;background:#2a362f}.btn.primary{background:var(--orange);border-color:var(--orange);color:#160e0a}.btn.primary:hover{background:#ff875d;border-color:#ff875d;color:#100b08}.btn.danger{color:#ffaaa0;border-color:#713e37;background:#281917}.btn.ghost{background:transparent;border-color:#3b4942;color:#9eaba2}.btn.active{border-color:var(--lime);color:var(--lime);background:#202a24}.btn:disabled{opacity:.38;cursor:not-allowed;transform:none}
.metric-row{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:10px 0 13px}.metric{position:relative;border:1px solid #2d3b35;border-top:2px solid #526158;border-radius:2px;background:#121918;padding:12px 13px;min-width:0;overflow:hidden;transition:border-color .15s,background .15s}.metric:hover{border-top-color:var(--orange);background:#18211e}.metric:after{content:"";position:absolute;right:-20px;bottom:-31px;width:72px;height:72px;border:1px solid #6c7d7118;transform:rotate(45deg)}.metric-label{color:#829087;font:8px var(--mono);letter-spacing:.12em}.metric-value{font:800 clamp(19px,2vw,25px)/1.1 var(--mono);margin:7px 0 3px;white-space:nowrap;color:#edf0e9}.metric-foot{font-size:8px;color:#718077}.meter{height:3px;background:#29342e;margin-top:9px;overflow:hidden}.meter i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--orange2),var(--orange),var(--lime));transition:width .5s}
.grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(280px,.8fr);gap:9px}.grid.equal{grid-template-columns:repeat(2,minmax(0,1fr))}.grid.triple{grid-template-columns:repeat(3,minmax(0,1fr))}.panel{position:relative;border:1px solid #2c3934;border-radius:2px;background:#111716;padding:14px;min-width:0;box-shadow:0 7px 22px #0002;overflow:hidden;transition:border-color .15s}.panel:before{content:"";position:absolute;top:0;left:0;width:27px;height:2px;background:#69786e}.panel:hover{border-color:#4a5b50}.panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #293631}.panel-title{font:800 10px var(--display);letter-spacing:.13em;color:#e4e9e1;text-transform:uppercase}.panel-sub{font-size:9px;color:#849188;margin-top:4px}.chart-wrap{height:190px;position:relative}.chart-wrap canvas{width:100%;height:100%}.legend{display:flex;gap:15px;flex-wrap:wrap;color:#87948b;font:8px var(--mono);margin-top:9px}.legend i{display:inline-block;width:8px;height:3px;margin-right:5px;background:var(--lime);vertical-align:middle}.legend i.red{background:var(--orange)}
.sensor-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px}.sensor{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:8px 9px;border:1px solid #2a3731;border-radius:2px;background:#151d1a}.sensor strong{display:block;font:800 9px var(--display);letter-spacing:.06em}.sensor small{display:block;color:#78877e;font-size:8px;margin-top:3px}.sensor-state{font:8px var(--mono);color:var(--lime);white-space:nowrap}.sensor-state.degraded,.sensor-state.partial{color:var(--amber)}.sensor-state.disabled,.sensor-state.optional{color:#78867d}
.alert-list,.event-list,.driver-list,.result-list,.audit-list,.insight-list{display:grid;gap:5px}.alert-card{border:1px solid #39463e;border-left:3px solid var(--amber);border-radius:2px;padding:9px 10px;background:#171d19}.alert-card.critical{border-left-color:var(--red)}.alert-card.info{border-left-color:var(--lime)}.alert-card.medium{border-left-color:var(--amber)}.alert-row{display:flex;align-items:center;justify-content:space-between;gap:8px}.alert-row strong{font:800 10px var(--display);letter-spacing:.04em}.alert-sev{color:var(--amber);font:8px var(--mono);letter-spacing:.1em}.alert-card.critical .alert-sev{color:var(--red)}.alert-card p{font-size:9px;color:#9aa79e;margin:5px 0 0}
.event{display:grid;grid-template-columns:27px minmax(0,1fr) auto;gap:8px;align-items:start;padding:8px 9px;border:1px solid #2a3731;border-radius:2px;background:#151c19;transition:border-color .15s,background .15s}.event:hover{border-color:#5b6d60;background:#1a2420}.event-icon{width:27px;height:27px;display:grid;place-items:center;border:1px solid #3d4b42;background:#202a24;color:var(--lime);font:10px var(--mono)}.event-name{font:800 9px var(--display);letter-spacing:.04em;overflow-wrap:anywhere;color:#e2e8df}.event-desc{font-size:8px;color:#839187;margin-top:3px;overflow-wrap:anywhere}.event-time{font:8px var(--mono);color:#718078;white-space:nowrap}.event details{margin-top:5px;color:#8c9a90;font-size:8px}.event summary{cursor:pointer;letter-spacing:.1em;color:var(--orange)}.event pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto;background:#090e0d;border:1px solid #2b3932;padding:9px;border-radius:2px;color:#afc0b4;font:8px/1.5 var(--mono)}
.scroll-list{max-height:460px;overflow:auto;padding-right:3px}.empty{border:1px dashed #3a4940;border-radius:2px;padding:18px;text-align:center;color:#87948a;font-size:9px;background:#0e1412}.search-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;margin-bottom:10px}.field,.select,.textarea{width:100%;min-width:0;border:1px solid #3a4840;border-radius:2px;background:#0b1110;color:#e5eae2;padding:9px 10px;font:10px "Segoe UI",sans-serif}.field::placeholder,.textarea::placeholder{color:#637169}.field:focus,.select:focus,.textarea:focus{border-color:var(--lime);outline:none}.textarea{min-height:96px;resize:vertical;line-height:1.55}
.system-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.info-card{border:1px solid #303d36;border-radius:2px;padding:10px;background:#151d19;min-width:0}.info-card small{display:block;color:#7f8d83;font:8px var(--mono);letter-spacing:.1em}.info-card strong{display:block;font:800 11px var(--display);margin-top:5px;overflow-wrap:anywhere;color:#e1e7df}.info-card p{font-size:8px;color:#8e9b92;margin:5px 0 0;overflow-wrap:anywhere}.button-row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.section-head .btn{flex:0 0 auto}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin:10px 0}.toggle{display:flex;align-items:flex-start;gap:10px;padding:10px;border:1px solid #303d36;background:#151d19;border-radius:2px;min-width:0}.toggle input{accent-color:var(--orange);margin:2px 0 0}.toggle strong{display:block;font:800 10px var(--display);letter-spacing:.05em}.toggle small{display:block;color:#849188;font-size:8px;margin-top:4px;line-height:1.45}.interval-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:12px 0}.interval{padding:9px;border:1px solid #303d36;background:#151d19}.interval label{display:block;color:#849188;font:8px var(--mono);letter-spacing:.09em;margin-bottom:6px}.interval input{width:100%;background:#0a100e;border:1px solid #39483f;color:#e5eae2;padding:7px 8px;font:10px var(--mono);border-radius:2px}
.action-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.action-tile{display:flex;flex-direction:column;align-items:flex-start;min-height:74px;text-align:left;padding:11px;border:1px solid #39483f;border-left:3px solid #69766c;border-radius:2px;background:#19211d;color:#dce4db;transition:.15s}.action-tile:hover{border-left-color:var(--orange);background:#222d26;transform:translateY(-1px)}.action-tile b{font:800 10px var(--display);letter-spacing:.08em}.action-tile small{font-size:8px;color:#839188;margin-top:6px;line-height:1.4}.note{font-size:9px;color:#829087;padding:8px 0;line-height:1.55}
.ai-shell{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(270px,.8fr);gap:9px}.ai-answer{border:1px solid #334139;border-left:3px solid var(--lime);border-radius:2px;background:#0d1411;padding:12px;color:#d1dbd1;font:10px/1.65 "Segoe UI",sans-serif;white-space:pre-wrap;overflow-wrap:anywhere;min-height:88px}.ai-reference{display:block;border:1px solid #344239;border-radius:2px;padding:7px 9px;color:var(--lime);font-size:9px}.ai-reference:hover{border-color:var(--orange);color:#fff}.model-card{border:1px solid #344139;padding:9px;background:#151d19;border-radius:2px}.model-card strong{display:block;color:#e3e9e1;font:800 10px var(--mono)}.model-card small{display:block;color:#839087;font-size:8px;margin-top:4px}
.driver-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:10px;align-items:center;border:1px solid #2e3c35;padding:8px 9px;background:#151d19}.driver-row strong{display:block;font:800 9px var(--display);overflow-wrap:anywhere}.driver-row small{display:block;color:#839087;font-size:8px;margin-top:3px}.driver-state{font:8px var(--mono);color:var(--lime)}.driver-state.unsigned{color:var(--red)}.disk-item{border:1px solid #303d36;background:#151d19;padding:9px;border-radius:2px}.disk-top{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:9px}.disk-meter{height:5px;background:#2d3932;margin-top:8px}.disk-meter i{display:block;height:100%;background:var(--lime)}.knowledge-card{border:1px solid #324037;background:#151d19;padding:10px;border-radius:2px}.knowledge-card strong{display:block;font:800 10px var(--display);color:#e2e8df}.knowledge-card small{display:block;color:#7e8e83;font:8px var(--mono);margin-top:4px}.knowledge-card p{font-size:9px;color:#9aa79d;line-height:1.5}.command-line{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 9px;border:1px solid #2d3b34;background:#151d19}.command-line strong{font:800 9px var(--display);letter-spacing:.04em}.command-line small{font:8px var(--mono);color:#87958a}.audit-list .command-line{border-left:2px solid #536258}
.toast-stack{position:fixed;z-index:1100;right:18px;bottom:18px;display:grid;gap:7px;width:min(360px,calc(100vw - 36px))}.toast{border:1px solid #65766a;border-left:3px solid var(--lime);background:#141c18;color:#e5ebe3;padding:11px 13px;font-size:10px;box-shadow:0 10px 30px #0009;animation:rise .16s}.toast.warn{border-left-color:var(--amber)}.toast.error{border-left-color:var(--red)}
@media(max-width:1250px){.app{grid-template-columns:196px minmax(0,1fr)}.metric-row{grid-template-columns:repeat(3,minmax(0,1fr))}.grid.triple{grid-template-columns:repeat(2,minmax(0,1fr))}.hero{grid-template-columns:minmax(0,1fr) 220px}}
@media(max-width:900px){.app{grid-template-columns:76px minmax(0,1fr)}.rail{padding:13px 8px}.rail-brand{justify-content:center;padding:5px 0 13px}.brand-lockup{display:none}.nav-btn{justify-content:center;padding:0 6px}.nav-btn .nav-icon{width:auto;flex:0 0 auto;text-align:center}.nav-btn small{display:none}.rail-bottom{writing-mode:vertical-rl;transform:rotate(180deg);padding:8px 0}.hero{grid-template-columns:1fr}.hero-aside{display:none}.grid,.grid.equal,.ai-shell{grid-template-columns:1fr}.interval-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:650px){.app{display:block;padding-bottom:68px}.rail{position:fixed;bottom:0;top:auto;left:0;right:0;width:100%;height:64px;flex-direction:row;justify-content:space-around;gap:2px;padding:5px 4px;border-right:0;border-top:1px solid #3a4940}.rail-brand,.rail-spacer,.rail-state,.rail-bottom{display:none}.nav-btn{width:auto;min-width:0;min-height:51px;flex:1;display:flex;flex-direction:column;justify-content:center;gap:3px;padding:4px;border:0;border-top:2px solid transparent}.nav-btn.active{border:0;border-top:2px solid var(--orange)}.nav-btn .nav-icon{font-size:9px}.nav-btn small{display:block;font-size:7px;letter-spacing:.04em}.topbar{min-height:62px;align-items:flex-start;padding:10px 0;margin-bottom:13px}.top-right{gap:5px}.clock{display:none}.icon-btn{padding:7px;font-size:8px}.system-badge{padding:6px 7px;font-size:8px}.view-title{font-size:16px}main{padding:0 11px 25px}.hero{min-height:0;padding:18px 17px}.hero h1{font-size:36px}.hero-meta{gap:13px}.metric-row{grid-template-columns:repeat(2,minmax(0,1fr))}.metric:last-child{grid-column:span 2}.grid,.grid.equal,.grid.triple,.ai-shell{grid-template-columns:1fr}.form-grid,.system-cards{grid-template-columns:1fr}.section-head{align-items:flex-start;flex-direction:column}.section-title{font-size:19px}.section-head .btn{width:100%}.panel{padding:11px}.event{grid-template-columns:24px minmax(0,1fr)}.event-time{grid-column:2}.driver-row{grid-template-columns:minmax(0,1fr) auto}.driver-row>small{grid-column:1}.boot-card{padding:24px 20px}.boot-emblem{width:64px;height:64px}.action-grid{grid-template-columns:1fr}.interval-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.01ms!important}}
</style>
</head>
<body>
<div class="ambient"></div><canvas id="starfield"></canvas>
<div class="boot" id="boot">
 <div class="boot-grid"></div>
 <div class="boot-card">
  <div class="boot-emblem"><div class="boot-mark">AIE</div></div>
  <div class="boot-title">AIE / SENTINEL FIELD SYSTEM</div>
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
  <div class="rail-brand"><div class="brand-mini"></div><div class="brand-lockup"><strong>AIE / 01</strong><small>SENTINEL FIELD SYSTEM</small></div></div>
  <button class="nav-btn active" data-view="cockpit" title="Command Center"><span class="nav-icon">01</span><small>COMMAND</small></button>
  <button class="nav-btn" data-view="system" title="System Intelligence"><span class="nav-icon">02</span><small>SYSTEM INTELLIGENCE</small></button>
  <button class="nav-btn" data-view="telemetry" title="Telemetry"><span class="nav-icon">03</span><small>TELEMETRY</small></button>
  <button class="nav-btn" data-view="evidence" title="Evidence Vault"><span class="nav-icon">04</span><small>EVIDENCE VAULT</small></button>
  <button class="nav-btn" data-view="ai" title="AI Laboratory"><span class="nav-icon">05</span><small>AI LABORATORY</small></button>
  <button class="nav-btn" data-view="autonomy" title="Automation"><span class="nav-icon">06</span><small>AUTONOMY</small></button>
  <button class="nav-btn" data-view="knowledge" title="Knowledge"><span class="nav-icon">07</span><small>KNOWLEDGE BASE</small></button>
  <div class="rail-spacer"></div><div class="rail-state" id="railLed"></div><div class="rail-bottom">WINDOWS 11 / LOCAL EXECUTION / USER CONTROL</div>
 </aside>
 <main>
  <header class="topbar">
   <div class="top-left"><div class="top-mark"></div><div><div class="eyebrow">AIE / SENTINEL FIELD SYSTEM — WINDOWS NODE / 01</div><div class="view-title" id="viewTitle">COMMAND CENTER</div></div></div>
   <div class="top-right"><span class="clock" id="clock">--:--:--</span><span class="system-badge" id="liveBadge"><i class="led"></i>CONNECTING</span><button class="icon-btn" id="notifyBtn">ALERTS</button><button class="icon-btn" id="refreshBtn">SYNC / F5</button><button class="icon-btn" id="stopBtn" style="border-color:#713e37;color:#ffaaa0">STOP WORKER</button></div>
  </header>

  <section class="screen active" data-screen="cockpit">
   <div class="hero">
    <div class="hero-copy">
     <div class="hero-kicker">FIELD SYSTEM / OBSERVATION CORE / LOCAL NODE 01</div>
      <h1>SYSTEM INTELLIGENCE<br><span>IN FULL VIEW.</span></h1>
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
     <div class="button-row" style="margin-bottom:12px"><button class="btn" data-preset="deep">⚡ DEEP WATCH</button><button class="btn" data-preset="balanced">◈ BALANCED</button><button class="btn" data-preset="quiet">◌ LOW IMPACT</button></div>
     <div class="note" id="presetNote">A preset updates the form only. Review and save before the worker applies it.</div>
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

  <div class="note" style="padding:22px 2px 0;text-align:center;letter-spacing:.12em">AIE / SENTINEL FIELD SYSTEM · LOCAL OBSERVATION · EVIDENCE FIRST · USER-CONTROLLED EXECUTION</div>
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
function drawCanvas(id,dataA,dataB){const canvas=$(id);if(!canvas)return;const rect=canvas.getBoundingClientRect();const w=Math.max(320,Math.round(rect.width*devicePixelRatio)),h=Math.max(150,Math.round(rect.height*devicePixelRatio));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}const ctx=canvas.getContext("2d");ctx.clearRect(0,0,w,h);const pad=18*devicePixelRatio;ctx.strokeStyle="#303c35";ctx.lineWidth=devicePixelRatio;for(let i=0;i<=4;i++){const y=pad+(h-2*pad)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke()}function line(values,color){if(values.length<2)return;ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=2*devicePixelRatio;ctx.shadowBlur=8*devicePixelRatio;ctx.shadowColor=color;values.forEach((value,index)=>{const x=pad+(w-2*pad)*index/Math.max(1,values.length-1);const y=h-pad-(h-2*pad)*Math.max(0,Math.min(100,Number(value)||0))/100;if(index===0)ctx.moveTo(x,y);else ctx.lineTo(x,y)});ctx.stroke();ctx.shadowBlur=0}line(dataA,"#b8e65b");line(dataB,"#ff6b38")}
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
 addSample(s);renderSensors(s);renderProviderDetails(s);renderWatchers(s);renderRuntime(s);renderAlerts(alerts);renderAI(s.ai||{});renderCommand(s.last_command||null);renderKnowledgeStats();
 $("telemetryFreshness").textContent="HEARTBEAT "+age(s.heartbeat_at).toUpperCase();
 if(currentView==="autonomy")renderAudit(lastEvents);
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
async function loadProfile(){try{const r=await request("/api/config");lastConfig=r.profile||{};renderProfile(lastConfig)}catch(e){$("profileNote").textContent="Profile load failed: "+e.message}}
function renderProfile(p){$("cfgRegistry").checked=p.registry_enabled===true;$("cfgDeep").checked=p.deep_inventory_enabled===true;$("cfgKnowledge").checked=p.knowledge_enabled===true;$("cfgAI").checked=p.ai_enabled===true;$("cfgPostureReview").checked=p.auto_review_on_posture_alerts===true;$("cfgRegistryReview").checked=p.auto_review_on_registry_changes===true;$("cfgRegistryInterval").value=p.registry_interval_seconds??180;$("cfgDeepInterval").value=p.deep_inventory_interval_seconds??900;$("cfgKnowledgeInterval").value=p.knowledge_interval_seconds??21600;$("cfgAIInterval").value=p.analysis_interval_seconds??300;$("cfgDiskThreshold").value=p.low_disk_alert_percent??10;$("cfgBatteryThreshold").value=p.low_battery_alert_percent??15;$("cfgEventLogs").checked=p.include_event_logs===true;$("cfgEtw").checked=p.include_etw===true;$("cfgWindowTitles").checked=p.include_window_titles===true;$("cfgUITreeApps").value=Array.isArray(p.ui_tree_apps)?p.ui_tree_apps.join(", "):""}
function applyPreset(name){
 const presets={
  deep:{registry:true,deep:true,knowledge:true,ai:true,posture:true,registryReview:true,registrySec:90,deepSec:300,knowledgeSec:3600,aiSec:120,disk:10,battery:15},
  balanced:{registry:true,deep:true,knowledge:true,ai:true,posture:true,registryReview:false,registrySec:180,deepSec:900,knowledgeSec:21600,aiSec:300,disk:10,battery:15},
  quiet:{registry:true,deep:true,knowledge:true,ai:true,posture:true,registryReview:false,registrySec:900,deepSec:3600,knowledgeSec:86400,aiSec:900,disk:8,battery:12}
 };
 const p=presets[name];if(!p)return;
 $("cfgRegistry").checked=p.registry;$("cfgDeep").checked=p.deep;$("cfgKnowledge").checked=p.knowledge;$("cfgAI").checked=p.ai;
 $("cfgPostureReview").checked=p.posture;$("cfgRegistryReview").checked=p.registryReview;
 $("cfgRegistryInterval").value=p.registrySec;$("cfgDeepInterval").value=p.deepSec;$("cfgKnowledgeInterval").value=p.knowledgeSec;$("cfgAIInterval").value=p.aiSec;
 $("cfgDiskThreshold").value=p.disk;$("cfgBatteryThreshold").value=p.battery;
 $("presetNote").textContent=name.toUpperCase()+" PRESET LOADED · Review the thresholds and press SAVE PROFILE to commit.";
 toast(name.toUpperCase()+" preset loaded. Save to apply.");
}
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
function drawStars(){const canvas=$("starfield");if(!canvas)return;const ctx=canvas.getContext("2d");let points=[];function resize(){canvas.width=Math.max(320,innerWidth*devicePixelRatio);canvas.height=Math.max(300,innerHeight*devicePixelRatio);points=Array.from({length:72},()=>({x:Math.random()*canvas.width,y:Math.random()*canvas.height,r:Math.random()*1.4+.3,s:Math.random()*.18+.04}))}function paint(move){ctx.clearRect(0,0,canvas.width,canvas.height);for(const p of points){ctx.fillStyle="rgba(184,230,91,.42)";ctx.beginPath();ctx.arc(p.x,p.y,p.r*devicePixelRatio,0,Math.PI*2);ctx.fill();if(move){p.y+=p.s*devicePixelRatio;if(p.y>canvas.height)p.y=0}}if(move)requestAnimationFrame(()=>paint(true))}resize();addEventListener("resize",()=>{resize();paint(false)});paint(!matchMedia("(prefers-reduced-motion: reduce)").matches)}
$("pauseBtn").addEventListener("click",async()=>{try{await post("/api/control",{action:"pause"});toast("Sensor pause requested.");refresh()}catch(e){toast(e.message,"error")}});
$("stopBtn").addEventListener("click",async()=>{if(!confirm("Stop the Sentinel background worker? The dashboard will disconnect until it is started again."))return;try{await post("/api/control",{action:"stop"});toast("Stop request sent. The local dashboard will close when the worker exits.","warn")}catch(e){toast(e.message,"error")}});
$("resumeBtn").addEventListener("click",async()=>{try{await post("/api/control",{action:"resume"});toast("Sentinel watch resumed.");refresh()}catch(e){toast(e.message,"error")}});
$("notifyBtn").addEventListener("click",enableNotifications);$("notifyEnable").addEventListener("click",enableNotifications);
$("refreshBtn").addEventListener("click",()=>refresh(true));$("modelRefresh").addEventListener("click",()=>{lastModelsFetch=0;loadModels()});
$("saveProfile").addEventListener("click",saveProfile);$("reloadProfile").addEventListener("click",loadProfile);
document.querySelectorAll("[data-preset]").forEach(button=>button.addEventListener("click",()=>applyPreset(button.dataset.preset)));
$("askBtn").addEventListener("click",askSentinel);$("aiQuestion").addEventListener("keydown",e=>{if(e.key==="Enter")askSentinel()});
$("driverSearch").addEventListener("click",searchDrivers);$("driverQuery").addEventListener("keydown",e=>{if(e.key==="Enter")searchDrivers()});
$("catalogSearch").addEventListener("click",()=>loadCatalog());
$("catalogQuery").addEventListener("keydown",e=>{if(e.key==="Enter")loadCatalog()});
document.querySelectorAll("[data-catalog]").forEach(button=>button.addEventListener("click",()=>loadCatalog(button.dataset.catalog)));
$("knowledgeSearch").addEventListener("click",searchKnowledge);$("knowledgeQuery").addEventListener("keydown",e=>{if(e.key==="Enter")searchKnowledge()});
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
