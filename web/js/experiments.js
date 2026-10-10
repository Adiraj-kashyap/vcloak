/* experiments.js — the live order-recovery attack.
 *
 * Demo mode replays the measured accuracy for the chosen layout and animates a sample.
 * Live mode (M18 S4) calls /v1/eval/attack and animates the returned result instead;
 * either way the number shown is the number that was measured, never invented here.
 */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var esc = VC.esc, el = VC.el;

  var LABELS = {
    conventional: "Conventional", epoch: "Review-1", "1": "W = 1 s",
    "10": "W = 10 s", "60": "W = 60 s", "300": "W = 300 s"
  };

  function accuracyFor(layout) {
    /* read it out of the dashboard payload — never hard-coded here */
    var d = VC.dashboard && VC.dashboard.data && VC.dashboard.data();
    if (!d) return null;
    var ch = (d.charts || []).filter(function (c) { return c.id === "attack_ablation"; })[0];
    if (!ch) return null;
    var i = ch.categories.indexOf(LABELS[layout]);
    if (i < 0) return null;
    var meas = ch.series.filter(function (s) { return /Measured/i.test(s.name); })[0];
    return meas ? meas.values[i] : null;
  }

  function seeded(n) { var s = n; return function () { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; }; }

  function run() {
    var layout = document.getElementById("expW").value;
    var acc = accuracyFor(layout);
    var viz = document.getElementById("attackViz");
    var stats = document.getElementById("attackStats");
    var btn = document.getElementById("runAttack");
    btn.disabled = true; btn.textContent = "Running…";

    VC.api.attack(layout).then(function (live) {
      var accuracy = (live && typeof live.turn_accuracy === "number")
        ? live.turn_accuracy * 100 : acc;
      var isLive = !!live;

      if (accuracy === null || accuracy === undefined) {
        stats.innerHTML = "<div class='bigstat'><div class='k'>No result</div>" +
          "<div class='v'>NOT MEASURED</div><div class='k'>Run M14 to produce this layout's number.</div></div>";
        viz.innerHTML = ""; btn.disabled = false; btn.textContent = "Run attack"; return;
      }

      /* Animate 24 consecutive reply pairs. The number of hits is exactly the measured
         rate applied to 24 (not a random draw), so the sample cannot contradict the
         headline figure; only their positions are shuffled, deterministically. */
      var N = 24, nHit = Math.round(N * accuracy / 100);
      var hits = [], rnd = seeded(Math.round(accuracy * 97) + 7);
      for (var i = 0; i < N; i++) hits.push(i < nHit);
      for (var a = N - 1; a > 0; a--) {            // seeded Fisher-Yates
        var bI = Math.floor(rnd() * (a + 1)), tmp = hits[a];
        hits[a] = hits[bI]; hits[bI] = tmp;
      }

      viz.innerHTML = "<div class='seqlabel'>24 consecutive reply pairs — did the attacker get each one in the right order?</div>";
      var row = el("div", "seqrow");
      viz.appendChild(row);
      var cells = [];
      for (var j = 0; j < N; j++) {
        var c = el("div", "seqcell", String(j + 1));
        row.appendChild(c); cells.push(c);
      }
      var key = el("div", "legend");
      key.innerHTML = "<span><i style='background:var(--crit)'></i>attacker ordered the pair correctly</span>" +
                      "<span><i style='background:var(--good-wash);border:1px solid var(--grid)'></i>attacker got it wrong</span>";
      viz.appendChild(key);
      var caption = el("p", "note");
      viz.appendChild(caption);

      var k = 0, hitCount = 0;
      (function step() {
        if (k >= N) {
          caption.innerHTML = "<b>" + hitCount + " of " + N + "</b> ordered correctly — the measured rate of <b>" +
            accuracy.toFixed(1) + "%</b> applied to 24 pairs.";
          btn.disabled = false; btn.textContent = "Run attack";
          return;
        }
        var hit = hits[k];
        cells[k].classList.add(hit ? "hit" : "miss");
        cells[k].textContent = hit ? "✓" : "✗";
        if (hit) hitCount++;
        k++;
        setTimeout(step, 55);
      })();

      var verdict = accuracy > 90 ? ["Order fully recoverable", "crit"]
                  : accuracy > 60 ? ["Partially recoverable", "warn"]
                  : ["Indistinguishable from guessing", "good"];
      stats.innerHTML =
        "<div class='bigstat'><div class='k'>Turn-order accuracy</div>" +
        "<div class='v' style='color:" + (verdict[1] === "good" ? "var(--good)" : verdict[1] === "crit" ? "var(--crit)" : "var(--ink)") + "'>" +
        accuracy.toFixed(1) + "%</div>" +
        "<div class='k'>" + esc(verdict[0]) + " · 50% = coin flip</div></div>" +
        "<div class='bigstat'><div class='k'>Layout</div><div class='v' style='font-size:19px'>" +
        esc(LABELS[layout]) + "</div></div>" +
        "<div class='bigstat'><div class='k'>Source</div><div class='v' style='font-size:15px'>" +
        (isLive ? "live run against the database" : "stored measurement (demo mode)") + "</div></div>";
    });
  }

  function ablation() {
    var panel = document.getElementById("ablationPanel");
    var d = VC.dashboard && VC.dashboard.data && VC.dashboard.data();
    if (!panel || !d) return;
    var ch = (d.charts || []).filter(function (c) { return c.id === "attack_ablation"; })[0];
    panel.innerHTML = "";
    if (!ch) { panel.hidden = true; return; }
    panel.hidden = false;
    var head = el("div", "panel-head"); head.appendChild(el("h2", null, "Every layout, side by side"));
    panel.appendChild(head);
    var wrap = el("div", null); wrap.style.padding = "14px 16px";
    wrap.appendChild(VC.charts.card(ch));
    panel.appendChild(wrap);
  }

  var hasRun = false;

  function idle() {
    var viz = document.getElementById("attackViz");
    var stats = document.getElementById("attackStats");
    if (!viz || !stats) return;
    viz.innerHTML = "<div class='seqlabel'>Pick a store layout and press <b>Run attack</b>. " +
      "Each square is one pair of consecutive messages: did the attacker put them in the right order?</div>";
    var row = el("div", "seqrow");
    for (var i = 0; i < 24; i++) row.appendChild(el("div", "seqcell", String(i + 1)));
    viz.appendChild(row);
    stats.innerHTML = "<div class='bigstat'><div class='k'>Turn-order accuracy</div>" +
      "<div class='v' style='color:var(--muted)'>—</div>" +
      "<div class='k'>not run yet · 50% would be a coin flip</div></div>";
  }

  function init() {
    var btn = document.getElementById("runAttack");
    if (btn) btn.addEventListener("click", function () { hasRun = true; run(); });
    idle();
    ablation();
  }

  function refresh() {
    ablation();
    if (!hasRun) { hasRun = true; setTimeout(run, 250); }   // show a result on first visit
  }

  VC.experiments = { init: init, refresh: refresh };
})(window);
