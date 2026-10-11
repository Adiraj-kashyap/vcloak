"""Reference bitonic network and write/read/re-shuffle paths (ported from seed/vcloak_oracle.py).

The comparator schedule depends on n only, so the access pattern is data-independent. Swaps are
arithmetic selects (`np.where`), the CPU analogue of the masked compare-exchange in kernels/bitonic.cu.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterator

import numpy as np


def _check_pow2(n: int) -> None:
    if n < 1 or n & (n - 1):
        raise ValueError(f"n must be a power of two, got {n}")


def bitonic_stages(n: int) -> Iterator[tuple[int, int]]:
    """The public (k, j) stage sequence: k = 2, 4, ..., n and j = k/2, k/4, ..., 1."""
    _check_pow2(n)
    k = 2
    while k <= n:
        j = k // 2
        while j >= 1:
            yield k, j
            j //= 2
        k *= 2


def bitonic_schedule(n: int) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Comparator schedule as (lo, hi, asc) index arrays per stage, in the seed's partner-XOR form."""
    idx = np.arange(n, dtype=np.int64)
    sched = []
    for k, j in bitonic_stages(n):
        part = idx ^ j
        m = part > idx
        lo, hi = idx[m], part[m]
        sched.append((lo, hi, (lo & k) == 0))
    return sched


def bitonic_pairs(n: int) -> Iterator[tuple[int, int, np.ndarray, np.ndarray, np.ndarray]]:
    """Yield (k, j, i, l, asc) per stage using the one-thread-per-pair indexing of ai/GPU_GUIDE.md §3:
    thread t in [0, n/2) handles i = (t / j) * 2j + (t % j), l = i + j, asc = ((i & k) == 0)."""
    t = np.arange(n // 2, dtype=np.int64)
    for k, j in bitonic_stages(n):
        i = (t // j) * 2 * j + (t % j)
        yield k, j, i, i + j, (i & k) == 0


def bitonic_sort(keys: list[np.ndarray], payload: list[np.ndarray] | None = None,
                 trace: list[bytes] | None = None) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Sort lexicographically by keys[0], keys[1], ... (SoA limbs). The last limb must make the keys
    unique (callers append the slot index). Returns (sorted keys, payload columns in the same order).
    If `trace` is given, a digest of each stage's accessed indices is appended to it."""
    n = keys[0].shape[0]
    cols = [k.copy() for k in keys] + [p.copy() for p in (payload or [])]
    nk = len(keys)
    for lo, hi, asc in bitonic_schedule(n):
        if trace is not None:
            trace.append(hashlib.sha256(lo.tobytes() + hi.tobytes()).digest())
        gt = np.zeros(lo.shape[0], dtype=bool)
        eq = np.ones(lo.shape[0], dtype=bool)
        for c in cols[:nk]:
            a, b = c[lo], c[hi]
            gt |= eq & (a > b)
            eq &= a == b
        swap = np.where(asc, gt, ~gt)  # select, no branch on data
        for c in cols:
            a, b = c[lo], c[hi]
            c[lo] = np.where(swap, b, a)
            c[hi] = np.where(swap, a, b)
    return cols[:nk], cols[nk:]
