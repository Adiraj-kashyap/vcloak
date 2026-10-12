"""Re-shuffle of a closed window (ADR-004): read it, permute it on the engine, swap the partition.

The engine decides the order; the repository only writes the rows in the order it is given.
A window is re-shuffled after it has closed, so nothing is inserted into it while this runs.
"""
from __future__ import annotations

from typing import Protocol

from vcloak.gpu.engine import StoredRow
from vcloak.storage.repo import Repo


class Reshuffler(Protocol):
    def reshuffle_window(self, win: int, rows: list[StoredRow]) -> list[StoredRow]: ...


class ReshuffleError(RuntimeError):
    """The engine returned something other than a permutation of the window."""


def _key(r: StoredRow) -> tuple[bytes, int, int, bytes, bytes]:
    return (r.row_id.bytes, r.bucket, r.win, r.seq_enc, r.payload)


def reshuffle_window(repo: Repo, engine: Reshuffler, win: int) -> int:
    """Rewrite window `win` under the permutation of `engine`; return the number of rows.
    Nothing is written unless the engine's output is exactly the stored rows in some order."""
    rows = repo.window_rows(win)
    new = engine.reshuffle_window(win, rows)
    if sorted(map(_key, new)) != sorted(map(_key, rows)):
        raise ReshuffleError(f"window {win}: the engine output is not a permutation of the stored rows")
    repo.rewrite_window(win, new)
    return len(new)
