/* Embed mode: lets the Nocturne shell host any classic screen inside its own panel.
   /?classic=1&embed=1&v=<screen> hides the classic chrome and opens that screen. */
(function () {
  var q = new URLSearchParams(location.search);
  if (q.get("embed") !== "1") return;
  document.documentElement.classList.add("embed");
  var v = q.get("v");
  if (v) { try { localStorage.setItem("sv", v); } catch (e) { } }
})();
