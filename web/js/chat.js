/* chat.js — the two-user chat and the "what the server stores" panel.
 *
 * Live (served by the backend with --sessions): each pane is a real client of its own (client.js) —
 * its own account, its own non-extractable device key and prekey, its own session. A pane shows what
 * its client read back from the server and verified, in the server's order; nothing is copied from
 * one pane to the other inside the page. Both panes read once a second whether or not anything was
 * sent: a fixed schedule, so the reads say nothing about the typing.
 *
 * Demo (file://, or no backend): the conversation is local and the stored rows come from demo-data.js.
 * The DOM contract (ids, classes) is the same in both.
 */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var esc = VC.esc;
  var USERS = ["A", "B"];
  var READ_EVERY_MS = 1000;

  /* ── demo ── */
  var convo = [];        // {user, text, seq, ts}
  var seq = { A: 0, B: 0 };

  function demoBubble(paneUser, msg) {
    var b = document.createElement("div");
    b.className = "bub" + (msg.user === paneUser ? " mine" : "");
    b.innerHTML = esc(msg.text) +
      "<span class='meta'>seq " + msg.seq + " · " + msg.ts + "</span>";
    return b;
  }

  function renderDemo() {
    USERS.forEach(function (u) {
      var box = document.getElementById("msgs" + u);
      if (!box) return;
      box.innerHTML = "";
      convo.forEach(function (m) { box.appendChild(demoBubble(u, m)); });
      box.scrollTop = box.scrollHeight;
    });
  }

  function sendDemo(user, text) {
    var now = new Date();
    convo.push({ user: user, text: text, seq: seq[user]++, ts: now.toTimeString().slice(0, 8) });
    renderDemo();
    refreshDump();
  }

  /* ── live ── */
  var panes = {};        // A, B -> {client, messages, pending, halted}
  var reading = null;
  var ready = null;

  function alertPane(u, text, info) {
    var n = document.getElementById("alert" + u);
    if (!n) return;
    n.hidden = !text;
    n.textContent = text || "";
    n.className = "pane-alert" + (info ? " info" : "");
    if (panes[u]) panes[u].alert = text || "";
  }

  function enable(u, on) {
    var form = document.getElementById("form" + u);
    if (!form) return;
    Array.prototype.forEach.call(form.elements, function (el) { el.disabled = !on; });
  }

  function renderLive(u) {
    var p = panes[u], box = document.getElementById("msgs" + u);
    if (!p || !box) return;
    // verified messages are appended once; what may still change is drawn again each time
    Array.prototype.forEach.call(box.querySelectorAll(".transient"), function (n) { box.removeChild(n); });
    for (; p.shown < p.messages.length; p.shown++) {
      var m = p.messages[p.shown];
      var b = VC.el("div", "bub" + (m.mine ? " mine" : ""), m.text);
      b.appendChild(VC.el("span", "meta", "#" + m.number + " · window " + m.win + " · verified"));
      box.appendChild(b);
    }
    p.pending.forEach(function (q) {
      var b = VC.el("div", "bub mine pending transient", q.text);
      b.appendChild(VC.el("span", "meta", q.failed ? "not confirmed as stored" : "sending…"));
      box.appendChild(b);
    });
    if (p.halted) box.appendChild(VC.el("div", "bub gap transient", "Reading stopped: " + p.halted));
    box.scrollTop = box.scrollHeight;
  }

  function account(u) {
    var cr = VC.crypto, name = "account:" + u;
    return cr.stored(name).then(function (a) {
      if (a && a.username && a.password) return a;
      // A demo account of this browser. The password only satisfies the login route and sits beside the
      // key handles; what binds the session is the device key, which script cannot read.
      return cr.store(name, { username: (u === "A" ? "alice_" : "bob_") + cr.hex(cr.random(4)),
                              password: cr.b64u(cr.random(18)) });
    });
  }

  function signIn(u) {
    var client = new VC.Client(u);
    panes[u] = { client: client, messages: [], pending: [], shown: 0, halted: "", alert: "" };
    function attempt(again) {
      return account(u).then(function (a) {
        return client.signIn(a.username, a.password).catch(function (e) {
          if (e.kind !== "login" || !again) throw e;
          return VC.crypto.forget("account:" + u).then(function () { return attempt(false); });
        });
      });
    }
    return client.init().then(function () { return attempt(true); });
  }

  function describeKeys() {
    USERS.forEach(function (u) {
      var k = document.getElementById("key" + u), c = panes[u].client;
      if (k) {
        k.textContent = c.username + " · ES256 jkt " + c.device.jkt.slice(0, 6) + "…";
        k.title = "Device key thumbprint (RFC 7638): " + c.device.jkt + ". The private key is a non-extractable WebCrypto handle.";
      }
    });
    var fp = document.getElementById("fingerprint");
    if (!fp) return;
    var a = panes.A.client.conv.fingerprint, b = panes.B.client.conv.fingerprint;
    fp.hidden = false;
    fp.textContent = "";
    fp.appendChild(document.createTextNode("Key fingerprint — A: "));
    fp.appendChild(VC.el("b", "", a));
    fp.appendChild(document.createTextNode(" · B: "));
    fp.appendChild(VC.el("b", "", b));
    fp.appendChild(document.createTextNode(a === b
      ? " · ✓ equal: both ends hold the same prekeys"
      : " · ✗ different: the server handed out a prekey that is not the other pane's"));
  }

  function readPane(u) {
    var p = panes[u];
    if (p.halted || !p.client.conv) return Promise.resolve();
    return p.client.sync().then(function (fresh) {
      var own = p.client.conv.sessionHex;
      fresh.forEach(function (m) {
        p.messages.push(m);
        if (m.mine && m.session === own) {
          p.pending = p.pending.filter(function (q) { return q.failed || q.number === undefined || q.number > m.number; });
        }
      });
      if (p.alert && !p.pending.some(function (q) { return q.failed; })) alertPane(u, "");
      renderLive(u);
    }, function (e) {
      if (e.kind === "sequence" || e.kind === "tamper" || e.kind === "protocol") {
        // the order or the content is not what was sent: say so and show nothing after it
        p.halted = e.message;
        alertPane(u, (e.kind === "sequence" ? "Order check failed" : "Content check failed") + " — " + e.message);
      } else {
        alertPane(u, "Cannot read from the server (" + (e.message || "no answer") + "). Trying again.", true);
      }
      renderLive(u);
    });
  }

  function readAll() {
    if (reading) return reading;
    reading = Promise.all(USERS.map(readPane)).then(function () { reading = null; }, function () { reading = null; });
    return reading;
  }

  function sendLive(u, text) {
    var p = panes[u];
    if (!p || !p.client.conv) return Promise.reject(new Error("the pane is not connected"));
    var entry = { text: text };
    p.pending.push(entry);
    renderLive(u);
    return p.client.send(text).then(function (number) {
      entry.number = number;
      return number;
    }, function (e) {
      entry.failed = true;
      alertPane(u, "Not sent — " + e.message);
      renderLive(u);
      throw e;
    });
  }

  function startLive() {
    USERS.forEach(function (u) { enable(u, false); });
    if (!VC.state.sessions) {
      USERS.forEach(function (u) {
        alertPane(u, "The server runs without sessions. Start it with: vcloak serve --dev --sessions", true);
      });
      return Promise.resolve(false);
    }
    return VC.crypto.unsupported().then(function (reason) {
      if (reason) throw new Error(reason);
      return Promise.all(USERS.map(signIn));
    }).then(function () {
      return Promise.all([
        panes.A.client.start(panes.B.client.username, VC.state.payloadLen),
        panes.B.client.start(panes.A.client.username, VC.state.payloadLen)
      ]);
    }).then(function () {
      describeKeys();
      USERS.forEach(function (u) { enable(u, true); document.getElementById("msgs" + u).innerHTML = ""; renderLive(u); });
      // the panel follows the panes on the same fixed schedule
      setInterval(function () { readAll().then(refreshDump); }, READ_EVERY_MS);
      return readAll().then(refreshDump).then(function () { return true; });
    }).catch(function (e) {
      USERS.forEach(function (u) { alertPane(u, "Not connected — " + (e.message || e)); });
      return false;
    });
  }

  /* ── the server view ── */
  var DUMP_ROWS = 200;
  var DUMP_SPAN_S = 240;   // how far back the panel looks, in seconds of windows
  var view = { rows: [], windows: [], sig: null };

  function shortId(s) { return String(s).length > 13 ? String(s).slice(0, 8) + "…" : String(s); }
  function unpad(b64) { return String(b64).replace(/=+$/, ""); }

  /* The first and last bytes of a stored field, in hex. */
  function shortHex(b64) {
    if (b64 === null || b64 === undefined) return "—";
    var raw;
    try { raw = atob(b64); } catch (e) { return "?"; }
    function hex(from, to) {
      var out = "";
      for (var i = from; i < to; i++) out += ("0" + raw.charCodeAt(i).toString(16)).slice(-2);
      return out;
    }
    return raw.length <= 6 ? hex(0, raw.length) : hex(0, 4) + "…" + hex(raw.length - 2, raw.length) + " (" + raw.length + " B)";
  }

  /* Which stored payload is which message: from what a pane read back and verified with its own key,
   * never from the server. n is the position in that pane's conversation since the page opened. */
  function truth() {
    var best = null;
    USERS.forEach(function (u) {
      var p = panes[u];
      if (p && (!best || p.messages.length > best.p.messages.length)) best = { u: u, p: p };
    });
    var map = {};
    if (!best) return map;
    best.p.messages.forEach(function (m, i) {
      if (!m.stored) return;
      var other = best.u === "A" ? "B" : "A";
      map[unpad(m.stored)] = { n: i + 1, who: m.mine ? best.u : other, number: m.number };
    });
    return map;
  }

  /* The rows of the panel, the same shape live and demo. */
  function dumpRows(d) {
    if (!VC.state.live) {
      return (d.rows || []).map(function (r, i) {
        return { pos: i, row_id: r.row_id, bucket: r.bucket, win: r.win, state: "", seq_enc: r.seq_enc,
                 payload: r.payload, sent: r.sent !== undefined ? { n: r.sent } : null };
      });
    }
    var states = {}, known = truth();
    (d.windows || []).forEach(function (w) { states[w.win] = w.state; });
    return (d.rows || []).map(function (r) {
      return { pos: r.pos, row_id: r.row_id, bucket: r.bucket === null ? "—" : r.bucket, win: r.win,
               state: states[r.win] || "", seq_enc: shortHex(r.seq_enc_b64), payload: shortHex(r.payload_b64),
               payload_b64: r.payload_b64, sent: known[unpad(r.payload_b64)] || null };
    });
  }

  var STATE_LABEL = { open: "open", closing: "closing", reshuffled: "re-shuffled", epoch: "epoch round", arrival: "" };

  function serverNote(d, rows) {
    var note = document.getElementById("serverNote");
    if (!note) return;
    note.textContent = "";
    function say(strong, text) {
      if (strong) note.appendChild(VC.el("b", "", strong));
      note.appendChild(document.createTextNode(text));
    }
    if (d.unavailable) {
      say("", VC.state.dev
        ? "The server gave no answer to GET /v1/dump."
        : "This server does not hand out its stored rows: GET /v1/dump exists with --dev only.");
      return;
    }
    var mode = d.mode || VC.state.mode;
    if (mode === "baseline") {
      say("Unprotected baseline.", " Rows carry a sequential id and sit in arrival order, so the row order is the conversation order — no key needed to read it.");
    } else if (!VC.state.live) {
      say("V‑cloak.", " Random UUIDs, a shared bucket, a coarse window id, and no timestamp. The physical order of these rows is the engine's permutation, not the order anyone typed.");
    } else if (d.visible_round === "epoch") {
      say("V‑cloak, epoch rounds.", " Random row ids, a bucket, a round id per epoch, no timestamp. Each epoch is permuted on its own and never re-shuffled, so the rounds still lie in arrival order.");
    } else {
      say("V‑cloak.", " Random row ids, a bucket, a coarse window id, no timestamp. A closed window has been re-shuffled as a whole: its physical order is the engine's permutation, not the order anyone typed. The open window is still filling: each epoch is permuted, but its epochs lie in arrival order until the window closes.");
    }
    if (VC.state.live) {
      say("", " Showing " + rows.length + " of " + d.total + " stored row(s) in the last " + (d.windows || []).length +
          " window(s). What still shows: the window of a row, the number of rows per window, and the bucket.");
      if (VC.state.reveal) {
        say("", " The revealed number is the position of the message in the conversation as the panes read and verified it; " +
            "the server did not supply it and cannot. “—” is a row no pane has read since this page opened.");
      }
    }
  }

  function paintDump(d) {
    var body = document.getElementById("dumpBody");
    if (!body) return;
    var rows = dumpRows(d);
    var sig = JSON.stringify([d.mode, d.unavailable, d.total, VC.state.reveal, rows.map(function (r) {
      return [r.row_id, r.state, r.sent && r.sent.n];
    })]);
    view.rows = rows;
    view.windows = d.windows || [];
    view.mode = d.mode || VC.state.mode;
    if (sig === view.sig) return;       // nothing moved: leave the table alone
    view.sig = sig;
    body.textContent = "";
    rows.forEach(function (r, i) {
      var tr = VC.el("tr", r.state ? "win-" + r.state : "");
      tr.appendChild(VC.el("td", "", String(i + 1)));
      var id = VC.el("td", "", shortId(r.row_id));
      id.title = String(r.row_id);
      tr.appendChild(id);
      tr.appendChild(VC.el("td", "", String(r.bucket)));
      var win = VC.el("td", "", String(r.win));
      if (STATE_LABEL[r.state]) win.appendChild(VC.el("span", "winstate", STATE_LABEL[r.state]));
      tr.appendChild(win);
      tr.appendChild(VC.el("td", "", String(r.seq_enc)));
      tr.appendChild(VC.el("td", "", String(r.payload)));
      var sent = VC.el("td", "reveal-col sent-badge", r.sent ? "#" + r.sent.n + (r.sent.who ? " " + r.sent.who : "") : "—");
      if (r.sent && r.sent.who) sent.title = "Message " + r.sent.number + " of user " + r.sent.who + ", as the panes verified it";
      tr.appendChild(sent);
      body.appendChild(tr);
    });
    serverNote(d, rows);
  }

  function refreshDump() {
    var windows = VC.state.live && VC.state.windowS
      ? Math.max(2, Math.min(64, Math.ceil(DUMP_SPAN_S / VC.state.windowS))) : 0;
    // without --dev the route answers 403: the page does not ask
    if (VC.state.live && !VC.state.dev) return Promise.resolve(paintDump({ rows: [], unavailable: true }));
    return VC.api.dump(DUMP_ROWS, windows).then(paintDump);
  }

  function init() {
    var live = VC.state.live;

    USERS.forEach(function (u) {
      var form = document.getElementById("form" + u);
      var input = document.getElementById("in" + u);
      if (!form) return;
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        var text = input.value.trim();
        if (!text) return;
        input.value = "";
        if (live) sendLive(u, text).catch(function () { /* shown in the pane */ });
        else sendDemo(u, text);
      });
      var k = document.getElementById("key" + u);
      if (k) k.textContent = live ? "connecting…" : "device key: — (demo)";
    });

    var modeSwitch = document.getElementById("modeSwitch");
    var revealSwitch = document.getElementById("revealSwitch");
    if (modeSwitch) {
      modeSwitch.checked = VC.state.mode === "baseline";
      modeSwitch.addEventListener("change", function () {
        VC.api.setMode(this.checked ? "baseline" : "vcloak").then(refreshDump);
        var ls = document.getElementById("ls-mode");
        if (ls) ls.textContent = this.checked ? "baseline" : "vcloak";
      });
    }
    if (revealSwitch) revealSwitch.addEventListener("change", function () {
      document.body.classList.toggle("reveal", this.checked);
      VC.state.reveal = this.checked;
      refreshDump();
    });

    if (live) {
      // the store mode is the server's to change (its dev route, S5). The true order needs the stored
      // rows, which the server hands out with --dev only.
      if (modeSwitch) modeSwitch.disabled = true;
      if (revealSwitch) revealSwitch.disabled = !VC.state.dev;
      ready = startLive();
      refreshDump();
      return;
    }

    // demo: a short seeded conversation so the panel is never empty on first open
    [["A", "hey — are we still on for the review rehearsal?"],
     ["B", "yes, 6pm. did the kernel job come back?"],
     ["A", "ingested this morning. numbers are in the dashboard."],
     ["B", "nice. does the attack demo still run live?"]].forEach(function (m, i) {
      convo.push({ user: m[0], text: m[1], seq: seq[m[0]]++,
                   ts: new Date(Date.now() - (4 - i) * 42000).toTimeString().slice(0, 8) });
    });
    ready = Promise.resolve(false);
    renderDemo();
    refreshDump();
  }

  VC.chat = {
    init: init,
    refreshDump: refreshDump,
    /* the live panes, for the page's own tests (tests/integration/test_web_app.py) */
    ready: function () { return ready || Promise.resolve(false); },
    panes: panes,
    send: sendLive,
    read: readAll,
    /* what the panel shows now: one entry per row, with the overlay of the reveal switch */
    serverView: function () {
      return { mode: view.mode, windows: view.windows, rows: view.rows.map(function (r) {
        return { pos: r.pos, row_id: r.row_id, win: r.win, state: r.state, payload_b64: r.payload_b64,
                 n: r.sent ? r.sent.n : null, who: r.sent ? r.sent.who || null : null,
                 number: r.sent && r.sent.number !== undefined ? r.sent.number : null };
      }) };
    },
    transcript: function (u) {
      return panes[u].messages.map(function (m) {
        return { sender: m.sender, mine: m.mine, session: m.session, number: m.number, text: m.text, win: m.win, stored: m.stored };
      });
    }
  };
})(window);
