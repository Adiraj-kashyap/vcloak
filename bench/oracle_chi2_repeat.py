#!/usr/bin/env python3
"""M14 S7 diagnostic: the chi-square uniformity statistic of the CPU oracle, repeated with fresh keys.

    python bench/oracle_chi2_repeat.py [--reps 10] [--n 64] [--epochs 20000] [--quick] [--out runs]

One run of `seed/vcloak_oracle.py` gives one chi-square statistic, from one key the oracle draws from the OS.
This repeats exactly that computation (the oracle's own `chacha_tags` and `bitonic_sort`, the same table, the
same (n-1)/n correction) for `--reps` fresh keys, to see whether a statistic in the tail is one draw or a bias.
It is a diagnostic chosen after the comparison was read, and it is labelled so: it changes no verdict.

Nothing here touches a GPU and nothing is a performance result. Outputs: oracle_chi2_repeat.json, summary.json.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "bench")]

from run_oracle_compare import load_oracle  # noqa: E402

from vcloak import runs  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--n", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=None, help="permutations per table (20000; quick: 2000)")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="runs")
    a = ap.parse_args(argv)
    epochs = a.epochs or (2000 if a.quick else 20_000)
    command = "python bench/oracle_chi2_repeat.py " + " ".join(argv if argv is not None else sys.argv[1:])
    run_dir = runs.new_run("M14", "oracle_chi2_repeat", step="S7", owner="Abhishek", command=command.strip(),
                           quick=a.quick, root=ROOT, runs_dir=a.out, backend=get_backend("numpy"),
                           params={"reps": a.reps, "n": a.n, "epochs": epochs, "oracle": "seed/vcloak_oracle.py",
                                   "keys": "one fresh 32-byte key from the OS per repetition, never stored"})
    mod = load_oracle(run_dir / "oracle")
    n, dof, corr, exp = a.n, (a.n - 1) ** 2, (a.n - 1) / a.n, epochs / a.n
    si, cols = np.arange(n, dtype=np.uint64), np.arange(n)
    tables = []
    for i in range(a.reps):
        t0, base = time.perf_counter(), os.urandom(32)
        counts = np.zeros((n, n), dtype=np.int64)
        for r in range(epochs):
            hi, lo = mod.chacha_tags(base, r, n)
            _, (perm,) = mod.bitonic_sort([hi, lo, si], [si])
            counts[perm.astype(np.int64), cols] += 1
        chi2 = float(corr * ((counts - exp) ** 2 / exp).sum())
        tables.append({"chi2": chi2, "p_value": float(stats.chi2.sf(chi2, dof))})
        print(f"repetition {i + 1} of {a.reps}: chi2 {chi2:.1f}, p {tables[-1]['p_value']:.4f} "
              f"({time.perf_counter() - t0:.0f} s)", flush=True)
    chis = [t["chi2"] for t in tables]
    below = sum(t["p_value"] < 0.01 for t in tables)
    doc = {"stage": "S7 diagnostic", "n": n, "epochs": epochs, "dof": dof, "tables": tables,
           "chi2_min": min(chis), "chi2_median": statistics.median(chis), "chi2_max": max(chis),
           "p_below_0_01": below}
    (run_dir / "oracle_chi2_repeat.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    at = f"over {a.reps} fresh keys, n {n}, {epochs} epochs, dof {dof}"
    metrics = [{"id": "S-ORACLE-CHI2-REP-MIN", "value": doc["chi2_min"], "unit": "-", "stat": f"smallest statistic {at}"},
               {"id": "S-ORACLE-CHI2-REP-MEDIAN", "value": doc["chi2_median"], "unit": "-", "stat": f"median {at}"},
               {"id": "S-ORACLE-CHI2-REP-MAX", "value": doc["chi2_max"], "unit": "-", "stat": f"largest statistic {at}"},
               {"id": "S-ORACLE-CHI2-REP-PBELOW", "value": below, "unit": "tables",
                "stat": f"tables with p below 0.01, {at}"},
               {"id": "S-ORACLE-CHI2-REP-N", "value": a.reps, "unit": "tables", "stat": "fresh keys"}]
    (run_dir / "summary.json").write_text(json.dumps({"metrics": metrics}, indent=2) + "\n", encoding="utf-8")
    runs.finish_run(run_dir, status="OK", notes=(
        f"S7 diagnostic, chosen after the comparison was read: the oracle's chi-square statistic for {a.reps} fresh "
        f"keys, median {doc['chi2_median']:.1f} at dof {dof}, {below} below p 0.01. CPU oracle (numpy), no GPU."))
    print(f"median {doc['chi2_median']:.1f} (dof {dof}), range {doc['chi2_min']:.1f} to {doc['chi2_max']:.1f}, "
          f"{below} of {a.reps} below p 0.01")
    print("run dir:", run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
