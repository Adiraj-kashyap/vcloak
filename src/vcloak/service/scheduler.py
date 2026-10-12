"""The round scheduler (ai/ARCHITECTURE.md §2, S4-S10): wall-clock epochs, one engine call per epoch,
one re-shuffle per closed window.

Epoch `e` is the interval [e * EPOCH_MS, (e + 1) * EPOCH_MS) of the clock. At its closing boundary the
scheduler takes, in arrival order, the queued submissions that arrived before the boundary, at most
SLOTS of them, and hands them to `engine.write_epoch(e, ...)` and `repo.insert_rows`. The epoch is
never extended: what does not fit (more than SLOTS, or the engine still busy with an earlier epoch)
stays queued and goes into a later epoch. Both cases are counted in public counters (`overflow`,
`missed`). `write_epoch` is called for an empty epoch too, so the work per epoch does not depend on
the load.

A window is closed when an epoch of a later window is written; it is then re-shuffled once
(`storage.reshuffle`, ADR-004). With `visible_round="epoch"` the stored round is the epoch itself and
nothing is re-shuffled: that is the Review-1 design, kept only as the comparison layout of M14.

Which windows still wait for their re-shuffle is kept in the store (`Repo.mark_pending`, ADR-016): a
window is marked before its first rows are stored and the mark goes with the swap. A scheduler started
with `pending` (the marks a stopped or killed service left) closes those windows like its own.

Arrival times live in the queue (host memory) only. They are never stored and never logged. The queue
is not durable, because a journal of it would be an arrival record: a submission made with `wait=True`
gets a future that completes when its epoch is in the store, which is the only acknowledgement of
durability a client has.
The sequence number of a submission is its arrival position, `epoch << SEQ_SHIFT | index` (ADR-015).
"""
from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Protocol, TypeVar

from vcloak.gpu.engine import StoredRow, Submission
from vcloak.service.logsafe import SafeLogger, get_logger
from vcloak.storage.repo import WIN_MAX, Repo
from vcloak.storage.reshuffle import reshuffle_window

T = TypeVar("T")

SEQ_SHIFT = 24  # index bits of a sequence number: more than log2 of any SLOTS
EPOCH_MAX = (1 << (64 - SEQ_SHIFT)) - 1
QUEUE_EPOCHS = 16  # default queue bound, in epochs of SLOTS submissions
# Round ids are an int4 in the store. Window ids fit for centuries; epoch ids of a wall clock do not,
# so the epoch-level layout counts its rounds from this public origin (2026-01-01T00:00:00Z).
EPOCH_ROUND_ORIGIN_MS = 1_767_225_600_000
VISIBLE_ROUNDS = ("window", "epoch")


class QueueFull(RuntimeError):
    """The submission queue is at its bound (or the scheduler is shutting down): try again later."""


class NotStored(RuntimeError):
    """The service stopped before it could write a submission whose sender waits for it."""


class Clock(Protocol):
    def now_ms(self) -> int: ...

    async def sleep_until(self, t_ms: int) -> None: ...


class WallClock:
    """The system clock: epochs are aligned to multiples of EPOCH_MS of Unix time."""

    name = "wall"

    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000

    async def sleep_until(self, t_ms: int) -> None:
        while (left := t_ms - self.now_ms()) > 0:
            await asyncio.sleep(left / 1000)


class SimClock:
    """A virtual clock that jumps to whatever the scheduler waits for: epochs run as fast as the
    engine and the store allow (M14). `advance` moves it by hand."""

    name = "sim"

    def __init__(self, start_ms: int = 0) -> None:
        self._now = start_ms
        self._lock = threading.Lock()

    def now_ms(self) -> int:
        with self._lock:
            return self._now

    def advance(self, ms: int) -> None:
        with self._lock:
            self._now += ms

    async def sleep_until(self, t_ms: int) -> None:
        with self._lock:
            self._now = max(self._now, t_ms)
        await asyncio.sleep(0)  # let requests in between two epochs


class EpochEngine(Protocol):
    slots: int
    epoch_ms: int

    def window_of(self, epoch: int) -> int: ...

    def write_epoch(self, epoch: int, batch: list[Submission]) -> list[StoredRow]: ...

    def reshuffle_window(self, win: int, rows: list[StoredRow]) -> list[StoredRow]: ...


@dataclass
class _Pending:
    conv_id: int
    payload: bytes
    t_ms: int  # arrival on the scheduler's clock; host memory only
    stored: asyncio.Future[None] | None = None  # set when the sender waits for the write


class EpochScheduler:
    """See the module docstring. `submit` and `run` belong to one event loop; the engine and the
    repository are called through `executor` (one thread, because an engine is not thread-safe), or
    inline when there is none."""

    def __init__(self, engine: EpochEngine, repo: Repo, clock: Clock, *, visible_round: str = "window",
                 epoch_origin: int = 0, max_queue: int | None = None, executor: Executor | None = None,
                 pending: Iterable[int] = (), log: SafeLogger | None = None) -> None:
        if visible_round not in VISIBLE_ROUNDS:
            raise ValueError(f"visible_round must be one of {VISIBLE_ROUNDS}")
        self._engine, self._repo, self._clock = engine, repo, clock
        self.visible_round = visible_round
        self.slots, self.epoch_ms = engine.slots, engine.epoch_ms
        self._origin = epoch_origin
        self.max_queue = QUEUE_EPOCHS * self.slots if max_queue is None else max_queue
        self._executor = executor
        self._log = log or get_logger("scheduler")
        self._queue: deque[_Pending] = deque()
        # windows that hold rows and have not been re-shuffled: the marks of the store plus our own
        self._hot: set[int] = set(pending) if visible_round == "window" else set()
        self._last_boundary: int | None = None
        self._stop = False
        self._finishing = False
        self._epoch_listeners: list[Callable[[], None]] = []
        # public counters
        self.epochs = 0  # epochs written
        self.overflow = 0  # submissions left for a later epoch because the epoch was full, counted per epoch
        self.missed = 0  # epoch boundaries that passed while an earlier epoch was still being written
        self.errors = 0  # epochs whose write failed; their submissions went back to the queue
        self.rewrites: Counter[int] = Counter()  # re-shuffles per window (audit A2: never above 1)

    # ── rounds ───────────────────────────────────────────────────────────────

    def round_of(self, epoch: int) -> int:
        """The visible round stored with the rows of `epoch`."""
        rnd = self._engine.window_of(epoch) if self.visible_round == "window" else epoch - self._origin
        if not 0 <= rnd <= WIN_MAX:
            raise ValueError("the visible round is outside the range of the store: check the clock and the origin")
        return rnd

    def current_round(self) -> int:
        return self.round_of(self._clock.now_ms() // self.epoch_ms)

    @property
    def queued(self) -> int:
        return len(self._queue)

    def stats(self) -> dict[str, int]:
        return {"epochs": self.epochs, "overflow": self.overflow, "missed": self.missed, "queued": self.queued}

    # ── submissions ──────────────────────────────────────────────────────────

    def submit(self, conv_id: int, payload: bytes, *, wait: bool = False) -> asyncio.Future[None] | None:
        """Queue one submission for the epoch that is open now (S4). With `wait`, return a future that
        completes when the submission is in the store, or fails with `NotStored`."""
        if self._finishing or self._stop or len(self._queue) >= self.max_queue:
            raise QueueFull("the submission queue is full")
        stored = asyncio.get_running_loop().create_future() if wait else None
        self._queue.append(_Pending(conv_id, payload, self._clock.now_ms(), stored))
        return stored

    # ── one epoch ────────────────────────────────────────────────────────────

    async def _blocking(self, fn: Callable[[], T]) -> T:
        if self._executor is None:
            return fn()
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn)

    def _cut(self, boundary_ms: int) -> list[_Pending]:
        """The batch of the epoch that closes at `boundary_ms`: arrivals before the boundary, first come
        first, at most SLOTS. Later arrivals are never taken, however late this runs."""
        batch: list[_Pending] = []
        while self._queue and len(batch) < self.slots and self._queue[0].t_ms < boundary_ms:
            batch.append(self._queue.popleft())
        self.overflow += sum(1 for p in self._queue if p.t_ms < boundary_ms)
        return batch

    def _close_before(self, rnd: int) -> None:
        """Re-shuffle every window that closed before round `rnd` and still holds its arrival-time layout."""
        for win in sorted(w for w in self._hot if w < rnd):
            rows = reshuffle_window(self._repo, self._engine, win)
            self._hot.discard(win)
            self.rewrites[win] += 1
            self._log.event("window_closed", win=win, rows=rows)

    def _write(self, epoch: int, batch: list[_Pending]) -> None:
        if not 0 <= epoch <= EPOCH_MAX:
            raise ValueError("the epoch is outside the range of a sequence number")
        rnd = self.round_of(epoch)
        if self.visible_round == "window":
            self._close_before(rnd)
        subs = [Submission(p.conv_id, (epoch << SEQ_SHIFT) | i, p.payload) for i, p in enumerate(batch)]
        rows = self._engine.write_epoch(epoch, subs)
        if len(rows) != len(subs):
            raise RuntimeError("the engine returned a different number of rows than it was given")
        if self.visible_round == "epoch":
            rows = [dataclasses.replace(r, win=rnd) for r in rows]
        if rows:
            if self.visible_round == "window" and rnd not in self._hot:
                self._repo.mark_pending(rnd)  # before the rows: a kill in between leaves a mark, never a lost window
                self._hot.add(rnd)
            self._repo.insert_rows(rows)

    def on_epoch(self, listener: Callable[[], None]) -> None:
        """`listener()` runs on the event loop after every epoch boundary handled, whatever the epoch held
        and whether its write succeeded: the call says that a boundary passed, nothing else."""
        self._epoch_listeners.append(listener)

    def _notify(self) -> None:
        for listener in list(self._epoch_listeners):
            try:
                listener()
            except Exception as e:  # noqa: BLE001 - a listener never stops the epochs
                self._log.failure("epoch_listener_failed", e)

    async def tick(self, boundary_ms: int) -> None:
        """Close the epoch that ends at `boundary_ms`."""
        if boundary_ms % self.epoch_ms:
            raise ValueError("an epoch closes on a multiple of EPOCH_MS only")
        epoch = boundary_ms // self.epoch_ms - 1
        batch = self._cut(boundary_ms)
        try:
            await self._blocking(lambda: self._write(epoch, batch))
        except Exception as e:  # noqa: BLE001 - nothing accepted may be lost: back to the head of the queue
            self._queue.extendleft(reversed(batch))
            self.errors += 1
            self._log.failure("epoch_failed", e, queued=len(self._queue))
            self._notify()
            return
        self.epochs += 1
        for p in batch:  # the epoch is committed: answer the senders that wait for it
            if p.stored is not None and not p.stored.done():
                p.stored.set_result(None)
        self._notify()

    # ── the loop ─────────────────────────────────────────────────────────────

    def _next_boundary(self) -> int:
        nxt = (self._clock.now_ms() // self.epoch_ms + 1) * self.epoch_ms
        if self._last_boundary is not None:  # an epoch number is used once, even if the clock steps back
            nxt = max(nxt, self._last_boundary + self.epoch_ms)
        return nxt

    async def run(self, n_epochs: int | None = None) -> int:
        """Close epochs on the clock's boundaries until `stop`, or for `n_epochs` boundaries, or (after
        `finish`) until the queue is empty. Returns the number of boundaries handled."""
        done = 0
        self._stop = False
        while not self._stop and (n_epochs is None or done < n_epochs) and not (self._finishing and not self._queue):
            boundary = self._next_boundary()
            if self._last_boundary is not None:
                self.missed += (boundary - self._last_boundary) // self.epoch_ms - 1
            await self._clock.sleep_until(boundary)
            if self._stop:
                break
            self._last_boundary = boundary
            await self.tick(boundary)
            done += 1
        return done

    def stop(self) -> None:
        self._stop = True

    def finish(self) -> int:
        """Shutdown: refuse new submissions. A running `run` returns once the queue is written; without
        one, call `run(budget)` with the returned number of epochs."""
        self._finishing = True
        return len(self._queue) // self.slots + 2 if self._queue else 0

    def drop_waiters(self) -> int:
        """After the last epoch of a shutdown: fail the senders whose submissions are still queued."""
        n = 0
        for p in self._queue:
            if p.stored is not None and not p.stored.done():
                p.stored.set_exception(NotStored("the service stopped before the submission was written"))
                n += 1
        return n

    def hot_windows(self) -> list[int]:
        """Windows that are still in their arrival-time layout: ours, and those a restart found marked."""
        return sorted(self._hot)
