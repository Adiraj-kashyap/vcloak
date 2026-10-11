"""M08 S1 on the runner: the planted-leak kernel against its NumPy twin (simulator parity, ai/TESTING.md §3)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from vcloak.gpu import sim

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import run_dudect as rd  # noqa: E402

pytestmark = pytest.mark.gpu


def inputs(n: int, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng([seed, n])
    two = rng.integers(0, 2, n, dtype=np.uint32) * np.uint32(0xDEADBEEF)
    return {"random": rng.integers(0, 2**32, n, dtype=np.uint32), "zeros": np.zeros(n, dtype=np.uint32),
            "all_equal": np.full(n, 7, dtype=np.uint32), "sorted": np.arange(n, dtype=np.uint32),
            "reverse": np.arange(n, dtype=np.uint32)[::-1].copy(), "two_value": two}


@pytest.mark.parametrize("log2n", [6, 10, 16])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_planted_leak_matches_its_twin(backend, log2n: int, seed: int) -> None:  # noqa: ANN001
    n = 1 << log2n
    t = rd.ControlLeak(backend, n, seed)
    for name, x in inputs(n, seed).items():
        rd.put(t.x, x)
        t.run()
        want = np.empty(n, dtype=np.uint32)
        sim.get("planted_leak")(x, want, n, rd.LEAK_SPINS, grid=t.grid, block=t.block)
        assert np.array_equal(rd.to_host(t.out), want), name
