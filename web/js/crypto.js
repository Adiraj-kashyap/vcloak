/* crypto.js — everything the browser client does with keys (WebCrypto only, no library).
 *
 * It follows docs/API.md "The client" byte for byte, so a pane can talk to the Python SDK:
 *
 *   device key   ES256 (ECDSA P-256), generated with extractable = false. It signs the DPoP proofs.
 *   prekey       X25519, generated with extractable = false. It agrees on the content key.
 *   K_content    HKDF-SHA256(X25519(own, peer), info = "vcloak-content-v1" + transcript)
 *   conv_token   base64url(HKDF-SHA256(K_content, info = "vcloak-conv-token-v1", 24 bytes))
 *   message      nonce(12) || AES-256-GCM(K_content, nonce, pad(header + text), aad = "vcloak-msg-v1\0" + token)
 *
 * The private keys live in IndexedDB as CryptoKey handles. A handle can sign or derive; the browser
 * never gives its bytes to script (exportKey rejects), so code injected into the page could use a key
 * while the page is open but could not carry it away.
 */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var subtle = global.crypto && global.crypto.subtle;
  var te = new TextEncoder();

  var NONCE_LEN = 12, TAG_LEN = 16, PUBLIC_LEN = 32, PAD_MARK = 0x80;
  var HEADER_LEN = 18;            // version(1) sender(1) session(8) number(LE64)
  var VERSION = 1;
  var INFO_CONTENT = "vcloak-content-v1";
  var INFO_TOKEN = "vcloak-conv-token-v1";
  var AAD = "vcloak-msg-v1\u0000";
  var CONTEXT = "vcloak-chat-v1\u0000";
  var FINGERPRINT = "vcloak-fingerprint-v1\u0000";

  /* ── bytes ── */
  function utf8(s) { return te.encode(s); }
  function concat() {
    var n = 0, i, off = 0;
    for (i = 0; i < arguments.length; i++) n += arguments[i].length;
    var out = new Uint8Array(n);
    for (i = 0; i < arguments.length; i++) { out.set(arguments[i], off); off += arguments[i].length; }
    return out;
  }
  function b64(bytes) {
    var s = "", i;
    for (i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  }
  function unb64(s) {
    if (typeof s !== "string" || s.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(s)) throw new Error("not base64");
    var bin = atob(s), out = new Uint8Array(bin.length), i;
    for (i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  function b64u(bytes) { return b64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
  function hex(bytes) {
    var s = "", i;
    for (i = 0; i < bytes.length; i++) s += (bytes[i] < 16 ? "0" : "") + bytes[i].toString(16);
    return s;
  }
  function random(n) { var b = new Uint8Array(n); global.crypto.getRandomValues(b); return b; }
  function compare(a, b) {                       // as Python compares bytes
    var n = Math.min(a.length, b.length), i;
    for (i = 0; i < n; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
    return a.length === b.length ? 0 : (a.length < b.length ? -1 : 1);
  }
  function sha256(bytes) {
    return subtle.digest("SHA-256", bytes).then(function (d) { return new Uint8Array(d); });
  }
  function hkdf(secret, info, nbytes) {
    return subtle.importKey("raw", secret, "HKDF", false, ["deriveBits"]).then(function (k) {
      return subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt: new Uint8Array(0), info: info }, k, nbytes * 8);
    }).then(function (bits) { return new Uint8Array(bits); });
  }

  /* ── IndexedDB: the key handles of each pane ── */
  var memory = {};                               // used when IndexedDB is not available (private mode)
  var dbPromise = null;
  function db() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve) {
      var req;
      try { req = global.indexedDB.open("vcloak", 1); } catch (e) { resolve(null); return; }
      req.onupgradeneeded = function () { req.result.createObjectStore("handles"); };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { resolve(null); };
      req.onblocked = function () { resolve(null); };
    });
    return dbPromise;
  }
  function stored(name) {
    return db().then(function (d) {
      if (!d) return memory[name];
      return new Promise(function (resolve) {
        var req = d.transaction("handles", "readonly").objectStore("handles").get(name);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { resolve(undefined); };
      });
    });
  }
  function store(name, value) {
    return db().then(function (d) {
      if (!d) { memory[name] = value; return value; }
      return new Promise(function (resolve) {
        var tx = d.transaction("handles", "readwrite");
        tx.objectStore("handles").put(value, name);
        tx.oncomplete = function () { resolve(value); };
        tx.onerror = tx.onabort = function () { memory[name] = value; resolve(value); };
      });
    });
  }
  function forget(name) {
    delete memory[name];
    return db().then(function (d) {
      if (!d) return;
      return new Promise(function (resolve) {
        var tx = d.transaction("handles", "readwrite");
        tx.objectStore("handles").delete(name);
        tx.oncomplete = tx.onerror = tx.onabort = function () { resolve(); };
      });
    });
  }
  function persistent() { return db().then(function (d) { return !!d; }); }

  /* ── the device key and the DPoP proof (RFC 9449) ── */
  function loadDevice(label) {
    var name = "device:" + label;
    return stored(name).then(function (pair) {
      if (pair && pair.privateKey && pair.publicKey) return pair;
      return subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"])
        .then(function (fresh) { return store(name, fresh); });
    }).then(function (pair) {
      return subtle.exportKey("jwk", pair.publicKey).then(function (j) {
        var jwk = { kty: "EC", crv: "P-256", x: j.x, y: j.y };
        // RFC 7638: the members in this order, no spaces
        var canonical = '{"crv":"P-256","kty":"EC","x":"' + j.x + '","y":"' + j.y + '"}';
        return sha256(utf8(canonical)).then(function (digest) {
          return { label: label, privateKey: pair.privateKey, publicKey: pair.publicKey, jwk: jwk, jkt: b64u(digest) };
        });
      });
    });
  }
  function segment(obj) { return b64u(utf8(JSON.stringify(obj))); }
  function proof(device, method, url, token) {
    var claims = { htm: method, htu: url, iat: Math.floor(Date.now() / 1000), jti: b64u(random(16)) };
    var ready = token ? sha256(utf8(token)).then(function (d) { claims.ath = b64u(d); }) : Promise.resolve();
    return ready.then(function () {
      var input = segment({ typ: "dpop+jwt", alg: "ES256", jwk: device.jwk }) + "." + segment(claims);
      // WebCrypto returns r || s (64 bytes), which is the JWS form of an ES256 signature
      return subtle.sign({ name: "ECDSA", hash: "SHA-256" }, device.privateKey, utf8(input)).then(function (sig) {
        return input + "." + b64u(new Uint8Array(sig));
      });
    });
  }

  /* ── the prekey and the agreement ── */
  function loadPrekey(label) {
    var name = "prekey:" + label;
    return stored(name).then(function (pair) {
      if (pair && pair.privateKey && pair.publicKey) return pair;
      return subtle.generateKey({ name: "X25519" }, false, ["deriveBits"])
        .then(function (fresh) { return store(name, fresh); });
    }).then(function (pair) {
      return subtle.exportKey("raw", pair.publicKey).then(function (raw) {
        return { label: label, privateKey: pair.privateKey, publicKey: pair.publicKey, public: new Uint8Array(raw) };
      });
    });
  }

  function transcript(a, b, context) {
    if (a.length !== PUBLIC_LEN || b.length !== PUBLIC_LEN) throw new Error("X25519 public keys are 32 bytes");
    var lo = compare(a, b) <= 0 ? a : b, hi = lo === a ? b : a;
    var len = new Uint8Array(4);
    new DataView(len.buffer).setUint32(0, context.length, true);
    return concat(lo, hi, len, context);
  }

  /* K_content with `peerPublic`, for the accounts `ownName` and `peerName`. The key bytes exist in script
   * only inside this function: they are imported as a non-extractable AES key and then overwritten. */
  function agree(prekey, peerPublic, ownName, peerName, block) {
    if (compare(prekey.public, peerPublic) === 0) return Promise.reject(new Error("both ends hold the same prekey"));
    var names = [ownName, peerName].sort();
    var t = transcript(prekey.public, peerPublic, utf8(CONTEXT + names.join("\u0000")));
    var conv = { block: block, role: compare(prekey.public, peerPublic) < 0 ? 0 : 1 };
    return subtle.importKey("raw", peerPublic, { name: "X25519" }, false, []).then(function (pub) {
      return subtle.deriveBits({ name: "X25519", public: pub }, prekey.privateKey, 256);
    }).then(function (shared) {
      var s = new Uint8Array(shared);
      return hkdf(s, concat(utf8(INFO_CONTENT), t), 32).then(function (k) { s.fill(0); return k; });
    }).then(function (k) {
      return Promise.all([
        subtle.importKey("raw", k, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]),
        hkdf(k, utf8(INFO_TOKEN), 24),
        sha256(concat(utf8(FINGERPRINT), t))
      ]).then(function (r) {
        k.fill(0);
        conv.key = r[0];
        conv.token = b64u(r[1]);
        conv.aad = utf8(AAD + conv.token);
        // 30 digits of the first 15 bytes, in groups of five: the same at both ends
        var n = 0n, i;
        for (i = 0; i < 15; i++) n = (n << 8n) | BigInt(r[2][i]);
        var digits = (n % (10n ** 30n)).toString().padStart(30, "0");
        conv.fingerprint = digits.match(/.{5}/g).join(" ");
        return conv;
      });
    });
  }

  /* ── one message ── */
  function maxText(block) { return block - 1 - HEADER_LEN; }

  function seal(conv, session, number, text) {
    var raw = utf8(text);
    if (raw.length > maxText(conv.block)) {
      return Promise.reject(new Error("a message holds at most " + maxText(conv.block) + " bytes of UTF-8, this one has " + raw.length));
    }
    var padded = new Uint8Array(conv.block);     // header | text | 0x80 | 00…  — always `block` bytes
    var view = new DataView(padded.buffer);
    padded[0] = VERSION;
    padded[1] = conv.role;
    padded.set(session, 2);
    view.setBigUint64(10, BigInt(number), true);
    padded.set(raw, HEADER_LEN);
    padded[HEADER_LEN + raw.length] = PAD_MARK;
    var nonce = random(NONCE_LEN);
    return subtle.encrypt({ name: "AES-GCM", iv: nonce, additionalData: conv.aad, tagLength: TAG_LEN * 8 }, conv.key, padded)
      .then(function (ct) { return concat(nonce, new Uint8Array(ct)); });
  }

  /* {sender, session (hex), number, text}; rejects with .kind = "tamper" | "protocol" */
  function open(conv, payload) {
    function fail(kind, msg) { var e = new Error(msg); e.kind = kind; return e; }
    if (payload.length !== NONCE_LEN + conv.block + TAG_LEN) return Promise.reject(fail("tamper", "a payload has the wrong size"));
    return subtle.decrypt({ name: "AES-GCM", iv: payload.subarray(0, NONCE_LEN), additionalData: conv.aad, tagLength: TAG_LEN * 8 },
                          conv.key, payload.subarray(NONCE_LEN))
      .then(function (plain) { return new Uint8Array(plain); },
            function () { throw fail("tamper", "a payload is not a ciphertext of this conversation"); })
      .then(function (padded) {
        var end = padded.length - 1;
        while (end >= 0 && padded[end] === 0) end--;
        if (padded.length !== conv.block || end < 0 || padded[end] !== PAD_MARK) throw fail("tamper", "bad padding");
        if (end < HEADER_LEN) throw fail("protocol", "a message without a header");
        if (padded[0] !== VERSION || padded[1] > 1) throw fail("protocol", "a message header of another version");
        var number = new DataView(padded.buffer, padded.byteOffset).getBigUint64(10, true);
        if (number > BigInt(Number.MAX_SAFE_INTEGER)) throw fail("protocol", "a message number out of range");
        var text;
        try { text = new TextDecoder("utf-8", { fatal: true }).decode(padded.subarray(HEADER_LEN, end)); }
        catch (e) { throw fail("protocol", "a message that is not UTF-8"); }
        return { sender: padded[1], session: hex(padded.subarray(2, 10)), number: Number(number), text: text };
      });
  }

  /* Does this browser have what the client needs? Resolves to null, or to the reason it does not. */
  function unsupported() {
    if (!subtle || !global.isSecureContext) return Promise.resolve("WebCrypto needs a secure context (https, or http on localhost)");
    if (typeof BigInt !== "function") return Promise.resolve("this browser has no BigInt");
    return subtle.generateKey({ name: "X25519" }, false, ["deriveBits"])
      .then(function () { return null; }, function () { return "this browser has no X25519 in WebCrypto"; });
  }

  VC.crypto = {
    b64: b64, unb64: unb64, b64u: b64u, hex: hex, random: random, utf8: utf8,
    loadDevice: loadDevice, proof: proof, loadPrekey: loadPrekey, agree: agree,
    seal: seal, open: open, maxText: maxText, unsupported: unsupported,
    stored: stored, store: store, forget: forget, persistent: persistent,
    PUBLIC_LEN: PUBLIC_LEN, OVERHEAD: NONCE_LEN + TAG_LEN
  };
})(window);
