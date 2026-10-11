"""M07 S3: every CPU baseline returns the records sorted by (hi, lo, slot), and the bitonic ones agree
with the M01 oracle network."""
from __future__ import annotations

import numpy as np
import pytest

from vcloak.bench import baselines
from vcloak.oracle import reference as ref


def make_cols(n: int, seed: int, *, ties: bool = False) -> baselines.Cols:
    rng = np.random.default_rng([seed, n])
    top = 4 if ties else 2**64  # few distinct (hi, lo) values: the slot column must break the ties
    return (rng.integers(0, top, n, dtype=np.uint64), rng.integers(0, top, n, dtype=np.uint64),
            np.arange(n, dtype=np.uint32), rng.integers(0, 2**32, n, dtype=np.uint32))


@pytest.mark.parametrize("fn", [baselines.oracle_bitonic, baselines.views_bitonic, baselines.lexsort])
@pytest.mark.parametrize("n", [2, 4, 64, 1024, 4096])
@pytest.mark.parametrize("ties", [False, True])
def test_vector_baselines_sort(fn, n: int, ties: bool) -> None:  # noqa: ANN001
    cols = make_cols(n, 7, ties=ties)
    before = tuple(c.copy() for c in cols)
    got = fn(cols)
    assert baselines.mismatches(got, cols) == 0
    assert all(g.dtype == c.dtype for g, c in zip(got, cols, strict=True))
    assert all(np.array_equal(b, c) for b, c in zip(before, cols, strict=True)), "the input must not be modified"


@pytest.mark.parametrize("n", [2, 8, 64, 256])
@pytest.mark.parametrize("ties", [False, True])
def test_pairs_baseline_sorts(n: int, ties: bool) -> None:
    """The source that numba compiles on the runner, run here under the interpreter."""
    cols = make_cols(n, 11, ties=ties)
    assert baselines.mismatches(baselines.pairs_bitonic(cols), cols) == 0


@pytest.mark.parametrize("n", [64, 1024])
def test_oracle_baseline_equals_reference_network(n: int) -> None:
    cols = make_cols(n, 3)
    keys, pay = ref.bitonic_sort(list(cols[:3]), [cols[3]])
    got = baselines.oracle_bitonic(cols)
    assert all(np.array_equal(g, w) for g, w in zip(got, (*keys, *pay), strict=True))


def test_numba_stage_reports_absence_or_sorts() -> None:
    stage, info = baselines.numba_stage()
    if stage is None:
        assert "numba" in info["reason"]
        return
    cols = make_cols(1024, 5)
    assert baselines.mismatches(baselines.pairs_bitonic(cols, stage), cols) == 0


def test_mismatches_counts_differences() -> None:
    cols = make_cols(64, 9)
    assert baselines.mismatches(cols, cols) > 0  # the unsorted input is not the sorted output
