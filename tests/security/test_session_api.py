"""M11 S1-S4 over HTTP: the session routes and the DPoP check in front of the message routes.

The app runs in-process (the numpy simulator behind it, a SQLite store); the client is tests/dpop_client.py.
Nothing here measures anything."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from dpop_client import Device
from service_contract import Harness, payload, read, token, vcloak_harness
from vcloak.service.models import decode_payload, encode_payload
from vcloak.service.session import PasswordParams, SessionConfig, SessionService
from vcloak.storage.repo import SqliteRepo

BASE = "http://vcloak.test"
PASSWORD = "correct horse battery"
CHEAP = PasswordParams(t=1, m_kib=64, p=1)  # tests only


def url(path: str) -> str:
    return BASE + path


@pytest.fixture
def harness() -> Harness:
    return vcloak_harness(SqliteRepo())


@pytest.fixture
def sessions() -> SessionService:
    return SessionService(SessionConfig(password=CHEAP))


def serve(harness: Harness, sessions: SessionService,
          scenario: Callable[[httpx.AsyncClient], Awaitable[Any]]) -> Any:
    return harness.serve(scenario, sessions=sessions)


async def register(client: httpx.AsyncClient, name: str = "alice", password: str = PASSWORD) -> httpx.Response:
    return await client.post("/v1/auth/register", json={"username": name, "password": password})


async def login(client: httpx.AsyncClient, dev: Device, name: str = "alice", password: str = PASSWORD,
                **proof_kw: Any) -> httpx.Response:
    path = "/v1/auth/login"
    return await client.post(path, json={"username": name, "password": password},
                             headers=dev.headers("POST", url(path), **proof_kw))


async def sign_in(client: httpx.AsyncClient, dev: Device, name: str = "alice") -> dict[str, Any]:
    assert (await register(client, name)).status_code in (201, 409)
    r = await login(client, dev, name)
    assert r.status_code == 200, r.text
    return r.json()


async def call(client: httpx.AsyncClient, dev: Device, access: str, path: str, body: Any = None,
               **proof_kw: Any) -> httpx.Response:
    return await client.post(path, json=body, headers=dev.headers("POST", url(path), access, **proof_kw))


def test_register_login_and_an_authenticated_round_trip(harness: Harness, sessions: SessionService) -> None:
    dev, conv = Device(), token("a")

    async def scenario(client: httpx.AsyncClient) -> None:
        r = await register(client)
        assert r.status_code == 201 and r.json() == {"registered": True}
        r = await login(client, dev)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        body = r.json()
        assert set(body) == {"access_token", "refresh_token", "expires_in", "token_type"}
        assert body["token_type"] == "DPoP" and body["expires_in"] == 600
        access = body["access_token"]
        for i in range(3):
            r = await call(client, dev, access, "/v1/messages",
                           {"conv_token": conv, "payload_b64": encode_payload(payload(i))})
            assert r.status_code == 202, r.text
        await harness.step(6)  # the window closes and is re-shuffled
        r = await call(client, dev, access, "/v1/read", {"conv_token": conv, "win": 0})
        assert r.status_code == 200, r.text
        assert [decode_payload(p) for p in r.json()["payloads_b64"]] == [payload(i) for i in range(3)]
    serve(harness, sessions, scenario)


def test_message_routes_refuse_a_request_without_a_session(harness: Harness, sessions: SessionService) -> None:
    dev, conv = Device(), token("a")

    async def scenario(client: httpx.AsyncClient) -> None:
        access = (await sign_in(client, dev))["access_token"]
        body = {"conv_token": conv, "payload_b64": encode_payload(payload(0))}
        cases: list[tuple[dict[str, str], str, str]] = [
            ({}, "invalid_dpop_proof", "proof_format"),
            ({"Authorization": f"Bearer {access}"}, "invalid_dpop_proof", "proof_format"),
            ({"Authorization": f"DPoP {access}"}, "invalid_dpop_proof", "proof_format"),
            (dev.headers("POST", url("/v1/read"), access), "invalid_dpop_proof", "htu"),
            (dev.headers("GET", url("/v1/messages"), access), "invalid_dpop_proof", "htm"),
            (Device().headers("POST", url("/v1/messages"), access), "invalid_token", "key_binding"),
            ({**dev.headers("POST", url("/v1/messages"), access), "Authorization": f"Bearer {access}"},
             "invalid_token", "authorization"),
        ]
        for headers, error, failed_check in cases:
            r = await client.post("/v1/messages", json=body, headers=headers)
            assert r.status_code == 401, (failed_check, r.text)
            assert r.json() == {"error": error, "failed_check": failed_check}
            assert r.headers["www-authenticate"] == (
                f'DPoP error="{error}", error_description="{failed_check}", algs="ES256"')
            assert r.headers["cache-control"] == "no-store"
        r = await client.post("/v1/read", json={"conv_token": conv, "win": 0})
        assert r.status_code == 401
        # the session is checked before the body: a malformed request without one learns nothing
        r = await client.post("/v1/messages", json={"nonsense": True})
        assert r.status_code == 401
        r = await call(client, dev, access, "/v1/messages", {"nonsense": True})
        assert r.status_code == 422
        assert harness.backend.stats()["queued"] == 0  # nothing refused reached the queue
        for path in ("/v1/windows", "/healthz"):  # public parameters and counters stay open
            assert (await client.get(path)).status_code == 200
    serve(harness, sessions, scenario)


def test_replayed_request_is_refused(harness: Harness, sessions: SessionService) -> None:
    dev, conv = Device(), token("a")

    async def scenario(client: httpx.AsyncClient) -> None:
        access = (await sign_in(client, dev))["access_token"]
        body = {"conv_token": conv, "payload_b64": encode_payload(payload(0))}
        headers = dev.headers("POST", url("/v1/messages"), access)
        assert (await client.post("/v1/messages", json=body, headers=headers)).status_code == 202
        r = await client.post("/v1/messages", json=body, headers=headers)  # the captured request, sent again
        assert r.status_code == 401 and r.json()["failed_check"] == "jti"
        assert harness.backend.stats()["queued"] == 1
    serve(harness, sessions, scenario)


def test_without_sessions_the_api_is_open_and_has_no_auth_routes(harness: Harness) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        r = await client.post("/v1/messages", json={"conv_token": token("a"),
                                                     "payload_b64": encode_payload(payload(0))})
        assert r.status_code == 202
        assert await read(client, token("a"), 0) == []
        assert (await register(client)).status_code == 404
    harness.serve(scenario)


def test_register_and_login_errors(harness: Harness, sessions: SessionService) -> None:
    dev = Device()

    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await register(client)).status_code == 201
        r = await register(client, password="another password")
        assert r.status_code == 409 and r.json() == {"error": "username_taken"}
        r = await register(client, "bob", "short")
        assert r.status_code == 422 and r.json() == {
            "error": "invalid_request", "fields": [{"field": "password", "reason": "string_too_short"}]}
        r = await register(client, "Bob Smith", PASSWORD + " and more")
        assert r.status_code == 422 and PASSWORD not in r.text and "Bob" not in r.text
        for name, password in (("alice", "wrong password"), ("nobody", PASSWORD)):
            r = await login(client, dev, name, password)
            assert r.status_code == 401 and r.json() == {"error": "invalid_credentials"}
            assert "www-authenticate" not in r.headers
        r = await client.post("/v1/auth/login", json={"username": "alice", "password": PASSWORD})
        assert r.status_code == 401 and r.json() == {"error": "invalid_dpop_proof", "failed_check": "proof_format"}
        r = await login(client, dev, iat=0)
        assert r.status_code == 401 and r.json()["failed_check"] == "iat"
        assert (await login(client, dev)).status_code == 200
    serve(harness, sessions, scenario)


def test_login_guessing_hits_the_rate_limit(harness: Harness, sessions: SessionService) -> None:
    dev = Device()

    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await register(client)).status_code == 201
        for _ in range(sessions.config.login_account_max):
            assert (await login(client, dev, password="guess guess")).status_code == 401
        r = await login(client, dev)  # the right password, too late
        assert r.status_code == 429 and r.json() == {"error": "rate_limited"}
        assert 0 < int(r.headers["retry-after"]) <= sessions.config.login_account_window_s
    serve(harness, sessions, scenario)


def test_refresh_rotates_and_a_reused_token_revokes_the_family(harness: Harness, sessions: SessionService,
                                                               caplog: pytest.LogCaptureFixture,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    dev, thief, conv = Device(), Device(), token("a")
    path = "/v1/auth/refresh"
    monkeypatch.setattr(logging.getLogger("vcloak"), "propagate", True)

    async def refresh(client: httpx.AsyncClient, who: Device, refresh_token: str) -> httpx.Response:
        return await client.post(path, json={"refresh_token": refresh_token}, headers=who.headers("POST", url(path)))

    async def scenario(client: httpx.AsyncClient) -> list[str]:
        first = await sign_in(client, dev)
        seen = [first["access_token"], first["refresh_token"]]
        r = await client.post(path, json={"refresh_token": first["refresh_token"]})
        assert r.status_code == 401 and r.json()["failed_check"] == "proof_format"  # no proof, token not spent
        r = await refresh(client, thief, first["refresh_token"])  # a stolen refresh token without the key
        assert r.status_code == 401 and r.json() == {"error": "invalid_grant", "reason": "key_binding"}
        r = await refresh(client, dev, first["refresh_token"])
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        second = r.json()
        seen += [second["access_token"], second["refresh_token"]]
        assert second["refresh_token"] != first["refresh_token"]
        body = {"conv_token": conv, "payload_b64": encode_payload(payload(0))}
        assert (await call(client, dev, second["access_token"], "/v1/messages", body)).status_code == 202
        r = await refresh(client, dev, first["refresh_token"])  # the spent token comes back
        assert r.status_code == 401 and r.json() == {"error": "invalid_grant", "reason": "reuse"}
        r = await refresh(client, dev, second["refresh_token"])
        assert r.status_code == 401 and r.json() == {"error": "invalid_grant", "reason": "family_revoked"}
        r = await call(client, dev, second["access_token"], "/v1/messages", body)
        assert r.status_code == 401 and r.json() == {"error": "invalid_token", "failed_check": "token_revoked"}
        r = await client.post(path, json={"refresh_token": "not-a-token"}, headers=dev.headers("POST", url(path)))
        assert r.status_code == 422
        assert (await login(client, dev)).status_code == 200  # the owner logs in again
        return seen

    with caplog.at_level(logging.DEBUG, logger="vcloak"):
        seen = serve(harness, sessions, scenario)
    lines = [r.getMessage() for r in caplog.records]
    assert "event=family_revoked error=refresh_reuse" in lines
    text = "\n".join(lines)
    for secret in (*seen, conv, PASSWORD, "alice", dev.jkt):
        assert secret not in text


def test_logout_revokes_the_session(harness: Harness, sessions: SessionService) -> None:
    dev = Device()

    async def scenario(client: httpx.AsyncClient) -> None:
        tokens = await sign_in(client, dev)
        other = await sign_in(client, dev)  # a second login: not touched by the logout of the first
        access = tokens["access_token"]
        r = await client.post("/v1/auth/logout")
        assert r.status_code == 401 and "www-authenticate" in r.headers
        r = await call(client, Device(), access, "/v1/auth/logout")
        assert r.status_code == 401 and r.json()["failed_check"] == "key_binding"
        r = await call(client, dev, access, "/v1/auth/logout")
        assert r.status_code == 204 and r.content == b""
        r = await call(client, dev, access, "/v1/read", {"conv_token": token("a"), "win": 0})
        assert r.status_code == 401 and r.json()["failed_check"] == "token_revoked"
        r = await client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]},
                              headers=dev.headers("POST", url("/v1/auth/refresh")))
        assert r.status_code == 401 and r.json()["reason"] == "family_revoked"
        r = await call(client, dev, other["access_token"], "/v1/read", {"conv_token": token("a"), "win": 0})
        assert r.status_code == 200
    serve(harness, sessions, scenario)


def test_public_origin_is_what_a_proof_must_name(harness: Harness) -> None:
    sessions = SessionService(SessionConfig(password=CHEAP, public_origin="https://chat.example"))
    dev = Device()

    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await register(client)).status_code == 201
        r = await login(client, dev)  # a proof for the address the server listens on
        assert r.status_code == 401 and r.json()["failed_check"] == "htu"
        r = await client.post("/v1/auth/login", json={"username": "alice", "password": PASSWORD},
                              headers=dev.headers("POST", "https://chat.example/v1/auth/login"))
        assert r.status_code == 200
    serve(harness, sessions, scenario)
