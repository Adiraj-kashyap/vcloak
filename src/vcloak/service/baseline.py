"""The unprotected baseline (M10 S4): what an ordinary message store does, behind the same API.

Every message is inserted the moment it arrives, with a BIGSERIAL id, a `timestamptz` and its
conversation id in the clear, and is read back with `ORDER BY id`. Nothing is batched, permuted or
padded. It exists to be compared with: M14 runs the order-recovery attack on its dump, M15 measures
what V-cloak costs over it. It is never a deployment mode.

The table lives in a schema of its own (`baseline`), so it never shares a table with V-cloak rows.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from typing import Any, Protocol, TypeVar

from vcloak import config
from vcloak.service.logsafe import SafeLogger, get_logger
from vcloak.service.models import conv_id_of
from vcloak.service.scheduler import Clock
from vcloak.storage import pgconf

T = TypeVar("T")

SCHEMA = "baseline"
_SCHEMA_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}")
_DDL = """
CREATE TABLE IF NOT EXISTS messages (
    id      BIGSERIAL   PRIMARY KEY,
    ts      timestamptz NOT NULL DEFAULT now(),
    conv    bytea       NOT NULL,
    win     int         NOT NULL,
    payload bytea       NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conv_win_idx ON messages (conv, win);
"""

Dumped = tuple[int, int, bytes]  # (id, win, payload), in physical order


def _conv_bytes(conv_id: int) -> bytes:
    return conv_id.to_bytes(8, "little")


class BaselineStore(Protocol):
    def init_schema(self) -> None: ...

    def insert(self, conv_id: int, win: int, payload: bytes) -> None: ...

    def read(self, conv_id: int, win: int) -> list[bytes]: ...

    def dump(self) -> list[Dumped]: ...

    def close(self) -> None: ...


class PgBaselineStore:
    def __init__(self, dsn: str | None = None, *, schema: str = SCHEMA) -> None:
        import psycopg
        from psycopg import sql

        if not _SCHEMA_RE.fullmatch(schema):
            raise ValueError("schema must be a lower-case identifier")
        self._schema, self._sql = schema, sql
        self._lock = threading.RLock()
        self._conn = psycopg.connect(dsn or pgconf.default_dsn(), autocommit=True)

    def init_schema(self) -> None:
        ident = self._sql.Identifier(self._schema)
        with self._lock:
            self._conn.execute(self._sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident))
            self._conn.execute(self._sql.SQL("SET search_path TO {}").format(ident))
            self._conn.execute(_DDL)

    def insert(self, conv_id: int, win: int, payload: bytes) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO messages (conv, win, payload) VALUES (%s, %s, %s)",
                               (_conv_bytes(conv_id), win, payload))

    def read(self, conv_id: int, win: int) -> list[bytes]:
        with self._lock:
            got = self._conn.execute("SELECT payload FROM messages WHERE conv = %s AND win = %s ORDER BY id",
                                     (_conv_bytes(conv_id), win)).fetchall()
        return [bytes(p) for (p,) in got]

    def dump(self) -> list[Dumped]:
        """The attacker's copy of the table: rows in physical order."""
        with self._lock:
            got = self._conn.execute("SELECT id, win, payload FROM messages ORDER BY ctid").fetchall()
        return [(i, w, bytes(p)) for i, w, p in got]

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._lock:
            cur = self._conn.execute(query, params)
            return cur.fetchall() if cur.description else []

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class SqliteBaselineStore:
    """SQLite twin for unit tests (ADR-008); physical order is the rowid order."""

    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)

    def init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, conv BLOB NOT NULL, win INTEGER NOT NULL, "
                "payload BLOB NOT NULL)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS messages_conv_win_idx ON messages (conv, win)")

    def insert(self, conv_id: int, win: int, payload: bytes) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO messages (conv, win, payload) VALUES (?, ?, ?)",
                               (_conv_bytes(conv_id), win, payload))

    def read(self, conv_id: int, win: int) -> list[bytes]:
        with self._lock:
            got = self._conn.execute("SELECT payload FROM messages WHERE conv = ? AND win = ? ORDER BY id",
                                     (_conv_bytes(conv_id), win)).fetchall()
        return [bytes(p) for (p,) in got]

    def dump(self) -> list[Dumped]:
        with self._lock:
            got = self._conn.execute("SELECT id, win, payload FROM messages ORDER BY rowid").fetchall()
        return [(i, w, bytes(p)) for i, w, p in got]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class BaselineBackend:
    """The service backend of `--mode baseline`: the same methods as `VcloakBackend` (app.py)."""

    mode = "baseline"
    visible_round = "window"

    def __init__(self, store: BaselineStore, clock: Clock, *, window_s: int = config.WINDOW_S,
                 epoch_ms: int = config.EPOCH_MS, log: SafeLogger | None = None) -> None:
        if window_s < 1 or epoch_ms < 1:
            raise ValueError("window_s and epoch_ms must be positive")
        self.store, self._clock = store, clock
        self.window_s, self.epoch_ms = window_s, epoch_ms
        self._log = log or get_logger("baseline")
        self._executor: ThreadPoolExecutor | None = None
        self._epoch_listeners: list[Callable[[], None]] = []
        self._ticker: asyncio.Task[None] | None = None

    @property
    def ready(self) -> bool:
        return self._executor is not None

    def on_epoch(self, listener: Callable[[], None]) -> None:
        """`listener()` runs on every EPOCH_MS boundary of the clock. The baseline has no epochs of its
        own: this is the cadence of the socket push only, and nothing ticks while nobody listens."""
        self._epoch_listeners.append(listener)

    async def _tick(self) -> None:
        while True:
            await self._clock.sleep_until((self._clock.now_ms() // self.epoch_ms + 1) * self.epoch_ms)
            for listener in list(self._epoch_listeners):
                try:
                    listener()
                except Exception as e:  # noqa: BLE001 - a listener never stops the cadence
                    self._log.failure("epoch_listener_failed", e)

    async def _blocking(self, fn: Callable[[], T]) -> T:
        if self._executor is None:
            raise RuntimeError("the backend is not started")
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn)

    async def start(self) -> None:
        # one thread: inserts reach the table in the order the requests were accepted
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vcloak-baseline")
        await self._blocking(self.store.init_schema)
        if self._epoch_listeners:
            self._ticker = asyncio.create_task(self._tick(), name="vcloak-baseline-ticker")
        self._log.event("started", mode=self.mode, window_s=self.window_s)

    async def stop(self) -> None:
        if self._ticker is not None:
            self._ticker.cancel()
            with suppress(asyncio.CancelledError):
                await self._ticker
            self._ticker = None
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._log.event("stopped", mode=self.mode)

    def current_window(self) -> int:
        return self._clock.now_ms() // (1000 * self.window_s)

    async def submit(self, conv_token: str, payload: bytes, *, stored: bool = False) -> None:
        # stored before it returns in either case: there is no epoch to wait for
        conv_id, win = conv_id_of(conv_token), self.current_window()
        await self._blocking(lambda: self.store.insert(conv_id, win, payload))

    async def read(self, conv_token: str, win: int) -> list[bytes]:
        conv_id = conv_id_of(conv_token)
        return await self._blocking(lambda: self.store.read(conv_id, win))

    def stats(self) -> dict[str, int]:
        return {"epochs": 0, "overflow": 0, "missed": 0, "queued": 0}

    def _stored(self, windows: int) -> list[dict[str, Any]]:
        current = self.current_window()
        first = max(current - windows + 1, 0)
        out: dict[int, dict[str, Any]] = {w: {"win": w, "state": "arrival", "rows": []}
                                          for w in range(first, current + 1)}
        for row_id, win, payload in self.store.dump():
            if win in out:
                out[win]["rows"].append({"row_id": str(row_id), "bucket": None, "seq_enc": None, "payload": payload})
        return [out[w] for w in sorted(out)]

    async def stored(self, windows: int) -> list[dict[str, Any]]:
        """The rows of the newest `windows` windows in physical order, which here is the arrival order."""
        return await self._blocking(lambda: self._stored(windows))
