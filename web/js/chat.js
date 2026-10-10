/* chat.js — the two-user chat and the "what the server stores" panel.
 *
 * In demo mode the conversation is local and the stored rows come from demo-data.js.
 * In live mode M13 replaces sendLocal/refreshDump internals with real API + WebCrypto calls;
 * the DOM contract (ids, classes) stays the same so the styling and tests survive.
 */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var esc = VC.esc;

  var convo = [];        // {user, text, seq, ts}
  var seq = { A: 0, B: 0 };

  function bubble(paneUser, msg) {
    var b = document.createElement("div");
    b.className = "bub" + (msg.user === paneUser ? " mine" : "");
    b.innerHTML = esc(msg.text) +
      "<span class='meta'>seq " + msg.seq + " · " + msg.ts + "</span>";
    return b;
  }

  function render() {
    ["A", "B"].forEach(function (u) {
      var box = document.getElementById("msgs" + u);
      if (!box) return;
      box.innerHTML = "";
      convo.forEach(function (m) { box.appendChild(bubble(u, m)); });
      box.scrollTop = box.scrollHeight;
    });
  }

  function send(user, text) {
    if (!text.trim()) return;
    var now = new Date();
    var msg = {
      user: user, text: text.trim(), seq: seq[user]++,
      ts: now.toTimeString().slice(0, 8)
    };
    convo.push(msg);
    render();
    VC.api.send(user, msg.text).then(function () { refreshDump(); });
  }

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
      if (note) {
        note.innerHTML = VC.state.mode === "baseline"
          ? "<b>Unprotected baseline.</b> Rows carry a sequential id and sit in arrival order, so the row order <i>is</i> the conversation order — no key needed to read it."
          : "<b>V&#8209;cloak.</b> Random UUIDs, a shared bucket, a coarse window id, and no timestamp. The physical order of these rows is the GPU's permutation, not the order anyone typed.";
      }
    });
  }

  function init() {
    ["A", "B"].forEach(function (u) {
      var form = document.getElementById("form" + u);
      var input = document.getElementById("in" + u);
      if (!form) return;
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        send(u, input.value);
        input.value = "";
      });
      var k = document.getElementById("key" + u);
      if (k) k.textContent = "device key: " + (u === "A" ? "ES256 · jkt 4f91…" : "ES256 · jkt b27c…") +
        (VC.state.live ? "" : " (demo)");
    });

    var modeSwitch = document.getElementById("modeSwitch");
    if (modeSwitch) modeSwitch.addEventListener("change", function () {
      VC.api.setMode(this.checked ? "baseline" : "vcloak").then(refreshDump);
      var ls = document.getElementById("ls-mode");
      if (ls) ls.textContent = this.checked ? "baseline" : "vcloak";
    });

    var revealSwitch = document.getElementById("revealSwitch");
    if (revealSwitch) revealSwitch.addEventListener("change", function () {
      document.body.classList.toggle("reveal", this.checked);
      VC.state.reveal = this.checked;
    });

    // a short seeded conversation so the panel is never empty on first open
    [["A", "hey — are we still on for the review rehearsal?"],
     ["B", "yes, 6pm. did the kernel job come back?"],
     ["A", "ingested this morning. numbers are in the dashboard."],
     ["B", "nice. does the attack demo still run live?"]].forEach(function (m, i) {
      convo.push({ user: m[0], text: m[1], seq: seq[m[0]]++,
                   ts: new Date(Date.now() - (4 - i) * 42000).toTimeString().slice(0, 8) });
    });
    render();
    refreshDump();
  }

  VC.chat = { init: init, refreshDump: refreshDump };
})(window);
