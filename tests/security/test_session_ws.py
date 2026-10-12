"""M11 S5: WebSocket tickets, the `/v1/ws` push at epoch cadence, and the CLI switch.

The app runs in-process behind Starlette's test client (the numpy simulator, a SQLite store); the client
side is tests/dpop_client.py. Epochs pass when the test says so. Nothing here measures anything."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dpop_client import Device, FakeTime
from service_contract import EPOCHS_PER_WINDOW, Harness, baseline_harness, payload, vcloak_harness
from vcloak import cli
from vcloak.service import app as service_app
from vcloak.service.app import create_app
from vcloak.service.baseline import SqliteBaselineStore
from vcloak.service.models import encode_payload
from vcloak.service.scheduler import EpochScheduler, SimClock
from vcloak.service.session import (
    PROOF_CHECKS,
    TICKET_CHECKS,
    TICKETS_PER_FAMILY,
    PasswordParams,
    SessionConfig,
    SessionService,
    Verdict,
)
from vcloak.storage.repo import SqliteRepo

BASE = "http://vcloak.test"
WS = "ws://vcloak.test/v1/ws"
WS_URL = BASE + "/v1/ws"  # what a socket proof names: the handshake URL as http
PASSWORD = "correct horse battery"
CHEAP = PasswordParams(t=1, m_kib=64, p=1)  # tests only


def url(path: str) -> str:
    return BASE + path


@pytest.fixture
def clock() -> FakeTime:
    return FakeTime()


@pytest.fixture
def harness() -> Harness:
    return vcloak_harness(SqliteRepo())


@pytest.fixture
def sessions(clock: FakeTime) -> SessionService:
    return SessionService(SessionConfig(password=CHEAP), now=clock)


@contextmanager
def running(harness: Harness, sessions: SessionService | None) -> Iterator[TestClient]:
    with TestClient(create_app(harness.backend, sessions=sessions), base_url=BASE) as client:
        yield client


def step(client: TestClient, harness: Harness, n: int = 1) -> None:
    """Let `n` epochs pass on the loop the app runs on."""
    assert client.portal is not None
    assert client.portal.call(harness.backend.scheduler.run, n) == n


def sign_in(client: TestClient, dev: Device, name: str = "alice") -> dict[str, Any]:
    r = client.post("/v1/auth/register", json={"username": name, "password": PASSWORD})
    assert r.status_code in (201, 409)
    path = "/v1/auth/login"
    r = client.post(path, json={"username": name, "password": PASSWORD}, headers=dev.headers("POST", url(path)))
    assert r.status_code == 200, r.text
    return r.json()


def call(client: TestClient, dev: Device, access: str, path: str, body: Any = None) -> Any:
    return client.post(path, json=body, headers=dev.headers("POST", url(path), access))


def ticket(client: TestClient, dev: Device, access: str) -> str:
    r = call(client, dev, access, "/v1/auth/ws-ticket")
    assert r.status_code == 200, r.text
    return r.json()["ticket"]


def auth_frame(dev: Device, tkt: Any, **proof_kw: Any) -> str:
    return json.dumps({"ticket": tkt, "dpop": dev.proof("GET", proof_kw.pop("htu", WS_URL), **proof_kw)})


def closed(ws: Any) -> tuple[int, str]:
    """The code and reason with which the server closes the socket next."""
    with pytest.raises(WebSocketDisconnect) as e:
        ws.receive_text()
    return e.value.code, e.value.reason


def refused(client: TestClient, frame: str) -> tuple[int, str]:
    with client.websocket_connect(WS) as ws:
        ws.send_text(frame)
        return closed(ws)


# ── the ticket route ─────────────────────────────────────────────────────────

def test_ticket_route_needs_a_session_and_answers_a_ticket(harness: Harness, sessions: SessionService,
                                                           clock: FakeTime) -> None:
    dev = Device(clock)
    with running(harness, sessions) as client:
        access = sign_in(client, dev)["access_token"]
        r = client.post("/v1/auth/ws-ticket")
        assert r.status_code == 401 and r.json()["failed_check"] == "proof_format"
        r = call(client, Device(clock), access, "/v1/auth/ws-ticket")
        assert r.status_code == 401 and r.json()["failed_check"] == "key_binding"
        r = call(client, dev, access, "/v1/auth/ws-ticket")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        body = r.json()
        assert set(body) == {"ticket", "expires_in"} and body["expires_in"] == 30
        assert len(body["ticket"]) == 43 and body["ticket"] != ticket(client, dev, access)


def test_without_sessions_there_is_no_socket_and_no_ticket_route(harness: Harness) -> None:
    with running(harness, None) as client:
        assert client.post("/v1/auth/ws-ticket").status_code == 404
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(WS):
            pass
        assert client.app.state.sockets is None  # type: ignore[attr-defined]


# ── the socket ───────────────────────────────────────────────────────────────

def test_socket_pushes_the_same_frame_to_every_client_at_each_epoch(harness: Harness, sessions: SessionService,
                                                                    clock: FakeTime) -> None:
    alice, bob = Device(clock), Device(clock)
    with running(harness, sessions) as client:
        a = sign_in(client, alice, "alice")["access_token"]
        b = sign_in(client, bob, "bob")["access_token"]
        hub = client.app.state.sockets  # type: ignore[attr-defined]
        with client.websocket_connect(WS) as wa, client.websocket_connect(WS) as wb:
            wa.send_text(auth_frame(alice, ticket(client, alice, a)))
            wb.send_text(auth_frame(bob, ticket(client, bob, b)))
            assert wa.receive_json() == {"type": "ready", "win": 0} == wb.receive_json()
            assert len(hub) == 2
            # alice sends, bob does not: the frames of the two sockets stay the same text
            r = call(client, alice, a, "/v1/messages",
                     {"conv_token": "c" * 32, "payload_b64": encode_payload(payload(0))})
            assert r.status_code == 202, r.text
            wins = []
            for _ in range(EPOCHS_PER_WINDOW + 1):
                step(client, harness)
                fa, fb = wa.receive_text(), wb.receive_text()
                assert fa == fb
                frame = json.loads(fa)
                assert set(frame) == {"type", "win"} and frame["type"] == "tick"
                wins.append(frame["win"])
            assert wins == [0] * (EPOCHS_PER_WINDOW - 1) + [1, 1]  # the round being written after each boundary
        assert len(hub) == 0


def test_a_ticket_opens_one_socket_only(harness: Harness, sessions: SessionService, clock: FakeTime) -> None:
    dev = Device(clock)
    with running(harness, sessions) as client:
        access = sign_in(client, dev)["access_token"]
        tkt = ticket(client, dev, access)
        with client.websocket_connect(WS) as ws:
            ws.send_text(auth_frame(dev, tkt))
            assert ws.receive_json()["type"] == "ready"
            assert refused(client, auth_frame(dev, tkt)) == (4401, "ticket_unused")  # while the first is open
        assert refused(client, auth_frame(dev, tkt)) == (4401, "ticket_unused")  # and after it


def test_a_ticket_is_bound_to_the_key_it_was_issued_to(harness: Harness, sessions: SessionService,
                                                      clock: FakeTime) -> None:
    dev, thief = Device(clock), Device(clock)
    with running(harness, sessions) as client:
        access = sign_in(client, dev)["access_token"]
        tkt = ticket(client, dev, access)
        assert refused(client, auth_frame(thief, tkt)) == (4401, "ticket_key")
        # a proof that names the owner's key and is signed by another one
        assert refused(client, auth_frame(dev, tkt, signer=thief)) == (4401, "signature")
        with client.websocket_connect(WS) as ws:  # the refusals did not spend it
            ws.send_text(auth_frame(dev, tkt))
            assert ws.receive_json()["type"] == "ready"


def test_ticket_and_proof_refusals(harness: Harness, sessions: SessionService, clock: FakeTime) -> None:
    dev = Device(clock)
    with running(harness, sessions) as client:
        access = sign_in(client, dev)["access_token"]
        assert refused(client, auth_frame(dev, "A" * 43)) == (4401, "ticket_known")
        assert refused(client, auth_frame(dev, "short")) == (4401, "ticket_format")
        assert refused(client, auth_frame(dev, 7)) == (4401, "ticket_format")
        tkt = ticket(client, dev, access)
        assert refused(client, auth_frame(dev, tkt, htu=url("/v1/read"))) == (4401, "htu")
        assert refused(client, auth_frame(dev, tkt, htu="ws://vcloak.test/v1/ws")) == (4401, "htu")
        assert refused(client, json.dumps({"ticket": tkt, "dpop": dev.proof("POST", WS_URL)})) == (4401, "htm")
        assert refused(client, auth_frame(dev, tkt, iat=clock() - 300)) == (4401, "iat")
        assert refused(client, json.dumps({"ticket": tkt, "dpop": None})) == (4401, "proof_format")
        # an access token is not a ticket, and a ticket is not an access token
        assert refused(client, auth_frame(dev, access)) == (4401, "ticket_format")
        r = client.post("/v1/read", json={"conv_token": "c" * 32, "win": 0},
                        headers={"DPoP": dev.proof("POST", url("/v1/read"), tkt), "Authorization": f"DPoP {tkt}"})
        assert r.status_code == 401 and r.json()["failed_check"] == "token_format"
        # a proof is good for one handshake: the captured frame cannot be sent again with a new ticket
        proof = dev.proof("GET", WS_URL)
        with client.websocket_connect(WS) as ws:
            ws.send_text(json.dumps({"ticket": tkt, "dpop": proof}))
            assert ws.receive_json()["type"] == "ready"
        again = ticket(client, dev, access)
        assert refused(client, json.dumps({"ticket": again, "dpop": proof})) == (4401, "jti")


def test_a_ticket_expires_after_30_seconds(harness: Harness, sessions: SessionService, clock: FakeTime) -> None:
    dev = Device(clock)
    with running(harness, sessions) as client:
        access = sign_in(client, dev)["access_token"]
        late, in_time = ticket(client, dev, access), ticket(client, dev, access)
        clock.advance(29)
        with client.websocket_connect(WS) as ws:
            ws.send_text(auth_frame(dev, in_time))
            assert ws.receive_json()["type"] == "ready"
        clock.advance(1)
        assert refused(client, auth_frame(dev, late)) == (4401, "ticket_exp")


@pytest.mark.parametrize("frame", ["not json", "[]", '{"ticket": "x"}', '{"ticket": "x", "dpop": "y", "more": 1}',
                                   '"text"', "x" * 9000])
def test_a_first_frame_of_another_shape_closes_the_socket(harness: Harness, sessions: SessionService,
                                                         frame: str) -> None:
    with running(harness, sessions) as client:
        assert refused(client, frame) == (1008, "auth_frame")


def test_a_socket_without_a_ticket_is_closed_after_the_timeout(harness: Harness, sessions: SessionService,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_app, "WS_AUTH_TIMEOUT_S", 0.05)
    with running(harness, sessions) as client, client.websocket_connect(WS) as ws:
        assert closed(ws) == (4408, "auth_timeout")


def test_a_client_frame_after_the_ticket_closes_the_socket(harness: Harness, sessions: SessionService,
                                                          clock: FakeTime) -> None:
    dev = Device(clock)
    with running(harness, sessions) as client:
        access = sign_in(client, dev)["access_token"]
        with client.websocket_connect(WS) as ws:
            ws.send_text(auth_frame(dev, ticket(client, dev, access)))
            assert ws.receive_json()["type"] == "ready"
            ws.send_text('{"subscribe": "' + "c" * 32 + '"}')
            assert closed(ws) == (1008, "unexpected_frame")
        assert len(client.app.state.sockets) == 0  # type: ignore[attr-defined]


def test_logout_closes_the_sockets_of_that_login_only(harness: Harness, sessions: SessionService,
                                                     clock: FakeTime) -> None:
    dev = Device(clock)
    with running(harness, sessions) as client:
        first, second = sign_in(client, dev), sign_in(client, dev)
        with client.websocket_connect(WS) as w1, client.websocket_connect(WS) as w2:
            w1.send_text(auth_frame(dev, ticket(client, dev, first["access_token"])))
            w2.send_text(auth_frame(dev, ticket(client, dev, second["access_token"])))
            assert w1.receive_json()["type"] == "ready" == w2.receive_json()["type"]
            unspent = ticket(client, dev, first["access_token"])
            assert call(client, dev, first["access_token"], "/v1/auth/logout").status_code == 204
            assert closed(w1) == (4001, "session_ended")  # at once: no epoch has passed
            step(client, harness)
            assert w2.receive_json()["type"] == "tick"
            # a ticket of the login that ended opens nothing
            assert refused(client, auth_frame(dev, unspent)) == (4401, "ticket_session")


def test_refresh_reuse_closes_the_socket(harness: Harness, sessions: SessionService, clock: FakeTime) -> None:
    dev = Device(clock)
    with running(harness, sessions) as client:
        tokens = sign_in(client, dev)
        with client.websocket_connect(WS) as ws:
            ws.send_text(auth_frame(dev, ticket(client, dev, tokens["access_token"])))
            assert ws.receive_json()["type"] == "ready"
            path = "/v1/auth/refresh"
            for expected in (200, 401):  # the token is spent, then presented again
                r = client.post(path, json={"refresh_token": tokens["refresh_token"]},
                                headers=dev.headers("POST", url(path)))
                assert r.status_code == expected
            assert closed(ws) == (4001, "session_ended")


def test_a_socket_ends_when_its_login_expires(harness: Harness, sessions: SessionService, clock: FakeTime) -> None:
    dev = Device(clock)
    with running(harness, sessions) as client:
        access = sign_in(client, dev)["access_token"]
        with client.websocket_connect(WS) as ws:
            ws.send_text(auth_frame(dev, ticket(client, dev, access)))
            assert ws.receive_json()["type"] == "ready"
            clock.advance(sessions.config.refresh_ttl_s - 1)
            step(client, harness)
            assert ws.receive_json()["type"] == "tick"  # the access token is long expired; the login is not
            clock.advance(1)
            step(client, harness)
            assert closed(ws) == (4001, "session_ended")


def test_a_login_holds_a_bounded_number_of_sockets(harness: Harness, sessions: SessionService,
                                                  clock: FakeTime) -> None:
    dev = Device(clock)
    with running(harness, sessions) as client:
        access = sign_in(client, dev)["access_token"]
        open_sockets = []
        try:
            for _ in range(service_app.WS_MAX_PER_SESSION):
                cm = client.websocket_connect(WS)
                ws = cm.__enter__()
                open_sockets.append(cm)
                ws.send_text(auth_frame(dev, ticket(client, dev, access)))
                assert ws.receive_json()["type"] == "ready"
            assert refused(client, auth_frame(dev, ticket(client, dev, access))) == (4429, "too_many_sockets")
        finally:
            for cm in open_sockets:
                cm.__exit__(None, None, None)


def test_shutdown_closes_the_sockets(harness: Harness, sessions: SessionService, clock: FakeTime) -> None:
    dev = Device(clock)
    with running(harness, sessions) as client:
        access = sign_in(client, dev)["access_token"]
        hub = client.app.state.sockets  # type: ignore[attr-defined]
        with client.websocket_connect(WS) as ws:
            ws.send_text(auth_frame(dev, ticket(client, dev, access)))
            assert ws.receive_json()["type"] == "ready"
            assert client.portal is not None
            client.portal.call(hub.close_all)
            assert closed(ws) == (1001, "shutdown")


def test_the_baseline_backend_pushes_on_the_same_cadence(sessions: SessionService, clock: FakeTime) -> None:
    h = baseline_harness(SqliteBaselineStore())
    dev = Device(clock)
    with running(h, sessions) as client:
        access = sign_in(client, dev)["access_token"]
        with client.websocket_connect(WS) as ws:
            ws.send_text(auth_frame(dev, ticket(client, dev, access)))
            assert ws.receive_json()["type"] == "ready"
            frames = [ws.receive_json() for _ in range(3)]
            assert all(set(f) == {"type", "win"} and f["type"] == "tick" for f in frames)


def test_the_baseline_backend_has_no_ticker_without_listeners() -> None:
    h = baseline_harness(SqliteBaselineStore())
    with running(h, None):
        assert h.backend._ticker is None and h.clock.now_ms() == 0


# ── the service object ───────────────────────────────────────────────────────

def session_of(svc: SessionService, dev: Device, name: str = "alice") -> Verdict:
    """A verified session of `name` on `dev`, as a route hands it to `issue_ws_ticket`."""
    login_url, read_url = url("/v1/auth/login"), url("/v1/read")

    async def go() -> Verdict:
        if name not in svc.accounts:
            assert (await svc.register(name, PASSWORD, ip="198.51.100.7")).status == "ok"
        result = await svc.login(name, PASSWORD, ip="198.51.100.7", method="POST", url=login_url,
                                 proofs=[dev.proof("POST", login_url)])
        assert result.tokens is not None
        access = result.tokens.access_token
        return svc.verify("POST", read_url, [dev.proof("POST", read_url, access)], f"DPoP {access}")
    verdict = asyncio.run(go())
    assert verdict.ok
    return verdict


def test_open_socket_evaluates_every_check(sessions: SessionService, clock: FakeTime) -> None:
    dev = Device(clock)
    session = session_of(sessions, dev)
    grant = sessions.open_socket(WS_URL, None, None)
    assert grant.failed == PROOF_CHECKS + TICKET_CHECKS and not grant.ok and grant.failed_check == "proof_format"
    assert (grant.sub, grant.family) == ("", "")
    tkt = sessions.issue_ws_ticket(session)
    assert tkt.expires_in == 30
    grant = sessions.open_socket(WS_URL, tkt.ticket, Device(clock).proof("POST", WS_URL))
    assert grant.failed == ("htm", "ticket_key")
    grant = sessions.open_socket(WS_URL, tkt.ticket, dev.proof("GET", WS_URL))
    assert grant.ok and grant.failed_check is None and (grant.sub, grant.family) == ("alice", session.family)
    assert sessions.open_socket(WS_URL, tkt.ticket, dev.proof("GET", WS_URL)).failed == ("ticket_unused",)
    sessions.close()


def test_the_ticket_table_holds_hashes_and_is_bounded_per_login(sessions: SessionService, clock: FakeTime) -> None:
    dev = Device(clock)
    session = session_of(sessions, dev)
    tickets = [sessions.issue_ws_ticket(session).ticket for _ in range(TICKETS_PER_FAMILY + 3)]
    assert len(sessions._tickets) == TICKETS_PER_FAMILY
    assert not any(t.encode() in key or key in t.encode() for t in tickets for key in sessions._tickets)
    dropped = sessions.open_socket(WS_URL, tickets[0], dev.proof("GET", WS_URL))
    assert dropped.failed == TICKET_CHECKS[1:]  # not in the table: every check that reads the record fails
    assert sessions.open_socket(WS_URL, tickets[-1], dev.proof("GET", WS_URL)).ok
    clock.advance(31)
    sessions.issue_ws_ticket(session)  # issuing forgets what expired, spent or not
    assert len(sessions._tickets) == 1
    with pytest.raises(ValueError, match="verified session"):
        sessions.issue_ws_ticket(Verdict(("jti",)))
    with pytest.raises(ValueError, match="verified session"):
        sessions.issue_ws_ticket(Verdict((), jkt=dev.jkt))  # a proof without a token (login, refresh)
    sessions.close()


@pytest.mark.parametrize("received, origin, expected", [
    ("ws://vcloak.test/v1/ws", None, "http://vcloak.test/v1/ws"),
    ("wss://vcloak.test/v1/ws", None, "https://vcloak.test/v1/ws"),
    ("WS://127.0.0.1:8000/v1/ws?x=1", None, "http://127.0.0.1:8000/v1/ws?x=1"),
    ("http://vcloak.test/v1/ws", None, "http://vcloak.test/v1/ws"),
    ("ws://10.0.0.5:8000/v1/ws", "https://chat.example", "https://chat.example/v1/ws"),
])
def test_socket_url(received: str, origin: str | None, expected: str) -> None:
    svc = SessionService(SessionConfig(password=CHEAP, public_origin=origin))
    assert svc.socket_url(received, "/v1/ws") == expected


# ── the epoch hook ───────────────────────────────────────────────────────────

def test_the_scheduler_calls_its_listeners_after_every_boundary() -> None:
    class Engine:
        slots, epoch_ms, fail = 4, 200, False

        def window_of(self, epoch: int) -> int:
            return epoch // 5

        def write_epoch(self, epoch: int, batch: list[Any]) -> list[Any]:
            if self.fail:
                raise RuntimeError("engine")
            return []

        def reshuffle_window(self, win: int, rows: list[Any]) -> list[Any]:
            return rows

    engine, calls = Engine(), []
    sched = EpochScheduler(engine, SqliteRepo(), SimClock())  # type: ignore[arg-type]

    def broken() -> None:
        raise RuntimeError("listener")

    sched.on_epoch(broken)
    sched.on_epoch(lambda: calls.append(sched.epochs))
    assert asyncio.run(sched.run(2)) == 2
    engine.fail = True
    assert asyncio.run(sched.run(1)) == 1
    assert calls == [1, 2, 2] and sched.errors == 1  # a failed epoch is a boundary too


# ── the CLI switch ───────────────────────────────────────────────────────────

def test_cli_sessions_switch(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import uvicorn

    started: list[tuple[str, bool]] = []
    monkeypatch.setattr(uvicorn, "run",
                        lambda app, host, **kw: started.append((host, app.state.sessions is not None)))
    base = ["serve", "--dev", "--store", "sqlite"]
    assert cli.main(base) == 0
    assert cli.main([*base, "--sessions"]) == 0
    assert cli.main([*base, "--sessions", "--host", "0.0.0.0"]) == 0  # a session is asked for: any address
    assert cli.main([*base, "--host", "0.0.0.0"]) == 2  # the open API stays on the loopback
    assert started == [("127.0.0.1", False), ("127.0.0.1", True), ("0.0.0.0", True)]
    assert "--sessions" in capsys.readouterr().err


def test_cli_public_origin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import uvicorn

    origins: list[str | None] = []
    monkeypatch.setattr(uvicorn, "run",
                        lambda app, host, **kw: origins.append(app.state.sessions.config.public_origin))
    base = ["serve", "--dev", "--store", "sqlite"]
    assert cli.main([*base, "--sessions", "--public-origin", "https://chat.example"]) == 0
    assert origins == ["https://chat.example"]
    assert cli.main([*base, "--public-origin", "https://chat.example"]) == 2  # nothing would read it
    assert cli.main([*base, "--sessions", "--public-origin", "chat.example"]) == 2
    assert origins == ["https://chat.example"] and "--public-origin" in capsys.readouterr().err
    a = cli.build_parser().parse_args(base)
    assert cli.build_sessions(a) is None and (a.sessions, a.public_origin) == (False, None)
