"""M03: the bitonic kernels and their NumPy twins against the oracle (ai/TESTING.md §2b, §3).

Every test with the `xp` fixture runs twice: on NumPy arrays (the simulator twins, on any machine) and
on CuPy arrays (the CUDA kernels, marked `gpu`, on the runner only). Equality is byte equality.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from vcloak.gpu import kernels
from vcloak.gpu.kernels import DEFAULT_T, clamp_tile, global_only_plan, gpu_bitonic_sort, launch_plan, run_launch
from vcloak.gpu.runtime import get_backend
from vcloak.oracle.reference import bitonic_schedule, bitonic_sort, bitonic_stages

Cols = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]

SIZES = (1 << 6, 1 << 10, 1 << 16)  # ai/TESTING.md §3; 2^max_log2n is test_max_log2n
CASES = (("random", 1), ("random", 2), ("random", 3), ("all_equal", 1), ("sorted", 1), ("reverse", 1),
         ("two_value", 1))
SMALL = tuple((n, t) for n in (2, 4, 8, 32, 256, 1024) for t in (1, 2, 8, DEFAULT_T))


def make_cols(kind: str, n: int, seed: int) -> Cols:
    """(hi, lo, slot, pay). slot makes the keys unique; pay is unrelated to the key, so a payload that
    does not travel with its key is caught."""
    rng = np.random.default_rng([seed, n])
    slot = rng.permutation(n).astype(np.uint32)
    pay = rng.integers(0, 2**32, n, dtype=np.uint32)
    if kind == "random":
        hi, lo = rng.integers(0, 2**64, n, dtype=np.uint64), rng.integers(0, 2**64, n, dtype=np.uint64)
    elif kind == "all_equal":
        hi, lo = np.full(n, 7, dtype=np.uint64), np.full(n, 2**64 - 1, dtype=np.uint64)
    elif kind == "sorted":
        hi, lo, slot = np.arange(n, dtype=np.uint64) // 3, np.arange(n, dtype=np.uint64), np.arange(n, dtype=np.uint32)
    elif kind == "reverse":
        hi, lo = np.arange(n, dtype=np.uint64)[::-1] // 3, np.arange(n, dtype=np.uint64)[::-1].copy()
        slot = np.arange(n, dtype=np.uint32)[::-1].copy()
    elif kind == "two_value":
        hi = rng.integers(0, 2, n, dtype=np.uint64) * np.uint64(2**63)
        lo = rng.integers(0, 2, n, dtype=np.uint64) * np.uint64(2**64 - 1)
    else:
        raise ValueError(kind)
    return np.ascontiguousarray(hi), lo, slot, pay


def oracle(cols: Cols) -> Cols:
    (hi, lo, slot), (pay,) = bitonic_sort([cols[0], cols[1], cols[2]], [cols[3]])
    return hi, lo, slot, pay


def oracle_prefix(cols: Cols, n_stages: int) -> Cols:
    """The oracle's compare-exchange (reference.bitonic_sort's loop body) for the first n_stages stages."""
    out = [c.copy() for c in cols]
    for lo_i, hi_i, asc in bitonic_schedule(out[0].shape[0])[:n_stages]:
        gt = np.zeros(lo_i.shape[0], dtype=bool)
        eq = np.ones(lo_i.shape[0], dtype=bool)
        for c in out[:3]:
            a, b = c[lo_i], c[hi_i]
            gt |= eq & (a > b)
            eq &= a == b
        swap = np.where(asc, gt, ~gt)
        for c in out:
            a, b = c[lo_i], c[hi_i]
            c[lo_i], c[hi_i] = np.where(swap, b, a), np.where(swap, a, b)
    return out[0], out[1], out[2], out[3]


def assert_bytes_equal(got: Any, want: Cols, what: str) -> None:
    for name, g, w in zip(("hi", "lo", "slot", "pay"), got, want, strict=True):
        g = to_host(g)
        assert g.dtype == w.dtype, f"{what}: {name} dtype {g.dtype} != {w.dtype}"
        assert g.tobytes() == w.tobytes(), f"{what}: column {name} differs ({int(np.count_nonzero(g != w))} elements)"


def to_host(a: Any) -> np.ndarray:
    return a if isinstance(a, np.ndarray) else a.get()


@pytest.fixture(params=["numpy", pytest.param("cupy", marks=pytest.mark.gpu)])
def xp(request: pytest.FixtureRequest) -> Any:
    """Array module: numpy runs the simulator twins, cupy the CUDA kernels."""
    return np if request.param == "numpy" else pytest.importorskip("cupy")


def on(xp: Any, cols: Cols) -> tuple[Any, ...]:
    return tuple(xp.asarray(c.copy()) for c in cols)


# ── the launch plan is public (A4) and race-free by construction (A2) ────────


@pytest.mark.parametrize("n", [1 << e for e in range(0, 18)])
@pytest.mark.parametrize("T", [1, 4, 32, DEFAULT_T])
def test_plan_covers_every_stage_once_in_order(n: int, T: int) -> None:  # noqa: N803
    plan = launch_plan(n, T)
    assert [s for launch in plan for s in launch.stages] == list(bitonic_stages(n))
    t = clamp_tile(n, T)
    for launch in plan:
        if launch.kernel == "bitonic_pairs_global":
            assert launch.grid * launch.block == n // 2 and launch.j > t and len(launch.stages) == 1
        else:
            assert launch.block == t and launch.grid * 2 * t == n
            assert all(j <= t for _, j in launch.stages)


def test_plan_shape_at_2_16_and_tile_clamp() -> None:
    plan = launch_plan(1 << 16)
    names = [launch.kernel for launch in plan]
    assert names[0] == "bitonic_shared_full" and names.count("bitonic_shared_full") == 1
    assert names.count("bitonic_shared") == 16 - 9  # one per k = 2^10 .. 2^16
    assert names.count("bitonic_pairs_global") == sum(range(1, 8))  # k = 2^(9+m) has m stages with j > T
    assert clamp_tile(64) == 32 and [launch.kernel for launch in launch_plan(64)] == ["bitonic_shared_full"]
    assert launch_plan(1) == () and clamp_tile(2) == 1


@pytest.mark.parametrize(("n", "T"), [(1 << 12, DEFAULT_T), (256, 8), (64, DEFAULT_T), (2, 1)])
def test_no_element_is_written_by_two_threads(n: int, T: int) -> None:  # noqa: N803
    """ADR-005: in every launch (global) and between every two barriers (shared), the pairs
    (i, i + j) with i = t + (t & ~(j - 1)) partition the elements the launch may write."""
    for launch in launch_plan(n, T):
        if launch.kernel == "bitonic_pairs_global":
            t = np.arange(launch.grid * launch.block, dtype=np.uint32)
            i = t + (t & ~np.uint32(launch.j - 1))
            assert np.array_equal(np.sort(np.concatenate([i, i + np.uint32(launch.j)])), np.arange(n))
        else:
            t = np.arange(launch.block, dtype=np.uint32)
            for _, j in launch.stages:
                i = t + (t & ~np.uint32(j - 1))
                assert np.array_equal(np.sort(np.concatenate([i, i + np.uint32(j)])), np.arange(2 * launch.block))
            assert np.array_equal(np.sort(np.concatenate([t, t + np.uint32(launch.block)])),
                                  np.arange(2 * launch.block))  # load and store: two elements per thread


# ── bit-exactness against the oracle (A1, G5) ────────────────────────────────


@pytest.mark.parametrize(("kind", "seed"), CASES)
@pytest.mark.parametrize("n", SIZES)
def test_sort_equals_oracle(xp: Any, n: int, kind: str, seed: int) -> None:
    cols = make_cols(kind, n, seed)
    d = on(xp, cols)
    gpu_bitonic_sort(*d)
    assert_bytes_equal(d, oracle(cols), f"n={n} {kind} seed={seed}")


@pytest.mark.parametrize(("n", "T"), SMALL)
def test_sort_equals_oracle_small_tiles(xp: Any, n: int, T: int) -> None:  # noqa: N803
    for seed in (1, 2, 3):
        cols = make_cols("random", n, seed)
        d = on(xp, cols)
        gpu_bitonic_sort(*d, T=T)
        assert_bytes_equal(d, oracle(cols), f"n={n} T={T} seed={seed}")


@pytest.mark.parametrize(("kind", "seed"), CASES)
def test_global_kernel_alone_equals_oracle(xp: Any, kind: str, seed: int) -> None:
    """S2: every stage of n = 2^10 through bitonic_pairs_global only."""
    cols = make_cols(kind, 1 << 10, seed)
    d = on(xp, cols)
    for launch in global_only_plan(1 << 10):
        run_launch(d, launch)
    assert_bytes_equal(d, oracle(cols), f"global only {kind} seed={seed}")


@pytest.mark.parametrize(("n", "T"), [(1 << 12, DEFAULT_T), (1 << 10, 16), (256, 8)])
def test_every_launch_matches_the_oracle_stage_by_stage(xp: Any, n: int, T: int) -> None:  # noqa: N803
    """S3: the tile-local sort and each later launch leave exactly the oracle's intermediate state."""
    cols = make_cols("random", n, 1)
    d = on(xp, cols)
    done = 0
    for launch in launch_plan(n, T):
        run_launch(d, launch)
        done += len(launch.stages)
        assert_bytes_equal(d, oracle_prefix(cols, done), f"after {launch.kernel} k={launch.k} j={launch.j}")


def test_output_is_sorted_and_payload_follows_its_key(xp: Any) -> None:
    hi, lo, slot, pay = make_cols("two_value", 1 << 10, 2)
    d = on(xp, (hi, lo, slot, pay))
    gpu_bitonic_sort(*d)
    order = np.lexsort((slot, lo, hi))
    assert_bytes_equal(d, (hi[order], lo[order], slot[order], pay[order]), "lexsort")


def test_rejects_bad_columns() -> None:
    hi, lo, slot, pay = make_cols("random", 64, 1)
    with pytest.raises(ValueError, match="power of two"):
        gpu_bitonic_sort(hi[:48].copy(), lo[:48].copy(), slot[:48].copy(), pay[:48].copy())
    with pytest.raises(TypeError, match="slot must be uint32"):
        gpu_bitonic_sort(hi, lo, slot.astype(np.uint64), pay)
    with pytest.raises(ValueError, match="pay must be one-dimensional with 64"):
        gpu_bitonic_sort(hi, lo, slot, pay[:32].copy())
    with pytest.raises(ValueError, match="T must be <="):
        gpu_bitonic_sort(hi, lo, slot, pay, T=512)
    with pytest.raises(ValueError, match="contiguous"):
        gpu_bitonic_sort(np.repeat(hi, 2)[::2], lo, slot, pay)


def test_every_bitonic_kernel_has_a_twin_and_a_source() -> None:
    from vcloak.gpu import sim

    src = (kernels.KERNEL_DIR / "bitonic.cu").read_text(encoding="utf-8")
    for name in kernels.BITONIC_KERNELS:
        assert name in sim.names() and f"void {name}(" in src


# ── runner only: simulator parity and the largest size ───────────────────────


@pytest.mark.gpu
@pytest.mark.parametrize(("kind", "seed"), CASES)
@pytest.mark.parametrize("n", SIZES)
def test_gpu_equals_simulator(n: int, kind: str, seed: int) -> None:
    cp = pytest.importorskip("cupy")
    cols = make_cols(kind, n, seed)
    d, s = on(cp, cols), on(np, cols)
    gpu_bitonic_sort(*d)
    gpu_bitonic_sort(*s)
    assert_bytes_equal(d, s, f"gpu vs twin n={n} {kind} seed={seed}")  # type: ignore[arg-type]


@pytest.mark.gpu
@pytest.mark.slow
@pytest.mark.parametrize(("kind", "seed"), CASES)
def test_max_log2n(kind: str, seed: int) -> None:
    """n = 2^max_log2n of the device. The reference is np.lexsort: the keys are unique, so the sorted
    order is unique, and the oracle equals lexsort (tests/unit/test_oracle_bitonic.py). The NumPy twin
    is run once at this size (random, seed 1); it needs minutes per sort on a runner CPU."""
    cp = pytest.importorskip("cupy")
    n = 1 << int(get_backend().device_info()["max_log2n"])
    hi, lo, slot, pay = make_cols(kind, n, seed)
    d = on(cp, (hi, lo, slot, pay))
    gpu_bitonic_sort(*d)
    order = np.lexsort((slot, lo, hi))
    assert_bytes_equal(d, (hi[order], lo[order], slot[order], pay[order]), f"n={n} {kind} seed={seed}")
    if (kind, seed) == ("random", 1):
        s = on(np, (hi, lo, slot, pay))
        gpu_bitonic_sort(*s)
        assert_bytes_equal(d, s, f"gpu vs twin n={n}")  # type: ignore[arg-type]
