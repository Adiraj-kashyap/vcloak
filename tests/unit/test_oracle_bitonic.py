"""M01 S1: the reference bitonic network (schedule, GPU pair indexing, sort vs np.lexsort)."""
from __future__ import annotations

import numpy as np
import pytest

from vcloak.oracle.reference import bitonic_pairs, bitonic_schedule, bitonic_sort, bitonic_stages

SIZES = [1 << e for e in range(1, 13)]
KINDS = ("random", "sorted", "reverse", "all_equal", "two_value")


def _keys(kind: str, n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    if kind == "random":
        return rng.integers(0, 2**64, n, dtype=np.uint64), rng.integers(0, 2**64, n, dtype=np.uint64)
    if kind == "sorted":
        return np.arange(n, dtype=np.uint64) // 3, np.arange(n, dtype=np.uint64)
    if kind == "reverse":
        return np.arange(n, dtype=np.uint64)[::-1].copy() // 3, np.arange(n, dtype=np.uint64)[::-1].copy()
    if kind == "all_equal":
        return np.full(n, 7, dtype=np.uint64), np.full(n, 2**64 - 1, dtype=np.uint64)
    return rng.integers(0, 2, n, dtype=np.uint64) * np.uint64(2**63), rng.integers(0, 2, n, dtype=np.uint64)


@pytest.mark.parametrize("n", SIZES)
def test_pairs_equal_schedule(n: int) -> None:
    sched = bitonic_schedule(n)
    pairs = list(bitonic_pairs(n))
    assert [(k, j) for k, j, *_ in pairs] == list(bitonic_stages(n))
    assert len(sched) == len(pairs) == (n.bit_length() - 1) * n.bit_length() // 2
    for (lo, hi, asc), (_, _, i, l, a) in zip(sched, pairs, strict=True):
        assert np.array_equal(lo, i) and np.array_equal(hi, l) and np.array_equal(asc, a)


@pytest.mark.parametrize("n", SIZES)
def test_each_stage_touches_every_element_once(n: int) -> None:
    for _, _, i, l, _ in bitonic_pairs(n):  # ADR-005: no two threads write the same element
        assert np.array_equal(np.sort(np.concatenate([i, l])), np.arange(n))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("n", SIZES)
def test_sort_equals_lexsort(n: int, kind: str) -> None:
    for seed in (1, 2, 3):
        hi, lo = _keys(kind, n, seed)
        slot = np.arange(n, dtype=np.uint32)
        (shi, slo, sslot), (pay,) = bitonic_sort([hi, lo, slot], [slot])
        order = np.lexsort((slot, lo, hi))
        assert np.array_equal(shi, hi[order]) and np.array_equal(slo, lo[order])
        assert np.array_equal(sslot, slot[order]) and np.array_equal(pay, slot[order])
        assert sslot.dtype == np.uint32 and shi.dtype == np.uint64


def test_sort_leaves_inputs_untouched_and_handles_n1() -> None:
    hi = np.array([3, 1, 2, 0], dtype=np.uint64)
    before = hi.copy()
    bitonic_sort([hi, np.arange(4, dtype=np.uint64)])
    assert np.array_equal(hi, before)
    (one,), _ = bitonic_sort([np.array([5], dtype=np.uint64)])
    assert one.tolist() == [5]


def test_access_trace_is_data_independent() -> None:
    n, traces = 256, []
    for kind in KINDS:
        hi, lo = _keys(kind, n, 9)
        tr: list[bytes] = []
        bitonic_sort([hi, lo, np.arange(n, dtype=np.uint32)], trace=tr)
        traces.append(tr)
    assert all(t == traces[0] for t in traces) and len(traces[0]) == 36


@pytest.mark.parametrize("n", [0, 3, 6, 100])
def test_non_power_of_two_rejected(n: int) -> None:
    with pytest.raises(ValueError):
        bitonic_schedule(n)
