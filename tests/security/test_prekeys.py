"""M12 S2: the prekey routes of the session layer (ADR-019).

The app runs in-process (the numpy simulator behind it, a SQLite store); the client is tests/dpop_client.py.
Nothing here measures anything."""
from __future__ import annotations

import base64
import logging
import os

import httpx
import pytest
from test_session_api import BASE, CHEAP, sign_in

from dpop_client import Device
from service_contract import Harness, vcloak_harness
from vcloak.service.session import SessionConfig, SessionService
from vcloak.storage.repo import SqliteRepo

PATH = "/v1/prekeys"


def key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


@pytest.fixture
def harness() -> Harness:
    return vcloak_harness(SqliteRepo())


@pytest.fixture
def sessions() -> SessionService:
    return SessionService(SessionConfig(password=CHEAP))


async def put(client: httpx.AsyncClient, dev: Device, access: str, prekey_b64: object) -> httpx.Response:
    return await client.put(PATH, json={"prekey_b64": prekey_b64}, headers=dev.headers("PUT", BASE + PATH, access))


def test_publish_and_fetch(harness: Harness, sessions: SessionService) -> None:
    dev, first, second = Device(), key(), key()

    async def scenario(client: httpx.AsyncClient) -> None:
        access = (await sign_in(client, dev, "alice"))["access_token"]
        r = await put(client, dev, access, first)
        assert r.status_code == 204 and r.content == b""
        r = await client.get(f"{PATH}/alice")  # no session: a fetch names no account
        assert r.status_code == 200 and r.json() == {"username": "alice", "prekey_b64": first}
        assert r.headers["cache-control"] == "no-store"
        assert (await put(client, dev, access, second)).status_code == 204  # the newest replaces it
        assert (await client.get(f"{PATH}/alice")).json()["prekey_b64"] == second
    harness.serve(scenario, sessions=sessions)


def test_an_unknown_name_and_an_account_without_a_prekey_get_the_same_answer(harness: Harness,
                                                                           sessions: SessionService) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        await sign_in(client, Device(), "alice")  # an account, no prekey
        answers = [await client.get(f"{PATH}/{name}") for name in ("alice", "nobody", "NOT A NAME")]
        assert [r.status_code for r in answers] == [404, 404, 404]
        assert all(r.json() == {"error": "no_prekey"} for r in answers)
    harness.serve(scenario, sessions=sessions)


def test_publishing_needs_the_session_and_only_sets_the_own_account(harness: Harness,
                                                                   sessions: SessionService) -> None:
    alice, bob = Device(), Device()

    async def scenario(client: httpx.AsyncClient) -> None:
        a = (await sign_in(client, alice, "alice"))["access_token"]
        b = (await sign_in(client, bob, "bob"))["access_token"]
        k = key()
        cases: list[tuple[dict[str, str], str]] = [
            ({}, "proof_format"),
            ({"Authorization": f"DPoP {a}"}, "proof_format"),
            (bob.headers("PUT", BASE + PATH, a), "key_binding"),  # Alice's token under Bob's key
            (alice.headers("POST", BASE + PATH, a), "htm"),
        ]
        for headers, failed in cases:
            r = await client.put(PATH, json={"prekey_b64": k}, headers=headers)
            assert r.status_code == 401 and r.json()["failed_check"] == failed, r.text
        # the session is checked before the body
        assert (await client.put(PATH, json={"nonsense": 1})).status_code == 401
        assert (await client.get(f"{PATH}/alice")).status_code == 404  # nothing refused was stored
        assert (await put(client, bob, b, k)).status_code == 204
        assert (await client.get(f"{PATH}/bob")).json()["prekey_b64"] == k
        assert (await client.get(f"{PATH}/alice")).status_code == 404  # the body names no account
    harness.serve(scenario, sessions=sessions)


@pytest.mark.parametrize("bad", ["", "short", base64.b64encode(bytes(31)).decode(),
                                 base64.b64encode(bytes(33)).decode(),
                                 base64.urlsafe_b64encode(b"\xff" * 32).decode(), "A" * 44, 7, None])
def test_only_32_bytes_of_base64_are_a_prekey(harness: Harness, sessions: SessionService, bad: object) -> None:
    dev = Device()

    async def scenario(client: httpx.AsyncClient) -> None:
        access = (await sign_in(client, dev, "alice"))["access_token"]
        r = await put(client, dev, access, bad)
        assert r.status_code == 422 and r.json()["fields"][0]["field"] == "prekey_b64"
        assert str(bad) not in r.text or bad in ("", "short")  # never the rejected value
        assert (await client.get(f"{PATH}/alice")).status_code == 404
    harness.serve(scenario, sessions=sessions)


def test_without_sessions_there_are_no_prekey_routes(harness: Harness) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await client.get(f"{PATH}/alice")).status_code == 404
        assert (await client.put(PATH, json={"prekey_b64": key()})).status_code in (404, 405)
    harness.serve(scenario)


def test_the_prekey_routes_log_nothing(harness: Harness, sessions: SessionService, caplog: pytest.LogCaptureFixture,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logging.getLogger("vcloak"), "propagate", True)
    dev, k = Device(), key()

    async def scenario(client: httpx.AsyncClient) -> None:
        access = (await sign_in(client, dev, "alice"))["access_token"]
        await put(client, dev, access, k)
        await client.get(f"{PATH}/alice")
        await client.get(f"{PATH}/nobody")

    with caplog.at_level(logging.DEBUG, logger="vcloak"):
        harness.serve(scenario, sessions=sessions)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "prekey" not in text and k not in text and "alice" not in text and "nobody" not in text
