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

  /* where the lines came from, in words: the page never shows demo lines as the project's own */
  function note(r) {
    var el = document.getElementById("logNote");
    if (r.unavailable) {
      el.textContent = "This server does not serve its logs (they are offered with --dev only).";
    } else if (r.demo) {
      el.textContent = "Demo mode: example lines, not this project's log. Start the service with --dev to tail state/.";
    } else if (r.missing) {
      el.textContent = "The server has no " + r.kind + " log to serve.";
    } else {
      el.textContent = "The last " + r.lines.length + " of " + r.total + " lines, through the server's redaction" +
        (r.redacted ? " (" + r.redacted + " lines had a path, an address, an id or a token replaced)." : ".");
    }
  }

  function load() {
    VC.api.logs(kind, 500).then(function (r) {
      lastLines = r.lines || [];
      note(r);
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
