"""Host driver for the CUDA kernels (ai/GPU_GUIDE.md §2-§3). M03: the bitonic sorting network.

The launch sequence is a function of the public values n and T only (`launch_plan`); the data never
influences which kernel runs, with which grid, or how often. Device arrays (CuPy) run the kernels in
`kernels/bitonic.cu`; NumPy arrays run their twins in `vcloak.gpu.sim` with the same launch plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from vcloak.gpu import sim

KERNEL_DIR = Path(__file__).resolve().parents[3] / "kernels"
BITONIC_KERNELS = ("bitonic_pairs_global", "bitonic_shared", "bitonic_shared_full")
DEFAULT_T = 256  # threads per block in the shared kernels; a tile is 2T records. Public.
GLOBAL_BLOCK = 256
COLUMN_DTYPES = (np.uint64, np.uint64, np.uint32, np.uint32)  # hi, lo, slot, pay


@dataclass(frozen=True)
class Launch:
    """One kernel launch. `stages` are the (k, j) network stages it performs, in order."""

    kernel: str
    grid: int
    block: int
    k: int
    j: int
    stages: tuple[tuple[int, int], ...]


def _check_pow2(name: str, v: int) -> None:
    if v < 1 or v & (v - 1):
        raise ValueError(f"{name} must be a power of two, got {v}")


def clamp_tile(n: int, T: int = DEFAULT_T) -> int:  # noqa: N803 - T is the spec's name
    """Threads per shared block for n records: T, clamped to n / 2 so one tile never exceeds the array."""
    _check_pow2("n", n)
    _check_pow2("T", T)
    if T > sim.MAX_T:
        raise ValueError(f"T must be <= {sim.MAX_T} (the shared arrays in kernels/bitonic.cu), got {T}")
    return max(1, min(T, n // 2))


def _global(n: int, k: int, j: int) -> Launch:
    npairs = n // 2
    block = min(GLOBAL_BLOCK, npairs)
    return Launch("bitonic_pairs_global", npairs // block, block, k, j, ((k, j),))


@lru_cache(maxsize=64)
def launch_plan(n: int, T: int = DEFAULT_T) -> tuple[Launch, ...]:  # noqa: N803
    """The launches that sort n records: a local sort of every tile (k <= 2T), then for each k > 2T one
    global launch per j > T and one shared launch for j = T, ..., 1. Depends only on n and T."""
    t = clamp_tile(n, T)
    if n < 2:
        return ()
    local = tuple((k, j) for k in _pow2_range(2, 2 * t) for j in _pow2_down(k // 2))
    plan = [Launch("bitonic_shared_full", n // (2 * t), t, 2 * t, t, local)]
    for k in _pow2_range(4 * t, n):
        plan += [_global(n, k, j) for j in _pow2_down(k // 2) if j > t]
        plan.append(Launch("bitonic_shared", n // (2 * t), t, k, t, tuple((k, j) for j in _pow2_down(t))))
    return tuple(plan)


def global_only_plan(n: int) -> tuple[Launch, ...]:
    """Every stage as a global launch (no shared memory). Used to test the global kernel on its own."""
    _check_pow2("n", n)
    return tuple(_global(n, k, j) for k in _pow2_range(2, n) for j in _pow2_down(k // 2))


def _pow2_range(lo: int, hi: int) -> list[int]:
    out = []
    while lo <= hi:
        out.append(lo)
        lo *= 2
    return out


def _pow2_down(hi: int) -> list[int]:
    out = []
    while hi >= 1:
        out.append(hi)
        hi //= 2
    return out


@lru_cache(maxsize=1)
def _bitonic_module() -> Any:
    import cupy as cp  # type: ignore[import-not-found]

    src = (KERNEL_DIR / "bitonic.cu").read_text(encoding="utf-8")
    return cp.RawModule(code=src, options=("-std=c++17", "-I" + str(KERNEL_DIR)))


def _check_columns(cols: tuple[Any, ...]) -> int:
    n = int(cols[0].shape[0])
    for name, c, dt in zip(("hi", "lo", "slot", "pay"), cols, COLUMN_DTYPES, strict=True):
        if c.ndim != 1 or int(c.shape[0]) != n:
            raise ValueError(f"column {name} must be one-dimensional with {n} elements, got shape {c.shape}")
        if c.dtype != dt:
            raise TypeError(f"column {name} must be {np.dtype(dt).name}, got {c.dtype}")
        if not c.flags.c_contiguous:
            raise ValueError(f"column {name} must be contiguous")
    _check_pow2("n", n)
    return n


def run_launch(cols: tuple[Any, ...], launch: Launch) -> None:
    """Execute one launch in place: the CUDA kernel for device arrays, its NumPy twin for host arrays."""
    n = int(cols[0].shape[0])
    if launch.kernel == "bitonic_pairs_global":
        scalars = (launch.k, launch.j, n // 2)
    elif launch.kernel == "bitonic_shared":
        scalars = (launch.k, launch.j, n)
    else:
        scalars = (n,)
    if isinstance(cols[0], np.ndarray):
        sim.get(launch.kernel)(*cols, *scalars, grid=launch.grid, block=launch.block)
    else:
        fn = _bitonic_module().get_function(launch.kernel)
        fn((launch.grid,), (launch.block,), (*cols, *(np.uint32(s) for s in scalars)))


def gpu_bitonic_sort(d_hi: Any, d_lo: Any, d_slot: Any, d_pay: Any, *, T: int = DEFAULT_T) -> None:  # noqa: N803
    """Sort the records (hi, lo, slot, pay) in place by (hi, lo, slot); `pay` travels with its key.

    hi and lo are uint64, slot and pay uint32, all of the same power-of-two length. The slot column
    must make the keys unique. Device arrays are sorted on the GPU; NumPy arrays by the simulator.
    """
    cols = (d_hi, d_lo, d_slot, d_pay)
    n = _check_columns(cols)
    for launch in launch_plan(n, T):
        run_launch(cols, launch)
