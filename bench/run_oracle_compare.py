#!/usr/bin/env python3
"""M14 S7: run the CPU oracle locally and put its numbers beside the ingested numbers of the real stack.

    python bench/run_oracle_compare.py [--reps 20] [--summary results/security/security_summary.json]
                                       [--s1 RUN --attack RUN --uniformity RUN --trace RUN] [--quick] [--out runs]

1. `seed/vcloak_oracle.py` runs unchanged, with the seed of the device runs (`--quick`: its quick sizes). Its
   output directory is redirected into the run dir (`oracle/`): it never writes into `results/`.
2. The oracle's attack is repeated `--reps` times on the same traffic with fresh keys (the oracle draws its keys
   from the OS), to measure how far a key-dependent number moves from one key to the next.
3. `vcloak.eval.oracle_compare` builds the table; a DIFFERS row is printed and has to become an issue.

The device runs are read, never re-run: by default the ones `results/security/security_summary.json` names. No GPU
is involved and nothing here is a performance result: the oracle's own CPU timings stay in `oracle/results.json`
as raw output and are neither indexed nor reported.

Outputs in the run dir: oracle/ (the oracle's files and its stdout), oracle_reps.json, oracle_comparison.json,
oracle_comparison.csv, summary.json.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import importlib.util
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import runs  # noqa: E402
from vcloak.eval import oracle_compare as oc  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402

ORACLE = ROOT / "seed" / "vcloak_oracle.py"
SUMMARY = ROOT / "results" / "security" / "security_summary.json"
STAGES = {"s1": ("s1", "s1_traffic.json"), "e1": ("attack", "e1_attack.json"), "e0": ("attack", "e0_restoration.json"),
          "e2": ("uniformity", "e2_uniformity.json"), "e3": ("trace", "e3_trace.json")}
REPS, REPS_QUICK = 20, 3


def load_oracle(out: Path) -> ModuleType:
    """The seed oracle as a module, writing into `out` instead of `results/`."""
    spec = importlib.util.spec_from_file_location("vcloak_seed_oracle", ORACLE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    out.mkdir(parents=True, exist_ok=True)
    mod.OUT = out
    return mod


def run_oracle(mod: ModuleType, seed: int, quick: bool) -> dict[str, Any]:
    """The oracle's own `main`, stdout kept in `oracle/stdout.txt`."""
    argv, sys.argv = sys.argv, ["vcloak_oracle.py", "--seed", str(seed)] + (["--quick"] if quick else [])
    try:
        with (mod.OUT / "stdout.txt").open("w", encoding="utf-8") as f, contextlib.redirect_stdout(f):
            mod.main()
    finally:
        sys.argv = argv
    return json.loads((mod.OUT / "results.json").read_text(encoding="utf-8"))


def oracle_reps(mod: ModuleType, oracle: dict[str, Any], windows: list[int], occ_window: int | None,
                reps: int) -> list[dict[str, Any]]:
    """The oracle's attack on the traffic of `oracle`, once per fresh `Keys()`. Only the keys change."""
    tr = oracle["traffic"]
    n_conv, rng = tr["conversations"], np.random.default_rng(oracle["seed"])
    msgs = mod.simulate_traffic(rng, n_conv, tr["duration_s"], 0.05, {c: os.urandom(32) for c in range(n_conv)})
    if len(msgs) != tr["messages"]:
        raise RuntimeError(f"the repetitions regenerated {len(msgs)} messages, the oracle run had {tr['messages']}")
    conv_of = {m.arrival: m.conv for m in msgs}
    slots, buckets = tr["slots_per_epoch"], tr["buckets"]
    out = []
    for i in range(reps):
        t0, keys = time.perf_counter(), mod.Keys()
        rep: dict[str, Any] = {"attack": {"epoch_200ms": mod.order_recovery_attack(
            mod.build_database(keys, msgs, "epoch", 0, slots, buckets, rng), conv_of)}}
        for w in windows:
            rows = mod.build_database(keys, msgs, "window", w, slots, buckets, rng)
            rep["attack"][f"window_{w}s"] = mod.order_recovery_attack(rows, conv_of)
            if w == occ_window:
                occ = Counter((r.bucket, r.round_visible) for r in rows)
                rep["occupancy"] = {"peak": max(occ.values()), "mean": float(np.mean(list(occ.values())))}
        out.append(rep)
        print(f"oracle repetition {i + 1} of {reps}: {time.perf_counter() - t0:.1f} s", flush=True)
    return out


def load_device(dirs: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The stage files of the device runs (layouts keyed by id) and what their manifests say about the stack."""
    device = {k: json.loads((dirs[run] / f).read_text(encoding="utf-8")) for k, (run, f) in STAGES.items()}
    device["e1"]["layouts"] = {v["layout"]: v for v in device["e1"]["layouts"]}
    mans = {k: runs.read_manifest(d) for k, d in dirs.items()}
    stack = {"backend": sorted({m["env"]["backend"] for m in mans.values()}),
             "runner": sorted({m["env"]["runner"] for m in mans.values()}),
             "session_id": sorted({str(m["env"].get("session_id")) for m in mans.values()}),
             "quick": sorted({bool(m["quick"]) for m in mans.values()}),
             "engine": mans["attack"]["params"].get("engine"), "db": mans["attack"]["params"].get("db")}
    return device, stack


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--summary", default=str(SUMMARY), help="security_summary.json naming the device runs")
    for name in ("s1", "attack", "uniformity", "trace"):
        ap.add_argument(f"--{name}", default=None, help=f"device run dir of the {name} stage (overrides --summary)")
    ap.add_argument("--reps", type=int, default=None, help=f"oracle repetitions with fresh keys ({REPS}; quick: "
                    f"{REPS_QUICK})")
    ap.add_argument("--quick", action="store_true", help="the oracle's quick sizes (the device runs must be quick too)")
    ap.add_argument("--out", default="runs", help="parent directory of the run dir")
    a = ap.parse_args(argv)
    reps = a.reps if a.reps is not None else (REPS_QUICK if a.quick else REPS)
    named = {k: getattr(a, k) for k in ("s1", "attack", "uniformity", "trace")}
    if not all(named.values()):
        listed = json.loads(Path(a.summary).read_text(encoding="utf-8"))["run_dirs"]
        named = {k: v or listed[k] for k, v in named.items()}
    dirs = {k: (ROOT / v if not Path(v).is_absolute() else Path(v)) for k, v in named.items()}
    device, stack = load_device(dirs)
    seed = device["e1"]["seed"]
    command = "python bench/run_oracle_compare.py " + " ".join(argv if argv is not None else sys.argv[1:])
    run_dir = runs.new_run(
        "M14", "oracle_compare", step="S7", owner="Abhishek", command=command.strip(), seed=seed, quick=a.quick,
        root=ROOT, runs_dir=a.out, backend=get_backend("numpy"),
        params={"device_runs": {k: d.name for k, d in dirs.items()}, "device_stack": stack, "oracle_reps": reps,
                "oracle": "seed/vcloak_oracle.py", "oracle_sha256": hashlib.sha256(ORACLE.read_bytes()).hexdigest(),
                "family_alpha": 0.01})
    t0 = time.perf_counter()
    mod = load_oracle(run_dir / "oracle")
    oracle = run_oracle(mod, seed, a.quick)
    print(f"oracle run: {oracle['traffic']['messages']} messages, {time.perf_counter() - t0:.0f} s", flush=True)
    lay = device["e1"]["layouts"]
    windows = sorted(int(k[1:]) for k in lay if k.startswith("W"))
    occ_window = next((int(k[1:]) for k, v in lay.items() if "e0" in v), None)
    rep_rows = oracle_reps(mod, oracle, windows, occ_window, reps)
    (run_dir / "oracle_reps.json").write_text(json.dumps({"seed": seed, "reps": rep_rows}, indent=2) + "\n",
                                              encoding="utf-8")
    try:
        result = oc.compare(device, oracle, rep_rows)
    except oc.CompareError as e:
        runs.finish_run(run_dir, status="FAIL", notes=f"S7 not compared: {e}")
        print(f"NOT COMPARED: {e}\nrun dir: {run_dir}")
        return 1
    result.update({"stage": "S7", "seed": seed, "device_runs": {k: d.name for k, d in dirs.items()},
                   "device_stack": stack, "oracle_run": run_dir.name})
    (run_dir / "oracle_comparison.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with (run_dir / "oracle_comparison.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(oc.COLUMNS)
        w.writerows([r[c] for c in oc.COLUMNS] for r in result["rows"])
    stat = f"seed {seed}, one run of seed/vcloak_oracle.py" + (" --quick" if a.quick else "")
    summary = {"metrics": oc.metrics(result, stat) + [
        {"id": f"{oc.ORACLE_PREFIX}REPS", "value": reps, "unit": "repetitions",
         "stat": "oracle attack repeated with fresh keys on the same traffic"}]}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    c = result["counts"]
    runs.finish_run(run_dir, status="OK", notes=(
        f"S7 device against CPU oracle: {len(result['rows'])} rows, {c[oc.EQUAL]} EQUAL, {c[oc.WITHIN]} WITHIN_NOISE, "
        f"{c[oc.DIFFERS]} DIFFERS, {c[oc.NOT_COMPARABLE]} NOT_COMPARABLE. The oracle ran on this CPU (numpy); the "
        f"device values are read from the runs in params.device_runs. No GPU, no performance result."))
    for r in result["rows"]:
        print(f"{r['verdict']:<14} {r['experiment']:<3} {r['quantity']}: device {r['device']}, oracle {r['oracle']}")
    print(f"{len(result['rows'])} rows: " + ", ".join(f"{c[v]} {v}" for v in oc.VERDICTS))
    print(f"device stack: backend {stack['backend']}, engine {stack['engine']}, db {stack['db']}")
    print("run dir:", run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
