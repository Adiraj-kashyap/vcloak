/* arch.js — the data-state flow, drawn as SVG, with a message animating through it. */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var NS = "http://www.w3.org/2000/svg";

  var STATES = [
    { id: "S0",  t: "plaintext + seq",     where: "client",  d: "The message and its sequence number, before anything happens." },
    { id: "S1",  t: "padded block",        where: "client",  d: "Padded to a fixed size, so length reveals nothing." },
    { id: "S2",  t: "ciphertext",          where: "client",  d: "AES-256-GCM under a key only the two users hold." },
    { id: "S3",  t: "in transit",          where: "net",     d: "TLS 1.3 with a DPoP proof bound to the device key." },
    { id: "S4",  t: "queued in epoch",     where: "host",    d: "Waiting for the 200 ms epoch to close. Never extended." },
    { id: "S5",  t: "padded batch",        where: "host",    d: "Padded to a fixed slot count with dummies, so volume is hidden." },
    { id: "S6",  t: "tagged",              where: "vram",    d: "A 128-bit ChaCha20 tag per slot, keyed per epoch." },
    { id: "S7",  t: "permuted",            where: "vram",    d: "Bitonic sort by tag — the shuffle itself." },
    { id: "S8",  t: "compacted",           where: "vram",    d: "Dummies removed by an oblivious sort, order preserved." },
    { id: "S9",  t: "stored row",          where: "db",      d: "uuid, bucket, window, seq_enc, payload. Durable. Visible in a dump." },
    { id: "S10", t: "window re-shuffled",  where: "db",      d: "At window close, rewritten under a fresh permutation. Durable." },
    { id: "R1",  t: "candidates",          where: "vram",    d: "A fixed number of rows fetched for (bucket, window)." },
    { id: "R2",  t: "seq decrypted",       where: "vram",    d: "Only the sequence field is opened, and only inside GPU memory." },
    { id: "R3",  t: "order restored",      where: "vram",    d: "Bitonic sort on (miss, seq) puts the conversation back in order." },
    { id: "R4",  t: "ordered ciphertexts", where: "net",     d: "Sent back over TLS, still encrypted." },
    { id: "R5",  t: "plaintext in order",  where: "client",  d: "Decrypted on the recipient's device." }
  ];

  var FILL = { client: "var(--plane)", net: "var(--s1-wash)", host: "var(--plane)",
               vram: "var(--good-wash)", db: "var(--s1)" };
  var STROKE = { client: "var(--axis)", net: "var(--s1)", host: "var(--axis)",
                 vram: "var(--s3)", db: "var(--s1)" };

  function draw() {
    var host = document.getElementById("flow");
    if (!host) return;
    host.innerHTML = "";
    var cols = 6, bw = 150, bh = 56, gx = 24, gy = 34;
    var rows = Math.ceil(STATES.length / cols);
    var W = cols * (bw + gx), H = rows * (bh + gy) + 30;

    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("class", "chart");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Data-state flow from S0 to R5");
    svg.style.minWidth = "760px";

    var defs = document.createElementNS(NS, "defs");
    defs.innerHTML = "<marker id='arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='6' markerHeight='6' orient='auto-start-reverse'><path d='M0 0 L10 5 L0 10 z' fill='var(--axis)'/></marker>";
    svg.appendChild(defs);

    var nodes = [];
    STATES.forEach(function (s, i) {
      var r = Math.floor(i / cols), c = i % cols;
      var x = c * (bw + gx) + gx / 2, y = r * (bh + gy) + 14;
      var g = document.createElementNS(NS, "g");
      g.setAttribute("class", "flownode");
      g.setAttribute("tabindex", "0");
      g.setAttribute("data-id", s.id);

      var rect = document.createElementNS(NS, "rect");
      rect.setAttribute("x", x); rect.setAttribute("y", y);
      rect.setAttribute("width", bw); rect.setAttribute("height", bh);
      rect.setAttribute("rx", 8);
      rect.setAttribute("fill", FILL[s.where]);
      rect.setAttribute("stroke", STROKE[s.where]);
      rect.setAttribute("stroke-width", s.where === "db" ? 2 : 1.2);
      g.appendChild(rect);

      var t1 = document.createElementNS(NS, "text");
      t1.setAttribute("class", "t"); t1.setAttribute("x", x + 10); t1.setAttribute("y", y + 21);
      t1.setAttribute("fill", s.where === "db" ? "#fff" : "var(--ink)");
      t1.textContent = s.id;
      g.appendChild(t1);

      var t2 = document.createElementNS(NS, "text");
      t2.setAttribute("x", x + 10); t2.setAttribute("y", y + 39);
      t2.setAttribute("fill", s.where === "db" ? "#fff" : "var(--ink-2)");
      t2.textContent = s.t;
      g.appendChild(t2);

      if (s.where === "db") {
        var warn = document.createElementNS(NS, "text");
        warn.setAttribute("x", x + bw - 10); warn.setAttribute("y", y + 21);
        warn.setAttribute("text-anchor", "end");
        warn.setAttribute("fill", "#fff");
        warn.setAttribute("font-size", "10");
        warn.textContent = "on disk";
        g.appendChild(warn);
      }

      VC.charts.hoverable(g, "<b>" + s.id + " — " + s.t + "</b><div>" + s.d + "</div>");
      svg.appendChild(g);
      nodes.push({ g: g, rect: rect, x: x, y: y, w: bw, h: bh });

      if (i > 0) {
        var p = nodes[i - 1], path;
        var line = document.createElementNS(NS, "path");
        if (c === 0) {
          path = "M" + (p.x + p.w / 2) + " " + (p.y + p.h) +
                 " L" + (p.x + p.w / 2) + " " + (y - 10) +
                 " L" + (x + bw / 2) + " " + (y - 10) + " L" + (x + bw / 2) + " " + y;
        } else {
          path = "M" + (p.x + p.w) + " " + (p.y + p.h / 2) + " L" + x + " " + (y + bh / 2);
        }
        line.setAttribute("d", path);
        line.setAttribute("class", "flowedge");
        svg.insertBefore(line, svg.firstChild.nextSibling);
      }
    });

    host.appendChild(svg);

    var playing = false;
    var btn = document.getElementById("flowPlay");
    if (btn) btn.onclick = function () {
      if (playing) return;
      playing = true; btn.disabled = true; btn.textContent = "Playing…";
      var i = 0;
      (function step() {
        nodes.forEach(function (n) { n.g.classList.remove("on"); n.rect.setAttribute("stroke-width", 1.2); });
        if (i >= nodes.length) {
          playing = false; btn.disabled = false; btn.textContent = "Play again";
          return;
        }
        nodes[i].g.classList.add("on");
        nodes[i].rect.setAttribute("stroke-width", 3);
        i++;
        setTimeout(step, 420);
      })();
    };
  }

  function leakTable() {
    var t = document.getElementById("leakTable");
    var rows = (global.VCLOAK_DEMO && global.VCLOAK_DEMO.leak) || [];
    if (!t) return;
    t.innerHTML = "<thead><tr><th>Observable</th><th>Leaked?</th><th>Why</th></tr></thead>";
    var tb = document.createElement("tbody");
    rows.forEach(function (r) {
      var cls = r[1] === "yes" ? "yes" : r[1] === "partial" ? "partial" : "no";
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + VC.esc(r[0]) + "</td><td class='" + cls + "'>" + VC.esc(r[1]) +
                     "</td><td>" + VC.esc(r[2]) + "</td>";
      tb.appendChild(tr);
    });
    t.appendChild(tb);
  }

  function init() { draw(); leakTable(); document.addEventListener("vc:theme", draw); }
  VC.arch = { init: init };
})(window);
