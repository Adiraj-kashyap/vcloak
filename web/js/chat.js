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
      setInterval(readAll, READ_EVERY_MS);
      return readAll().then(function () { return true; });
    }).catch(function (e) {
      USERS.forEach(function (u) { alertPane(u, "Not connected — " + (e.message || e)); });
      return false;
    });
  }

  /* ── the server view ── */
  function shortId(s) { return String(s).length > 13 ? String(s).slice(0, 8) + "…" : String(s); }

  function refreshDump() {
    VC.api.dump(50).then(function (d) {
      var body = document.getElementById("dumpBody");
      var note = document.getElementById("serverNote");
      if (!body) return;
      body.innerHTML = "";
      (d.rows || []).forEach(function (r, i) {
        var tr = document.createElement("tr");
        tr.innerHTML =
          "<td>" + (i + 1) + "</td>" +
          "<td>" + esc(shortId(r.row_id)) + "</td>" +
          "<td>" + esc(r.bucket) + "</td>" +
          "<td>" + esc(r.win) + "</td>" +
          "<td>" + esc(r.seq_enc) + "</td>" +
          "<td>" + esc(r.payload) + "</td>" +
          "<td class='reveal-col sent-badge'>" + (r.sent !== undefined ? "#" + r.sent : "—") + "</td>";
        body.appendChild(tr);
      });
      if (!note) return;
      if (d.unavailable) {
        note.textContent = "This server does not hand out its stored rows (GET /v1/dump gave no answer).";
        return;
      }
      note.innerHTML = VC.state.mode === "baseline"
        ? "<b>Unprotected baseline.</b> Rows carry a sequential id and sit in arrival order, so the row order <i>is</i> the conversation order — no key needed to read it."
        : "<b>V&#8209;cloak.</b> Random UUIDs, a shared bucket, a coarse window id, and no timestamp. The physical order of these rows is the GPU's permutation, not the order anyone typed.";
    });
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
    });

    if (live) {
      // the store mode and the true order are the server's to give: both switches act on the live
      // server only through its dev routes
      if (modeSwitch) modeSwitch.disabled = true;
      if (revealSwitch) revealSwitch.disabled = true;
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
    transcript: function (u) {
      return panes[u].messages.map(function (m) {
        return { sender: m.sender, mine: m.mine, session: m.session, number: m.number, text: m.text, win: m.win };
      });
    }
  };
})(window);
