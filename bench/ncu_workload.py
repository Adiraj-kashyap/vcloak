#!/usr/bin/env python3
"""M08 S4 - the kernels that Nsight Compute profiles. Run under `ncu` by bench/run_ncu.py, never by hand.

One fused sort (bitonic_shared_full, bitonic_pairs_global, bitonic_shared), one global-only pass of the
last merge step, one aead_open_seq and one launch of the planted-leak kernel on a half-zero input (the
positive control: it must show divergent branches), all at n = 2^log2n on random TEST data.
The outputs are checked, so a profile of wrong results cannot be recorded.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import run_dudect as rd  # noqa: E402
from vcloak.gpu.kernels import global_only_plan, run_launch  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--log2n", type=int, default=16)
    ap.add_argument("--seed", type=int, default=8)
    a = ap.parse_args(argv)
    backend = get_backend()
    n = 1 << a.log2n
    rng = np.random.default_rng([a.seed, n, 500])
    sync = backend.xp.cuda.get_current_stream().synchronize if backend.is_gpu else (lambda: None)
    bad = 0

    sort = rd.BitonicSorted(backend, n, a.seed)
    sort.prepare(1, rng)  # fresh random tags
    sort.run()
    sync()
    bad += sort.check(1)
    for launch in global_only_plan(n)[-a.log2n:]:  # the last merge step (k = n) as global launches
        run_launch(sort.cols, launch)
    sync()

    aead = rd.AeadTag(backend, n, a.seed)
    aead.prepare(0, rng)
    aead.run()
    sync()
    bad += aead.check(0)

    leak = rd.ControlLeak(backend, n, a.seed)
    x = rng.integers(0, 2**32, n, dtype=np.uint32)
    x[::2] = 0  # neighbouring threads take different sides of the planted branch
    leak.last = x
    rd.put(leak.x, x)
    leak.run()
    sync()
    bad += leak.check(1)

    print(f"ncu_workload backend={backend.name} n=2^{a.log2n} mismatches={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
