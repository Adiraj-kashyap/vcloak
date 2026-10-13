"""The anonymity set of a stored message (M14 S6): how many real messages share its visible round.

Inside one window the physical order of the rows is a fresh permutation, so a message hides among the
real rows of its window; a read names a (bucket, window), so towards the reads it hides among the real
rows of that bucket-window. Both counts are taken from a dump of the real store, over every cell of the
run: a window or a bucket-window that holds no real message counts as 0 (it is a round in which a
message would have had no cover), and the number of empty cells is reported beside the distribution.

Users are mapped to conversations in pairs, as the load generator of M15 does: `users` users are
`users / 2` two-party conversations, every user in exactly one.

Percentiles are `numpy.percentile` with its default linear interpolation.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np


def conversations(users: int) -> int:
    """The number of two-party conversations of `users` users, every user in exactly one."""
    if users < 2 or users % 2:
        raise ValueError("users must be an even number of at least 2")
    return users // 2


def cell_counts(rows: Sequence[Any], n_windows: int, buckets: int) -> tuple[np.ndarray, np.ndarray]:
    """(real rows per window, real rows per (window, bucket)) of a V-cloak dump, empty cells included.
    A row outside the `n_windows` windows or the `buckets` buckets of the run is a ValueError."""
    if n_windows < 1 or buckets < 1:
        raise ValueError("n_windows and buckets must be positive")
    per_cell = np.zeros((n_windows, buckets), dtype=np.int64)
    for r in rows:
        win, bucket = int(r.win), int(r.bucket)
        if not (0 <= win < n_windows and 0 <= bucket < buckets):
            raise ValueError(f"row in window {win}, bucket {bucket}: outside the run")
        per_cell[win, bucket] += 1
    return per_cell.sum(axis=1), per_cell.reshape(-1)


def distribution(counts: np.ndarray) -> dict[str, float]:
    """Summary of the real rows per cell, and of the same count as a real row sees it (`msg_*`: every
    row weighted once, so a full cell counts for each of its rows and an empty one for none)."""
    counts = np.asarray(counts, dtype=np.int64)
    if counts.size == 0:
        raise ValueError("no cells")
    out: dict[str, float] = {
        "cells": int(counts.size), "empty": int((counts == 0).sum()), "rows": int(counts.sum()),
        "min": int(counts.min()), "p5": float(np.percentile(counts, 5)), "median": float(np.median(counts)),
        "mean": float(counts.mean()), "max": int(counts.max())}
    seen = np.repeat(counts, counts)
    out["msg_p5"] = float(np.percentile(seen, 5)) if seen.size else float("nan")
    out["msg_median"] = float(np.median(seen)) if seen.size else float("nan")
    return out


def anonymity(rows: Sequence[Any], n_windows: int, buckets: int) -> dict[str, Any]:
    """The two distributions of S6 for one dump."""
    per_window, per_bucket_window = cell_counts(rows, n_windows, buckets)
    return {"n_windows": n_windows, "buckets": buckets, "per_window": distribution(per_window),
            "per_bucket_window": distribution(per_bucket_window),
            "rows_per_window": [int(x) for x in per_window]}
