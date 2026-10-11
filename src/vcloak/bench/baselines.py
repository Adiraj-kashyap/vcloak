"""CPU sorting baselines for the GPU/CPU crossover (M07 S3). All sort SoA records (hi, lo, slot, pay)
by (hi, lo, slot), like `vcloak.gpu.kernels.gpu_bitonic_sort`, and return new columns.

Oblivious by construction (the comparator sequence depends on n only):
- `oracle_bitonic`  the M01 oracle network (`vcloak.oracle.reference.bitonic_sort` arithmetic: index
                    arrays and fancy indexing per stage), with the schedule built one stage at a time so
                    that large n do not hold every stage's index arrays in memory at once.
- `views_bitonic`   the same network on reshaped views (no index arrays): the faster single-thread NumPy form.
- `numba_bitonic`   the same network as a parallel loop over pairs, when numba is installed.

Not oblivious (a lower bound for what a CPU can do, never a candidate for the crossover):
- `lexsort`         `np.lexsort`.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from vcloak.oracle.reference import bitonic_stages

Cols = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
N_KEYS = 3  # hi, lo, slot
OBLIVIOUS = ("oracle_bitonic", "views_bitonic", "numba_bitonic")
NON_OBLIVIOUS = ("lexsort",)


def lexsort(cols: Cols) -> Cols:
    hi, lo, slot, _ = cols
    order = np.lexsort((slot, lo, hi))
    return tuple(c[order] for c in cols)  # type: ignore[return-value]


def oracle_bitonic(cols: Cols) -> Cols:
    """The oracle's compare-exchange, stage by stage, in its partner-XOR indexing."""
    out = [c.copy() for c in cols]
    n = out[0].shape[0]
    idx = np.arange(n, dtype=np.int64)
    for k, j in bitonic_stages(n):
        part = idx ^ j
        m = part > idx
        lo_i, hi_i = idx[m], part[m]
        asc = (lo_i & k) == 0
        gt = np.zeros(lo_i.shape[0], dtype=bool)
        eq = np.ones(lo_i.shape[0], dtype=bool)
        for c in out[:N_KEYS]:
            a, b = c[lo_i], c[hi_i]
            gt |= eq & (a > b)
            eq &= a == b
        swap = np.where(asc, gt, ~gt)  # select, no branch on data
        for c in out:
            a, b = c[lo_i], c[hi_i]
            c[lo_i] = np.where(swap, b, a)
            c[hi_i] = np.where(swap, a, b)
    return tuple(out)  # type: ignore[return-value]


def views_bitonic(cols: Cols) -> Cols:
    """The same network without index arrays: at stage (k, j) the array is viewed as (n / 2j, 2, j), so
    [:, 0, :] and [:, 1, :] are the two sides of every pair, and the direction of a pair depends on its
    row only (bit k of the pair's lower index), which is public."""
    out = [np.ascontiguousarray(c).copy() for c in cols]
    n = out[0].shape[0]
    for k, j in bitonic_stages(n):
        rows = n // (2 * j)
        v = [c.reshape(rows, 2, j) for c in out]
        desc = ((np.arange(rows, dtype=np.int64) * 2 * j) & k) != 0
        gt = np.zeros((rows, j), dtype=bool)
        eq = np.ones((rows, j), dtype=bool)
        for c in v[:N_KEYS]:
            a, b = c[:, 0, :], c[:, 1, :]
            gt |= eq & (a > b)
            eq &= a == b
        swap = gt ^ desc[:, None]  # the keys are unique, so "not greater" is "less"
        for c in v:
            a = c[:, 0, :].copy()
            b = c[:, 1, :]
            c[:, 0, :] = np.where(swap, b, a)
            c[:, 1, :] = np.where(swap, a, b)
    return tuple(out)  # type: ignore[return-value]


def _stage_source(prange: Any) -> Callable[..., None]:
    """One stage, one pair per iteration (the indexing of kernels/bitonic.cu), as a plain function that
    runs under the interpreter with `range` and is compiled by numba with `numba.prange`."""

    def stage(hi, lo, slot, pay, k, j):  # noqa: ANN001, ANN202 - typed by numba at the first call
        npairs = hi.shape[0] // 2
        for t in prange(npairs):
            i = t + (t & ~(j - 1))
            m = i + j
            a_hi, b_hi, a_lo, b_lo, a_s, b_s = hi[i], hi[m], lo[i], lo[m], slot[i], slot[m]
            gt = (a_hi > b_hi) | ((a_hi == b_hi) & ((a_lo > b_lo) | ((a_lo == b_lo) & (a_s > b_s))))
            swap = gt ^ ((i & k) != 0)
            a_p, b_p = pay[i], pay[m]
            # Written as a conditional swap. Whether the compiler emits selects or a branch is not checked:
            # this is a CPU timing baseline, not a part of the server.
            if swap:
                hi[i], hi[m] = b_hi, a_hi
                lo[i], lo[m] = b_lo, a_lo
                slot[i], slot[m] = b_s, a_s
                pay[i], pay[m] = b_p, a_p

    return stage


def pairs_bitonic(cols: Cols, stage: Callable[..., None] | None = None) -> Cols:
    """The network driven stage by stage through `stage` (pure Python by default: for tests at small n)."""
    stage = stage or _stage_source(range)
    out = [np.ascontiguousarray(c).copy() for c in cols]
    for k, j in bitonic_stages(out[0].shape[0]):
        stage(*out, k, j)
    return tuple(out)  # type: ignore[return-value]


def numba_stage() -> tuple[Callable[..., None] | None, dict[str, Any]]:
    """(compiled parallel stage, info) when numba is importable, else (None, {"reason": ...})."""
    try:
        import numba  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001 - absent, or present but broken on this interpreter
        return None, {"reason": f"numba is not available ({type(e).__name__})"}
    try:
        stage = numba.njit(parallel=True, cache=False)(_stage_source(numba.prange))
        info = {"numba": numba.__version__, "threads": int(numba.get_num_threads())}
    except Exception as e:  # noqa: BLE001
        return None, {"reason": f"numba could not build the stage ({type(e).__name__})"}
    return stage, info


def mismatches(got: Cols, cols: Cols) -> int:
    """Elements in which `got` differs from the records sorted by (hi, lo, slot)."""
    return sum(int(np.count_nonzero(g != w)) for g, w in zip(got, lexsort(cols), strict=True))
