/* client.js — one V-cloak client in the page: a session and a conversation (the browser's port of
 * vcloak.client.sdk, same rules, same bytes: docs/API.md "Sessions and DPoP" and "The client").
 *
 *   var c = new VC.Client("A");
 *   c.init().then(() => c.signIn(name, password)).then(() => c.start(peerName));
 *   c.send("hi");                 // stored before it resolves (ack: "stored")
 *   c.sync().then(messages => …)  // new messages, decrypted, order verified
 *
 * The order is verified here, not by the server: every plaintext starts with (sender, session, number),
 * and for each (sender, session) the numbers must come as n, n+1, n+2, … . A repeat is dropped; a jump
 * rejects with kind "sequence"; a payload that does not authenticate rejects with kind "tamper".
 * A pane starts reading at the window that is open when it starts, so the first number it sees of a
 * session is where that session begins for it (the SDK's `strict_start=False`).
 *
 * Every call of one client runs after the one before it (a queue), so two requests never race for the
 * single-use refresh token.
 */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var cr = VC.crypto;

  var SEND_ATTEMPTS = 5;
  var REFRESH_MARGIN_S = 30;

  function ClientError(kind, message, extra) {
    var e = new Error(message);
    e.name = "ClientError";
    e.kind = kind;                    // api | login | sequence | tamper | protocol | unconfirmed | state
    if (extra) Object.keys(extra).forEach(function (k) { e[k] = extra[k]; });
    return e;
  }
  function apiError(r) {
    var b = r.body || {};
    return ClientError("api", r.status + " " + (b.error || "") + (b.failed_check || b.reason ? " (" + (b.failed_check || b.reason) + ")" : ""),
                       { status: r.status, error: b.error || "", detail: b.failed_check || b.reason || "" });
  }
  function sleep(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
  function retryAfter(r) {
    var s = parseFloat(r.headers.get("Retry-After"));
    return (isFinite(s) ? Math.min(Math.max(s, 0), 5) : 1) * 1000;
  }

  function Client(label) {
    this.label = label;
    this.username = "";
    this.device = null;
    this.prekey = null;
    this.conv = null;
    this._access = "";
    this._refresh = "";
    this._expiresAt = 0;
    this._queue = Promise.resolve();
  }

  Client.prototype._serial = function (fn) {
    var run = this._queue.then(fn, fn);
    this._queue = run.then(function () {}, function () {});
    return run;
  };

  /* The key handles of this pane: made once, then found again in IndexedDB. */
  Client.prototype.init = function () {
    var self = this;
    return cr.loadDevice(this.label).then(function (d) {
      self.device = d;
      return cr.loadPrekey(self.label);
    }).then(function (p) { self.prekey = p; return self; });
  };

  Client.prototype._headers = function (method, path, withToken) {
    var self = this;
    if (withToken && !this._access) return Promise.reject(ClientError("state", "log in first"));
    return cr.proof(this.device, method, VC.api.origin + path, withToken ? this._access : null).then(function (p) {
      var h = { "DPoP": p };
      if (withToken) h["Authorization"] = "DPoP " + self._access;
      return h;
    });
  };

  Client.prototype._takeTokens = function (r) {
    if (r.status !== 200) throw apiError(r);
    this._access = r.body.access_token;
    this._refresh = r.body.refresh_token;
    this._expiresAt = Date.now() / 1000 + Number(r.body.expires_in);
  };

  Client.prototype._register = function (username, password) {
    return VC.api.raw("POST", "/v1/auth/register", { username: username, password: password }).then(function (r) {
      if (r.status === 409) return false;
      if (r.status !== 201) throw apiError(r);
      return true;
    });
  };

  Client.prototype._login = function (username, password) {
    var self = this, path = "/v1/auth/login";
    return this._headers("POST", path, false).then(function (h) {
      return VC.api.raw("POST", path, { username: username, password: password }, h);
    }).then(function (r) {
      self._takeTokens(r);
      self.username = username;
    });
  };

  Client.prototype._doRefresh = function () {
    var self = this, path = "/v1/auth/refresh";
    if (!this._refresh) return Promise.reject(ClientError("state", "no refresh token"));
    var token = this._refresh;
    this._refresh = "";               // single use, whatever the answer
    return this._headers("POST", path, false).then(function (h) {
      return VC.api.raw("POST", path, { refresh_token: token }, h);
    }).then(function (r) {
      if (r.status !== 200) self._access = "";
      self._takeTokens(r);
      self.refreshes = (self.refreshes || 0) + 1;
    });
  };

  /* One authenticated request. The token is replaced shortly before it ends, and once more if the server says it has. */
  Client.prototype._authed = function (method, path, body) {
    var self = this;
    function once() {
      return self._headers(method, path, true).then(function (h) { return VC.api.raw(method, path, body, h); });
    }
    if (!this._access) return Promise.reject(ClientError("state", "log in first"));
    var ready = (this._refresh && Date.now() / 1000 >= this._expiresAt - REFRESH_MARGIN_S) ? this._doRefresh() : Promise.resolve();
    return ready.then(once).then(function (r) {
      if (r.status === 401 && self._refresh && r.body && r.body.failed_check === "token_exp") {
        return self._doRefresh().then(once);
      }
      return r;
    });
  };

  /* Log in as `username`, creating the account when the server does not know it (it forgets them at a
   * restart), and publish the prekey. Resolves to true when the account was created now. */
  Client.prototype.signIn = function (username, password) {
    var self = this;
    return this._serial(function () {
      var created = false;
      return self._login(username, password).catch(function (e) {
        if (e.kind !== "api" || e.error !== "invalid_credentials") throw e;
        return self._register(username, password).then(function (ok) {
          if (!ok) throw ClientError("login", "the name " + username + " is taken with another password");
          created = true;
          return self._login(username, password);
        });
      }).then(function () {
        return self._authed("PUT", "/v1/prekeys", { prekey_b64: cr.b64(self.prekey.public) });
      }).then(function (r) {
        if (r.status !== 204) throw apiError(r);
        return created;
      });
    });
  };

  Client.prototype.refresh = function () {
    var self = this;
    return this._serial(function () { return self._doRefresh(); });
  };

  Client.prototype.logout = function () {
    var self = this;
    return this._serial(function () {
      return self._authed("POST", "/v1/auth/logout").then(function (r) {
        if (r.status !== 204) throw apiError(r);
        self._access = self._refresh = "";
      });
    });
  };

  /* Sent without the session, so the server is not told who asks (ADR-019). */
  Client.prototype.fetchPrekey = function (username) {
    return VC.api.raw("GET", "/v1/prekeys/" + encodeURIComponent(username)).then(function (r) {
      if (r.status !== 200) throw apiError(r);
      var raw;
      try { raw = cr.unb64(r.body.prekey_b64); } catch (e) { raw = null; }
      if (!raw || raw.length !== cr.PUBLIC_LEN) throw ClientError("tamper", "the prekey answer is malformed");
      return raw;
    });
  };

  function windows() {
    return VC.api.raw("GET", "/v1/windows").then(function (r) {
      if (r.status !== 200) throw apiError(r);
      return r.body;
    });
  }

  /* Agree on K_content with `peer` and start reading at the open window. `payloadLen` is the server's
   * payload size (from /v1/stats/live): the padded block is that minus nonce and tag. */
  Client.prototype.start = function (peer, payloadLen) {
    var self = this;
    return this._serial(function () {
      if (!self.username) throw ClientError("state", "log in first");
      return self.fetchPrekey(peer).then(function (peerPublic) {
        return cr.agree(self.prekey, peerPublic, self.username, peer, payloadLen - cr.OVERHEAD);
      }).then(function (conv) {
        return windows().then(function (w) {
          conv.peer = peer;
          conv.session = cr.random(8);
          conv.sessionHex = cr.hex(conv.session);
          conv.number = 0;            // own messages confirmed as stored
          conv.pending = null;        // the ciphertext of message `number`, not confirmed yet
          conv.firstWin = conv.cursor = w.win;
          conv.consumed = {};         // window -> payloads of it already handled
          conv.next = {};             // "sender:session" -> the next number
          conv.first = {};
          conv.repeats = 0;
          self.conv = conv;
          return conv;
        });
      });
    });
  };

  Client.prototype._postStored = function (payload) {
    var self = this, conv = this.conv;
    var body = { conv_token: conv.token, payload_b64: cr.b64(payload), ack: "stored" };
    var last = "";
    function attempt(left) {
      if (left === 0) {
        return Promise.reject(ClientError("unconfirmed", "message " + conv.number + " is not confirmed as stored (" + last + "); it stays pending"));
      }
      return self._authed("POST", "/v1/messages", body).then(function (r) {
        if (r.status === 201 && r.body && r.body.stored === true) return;
        if (r.status === 503) {       // queue_full or not_stored: it is not in the store
          last = (r.body && r.body.error) || "503";
          return sleep(retryAfter(r)).then(function () { return attempt(left - 1); });
        }
        if (r.status === 504) { last = "ack_timeout"; return attempt(left - 1); }   // outcome unknown
        throw apiError(r);
      }, function (e) {
        if (e.kind) throw e;
        last = "network";             // outcome unknown: the same ciphertext goes again
        return attempt(left - 1);
      });
    }
    return attempt(SEND_ATTEMPTS);
  };

  Client.prototype._flush = function () {
    var conv = this.conv;
    if (!conv.pending) return Promise.resolve();
    return this._postStored(conv.pending).then(function () {
      conv.pending = null;
      conv.number += 1;
    });
  };

  /* Store one message; resolves to its number. The number is not reused for another text until the
   * message is confirmed. */
  Client.prototype.send = function (text) {
    var self = this;
    return this._serial(function () {
      var conv = self.conv;
      if (!conv) throw ClientError("state", "start a conversation first");
      var number;
      return self._flush().then(function () {
        number = conv.number;
        return cr.seal(conv, conv.session, number, text);
      }).then(function (payload) {
        conv.pending = payload;
        return self._flush();
      }).then(function () { return number; });
    });
  };

  Client.prototype._fetch = function (win) {
    var conv = this.conv;
    return this._authed("POST", "/v1/read", { conv_token: conv.token, win: win }).then(function (r) {
      if (r.status !== 200) throw apiError(r);
      var b = r.body;
      if (!b || b.win !== win || !Array.isArray(b.payloads_b64)) {
        throw ClientError("tamper", "the answer for window " + win + " is not a read answer", { win: win });
      }
      return b.payloads_b64.map(function (item) {
        var raw;
        try { raw = cr.unb64(item); } catch (e) { raw = null; }
        if (!raw || raw.length !== conv.block + cr.OVERHEAD) {
          throw ClientError("tamper", "a payload of window " + win + " is malformed", { win: win });
        }
        return raw;
      });
    });
  };

  /* True for the next message of its sender, false for a repeat; throws on a gap. */
  function accept(conv, m) {
    var key = m.sender + ":" + m.session;
    var expected = conv.next[key];
    if (expected === undefined) {
      conv.first[key] = m.number;
      conv.next[key] = m.number + 1;
      return true;
    }
    if (m.number === expected) { conv.next[key] = expected + 1; return true; }
    if (conv.first[key] <= m.number && m.number < expected) return false;
    if (m.number < expected) {
      throw ClientError("sequence", "message " + m.number + " of a sender came after message " + conv.first[key] + ": out of order");
    }
    throw ClientError("sequence", "expected message " + expected + " of a sender, got " + m.number + ": " +
                      (m.number - expected) + " message(s) are missing or out of order");
  }

  /* The messages that are new since the last call, in the server's order, verified. */
  Client.prototype.sync = function () {
    var self = this;
    return this._serial(function () {
      var conv = self.conv;
      if (!conv) throw ClientError("state", "start a conversation first");
      return windows().then(function (w) {
        var current = w.win, wins = [], i;
        for (i = conv.cursor; i <= current; i++) wins.push(i);
        var fetched = {};
        // newest first: an older window is then read later than every newer one, so a message is never
        // seen before one that precedes it
        var chain = Promise.resolve();
        wins.slice().reverse().forEach(function (win) {
          chain = chain.then(function () { return self._fetch(win); }).then(function (p) { fetched[win] = p; });
        });
        var out = [];
        wins.forEach(function (win) {
          chain = chain.then(function () {
            var payloads = fetched[win], done = conv.consumed[win] || 0;
            if (payloads.length < done) {
              throw ClientError("sequence", "window " + win + " holds fewer messages than it did: " + (done - payloads.length) + " missing", { win: win });
            }
            var inner = Promise.resolve();
            payloads.slice(done).forEach(function (payload) {
              inner = inner.then(function () { return cr.open(conv, payload); }).then(function (m) {
                if (accept(conv, m)) {
                  var mine = m.sender === conv.role;
                  out.push({ sender: mine ? self.username : conv.peer, mine: mine, session: m.session,
                             number: m.number, text: m.text, win: win, stored: cr.b64(payload) });
                } else {
                  conv.repeats += 1;
                }
              }, function (e) {
                if (e.name === "ClientError") throw e;     // from an earlier payload of this window
                throw ClientError(e.kind || "tamper", e.message + " (window " + win + ")", { win: win });
              });
            });
            return inner.then(function () { conv.consumed[win] = payloads.length; });
          });
        });
        return chain.then(function () {
          while (conv.cursor < current - 1) {   // a window two behind the open one gets no more rows
            delete conv.consumed[conv.cursor];
            conv.cursor += 1;
          }
          return out;
        });
      });
    });
  };

  VC.Client = Client;
  VC.ClientError = ClientError;
})(window);
