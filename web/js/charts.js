/* charts.js — hand-written SVG charts. No dependencies, no CDN.
 *
 * Rules enforced here (ai/FRONTEND.md §5):
 *   · colours come from CSS custom properties, never literals;
 *   · one y-axis per chart, always;
 *   · >=2 series => a legend is always drawn;
 *   · every chart gets a hover tooltip and a Table toggle;
 *   · grid and axes stay recessive; only endpoints and extremes get value labels.
 *
 * Public API:  VC.charts.card(spec) -> HTMLElement
 */
(function (global) {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";

  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function seriesVar(slot) { return "var(--s" + (((slot || 1) - 1) % 4 + 1) + ")"; }
  function fmt(v, unit) {
    if (v === null || v === undefined || (typeof v === "number" && !isFinite(v))) return "—";
    var s = typeof v === "number" ? (Math.abs(v) >= 100 ? v.toFixed(0)
            : Math.abs(v) >= 1 ? v.toFixed(1)
            : Math.abs(v) >= 0.01 ? v.toFixed(3) : v.toExponential(1)) : String(v);
    return s + (unit || "");
  }

  function tickFmt(v, unit, step) {
    if (v === 0) return "0" + (unit || "");
    var dec = 0;
    if (step !== undefined && step < 1) dec = Math.min(4, Math.max(0, Math.ceil(-Math.log10(step))));
    else if (Math.abs(v) < 1) dec = 2;
    var s = Math.abs(v) >= 1000 ? v.toLocaleString() : v.toFixed(dec);
    return s + (unit || "");
  }

  /* ── shared tooltip ───────────────────────────────── */
  var tip = null;
  function tipEl() { return tip || (tip = document.getElementById("tooltip")); }
  function showTip(evt, html) {
    var t = tipEl(); if (!t) return;
    t.innerHTML = html;
    t.style.opacity = "1";
    var pad = 14, w = t.offsetWidth, hgt = t.offsetHeight;
    var x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
    if (y + hgt > innerHeight - 8) y = evt.clientY - hgt - pad;
    t.style.left = x + "px"; t.style.top = y + "px";
  }
  function hideTip() { var t = tipEl(); if (t) t.style.opacity = "0"; }

  function hoverable(node, html) {
    node.addEventListener("mousemove", function (e) { showTip(e, html); });
    node.addEventListener("mouseleave", hideTip);
    node.addEventListener("focus", function (e) {
      var r = node.getBoundingClientRect();
      showTip({ clientX: r.left + r.width / 2, clientY: r.top }, html);
    });
    node.addEventListener("blur", hideTip);
  }

  /* ── axes helpers ─────────────────────────────────── */
  function niceTicks(min, max, count) {
    var span = max - min;
    if (span <= 0) return [min];
    var raw = span / (count || 5);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var norm = raw / mag;
    var step = (norm >= 7.5 ? 10 : norm >= 3.5 ? 5 : norm >= 1.5 ? 2 : 1) * mag;
    var out = [], v = Math.ceil(min / step) * step;
    for (; v <= max + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  function yAxis(svg, box, scale, ticks, unit) {
    var step = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : undefined;
    ticks.forEach(function (t) {
      var y = scale(t);
      el("line", { class: "gridline", x1: box.l, x2: box.l + box.w, y1: y, y2: y }, svg);
      var tx = el("text", { class: "tick", x: box.l - 8, y: y + 3.5, "text-anchor": "end" }, svg);
      tx.textContent = tickFmt(t, unit, step);
    });
    el("line", { class: "axisline", x1: box.l, x2: box.l, y1: box.t, y2: box.t + box.h }, svg);
  }

  /* ── grouped / single bar chart ───────────────────── */
  function groupedBar(spec, width) {
    var W = width, H = 270, box = { l: 52, t: 14, w: W - 68, h: H - 58 };
    var svg = el("svg", { class: "chart", viewBox: "0 0 " + W + " " + H, role: "img",
                          "aria-label": spec.title });
    var vals = [];
    spec.series.forEach(function (s) { s.values.forEach(function (v) { if (v !== null) vals.push(v); }); });
    var yMin = spec.yMin !== undefined ? spec.yMin : Math.min(0, Math.min.apply(null, vals));
    var yMax = spec.yMax !== undefined ? spec.yMax : Math.max.apply(null, vals) * 1.08;
    var y = function (v) { return box.t + box.h - (v - yMin) / (yMax - yMin) * box.h; };

    yAxis(svg, box, y, niceTicks(yMin, yMax, 5), spec.unit);

    var n = spec.categories.length, ns = spec.series.length;
    var slotW = box.w / n, barGap = 2, pad = slotW * 0.18;
    var bw = (slotW - pad * 2 - barGap * (ns - 1)) / ns;

    spec.categories.forEach(function (cat, ci) {
      spec.series.forEach(function (s, si) {
        var v = s.values[ci];
        if (v === null || v === undefined) return;
        var x = box.l + ci * slotW + pad + si * (bw + barGap);
        var top = y(v), hgt = Math.max(1, y(yMin) - top);
        var g = el("g", { tabindex: "0", role: "listitem" }, svg);
        el("rect", { x: x, y: top, width: bw, height: hgt, rx: 4, ry: 4,
                     fill: seriesVar(s.slot) }, g);
        // square off the baseline end so bars sit on the axis
        el("rect", { x: x, y: top + hgt - 5, width: bw, height: 5, fill: seriesVar(s.slot) }, g);
        hoverable(g, "<div class='tt-row'><i style='background:" + seriesVar(s.slot) + "'></i><b>" +
                     fmt(v, spec.unit) + "</b></div><div>" + cat + " · " + s.name + "</div>");
        if (si === 0) {   // label one series only; a second row of labels collides
          var lt = el("text", { class: "dlabel", x: x + bw / 2, y: top - 6, "text-anchor": "middle" }, svg);
          lt.textContent = fmt(v, spec.unit);
        }
      });
      var ct = el("text", { class: "tick", x: box.l + ci * slotW + slotW / 2,
                            y: box.t + box.h + 16, "text-anchor": "middle" }, svg);
      ct.textContent = cat;
    });

    if (spec.refLine) {
      var ry = y(spec.refLine.value);
      el("line", { class: "refline", x1: box.l, x2: box.l + box.w, y1: ry, y2: ry }, svg);
      var rl = el("text", { class: "reflabel", x: box.l + 4, y: ry - 6, "text-anchor": "start",
                            fill: "var(--muted)" }, svg);
      rl.textContent = spec.refLine.label;
    }
    el("line", { class: "axisline", x1: box.l, x2: box.l + box.w,
                 y1: y(yMin), y2: y(yMin) }, svg);
    return svg;
  }

  /* ── histogram with a ±band ───────────────────────── */
  function histogram(spec, width) {
    var W = width, H = 250, box = { l: 48, t: 14, w: W - 64, h: H - 56 };
    var svg = el("svg", { class: "chart", viewBox: "0 0 " + W + " " + H, role: "img",
                          "aria-label": spec.title });
    var maxC = Math.max.apply(null, spec.counts);
    var xMin = spec.binCenters[0] - 0.2, xMax = spec.binCenters[spec.binCenters.length - 1] + 0.2;
    var x = function (v) { return box.l + (v - xMin) / (xMax - xMin) * box.w; };
    var y = function (v) { return box.t + box.h - v / (maxC * 1.08) * box.h; };

    yAxis(svg, box, y, niceTicks(0, maxC * 1.08, 4), "");

    var bw = Math.max(2, box.w / spec.binCenters.length - 2);
    spec.binCenters.forEach(function (c, i) {
      var v = spec.counts[i]; if (!v) return;
      var g = el("g", { tabindex: "0" }, svg);
      el("rect", { x: x(c) - bw / 2, y: y(v), width: bw, height: y(0) - y(v), rx: 3,
                   fill: "var(--s1)" }, g);
      hoverable(g, "<b>" + v + "</b> epochs<div>τ/σ ≈ " + c.toFixed(2) + "</div>");
    });

    [-spec.band, spec.band].forEach(function (b) {
      el("line", { class: "refline", x1: x(b), x2: x(b), y1: box.t, y2: box.t + box.h,
                   stroke: "var(--crit)" }, svg);
    });
    var bl = el("text", { class: "reflabel", x: x(spec.band) + 5, y: box.t + 10, fill: "var(--crit)" }, svg);
    bl.textContent = "±3σ";

    niceTicks(xMin, xMax, 5).forEach(function (t) {
      var tx = el("text", { class: "tick", x: x(t), y: box.t + box.h + 16, "text-anchor": "middle" }, svg);
      tx.textContent = t;
    });
    el("line", { class: "axisline", x1: box.l, x2: box.l + box.w, y1: y(0), y2: y(0) }, svg);
    var xl = el("text", { class: "axis-label", x: box.l + box.w / 2, y: H - 4, "text-anchor": "middle" }, svg);
    xl.textContent = spec.xLabel || "";
    return svg;
  }

  /* ── log–log line chart ───────────────────────────── */
  function lineLog(spec, width) {
    var W = width, H = 270, box = { l: 56, t: 14, w: W - 72, h: H - 58 };
    var svg = el("svg", { class: "chart", viewBox: "0 0 " + W + " " + H, role: "img",
                          "aria-label": spec.title });
    var xs = [], ys = [];
    spec.series.forEach(function (s) {
      s.points.forEach(function (p) { xs.push(p[0]); if (p[1] > 0) ys.push(p[1]); });
    });
    var lx = function (v) { return Math.log10(v); };
    var xMin = lx(Math.min.apply(null, xs)), xMax = lx(Math.max.apply(null, xs));
    var yMin = Math.floor(Math.log10(Math.min.apply(null, ys))), yMax = Math.ceil(Math.log10(Math.max.apply(null, ys)));
    var X = function (v) { return box.l + (lx(v) - xMin) / (xMax - xMin || 1) * box.w; };
    var Y = function (v) { return box.t + box.h - (Math.log10(v) - yMin) / (yMax - yMin || 1) * box.h; };

    for (var p = yMin; p <= yMax; p++) {
      var yy = Y(Math.pow(10, p));
      el("line", { class: "gridline", x1: box.l, x2: box.l + box.w, y1: yy, y2: yy }, svg);
      var t = el("text", { class: "tick", x: box.l - 8, y: yy + 3.5, "text-anchor": "end" }, svg);
      t.textContent = Math.pow(10, p) >= 1 ? String(Math.pow(10, p)) : Math.pow(10, p).toFixed(Math.abs(p));
    }
    el("line", { class: "axisline", x1: box.l, x2: box.l, y1: box.t, y2: box.t + box.h }, svg);

    spec.series.forEach(function (s) {
      var d = s.points.map(function (p, i) { return (i ? "L" : "M") + X(p[0]) + " " + Y(p[1]); }).join(" ");
      el("path", { d: d, fill: "none", stroke: seriesVar(s.slot), "stroke-width": 2,
                   "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      s.points.forEach(function (p) {
        var g = el("g", { tabindex: "0" }, svg);
        el("circle", { cx: X(p[0]), cy: Y(p[1]), r: 4.5, fill: seriesVar(s.slot),
                       stroke: "var(--surface)", "stroke-width": 2 }, g);
        hoverable(g, "<div class='tt-row'><i style='background:" + seriesVar(s.slot) + "'></i><b>" +
                     fmt(p[1], spec.unit) + "</b></div><div>" + s.name + " · n = " + p[0].toLocaleString() + "</div>");
      });
    });

    if (spec.crossover) {
      var cx = X(spec.crossover);
      el("line", { class: "refline", x1: cx, x2: cx, y1: box.t, y2: box.t + box.h }, svg);
      var cl = el("text", { class: "reflabel", x: cx + 5, y: box.t + 11, fill: "var(--muted)" }, svg);
      cl.textContent = "crossover";
    }

    xs.filter(function (v, i, a) { return a.indexOf(v) === i; }).forEach(function (v, i, arr) {
      if (arr.length > 7 && i % 2) return;
      var t = el("text", { class: "tick", x: X(v), y: box.t + box.h + 16, "text-anchor": "middle" }, svg);
      t.textContent = v >= 1024 ? "2^" + Math.round(Math.log2(v)) : String(v);
    });
    el("line", { class: "axisline", x1: box.l, x2: box.l + box.w,
                 y1: box.t + box.h, y2: box.t + box.h }, svg);
    return svg;
  }

  /* ── stacked bar ──────────────────────────────────── */
  function stackedBar(spec, width) {
    var W = width, H = 270, box = { l: 52, t: 14, w: W - 68, h: H - 58 };
    var svg = el("svg", { class: "chart", viewBox: "0 0 " + W + " " + H, role: "img",
                          "aria-label": spec.title });
    var totals = spec.categories.map(function (_, ci) {
      return spec.series.reduce(function (a, s) { return a + (s.values[ci] || 0); }, 0);
    });
    var yMax = Math.max(Math.max.apply(null, totals), spec.refLine ? spec.refLine.value : 0) * 1.12;
    var y = function (v) { return box.t + box.h - v / yMax * box.h; };
    yAxis(svg, box, y, niceTicks(0, yMax, 5), spec.unit);

    var slotW = box.w / spec.categories.length, bw = slotW * 0.56;
    spec.categories.forEach(function (cat, ci) {
      var acc = 0, x = box.l + ci * slotW + (slotW - bw) / 2;
      spec.series.forEach(function (s, si) {
        var v = s.values[ci] || 0; if (!v) return;
        var top = y(acc + v), bot = y(acc);
        var g = el("g", { tabindex: "0" }, svg);
        el("rect", { x: x, y: top, width: bw, height: Math.max(1, bot - top - 2),
                     rx: si === spec.series.length - 1 ? 4 : 0, fill: seriesVar(s.slot) }, g);
        hoverable(g, "<div class='tt-row'><i style='background:" + seriesVar(s.slot) + "'></i><b>" +
                     fmt(v, spec.unit) + "</b></div><div>" + cat + " · " + s.name + "</div>");
        acc += v;
      });
      var lt = el("text", { class: "dlabel", x: x + bw / 2, y: y(acc) - 6, "text-anchor": "middle" }, svg);
      lt.textContent = fmt(totals[ci], spec.unit);
      var ct = el("text", { class: "tick", x: box.l + ci * slotW + slotW / 2,
                            y: box.t + box.h + 16, "text-anchor": "middle" }, svg);
      ct.textContent = cat;
    });
    if (spec.refLine) {
      var ry = y(spec.refLine.value);
      el("line", { class: "refline", x1: box.l, x2: box.l + box.w, y1: ry, y2: ry, stroke: "var(--crit)" }, svg);
      var rl = el("text", { class: "reflabel", x: box.l + box.w, y: ry - 5, "text-anchor": "end", fill: "var(--crit)" }, svg);
      rl.textContent = spec.refLine.label;
    }
    el("line", { class: "axisline", x1: box.l, x2: box.l + box.w, y1: y(0), y2: y(0) }, svg);
    return svg;
  }

  /* ── pass/fail matrix ─────────────────────────────── */
  function matrix(spec) {
    var wrap = h("div", "tablewrap");
    var t = h("table", "rows");
    t.innerHTML = "<thead><tr><th>Scenario</th><th>Expected</th><th>Observed</th><th>Failed check</th></tr></thead>";
    var tb = document.createElement("tbody");
    spec.rows.forEach(function (r) {
      var tr = document.createElement("tr");
      var okMark = r.ok
        ? "<span class='statusline' style='color:var(--good)'>&#10003; " + r.observed + "</span>"
        : "<span class='statusline' style='color:var(--crit)'>&#10007; " + r.observed + "</span>";
      tr.innerHTML = "<td style='white-space:normal;font-family:var(--sans)'>" + r.name + "</td>" +
                     "<td>" + r.expected + "</td><td>" + okMark + "</td><td>" + (r.why || "—") + "</td>";
      tb.appendChild(tr);
    });
    t.appendChild(tb); wrap.appendChild(t);
    return wrap;
  }

  /* ── table view (every chart has one) ─────────────── */
  function tableFor(spec) {
    var wrap = h("div", "tablewrap"); wrap.hidden = true;
    var t = h("table", "rows"), head, body = document.createElement("tbody");
    if (spec.kind === "histogram") {
      t.innerHTML = "<thead><tr><th>τ/σ bin</th><th>epochs</th></tr></thead>";
      spec.binCenters.forEach(function (c, i) {
        var tr = document.createElement("tr");
        tr.innerHTML = "<td>" + c.toFixed(2) + "</td><td>" + spec.counts[i] + "</td>";
        body.appendChild(tr);
      });
    } else if (spec.kind === "lineLog") {
      t.innerHTML = "<thead><tr><th>n</th>" + spec.series.map(function (s) {
        return "<th>" + s.name + "</th>"; }).join("") + "</tr></thead>";
      var xs = {};
      spec.series.forEach(function (s) { s.points.forEach(function (p) { xs[p[0]] = 1; }); });
      Object.keys(xs).map(Number).sort(function (a, b) { return a - b; }).forEach(function (xv) {
        var tr = document.createElement("tr");
        tr.innerHTML = "<td>" + xv.toLocaleString() + "</td>" + spec.series.map(function (s) {
          var p = s.points.filter(function (q) { return q[0] === xv; })[0];
          return "<td>" + (p ? fmt(p[1], spec.unit) : "—") + "</td>";
        }).join("");
        body.appendChild(tr);
      });
    } else {
      t.innerHTML = "<thead><tr><th>Category</th>" + spec.series.map(function (s) {
        return "<th>" + s.name + "</th>"; }).join("") + "</tr></thead>";
      spec.categories.forEach(function (c, ci) {
        var tr = document.createElement("tr");
        tr.innerHTML = "<td style='white-space:normal;font-family:var(--sans)'>" + c + "</td>" +
          spec.series.map(function (s) { return "<td>" + fmt(s.values[ci], spec.unit) + "</td>"; }).join("");
        body.appendChild(tr);
      });
    }
    t.appendChild(body); wrap.appendChild(t);
    return wrap;
  }

  function legend(spec) {
    if (!spec.series || spec.series.length < 2) return null;
    var l = h("div", "legend");
    spec.series.forEach(function (s) {
      var sp = h("span", null);
      sp.innerHTML = "<i style='background:" + seriesVar(s.slot) + "'></i>" + s.name;
      l.appendChild(sp);
    });
    return l;
  }

  /* ── card wrapper ─────────────────────────────────── */
  function card(spec) {
    var c = h("div", "chartcard");
    var head = document.createElement("header");
    head.appendChild(h("h3", null, spec.title));
    c.appendChild(head);

    if (spec.pending) {
      c.appendChild(h("p", "note", spec.note || ""));
      var na = h("div", "tile na");
      na.innerHTML = "<div class='label'>Not measured yet</div><div class='value'>NOT MEASURED</div>" +
                     "<div class='sub'>" + (spec.how || "") + "</div>";
      c.appendChild(na);
      if (spec.metric_ids) c.appendChild(h("div", "prov", "awaiting: " + spec.metric_ids.join(", ")));
      return c;
    }

    var btn = h("button", "tablebtn", "Table");
    btn.setAttribute("aria-expanded", "false");
    head.appendChild(btn);

    if (spec.note) c.appendChild(h("p", "note", spec.note));
    var lg = legend(spec); if (lg) c.appendChild(lg);

    var holder = h("div", null);
    c.appendChild(holder);

    var width = 560;
    var svg = spec.kind === "histogram" ? histogram(spec, width)
            : spec.kind === "lineLog" ? lineLog(spec, width)
            : spec.kind === "stackedBar" ? stackedBar(spec, width)
            : spec.kind === "matrix" ? matrix(spec)
            : groupedBar(spec, width);
    holder.appendChild(svg);

    var tbl = spec.kind === "matrix" ? null : tableFor(spec);
    if (tbl) {
      c.appendChild(tbl);
      btn.addEventListener("click", function () {
        var open = tbl.hidden;
        tbl.hidden = !open; holder.hidden = open;
        btn.textContent = open ? "Chart" : "Table";
        btn.setAttribute("aria-expanded", String(open));
      });
    } else {
      btn.remove();
    }

    var prov = [];
    if (spec.metric_ids) prov.push(spec.metric_ids.slice(0, 4).join(", ") + (spec.metric_ids.length > 4 ? " …" : ""));
    if (spec.runs) prov.push(spec.runs.join(", "));
    if (prov.length) c.appendChild(h("div", "prov", "source: " + prov.join("  ·  ")));
    return c;
  }

  global.VC = global.VC || {};
  global.VC.charts = { card: card, fmt: fmt, seriesVar: seriesVar, h: h, el: el,
                       showTip: showTip, hideTip: hideTip, hoverable: hoverable };
})(window);
