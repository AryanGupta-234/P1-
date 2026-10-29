/* Nocturne console banners: every screen opens with the same crimson banner.
   Screens that already have their own header keep it (restyled in nocturne.css);
   the rest get one. DOM-only: no data, endpoints or logic are touched. */
(function () {
  var DESC = {
    agent: "Runtime footprint, collectors and agent health",
    sys: "Platform, storage and security inventory",
    act: "Live events and collector heartbeats",
    activityx: "Foreground usage and learned routines",
    proc: "Windows processes, identities and load",
    net: "Latency, jitter and active connections",
    ker: "Kernel counter history and latency",
    adv: "Thermals, sensors and tuning",
    eng: "Safeguards, runtime and memory policy",
    intelx: "Memories, goals and ranked context",
    int: "Local intelligence results",
    ai: "Model availability and council conversation",
    evi: "Searchable event records",
    ctl: "Approvals and action history",
    fc: "Preferences and audit history",
    tsk: "Jobs and run history",
    maint: "Previewed, reversible maintenance"
  };
  var HEADS = ["command-hero", "engine-head", "agent-overview-head", "proc-command-head", "signal-page-head", "adv-page-head",
    "maint-head", "system-node-banner", "activity-page-head", "ix-specialist-head"];
  var $ = function (s, r) { return (r || document).querySelector(s); };

  function hasHead(view) {
    var first = view.firstElementChild;
    if (!first) return false;
    return HEADS.some(function (c) { return first.classList.contains(c) || first.querySelector("." + c); });
  }
  function build() {
    document.querySelectorAll(".view").forEach(function (view) {
      var key = view.id.replace(/^v-/, "");
      if (key === "cmd" || $(":scope > .nx-banner", view) || hasHead(view)) return;
      var btn = $('#nav button[data-v="' + key + '"] .lb');
      var title = (btn && btn.textContent.trim()) || key.toUpperCase();
      var el = document.createElement("section");
      el.className = "nx-banner";
      el.innerHTML = '<div><span>SENTINEL / WINDOWS NODE</span><b></b><small></small></div>' +
        '<div class="nx-stats"><div>LAG INDEX<b data-nx="lag">--</b></div><div>UPTIME<b data-nx="up">--</b></div></div>';
      $("b", el).textContent = title;
      $("small", el).textContent = DESC[key] || "";
      view.insertBefore(el, view.firstChild);
    });
  }
  function sync() {
    var lag = $("#h-lag"), up = $("#h-up");
    document.querySelectorAll(".nx-banner").forEach(function (el) {
      if (!el.offsetParent) return;
      var a = $('[data-nx="lag"]', el), b = $('[data-nx="up"]', el);
      if (lag && a) a.textContent = lag.textContent;
      if (up && b) b.textContent = up.textContent;
    });
  }

  /* Tone engine: assigns ink / forest / crimson to the cards of the open screen so the
     three colours cover (roughly) equal area. Banners count as crimson. Existing tones are
     kept, so cards never flicker when live data changes their height. */
  var BANNERS = ".nx-banner," + HEADS.map(function (c) { return "." + c; }).join(",");
  var TONES = ["ink", "forest", "red"];
  function area(el) { var r = el.getBoundingClientRect(); return r.width * r.height; }
  function tone() {
    var view = $(".view.on"); if (!view) return;
    var sum = { ink: 0, forest: 0, red: 0 };
    view.querySelectorAll(BANNERS).forEach(function (b) { sum.red += area(b); });
    var cards = [].slice.call(view.querySelectorAll(".panel, .metrics > *, .signal-strip > *, .engine-pulse-rail > *"))
      .filter(function (el) { return !(el.parentElement && el.parentElement.closest(".panel")) && el.offsetParent; });
    cards.forEach(function (el) { TONES.forEach(function (t) { if (el.classList.contains("tone-" + t)) sum[t] += area(el); }); });
    cards.forEach(function (el) {
      if (TONES.some(function (t) { return el.classList.contains("tone-" + t); })) return;
      var a = area(el); if (!a) return;
      var canRed = !el.querySelector("canvas") && el.getBoundingClientRect().height < 560;
      var pick = TONES.filter(function (t) { return t !== "red" || canRed; })
        .sort(function (x, y) { return sum[x] - sum[y]; })[0];
      sum[pick] += a; el.classList.add("tone-" + pick);
    });
  }
  var timer = 0;
  function later() { clearTimeout(timer); timer = setTimeout(tone, 260); }
  function watch() {
    var main = $("main"); if (!main) return;
    new MutationObserver(later).observe(main, { childList: true, subtree: true });
    document.addEventListener("click", later, true);
    later();
  }
  function start() { build(); sync(); watch(); setInterval(sync, 2000); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
