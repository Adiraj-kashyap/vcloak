"""M12: two SDK clients against the real service over HTTP (audit A1-A3).

The service is `vcloak serve --dev --sessions` inside the test process (scripts/demo_two_users.py:
uvicorn on a loopback port, wall clock, short windows), so the SDK's proofs, tokens and sockets are
checked by the server's own verification, which shares no code with the client. The store is SQLite in
memory; the PostgreSQL run is marked `integration` and is skipped when no database answers.
Nothing here measures anything: the engine is the numpy simulator.
"""
from __future__ import annotations

import io
import json
import os
import re
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from demo_two_users import LocalServer, run_demo, sign_in, wait_closed
from vcloak.client import cli
from vcloak.client.sdk import ApiError, NotLoggedIn, SequenceError, TamperError, VcloakClient
from vcloak.crypto.client import PAYLOAD_LEN
from vcloak.service.session import PasswordParams, SessionConfig

EPOCH_MS = 100
ARGV = ["--dev", "--sessions", "--store", "sqlite", "--window-s", "1", "--epoch-ms", str(EPOCH_MS)]


def config() -> SessionConfig:
    # a cheap password hash and no registration limit: tests only
    return SessionConfig(password=PasswordParams(t=1, m_kib=64, p=1), register_ip_max=10_000, login_ip_max=10_000)


@pytest.fixture(scope="module")
def server() -> Iterator[LocalServer]:
    with LocalServer(ARGV, config=config()) as s:
        yield s


def name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def pair(base: str, **kw: Any) -> tuple[VcloakClient, VcloakClient]:
    """Two signed-in clients in one conversation. `kw` goes to the second client's constructor."""
    a_name, b_name = name("alice"), name("bob")
    alice = sign_in(base, a_name)
    bob = VcloakClient(base, **kw)
    password = os.urandom(16).hex()
    bob.register(b_name, password)
    bob.login(b_name, password)
    bob.publish_prekey()
    conv = alice.start_conversation(b_name)
    bob.start_conversation(a_name, first_win=conv.first_win)
    return alice, bob


# ── A1 ───────────────────────────────────────────────────────────────────────

def check_demo(result: dict[str, Any]) -> None:
    failed = [k for k, held in result["checks"].items() if not held]
    assert not failed, failed
    assert len(result["sent"]) == 30 and len(result["windows"]) >= 2
    for view in result["views"].values():
        assert [(m.sender, m.text) for m in view] == result["sent"]  # exact, in order, at both ends
    assert result["repeats"] == 0


def test_a1_two_users_exchange_30_messages_across_windows_in_order() -> None:
    check_demo(run_demo("sqlite", 30, 1, EPOCH_MS, seed=1, config=config()))


@pytest.mark.integration
def test_a1_two_users_on_postgresql() -> None:
    psycopg = pytest.importorskip("psycopg")
    from vcloak.storage import pgconf

    try:
        with psycopg.connect(pgconf.default_dsn()) as c:
            c.execute("SELECT 1")
    except psycopg.OperationalError:
        pytest.skip("no PostgreSQL at the configured DSN: run `docker compose up -d --wait db`")
    check_demo(run_demo("pg", 30, 1, EPOCH_MS, seed=2, config=config()))


# ── A2 ───────────────────────────────────────────────────────────────────────

def test_a2_the_server_never_receives_or_stores_plaintext() -> None:
    texts = ["meet me at the old bridge", "bring the blue folder", "ZEBRA-7741-QUARTZ",
             "understood, at half past seven"]
    seen: list[bytes] = []

    def record(request: httpx.Request) -> None:
        headers = b" ".join(k + b"=" + v for k, v in request.headers.raw)
        seen.append(request.url.raw_path + b" " + headers + b" " + request.content)

    srv = LocalServer(ARGV, config=config())
    with srv:
        hooks = {"request": [record]}
        a_name, b_name = name("alice"), name("bob")
        clients = []
        for who in (a_name, b_name):
            c = VcloakClient(srv.base, http=httpx.Client(timeout=15.0, event_hooks=hooks))
            password = os.urandom(16).hex()
            c.register(who, password)
            c.login(who, password)
            c.publish_prekey()
            clients.append(c)
        alice, bob = clients
        seen.clear()  # from here on: the conversation (the password was sent at login, by design)
        conv = alice.start_conversation(b_name)
        bob.start_conversation(a_name, first_win=conv.first_win)
        for i, text in enumerate(texts):
            (alice if i % 2 == 0 else bob).send(text)
        assert [m.text for m in bob.sync()] == texts
        key, token = conv._k, conv.conv_token
    rows = srv.backend.repo.dump()  # after the stop: everything the service made durable
    srv.backend.repo.close()

    wire = b"\n".join(seen)
    assert len(rows) == len(texts)
    stored = b"".join(bytes(r.payload) + bytes(r.seq_enc) + r.row_id.bytes for r in rows)
    for text in texts:
        for needle in (text.encode(), text.encode().hex().encode(), text[:8].encode()):
            assert needle not in wire and needle not in stored
    for secret in (key, key.hex().encode()):
        assert secret not in wire and secret not in stored
    assert token.encode() in wire and token.encode() not in stored  # the token is sent, never stored
    assert {len(r.payload) for r in rows} == {PAYLOAD_LEN}
    bodies = [json.loads(s[s.index(b"{"):]) for s in seen if s.startswith(b"/v1/messages")]
    assert bodies and all(set(b) == {"conv_token", "payload_b64", "ack"} and b["ack"] == "stored" for b in bodies)
    # and the rows are ciphertexts of this conversation: only the clients' key opens them
    assert sorted(conv.open(bytes(r.payload))[3] for r in rows) == sorted(texts)


# ── A3 ───────────────────────────────────────────────────────────────────────

class TamperingTransport(httpx.BaseTransport):
    """The real server behind a middlebox that rewrites the answers to POST /v1/read."""

    def __init__(self) -> None:
        self._inner = httpx.HTTPTransport()
        self.fn: Callable[[list[str]], list[str]] | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        if request.url.path != "/v1/read" or self.fn is None or response.status_code != 200:
            return response
        body = json.loads(response.read())
        response.close()
        body["payloads_b64"] = self.fn(body["payloads_b64"])
        return httpx.Response(200, json=body)


@pytest.mark.parametrize("what, fn, error", [
    ("reordered", lambda p: p[:1] + p[1:3][::-1] + p[3:] if len(p) >= 3 else p[::-1], SequenceError),
    ("missing", lambda p: p[1:], SequenceError),
    ("forged", lambda p: [p[0][:8] + ("B" if p[0][8] != "B" else "C") + p[0][9:], *p[1:]] if p else p,
     TamperError),
])
def test_a3_a_tampered_answer_of_the_real_server_is_detected(server: LocalServer, what: str,
                                                             fn: Callable[[list[str]], list[str]],
                                                             error: type[Exception]) -> None:
    transport = TamperingTransport()
    alice, bob = pair(server.base, transport=transport)
    for i in range(6):
        alice.send(f"message {i}")
    last = int(alice.windows()["win"])
    wait_closed(alice, last, EPOCH_MS)  # every message is in a closed, re-shuffled window
    assert [m.text for m in alice.sync()] == [f"message {i}" for i in range(6)]  # the honest answer
    transport.fn = fn
    with pytest.raises(error):
        bob.sync()


# ── the SDK against the server's session layer ───────────────────────────────

def test_refresh_logout_and_the_push_socket(server: LocalServer) -> None:
    alice, bob = pair(server.base)
    alice.send("before the refresh")
    old, spent = alice.dpop_headers("POST", "/v1/read")["Authorization"], alice._refresh
    alice.refresh()
    # the refresh token rotates (an access token issued in the same second for the same login is the same)
    assert alice._refresh and alice._refresh != spent
    alice.send("after the refresh")
    frames = bob.ticks(3)
    assert [f["type"] for f in frames] == ["ready", "tick", "tick", "tick"]
    assert all(set(f) == {"type", "win"} for f in frames)  # the same frame for everybody: no message count
    assert [m.text for m in bob.sync()] == ["before the refresh", "after the refresh"]
    alice.logout()
    with pytest.raises(NotLoggedIn):
        alice.send("after the logout")
    # the old token is dead on the server too, not only forgotten by the client
    r = httpx.post(server.base + "/v1/read", json={"conv_token": "x" * 32, "win": 0},
                   headers={"Authorization": old, "DPoP": alice.device.proof("POST", server.base + "/v1/read",
                                                                             old.removeprefix("DPoP "))})
    assert r.status_code == 401 and r.json()["failed_check"] == "token_revoked"


def test_wrong_password_and_another_devices_token(server: LocalServer) -> None:
    alice, bob = pair(server.base)
    intruder = VcloakClient(server.base)
    with pytest.raises(ApiError) as e:
        intruder.login(alice.username, "not the password")
    assert (e.value.status, e.value.error) == (401, "invalid_credentials") and not intruder.logged_in
    # a stolen access token is useless under another device's key
    intruder._access = alice._access
    r = intruder.authed("POST", "/v1/read", {"conv_token": "x" * 32, "win": 0})
    assert r.status_code == 401 and r.json()["failed_check"] == "key_binding"


def test_a_message_stored_twice_is_read_once(server: LocalServer) -> None:
    alice, bob = pair(server.base)
    conv = alice.conversation
    assert conv is not None
    alice.send("once")
    conv._post_stored(conv.seal("twice", 1))  # a retry after an unknown outcome: the server keeps both
    conv._pending = conv.seal("twice", 1)
    conv.flush()
    alice.send("thrice")
    assert [m.text for m in bob.sync()] == ["once", "twice", "thrice"]
    assert bob.conversation is not None and bob.conversation.repeats == 1


# ── the command ──────────────────────────────────────────────────────────────

def test_vcloak_chat_sends_and_prints_and_keeps_its_keys_sealed(server: LocalServer, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    a_name, b_name = name("alice"), name("bob")
    bob = sign_in(server.base, b_name)
    keyfile = tmp_path / "alice.key"
    argv = ["--server", server.base, "--user", a_name, "--peer", b_name, "--keyfile", str(keyfile), "--poll", "0.1"]

    def chat(lines: str, *extra: str) -> tuple[int, str]:
        monkeypatch.setenv(cli.PASSWORD_ENV, "a password for alice")
        monkeypatch.setenv(cli.PASSPHRASE_ENV, "a passphrase for the key file")
        out = io.StringIO()
        code = cli.main([*argv, *extra], stdin=io.StringIO(lines), stdout=out,
                        ask=lambda prompt: pytest.fail("the secrets come from the environment"))
        assert cli.PASSWORD_ENV not in os.environ and cli.PASSPHRASE_ENV not in os.environ  # read once, removed
        return code, out.getvalue()

    code, text = chat("hello bob\n\nsecond line\n/quit\nnever sent\n", "--register")
    assert code == 0, text
    fingerprint = re.search(r"Fingerprint \(compare it with your peer\): ([\d ]+)", text)
    assert fingerprint is not None
    conv = bob.start_conversation(a_name, first_win=int(bob.windows()["win"]) - 3, strict_start=False)
    assert [m.text for m in bob.sync()] == ["hello bob", "second line"]
    assert conv.fingerprint == fingerprint.group(1).strip()  # what the two would compare
    blob = keyfile.read_bytes()
    assert blob[:8] == b"VCLKDEV1" and b"passphrase" not in blob and b"password" not in blob

    bob.send("hello alice")
    code, text = chat("/quit\n")  # a second run: the same keys from the file, so the same conversation
    assert code == 0 and f"<{b_name}> hello alice" in text
    assert fingerprint.group(1).strip() in text

    monkeypatch.setenv(cli.PASSPHRASE_ENV, "not the passphrase")
    assert cli.main(argv, stdin=io.StringIO(""), stdout=io.StringIO()) == 2
