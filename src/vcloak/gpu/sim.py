"""Simulator registry: kernel name -> NumPy twin (ai/GPU_GUIDE.md §2).

Each CUDA kernel added to `kernels/` gets a NumPy function here (or registered from its own module)
that takes the same arguments and computes the same thread-indexed arithmetic over
`t = arange(nthreads)`. The twins give correctness on a GPU-less laptop; they say nothing about speed.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

_REGISTRY: dict[str, Callable[..., Any]] = {}


def register(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register `fn` as the NumPy twin of the CUDA kernel `name`."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name in _REGISTRY and _REGISTRY[name] is not fn:
            raise ValueError(f"simulator twin {name!r} is already registered")
        _REGISTRY[name] = fn
        return fn

    return deco


def get(name: str) -> Callable[..., Any]:
    """Return the NumPy twin of kernel `name`."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"no simulator twin registered for kernel {name!r}; known: {names()}") from None


def names() -> list[str]:
    """Registered kernel names, sorted."""
    return sorted(_REGISTRY)


@register("vector_add")
def vector_add(a: np.ndarray, b: np.ndarray, out: np.ndarray, n: int) -> None:
    """Twin of the M00 probe kernel: out[t] = a[t] + b[t] for thread ids t < n (uint32 wraparound)."""
    t = np.arange(n)
    out[t] = a[t] + b[t]


# ── bitonic network (kernels/common.cuh, kernels/bitonic.cu) ─────────────────
# The twins take the kernel's arguments plus the launch configuration (`grid` blocks of `block`
# threads), because blockIdx and blockDim are inputs of the thread-indexed arithmetic.

MAX_T = 256  # same constant as kernels/bitonic.cu


def _mask64(c: np.ndarray) -> np.ndarray:
    """mask64: all ones where c is non-zero, computed as 0 - (c != 0) in uint64 like the kernel."""
    return np.negative((c != 0).astype(np.uint64))


def _lex_gt3(hi_a: np.ndarray, lo_a: np.ndarray, slot_a: np.ndarray,
             hi_b: np.ndarray, lo_b: np.ndarray, slot_b: np.ndarray) -> np.ndarray:
    gt_hi = (hi_a > hi_b).astype(np.uint64)
    eq_hi = (hi_a == hi_b).astype(np.uint64)
    gt_lo = (lo_a > lo_b).astype(np.uint64)
    eq_lo = (lo_a == lo_b).astype(np.uint64)
    gt_slot = (slot_a > slot_b).astype(np.uint64)
    return _mask64(gt_hi | (eq_hi & (gt_lo | (eq_lo & gt_slot))))


def _cmp_exchange(hi: np.ndarray, lo: np.ndarray, slot: np.ndarray, pay: np.ndarray,
                  i: Any, l: Any, asc: np.ndarray) -> None:  # noqa: E741 - `l` is the kernel's name
    """cmp_exchange over a vector of pairs. `i` and `l` are index expressions into the four columns."""
    a_hi, b_hi = hi[i], hi[l]
    a_lo, b_lo = lo[i], lo[l]
    a_slot, b_slot = slot[i], slot[l]
    a_pay, b_pay = pay[i], pay[l]
    sw = ~(asc ^ _lex_gt3(a_hi, a_lo, a_slot, b_hi, b_lo, b_slot))
    sw32 = sw.astype(np.uint32)  # (u32)m: the low 32 bits of the mask
    for col, a, b, m in ((hi, a_hi, b_hi, sw), (lo, a_lo, b_lo, sw),
                         (slot, a_slot, b_slot, sw32), (pay, a_pay, b_pay, sw32)):
        d = (a ^ b) & m
        col[i] = a ^ d
        col[l] = b ^ d


@register("bitonic_pairs_global")
def bitonic_pairs_global(hi: np.ndarray, lo: np.ndarray, slot: np.ndarray, pay: np.ndarray,
                         k: int, j: int, npairs: int, *, grid: int, block: int) -> None:
    """Twin of the global stage: thread t owns the pair (i, i + j), i = t + (t & ~(j - 1))."""
    t = np.arange(grid * block, dtype=np.uint32)
    t = t[t < np.uint32(npairs)]
    i = t + (t & ~np.uint32(j - 1))
    l = i + np.uint32(j)  # noqa: E741
    asc = _mask64((i & np.uint32(k)) == 0)
    _cmp_exchange(hi, lo, slot, pay, i, l, asc)


def _tiles(cols: tuple[np.ndarray, ...], n: int, grid: int, block: int) -> tuple[list[np.ndarray], np.ndarray, int]:
    """The shared-memory load: one row of 2T records per block whose tile starts below n."""
    if block > MAX_T:
        raise ValueError(f"block size {block} exceeds MAX_T = {MAX_T}")
    base = np.arange(grid, dtype=np.uint32) * np.uint32(2 * block)
    base = base[base < np.uint32(n)]
    live = base.shape[0]
    return [c[: live * 2 * block].reshape(live, 2 * block).copy() for c in cols], base, live


def _tile_stage(s: list[np.ndarray], base: np.ndarray, k: int, j: int, block: int) -> None:
    t = np.arange(block, dtype=np.uint32)
    i = t + (t & ~np.uint32(j - 1))
    l = i + np.uint32(j)  # noqa: E741
    asc = _mask64(((base[:, None] + i[None, :]) & np.uint32(k)) == 0)
    _cmp_exchange(s[0], s[1], s[2], s[3], (slice(None), i), (slice(None), l), asc)


def _store(cols: tuple[np.ndarray, ...], s: list[np.ndarray], live: int, block: int) -> None:
    for c, sc in zip(cols, s, strict=True):
        c[: live * 2 * block] = sc.reshape(-1)


@register("bitonic_shared")
def bitonic_shared(hi: np.ndarray, lo: np.ndarray, slot: np.ndarray, pay: np.ndarray,
                   k: int, j_start: int, n: int, *, grid: int, block: int) -> None:
    """Twin of the shared stages of one k: j = j_start, j_start / 2, ..., 1 inside each tile of 2T."""
    cols = (hi, lo, slot, pay)
    s, base, live = _tiles(cols, n, grid, block)
    j = j_start
    while j > 0:
        _tile_stage(s, base, k, j, block)
        j >>= 1
    _store(cols, s, live, block)


@register("bitonic_shared_full")
def bitonic_shared_full(hi: np.ndarray, lo: np.ndarray, slot: np.ndarray, pay: np.ndarray,
                        n: int, *, grid: int, block: int) -> None:
    """Twin of the initial local sort: every stage with k <= 2T inside each tile."""
    cols = (hi, lo, slot, pay)
    s, base, live = _tiles(cols, n, grid, block)
    k = 2
    while k <= 2 * block:
        j = k >> 1
        while j > 0:
            _tile_stage(s, base, k, j, block)
            j >>= 1
        k <<= 1
    _store(cols, s, live, block)
