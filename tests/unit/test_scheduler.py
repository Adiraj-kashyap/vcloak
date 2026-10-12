"""M10: the epoch scheduler on its own (A1, A2): boundaries, carry-over, window close, failures."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from service_contract import index_of, payload
from testkeys import dev_keystore
from vcloak.gpu.engine import GpuEngine, StoredRow, Submission
from vcloak.gpu.runtime import get_backend
from vcloak.service.scheduler import (
    EPOCH_MAX,
    SEQ_SHIFT,
    EpochScheduler,
    NotStored,
    QueueFull,
    SimClock,
    WallClock,
)
from vcloak.storage.repo import SqliteRepo

E = 200
SLOTS = 64


class SpyEngine:
    """A real engine (numpy simulator) that records its calls; `on_write` runs inside `write_epoch`."""

    def __init__(self, window_s: int = 1, epoch_ms: int = E, slots: int = SLOTS) -> None:
        self._inner = GpuEngine(dev_keystore(get_backend()), slots=slots, buckets=4, window_s=window_s,
                                epoch_ms=epoch_ms)
        self.slots, self.epoch_ms = slots, epoch_ms
        self.writes: list[tuple[int, list[Submission]]] = []
        self.write_times_ms: list[int] = []
        self.reshuffles: list[int] = []
        self.on_write: Any = None

    def window_of(self, epoch: int) -> int:
        return self._inner.window_of(epoch)

    def write_epoch(self, epoch: int, batch: list[Submission]) -> list[StoredRow]:
        self.write_times_ms.append(time.time_ns() // 1_000_000)
        self.writes.append((epoch, list(batch)))
        if self.on_write is not None:
            self.on_write(epoch)
        return self._inner.write_epoch(epoch, batch)

    def reshuffle_window(self, win: int, rows: list[StoredRow]) -> list[StoredRow]:
        self.reshuffles.append(win)
        return self._inner.reshuffle_window(win, rows)

    def sizes(self) -> list[tuple[int, int]]:
        return [(e, len(b)) for e, b in self.writes]


def make(clock: Any = None, **kw: Any) -> tuple[EpochScheduler, SpyEngine, SqliteRepo, Any]:
    clock = clock or SimClock()
    engine = SpyEngine(**{k: kw.pop(k) for k in ("window_s", "epoch_ms", "slots") if k in kw})
    repo = SqliteRepo()
    repo.init_schema()
    return EpochScheduler(engine, repo, clock, **kw), engine, repo, clock


def stored(repo: SqliteRepo) -> list[int]:
    return sorted(index_of(r.payload) for r in repo.dump())


def test_every_epoch_calls_the_engine_even_when_empty() -> None:
    sched, engine, repo, _ = make()
    assert asyncio.run(sched.run(5)) == 5
    assert engine.sizes() == [(e, 0) for e in range(5)]
    assert sched.epochs == 5 and repo.dump() == []


def test_epochs_are_the_intervals_of_the_clock() -> None:
    sched, engine, _, clock = make(SimClock(start_ms=1_000_050))
    sched.submit(1, payload(0))
    asyncio.run(sched.run(2))
    # 1_000_050 lies in epoch 5000, which closes at 1_000_200
    assert engine.sizes() == [(5000, 1), (5001, 0)] and clock.now_ms() == 1_000_400


def test_a_tick_off_the_boundary_is_refused() -> None:
    sched, _, _, _ = make()
    with pytest.raises(ValueError):
        asyncio.run(sched.tick(E + 1))


def test_a1_an_arrival_after_the_boundary_is_never_taken_into_the_closed_epoch() -> None:
    sched, engine, repo, clock = make()
    sched.submit(1, payload(0))  # arrives at 0, epoch 0
    clock.advance(E + 30)  # the scheduler runs late: the boundary at 200 has passed
    sched.submit(1, payload(1))  # arrives at 230, epoch 1

    asyncio.run(sched.tick(E))
    assert engine.sizes() == [(0, 1)] and stored(repo) == [0] and sched.queued == 1
    assert sched.overflow == 0  # a later arrival is not an overflow of this epoch
    asyncio.run(sched.tick(2 * E))
    assert engine.sizes() == [(0, 1), (1, 1)] and stored(repo) == [0, 1]


def test_a1_a_slow_engine_does_not_extend_the_epoch_and_the_overflow_carries() -> None:
    """The engine takes 2.5 epochs per call. The epoch still holds only what arrived before its boundary;
    what arrives during the call, and what did not fit, goes into the next epoch that is written."""
    sched, engine, repo, clock = make()
    for i in range(100):  # 36 more than SLOTS, all in epoch 0
        sched.submit(7, payload(i))
    arrivals = iter(range(100, 110))

    def slow(epoch: int) -> None:
        clock.advance(E * 5 // 2)
        sched.submit(7, payload(next(arrivals)))  # arrives while the engine is busy

    engine.on_write = slow
    asyncio.run(sched.run(3))

    # boundaries 200, 800, 1400: epochs 0, 3, 6. The boundaries in between passed during the calls.
    assert engine.sizes() == [(0, SLOTS), (3, 37), (6, 1)]
    assert sched.missed == 4 and sched.overflow == 36
    assert [index_of(s.payload) for s in engine.writes[0][1]] == list(range(SLOTS))  # first come, first written
    assert [index_of(s.payload) for s in engine.writes[1][1]] == [*range(SLOTS, 100), 100]
    assert [index_of(s.payload) for s in engine.writes[2][1]] == [101]
    assert stored(repo) == list(range(102)) and sched.queued == 1  # the arrival of the last call waits


def test_a1_wall_clock_epochs_never_close_before_their_boundary() -> None:
    sched, engine, _, _ = make(WallClock(), epoch_ms=100)
    sched.submit(1, payload(0))
    asyncio.run(sched.run(4))
    epochs = [e for e, _ in engine.writes]
    assert epochs == sorted(set(epochs)) and len(epochs) == 4
    for epoch, t_ms in zip(epochs, engine.write_times_ms, strict=True):
        assert t_ms >= (epoch + 1) * 100  # written only after the epoch's closing boundary
    assert engine.sizes()[0][1] == 1
    assert sched.epochs + sched.missed == epochs[-1] - epochs[0] + 1  # every boundary is written or counted


def test_sequence_numbers_are_arrival_positions() -> None:
    sched, engine, _, _ = make()
    for i in range(3):
        sched.submit(5, payload(i))
    asyncio.run(sched.run(1))
    sched.submit(5, payload(3))
    asyncio.run(sched.run(1))
    seqs = [s.seq for _, b in engine.writes for s in b]
    assert seqs == [0, 1, 2, (1 << SEQ_SHIFT)] and seqs == sorted(seqs)
    assert SLOTS < 1 << SEQ_SHIFT and (EPOCH_MAX << SEQ_SHIFT) < 1 << 64


def test_a2_window_close_reshuffles_once_and_only_closed_windows() -> None:
    sched, engine, repo, _ = make()  # window_s = 1: five epochs per window
    n = 0
    for e in range(15):  # windows 0, 1, 2
        if e // 5 != 1:  # nothing arrives in window 1
            for _ in range(8):
                sched.submit(n % 3, payload(n))
                n += 1
        asyncio.run(sched.run(1))
    assert engine.reshuffles == [0] and sched.hot_windows() == [2]  # 0 closed; 1 was empty; 2 is still open
    before = [index_of(r.payload) for r in repo.dump() if r.win == 2]
    asyncio.run(sched.run(1))  # epoch 15 opens window 3
    assert engine.reshuffles == [0, 2] and dict(sched.rewrites) == {0: 1, 2: 1} and sched.hot_windows() == []
    after = [index_of(r.payload) for r in repo.dump() if r.win == 2]
    assert sorted(after) == sorted(before) and after != before  # same rows, new order
    asyncio.run(sched.run(20))
    assert engine.reshuffles == [0, 2] and stored(repo) == list(range(n))


def test_visible_round_epoch_stores_the_epoch_and_never_reshuffles() -> None:
    sched, engine, repo, _ = make(SimClock(start_ms=10 * E), visible_round="epoch", epoch_origin=4)
    for e in range(12):
        for i in range(3):
            sched.submit(1, payload(3 * e + i))
        asyncio.run(sched.run(1))
    rows = repo.dump()
    assert sorted({r.win for r in rows}) == list(range(6, 18))  # epoch 10 is round 6 from origin 4
    assert all(r.win == index_of(r.payload) // 3 + 6 for r in rows)
    assert engine.reshuffles == [] and not sched.rewrites and sched.current_round() == 22 - 4


def test_a_round_outside_the_store_is_an_error_not_a_wrap() -> None:
    sched, _, _, _ = make(visible_round="epoch", epoch_origin=10)
    with pytest.raises(ValueError):
        sched.current_round()
    with pytest.raises(ValueError):
        EpochScheduler(SpyEngine(), SqliteRepo(), SimClock(), visible_round="minute")


def test_a_failed_epoch_loses_nothing() -> None:
    sched, engine, repo, _ = make()
    for i in range(5):
        sched.submit(2, payload(i))
    pending = [True]

    def fail_once(epoch: int) -> None:
        if pending and pending.pop():
            raise RuntimeError("device lost")

    engine.on_write = fail_once
    asyncio.run(sched.run(1))
    assert sched.errors == 1 and sched.epochs == 0 and sched.queued == 5 and repo.dump() == []
    sched.submit(2, payload(5))
    asyncio.run(sched.run(1))
    assert sched.epochs == 1 and sched.queued == 0
    assert [index_of(s.payload) for s in engine.writes[-1][1]] == [0, 1, 2, 3, 4, 5]  # order kept
    assert engine.writes[-1][0] == 1 and stored(repo) == list(range(6))  # written under the later epoch


def test_a_failed_insert_loses_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    sched, engine, repo, _ = make()
    sched.submit(2, payload(0))
    insert, calls = repo.insert_rows, []

    def flaky(rows: list[StoredRow]) -> None:
        calls.append(len(rows))
        if len(calls) == 1:
            raise OSError("connection reset")
        insert(rows)

    monkeypatch.setattr(repo, "insert_rows", flaky)
    asyncio.run(sched.run(2))
    assert calls == [1, 1] and sched.errors == 1 and stored(repo) == [0]


def test_an_epoch_number_is_used_once_when_the_clock_steps_back() -> None:
    sched, engine, _, clock = make(SimClock(start_ms=10 * E))
    asyncio.run(sched.run(2))
    clock.advance(-5 * E)
    asyncio.run(sched.run(2))
    epochs = [e for e, _ in engine.writes]
    assert epochs == [10, 11, 12, 13]


def test_queue_bound_and_finish() -> None:
    sched, _, repo, _ = make(max_queue=2)
    sched.submit(1, payload(0))
    sched.submit(1, payload(1))
    with pytest.raises(QueueFull):
        sched.submit(1, payload(2))
    assert sched.finish() == 2  # epochs enough to write the queue
    with pytest.raises(QueueFull):  # nothing is accepted during shutdown
        sched.submit(1, payload(3))
    assert asyncio.run(sched.run()) == 1  # returns by itself once the queue is written
    assert stored(repo) == [0, 1] and sched.stats() == {"epochs": 1, "overflow": 0, "missed": 0, "queued": 0}


def test_default_queue_bound_is_public_and_proportional_to_slots() -> None:
    sched, _, _, _ = make()
    assert sched.max_queue == 16 * SLOTS


# ── ISSUE-22: restarts and the acknowledgement of a write ────────────────────

def restarted(repo: SqliteRepo, clock: SimClock, **kw: Any) -> tuple[EpochScheduler, SpyEngine]:
    """A new scheduler and engine on the store of an earlier one, as the backend builds them at startup."""
    engine = SpyEngine()
    return EpochScheduler(engine, repo, clock, pending=repo.pending_windows(), **kw), engine


def test_the_store_lists_a_window_from_its_first_rows_until_its_re_shuffle() -> None:
    sched, _, repo, _ = make()
    asyncio.run(sched.run(2))
    assert repo.pending_windows() == []  # empty epochs mark nothing
    sched.submit(1, payload(0))
    asyncio.run(sched.run(1))
    assert repo.pending_windows() == [0] == sched.hot_windows()
    asyncio.run(sched.run(3))  # epoch 5 is the first of window 1
    assert repo.pending_windows() == [] == sched.hot_windows() and dict(sched.rewrites) == {0: 1}


def test_a_new_scheduler_closes_the_windows_an_earlier_one_left_pending() -> None:
    sched, _, repo, clock = make()
    for e in range(8):  # windows 0 and 1; the process dies in window 1 without a shutdown
        for i in range(4):
            sched.submit(i, payload(4 * e + i))
        asyncio.run(sched.run(1))
    assert repo.pending_windows() == [1] and dict(sched.rewrites) == {0: 1}
    before = [index_of(r.payload) // 4 for r in repo.window_rows(1)]
    assert before == sorted(before)  # one epoch after the other
    clock.advance(40 * E)  # windows pass while nothing runs
    again, engine = restarted(repo, clock)
    assert again.hot_windows() == [1]
    asyncio.run(again.run(1))
    assert engine.reshuffles == [1] and dict(again.rewrites) == {1: 1} and repo.pending_windows() == []
    after = [index_of(r.payload) // 4 for r in repo.window_rows(1)]
    assert sorted(after) == before and after != before
    asyncio.run(again.run(10))
    assert engine.reshuffles == [1]  # once


def test_a_window_that_is_still_open_after_the_restart_is_not_closed_early() -> None:
    sched, _, repo, clock = make()
    sched.submit(1, payload(0))
    asyncio.run(sched.run(2))
    again, engine = restarted(repo, clock)
    asyncio.run(again.run(2))  # epochs 2 and 3: still window 0
    assert engine.reshuffles == [] and repo.pending_windows() == [0]
    asyncio.run(again.run(2))  # epoch 5
    assert engine.reshuffles == [0] and repo.pending_windows() == []


def test_a_kill_between_the_mark_and_the_rows_leaves_a_mark_that_the_restart_clears(
        monkeypatch: pytest.MonkeyPatch) -> None:
    sched, _, repo, clock = make()
    sched.submit(1, payload(0))

    def killed(rows: list[StoredRow]) -> None:
        raise OSError("the process is gone")

    monkeypatch.setattr(repo, "insert_rows", killed)
    asyncio.run(sched.run(1))
    assert repo.pending_windows() == [0] and repo.dump() == []  # the mark is written first
    monkeypatch.undo()
    clock.advance(10 * E)
    again, engine = restarted(repo, clock)
    asyncio.run(again.run(1))
    assert again.errors == 0 and repo.pending_windows() == [] and engine.reshuffles == [0]


def test_a_failed_re_shuffle_keeps_the_mark_and_is_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    sched, engine, repo, _ = make()
    sched.submit(1, payload(0))
    sched.submit(1, payload(1))
    asyncio.run(sched.run(5))
    rewrite, calls = repo.rewrite_window, []

    def flaky(win: int, rows: list[StoredRow]) -> None:
        calls.append(win)
        if len(calls) == 1:
            raise OSError("connection reset")
        rewrite(win, rows)

    monkeypatch.setattr(repo, "rewrite_window", flaky)
    asyncio.run(sched.run(1))
    assert sched.errors == 1 and repo.pending_windows() == [0] and not sched.rewrites
    asyncio.run(sched.run(1))
    assert calls == [0, 0] and repo.pending_windows() == [] and dict(sched.rewrites) == {0: 1}


def test_the_epoch_layout_marks_nothing_and_ignores_old_marks() -> None:
    repo = SqliteRepo()
    repo.init_schema()
    repo.mark_pending(0)
    engine = SpyEngine()
    sched = EpochScheduler(engine, repo, SimClock(), visible_round="epoch", pending=repo.pending_windows())
    sched.submit(1, payload(0))
    asyncio.run(sched.run(8))
    assert sched.hot_windows() == [] and engine.reshuffles == [] and repo.pending_windows() == [0]


def test_a_waiting_submission_is_answered_when_its_epoch_is_stored_and_not_before() -> None:
    sched, engine, repo, _ = make()
    seen: list[tuple[bool, int]] = []

    async def scenario() -> None:
        assert sched.submit(1, payload(0)) is None  # nothing to wait on unless asked
        done = sched.submit(1, payload(1), wait=True)
        assert done is not None and not done.done()
        engine.on_write = lambda epoch: seen.append((done.done(), len(repo.dump())))
        await sched.run(1)
        assert done.done() and done.result() is None and stored(repo) == [0, 1]

    asyncio.run(scenario())
    assert seen == [(False, 0)]


def test_a_waiting_submission_of_a_failed_epoch_is_answered_by_the_epoch_that_stores_it() -> None:
    sched, engine, repo, _ = make()
    fail = [True]

    def fail_once(epoch: int) -> None:
        if fail and fail.pop():
            raise RuntimeError("device lost")

    async def scenario() -> None:
        done = sched.submit(1, payload(0), wait=True)
        assert done is not None
        engine.on_write = fail_once
        await sched.run(1)
        assert sched.errors == 1 and not done.done() and repo.dump() == []
        await sched.run(1)
        assert done.done() and done.exception() is None and stored(repo) == [0]

    asyncio.run(scenario())


def test_overflowing_waiters_are_answered_epoch_by_epoch() -> None:
    sched, _, repo, _ = make(slots=4)

    async def scenario() -> None:
        waits = [sched.submit(1, payload(i), wait=True) for i in range(10)]
        for written in (4, 8, 10):
            await sched.run(1)
            assert [w.done() for w in waits] == [i < written for i in range(10)] and len(repo.dump()) == written

    asyncio.run(scenario())


def test_waiters_left_in_the_queue_at_the_stop_are_told_so() -> None:
    sched, _, repo, _ = make(slots=4)

    async def scenario() -> None:
        waits = [sched.submit(1, payload(i), wait=True) for i in range(6)]
        gone = sched.submit(1, payload(6), wait=True)
        gone.cancel()  # a sender that gave up: its message stays queued, nobody is told
        await sched.run(1)
        sched.stop()
        assert sched.drop_waiters() == 2 and sched.drop_waiters() == 0
        assert [w.done() and w.exception() is None for w in waits[:4]] == [True] * 4
        for w in waits[4:]:
            with pytest.raises(NotStored):
                w.result()
        assert stored(repo) == [0, 1, 2, 3]

    asyncio.run(scenario())
