/* logs.js — tails the project's own logs through the API's allow-list. */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var esc = VC.esc;
  var kind = "session", timer = null, lastLines = [];

  function classify(line) {
    if (/^#{1,3}\s/.test(line)) return "ln-h";
    if (/\bPASS\b|\bDONE\b|✓/.test(line)) return "ln-ok";
    if (/\bFAIL\b|\bBLOCKED\b|\bOPEN\b|✗/.test(line)) return "ln-bad";
    if (/^\s*[-|]/.test(line)) return "";
    return "ln-dim";
  }

  function paint() {
    var box = document.getElementById("logBox");
    var q = (document.getElementById("logFilter").value || "").trim();
    var rx = q ? new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig") : null;
    var out = lastLines.filter(function (l) { return !q || l.toLowerCase().indexOf(q.toLowerCase()) >= 0; })
      .map(function (l) {
        var safe = esc(l);
        if (rx) safe = safe.replace(rx, "<mark>$1</mark>");
        return "<span class='" + classify(l) + "'>" + safe + "</span>";
      }).join("\n");
    box.innerHTML = out || "<span class='ln-dim'>(nothing matches)</span>";
    if (document.getElementById("followSwitch").checked) box.scrollTop = box.scrollHeight;
  }

  function load() {
    VC.api.logs(kind, 500).then(function (r) {
      lastLines = r.lines || [];
      paint();
    });
  }

  function init() {
    document.querySelectorAll(".seg").forEach(function (b) {
      b.addEventListener("click", function () {
        document.querySelectorAll(".seg").forEach(function (x) {
          x.classList.remove("on"); x.setAttribute("aria-selected", "false");
        });
        b.classList.add("on"); b.setAttribute("aria-selected", "true");
        kind = b.dataset.kind; load();
      });
    });
    document.getElementById("logFilter").addEventListener("input", paint);
    document.getElementById("followSwitch").addEventListener("change", function () {
      if (timer) { clearInterval(timer); timer = null; }
      if (this.checked) timer = setInterval(load, 4000);
    });
    load();
  }

  VC.logs = { init: init, reload: load };
})(window);
