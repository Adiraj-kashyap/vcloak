"""M11 S7: the log of a service run with sessions holds no identifier and no credential (audit A3).

The module names this file `tests/security/test_logsafe.py`; that basename belongs to tests/unit/test_logsafe.py
(the allow-list itself, M10), so the traffic test lives here (Amendments of ai/modules/M11).

The app runs in-process with the session layer on. A client registers, logs in, sends and reads over two
windows, opens the socket, is refused in several ways, refreshes, replays a spent refresh token, logs out and
runs into the login limit. Every value it handled is then searched for in the captured log."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dpop_client import Device, decode_segment
from service_contract import EPOCHS_PER_WINDOW, payload, token, vcloak_harness
from vcloak.service import logsafe
from vcloak.service.app import create_app
from vcloak.service.models import conv_id_of, encode_payload
from vcloak.service.session import PasswordParams, SessionConfig, SessionService
from vcloak.storage.repo import SqliteRepo

BASE = "http://vcloak.test"
WS = "ws://vcloak.test/v1/ws"
PASSWORD = "correct horse battery"
CHEAP = PasswordParams(t=1, m_kib=64, p=1)  # tests only
FORBIDDEN_KEYS = {"conv_id", "conv_token", "bucket", "seq", "row_id", "epoch", "payload", "token", "access_token",
                  "refresh_token", "ticket", "dpop", "proof", "jti", "jkt", "sub", "user", "username", "password",
                  "family", "fam", "ip", "client", "htu", "key"}


class Recorder(Device):
    """A device that keeps every proof it signs."""

    def __init__(self) -> None:
        super().__init__()
        self.proofs: list[str] = []

    def proof(self, *a: Any, **kw: Any) -> str:
        p = super().proof(*a, **kw)
        self.proofs.append(p)
        return p


def url(path: str) -> str:
    return BASE + path


def drive(client: TestClient, h: Any) -> list[str]:
    """The traffic. Returns every value that must not be in the log."""
    dev, thief = Recorder(), Recorder()
    convs = [token("log-a"), token("log-b")]
    secrets: list[str] = [PASSWORD, "alice_logtest", "bob_logtest", dev.jkt, thief.jkt, *convs]
    secrets += [str(conv_id_of(c)) for c in convs] + [hex(conv_id_of(c))[2:] for c in convs]

    def step(n: int = 1) -> None:
        assert client.portal is not None
        assert client.portal.call(h.backend.scheduler.run, n) == n

    def post(d: Device, access: str, path: str, body: Any = None) -> Any:
        return client.post(path, json=body, headers=d.headers("POST", url(path), access))

    def login(d: Device, name: str, password: str = PASSWORD) -> Any:
        path = "/v1/auth/login"
        return client.post(path, json={"username": name, "password": password}, headers=d.headers("POST", url(path)))

    for name in ("alice_logtest", "bob_logtest"):
        assert client.post("/v1/auth/register", json={"username": name, "password": PASSWORD}).status_code == 201
    assert client.post("/v1/auth/register",
                       json={"username": "alice_logtest", "password": PASSWORD}).status_code == 409
    tokens = login(dev, "alice_logtest").json()
    access, refresh = tokens["access_token"], tokens["refresh_token"]
    secrets += [access, refresh, *access.split("."), decode_segment(access.split(".")[1])["fam"]]

    # messages over two windows, and the reads
    sent = 0
    for _ in range(2 * EPOCHS_PER_WINDOW):
        for conv in convs:
            p = payload(sent, seed=9)
            secrets += [encode_payload(p)[:24], p[:8].hex()]
            assert post(dev, access, "/v1/messages", {"conv_token": conv, "payload_b64": encode_payload(p)}
                        ).status_code == 202
            sent += 1
        step()
    step()
    for win in (0, 1):
        r = post(dev, access, "/v1/read", {"conv_token": convs[0], "win": win})
        assert r.status_code == 200 and len(r.json()["payloads_b64"]) == EPOCHS_PER_WINDOW

    # refusals: no proof, a replay, another key, a malformed body, a wrong password
    assert client.post("/v1/read", json={"conv_token": convs[0], "win": 0}).status_code == 401
    replay = dev.headers("POST", url("/v1/read"), access)
    for expected in (200, 401):
        assert client.post("/v1/read", json={"conv_token": convs[0], "win": 0}, headers=replay).status_code == expected
    assert post(thief, access, "/v1/read", {"conv_token": convs[1], "win": 0}).status_code == 401
    assert post(dev, access, "/v1/messages", {"conv_token": convs[0], "payload_b64": "AAAA"}).status_code == 422
    assert login(thief, "alice_logtest", "not the password").status_code == 401

    # the socket: opened, pushed to, and refused for a spent ticket and for another key
    ticket = post(dev, access, "/v1/auth/ws-ticket").json()["ticket"]
    other = post(dev, access, "/v1/auth/ws-ticket").json()["ticket"]
    secrets += [ticket, other]
    with client.websocket_connect(WS) as ws:
        ws.send_text(json.dumps({"ticket": ticket, "dpop": dev.proof("GET", url("/v1/ws"))}))
        assert ws.receive_json()["type"] == "ready"
        step()
        assert ws.receive_json()["type"] == "tick"
        for d, t, reason in ((dev, ticket, "ticket_unused"), (thief, other, "ticket_key")):
            with client.websocket_connect(WS) as refused:
                refused.send_text(json.dumps({"ticket": t, "dpop": d.proof("GET", url("/v1/ws"))}))
                with pytest.raises(WebSocketDisconnect) as e:
                    refused.receive_text()
                assert e.value.reason == reason

        # refresh, the spent token again (the family is revoked: the socket closes), logout of a second login
        path = "/v1/auth/refresh"
        r = client.post(path, json={"refresh_token": refresh}, headers=dev.headers("POST", url(path)))
        assert r.status_code == 200
        secrets += [r.json()["access_token"], r.json()["refresh_token"]]
        r = client.post(path, json={"refresh_token": refresh}, headers=dev.headers("POST", url(path)))
        assert r.status_code == 401 and r.json()["reason"] == "reuse"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
    again = login(dev, "alice_logtest").json()
    secrets += [again["access_token"], again["refresh_token"]]
    assert post(dev, again["access_token"], "/v1/auth/logout").status_code == 204

    # the login limit
    codes = [login(thief, "bob_logtest", f"guess number {i}").status_code for i in range(6)]
    assert codes == [401] * 5 + [429]
    secrets += [f"guess number {i}" for i in range(6)]

    for d in (dev, thief):
        for p in d.proofs:
            secrets += [p, p.split(".")[2], decode_segment(p.split(".")[1])["jti"]]
        secrets += [d.jwk["x"], d.jwk["y"]]
    return secrets


def test_a3_the_log_of_a_session_run_holds_no_identifier_and_no_credential(caplog: pytest.LogCaptureFixture) -> None:
    h = vcloak_harness(SqliteRepo())
    sessions = SessionService(SessionConfig(password=CHEAP))
    with caplog.at_level(logging.DEBUG):
        with TestClient(create_app(h.backend, sessions=sessions), base_url=BASE) as client:
            secrets = drive(client, h)
    ours = [r for r in caplog.records if r.name.startswith("vcloak")]
    text = "\n".join(f"{r.name} {r.getMessage()}" for r in ours)
    events = re.findall(r"event=(\w+)", text)
    assert {"started", "window_closed", "family_revoked", "stopped"} <= set(events)

    assert len(secrets) > 150 and all(isinstance(s, str) and len(s) >= 8 for s in secrets)
    leaked = [s for s in set(secrets) if s in text]
    assert not leaked, f"{len(leaked)} handled values are in the log"
    keys = set(re.findall(r"(\w+)=", text))
    assert keys <= logsafe.ALLOWED | {"event"}, keys - logsafe.ALLOWED
    assert not keys & FORBIDDEN_KEYS
    # no JWS segment, no row id, no long digit run (epoch numbers, millisecond timestamps, conversation ids)
    assert "eyJ" not in text and not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", text) and not re.search(r"\d{10,}", text)
    # whatever any other logger wrote during the run (the HTTP stack included) is held to the same search
    everything = "\n".join(r.getMessage() for r in caplog.records)
    assert not [s for s in set(secrets) if s in everything]


@pytest.mark.parametrize("field", sorted(FORBIDDEN_KEYS))
def test_a3_no_session_identifier_is_an_allowed_field(field: str) -> None:
    assert field not in logsafe.ALLOWED
    with pytest.raises(logsafe.ForbiddenLogField):
        logsafe.render("request_refused", {field: 1})


def test_the_final_allow_list() -> None:
    """A change of the allow-list is a change of this test: what a log line may carry is decided here."""
    assert logsafe.ALLOWED == {
        "mode", "clock", "visible_round", "backend", "store", "slots", "buckets", "window_s", "epoch_ms", "cand_k",
        "port", "win", "rows", "epochs", "overflow", "missed", "queued", "windows", "status", "error", "dev_key",
        "ready", "sessions"}
    assert logsafe.TEXT_FIELDS <= logsafe.ALLOWED
    assert logsafe.render("serve", {"sessions": True, "port": 8000}) == "event=serve port=8000 sessions=True"
    with pytest.raises(logsafe.ForbiddenLogField):
        logsafe.render("serve", {"sessions": "alice"})  # a flag, never text


# ── the HTTP server's own lines ──────────────────────────────────────────────

@pytest.mark.parametrize("message, args, kept", [
    ('%s - "WebSocket %s" [accepted]', ("127.0.0.1:63695", "/v1/ws"), False),
    ('%s - "WebSocket %s" 403', ("203.0.113.9:4411", "/v1/ws"), False),
    ("connection open", (), False),
    ("connection closed", (), False),
    ("connection rejected (403 Forbidden)", (), False),
    ("Application startup complete.", (), True),
    ("Uvicorn running on %s://%s:%d (Press CTRL+C to quit)", ("http", "127.0.0.1", 8000), True),
    ("Invalid HTTP request received.", (), True),
    ("%d items", ("not a number",), False),  # a record that cannot be rendered is not written
])
def test_connection_lines_are_dropped(message: str, args: tuple[Any, ...], kept: bool) -> None:
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, message, args, None)
    assert logsafe.ConnectionLineFilter().filter(record) is kept


def test_server_log_config_filters_every_handler_and_leaves_the_base_alone() -> None:
    import logging.config

    import uvicorn.config

    base = uvicorn.config.LOGGING_CONFIG
    before = json.dumps(base, sort_keys=True)
    cfg = logsafe.server_log_config(base)
    assert json.dumps(base, sort_keys=True) == before
    assert set(cfg["handlers"]) == set(base["handlers"]) and cfg["handlers"]
    assert all(h["filters"] == ["no_connection_lines"] for h in cfg["handlers"].values())
    factory = cfg["filters"]["no_connection_lines"]["()"]
    assert factory == "vcloak.service.logsafe.ConnectionLineFilter"
    # the name resolves the way logging.config resolves it
    assert logging.config.BaseConfigurator({}).resolve(factory) is logsafe.ConnectionLineFilter
