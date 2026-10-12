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


def spy_rewrites(store: Any) -> list[int]:
    """Record the windows `store.rewrite_window` is called for (A2)."""
    calls: list[int] = []
    rewrite = store.rewrite_window

    def spy(win: int, rows: list[Any]) -> None:
        calls.append(win)
        rewrite(win, rows)

    store.rewrite_window = spy
    return calls


async def post(client: httpx.AsyncClient, conv: str, p: bytes) -> httpx.Response:
    return await client.post("/v1/messages", json={"conv_token": conv, "payload_b64": encode_payload(p)})


async def post_stored(h: Harness, client: httpx.AsyncClient, conv: str, p: bytes) -> httpx.Response:
    """Post with `ack: stored` and let epochs pass until the answer is there."""
    body = {"conv_token": conv, "payload_b64": encode_payload(p), "ack": "stored"}
    answer = asyncio.create_task(client.post("/v1/messages", json=body))
    for _ in range(20):
        if answer.done():
            break
        await asyncio.sleep(0.01)  # the request reaches the queue, or the baseline stores it
        if h.vcloak and h.backend.scheduler.queued:
            await h.step()
    return await asyncio.wait_for(answer, 5)


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

    # -- ISSUE-22: the acknowledgement of a write --------------------------------------------------
    def test_ack_stored_answers_201_once_the_message_can_be_read(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            a = token("a")
            r = await post_stored(harness, client, a, payload(0))
            assert r.status_code == 201 and r.json() == {"accepted": True, "stored": True}
            assert await read(client, a, 0) == [payload(0)]  # no further epoch is needed
            r = await post(client, a, payload(1))
            assert r.status_code == 202 and r.json() == {"accepted": True, "stored": False}

        harness.serve(scenario)

    @pytest.mark.parametrize("ack", ["written", "", True, 1, None])
    def test_an_unknown_ack_is_rejected(self, harness: Harness, ack: Any) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            r = await client.post("/v1/messages", json={"conv_token": token("a"), "ack": ack,
                                                        "payload_b64": encode_payload(payload(0))})
            assert r.status_code == 422 and r.json()["fields"][0]["field"] == "ack"

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
        calls = spy_rewrites(harness.store)

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

    # -- ISSUE-22: restarts ------------------------------------------------------------------------
    @pytest.mark.parametrize(("down_windows", "more"), [(0, False), (0, True), (3, False)])
    def test_a_window_left_open_at_shutdown_is_re_shuffled_once_after_the_restart(
            self, harness: Harness, down_windows: int, more: bool) -> None:
        """The service stops in the middle of window 1 and comes back in the same window (0), with or
        without more messages for it, or three windows later (3). Window 1 must end up re-shuffled,
        exactly once, whichever process closes it."""
        calls = spy_rewrites(harness.store)
        convs = [token(f"restart-{i}") for i in range(3)]
        sent: dict[str, list[bytes]] = {c: [] for c in convs}

        async def send(client: httpx.AsyncClient, epochs: int) -> None:
            for _ in range(epochs):
                for _ in range(12):
                    i = sum(map(len, sent.values()))
                    assert (await post(client, convs[i % 3], payload(i))).status_code == 202
                    sent[convs[i % 3]].append(payload(i))
                await harness.step()

        async def first_run(client: httpx.AsyncClient) -> None:
            await send(client, EPOCHS_PER_WINDOW + 2)  # window 0 and two epochs of window 1
            assert calls == [0]

        async def second_run(client: httpx.AsyncClient) -> None:
            assert calls == [0]
            if more:
                await send(client, 2)  # the same window goes on: still open, still not rewritten
                assert calls == [0]
            if not down_windows:
                await harness.step(EPOCHS_PER_WINDOW)
            else:
                await harness.step()  # the first epoch after the restart closes what was left open
            assert calls == [0, 1]
            await harness.step(2 * EPOCHS_PER_WINDOW)
            assert calls == [0, 1]
            for conv, expected in sent.items():
                assert [p for w in range(2) for p in await read(client, conv, w)] == expected

        harness.serve(first_run)
        def epochs_of_window_1() -> list[int]:
            """The epoch each stored row of window 1 arrived in (12 messages per epoch), in physical order."""
            return [index_of(r.payload) // 12 for r in harness.store.window_rows(1)]

        as_written = epochs_of_window_1()  # one epoch after the other: the layout a restart must not keep
        assert as_written == sorted(as_written) and len(as_written) == 24
        harness.clock.advance(down_windows * EPOCHS_PER_WINDOW * EPOCH_MS)
        harness.serve(second_run)
        order = epochs_of_window_1()
        assert len(order) == (48 if more else 24) and order != sorted(order)

    def test_ack_stored_is_not_answered_before_the_epoch_is_in_the_store(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            a = token("a")
            body = {"conv_token": a, "payload_b64": encode_payload(payload(0)), "ack": "stored"}
            answer = asyncio.create_task(client.post("/v1/messages", json=body))
            while not harness.backend.scheduler.queued:
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            assert not answer.done() and harness.store.dump() == []  # queued: no answer yet
            await harness.step()
            r = await asyncio.wait_for(answer, 5)
            assert r.status_code == 201 and len(harness.store.dump()) == 1

        harness.serve(scenario)

    def test_ack_stored_times_out_with_504_and_the_message_stays_queued(self, harness: Harness) -> None:
        harness.backend.ack_timeout_s = 0.05

        async def scenario(client: httpx.AsyncClient) -> None:
            a = token("a")
            r = await client.post("/v1/messages", json={"conv_token": a, "ack": "stored",
                                                        "payload_b64": encode_payload(payload(0))})
            assert r.status_code == 504 and r.json() == {"error": "ack_timeout"}
            assert harness.backend.scheduler.queued == 1  # not withdrawn: a later epoch stores it
            await harness.step()
            assert await read(client, a, 0) == [payload(0)]

        harness.serve(scenario)

    def test_ack_stored_answers_503_when_the_service_stops_before_the_write(self, harness: Harness) -> None:
        answers: list[httpx.Response] = []

        async def main() -> None:
            app = create_app(harness.backend)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://vcloak.test") as client:
                async with app.router.lifespan_context(app):
                    def refuse(rows: list[Any]) -> None:
                        raise OSError("the store is gone")

                    harness.store.insert_rows = refuse
                    body = {"conv_token": token("a"), "payload_b64": encode_payload(payload(0)), "ack": "stored"}
                    answer = asyncio.create_task(client.post("/v1/messages", json=body))
                    while not harness.backend.scheduler.queued:
                        await asyncio.sleep(0.01)
                answers.append(await asyncio.wait_for(answer, 5))

        asyncio.run(main())
        assert answers[0].status_code == 503 and answers[0].json() == {"error": "not_stored"}
        assert harness.store.dump() == []

    def test_ack_timeout_covers_the_epochs_the_queue_can_hold(self, harness: Harness) -> None:
        b = harness.backend
        assert b.ack_timeout_s == max(5.0, (16 + 2) * EPOCH_MS / 1000)
        long_epochs = vcloak_harness(harness.store, epoch_ms=1000, max_queue=40 * SLOTS + 1).backend
        assert long_epochs.ack_timeout_s == 43.0  # 41 epochs of queue, and two

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
