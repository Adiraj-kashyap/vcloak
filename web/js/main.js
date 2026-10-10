/* main.js — boot, tab routing, live strip. */
(function (global) {
  "use strict";
  var VC = global.VC;

  function switchView(name) {
    document.querySelectorAll(".tab").forEach(function (t) {
      var on = t.dataset.view === name;
      t.setAttribute("aria-selected", String(on));
    });
    document.querySelectorAll(".view").forEach(function (v) {
      v.hidden = v.id !== "view-" + name;
    });
    if (name === "experiments" && VC.experiments) VC.experiments.refresh();
    if (name === "logs" && VC.logs) VC.logs.reload();
    try { history.replaceState(null, "", "#" + name); } catch (e) { /* file:// */ }
  }

  function tickStrip() {
    VC.api.stats().then(function (s) {
      var set = function (id, v) { var n = document.getElementById(id); if (n) n.textContent = v; };
      set("ls-epoch", s.epoch !== undefined ? s.epoch : "—");
      set("ls-win", s.win !== undefined ? s.win : "—");
      set("ls-queued", s.queued !== undefined ? s.queued : "—");
      set("ls-slots", s.slots !== undefined ? s.slots : "—");
      set("ls-mode", s.mode || VC.state.mode);
      set("ls-backend", s.gpu ? (s.gpu.backend + " · " + s.gpu.runner) : (s.demo ? "demo" : "cpu"));
      var bar = document.getElementById("ls-fillbar");
      if (bar && s.slots) bar.style.width = Math.min(100, (s.queued / s.slots) * 100) + "%";
    });
  }

  function conn() {
    var c = document.getElementById("conn");
    if (!c) return;
    if (VC.state.live) {
      c.className = "chip chip-live";
      c.textContent = VC.state.dev ? "live · dev" : "live";
      c.title = "Connected to the backend";
    } else {
      c.className = "chip chip-demo";
      c.textContent = "demo data";
      c.title = VC.api.canFetch
        ? "Backend not reachable — showing the last exported data"
        : "Opened from a file — showing bundled demo data";
    }
  }

  function init() {
    VC.initTheme();
    document.getElementById("themeBtn").addEventListener("click", VC.toggleTheme);

    document.querySelectorAll(".tab").forEach(function (t) {
      t.addEventListener("click", function () { switchView(t.dataset.view); });
    });

    VC.api.hello().then(function () {
      conn();
      VC.chat.init();
      VC.dashboard.init();
      VC.logs.init();
      VC.arch.init();
      setTimeout(function () { VC.experiments.init(); }, 60);
      tickStrip();
      setInterval(tickStrip, 1000);

      var want = (location.hash || "#chat").slice(1);
      switchView(["chat", "dashboard", "experiments", "logs", "arch"].indexOf(want) >= 0 ? want : "chat");
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
