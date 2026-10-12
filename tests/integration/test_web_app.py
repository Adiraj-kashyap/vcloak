"""M13: the web app, served by the real service and run in a real browser.

Two layers:

- the static mount and its headers (S1, A5), with the test client of the framework;
- the page itself in headless Chrome or Edge (scripts/headless.py), against `vcloak serve --dev --sessions`
  inside the test process (scripts/demo_two_users.py: uvicorn on a loopback port, wall clock, 2 s
  windows). The browser's proofs, tokens and ciphertexts are checked by the server and by the Python SDK,
  which share no code with the page. These tests are SKIPPED when no browser is installed: read the skip
  count before calling the run a pass.

Nothing here measures anything: the engine is the numpy simulator and the store is SQLite in memory.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from demo_two_users import LocalServer, free_port, sign_in
from headless import Browser, Page, find_browser
from vcloak.cli import build_backend, build_parser
from vcloak.crypto.client import PAYLOAD_LEN
from vcloak.service.app import create_app
from vcloak.service.models import conv_id_of
from vcloak.service.session import PasswordParams, SessionConfig
from vcloak.service.web import CSP, WEB_DIR

EPOCH_MS = 100
WINDOW_S = 2
ARGV = ["--dev", "--sessions", "--store", "sqlite", "--window-s", str(WINDOW_S), "--epoch-ms", str(EPOCH_MS)]

needs_browser = pytest.mark.skipif(find_browser() is None, reason="no Chrome or Edge installed (set VCLOAK_BROWSER)")


# ── S1: the mount and its headers ────────────────────────────────────────────
def app_client(*argv: str, dev: bool) -> TestClient:
    a = build_parser().parse_args(["serve", "--store", "sqlite", "--dev", *argv])
    return TestClient(create_app(build_backend(a), dev=dev))


def test_app_serves_the_shell_with_a_strict_csp() -> None:
    with app_client(dev=True) as c:
        first = c.get("/app", follow_redirects=False)
        assert first.status_code == 307 and first.headers["location"].endswith("/app/")
        r = c.get("/app")
        assert r.status_code == 200 and "<title>V-cloak</title>" in r.text
        for answer in (first, r, c.get("/app/js/chat.js"), c.get("/app/css/app.css"), c.get("/app/nothing.js")):
            assert answer.headers["content-security-policy"] == CSP
            assert answer.headers["cache-control"] == "no-store"
            assert answer.headers["x-content-type-options"] == "nosniff"
        assert c.get("/app/nothing.js").status_code == 404
        kind = c.get("/app/js/chat.js").headers["content-type"]
        assert kind.startswith(("text/javascript", "application/javascript"))


def test_csp_allows_no_inline_script_and_no_other_origin() -> None:
    policy = dict(part.split(" ", 1) for part in CSP.split("; "))
    assert policy["default-src"] == "'self'"
    assert policy["script-src"] == "'self'"
    assert policy["connect-src"] == "'self'"
    assert policy["object-src"] == "'none'" and policy["base-uri"] == "'none'"
    assert policy["frame-ancestors"] == "'none'"
    # the one relaxation is style attributes (ISSUE-29): never a script, never a stylesheet
    assert [k for k, v in policy.items() if "unsafe" in v] == ["style-src-attr"]
    assert not any(v for v in policy.values() if "http" in v or "*" in v)


def test_without_dev_the_page_is_revalidated_not_stored() -> None:
    with app_client(dev=False) as c:
        assert c.get("/app/").headers["cache-control"] == "no-cache"
        assert c.get("/v1/stats/live").json()["dev"] is False


def test_files_outside_web_are_not_served() -> None:
    with app_client(dev=True) as c:
        for path in ("/app/../pyproject.toml", "/app/%2e%2e/pyproject.toml", "/app/..%2fpyproject.toml",
                     "/app/js/../../pyproject.toml"):
            r = c.get(path)
            assert r.status_code in (404, 400) or "[project]" not in r.text, path


def test_no_page_when_the_caller_wants_none() -> None:
    a = build_parser().parse_args(["serve", "--store", "sqlite", "--dev"])
    with TestClient(create_app(build_backend(a), web_dir=False)) as c:
        assert c.get("/app/").status_code == 404


def test_stats_live_is_public_parameters_only() -> None:
    with app_client(dev=True) as c:
        body = c.get("/v1/stats/live").json()
    assert set(body) == {"mode", "dev", "sessions", "win", "window_s", "epoch_ms", "slots", "queued", "epochs",
                         "payload_len", "switchable", "gpu"}
    assert body["mode"] == "vcloak" and body["dev"] is True and body["sessions"] is False
    assert body["payload_len"] == PAYLOAD_LEN and body["gpu"] is None


# ── S4: the stored rows (dev only) ───────────────────────────────────────────
def post_stored(c: TestClient, token: str, n: int) -> None:
    for i in range(n):
        payload = base64.b64encode(bytes([i]) * PAYLOAD_LEN).decode()
        body = {"conv_token": token, "payload_b64": payload, "ack": "stored"}
        assert c.post("/v1/messages", json=body).status_code == 201


def test_dump_is_refused_without_dev() -> None:
    """A3: without --dev the route gives nothing, whatever is asked."""
    with app_client(dev=False) as c:
        post_stored(c, "a" * 32, 3)
        for path in ("/v1/dump", "/v1/dump?limit=5", "/v1/dump?limit=0", "/v1/dump?windows=1&limit=500"):
            r = c.get(path)
            assert r.status_code == 403 and r.json() == {"error": "dev_only"}, path
            assert r.headers["cache-control"] == "no-store"


def test_dump_is_the_store_in_physical_order() -> None:
    """S4: the answer is the rows of the store, window after window, in the order the store holds them,
    and a closed window is no longer in the order of arrival."""
    with app_client("--epoch-ms", "50", "--window-s", "1", dev=True) as c:
        post_stored(c, "b" * 32, 16)
        deadline = time.monotonic() + 20
        while True:
            d = c.get("/v1/dump?limit=500&windows=16").json()
            if d["total"] == 16 and all(w["state"] == "reshuffled" for w in d["windows"] if w["rows"]):
                break
            assert time.monotonic() < deadline, d["windows"]
            time.sleep(0.1)
        repo = c.app.state.backend.repo  # type: ignore[attr-defined]
        stored = [r for w in d["windows"] for r in repo.window_rows(w["win"])]
        assert [r["row_id"] for r in d["rows"]] == [str(r.row_id) for r in stored]
        assert [base64.b64decode(r["payload_b64"]) for r in d["rows"]] == [r.payload for r in stored]
        assert [base64.b64decode(r["seq_enc_b64"]) for r in d["rows"]] == [r.seq_enc for r in stored]
        assert [r["pos"] for r in d["rows"]] == list(range(16))
        assert set(d["rows"][0]) == {"pos", "win", "row_id", "bucket", "seq_enc_b64", "payload_b64", "ts", "conv_hex"}
        assert all(r["ts"] is None and r["conv_hex"] is None for r in d["rows"])  # V-cloak rows have neither
        assert d["mode"] == "vcloak" and d["visible_round"] == "window" and d["truncated"] is False
        assert [w["win"] for w in d["windows"]] == list(range(d["win"] - 15, d["win"] + 1))
        assert d["windows"][-1]["state"] == "open"
        wins = [r["win"] for r in d["rows"]]
        assert wins == sorted(wins)
        arrival = [base64.b64decode(r["payload_b64"])[0] for r in d["rows"]]
        assert sorted(arrival) == list(range(16)) and arrival != sorted(arrival)

        # the newest rows win the limit
        few = c.get("/v1/dump?limit=5&windows=16").json()
        assert few["truncated"] is True and few["total"] == 16 and len(few["rows"]) == 5
        assert {r["row_id"] for r in few["rows"]} <= {r["row_id"] for r in d["rows"]}
        assert max(r["win"] for r in few["rows"]) == max(wins)
        assert c.get("/v1/dump?windows=1").json()["total"] == 0  # the open window only: nothing new in it
        for bad in ("limit=0", "limit=501", "windows=0", "windows=65", "limit=x"):
            assert c.get("/v1/dump?" + bad).status_code == 422, bad


def test_dump_of_the_baseline_is_the_arrival_order() -> None:
    with app_client("--mode", "baseline", "--window-s", "1", dev=True) as c:
        post_stored(c, "c" * 32, 10)
        d = c.get("/v1/dump?limit=500&windows=8").json()
    assert d["mode"] == "baseline" and d["total"] == 10
    assert [base64.b64decode(r["payload_b64"])[0] for r in d["rows"]] == list(range(10))
    ids = [int(r["row_id"]) for r in d["rows"]]
    assert ids == sorted(ids) and all(r["bucket"] is None and r["seq_enc_b64"] is None for r in d["rows"])
    assert {w["state"] for w in d["windows"]} == {"arrival"}
    # ISSUE-30 (2): the two columns this table holds in the clear
    assert {r["conv_hex"] for r in d["rows"]} == {conv_id_of("c" * 32).to_bytes(8, "little").hex()}
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d.*", r["ts"]) for r in d["rows"])
    assert [r["ts"] for r in d["rows"]] == sorted(r["ts"] for r in d["rows"])


# ── S5: the mode switch ──────────────────────────────────────────────────────
def test_mode_cannot_be_changed_without_dev_or_without_compare() -> None:
    with app_client(dev=False) as c:
        assert c.get("/v1/mode").json() == {"mode": "vcloak", "switchable": False}
        r = c.post("/v1/mode", json={"mode": "baseline"})
        assert r.status_code == 403 and r.json() == {"error": "dev_only"}
    with app_client("--compare", dev=False) as c:  # the backend alone does not open the route
        assert c.post("/v1/mode", json={"mode": "baseline"}).status_code == 403
        assert c.get("/v1/stats/live").json()["switchable"] is False
    for argv in ((), ("--mode", "baseline")):
        with app_client(*argv, dev=True) as c:
            r = c.post("/v1/mode", json={"mode": "baseline"})
            assert r.status_code == 409 and r.json() == {"error": "not_switchable"}
            assert c.get("/v1/mode").json() == {"mode": argv[-1] if argv else "vcloak", "switchable": False}
            assert c.get("/v1/stats/live").json()["switchable"] is False


def test_mode_switch_dumps_the_same_messages_both_ways() -> None:
    """S5: with --compare every message is in both stores; the mode says which one answers. The V-cloak
    dump of a closed window is not in arrival order, the baseline dump of the same messages is."""
    token = "d" * 32
    with app_client("--compare", "--epoch-ms", "50", "--window-s", "1", dev=True) as c:
        assert c.get("/v1/mode").json() == {"mode": "vcloak", "switchable": True}
        assert c.get("/v1/mode").headers["cache-control"] == "no-store"
        post_stored(c, token, 16)
        deadline = time.monotonic() + 20
        while True:
            cloak = c.get("/v1/dump?limit=500&windows=32").json()
            if cloak["total"] == 16 and all(w["state"] == "reshuffled" for w in cloak["windows"] if w["rows"]):
                break
            assert time.monotonic() < deadline, cloak["windows"]
            time.sleep(0.1)
        order = [base64.b64decode(r["payload_b64"])[0] for r in cloak["rows"]]
        assert cloak["mode"] == "vcloak" and sorted(order) == list(range(16)) and order != sorted(order)

        r = c.post("/v1/mode", json={"mode": "baseline"})
        assert r.status_code == 200 and r.json() == {"mode": "baseline", "switchable": True}
        live = c.get("/v1/stats/live").json()
        assert live["mode"] == "baseline" and live["slots"] is None and live["switchable"] is True
        assert c.get("/healthz").json()["mode"] == c.get("/v1/windows").json()["mode"] == "baseline"
        plain = c.get("/v1/dump?limit=500&windows=32").json()
        assert plain["mode"] == "baseline" and {w["state"] for w in plain["windows"]} == {"arrival"}
        assert [base64.b64decode(r["payload_b64"])[0] for r in plain["rows"]] == list(range(16))
        assert {r["payload_b64"] for r in plain["rows"]} == {r["payload_b64"] for r in cloak["rows"]}
        assert all(r["ts"] and r["conv_hex"] and r["bucket"] is None for r in plain["rows"])

        def read_all() -> list[int]:
            wins = sorted({r["win"] for r in plain["rows"]} | {r["win"] for r in cloak["rows"]})
            answers = [c.post("/v1/read", json={"conv_token": token, "win": w}).json() for w in wins]
            return [base64.b64decode(p)[0] for a in answers for p in a["payloads_b64"]]

        assert read_all() == list(range(16))  # the route reads the arrival-order table
        # a message sent in baseline mode is in the V-cloak store too
        payload = base64.b64encode(bytes([16]) * PAYLOAD_LEN).decode()
        body = {"conv_token": token, "payload_b64": payload, "ack": "stored"}
        assert c.post("/v1/messages", json=body).status_code == 201
        backend = c.app.state.backend  # type: ignore[attr-defined]
        assert sorted(r.payload[0] for r in backend.vcloak.repo.dump()) == list(range(17))
        assert [p[0] for _, _, p in backend.baseline.store.dump()] == list(range(17))

        assert c.post("/v1/mode", json={"mode": "vcloak"}).json()["mode"] == "vcloak"
        again = c.get("/v1/dump?limit=500&windows=32").json()
        assert again["mode"] == "vcloak" and again["total"] == 17
        assert read_all()[:16] == list(range(16))  # the same windows, read from the permuted store
        for bad in ({"mode": "plain"}, {}, {"mode": "vcloak", "x": 1}):
            assert c.post("/v1/mode", json=bad).status_code == 422, bad
        assert c.get("/v1/mode").json()["mode"] == "vcloak"


# ── A5: the files themselves ─────────────────────────────────────────────────
def web_sources() -> list[Path]:
    return sorted(p for p in WEB_DIR.rglob("*") if p.suffix in (".html", ".js", ".css"))


def test_the_shell_has_no_inline_script() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, flags=re.S)
    assert scripts
    for attrs, body in scripts:
        src = re.search(r'\bsrc="([^"]+)"', attrs)
        assert src and not body.strip(), "an inline script"
        assert not re.match(r"[a-z]+:|//", src.group(1)), "a script from another origin"
        assert "module" not in attrs  # classic scripts: the page must open from file:// (ADR-012)
    assert not re.search(r"<[^>]+\son[a-z]+\s*=", html), "an inline event handler"
    assert not re.search(r"javascript:", html, flags=re.I)
    for href in re.findall(r'<link\b[^>]*\bhref="([^"]+)"', html):
        assert href.startswith("data:") or not re.match(r"[a-z]+:|//", href), href


def test_the_page_asks_no_other_host() -> None:
    allowed = ("http://www.w3.org/",)  # XML namespace names: identifiers, never fetched
    for path in web_sources():
        for url in re.findall(r"""(?:https?:|wss?:)?//[A-Za-z0-9.-]+\.[a-z]{2,}[^\s"'<>)]*""",
                              path.read_text(encoding="utf-8")):
            assert url.startswith(allowed), f"{path.name}: {url}"


def test_no_script_evaluates_text() -> None:
    for path in web_sources():
        if path.suffix == ".js":
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"\beval\s*\(|new\s+Function\s*\(|document\.write", text), path.name


# ── the page in a browser ────────────────────────────────────────────────────
def session_config() -> SessionConfig:
    # a cheap password hash and no rate limit: tests only
    return SessionConfig(password=PasswordParams(t=1, m_kib=64, p=1), register_ip_max=10_000, login_ip_max=10_000)


@pytest.fixture(scope="module")
def server() -> Iterator[LocalServer]:
    with LocalServer(ARGV, config=session_config()) as s:
        yield s


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with Browser() as b:
        yield b


def open_app(browser: Browser, server: LocalServer) -> Page:
    page = browser.page(server.base + "/app/")
    # the panes exist once the page has asked the server how it runs: before that `ready()` is not the sign-in yet
    page.wait_for("document.readyState === 'complete' && !!(window.VC && VC.chat && VC.chat.panes.A)", timeout=20)
    assert page.evaluate("VC.chat.ready()") is True, page.evaluate(
        "['A','B'].map(u => document.getElementById('alert' + u).textContent)")
    return page


@pytest.fixture(scope="module")
def page(browser: Browser, server: LocalServer) -> Iterator[Page]:
    p = open_app(browser, server)
    yield p
    p.close()


def js(value: Any) -> str:
    return json.dumps(value)


def transcript(page: Page, user: str) -> list[dict[str, Any]]:
    return page.evaluate(f"VC.chat.transcript({js(user)})")


def wait_transcripts(page: Page, n: int) -> None:
    page.wait_for(f"VC.chat.transcript('A').length >= {n} && VC.chat.transcript('B').length >= {n}", timeout=30)


@needs_browser
def test_both_panes_sign_in_with_their_own_key(page: Page, server: LocalServer) -> None:
    """S2: two independent sessions in one page, each bound to a key of its own."""
    info = page.evaluate("""['A','B'].map(u => { const c = VC.chat.panes[u].client;
        return {name: c.username, jkt: c.device.jkt, token: c.conv.token, fp: c.conv.fingerprint,
                role: c.conv.role, label: document.getElementById('key' + u).textContent}; })""")
    a, b = info
    assert a["name"].startswith("alice_") and b["name"].startswith("bob_")
    assert a["jkt"] != b["jkt"] and len(a["jkt"]) == 43
    assert a["token"] == b["token"] and re.fullmatch(r"[A-Za-z0-9_-]{32}", a["token"])
    assert a["fp"] == b["fp"] and re.fullmatch(r"(\d{5} ){5}\d{5}", a["fp"])
    assert {a["role"], b["role"]} == {0, 1}
    assert a["name"] in a["label"] and a["jkt"][:6] in a["label"]
    assert a["name"] in server.sessions.accounts and b["name"] in server.sessions.accounts
    assert page.evaluate("VC.state.live && VC.state.dev && VC.state.sessions") is True
    assert page.evaluate("document.getElementById('conn').textContent") == "live · dev"
    assert "equal" in page.evaluate("document.getElementById('fingerprint').textContent")
    assert page.errors() == []  # no exception, no console error, nothing blocked by the CSP


@needs_browser
def test_the_private_keys_cannot_be_exported(page: Page) -> None:
    """A2: the device key and the prekey are handles; the browser refuses to give their bytes to script."""
    got = page.evaluate("""(async () => {
        const out = {};
        for (const u of ['A', 'B']) {
            const c = VC.chat.panes[u].client;
            for (const [name, key, formats] of [['device', c.device.privateKey, ['jwk', 'pkcs8']],
                                                ['prekey', c.prekey.privateKey, ['jwk', 'pkcs8', 'raw']]]) {
                out[u + name + ':extractable'] = key.extractable;
                for (const f of formats) {
                    out[u + name + ':' + f] = await crypto.subtle.exportKey(f, key).then(() => 'EXPORTED', e => e.name);
                }
            }
            const kept = await VC.crypto.stored('device:' + u);
            out[u + ':stored'] = kept.privateKey instanceof CryptoKey && kept.privateKey.extractable === false;
            out[u + ':content'] = await crypto.subtle.exportKey('raw', c.conv.key).then(() => 'EXPORTED', e => e.name);
        }
        out.persistent = await VC.crypto.persistent();
        return out; })()""")
    assert got.pop("persistent") is True  # the handles are in IndexedDB, not only in memory
    for name, value in got.items():
        if name.endswith(":extractable"):
            assert value is False, name
        elif name.endswith(":stored"):
            assert value is True, name
        else:
            assert value in ("InvalidAccessError", "NotSupportedError"), (name, value)


@needs_browser
def test_thirty_messages_two_users_exact_order(page: Page, server: LocalServer) -> None:
    """S3 and A1: 30 messages over at least two windows come back in the order they were sent, at both
    panes, and the store holds none of the text."""
    before = len(transcript(page, "A"))
    marker = uuid.uuid4().hex[:8]
    sent = []
    for i in range(30):
        user = "AB"[(i * 7 + i // 3) % 2]
        text = f"{marker} message {i:02d} from {user} · ünïcode ✓"
        number = page.evaluate(f"VC.chat.send({js(user)}, {js(text)})")
        sent.append((user, text, number))
    wait_transcripts(page, before + 30)
    names = page.evaluate("({A: VC.chat.panes.A.client.username, B: VC.chat.panes.B.client.username})")
    for pane in "AB":
        got = [m for m in transcript(page, pane) if m["text"].startswith(marker)]
        assert [m["text"] for m in got] == [text for _, text, _ in sent]
        assert [m["sender"] for m in got] == [names[user] for user, _, _ in sent]
        assert [m["number"] for m in got] == [number for _, _, number in sent]
        assert [m["mine"] for m in got] == [user == pane for user, _, _ in sent]
        assert len({m["win"] for m in got}) >= 2, "the round trip must cross a window boundary"
    for user in "AB":  # each sender's numbers are 0, 1, 2, ... without a hole
        numbers = [n for u, _, n in sent if u == user]
        assert numbers == list(range(numbers[0], numbers[0] + len(numbers)))
    assert page.evaluate("['A','B'].map(u => VC.chat.panes[u].alert + VC.chat.panes[u].halted).join('')") == ""
    assert page.evaluate("document.querySelectorAll('#msgsA .bub').length") >= 30

    # A1: what the server stored is ciphertext of one size; none of the text is in it
    rows = server.backend.repo.dump()
    assert len(rows) >= 30
    needles = [marker.encode(), b"message", "ünïcode".encode(), names["A"].encode(), names["B"].encode()]
    for row in rows:
        assert len(row.payload) == PAYLOAD_LEN
        blob = row.payload + row.seq_enc + row.row_id.bytes
        assert not any(n in blob for n in needles)
    assert page.errors() == []


@needs_browser
def test_the_server_view_shows_the_stored_rows_and_the_true_order(page: Page, server: LocalServer) -> None:
    """S4: the panel is the store in physical order; with the reveal switch each row carries the position
    of its message in the conversation, which the panes worked out themselves. In a closed window that
    order is not the order of sending."""
    marker = uuid.uuid4().hex[:8]
    texts = [f"{marker} row {i:02d}" for i in range(24)]
    for i, text in enumerate(texts):
        page.evaluate(f"VC.chat.send({js('AB'[i % 2])}, {js(text)})")
    page.wait_for(f"VC.chat.transcript('A').filter(m => m.text.startsWith({js(marker)})).length === 24", timeout=30)
    assert page.evaluate("document.getElementById('revealSwitch').disabled") is False
    assert page.evaluate("document.getElementById('modeSwitch').disabled") is True  # no --compare: nothing to switch
    assert page.evaluate("getComputedStyle(document.querySelector('th.clear-col')).display") == "none"
    assert page.evaluate("getComputedStyle(document.querySelector('th.reveal-col')).display") == "none"
    page.evaluate("document.getElementById('revealSwitch').click()")
    assert page.evaluate("getComputedStyle(document.querySelector('th.reveal-col')).display") == "table-cell"

    # every message of this test in a closed, re-shuffled window, and read by the panel
    mine = f"VC.chat.transcript('A').map((m, i) => [m, i + 1]).filter(x => x[0].text.startsWith({js(marker)}))"
    page.wait_for(f"""(() => {{ const want = new Set({mine}.map(x => x[1]));
        const got = VC.chat.serverView().rows.filter(r => want.has(r.n));
        return got.length === 24 && got.every(r => r.state === 'reshuffled'); }})()""", timeout=30)
    view = page.evaluate("VC.chat.serverView()")
    known = {n: m for m, n in page.evaluate(mine)}
    rows = [r for r in view["rows"] if r["n"] in known]
    assert view["mode"] == "vcloak" and len(rows) == 24

    # the panel is the store: the same rows in the same order
    stored = [r for w in view["windows"] for r in server.backend.repo.window_rows(w["win"])]
    assert [r["row_id"] for r in view["rows"]] == [str(r.row_id) for r in stored][-len(view["rows"]):]
    by_id = {str(r.row_id): r for r in stored}
    # the overlay is the client's sequence: row -> n -> the text sent as number n of the test
    assert [known[n]["text"] for n in sorted(known)] == texts
    for r in rows:
        m = known[r["n"]]
        assert base64.b64decode(m["stored"]) == by_id[r["row_id"]].payload
        assert r["who"] == "AB"[texts.index(m["text"]) % 2] and r["number"] == m["number"] and r["win"] == m["win"]
    # physical order against send order: the windows are in order, the rows inside them are not
    shown = [r["n"] for r in rows]
    assert [r["win"] for r in rows] == sorted(r["win"] for r in rows)
    assert shown != sorted(shown), "the stored order is the order of sending"
    assert max(sum(1 for r in rows if r["win"] == w) for w in {r["win"] for r in rows}) >= 6

    # what the audience sees: one table line per row, the truncated fields, the overlay
    table = page.evaluate("""Array.from(document.querySelectorAll('#dumpBody tr')).map(tr =>
        Array.from(tr.cells).map(td => td.textContent))""")
    assert len(table) == len(view["rows"])
    for line, r in zip(table, view["rows"], strict=True):
        assert line[1] == r["row_id"][:8] + "…" and line[5].startswith(str(r["win"]))
        assert line[2] == line[3] == "—"  # ts, conv: columns of the baseline table, hidden here
        assert re.fullmatch(r"[0-9a-f]{8}…[0-9a-f]{4} \(44 B\)", line[6])
        assert re.fullmatch(rf"[0-9a-f]{{8}}…[0-9a-f]{{4}} \({PAYLOAD_LEN} B\)", line[7])
        assert line[8] == (f"#{r['n']} {r['who']}" if r["n"] else "—")
    note = page.evaluate("document.getElementById('serverNote').textContent")
    assert "the server did not supply it" in note and "number of rows per window" in note
    assert marker not in json.dumps(table)
    page.evaluate("document.getElementById('revealSwitch').click()")
    assert page.evaluate("getComputedStyle(document.querySelector('th.reveal-col')).display") == "none"
    assert page.errors() == []


@needs_browser
def test_the_mode_switch_shows_the_same_conversation_both_ways(browser: Browser) -> None:
    """S5: on `serve --dev --compare` the switch exchanges the store that answers and the panel repaints.
    With the true order revealed, the baseline rows are in the order of sending and the V-cloak rows of a
    closed window are not; the panes go on reading across the switch without a gap or a repeat."""
    with LocalServer([*ARGV, "--compare"], config=session_config()) as srv:
        page = open_app(browser, srv)
        try:
            switch = "document.getElementById('modeSwitch')"

            def shown_as(cls: str) -> str:
                return str(page.evaluate(f"getComputedStyle(document.querySelector('th.{cls}')).display"))

            def note() -> str:
                return str(page.evaluate("document.getElementById('serverNote').textContent"))

            assert page.evaluate("VC.state.switchable") is True and page.evaluate(switch + ".disabled") is False
            texts = [f"cmp {i:02d}" for i in range(24)]
            for i, text in enumerate(texts):
                page.evaluate(f"VC.chat.send({js('AB'[i % 2])}, {js(text)})")
            wait_transcripts(page, 24)
            page.evaluate("document.getElementById('revealSwitch').click()")
            page.wait_for("""(() => { const got = VC.chat.serverView().rows.filter(r => r.n);
                return got.length === 24 && got.every(r => r.state === 'reshuffled'); })()""", timeout=30)
            cloak = page.evaluate("VC.chat.serverView()")
            shown = [r["n"] for r in cloak["rows"]]
            assert cloak["mode"] == "vcloak" and sorted(shown) == list(range(1, 25))
            assert shown != sorted(shown), "the V-cloak rows are in the order of sending"
            assert all(r["ts"] is None and r["conv"] is None for r in cloak["rows"])
            assert shown_as("clear-col") == "none" and shown_as("cloak-col") == "table-cell"
            assert "--compare" in note()

            # the switch: the same 24 messages, now in the order they were sent, with a time and a conversation id
            page.evaluate(switch + ".click()")
            page.wait_for("(v => v.mode === 'baseline' && v.rows.length === 24)(VC.chat.serverView())", timeout=20)
            plain = page.evaluate("VC.chat.serverView()")
            assert [r["n"] for r in plain["rows"]] == list(range(1, 25)), "the baseline rows are not in send order"
            assert {r["payload_b64"] for r in plain["rows"]} == {r["payload_b64"] for r in cloak["rows"]}
            assert [int(r["row_id"]) for r in plain["rows"]] == sorted(int(r["row_id"]) for r in plain["rows"])
            assert len({r["conv"] for r in plain["rows"]}) == 1 and all(r["ts"] for r in plain["rows"])
            assert page.evaluate(switch + ".checked") is True and page.evaluate("VC.state.mode") == "baseline"
            assert page.evaluate("document.getElementById('ls-mode').textContent") == "baseline"
            assert shown_as("clear-col") == "table-cell" and shown_as("cloak-col") == "none"
            assert "Unprotected baseline" in note() and "who is in a conversation with whom" in note()
            assert "--compare" in note()
            table = page.evaluate("""Array.from(document.querySelectorAll('#dumpBody tr')).map(tr =>
                Array.from(tr.cells).map(td => td.textContent))""")
            assert [line[8] for line in table] == [f"#{i + 1} {'AB'[i % 2]}" for i in range(24)]
            for line, r in zip(table, plain["rows"], strict=True):
                assert line[2] == r["ts"] and line[3] == r["conv"]
            mode = page.evaluate("VC.api.raw('GET', '/v1/mode').then(r => r.body)")
            assert mode == {"mode": "baseline", "switchable": True}

            # the panes read on from the other store: nothing twice, nothing missing, and they still send
            more = [f"cmp base {i}" for i in range(6)]
            for i, text in enumerate(more):
                page.evaluate(f"VC.chat.send({js('AB'[i % 2])}, {js(text)})")
            wait_transcripts(page, 30)
            for user in "AB":
                assert [m["text"] for m in transcript(page, user)] == texts + more
            page.wait_for("VC.chat.serverView().rows.length === 30", timeout=20)
            assert [r["n"] for r in page.evaluate("VC.chat.serverView()")["rows"]] == list(range(1, 31))

            # and back: the six messages sent in baseline mode are in the V-cloak store as well
            page.evaluate(switch + ".click()")
            page.wait_for("""(() => { const v = VC.chat.serverView(); const got = v.rows.filter(r => r.n);
                return v.mode === 'vcloak' && got.length === 30 && got.every(r => r.state === 'reshuffled'); })()""",
                          timeout=30)
            back = [r["n"] for r in page.evaluate("VC.chat.serverView()")["rows"]]
            assert sorted(back) == list(range(1, 31)) and back != sorted(back)
            assert page.evaluate(switch + ".checked") is False
            for text in ("cmp after A", "cmp after B"):
                page.evaluate(f"VC.chat.send({js(text[-1])}, {js(text)})")
            wait_transcripts(page, 32)
            assert [m["text"] for m in transcript(page, "B")] == texts + more + ["cmp after A", "cmp after B"]
            panes = page.evaluate("['A','B'].map(u => [VC.chat.panes[u].halted, VC.chat.panes[u].alert])")
            assert panes == [["", ""], ["", ""]]
            assert len(srv.backend.vcloak.repo.dump()) == len(srv.backend.baseline.store.dump()) == 32
            assert page.errors() == []
        finally:
            page.close()


@needs_browser
def test_the_page_says_when_the_mode_cannot_be_changed(browser: Browser, server: LocalServer) -> None:
    """A server without --compare refuses the switch: the page keeps its mode and says so."""
    page = open_app(browser, server)
    try:
        page.evaluate("VC.chat.setMode('baseline')")
        page.wait_for("document.getElementById('serverNote').textContent.includes('was not changed')", timeout=20)
        assert "409 not_switchable" in page.evaluate("document.getElementById('serverNote').textContent")
        assert page.evaluate("[VC.state.mode, document.getElementById('modeSwitch').checked]") == ["vcloak", False]
        assert page.evaluate("VC.chat.serverView().mode") == "vcloak"
    finally:
        page.close()


@needs_browser
def test_without_dev_the_page_has_no_rows_and_no_reveal(browser: Browser) -> None:
    """A3: a server that is not in dev mode gives the page no stored rows, and the reveal switch stays off."""
    with LocalServer(ARGV, config=session_config(), dev=False) as plain:
        page = open_app(browser, plain)
        try:
            assert page.evaluate("VC.state.live && !VC.state.dev") is True
            assert page.evaluate("document.getElementById('conn').textContent") == "live"
            assert page.evaluate("VC.chat.send('A', 'no rows for the page')") >= 0
            page.wait_for("VC.chat.transcript('B').some(m => m.text === 'no rows for the page')", timeout=20)
            page.evaluate("VC.chat.refreshDump()")
            assert page.evaluate("document.getElementById('revealSwitch').disabled") is True
            assert page.evaluate("document.getElementById('modeSwitch').disabled") is True
            assert page.evaluate("document.querySelectorAll('#dumpBody tr').length") == 0
            assert page.evaluate("VC.chat.serverView().rows.length") == 0
            assert "--dev only" in page.evaluate("document.getElementById('serverNote').textContent")
            assert page.errors() == []  # the page never asked for the rows
            status = page.evaluate("VC.api.raw('GET', '/v1/dump?limit=5').then(r => [r.status, r.body.error])")
            assert status == [403, "dev_only"]
        finally:
            page.close()


@needs_browser
def test_refresh_rotates_and_the_session_goes_on(browser: Browser, server: LocalServer) -> None:
    """S2: the refresh token is single use; after a rotation the pane still sends and reads, and the
    spent token is refused."""
    page = open_app(browser, server)
    try:
        got = page.evaluate("""(async () => {
            const c = VC.chat.panes.A.client, old = {access: c._access, refresh: c._refresh};
            await c.refresh();
            const n = await VC.chat.send('A', 'after the refresh');
            return {rotated: c._refresh !== old.refresh && c.refreshes === 1, n: n, old: old.refresh}; })()""")
        assert got["rotated"] is True and got["n"] == 0
        page.wait_for("VC.chat.transcript('B').some(m => m.text === 'after the refresh')", timeout=20)
        # the spent token again: refused, and the reuse revokes the login (docs/API.md)
        reuse = page.evaluate(f"""(async () => {{
            const c = VC.chat.panes.A.client;
            const h = await c._headers('POST', '/v1/auth/refresh', false);
            const r = await VC.api.raw('POST', '/v1/auth/refresh', {{refresh_token: {js(got["old"])}}}, h);
            return [r.status, r.body.reason]; }})()""")
        assert reuse == [401, "reuse"]
    finally:
        page.close()


@needs_browser
def test_a_pane_talks_to_the_python_sdk(browser: Browser, server: LocalServer) -> None:
    """The browser client and vcloak.client.sdk agree byte for byte: same token, same fingerprint, and
    each reads and verifies what the other wrote."""
    page = open_app(browser, server)
    try:
        carol_name, tina_name = f"carol_{uuid.uuid4().hex[:8]}", f"tina_{uuid.uuid4().hex[:8]}"
        carol = sign_in(server.base, carol_name)
        tina = page.evaluate(f"""(async () => {{
            const c = new VC.Client('T-' + {js(tina_name)});
            await c.init();
            await c.signIn({js(tina_name)}, {js(uuid.uuid4().hex)});
            await c.start({js(carol_name)}, VC.state.payloadLen);
            window.tina = c;
            return {{token: c.conv.token, fp: c.conv.fingerprint, role: c.conv.role, win: c.conv.firstWin}}; }})()""")
        conv = carol.start_conversation(tina_name, first_win=tina["win"])
        assert conv.conv_token == tina["token"]
        assert conv.fingerprint == tina["fp"]
        assert {conv.role, tina["role"]} == {0, 1}

        assert page.evaluate("tina.send('from the browser: héllo ✓')") == 0
        assert carol.send("from python: grüße") == 0
        assert page.evaluate("tina.send('second from the browser')") == 1
        got = [(m.sender, m.number, m.text) for m in carol.sync()]
        assert got == [(tina_name, 0, "from the browser: héllo ✓"), (carol_name, 0, "from python: grüße"),
                       (tina_name, 1, "second from the browser")]
        seen = page.evaluate("tina.sync().then(ms => ms.map(m => [m.sender, m.number, m.text, m.mine]))")
        assert seen == [[tina_name, 0, "from the browser: héllo ✓", True], [carol_name, 0, "from python: grüße", False],
                        [tina_name, 1, "second from the browser", True]]
        carol.conversation.verify_delivered()
        carol.close()
        assert page.errors() == []
    finally:
        page.close()


@needs_browser
def test_a_withheld_message_is_flagged_in_the_pane(browser: Browser, server: LocalServer) -> None:
    """S3: when the server leaves a message out, the reader's pane says so and shows nothing after it."""
    page = open_app(browser, server)
    try:
        # B has to know where A's session stands: a reader cannot miss what came before the first
        # message it ever saw of a session (docs/API.md)
        assert page.evaluate("VC.chat.send('A', 'the first one')") == 0
        page.wait_for("VC.chat.transcript('B').some(m => m.text === 'the first one')", timeout=20)
        # from here on, a server that withholds from B the next message A sends. The message is known by its
        # ciphertext, not by its place: a pane fetches its windows newest first, so "the first new payload B
        # is handed" is the LAST message when the two fall into different windows, and a missing last message
        # cannot be noticed yet (ISSUE-31 point 1)
        page.evaluate("""(() => {
            const a = VC.chat.panes.A.client, post = a._postStored.bind(a);
            let withheld = null;
            a._postStored = payload => { withheld = withheld || payload; return post(payload); };
            const c = VC.chat.panes.B.client, fetch = c._fetch.bind(c);
            const same = (x, y) => x.length === y.length && x.every((v, i) => v === y[i]);
            c._fetch = win => fetch(win).then(payloads => payloads.filter(p => !(withheld && same(p, withheld))));
            return true; })()""")
        assert page.evaluate("VC.chat.send('A', 'the withheld one')") == 1
        assert page.evaluate("VC.chat.send('A', 'the one after it')") == 2
        page.wait_for("!document.getElementById('alertB').hidden", timeout=20)
        alert = page.evaluate("document.getElementById('alertB').textContent")
        assert alert.startswith("Order check failed") and "missing or out of order" in alert
        shown = [m["text"] for m in transcript(page, "B")]
        assert "the first one" in shown and "the withheld one" not in shown and "the one after it" not in shown
        assert page.evaluate("document.querySelectorAll('#msgsB .bub.gap').length") == 1
        # the sender reads its own messages back and is not affected
        page.wait_for("VC.chat.transcript('A').some(m => m.text === 'the one after it')", timeout=20)
        assert page.evaluate("document.getElementById('alertA').hidden") is True
    finally:
        page.close()


@contextmanager
def serving(app: Any) -> Iterator[str]:
    """`app` on a loopback port, in a thread; yields its origin."""
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_config=None,
                                        log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not srv.started:
        assert thread.is_alive() and time.monotonic() < deadline, "the server did not start"
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.should_exit = True
        thread.join(timeout=30)


@needs_browser
def test_without_sessions_the_page_says_how_to_start_the_server(browser: Browser) -> None:
    a = build_parser().parse_args(["serve", "--dev", "--store", "sqlite"])
    with serving(create_app(build_backend(a), dev=True)) as base:
        page = browser.page(base + "/app/")
        try:
            page.wait_for("document.readyState === 'complete' && !!(window.VC && VC.chat && VC.chat.ready)")
            assert page.evaluate("VC.chat.ready()") is False
            assert "--sessions" in page.evaluate("document.getElementById('alertA').textContent")
            assert page.evaluate("document.querySelector('#formA button').disabled") is True
            assert page.evaluate("document.getElementById('dumpBody').children.length") == 0  # never demo rows
        finally:
            page.close()
