/* dashboard.js — renders tiles and charts from the dashboard payload.
 * It computes nothing. Every value comes from the JSON (ADR-013). */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var esc = VC.esc, el = VC.el;
  var cache = null;

  function statusIcon(state) {
    if (state === "good") return "<svg viewBox='0 0 16 16' width='12' height='12' aria-hidden='true'><path d='M6.4 11.2L3.2 8l1.1-1.1 2.1 2.1 5.3-5.3L12.8 4z' fill='currentColor'/></svg>";
    if (state === "crit") return "<svg viewBox='0 0 16 16' width='12' height='12' aria-hidden='true'><path d='M8 1.6l6.4 11.2H1.6zM7.2 6v3.2h1.6V6zm0 4v1.6h1.6V10z' fill='currentColor'/></svg>";
    return "<svg viewBox='0 0 16 16' width='12' height='12' aria-hidden='true'><circle cx='8' cy='8' r='5' fill='none' stroke='currentColor' stroke-width='1.6'/></svg>";
  }

  function tile(t) {
    var d = el("div", "tile " + (t.state || ""));
    var chips = "";
    if (t.quick) chips += " <span class='chip chip-quick'>QUICK</span>";
    d.innerHTML =
      "<div class='label'>" + esc(t.label) + chips + "</div>";

    if (t.value === null || t.value === undefined) {
      d.classList.add("na");
      d.innerHTML += "<div class='value'>NOT MEASURED</div>" +
                     "<div class='sub'>" + esc(t.how || "") + "</div>";
    } else {
      var unit = t.unit ? "<small>" + esc(t.unit) + "</small>" : "";
      d.innerHTML += "<div class='value'>" + esc(t.value) + unit + "</div>";
      if (t.sub) {
        var color = t.state === "good" ? "var(--good)" : t.state === "crit" ? "var(--crit)" : "var(--muted)";
        d.innerHTML += "<div class='sub'><span class='statusline' style='color:" + color + "'>" +
                       statusIcon(t.state) + "</span> " + esc(t.sub) + "</div>";
      }
    }
    if (t.stat) d.innerHTML += "<div class='sub'>" + esc(t.stat) + "</div>";
    if (t.metric_id) {
      var src = [t.backend, t.runner].filter(Boolean).join(" · ");
      d.innerHTML += "<div class='prov'>" + esc(t.metric_id) +
                     (t.run ? "<br>" + esc(t.run) : "") +
                     (src ? "<br>backend " + esc(src) : "") + "</div>";
      d.title = [t.metric_id, t.run, src, t.stat].filter(Boolean).join("\n");
    }
    return d;
  }

  function provbar(data) {
    var p = data.provenance || {};
    var bar = document.getElementById("provbar");
    if (!bar) return;
    var seed = data.source === "seed-oracle";
    bar.innerHTML =
      (seed ? "<span class='chip chip-demo'>SEED DATA</span>" : "<span class='chip chip-live'>GENERATED</span>") +
      "<span>compute: <b>" + esc(p.backend || "—") + "</b></span>" +
      "<span>runner: <b>" + esc(p.runner || "—") + "</b></span>" +
      "<span>generated: <b>" + esc((data.generated_at || "—").slice(0, 10)) + "</b></span>" +
      "<span>commit: <b>" + esc((data.git_sha || "—").slice(0, 7)) + "</b></span>" +
      (p.note ? "<span class='muted' style='flex-basis:100%'>" + esc(p.note) + "</span>" : "");
  }

  function render(data) {
    cache = data;
    provbar(data);

    var tiles = document.getElementById("tiles");
    tiles.innerHTML = "";
    var framing = {};
    (data.framing || []).forEach(function (f) { framing[f.id] = f; });
    var groups = (data.groups || []).length ? data.groups : [{ id: null, title: "" }];
    groups.forEach(function (g) {
      var sec = el("section", "tilegroup");
      if (g.title) sec.innerHTML = "<h2>" + esc(g.title) + "</h2>";
      var f = g.framing && framing[g.framing];
      if (f) {
        var box = el("div", "framing");
        box.innerHTML = "<h3>" + esc(f.title) + "</h3><ul>" +
          f.points.map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("") + "</ul>";
        sec.appendChild(box);
      }
      if (g.note) { var n = el("p", "groupnote"); n.textContent = g.note; sec.appendChild(n); }
      var grid = el("div", "tiles");
      (data.tiles || []).forEach(function (t) {
        if (g.id === null || t.group === g.id) grid.appendChild(tile(t));
      });
      sec.appendChild(grid);
      if (g.id === "gpu" && (data.excluded || []).length) {
        var ex = el("div", "excluded");
        ex.innerHTML = "<b>Not shown:</b> " + data.excluded.map(function (x) {
          return esc(x.users) + " users — " + esc(x.reason);
        }).join("; ");
        sec.appendChild(ex);
      }
      tiles.appendChild(sec);
    });

    var charts = document.getElementById("charts");
    charts.innerHTML = "";
    (data.charts || []).forEach(function (c) {
      try { charts.appendChild(VC.charts.card(c)); }
      catch (e) {
        var f = el("div", "chartcard");
        f.innerHTML = "<header><h3>" + esc(c.title || c.id) + "</h3></header>" +
                      "<p class='note'>This chart could not be drawn: " + esc(e.message) + "</p>";
        charts.appendChild(f);
      }
    });

    var mp = document.getElementById("missingPanel"), ml = document.getElementById("missingList");
    if ((data.missing || []).length) {
      mp.hidden = false; ml.innerHTML = "";
      data.missing.forEach(function (m) {
        var li = document.createElement("li");
        li.innerHTML = "<code>" + esc(m.metric_id) + "</code> — " + esc(m.how || "");
        ml.appendChild(li);
      });
    } else { mp.hidden = true; }

    var fp = document.getElementById("footProv");
    if (fp) fp.textContent = (data.provenance && data.provenance.session_id)
      ? "dashboard data: " + data.provenance.session_id : "";
  }

  function init() {
    VC.api.dashboard().then(render).catch(function (e) {
      document.getElementById("tiles").innerHTML =
        "<div class='tile na'><div class='value'>No data</div><div class='sub'>" + esc(e.message) + "</div></div>";
    });
    document.addEventListener("vc:theme", function () { if (cache) render(cache); });
  }

  VC.dashboard = { init: init, data: function () { return cache; } };
})(window);
