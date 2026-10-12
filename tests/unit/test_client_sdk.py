"""M12 S1-S3: the client SDK against a scripted fake server (httpx.MockTransport) and a fake clock.

The fake keeps what a real server keeps (ciphertexts per token and window) and can be told to fail a
submission, to expire a token or to return a tampered read (A3). The SDK against the real service is
tests/integration/test_two_users.py. Nothing here measures anything.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from dpop_client import FakeTime, decode_segment
from vcloak.client import sdk
from vcloak.client.device import DeviceKey, load_keyfile, public_bytes, save_keyfile
from vcloak.client.sdk import (
    HEADER,
    MAX_TEXT_BYTES,
    ApiError,
    ClientError,
    NotLoggedIn,
    SendUnconfirmed,
    SeqChecker,
    SequenceError,
    TamperError,
    VcloakClient,
)
from vcloak.config import BLOCK
from vcloak.crypto.client import PAYLOAD_LEN, derive_conv_token
from vcloak.crypto.keys import Argon2Params, UnsealError
from vcloak.service.models import TOKEN_PATTERN
from vcloak.service.session import PREKEY_PATTERN, jwk_thumbprint

BASE = "http://fake.test"
CHEAP = Argon2Params(t=1, m_kib=64, p=1)  # tests only
PASSWORD = "correct horse battery"


# ── the device key and its file ──────────────────────────────────────────────

def ub64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def test_a_proof_is_an_rfc_9449_jws_signed_by_the_device_key() -> None:
    clock = FakeTime()
    dev = DeviceKey(now=clock)
    proof = dev.proof("POST", BASE + "/v1/messages", "the-token")
    h, c, sig = proof.split(".")
    header, claims = decode_segment(h), decode_segment(c)
    assert header == {"typ": "dpop+jwt", "alg": "ES256", "jwk": dev.jwk}
    assert set(dev.jwk) == {"kty", "crv", "x", "y"}  # never a private member
    assert claims["htm"] == "POST" and claims["htu"] == BASE + "/v1/messages" and claims["iat"] == int(clock.t)
    assert claims["ath"] == base64.urlsafe_b64encode(hashlib.sha256(b"the-token").digest()).rstrip(b"=").decode()
    assert re.fullmatch(r"[A-Za-z0-9_-]{22}", claims["jti"])
    raw = ub64(sig)
    assert len(raw) == 64
    public = ec.EllipticCurvePublicNumbers(int.from_bytes(ub64(dev.jwk["x"]), "big"),
                                           int.from_bytes(ub64(dev.jwk["y"]), "big"), ec.SECP256R1()).public_key()
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, f"{h}.{c}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if it does not verify
    assert "ath" not in decode_segment(dev.proof("POST", BASE + "/v1/auth/login").split(".")[1])
    assert dev.thumbprint == jwk_thumbprint(dev.jwk)  # the server's RFC 7638 implementation agrees


def test_every_proof_is_fresh() -> None:
    dev = DeviceKey()
    proofs = [dev.proof("POST", BASE + "/x", "t") for _ in range(20)]
    assert len({decode_segment(p.split(".")[1])["jti"] for p in proofs}) == 20


def test_keyfile_round_trip_and_what_is_on_disk(tmp_path: Path) -> None:
    dev, prekey = DeviceKey(), X25519PrivateKey.generate()
    path = save_keyfile(tmp_path / "device.key", "a passphrase", dev, prekey, params=CHEAP)
    blob = path.read_bytes()
    assert blob[:8] == b"VCLKDEV1" and len(blob) == 8 + 12 + 16 + 12 + 64 + 16
    assert dev._scalar() not in blob  # the private keys are on disk only sealed
    assert prekey.private_bytes_raw() not in blob and b"a passphrase" not in blob
    assert not (tmp_path / "device.key.tmp").exists()
    dev2, prekey2 = load_keyfile(path, "a passphrase")
    assert dev2.jwk == dev.jwk and dev2.thumbprint == dev.thumbprint
    assert public_bytes(prekey2) == public_bytes(prekey)


def test_keyfile_refuses_a_wrong_passphrase_and_a_changed_file(tmp_path: Path) -> None:
    path = save_keyfile(tmp_path / "device.key", "right", DeviceKey(), X25519PrivateKey.generate(), params=CHEAP)
    with pytest.raises(UnsealError) as e:
        load_keyfile(path, "wrong")
    assert "right" not in str(e.value) and "wrong passphrase" in str(e.value)
    blob = bytearray(path.read_bytes())
    for index in (9, 30, 50, len(blob) - 1):  # a parameter, the salt, the ciphertext, the tag
        changed = bytearray(blob)
        changed[index] ^= 1
        path.write_bytes(changed)
        with pytest.raises(UnsealError):
            load_keyfile(path, "right")
    path.write_bytes(blob[:-1])
    with pytest.raises(UnsealError):
        load_keyfile(path, "right")
    with pytest.raises(ValueError):
        save_keyfile(tmp_path / "x.key", "", DeviceKey(), X25519PrivateKey.generate(), params=CHEAP)


# ── the continuity rule ──────────────────────────────────────────────────────

def test_seq_checker_accepts_the_next_number_and_drops_repeats() -> None:
    c, s = SeqChecker(), b"s" * 8
    assert [c.accept(0, s, n) for n in (0, 1, 1, 0, 2, 2)] == [True, True, False, False, True, False]
    assert c.next(0, s) == 3 and c.next(1, s) == 0
    assert c.accept(1, s, 0) and c.accept(0, b"t" * 8, 0)  # the other sender, another session: own counters


@pytest.mark.parametrize("numbers", [(0, 2), (1,), (0, 1, 3), (0, 2, 1), (5, 0)])
def test_seq_checker_raises_on_a_gap_or_a_reordering(numbers: tuple[int, ...]) -> None:
    c = SeqChecker()
    with pytest.raises(SequenceError):
        for n in numbers:
            c.accept(0, b"s" * 8, n)


def test_seq_checker_without_a_strict_start_takes_the_first_number_as_given() -> None:
    c = SeqChecker(strict_start=False)
    assert c.accept(0, b"s" * 8, 7) and c.accept(0, b"s" * 8, 8)
    assert not c.accept(0, b"s" * 8, 7)  # a repeat of what it accepted
    with pytest.raises(SequenceError):
        c.accept(0, b"s" * 8, 10)
    with pytest.raises(SequenceError):
        c.accept(0, b"s" * 8, 3)  # older than its start, after its start: the server moved it


# ── a fake server ────────────────────────────────────────────────────────────

class FakeServer:
    """What the SDK talks to in this file. It checks nothing of a proof (the real server does, in the
    integration test); it records every request and can be scripted."""

    def __init__(self, clock: FakeTime) -> None:
        self.clock = clock
        self.win = 100
        self.store: dict[str, list[tuple[int, str]]] = {}  # conv_token -> [(win, payload_b64)] in arrival order
        self.prekeys: dict[str, str] = {}
        self.tokens: dict[str, str] = {}  # access token -> account
        self.refresh_tokens: dict[str, str] = {}
        self.script: list[Any] = []  # answers for the next POST /v1/messages: an int status or "drop"/"lost"
        self.expire_next = 0  # the next n authenticated requests answer 401 token_exp
        self.tamper: Callable[[int, list[str]], list[str]] | None = None
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self.handle)
        self.issued = 0

    def _tokens(self, user: str) -> httpx.Response:
        self.issued += 1
        access, refresh = f"access-{self.issued}-{os.urandom(4).hex()}", f"refresh-{self.issued}-{os.urandom(4).hex()}"
        self.tokens[access], self.refresh_tokens[refresh] = user, user
        return httpx.Response(200, json={"access_token": access, "refresh_token": refresh, "expires_in": 600,
                                         "token_type": "DPoP"})

    def _user(self, request: httpx.Request) -> str | None:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        return self.tokens.get(token) if scheme == "DPoP" and "dpop" in request.headers else None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, body = request.url.path, json.loads(request.content) if request.content else None
        if path == "/v1/windows":
            return httpx.Response(200, json={"win": self.win, "window_s": 60, "epoch_ms": 200,
                                             "visible_round": "window", "mode": "vcloak"})
        if path == "/v1/auth/register":
            return httpx.Response(201, json={"registered": True})
        if path == "/v1/auth/login":
            return self._tokens(body["username"])
        if path == "/v1/auth/refresh":
            user = self.refresh_tokens.pop(body["refresh_token"], None)
            if user is None:
                return httpx.Response(401, json={"error": "invalid_grant", "reason": "reuse"})
            return self._tokens(user)
        if path.startswith("/v1/prekeys/"):
            name = path.rsplit("/", 1)[1]
            if name not in self.prekeys:
                return httpx.Response(404, json={"error": "no_prekey"})
            return httpx.Response(200, json={"username": name, "prekey_b64": self.prekeys[name]})
        user = self._user(request)
        if user is None:
            return httpx.Response(401, json={"error": "invalid_dpop_proof", "failed_check": "proof_format"})
        if self.expire_next:
            self.expire_next -= 1
            del self.tokens[request.headers["authorization"].split(" ")[1]]
            return httpx.Response(401, json={"error": "invalid_token", "failed_check": "token_exp"})
        if path == "/v1/prekeys":
            self.prekeys[user] = body["prekey_b64"]
            return httpx.Response(204)
        if path == "/v1/auth/logout":
            return httpx.Response(204)
        if path == "/v1/messages":
            step = self.script.pop(0) if self.script else 201
            if step == "drop":  # the connection breaks before anything is stored
                raise httpx.ConnectError("connection refused")
            if step in (201, 504, "lost"):  # stored; with 504 or a lost answer the client is not told
                self.store.setdefault(body["conv_token"], []).append((self.win, body["payload_b64"]))
            if step == "lost":
                raise httpx.ReadTimeout("no answer")
            if step == 201:
                return httpx.Response(201, json={"accepted": True, "stored": True})
            if step == 503:
                return httpx.Response(503, json={"error": "not_stored"}, headers={"Retry-After": "1"})
            if step == 504:
                return httpx.Response(504, json={"error": "ack_timeout"})
            return httpx.Response(step, json={"error": "invalid_request", "fields": []})
        if path == "/v1/read":
            got = [p for w, p in self.store.get(body["conv_token"], []) if w == body["win"]]
            if self.tamper is not None:
                got = self.tamper(body["win"], got)
            return httpx.Response(200, json={"win": body["win"], "payloads_b64": got})
        return httpx.Response(404, json={"error": "not_found"})

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]


class World:
    def __init__(self) -> None:
        self.clock = FakeTime()
        self.server = FakeServer(self.clock)
        self.slept: list[float] = []

    def client(self, name: str) -> VcloakClient:
        c = VcloakClient(BASE, transport=self.server.transport, now=self.clock, sleep=self.slept.append)
        assert c.register(name, PASSWORD)
        c.login(name, PASSWORD)
        c.publish_prekey()
        return c

    def pair(self) -> tuple[VcloakClient, VcloakClient]:
        alice, bob = self.client("alice"), self.client("bob")
        alice.start_conversation("bob")
        bob.start_conversation("alice")
        return alice, bob


@pytest.fixture
def world() -> World:
    return World()


def texts(client: VcloakClient) -> list[str]:
    return [m.text for m in client.sync()]


# ── S1: the session ──────────────────────────────────────────────────────────

def test_login_sends_a_proof_without_a_token_and_requests_carry_both(world: World) -> None:
    alice = world.client("alice")
    by_path = {r.url.path: r for r in world.server.requests}
    login = by_path["/v1/auth/login"]
    assert "authorization" not in login.headers
    assert "ath" not in decode_segment(login.headers["dpop"].split(".")[1])
    put = by_path["/v1/prekeys"]
    claims = decode_segment(put.headers["dpop"].split(".")[1])
    token = put.headers["authorization"].removeprefix("DPoP ")
    assert claims["htm"] == "PUT" and claims["htu"] == BASE + "/v1/prekeys"
    assert claims["ath"] == base64.urlsafe_b64encode(hashlib.sha256(token.encode()).digest()).rstrip(b"=").decode()
    assert alice.logged_in and alice.dpop_headers("POST", "/v1/read")["Authorization"] == f"DPoP {token}"
    assert json.loads(by_path["/v1/auth/register"].content) == {"username": "alice", "password": PASSWORD}


def test_a_client_that_is_not_logged_in_sends_nothing(world: World) -> None:
    c = VcloakClient(BASE, transport=world.server.transport)
    for call in (lambda: c.dpop_headers("POST", "/v1/read"), c.publish_prekey, c.refresh, c.logout,
                 lambda: c.start_conversation("bob")):
        with pytest.raises(NotLoggedIn):
            call()
    with pytest.raises(ClientError):
        c.send("hi")
    assert world.server.requests == []


def test_the_token_is_refreshed_before_it_ends_and_when_the_server_says_so(world: World) -> None:
    alice, bob = world.pair()
    alice.send("one")
    assert world.server.bodies("/v1/auth/refresh") == []
    world.clock.advance(600 - 29)  # inside the margin
    alice.send("two")
    assert len(world.server.bodies("/v1/auth/refresh")) == 1
    world.server.expire_next = 1  # the server's clock ran ahead
    alice.send("three")
    assert len(world.server.bodies("/v1/auth/refresh")) == 2
    spent = [b["refresh_token"] for b in world.server.bodies("/v1/auth/refresh")]
    assert len(set(spent)) == 2  # a refresh token is used once
    assert texts(bob) == ["one", "two", "three"]


def test_a_refused_refresh_ends_the_session(world: World) -> None:
    alice = world.client("alice")
    world.server.refresh_tokens.clear()
    with pytest.raises(ApiError) as e:
        alice.refresh()
    assert (e.value.status, e.value.error, e.value.detail) == (401, "invalid_grant", "reuse")
    assert not alice.logged_in
    with pytest.raises(NotLoggedIn):
        alice.refresh()


def test_errors_name_the_status_and_the_reason_never_a_token(world: World) -> None:
    alice = world.client("alice")
    token = alice.dpop_headers("POST", "/x")["Authorization"].removeprefix("DPoP ")
    world.server.tokens.clear()
    with pytest.raises(ApiError) as e:
        alice.publish_prekey()
    assert str(e.value) == "HTTP 401 invalid_dpop_proof (proof_format)" and token not in str(e.value)


# ── S2: conversation setup ───────────────────────────────────────────────────

def test_both_ends_derive_one_key_one_token_and_one_fingerprint(world: World) -> None:
    alice, bob = world.pair()
    a, b = alice.conversation, bob.conversation
    assert a is not None and b is not None
    assert a._k == b._k and len(a._k) == 32
    assert a.conv_token == b.conv_token == derive_conv_token(a._k)
    assert re.fullmatch(TOKEN_PATTERN, a.conv_token)  # what the server accepts as a token
    assert a.fingerprint == b.fingerprint and re.fullmatch(r"(\d{5} ){5}\d{5}", a.fingerprint)
    assert {a.role, b.role} == {0, 1}
    assert a._k.hex() not in repr(a) and a.conv_token not in repr(a)
    carol = world.client("carol")
    c = carol.start_conversation("bob")
    assert c.conv_token != a.conv_token and c._k != a._k and c.fingerprint != a.fingerprint


def test_the_key_is_bound_to_the_names(world: World) -> None:
    alice, bob = world.pair()
    assert alice.conversation is not None
    world.server.prekeys["mallory"] = world.server.prekeys["bob"]  # the same prekey under another name
    other = alice.start_conversation("mallory")
    assert bob.conversation is not None and other._k != bob.conversation._k


def test_a_prekey_is_fetched_without_the_session_and_published_as_32_bytes(world: World) -> None:
    alice, _ = world.pair()
    fetches = [r for r in world.server.requests if r.url.path.startswith("/v1/prekeys/")]
    assert fetches and all("authorization" not in r.headers and "dpop" not in r.headers for r in fetches)
    published = world.server.bodies("/v1/prekeys")[0]["prekey_b64"]
    assert re.fullmatch(PREKEY_PATTERN, published) and base64.b64decode(published) == alice.prekey_public


def test_a_missing_or_malformed_prekey(world: World) -> None:
    alice = world.client("alice")
    with pytest.raises(ApiError) as e:
        alice.start_conversation("nobody")
    assert (e.value.status, e.value.error) == (404, "no_prekey")
    alice.sleep = world.clock.advance  # waiting moves the fake clock
    before = len(world.server.requests)
    with pytest.raises(ApiError):
        alice.wait_for_prekey("nobody", timeout_s=2.0, poll_s=0.5)
    assert len(world.server.requests) - before == 5  # at 0, 0.5, 1, 1.5 and 2 s, then it gives up
    world.server.prekeys["short"] = base64.b64encode(bytes(31)).decode()
    world.server.prekeys["junk"] = "not base64 !"
    for name in ("short", "junk"):
        with pytest.raises(TamperError):
            alice.fetch_prekey(name)
    world.server.prekeys["me"] = base64.b64encode(alice.prekey_public).decode()
    with pytest.raises(ClientError):
        alice.start_conversation("me")


# ── S3: send ─────────────────────────────────────────────────────────────────

def test_what_the_server_receives_of_a_message(world: World) -> None:
    alice, bob = world.pair()
    secret = "the launch code is 0000"
    assert alice.send(secret) == 0 and alice.send("x") == 1
    sent = world.server.bodies("/v1/messages")
    assert conv_token(alice) not in {""} and all(set(b) == {"conv_token", "payload_b64", "ack"} for b in sent)
    assert all(b["ack"] == "stored" for b in sent)  # ISSUE-23: only a stored message is confirmed
    payloads = [base64.b64decode(b["payload_b64"]) for b in sent]
    assert [len(p) for p in payloads] == [PAYLOAD_LEN, PAYLOAD_LEN]  # one size, whatever the text
    wire = b"".join(r.content for r in world.server.requests if r.url.path in ("/v1/messages", "/v1/read"))
    assert secret.encode() not in wire and b"launch" not in base64.b64decode(sent[0]["payload_b64"])
    assert bob.conversation is not None
    sender, session, number, text = bob.conversation.open(payloads[0])
    assert (sender, number, text) == (alice.conversation.role, 0, secret) and len(session) == 8  # type: ignore[union-attr]


def conv_token(client: VcloakClient) -> str:
    assert client.conversation is not None
    return client.conversation.conv_token


def test_the_header_is_inside_the_ciphertext_and_the_text_is_bounded(world: World) -> None:
    alice, bob = world.pair()
    assert HEADER.size == 18 and MAX_TEXT_BYTES == BLOCK - 19
    a, b = alice.conversation, bob.conversation
    assert a is not None and b is not None
    longest = "é" * (MAX_TEXT_BYTES // 2)
    assert b.open(a.seal(longest, 7))[2:] == (7, longest)
    assert b.open(a.seal("", 0))[3] == ""
    with pytest.raises(ValueError):
        a.seal("x" * (MAX_TEXT_BYTES + 1), 0)
    assert a.seal("same", 0) != a.seal("same", 0)  # a fresh nonce
    assert world.server.bodies("/v1/messages") == []


def test_a_503_is_sent_again_after_retry_after(world: World) -> None:
    alice, bob = world.pair()
    world.server.script = [503, 503, 201]
    assert alice.send("hello") == 0
    assert world.slept == [1.0, 1.0] and len(world.server.bodies("/v1/messages")) == 3
    assert texts(bob) == ["hello"] and bob.conversation.repeats == 0  # type: ignore[union-attr]


@pytest.mark.parametrize("unknown", [504, "lost"])
def test_an_unknown_outcome_is_sent_again_and_the_repeat_is_dropped_on_read(world: World, unknown: Any) -> None:
    alice, bob = world.pair()
    alice.send("first")
    world.server.script = [unknown, 201]  # stored both times
    assert alice.send("second") == 1
    alice.send("third")
    assert len(world.server.store[conv_token(alice)]) == 4
    sent = world.server.bodies("/v1/messages")
    assert sent[1]["payload_b64"] == sent[2]["payload_b64"]  # the same ciphertext, not a new message
    assert texts(bob) == ["first", "second", "third"] and bob.conversation.repeats == 1  # type: ignore[union-attr]
    assert texts(alice) == ["first", "second", "third"]
    alice.conversation.verify_delivered()  # type: ignore[union-attr]


def test_a_broken_connection_is_sent_again(world: World) -> None:
    alice, bob = world.pair()
    world.server.script = ["drop", "drop", 201]
    alice.send("hello")
    assert texts(bob) == ["hello"] and bob.conversation.repeats == 0  # type: ignore[union-attr]


def test_an_unconfirmed_message_stays_pending_and_goes_first(world: World) -> None:
    alice, bob = world.pair()
    alice.send("zero")
    world.server.script = [504] + [503] * (sdk.SEND_ATTEMPTS - 1)  # stored once, never confirmed
    with pytest.raises(SendUnconfirmed):
        alice.send("one")
    conv = alice.conversation
    assert conv is not None and conv._pending is not None and conv._number == 1
    world.server.script = [503] * sdk.SEND_ATTEMPTS
    with pytest.raises(SendUnconfirmed):
        alice.send("two")  # the pending message blocks it: "two" was never sealed under number 1
    assert conv._number == 1
    assert alice.send("two") == 2  # "one" again (a repeat), then "two"
    assert conv._pending is None
    assert texts(bob) == ["zero", "one", "two"] and bob.conversation.repeats == 1  # type: ignore[union-attr]


def test_a_refused_message_is_an_error_and_is_not_sent_again(world: World) -> None:
    alice, _ = world.pair()
    world.server.script = [422]
    with pytest.raises(ApiError) as e:
        alice.send("hello")
    assert e.value.status == 422 and len(world.server.bodies("/v1/messages")) == 1


# ── S3: read, and A3 ─────────────────────────────────────────────────────────

def test_sync_returns_new_messages_across_windows_with_their_senders(world: World) -> None:
    alice, bob = world.pair()
    alice.send("a0")
    bob.send("b0")
    world.server.win += 1
    alice.send("a1")
    got = bob.sync()
    assert [(m.sender, m.mine, m.number, m.text, m.win) for m in got] == [
        ("alice", False, 0, "a0", 100), ("bob", True, 0, "b0", 100), ("alice", False, 1, "a1", 101)]
    assert bob.sync() == []
    bob.send("b1")  # the open window grows: only the new message comes back
    world.server.win += 3
    alice.send("a2")
    assert texts(bob) == ["b1", "a2"]
    assert bob.conversation._cursor == 103  # type: ignore[union-attr]  # closed windows are not read again
    assert bob.read(100) == ["a0", "b0"] and bob.read(102) == [] and bob.read() == []
    assert texts(alice) == ["a0", "b0", "a1", "b1", "a2"]


def test_a_restarted_client_is_a_new_session(world: World) -> None:
    alice, bob = world.pair()
    alice.send("before")
    old = alice.conversation
    again = alice.start_conversation("bob", first_win=old.first_win)  # type: ignore[union-attr]
    assert again.conv_token == old.conv_token and again._session != old._session  # type: ignore[union-attr]
    assert alice.send("after") == 0  # numbers restart with the session
    assert texts(bob) == ["before", "after"]


def tampered(world: World, fn: Callable[[list[str]], list[str]]) -> VcloakClient:
    """Alice sent a0..a4 and Bob b0; return a Bob whose server answers reads through `fn`."""
    alice, bob = world.pair()
    for i in range(5):
        alice.send(f"a{i}")
    bob.send("b0")
    world.server.tamper = lambda win, payloads: fn(list(payloads))
    return bob


def test_a3_an_honest_server_passes(world: World) -> None:
    bob = tampered(world, lambda p: p)
    assert texts(bob) == ["a0", "a1", "a2", "a3", "a4", "b0"]


@pytest.mark.parametrize("name, fn", [
    ("two messages swapped", lambda p: [p[0], p[2], p[1], *p[3:]]),
    ("the first two swapped", lambda p: [p[1], p[0], *p[2:]]),
    ("reversed", lambda p: p[::-1]),
    ("a message in the middle dropped", lambda p: p[:2] + p[3:]),
    ("the first message dropped", lambda p: p[1:]),
])
def test_a3_a_reordered_or_missing_message_is_detected(world: World, name: str,
                                                       fn: Callable[[list[str]], list[str]]) -> None:
    bob = tampered(world, fn)
    with pytest.raises(SequenceError):
        bob.sync()
    if name == "the first message dropped":
        # one window on its own does not say where a session starts: only `sync` sees this one
        assert bob.read(100) == ["a1", "a2", "a3", "a4", "b0"]
    else:
        with pytest.raises(SequenceError):
            bob.read(100)


def test_a3_a_replayed_message_is_dropped_not_delivered_twice(world: World) -> None:
    bob = tampered(world, lambda p: [p[0], p[1], p[0], p[1], *p[2:], p[3]])
    assert texts(bob) == ["a0", "a1", "a2", "a3", "a4", "b0"]
    assert bob.conversation.repeats == 3  # type: ignore[union-attr]


def test_a3_a_forged_or_foreign_payload_is_detected(world: World) -> None:
    carol = world.client("carol")
    dave = world.client("dave")
    carol.start_conversation("dave")
    dave.start_conversation("carol")
    carol.send("not for bob")
    foreign = world.server.bodies("/v1/messages")[-1]["payload_b64"]
    forged = base64.b64encode(os.urandom(PAYLOAD_LEN)).decode()
    cases: list[Callable[[list[str]], list[str]]] = [
        lambda p: [p[0], forged, *p[2:]],
        lambda p: [*p, foreign],
        lambda p: [p[0][:-4] + ("AAA=" if not p[0].endswith("AAA=") else "BBA="), *p[1:]],  # a changed tag
        lambda p: [base64.b64encode(b"short").decode()],
        lambda p: ["*** not base64 ***"],
    ]
    bob = tampered(world, lambda p: p)
    for fn in cases:
        world.server.tamper = lambda win, payloads, fn=fn: fn(list(payloads))
        with pytest.raises(TamperError):
            bob.sync()


def test_a3_a_message_moved_to_another_window_is_detected(world: World) -> None:
    alice, bob = world.pair()
    alice.send("a0")
    alice.send("a1")
    world.server.win += 1
    alice.send("a2")
    store = world.server.store[conv_token(alice)]
    store[1], store[2] = (101, store[1][1]), (100, store[2][1])  # a1 and a2 change windows
    with pytest.raises(SequenceError):
        bob.sync()


def test_a3_rows_that_disappear_from_a_window_already_read_are_detected(world: World) -> None:
    alice, bob = world.pair()
    alice.send("a0")
    alice.send("a1")
    assert texts(bob) == ["a0", "a1"]
    world.server.store[conv_token(alice)].pop()
    with pytest.raises(SequenceError):
        bob.sync()


def test_a3_the_sender_detects_the_loss_of_its_last_messages(world: World) -> None:
    alice, bob = world.pair()
    for i in range(3):
        alice.send(f"a{i}")
    world.server.store[conv_token(alice)].pop()  # the tail: a reader alone cannot see it
    assert texts(bob) == ["a0", "a1"]
    assert texts(alice) == ["a0", "a1"]
    assert alice.conversation is not None and alice.conversation.unseen_own == 1
    with pytest.raises(SequenceError):
        alice.conversation.verify_delivered()


def test_a_malformed_read_answer_is_not_trusted(world: World) -> None:
    alice, bob = world.pair()
    alice.send("a0")
    real = world.server.handle

    def wrong_window(request: httpx.Request) -> httpx.Response:
        r = real(request)
        if request.url.path == "/v1/read":
            return httpx.Response(200, json={"win": 0, "payloads_b64": json.loads(r.content)["payloads_b64"]})
        return r

    bob._http = httpx.Client(transport=httpx.MockTransport(wrong_window))
    with pytest.raises(TamperError):
        bob.sync()
