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

  /* The epoch clock is the server's: every answer of /v1/stats/live carries its `now_ms`, and between
   * two answers the strip counts on from the last one with the page's monotonic clock. An answer older
   * than STALE_MS is not counted on from: the strip then shows no epoch instead of a guess. */
  var POLL_MS = 1000, PAINT_MS = 50, STALE_MS = 3000;
  var anchor = null;   // { at, nowMs, epochMs } of the last answer that had an epoch
  var last = null;     // the last answer, for the tests and the evidence capture

  function set(id, v) { var n = document.getElementById(id); if (n) n.textContent = v; }
  function shown(v) { return v === undefined || v === null ? "—" : v; }

  function epochNow() {
    if (!anchor || performance.now() - anchor.at > STALE_MS) return null;
    return Math.floor((anchor.nowMs + performance.now() - anchor.at) / anchor.epochMs);
  }

  function paintEpoch() { set("ls-epoch", shown(epochNow())); }

  function backendLabel(s) {
    if (s.demo) return ["demo", "Bundled demo data: no server"];
    if (!s.gpu) return ["none", "The baseline stores each message as it arrives: nothing is computed"];
    var what = s.gpu.backend === "numpy"
      ? "the numpy thread model on the host CPU: correctness only, never a GPU result"
      : "CUDA through CuPy";
    return [s.gpu.backend + " · " + s.gpu.runner,
            what + (s.gpu.device ? " (" + s.gpu.device + ")" : "")
              + (s.gpu.util !== null && s.gpu.util !== undefined ? ", GPU load " + s.gpu.util + "%" : "")];
  }

  function paintStrip(s) {
    var strip = document.getElementById("livestrip");
    last = s;
    if (s.unavailable) {            // a live server that went silent: keep nothing on screen that would look current
      anchor = null;
      if (strip) strip.classList.add("ls-stale");
      ["ls-win", "ls-queued", "ls-slots"].forEach(function (id) { set(id, "—"); });
      set("ls-backend", "no answer");
      paintEpoch();
      return;
    }
    if (strip) strip.classList.remove("ls-stale");
    var epochs = s.epoch !== undefined && s.epoch !== null && s.epoch_ms > 0;
    anchor = epochs ? { at: s.at, nowMs: s.now_ms, epochMs: s.epoch_ms } : null;
    paintEpoch();
    set("ls-win", shown(s.win));
    set("ls-queued", shown(s.queued));
    set("ls-slots", shown(s.slots));
    set("ls-mode", s.mode || VC.state.mode);
    var fill = document.getElementById("ls-fillnote"), none = document.getElementById("ls-noepoch");
    if (fill) fill.hidden = !epochs;
    if (none) none.hidden = epochs;
    var label = backendLabel(s), b = document.getElementById("ls-backend");
    if (b) { b.textContent = label[0]; b.parentNode.title = label[1]; }
    var e = document.getElementById("ls-epoch");
    if (e) e.parentNode.title = s.last_epoch !== undefined && s.last_epoch !== null
      ? "The open epoch by the server's clock; the last epoch in the store is " + s.last_epoch : "";
    var bar = document.getElementById("ls-fillbar");
    if (bar) bar.style.width = (epochs && s.slots ? Math.min(100, (s.queued / s.slots) * 100) : 0) + "%";
  }

  function tickStrip() { return VC.api.stats().then(paintStrip); }

  VC.strip = { tick: tickStrip, epoch: epochNow, last: function () { return last; } };

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
      setInterval(tickStrip, POLL_MS);
      setInterval(paintEpoch, PAINT_MS);

      var want = (location.hash || "#chat").slice(1);
      switchView(["chat", "dashboard", "experiments", "logs", "arch"].indexOf(want) >= 0 ? want : "chat");
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
