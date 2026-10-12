"""The message store behind the `Repo` protocol (ai/ARCHITECTURE.md §4): PostgreSQL, and SQLite for tests.

Everything the store holds is public at the database level: bucket, window, the sealed sequence
(`seq_enc`) and the client ciphertext (`payload`). The repository never sees a key. What it must not
add is arrival information, so there is no serial, sequence or timestamp, a closed window is
replaced by a new partition written in the order it is given, and a read always returns exactly K rows.

`dump()` is the view of an attacker who copies the database files: rows in physical order, one
window (partition) after the other.
"""
from __future__ import annotations

import os
import random
import re
import sqlite3
import threading
import uuid
from importlib import resources
from typing import Any, Protocol

from vcloak.crypto.aead_ref import SEQ_ENC_LEN
from vcloak.crypto.client import PAYLOAD_LEN
from vcloak.gpu.engine import StoredRow
from vcloak.storage import pgconf

WIN_MAX = 2**31 - 2  # win is an int4 and the partition bound is win + 1
_SCHEMA_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}")
_COLS = "row_id, bucket, win, seq_enc, payload"


class CandidateOverflow(RuntimeError):
    """A bucket-window holds more than K rows: CAND_K is too small for the load (PROJECT_BRIEF §7).
    Truncating would silently drop messages, so the read fails instead. The count is public."""


class RewriteMismatch(RuntimeError):
    """`rewrite_window` was given a different number of rows than the window holds."""


class Repo(Protocol):
    def insert_rows(self, rows: list[StoredRow]) -> None: ...

    def fetch_candidates(self, bucket: int, win: int, K: int) -> list[StoredRow]: ...  # noqa: N803

    def rewrite_window(self, win: int, rows: list[StoredRow]) -> None: ...

    def dump(self) -> list[StoredRow]: ...

    def window_rows(self, win: int) -> list[StoredRow]: ...  # physical order; input of the re-shuffle (ADR-014)


def _check_win(win: int) -> int:
    if isinstance(win, bool) or not isinstance(win, int) or not 0 <= win <= WIN_MAX:
        raise ValueError(f"win must be an int in [0, {WIN_MAX}]")
    return win


def _check_rows(rows: list[StoredRow], win: int | None = None) -> list[StoredRow]:
    """Plain Python values (the engine hands out numpy integers) and the public length checks."""
    out = []
    for r in rows:
        w = _check_win(int(r.win))
        if win is not None and w != win:
            raise ValueError("every row must belong to the window being rewritten")
        if len(r.seq_enc) != SEQ_ENC_LEN:
            raise ValueError(f"seq_enc must be {SEQ_ENC_LEN} bytes")
        out.append(StoredRow(r.row_id, int(r.bucket), w, bytes(r.seq_enc), bytes(r.payload)))
    return out


def _pad(real: list[StoredRow], bucket: int, win: int, K: int, size: int) -> list[StoredRow]:  # noqa: N803
    """Exactly K rows in random order: the real ones plus dummies of the same shape."""
    if len(real) > K:
        raise CandidateOverflow(f"bucket-window holds {len(real)} rows, K is {K}")
    out = list(real)
    for _ in range(K - len(real)):
        out.append(StoredRow(uuid.UUID(bytes=os.urandom(16), version=4), bucket, win, os.urandom(SEQ_ENC_LEN),
                             os.urandom(size)))
    random.SystemRandom().shuffle(out)
    return out


def _check_k(K: int) -> None:  # noqa: N803
    if isinstance(K, bool) or not isinstance(K, int) or K < 1:
        raise ValueError("K must be a positive int")


class PgRepo:
    """PostgreSQL: `messages` partitioned by window, one partition `messages_w<win>` per window."""

    def __init__(self, dsn: str | None = None, *, schema: str = "public",
                 dummy_payload_len: int = PAYLOAD_LEN) -> None:
        import psycopg
        from psycopg import sql

        if not _SCHEMA_RE.fullmatch(schema):
            raise ValueError("schema must be a lower-case identifier")
        self._sql = sql
        self._schema = schema
        self._dummy_len = dummy_payload_len
        self._lock = threading.RLock()
        self._parts: set[int] = set()
        self._conn = psycopg.connect(dsn or pgconf.default_dsn(), autocommit=True)
        self._conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))

    # -- schema ---------------------------------------------------------------------------------
    def init_schema(self) -> None:
        ddl = resources.files("vcloak.storage").joinpath("schema.sql").read_text(encoding="utf-8")
        with self._lock, self._conn.transaction():
            self._conn.execute(self._sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                self._sql.Identifier(self._schema)))
            self._conn.execute(ddl)

    @staticmethod
    def partition_name(win: int) -> str:
        return f"messages_w{_check_win(win)}"

    def create_partition(self, win: int) -> None:
        """Create the partition of one window if it is missing."""
        with self._lock:
            if win in self._parts:
                return
            self._conn.execute(self._sql.SQL(
                "CREATE TABLE IF NOT EXISTS {} PARTITION OF messages FOR VALUES FROM ({}) TO ({})").format(
                    self._sql.Identifier(self.partition_name(win)), self._sql.Literal(win),
                    self._sql.Literal(win + 1)))
            self._parts.add(win)

    def _has_partition(self, win: int) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s", (self._schema, self.partition_name(win))).fetchone() is not None

    def _copy(self, table: str, rows: list[StoredRow]) -> None:
        stmt = self._sql.SQL("COPY {} ({}) FROM STDIN (FORMAT BINARY)").format(
            self._sql.Identifier(table), self._sql.SQL(_COLS))
        with self._conn.cursor() as cur, cur.copy(stmt) as cp:
            cp.set_types(["uuid", "int4", "int4", "bytea", "bytea"])
            for r in rows:
                cp.write_row((r.row_id, r.bucket, r.win, r.seq_enc, r.payload))

    # -- Repo -----------------------------------------------------------------------------------
    def insert_rows(self, rows: list[StoredRow]) -> None:
        """One epoch: one transaction, one COPY, in the order given."""
        rows = _check_rows(rows)
        if not rows:
            return
        with self._lock:
            try:
                with self._conn.transaction():
                    for w in sorted({r.win for r in rows}):
                        self.create_partition(w)
                    self._copy("messages", rows)
            except BaseException:
                self._parts.clear()  # a rolled-back transaction takes its new partitions with it
                raise

    def fetch_candidates(self, bucket: int, win: int, K: int) -> list[StoredRow]:  # noqa: N803
        _check_k(K)
        _check_win(win)
        with self._lock:
            got = self._conn.execute(
                f"SELECT {_COLS} FROM messages WHERE bucket = %s AND win = %s", (bucket, win)).fetchall()
        real = [StoredRow(*r) for r in got]
        size = len(real[0].payload) if real else self._dummy_len
        return _pad(real, bucket, win, K, size)

    def window_rows(self, win: int) -> list[StoredRow]:
        _check_win(win)
        with self._lock:
            got = self._conn.execute(f"SELECT {_COLS} FROM messages WHERE win = %s ORDER BY ctid", (win,)).fetchall()
        return [StoredRow(*r) for r in got]

    def rewrite_window(self, win: int, rows: list[StoredRow]) -> None:
        """Replace the partition of `win` by a new one that holds `rows` in the order given.

        The new table is built and loaded first; then one transaction detaches and drops the old
        partition and attaches the new one, so a reader sees the old window or the new one."""
        rows = _check_rows(rows, _check_win(win))
        s, name = self._sql, self.partition_name(win)
        old, new = s.Identifier(name), s.Identifier(name + "_new")
        lo, hi = s.Literal(win), s.Literal(win + 1)
        with self._lock:
            with self._conn.transaction():
                self._conn.execute(s.SQL("DROP TABLE IF EXISTS {}").format(new))  # left by an interrupted rewrite
                self._conn.execute(s.SQL("CREATE TABLE {} (LIKE messages INCLUDING DEFAULTS)").format(new))
                # the bound as a CHECK lets ATTACH skip its validation scan
                self._conn.execute(s.SQL("ALTER TABLE {} ADD CONSTRAINT win_bound CHECK (win >= {} AND win < {})")
                                   .format(new, lo, hi))
                self._copy(name + "_new", rows)
            try:
                with self._conn.transaction():
                    exists = self._has_partition(win)
                    have = 0
                    if exists:
                        self._conn.execute(s.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(old))
                        have = self._conn.execute(s.SQL("SELECT count(*) FROM {}").format(old)).fetchone()[0]
                    if have != len(rows):
                        raise RewriteMismatch(f"window {win} holds {have} rows, {len(rows)} were given")
                    if exists:
                        self._conn.execute(s.SQL("ALTER TABLE messages DETACH PARTITION {}").format(old))
                        self._conn.execute(s.SQL("DROP TABLE {}").format(old))
                    self._conn.execute(s.SQL("ALTER TABLE {} RENAME TO {}").format(new, old))
                    self._conn.execute(s.SQL("ALTER TABLE messages ATTACH PARTITION {} FOR VALUES FROM ({}) TO ({})")
                                       .format(old, lo, hi))
                    self._conn.execute(s.SQL("ALTER TABLE {} DROP CONSTRAINT win_bound").format(old))
            except BaseException:
                self._conn.execute(s.SQL("DROP TABLE IF EXISTS {}").format(new))
                raise
            self._parts.add(win)

    def dump(self) -> list[StoredRow]:
        with self._lock:
            got = self._conn.execute(f"SELECT {_COLS} FROM messages ORDER BY win, ctid").fetchall()
        return [StoredRow(*r) for r in got]

    # -- helpers for tests and operations ---------------------------------------------------------
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        """Run one statement on the repository's connection (catalog queries of the tests, SHOW)."""
        with self._lock:
            cur = self._conn.execute(query, params)
            return cur.fetchall() if cur.description else []

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class SqliteRepo:
    """SQLite twin for unit tests (ADR-008). Physical order is the rowid order inside a window.
    SQLite keeps a rowid per row, which is an arrival counter: this class is never an evaluation target."""

    def __init__(self, path: str = ":memory:", *, dummy_payload_len: int = PAYLOAD_LEN) -> None:
        self._dummy_len = dummy_payload_len
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)

    def init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS messages (row_id BLOB NOT NULL, bucket INTEGER NOT NULL, "
                "win INTEGER NOT NULL, seq_enc BLOB NOT NULL, payload BLOB NOT NULL, PRIMARY KEY (row_id, win))")
            self._conn.execute("CREATE INDEX IF NOT EXISTS messages_bucket_win_idx ON messages (bucket, win)")

    def create_partition(self, win: int) -> None:
        _check_win(win)  # one table: nothing to create

    @staticmethod
    def _row(r: tuple[Any, ...]) -> StoredRow:
        return StoredRow(uuid.UUID(bytes=bytes(r[0])), r[1], r[2], bytes(r[3]), bytes(r[4]))

    def _insert(self, rows: list[StoredRow]) -> None:
        self._conn.executemany(f"INSERT INTO messages ({_COLS}) VALUES (?, ?, ?, ?, ?)",
                               [(r.row_id.bytes, r.bucket, r.win, r.seq_enc, r.payload) for r in rows])

    def _tx(self, body: Any) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                body()
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def insert_rows(self, rows: list[StoredRow]) -> None:
        rows = _check_rows(rows)
        if rows:
            self._tx(lambda: self._insert(rows))

    def fetch_candidates(self, bucket: int, win: int, K: int) -> list[StoredRow]:  # noqa: N803
        _check_k(K)
        _check_win(win)
        with self._lock:
            got = self._conn.execute(f"SELECT {_COLS} FROM messages WHERE bucket = ? AND win = ?",
                                     (bucket, win)).fetchall()
        real = [self._row(r) for r in got]
        size = len(real[0].payload) if real else self._dummy_len
        return _pad(real, bucket, win, K, size)

    def window_rows(self, win: int) -> list[StoredRow]:
        _check_win(win)
        with self._lock:
            got = self._conn.execute(f"SELECT {_COLS} FROM messages WHERE win = ? ORDER BY rowid", (win,)).fetchall()
        return [self._row(r) for r in got]

    def rewrite_window(self, win: int, rows: list[StoredRow]) -> None:
        rows = _check_rows(rows, _check_win(win))

        def body() -> None:
            have = self._conn.execute("SELECT count(*) FROM messages WHERE win = ?", (win,)).fetchone()[0]
            if have != len(rows):
                raise RewriteMismatch(f"window {win} holds {have} rows, {len(rows)} were given")
            self._conn.execute("DELETE FROM messages WHERE win = ?", (win,))
            self._insert(rows)

        self._tx(body)

    def dump(self) -> list[StoredRow]:
        with self._lock:
            got = self._conn.execute(f"SELECT {_COLS} FROM messages ORDER BY win, rowid").fetchall()
        return [self._row(r) for r in got]

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._lock:
            return self._conn.execute(query, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
