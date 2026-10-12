"""The service contract (M10 A3): one set of API tests, run against the V-cloak backend and the
baseline backend, on SQLite (tests/unit) and on PostgreSQL (tests/integration).

A subclass provides the `harness` fixture. Time is a `SimClock` the test moves: `Harness.step(n)`
lets n epochs pass. Nothing here measures anything: the backend is the numpy simulator.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from testkeys import TEST_K_MASTER
from vcloak.crypto.client import PAYLOAD_LEN
from vcloak.gpu.runtime import get_backend
from vcloak.service.app import VcloakBackend, create_app
from vcloak.service.baseline import BaselineBackend
from vcloak.service.models import decode_payload, encode_payload
from vcloak.service.scheduler import SimClock

EPOCH_MS = 200
WINDOW_S = 1  # five epochs per window
EPOCHS_PER_WINDOW = 1000 * WINDOW_S // EPOCH_MS
SLOTS = 64
BUCKETS = 4  # few buckets: conversations share bucket-windows
CAND_K = 128


def token(name: str) -> str:
    """A conversation token as a client would derive one (opaque to the server)."""
    return hashlib.sha256(b"test-conv:" + name.encode()).hexdigest()[:32]


def payload(i: int, seed: int = 0) -> bytes:
    """A stand-in ciphertext of the exact size; the first 4 bytes carry the test's arrival index."""
    return i.to_bytes(4, "big") + random.Random(seed * 1_000_003 + i).randbytes(PAYLOAD_LEN - 4)


def index_of(p: bytes) -> int:
    return int.from_bytes(p[:4], "big")


def fixed_master() -> bytearray:
    """A fresh copy of the fixed TEST master, as a key provider hands it out."""
    return bytearray(TEST_K_MASTER)


@dataclass
class Harness:
    backend: Any
    clock: SimClock
    store: Any  # the Repo (vcloak) or the BaselineStore

    @property
    def vcloak(self) -> bool:
        return self.backend.mode == "vcloak"

    async def step(self, n: int = 1) -> None:
        """Let `n` epochs pass."""
        if self.vcloak:
            assert await self.backend.scheduler.run(n) == n
        else:
            self.clock.advance(n * EPOCH_MS)

    def serve(self, scenario: Callable[[httpx.AsyncClient], Awaitable[Any]], **app_kw: Any) -> Any:
        """Start the app (lifespan included), run `scenario(client)` against it, shut it down."""
        async def main() -> Any:
            app = create_app(self.backend, **app_kw)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://vcloak.test") as client:
                    return await scenario(client)
        return asyncio.run(main())


def vcloak_harness(repo: Any, **kw: Any) -> Harness:
    clock = kw.pop("clock", None) or SimClock()
    opts = dict(gpu=get_backend(), slots=SLOTS, buckets=BUCKETS, window_s=WINDOW_S, epoch_ms=EPOCH_MS,
                cand_k=CAND_K, autorun=False)
    opts.update(kw)
    return Harness(VcloakBackend(repo, clock, fixed_master, **opts), clock, repo)


def baseline_harness(store: Any) -> Harness:
    clock = SimClock()
    return Harness(BaselineBackend(store, clock, window_s=WINDOW_S, epoch_ms=EPOCH_MS), clock, store)


async def post(client: httpx.AsyncClient, conv: str, p: bytes) -> httpx.Response:
    return await client.post("/v1/messages", json={"conv_token": conv, "payload_b64": encode_payload(p)})


async def read(client: httpx.AsyncClient, conv: str, win: int) -> list[bytes]:
    r = await client.post("/v1/read", json={"conv_token": conv, "win": win})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["win"] == win
    return [decode_payload(p) for p in body["payloads_b64"]]


async def send_across_windows(h: Harness, client: httpx.AsyncClient, n: int = 200, windows: int = 3,
                              n_convs: int = 4, seed: int = 1) -> dict[str, list[bytes]]:
    """`n` messages of `n_convs` conversations spread over the epochs of `windows` windows, then one
    more epoch so that the last window is closed. Returns what each conversation sent, in order."""
    rng = random.Random(seed)
    convs = [token(f"conv-{seed}-{i}") for i in range(n_convs)]
    sent: dict[str, list[bytes]] = {c: [] for c in convs}
    epochs = windows * EPOCHS_PER_WINDOW
    i = 0
    for e in range(epochs):
        for _ in range(n // epochs + (1 if e < n % epochs else 0)):
            conv, p = rng.choice(convs), payload(i, seed)
            assert (await post(client, conv, p)).status_code == 202
            sent[conv].append(p)
            i += 1
        await h.step()
    assert i == n
    await h.step()
    return sent


class ServiceContract:
    """What both modes must do. Subclasses define the `harness` fixture."""

    def test_round_trip_200_messages_across_3_windows_in_order(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            sent = await send_across_windows(harness, client)
            assert sum(map(len, sent.values())) == 200
            for conv, expected in sent.items():
                per_window = [await read(client, conv, w) for w in range(4)]
                assert sum(map(len, per_window[:3])) == len(expected) and per_window[3] == []
                assert all(per_window[w] for w in range(3))  # the conversation spans the three windows
                assert [p for part in per_window for p in part] == expected

        harness.serve(scenario)

    def test_unknown_conversation_and_empty_window_read_empty(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            a, b = token("a"), token("b")
            assert (await post(client, a, payload(0))).status_code == 202
            await harness.step(2)
            assert await read(client, a, 0) == [payload(0)]
            assert await read(client, b, 0) == []  # another conversation sees nothing of it
            assert await read(client, a, 7) == []  # a window nothing was written to

        harness.serve(scenario)

    def test_windows_route_follows_the_clock(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            first = (await client.get("/v1/windows")).json()
            assert first == {"win": 0, "window_s": WINDOW_S, "epoch_ms": EPOCH_MS, "visible_round": "window",
                             "mode": harness.backend.mode}
            await harness.step(2 * EPOCHS_PER_WINDOW)
            assert (await client.get("/v1/windows")).json()["win"] == 2

        harness.serve(scenario)

    def test_health(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            r = await client.get("/healthz")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok" and body["ready"] is True and body["mode"] == harness.backend.mode
            assert set(body) == {"status", "mode", "ready", "epochs", "overflow", "missed", "queued"}

        harness.serve(scenario)

    @pytest.mark.parametrize("size", [0, 1, PAYLOAD_LEN - 1, PAYLOAD_LEN + 1, 2 * PAYLOAD_LEN])
    def test_payload_must_be_exactly_the_ciphertext_size(self, harness: Harness, size: int) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            r = await post(client, token("a"), bytes(size))
            assert r.status_code == 422
            assert r.json()["error"] == "invalid_request"
            await harness.step(2)
            assert await read(client, token("a"), 0) == []

        harness.serve(scenario)

    @pytest.mark.parametrize("body", [
        {"conv_token": "short", "payload_b64": encode_payload(payload(0))},
        {"conv_token": "has spaces and $ymbols, long enough", "payload_b64": encode_payload(payload(0))},
        {"conv_token": token("a"), "payload_b64": "!!! not base64 !!!"},
        {"conv_token": token("a")},
        {"payload_b64": encode_payload(payload(0))},
        {"conv_token": token("a"), "payload_b64": encode_payload(payload(0)), "seq": 3},
        {"conv_token": token("a"), "payload_b64": encode_payload(payload(0)), "conv_id": 1},
    ])
    def test_invalid_submissions_are_rejected_without_echo(self, harness: Harness, body: dict[str, Any]) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            r = await client.post("/v1/messages", json=body)
            assert r.status_code == 422
            assert r.json()["error"] == "invalid_request" and r.json()["fields"]
            for value in body.values():  # the answer names the field, never the rejected value
                if isinstance(value, str) and len(value) > 4:
                    assert value not in r.text

        harness.serve(scenario)

    @pytest.mark.parametrize("body", [
        {"conv_token": token("a"), "win": -1},
        {"conv_token": token("a"), "win": 2**31},
        {"conv_token": token("a"), "win": "now"},
        {"conv_token": token("a")},
        {"conv_token": "short", "win": 0},
        {"conv_token": token("a"), "win": 0, "bucket": 1},
    ])
    def test_invalid_reads_are_rejected(self, harness: Harness, body: dict[str, Any]) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            r = await client.post("/v1/read", json=body)
            assert r.status_code == 422 and r.json()["error"] == "invalid_request"

        harness.serve(scenario)

    def test_no_interactive_docs_and_unknown_routes(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            for path in ("/docs", "/redoc", "/v1/dump", "/v1/messages/1"):
                assert (await client.get(path)).status_code == 404
            assert (await client.get("/v1/messages")).status_code == 405

        harness.serve(scenario)


class VcloakService(ServiceContract):
    """V-cloak mode only: the scheduler, the read path and the key lifecycle behind the API."""

    def test_s2_100_sim_epochs_complete_and_the_rows_are_stored(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            sched = harness.backend.scheduler
            n = 0
            for e in range(100):
                for _ in range(e % 4):
                    assert (await post(client, token(f"c{n % 7}"), payload(n))).status_code == 202
                    n += 1
                await harness.step()
            assert sched.epochs == 100 and sched.errors == 0 and sched.queued == 0
            stored = harness.store.dump()
            assert len(stored) == n == 150
            assert sorted(index_of(r.payload) for r in stored) == list(range(n))
            assert {r.win for r in stored} <= set(range(100 // EPOCHS_PER_WINDOW))
            assert (await client.get("/healthz")).json()["epochs"] == 100

        harness.serve(scenario)

    def test_a2_each_closed_window_is_rewritten_exactly_once(self, harness: Harness) -> None:
        calls: list[int] = []
        rewrite = harness.store.rewrite_window

        def spy(win: int, rows: list[Any]) -> None:
            calls.append(win)
            rewrite(win, rows)

        harness.store.rewrite_window = spy

        async def scenario(client: httpx.AsyncClient) -> None:
            sent = await send_across_windows(harness, client)
            sched = harness.backend.scheduler
            assert calls == [0, 1, 2] and dict(sched.rewrites) == {0: 1, 1: 1, 2: 1}
            await harness.step(3 * EPOCHS_PER_WINDOW)  # empty windows: nothing to rewrite, nothing rewritten twice
            assert calls == [0, 1, 2] and sched.hot_windows() == []
            assert (await post(client, token("late"), payload(999))).status_code == 202
            await harness.step()
            assert sched.hot_windows() == [6] and calls == [0, 1, 2]  # the open window is not rewritten
            for conv, expected in sent.items():  # the re-shuffle changed nothing a reader sees
                assert [p for w in range(3) for p in await read(client, conv, w)] == expected

        harness.serve(scenario)

    def test_stored_order_is_not_arrival_order(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            await send_across_windows(harness, client)
            stored = harness.store.dump()
            assert [r.win for r in stored] == sorted(r.win for r in stored)
            for win in range(3):
                order = [index_of(r.payload) for r in stored if r.win == win]
                assert len(order) > 60 and order != sorted(order)

        harness.serve(scenario)

    def test_overflow_carries_to_the_next_epoch_and_is_counted(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            sched = harness.backend.scheduler
            conv = token("burst")
            for i in range(150):
                assert (await post(client, conv, payload(i))).status_code == 202
            await harness.step()
            assert len(harness.store.dump()) == SLOTS and sched.overflow == 150 - SLOTS
            await harness.step()
            assert len(harness.store.dump()) == 2 * SLOTS and sched.overflow == (150 - SLOTS) + (150 - 2 * SLOTS)
            await harness.step()
            assert len(harness.store.dump()) == 150 and sched.queued == 0
            health = (await client.get("/healthz")).json()
            assert health["overflow"] == 108 and health["queued"] == 0
            # 150 messages of one conversation in one bucket-window exceed CAND_K = 128
            r = await client.post("/v1/read", json={"conv_token": conv, "win": 0})
            assert r.status_code == 503 and r.json() == {"error": "candidate_overflow"}

        harness.serve(scenario)

    def test_overflowing_messages_keep_their_order(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            conv = token("burst")
            for i in range(120):
                assert (await post(client, conv, payload(i))).status_code == 202
            await harness.step(3)
            assert [index_of(p) for p in await read(client, conv, 0)] == list(range(120))

        harness.serve(scenario)

    def test_queue_bound_answers_503(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            harness.backend.scheduler.max_queue = 3
            codes = [(await post(client, token("a"), payload(i))).status_code for i in range(5)]
            assert codes == [202, 202, 202, 503, 503]
            r = await post(client, token("a"), payload(9))
            assert r.json() == {"error": "queue_full"} and r.headers["retry-after"] == "1"
            await harness.step()
            assert (await post(client, token("a"), payload(3))).status_code == 202
            await harness.step()
            assert [index_of(p) for p in await read(client, token("a"), 0)] == [0, 1, 2, 3]

        harness.serve(scenario)

    def test_s5_shutdown_writes_the_queue_and_zeroizes_the_keys(self, harness: Harness) -> None:
        seen: dict[str, Any] = {}

        async def scenario(client: httpx.AsyncClient) -> None:
            keys = harness.backend.keys
            assert keys.ready and (await client.get("/healthz")).json()["ready"] is True
            seen["keys"], seen["calls"] = keys, []
            zeroize = keys.zeroize

            def spy() -> None:
                seen["calls"].append(keys.ready)
                zeroize()

            keys.zeroize = spy
            for i in range(70):  # more than one epoch of SLOTS, never stepped
                assert (await post(client, token("a"), payload(i))).status_code == 202

        harness.serve(scenario)
        assert seen["calls"] == [True]  # called once, while the keys were still loaded
        assert seen["keys"].ready is False and harness.backend.ready is False
        assert len(harness.store.dump()) == 70  # accepted messages were written before the keys went

    def test_s5_master_buffer_is_zeroized_at_startup(self, harness: Harness) -> None:
        handed: list[bytearray] = []

        def provider() -> bytearray:
            handed.append(fixed_master())
            return handed[-1]

        harness.backend._key_provider = provider

        async def scenario(client: httpx.AsyncClient) -> None:
            assert handed and handed[0] == bytearray(32)
            assert (await client.get("/healthz")).json()["ready"] is True

        harness.serve(scenario)

    def test_wall_clock_service_round_trip(self, harness: Harness) -> None:
        """The background scheduler on the real clock (short epochs): post, wait, read."""
        from vcloak.service.scheduler import WallClock

        h = vcloak_harness(harness.store, clock=WallClock(), epoch_ms=50, window_s=1, autorun=True)

        async def scenario(client: httpx.AsyncClient) -> None:
            conv = token("live")
            w0 = (await client.get("/v1/windows")).json()["win"]
            for i in range(10):
                assert (await post(client, conv, payload(i))).status_code == 202
            got: list[bytes] = []
            for _ in range(40):
                await asyncio.sleep(0.05)
                got = [p for w in (w0, w0 + 1) for p in await read(client, conv, w)]
                if len(got) == 10:
                    break
            assert [index_of(p) for p in got] == list(range(10))
            assert (await client.get("/healthz")).json()["epochs"] >= 1

        h.serve(scenario)
        assert h.backend.ready is False


class BaselineService(ServiceContract):
    """Baseline mode only."""

    def test_s4_attack_on_the_baseline_dump_recovers_the_order(self, harness: Harness) -> None:
        from vcloak.oracle.attacks import order_recovery_attack

        async def scenario(client: httpx.AsyncClient) -> None:
            await send_across_windows(harness, client)

        harness.serve(scenario)
        dumped = harness.store.dump()  # physical order
        assert len(dumped) == 200
        ids = [i for i, _, _ in dumped]
        assert ids == sorted(ids)  # the serial id is the arrival order
        res = order_recovery_attack([w for _, w, _ in dumped], [index_of(p) for _, _, p in dumped])
        assert res["tau_global"] == pytest.approx(1.0)
        assert res["tau_within_round"] == pytest.approx(1.0)

    def test_baseline_reports_no_scheduler(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            assert (await post(client, token("a"), payload(0))).status_code == 202
            assert await read(client, token("a"), 0) == [payload(0)]  # readable at once: nothing is batched
            health = (await client.get("/healthz")).json()
            assert (health["epochs"], health["overflow"], health["queued"]) == (0, 0, 0)

        harness.serve(scenario)
