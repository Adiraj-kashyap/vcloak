"""The client SDK (M12): everything a client does, over the API of docs/API.md.

    client = VcloakClient("http://127.0.0.1:8000")
    client.register("alice", password); client.login("alice", password); client.publish_prekey()
    client.start_conversation("bob")
    client.send("hi")              # S0-S3: header + text, padded to BLOCK, AES-256-GCM, POST with a DPoP proof
    for m in client.sync(): ...    # R4-R5: read the windows, decrypt, verify the order

What the server sees of a message: one ciphertext of the fixed size `12 + BLOCK + 16` and the
conversation token. The token is derived from K_content (crypto/client.py), so both ends compute it
and the server cannot tell which accounts share it.

**The order is verified by the client.** Inside every plaintext, before the text, there is a header

    version(1) = 1 | sender(1) | session(8) | number(LE64)

`sender` is 0 for the party with the smaller prekey and 1 for the other; `session` is drawn at random
when a client starts; `number` counts that client's messages from 0. A reader accepts, for each
(sender, session), the numbers 0, 1, 2, ... in the order the server returns them:

- a number that was already accepted is a repeat (the sender retried, or the server replayed) and is
  dropped; this is what makes `ack: "stored"` with retries safe (ISSUE-23);
- a number above the next expected one means a message is missing or out of order: `SequenceError`
  (and so does, for a reader that did not start at message 0, a number below the first one it saw);
- a payload that does not authenticate under K_content and the token: `TamperError`.

Not detected by a reader alone: the loss of the last messages of a sender, and of every message of a
session it has seen nothing of. The sender detects the first for its own messages (`verify_delivered`).
The order *between* the two senders is the server's arrival order and is not verifiable.

Sending uses `ack: "stored"`: `send` returns when the message is in the store. A 503 is sent again
after `Retry-After`; a 504 or a broken connection leaves the outcome unknown, so the same ciphertext
is sent again and the number is not reused for another text until the message is confirmed.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from vcloak.client.device import DeviceKey, public_bytes
from vcloak.config import BLOCK
from vcloak.crypto.client import (
    PAYLOAD_LEN,
    PUBLIC_LEN,
    ContentError,
    decrypt_content,
    derive_content_key,
    derive_conv_token,
    encrypt_content,
    transcript,
)

HEADER = struct.Struct("<BB8sQ")  # version, sender, session, number
VERSION = 1
MAX_TEXT_BYTES = BLOCK - 1 - HEADER.size  # the padding mark takes one byte
SEND_ATTEMPTS = 5
REFRESH_MARGIN_S = 30.0  # an access token this close to its end is replaced before the request
_AAD = b"vcloak-msg-v1\x00"
_CONTEXT = b"vcloak-chat-v1\x00"
_FINGERPRINT = b"vcloak-fingerprint-v1\x00"


class ClientError(Exception):
    """Base of what the SDK raises. No message of it carries a key, a token or a plaintext."""


class NotLoggedIn(ClientError):
    pass


class ApiError(ClientError):
    """An answer the SDK did not expect: the status, the server's error code and its named reason."""

    def __init__(self, status: int, error: str = "", detail: str = "") -> None:
        super().__init__(f"HTTP {status}" + (f" {error}" if error else "") + (f" ({detail})" if detail else ""))
        self.status, self.error, self.detail = status, error, detail


class SendUnconfirmed(ClientError):
    """A message is not confirmed as stored after every attempt. It stays pending: the next `send`
    (or `flush`) sends it again before anything else."""


class SequenceError(ClientError):
    """The server returned a conversation with a message missing or out of order."""


class TamperError(ClientError):
    """The server returned something that is not a ciphertext of this conversation."""


class ProtocolError(ClientError):
    """An authentic message with a header this version does not understand."""


@dataclass(frozen=True)
class Message:
    sender: str  # the account name
    mine: bool
    session: str  # hex of the sender's session id
    number: int
    text: str
    win: int


class SeqChecker:
    """The continuity rule of the module docstring, for one conversation."""

    def __init__(self, strict_start: bool = True) -> None:
        self._strict = strict_start
        self._next: dict[tuple[int, bytes], int] = {}
        self._first: dict[tuple[int, bytes], int] = {}  # the first number accepted (0 with a strict start)

    def next(self, sender: int, session: bytes) -> int:
        return self._next.get((sender, session), 0)

    def accept(self, sender: int, session: bytes, number: int) -> bool:
        """True for the next message of its sender, False for a repeat; raises on a gap."""
        key = (sender, session)
        expected = self._next.get(key)
        if expected is None:
            if self._strict and number != 0:
                raise SequenceError(f"the first message of a session has number {number}: "
                                    f"{number} earlier message(s) are missing or out of order")
            self._first[key], self._next[key] = number, number + 1
            return True
        if number == expected:
            self._next[key] = expected + 1
            return True
        if self._first[key] <= number < expected:
            return False
        if number < expected:  # only without a strict start: older than where this reader began
            raise SequenceError(f"message {number} of a sender came after message {self._first[key]}: out of order")
        raise SequenceError(f"expected message {expected} of a sender, got {number}: "
                            f"{number - expected} message(s) are missing or out of order")


def _error_of(r: httpx.Response) -> ApiError:
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    detail = body.get("failed_check") or body.get("reason") or ""
    return ApiError(r.status_code, str(body.get("error", "")), str(detail))


class Conversation:
    """One conversation with one peer: K_content, the token, the send counter and the read state."""

    def __init__(self, client: VcloakClient, peer: str, k_content: bytes, own_public: bytes, peer_public: bytes,
                 transcript_bytes: bytes, *, first_win: int, strict_start: bool = True) -> None:
        if own_public == peer_public:
            raise ClientError("both ends hold the same prekey")
        self._client, self.peer, self._k = client, peer, k_content
        self.conv_token = derive_conv_token(k_content)
        self._aad = _AAD + self.conv_token.encode("ascii")
        self.role = 0 if own_public < peer_public else 1
        self._session = os.urandom(8)
        self._number = 0  # own messages confirmed as stored
        self._pending: bytes | None = None  # the ciphertext of message `_number`, not confirmed yet
        self._checker = SeqChecker(strict_start)
        self.first_win = first_win
        self._cursor = first_win
        self._consumed: dict[int, int] = {}  # window -> payloads of it already handled
        self.repeats = 0  # repeats dropped while reading
        digest = hashlib.sha256(_FINGERPRINT + transcript_bytes).digest()
        digits = f"{int.from_bytes(digest[:15], 'big') % 10 ** 30:030d}"
        self.fingerprint = " ".join(digits[i:i + 5] for i in range(0, 30, 5))  # equal at both ends

    def __repr__(self) -> str:
        return f"Conversation(peer={self.peer!r})"  # never the key or the token

    # -- S0-S2 and R5 --

    def seal(self, text: str, number: int) -> bytes:
        """The ciphertext of own message `number`: header and text, padded to BLOCK, AES-256-GCM."""
        raw = text.encode("utf-8")
        if len(raw) > MAX_TEXT_BYTES:
            raise ValueError(f"a message holds at most {MAX_TEXT_BYTES} bytes of UTF-8, this one has {len(raw)}")
        header = HEADER.pack(VERSION, self.role, self._session, number)
        return encrypt_content(self._k, header + raw, self._aad)

    def open(self, payload: bytes, win: int = -1) -> tuple[int, bytes, int, str]:
        """(sender, session, number, text) of one payload the server returned."""
        try:
            plain = decrypt_content(self._k, payload, self._aad)
        except ContentError:
            raise TamperError(f"a payload of window {win} is not a ciphertext of this conversation") from None
        if len(plain) < HEADER.size:
            raise ProtocolError("a message without a header")
        version, sender, session, number = HEADER.unpack_from(plain)
        if version != VERSION or sender not in (0, 1):
            raise ProtocolError("a message header of another version")
        try:
            return sender, session, number, plain[HEADER.size:].decode("utf-8")
        except UnicodeDecodeError:
            raise ProtocolError("a message that is not UTF-8") from None

    # -- send --

    def _post_stored(self, payload: bytes) -> None:
        body = {"conv_token": self.conv_token, "payload_b64": base64.b64encode(payload).decode("ascii"),
                "ack": "stored"}
        last = ""
        for _ in range(SEND_ATTEMPTS):
            try:
                r = self._client.authed("POST", "/v1/messages", body)
            except httpx.TransportError as e:
                last = type(e).__name__  # outcome unknown: the same ciphertext goes again
                continue
            if r.status_code == 201 and r.json().get("stored") is True:
                return
            if r.status_code == 503:  # queue_full or not_stored: it is not in the store
                last = _error_of(r).error
                self._client.sleep(_retry_after(r))
                continue
            if r.status_code == 504:  # ack_timeout: outcome unknown
                last = "ack_timeout"
                continue
            raise _error_of(r)
        raise SendUnconfirmed(f"message {self._number} is not confirmed as stored ({last}); it stays pending")

    def flush(self) -> None:
        """Send the pending message again, if there is one, until it is confirmed."""
        if self._pending is not None:
            self._post_stored(self._pending)
            self._pending = None
            self._number += 1

    def send(self, text: str) -> int:
        """Store one message; returns its number. Raises `SendUnconfirmed` when the store did not confirm."""
        self.flush()
        self._pending = self.seal(text, self._number)
        number = self._number
        self.flush()
        return number

    # -- read --

    def _fetch(self, win: int) -> list[bytes]:
        r = self._client.authed("POST", "/v1/read", {"conv_token": self.conv_token, "win": win})
        if r.status_code != 200:
            raise _error_of(r)
        body = r.json()
        if not isinstance(body, dict) or body.get("win") != win or not isinstance(body.get("payloads_b64"), list):
            raise TamperError(f"the answer for window {win} is not a read answer")
        out = []
        for item in body["payloads_b64"]:
            try:
                raw = base64.b64decode(item, validate=True)
            except (binascii.Error, ValueError, TypeError):
                raise TamperError(f"a payload of window {win} is not base64") from None
            if len(raw) != PAYLOAD_LEN:
                raise TamperError(f"a payload of window {win} has the wrong size")
            out.append(raw)
        return out

    def _message(self, sender: int, session: bytes, number: int, text: str, win: int) -> Message:
        mine = sender == self.role
        return Message(self._client.username if mine else self.peer, mine, session.hex(), number, text, win)

    def read_window(self, win: int) -> list[Message]:
        """The messages of one window, on their own: repeats dropped, a gap inside the window raises.
        It keeps no state; `sync` is the reader that verifies the conversation from its start."""
        checker, out = SeqChecker(strict_start=False), []
        for payload in self._fetch(win):
            sender, session, number, text = self.open(payload, win)
            if checker.accept(sender, session, number):
                out.append(self._message(sender, session, number, text, win))
        return out

    def sync(self) -> list[Message]:
        """The messages that are new since the last call, in order, verified (module docstring)."""
        current = int(self._client.windows()["win"])
        wins = range(self._cursor, current + 1)
        # newest first: an older window is then read later than every newer one, so a message is never
        # seen before one that precedes it
        fetched = {w: self._fetch(w) for w in reversed(wins)}
        out: list[Message] = []
        for w in wins:
            payloads, done = fetched[w], self._consumed.get(w, 0)
            if len(payloads) < done:
                raise SequenceError(f"window {w} holds fewer messages than it did: {done - len(payloads)} missing")
            for payload in payloads[done:]:
                sender, session, number, text = self.open(payload, w)
                if self._checker.accept(sender, session, number):
                    out.append(self._message(sender, session, number, text, w))
                else:
                    self.repeats += 1
            self._consumed[w] = len(payloads)
        while self._cursor < current - 1:  # a window two behind the open one gets no more rows
            self._consumed.pop(self._cursor, None)
            self._cursor += 1
        return out

    @property
    def unseen_own(self) -> int:
        """Own messages confirmed as stored that `sync` has not returned yet."""
        return self._number - self._checker.next(self.role, self._session)

    def verify_delivered(self) -> None:
        """After a `sync`: every own message the store confirmed must have come back."""
        if self.unseen_own > 0:
            raise SequenceError(f"{self.unseen_own} own message(s) were confirmed as stored and are not returned")


def _retry_after(r: httpx.Response) -> float:
    try:
        return min(max(float(r.headers.get("Retry-After", "1")), 0.0), 5.0)
    except ValueError:
        return 1.0


class VcloakClient:
    """One device of one account. Keys live in memory; pass `device` and `prekey` from a sealed key file
    (client/device.py) to keep them across runs."""

    def __init__(self, base_url: str, *, device: DeviceKey | None = None, prekey: X25519PrivateKey | None = None,
                 http: httpx.Client | None = None, transport: httpx.BaseTransport | None = None,
                 timeout: float = 15.0, now: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.base = base_url.rstrip("/")
        self.now, self.sleep = now, sleep
        self.device = device or DeviceKey(now=now)
        self._prekey = prekey or X25519PrivateKey.generate()
        self.prekey_public = public_bytes(self._prekey)
        self._http = http or httpx.Client(timeout=timeout, transport=transport)
        self.username = ""
        self._access = ""
        self._refresh = ""
        self._expires_at = 0.0
        self.conversation: Conversation | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> VcloakClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- S1: session --

    @property
    def logged_in(self) -> bool:
        return bool(self._access)

    def dpop_headers(self, method: str, path: str, *, with_token: bool = True) -> dict[str, str]:
        """The headers of one request: a fresh proof for this method and URL, and the access token."""
        if not with_token:
            return {"DPoP": self.device.proof(method, self.base + path)}
        if not self._access:
            raise NotLoggedIn("log in first")
        return {"DPoP": self.device.proof(method, self.base + path, self._access),
                "Authorization": f"DPoP {self._access}"}

    def _take_tokens(self, r: httpx.Response) -> None:
        if r.status_code != 200:
            raise _error_of(r)
        body = r.json()
        self._access, self._refresh = body["access_token"], body["refresh_token"]
        self._expires_at = self.now() + float(body["expires_in"])

    def register(self, username: str, password: str) -> bool:
        """Create the account. False when the name is taken (then log in)."""
        r = self._http.post(self.base + "/v1/auth/register", json={"username": username, "password": password})
        if r.status_code == 409:
            return False
        if r.status_code != 201:
            raise _error_of(r)
        return True

    def login(self, username: str, password: str) -> None:
        """Get tokens bound to this device's key. The password is sent once and not kept."""
        path = "/v1/auth/login"
        r = self._http.post(self.base + path, json={"username": username, "password": password},
                            headers=self.dpop_headers("POST", path, with_token=False))
        self._take_tokens(r)
        self.username = username

    def refresh(self) -> None:
        """Trade the refresh token for the next pair. A refused refresh ends the session."""
        if not self._refresh:
            raise NotLoggedIn("no refresh token")
        path = "/v1/auth/refresh"
        token, self._refresh = self._refresh, ""  # single use, whatever the answer
        r = self._http.post(self.base + path, json={"refresh_token": token},
                            headers=self.dpop_headers("POST", path, with_token=False))
        if r.status_code != 200:
            self._access = ""
        self._take_tokens(r)

    def authed(self, method: str, path: str, body: Any = None) -> httpx.Response:
        """One authenticated request. The access token is refreshed shortly before it ends, and once
        more if the server says it has."""
        if not self._access:
            raise NotLoggedIn("log in first")
        if self._refresh and self.now() >= self._expires_at - REFRESH_MARGIN_S:
            self.refresh()
        r = self._http.request(method, self.base + path, json=body, headers=self.dpop_headers(method, path))
        if r.status_code == 401 and self._refresh and _error_of(r).detail == "token_exp":
            self.refresh()
            r = self._http.request(method, self.base + path, json=body, headers=self.dpop_headers(method, path))
        return r

    def logout(self) -> None:
        r = self.authed("POST", "/v1/auth/logout")
        if r.status_code != 204:
            raise _error_of(r)
        self._access = self._refresh = ""

    # -- S2: conversation setup --

    def publish_prekey(self) -> None:
        """Publish this device's public X25519 prekey under the account."""
        r = self.authed("PUT", "/v1/prekeys", {"prekey_b64": base64.b64encode(self.prekey_public).decode("ascii")})
        if r.status_code != 204:
            raise _error_of(r)

    def fetch_prekey(self, username: str) -> bytes:
        """The public prekey `username` published. Sent without the session, so the server is not told
        who asks (ADR-019). `ApiError` 404 `no_prekey` when there is none."""
        r = self._http.get(f"{self.base}/v1/prekeys/{username}")
        if r.status_code != 200:
            raise _error_of(r)
        try:
            raw = base64.b64decode(r.json()["prekey_b64"], validate=True)
        except (binascii.Error, ValueError, KeyError, TypeError):
            raise TamperError("the prekey answer is malformed") from None
        if len(raw) != PUBLIC_LEN:
            raise TamperError("the prekey answer is malformed")
        return raw

    def wait_for_prekey(self, username: str, *, timeout_s: float = 60.0, poll_s: float = 0.5) -> bytes:
        deadline = self.now() + timeout_s
        while True:
            try:
                return self.fetch_prekey(username)
            except ApiError as e:
                if e.status != 404 or self.now() >= deadline:
                    raise
            self.sleep(poll_s)

    def windows(self) -> dict[str, Any]:
        r = self._http.get(self.base + "/v1/windows")
        if r.status_code != 200:
            raise _error_of(r)
        return r.json()

    def start_conversation(self, peer: str, *, first_win: int | None = None, strict_start: bool = True,
                           peer_prekey: bytes | None = None) -> Conversation:
        """Agree on K_content with `peer` (X25519 + HKDF over both prekeys and both names) and derive the
        conversation token. `first_win` is the window the conversation is read from (default: the open
        one); with `strict_start` every session must start at message 0 from there on."""
        if not self.username:
            raise NotLoggedIn("log in first")
        peer_public = peer_prekey if peer_prekey is not None else self.fetch_prekey(peer)
        names = sorted((self.username, peer))
        t = transcript(self.prekey_public, peer_public, _CONTEXT + "\x00".join(names).encode("utf-8"))
        k_content = derive_content_key(self._prekey, peer_public, t)
        if first_win is None:
            first_win = int(self.windows()["win"])
        self.conversation = Conversation(self, peer, k_content, self.prekey_public, peer_public, t,
                                         first_win=first_win, strict_start=strict_start)
        return self.conversation

    # -- S3: send and read --

    def _conv(self) -> Conversation:
        if self.conversation is None:
            raise ClientError("start a conversation first")
        return self.conversation

    def send(self, text: str) -> int:
        return self._conv().send(text)

    def read(self, win: int | None = None) -> list[str]:
        """The texts of one window; without `win`, of what is new since the last call (verified)."""
        conv = self._conv()
        return [m.text for m in (conv.sync() if win is None else conv.read_window(win))]

    def sync(self) -> list[Message]:
        return self._conv().sync()

    # -- the push socket (ADR-018) --

    def ws_ticket(self) -> str:
        r = self.authed("POST", "/v1/auth/ws-ticket")
        if r.status_code != 200:
            raise _error_of(r)
        return r.json()["ticket"]

    def ticks(self, n: int, *, timeout: float = 10.0) -> list[dict[str, Any]]:
        """Open /v1/ws with a ticket and return the `ready` frame and the next `n` pushed frames. Every
        socket gets the same frames: they say that an epoch boundary passed, not that a message came."""
        from websockets.sync.client import connect

        ticket = self.ws_ticket()
        with connect("ws" + self.base[4:] + "/v1/ws", open_timeout=timeout) as ws:
            ws.send(json.dumps({"ticket": ticket, "dpop": self.device.proof("GET", self.base + "/v1/ws")}))
            return [json.loads(ws.recv(timeout=timeout)) for _ in range(n + 1)]
