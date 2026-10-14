/* experiments.js — the order-recovery attack, live (M18 S4).
 *
 * Live (`serve --dev`): POST /v1/eval/attack replays the M14 seed traffic into a new store of the chosen
 * layout, dumps it and attacks the dump; the page polls GET /v1/eval/attack and animates what came back:
 * one visible round of the dump in physical order (the attacker's guess) with each row's true rank, the
 * first 24 turns scored right or wrong, and the accuracy against chance. The live number is then compared
 * with the stored one of the same seed and sizes (dashboard.json → experiments.attack).
 * Otherwise: the stored number, with its provenance, and an illustration that says it is one.
 * Every number shown comes from the server or from dashboard.json; none is computed or typed here.
 */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var esc = VC.esc, el = VC.el;
  var POLL_MS = 1000, STEP_MS = 55, N = 24;
  var runToken = 0;

  function experiment() {
    var d = VC.dashboard && VC.dashboard.data && VC.dashboard.data();
    return (d && d.experiments && d.experiments.attack) || null;
  }

  function stored(layout) {
    var e = experiment();
    if (!e) return null;
    return e.layouts.filter(function (x) { return x.layout === layout; })[0] || null;
  }

  function label(layout) {
    var opt = document.querySelector("#expW option[value='" + layout + "']");
    return opt ? opt.textContent : layout;
  }

  function pct(x) { return (x * 100).toFixed(1) + "%"; }

  /* ── the panels ─────────────────────────────────────────────────────────── */

  function chanceBar(acc) {
    /* accuracy on a 0..100 track; the chance mark is a coin flip, a public reference */
    var w = el("div", "chancebar");
    w.innerHTML = "<div class='track'><div class='fill' style='width:" + (acc * 100).toFixed(2) + "%'></div>" +
      "<div class='chance' style='left:50%'><span>chance 50%</span></div></div>";
    return w;
  }

  function statsPanel(acc, st, live) {
    var stats = document.getElementById("attackStats");
    var verdict = acc > 0.9 ? "the order is recovered" : acc > 0.6 ? "partly recovered" : "close to a coin flip";
    stats.innerHTML = "";
    var big = el("div", "bigstat");
    big.innerHTML = "<div class='k'>Turn-order accuracy · " + esc(live ? "this live run" : "stored result") + "</div>" +
      "<div class='v'>" + pct(acc) + "</div><div class='k'>" + esc(verdict) + " · 50% = coin flip</div>";
    big.appendChild(chanceBar(acc));
    stats.appendChild(big);

    var src = el("div", "bigstat");
    if (live) {
      var r = live;
      src.innerHTML = "<div class='k'>This run</div><div class='v small'>" + esc(label(r.layout)) + "</div>" +
        "<div class='k mono'>seed " + esc(r.seed) + " · " + esc(r.params.n_conv) + " conversations · " +
        esc(r.params.duration_s) + " s simulated · " + esc(r.messages) + " messages · " + esc(r.visible_rounds) +
        " visible rounds<br>" + esc(r.backend) + " backend · " + esc(r.store) + "</div>";
    } else {
      src.innerHTML = "<div class='k'>Source</div><div class='v small'>stored measurement</div>" +
        "<div class='k mono'>" + esc(st.metric_id) + " · " + esc(st.run) + " · " + esc(st.backend) + "/" +
        esc(st.runner) + " · " + esc(st.stat) + "</div>";
    }
    stats.appendChild(src);
    if (live) stats.appendChild(matchPanel(live, st));
  }

  /* The S4 check, on screen: same seed and sizes → the live value must equal the stored one exactly. */
  function matchPanel(r, st) {
    var box = el("div", "bigstat");
    if (!st || st.value === null || st.value === undefined) {
      box.innerHTML = "<div class='k'>Stored result</div><div class='v small'>NOT MEASURED</div>" +
        "<div class='k'>No indexed value for this layout to compare with.</div>";
      return box;
    }
    var same = !r.quick && r.seed === st.seed && ["n_conv", "duration_s", "buckets", "rate"].every(function (k) {
      return r.params[k] === st.params[k];
    });
    var head = "<div class='k'>Against the stored " + esc(st.metric_id) + " (" + esc(st.backend) + "/" + esc(st.runner) + ")</div>";
    if (!same) {
      box.innerHTML = head + "<div class='v small'>not comparable</div><div class='k'>This run used other sizes " +
        "or another seed than " + esc(st.run) + ".</div>";
      return box;
    }
    var eq = r.turn_order_accuracy === st.value;
    box.className = "bigstat " + (eq ? "match" : "nomatch");
    box.innerHTML = head + "<div class='v small'>" + (eq ? "✓ identical" : "✗ different") + "</div>" +
      "<div class='k mono'>live&nbsp;&nbsp; " + esc(String(r.turn_order_accuracy)) + "<br>stored " +
      esc(String(st.value)) + "<br>" + esc(st.run) + "</div>";
    return box;
  }

  function roundPanel(viz, round) {
    var head = el("div", "seqlabel");
    viz.appendChild(head);
    if (!round || !round.rows.length) {
      head.textContent = "No visible round of this dump holds enough rows to show.";
      return function () {};
    }
    head.innerHTML = "<b>The dump.</b> Visible round " + esc(round.win) + ": " + esc(round.rows.length) + " of its " +
      esc(round.rows_in_round) + " rows, in the order the store holds them. That order is all the attacker has " +
      "inside a round; the number is when each row was really sent, among the rows shown.";
    var row = el("div", "seqrow");
    viz.appendChild(row);
    var cells = round.rows.map(function (r) {
      var c = el("div", "seqcell dump", "?");
      c.title = "physical position " + (r.pos + 1);
      row.appendChild(c);
      return c;
    });
    return function reveal(k) {
      if (k < cells.length) {
        var r = round.rows[k];
        cells[k].textContent = String(r.rank);
        cells[k].classList.add(r.rank === r.pos + 1 ? "inplace" : "moved");
      }
    };
  }

  function turnsPanel(viz, turns, total) {
    var head = el("div", "seqlabel");
    head.innerHTML = "<b>The attacker's guess.</b> The first " + esc(turns.length) + " of " + esc(total) +
      " turns (two consecutive messages of one conversation): did the dump put them in the right order?";
    viz.appendChild(head);
    var row = el("div", "seqrow");
    viz.appendChild(row);
    var cells = turns.map(function (t, i) {
      var c = el("div", "seqcell", String(i + 1));
      c.title = t.same_round ? "both messages in one visible round" : "messages in different visible rounds";
      row.appendChild(c);
      return c;
    });
    var key = el("div", "legend");
    key.innerHTML = "<span><i class='k-hit'></i>✓ attacker ordered the turn correctly</span>" +
                    "<span><i class='k-miss'></i>✗ attacker got it wrong</span>" +
                    "<span><i class='k-same'></i>underlined: both inside one visible round</span>";
    viz.appendChild(key);
    return function reveal(k) {
      if (k < cells.length) {
        var t = turns[k];
        cells[k].classList.add(t.hit ? "hit" : "miss");
        if (t.same_round) cells[k].classList.add("same");
        cells[k].textContent = t.hit ? "✓" : "✗";
      }
    };
  }

  function animate(steps, done) {
    var k = 0;
    (function step() {
      if (k >= steps.n) { done(); return; }
      steps.fns.forEach(function (f) { f(k); });
      k++;
      setTimeout(step, STEP_MS);
    })();
  }

  /* ── live ───────────────────────────────────────────────────────────────── */

  function showLive(r) {
    var st = stored(r.layout);
    var viz = document.getElementById("attackViz");
    viz.innerHTML = "";
    var smp = r.sample || { turns: [], turns_total: 0, round: null };
    var a = roundPanel(viz, smp.round);
    var b = turnsPanel(viz, smp.turns, smp.turns_total);
    var cap = el("p", "note");
    viz.appendChild(cap);
    var n = Math.max(smp.turns.length, smp.round ? smp.round.rows.length : 0);
    animate({ n: n, fns: [a, b] }, function () {
      var hits = smp.turns.filter(function (t) { return t.hit; }).length;
      cap.innerHTML = "<b>" + hits + " of " + smp.turns.length + "</b> of these turns ordered correctly; over all " +
        esc(smp.turns_total) + " turns of the replay: <b>" + pct(r.turn_order_accuracy) + "</b>" +
        (r.predicted_turn_accuracy !== null ? " (the run's own prediction 1 − f/2: " + pct(r.predicted_turn_accuracy) + ")" : "") + ".";
      done();
    });
    statsPanel(r.turn_order_accuracy, st, r);
    note("Live run against a new store built for it: the store the chat is using cannot be scored, because the " +
         "server does not know the true order (that is what it hides). " + (r.ok ? "All the run's checks passed." :
         "Some of the run's checks FAILED: " + Object.keys(r.checks).filter(function (k) { return !r.checks[k]; }).join(", ") + "."));
  }

  function poll(token, layout) {
    VC.api.attackState().then(function (ans) {
      if (token !== runToken) return;
      var s = ans && ans.status === 200 ? ans.body : null;
      if (!s) { showStored(layout, "The live run stopped answering; the stored result is shown."); return; }
      if (s.state === "running") {
        progress(s);
        setTimeout(function () { poll(token, layout); }, POLL_MS);
      } else if (s.state === "done") {
        showLive(s.result);
      } else {
        showStored(layout, "The live run failed (" + (s.error || s.state) + "); the stored result is shown.");
      }
    });
  }

  function progress(s) {
    var st = stored(s.layout);
    var stats = document.getElementById("attackStats");
    var p = st && st.params ? "seed " + st.seed + ", " + st.params.n_conv + " conversations over " +
      st.params.duration_s + " simulated seconds" : "the M14 seed traffic";
    stats.innerHTML = "<div class='bigstat'><div class='k'>Running · " + esc(label(s.layout)) + "</div>" +
      "<div class='v small'>" + esc(String(s.elapsed_s || 0)) + " s</div>" +
      "<div class='k'>Replaying " + esc(p) + " through the service into a new store, then attacking its dump. " +
      "The counter above is the time so far.</div></div>";
  }

  /* ── stored (no live endpoint) ──────────────────────────────────────────── */

  function showStored(layout, why) {
    var st = stored(layout);
    var viz = document.getElementById("attackViz");
    var stats = document.getElementById("attackStats");
    if (!st || st.value === null) {
      stats.innerHTML = "<div class='bigstat'><div class='k'>No result</div><div class='v'>NOT MEASURED</div>" +
        "<div class='k'>M14 · python bench/run_security_eval.py --stage attack</div></div>";
      viz.innerHTML = "";
      note(why);
      done();
      return;
    }
    /* An illustration, not a sample: the stored rate applied to 24 cells (the count is exact, the positions
       are a fixed shuffle), so it cannot contradict the stored figure. Said on screen. */
    var nHit = Math.round(N * st.value), hits = [];
    for (var i = 0; i < N; i++) hits.push(i < nHit);
    var s = 7;
    for (var a = N - 1; a > 0; a--) {
      s = (s * 1103515245 + 12345) % 2147483648;
      var b = Math.floor(s / 2147483648 * (a + 1)), t = hits[a];
      hits[a] = hits[b]; hits[b] = t;
    }
    viz.innerHTML = "";
    var reveal = turnsPanel(viz, hits.map(function (h) { return { hit: h, same_round: false }; }), N);
    viz.querySelector(".seqlabel").innerHTML = "<b>Illustration.</b> The stored rate applied to 24 turns; these " +
      "cells are not individual results of the run.";
    var cap = el("p", "note");
    viz.appendChild(cap);
    animate({ n: N, fns: [reveal] }, function () {
      cap.innerHTML = "<b>" + nHit + " of " + N + "</b>: the stored " + esc(st.metric_id) + " of " + pct(st.value) +
        " applied to 24 turns.";
      done();
    });
    statsPanel(st.value, st, null);
    note(why);
  }

  /* ── wiring ─────────────────────────────────────────────────────────────── */

  function note(text) { var n = document.getElementById("attackNote"); if (n) n.textContent = text || ""; }

  function done() {
    var btn = document.getElementById("runAttack");
    btn.disabled = false; btn.textContent = "Run attack";
  }

  function run() {
    var layout = document.getElementById("expW").value;
    var btn = document.getElementById("runAttack");
    var token = ++runToken;
    btn.disabled = true; btn.textContent = "Running…";
    if (!(VC.state.live && VC.state.dev)) {
      showStored(layout, VC.state.live ? "The live attack needs `vcloak serve --dev`; the stored result is shown."
                                       : "Demo mode: the stored result is shown.");
      return;
    }
    VC.api.attackStart(layout).then(function (ans) {
      if (token !== runToken) return;
      if (ans && (ans.status === 202 || ans.status === 409)) {
        if (ans.status === 409 && ans.body && ans.body.layout !== layout) {
          note("Another run (" + label(ans.body.layout) + ") is in progress; its result is shown when it ends.");
          layout = ans.body.layout;
        }
        progress(ans.body || { layout: layout });
        poll(token, layout);
      } else {
        showStored(layout, "The live attack is not available (" + (ans ? ans.status : "no answer") +
                   "); the stored result is shown.");
      }
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
    var head = el("div", "panel-head"); head.appendChild(el("h2", null, "Every layout, side by side (stored)"));
    panel.appendChild(head);
    var wrap = el("div", null); wrap.style.padding = "14px 16px";
    wrap.appendChild(VC.charts.card(ch));
    panel.appendChild(wrap);
  }

  function idle() {
    var viz = document.getElementById("attackViz");
    var stats = document.getElementById("attackStats");
    if (!viz || !stats) return;
    viz.innerHTML = "<div class='seqlabel'>Pick a store layout and press <b>Run attack</b>. With <code>serve --dev</code> " +
      "the attack runs live on a new store; otherwise the stored result is shown.</div>";
    var row = el("div", "seqrow");
    for (var i = 0; i < N; i++) row.appendChild(el("div", "seqcell", String(i + 1)));
    viz.appendChild(row);
    stats.innerHTML = "<div class='bigstat'><div class='k'>Turn-order accuracy</div>" +
      "<div class='v' style='color:var(--muted)'>—</div>" +
      "<div class='k'>not run yet · 50% would be a coin flip</div></div>";
  }

  var shown = false;

  function init() {
    var btn = document.getElementById("runAttack");
    if (btn) btn.addEventListener("click", function () { shown = true; run(); });
    idle();
    ablation();
  }

  function refresh() {
    ablation();
    if (shown) return;
    shown = true;
    /* first visit: the stored result straight away; a live run (a full replay) starts only from the button */
    setTimeout(function () {
      var btn = document.getElementById("runAttack");
      btn.disabled = true;
      showStored(document.getElementById("expW").value, VC.state.live && VC.state.dev ?
        "Stored result. Press Run attack to replay it live." : "");
    }, 250);
  }

  VC.experiments = { init: init, refresh: refresh };
})(window);
