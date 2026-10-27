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
  function start() { build(); sync(); setInterval(sync, 2000); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
