/* store.js — tiny shared state: theme, mode, connection status, helpers. */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};

  var state = {
    live: false,            // true once the API answers
    dev: false,             // dev endpoints available
    mode: "vcloak",         // vcloak | baseline
    switchable: false,      // the server can change its store mode (serve --dev --compare)
    reveal: false,
    backend: "—",
    runner: "—"
  };

  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("vcloak-theme", t); } catch (e) { /* private mode */ }
  }
  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem("vcloak-theme"); } catch (e) { /* ignore */ }
    if (saved) {
      document.documentElement.setAttribute("data-theme", saved);
    } else {
      var dark = global.matchMedia && global.matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    }
  }
  function toggleTheme() {
    var cur = document.documentElement.getAttribute("data-theme");
    setTheme(cur === "dark" ? "light" : "dark");
    document.dispatchEvent(new CustomEvent("vc:theme"));
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  VC.state = state;
  VC.initTheme = initTheme;
  VC.toggleTheme = toggleTheme;
  VC.esc = esc;
  VC.el = el;
})(window);
