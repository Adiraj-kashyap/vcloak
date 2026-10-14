/* arch.js — the data-state flow, drawn as SVG, with a message animating through it (M18 S6).
 * Everything drawn here comes from the `architecture` block of dashboard.json (scripts/export_dashboard.py):
 * the states of ai/ARCHITECTURE.md section 2 with their parameters read from src/vcloak/config.py, and the
 * leakage table of ai/PROJECT_BRIEF.md sections 3 and 5 under the ADR-031 sentence. No value is typed here. */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var NS = "http://www.w3.org/2000/svg";

  var WHERE = { client: "on the client", net: "on the network", host: "in host memory",
                vram: "in GPU memory", db: "in PostgreSQL (durable)" };
  var FILL = { client: "var(--surface)", net: "var(--s1-wash)", host: "var(--surface)",
               vram: "var(--good-wash)", db: "var(--s1)" };
  var STROKE = { client: "var(--axis)", net: "var(--s1)", host: "var(--axis)",
                 vram: "var(--s3)", db: "var(--s1)" };
  var STATUS = { "concealed": ["no", "✓"], "partly visible": ["partial", "◐"], "visible": ["yes", "✕"] };

  var arch = null, playing = false, timer = null;

  function el(name, attrs, text) {
    var e = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    return e;
  }

  function reduced() {
    return global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  /* Write path in two rows, the read path in a third; the read starts from the stored rows (S9). */
  function layout(a) {
    var bw = 150, bh = 58, gx = 26, gy = 46, top = 30, cols = 6;
    var pos = {}, order = [];
    function place(list, row0, lane) {
      list.forEach(function (s, i) {
        var r = row0 + Math.floor(i / cols), c = i % cols;
        pos[s.id] = { s: s, x: c * (bw + gx) + gx / 2, y: top + r * (bh + gy), w: bw, h: bh, lane: lane };
        order.push(s.id);
      });
    }
    place(a.write, 0, "write");
    var wrows = Math.ceil(a.write.length / cols);
    place(a.read, wrows, "read");
    var rows = wrows + Math.ceil(a.read.length / cols);
    return { pos: pos, order: order, W: cols * (bw + gx), H: top + rows * (bh + gy) - gy + 14, top: top,
             wrows: wrows, bh: bh, gy: gy };
  }

  function edge(svg, p, q, dashed) {
    var d;
    if (Math.abs(p.y - q.y) < 1) {
      d = "M" + (p.x + p.w) + " " + (p.y + p.h / 2) + " L" + q.x + " " + (q.y + q.h / 2);
    } else {
      var midY = (p.y + p.h + q.y) / 2;
      d = "M" + (p.x + p.w / 2) + " " + (p.y + p.h) + " L" + (p.x + p.w / 2) + " " + midY +
          " L" + (q.x + q.w / 2) + " " + midY + " L" + (q.x + q.w / 2) + " " + q.y;
    }
    svg.appendChild(el("path", { d: d, "class": "flowedge" + (dashed ? " dashed" : "") }));
  }

  function draw() {
    var host = document.getElementById("flow");
    if (!host || !arch) return;
    host.innerHTML = "";
    var L = layout(arch);
    var svg = el("svg", { viewBox: "0 0 " + L.W + " " + L.H, "class": "chart", role: "img",
                          "aria-label": "Data-state flow: write path " + arch.write[0].id + " to " +
                          arch.write[arch.write.length - 1].id + ", read path " + arch.read[0].id + " to " +
                          arch.read[arch.read.length - 1].id + "; durable states drawn dark" });
    svg.style.minWidth = "760px";
    var defs = el("defs");
    defs.innerHTML = "<marker id='arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='6' markerHeight='6' " +
                     "orient='auto-start-reverse'><path d='M0 0 L10 5 L0 10 z' fill='var(--muted)'/></marker>";
    svg.appendChild(defs);

    svg.appendChild(el("text", { x: 13, y: 18, "class": "lane" }, "WRITE PATH"));
    svg.appendChild(el("text", { x: 13, y: L.top + L.wrows * (L.bh + L.gy) - 12, "class": "lane" }, "READ PATH"));

    var edges = el("g"), nodes = el("g");
    svg.appendChild(edges); svg.appendChild(nodes);
    var ids = L.order;
    ids.forEach(function (id, i) {
      var n = L.pos[id], s = n.s, dark = s.where === "db";
      var g = el("g", { "class": "flownode" + (s.durable ? " durable" : ""), tabindex: "0", "data-id": id });
      n.rect = el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, rx: 8, fill: FILL[s.where],
                            stroke: STROKE[s.where], "stroke-width": s.durable ? 2 : 1.2 });
      g.appendChild(n.rect);
      g.appendChild(el("text", { "class": "t", x: n.x + 10, y: n.y + 22, fill: dark ? "#fff" : "var(--ink)" }, id));
      g.appendChild(el("text", { x: n.x + 10, y: n.y + 41, fill: dark ? "#fff" : "var(--ink-2)" }, s.t));
      if (s.durable) g.appendChild(el("text", { x: n.x + n.w - 10, y: n.y + 22, "text-anchor": "end",
                                                 fill: "#fff", "font-size": "10" }, "on disk"));
      VC.charts.hoverable(g, "<b>" + VC.esc(id + " — " + s.t) + "</b><div>" + VC.esc(s.d) + "</div><div class='muted'>" +
                             VC.esc(WHERE[s.where]) + "</div>");
      g.addEventListener("focus", function () { caption(id); });
      nodes.appendChild(g);
      var prev = ids[i - 1];
      if (prev && L.pos[prev].lane === n.lane) edge(edges, L.pos[prev], n, false);
    });
    /* the read path starts from what is stored */
    var from = L.pos[arch.write.filter(function (s) { return s.durable; })[0].id], to = L.pos[arch.read[0].id];
    if (from && to) {
      edge(edges, from, to, true);
      edges.appendChild(el("text", { x: from.x + from.w / 2 + 6, y: to.y - L.gy / 2 - 5, "class": "lane" },
                           "a read fetches stored rows"));
    }
    var dot = el("circle", { r: 7, "class": "flowmsg", cx: -20, cy: -20 });
    svg.appendChild(dot);
    host.appendChild(svg);

    var btn = document.getElementById("flowPlay");
    if (btn) btn.onclick = function () { play(L, dot, btn); };
  }

  function caption(id) {
    var c = document.getElementById("flowCaption"), s = null;
    if (!c || !arch) return;
    arch.write.concat(arch.read).forEach(function (x) { if (x.id === id) s = x; });
    if (!s) return;
    c.innerHTML = "<b>" + VC.esc(s.id + " · " + s.t) + "</b> <span class='chip " + (s.durable ? "chip-dev" : "chip-live") +
                  "'>" + VC.esc(s.durable ? "durable" : WHERE[s.where]) + "</span><div>" + VC.esc(s.d) + "</div>";
  }

  function play(L, dot, btn) {
    if (playing) return;
    playing = true; btn.disabled = true; btn.textContent = "Playing…";
    var ids = L.order, i = 0, step = reduced() ? 900 : 700;
    function centre(n) { return [n.x + n.w / 2, n.y + n.h - 2]; }
    (function next() {
      ids.forEach(function (id) {
        var n = L.pos[id];
        n.rect.setAttribute("stroke-width", n.s.durable ? 2 : 1.2);
        n.rect.parentNode.classList.remove("on");
      });
      if (i >= ids.length) {
        playing = false; btn.disabled = false; btn.textContent = "Play again";
        dot.setAttribute("cx", -20); dot.setAttribute("cy", -20);
        return;
      }
      var n = L.pos[ids[i]], c = centre(n);
      n.rect.parentNode.classList.add("on");
      n.rect.setAttribute("stroke-width", 3);
      dot.setAttribute("cx", c[0]); dot.setAttribute("cy", c[1]);
      caption(ids[i]);
      i++;
      timer = setTimeout(next, step);
    })();
  }

  function evidenceCell(ev) {
    if (!ev.length) return "<span class='muted'>by construction; no measurement</span>";
    return ev.map(function (e) {
      if (e.value == null) {
        return "<div class='ev'><b>NOT MEASURED</b> · " + VC.esc(e.label) + " · " + VC.esc(e.metric_id) +
               (e.how ? "<div class='muted'>" + VC.esc(e.how) + "</div>" : "") + "</div>";
      }
      return "<div class='ev'>" + VC.esc(e.label) + ": <b>" + VC.esc(String(e.value)) + (e.unit ? " " + VC.esc(e.unit) : "") +
             "</b>" + (e.quick ? " <span class='chip chip-quick'>QUICK</span>" : "") +
             "<div class='prov'>" + VC.esc(e.metric_id) + " · " + VC.esc(e.run) + " · " + VC.esc(e.backend) + "/" +
             VC.esc(e.runner) + "</div></div>";
    }).join("");
  }

  function leakTable() {
    var t = document.getElementById("leakTable"), s = document.getElementById("leakSentence");
    if (!t) return;
    if (s) s.textContent = arch ? arch.leak_sentence : "";
    t.innerHTML = "<thead><tr><th>Observable</th><th>In a snapshot of the store</th><th>Why</th><th>Measured</th></tr></thead>";
    var tb = document.createElement("tbody");
    (arch ? arch.leak : []).forEach(function (r) {
      var st = STATUS[r.status] || ["partial", "?"];
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + VC.esc(r.observable) + "</td><td class='" + st[0] + "'>" + st[1] + " " + VC.esc(r.status) +
                     "</td><td>" + VC.esc(r.why) + "</td><td>" + evidenceCell(r.evidence || []) + "</td>";
      tb.appendChild(tr);
    });
    t.appendChild(tb);
  }

  /* The live line: the epoch the server's scheduler has open, the last one stored, the engine. Never a clock of
     our own: without a server it says there is none. */
  function live() {
    var box = document.getElementById("flowLive");
    if (!box) return;
    if (!VC.state.live) { box.textContent = "No live server: the drawing only. Start `vcloak serve --dev` to see the epoch clock here."; return; }
    VC.api.stats().then(function (s) {
      if (!s || s.unavailable || s.demo) { box.textContent = "The live server is not answering."; return; }
      var g = s.gpu;
      box.textContent = "Live: epoch " + s.epoch + " open (S4)" +
        (s.last_epoch != null ? ", last epoch written to the store " + s.last_epoch + " (S9)" : ", nothing stored yet") +
        (g ? "; engine " + g.backend + (g.runner ? " on " + g.runner : "") : "; no engine (baseline)") + ".";
    });
  }

  function init() {
    VC.api.dashboard().then(function (d) {
      arch = d && d.architecture ? d.architecture : null;
      var src = document.getElementById("flowSource");
      if (src) src.textContent = arch ? "Source: " + arch.source + "." :
        "The generated web/data/dashboard.json could not be loaded: nothing is drawn rather than a guess.";
      draw(); leakTable(); live();
      if (arch) caption(arch.write[0].id);
    });
    document.addEventListener("vc:theme", draw);
    setInterval(function () {
      var v = document.getElementById("view-arch");
      if (v && !v.hidden) live();
    }, 2000);
  }
  VC.arch = { init: init };
})(window);
