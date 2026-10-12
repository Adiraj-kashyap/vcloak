/* api.js — the only place that talks to the backend.
 *
 * Served over http  -> try the live API, fall back to demo data per call.
 * Opened from file:// -> demo data only (browsers block fetch of local files),
 *                        which is also the offline fallback for the review demo.
 */
(function (global) {
  "use strict";
  var VC = global.VC = global.VC || {};
  var DEMO = global.VCLOAK_DEMO || {};
  var canFetch = location.protocol === "http:" || location.protocol === "https:";

  function get(path, opts) {
    if (!canFetch) return Promise.reject(new Error("file://"));
    var ctl = new AbortController();
    var timer = setTimeout(function () { ctl.abort(); }, 4000);
    return fetch(path, Object.assign({ signal: ctl.signal, headers: { "Accept": "application/json" } }, opts || {}))
      .then(function (r) {
        clearTimeout(timer);
        if (!r.ok) throw new Error(path + " -> " + r.status);
        return r.json();
      });
  }
  function post(path, body) {
    return get(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body || {})
    });
  }

  /* One request of the live client (client.js): the status, the parsed body and the headers, whatever
   * the status. It rejects only when no answer came. The wait is long: `ack: "stored"` answers at an
   * epoch boundary. */
  function raw(method, path, body, headers) {
    var ctl = new AbortController();
    var timer = setTimeout(function () { ctl.abort(); }, 20000);
    var h = Object.assign({ "Accept": "application/json" }, headers || {});
    var init = { method: method, headers: h, signal: ctl.signal, cache: "no-store", credentials: "omit" };
    if (body !== undefined && body !== null) {
      h["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    return fetch(path, init).then(function (r) {
      return r.text().then(function (t) {
        clearTimeout(timer);
        var parsed = null;
        try { parsed = t ? JSON.parse(t) : null; } catch (e) { parsed = null; }
        return { status: r.status, body: parsed, headers: r.headers };
      });
    }, function (e) { clearTimeout(timer); throw e; });
  }

  var API = {
    canFetch: canFetch,
    origin: canFetch ? location.origin : "",
    raw: raw,

    /* Probe once at startup: decides live vs demo and reveals dev mode. */
    hello: function () {
      return get("/v1/stats/live").then(function (s) {
        VC.state.live = true;
        VC.state.dev = !!s.dev;
        VC.state.sessions = !!s.sessions;
        VC.state.payloadLen = s.payload_len;
        VC.state.windowS = s.window_s;
        if (s.mode) VC.state.mode = s.mode;
        VC.state.backend = (s.gpu && s.gpu.backend) || "cpu";
        VC.state.runner = (s.gpu && s.gpu.runner) || "local";
        return s;
      }).catch(function () {
        VC.state.live = false;
        return null;
      });
    },

    stats: function () {
      return get("/v1/stats/live").catch(function () {
        /* demo clock so the strip still ticks offline */
        var t = Date.now();
        return { epoch: Math.floor(t / 200) % 100000, win: 41, slots: 64,
                 queued: Math.floor((t / 200) % 7), mode: VC.state.mode,
                 gpu: null, demo: true };
      });
    },

    dashboard: function () {
      return get("/v1/dashboard")
        .catch(function () { return get("data/dashboard.json"); })
        .catch(function () { return DEMO.dashboard; });
    },

    dump: function (limit, windows) {
      return get("/v1/dump?limit=" + (limit || 50) + (windows ? "&windows=" + windows : "")).catch(function () {
        /* a live server that does not hand out its rows: say so, never show demo rows in their place */
        if (VC.state.live) return { rows: [], unavailable: true };
        var d = JSON.parse(JSON.stringify(DEMO.dump || { rows: [] }));
        if (VC.state.mode === "baseline") {
          d.rows.sort(function (a, b) { return a.sent - b.sent; });
          d.rows.forEach(function (r, i) { r.row_id = String(1000 + i); });
          d.mode = "baseline";
        }
        return d;
      });
    },

    logs: function (kind, tail) {
      return get("/v1/logs?kind=" + kind + "&tail=" + (tail || 400)).catch(function () {
        return { lines: (DEMO.logs && DEMO.logs[kind]) || ["(no log data in demo mode)"] , demo: true };
      });
    },

    setMode: function (mode) {
      VC.state.mode = mode;
      return post("/v1/mode", { mode: mode }).catch(function () { return { mode: mode, demo: true }; });
    },

    attack: function (layout) {
      return post("/v1/eval/attack", { layout: layout }).catch(function () { return null; });
    }
  };

  VC.api = API;
})(window);
