#!/usr/bin/env python3
"""M03 S6 - quick timing smoke of the bitonic sort, and the shared-memory race check (audit A2).

    python bench/bitonic_smoke.py --seed 3 [--quick] [--log2n 16] [--out runs]

On the runner it times `gpu_bitonic_sort` at n = 2^log2n with CUDA events (warm-up, then >= 30 runs;
15 with --quick), checks the result against np.lexsort, and runs one sort under
`compute-sanitizer --tool racecheck` when that tool exists. It only confirms that the kernels run at
a sane speed: the real measurements are M07.

Under the numpy backend (the laptop) the NumPy twin sorts once to exercise the plumbing, and every
metric is recorded as NOT_MEASURED.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import config, runs  # noqa: E402
from vcloak.gpu import telemetry  # noqa: E402
from vcloak.gpu.kernels import DEFAULT_T, clamp_tile, gpu_bitonic_sort, launch_plan  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402

CV_LIMIT = 0.10
RACECHECK_LOG2N = 12  # 2^12 with T = 256 uses all three kernels
RACECHECK_TIMEOUT_S = 900
NM = "NOT_MEASURED"


def make_cols(n: int, seed: int) -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(seed)
    return (rng.integers(0, 2**64, n, dtype=np.uint64), rng.integers(0, 2**64, n, dtype=np.uint64),
            np.arange(n, dtype=np.uint32), rng.integers(0, 2**32, n, dtype=np.uint32))


def mismatches(got: tuple[np.ndarray, ...], cols: tuple[np.ndarray, ...]) -> int:
    hi, lo, slot, _ = cols
    order = np.lexsort((slot, lo, hi))
    return sum(int(np.count_nonzero(g != c[order])) for g, c in zip(got, cols, strict=True))


def stats(times_ms: list[float]) -> dict[str, float]:
    a = np.asarray(times_ms, dtype=np.float64)
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if a.size > 1 else 0.0
    return {"runs": int(a.size), "median_ms": float(np.median(a)), "p5_ms": float(np.percentile(a, 5)),
            "p95_ms": float(np.percentile(a, 95)), "mean_ms": mean, "std_ms": std,
            "cv": std / mean if mean > 0 else 0.0}


def plan_summary(n: int) -> dict:
    """Public facts about the launch sequence at n (derived from n and T, not measured)."""
    plan = launch_plan(n)
    shared = sum(len(p.stages) for p in plan if p.kernel != "bitonic_pairs_global")
    total = sum(len(p.stages) for p in plan)
    return {"n": n, "T": clamp_tile(n), "launches": len(plan), "stages": total, "stages_in_shared_memory": shared,
            "stages_global": total - shared, "compare_exchanges": total * (n // 2)}


def time_sort(cp, cols: tuple[np.ndarray, ...], warmup: int, n_runs: int) -> tuple[list[float], int]:
    """Time the sort alone with CUDA events on one stream (ai/GPU_GUIDE.md §4). The copy that restores
    the unsorted input before each run is outside the timed region."""
    src = tuple(cp.asarray(c) for c in cols)
    work = tuple(cp.empty_like(c) for c in src)
    stream = cp.cuda.get_current_stream()
    start, end = cp.cuda.Event(), cp.cuda.Event()

    def reset() -> None:
        for w, s in zip(work, src, strict=True):
            cp.copyto(w, s)

    for _ in range(warmup):
        reset()
        gpu_bitonic_sort(*work)
    stream.synchronize()
    times: list[float] = []
    for _ in range(n_runs):
        reset()
        start.record(stream)
        gpu_bitonic_sort(*work)
        end.record(stream)
        end.synchronize()
        times.append(float(cp.cuda.get_elapsed_time(start, end)))
    return times, mismatches(tuple(cp.asnumpy(w) for w in work), cols)


def racecheck(run_dir: Path, seed: int) -> dict:
    """One sort under compute-sanitizer's racecheck (shared-memory hazards). NOT_MEASURED with the
    reason when the tool is missing, fails to start or times out; never a guessed result."""
    tool = shutil.which("compute-sanitizer") or next(
        (str(p) for p in (Path("/usr/local/cuda/bin/compute-sanitizer"),) if p.exists()), None)
    if tool is None:
        return {"status": NM, "reason": "compute-sanitizer is not installed on this runner"}
    cmd = [tool, "--tool", "racecheck", "--racecheck-report", "all", sys.executable, str(Path(__file__).resolve()),
           "--child-sort", "--seed", str(seed), "--log2n", str(RACECHECK_LOG2N)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=RACECHECK_TIMEOUT_S, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return {"status": NM, "reason": f"compute-sanitizer timed out after {RACECHECK_TIMEOUT_S} s", "command": cmd}
    except OSError as e:
        return {"status": NM, "reason": f"compute-sanitizer could not start: {type(e).__name__}", "command": cmd}
    out = p.stdout + p.stderr
    (run_dir / "racecheck.txt").write_text(out, encoding="utf-8")
    m = re.search(r"RACECHECK SUMMARY:\s*(\d+)\s+hazards? displayed\s*\((\d+)\s+errors?,\s*(\d+)\s+warnings?\)", out)
    if m is None or "CHILD_SORT_OK" not in out:
        return {"status": NM, "command": cmd, "exit_code": p.returncode,
                "reason": "no RACECHECK SUMMARY line, or the sort under the tool did not finish: see racecheck.txt"}
    hazards, errors, warnings = (int(x) for x in m.groups())
    return {"status": "OK" if hazards == 0 else "FAIL", "hazards": hazards, "errors": errors, "warnings": warnings,
            "n": 1 << RACECHECK_LOG2N, "command": cmd, "exit_code": p.returncode}


def child_sort(log2n: int, seed: int) -> int:
    """The process that runs under compute-sanitizer: one GPU sort, checked."""
    cp = get_backend("cupy").xp
    cols = make_cols(1 << log2n, seed)
    work = tuple(cp.asarray(c) for c in cols)
    gpu_bitonic_sort(*work)
    bad = mismatches(tuple(cp.asnumpy(w) for w in work), cols)
    print("CHILD_SORT_OK" if bad == 0 else f"CHILD_SORT_WRONG {bad}", flush=True)
    return 0 if bad == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--log2n", type=int, default=16)
    ap.add_argument("--out", default="runs", help="parent directory for the run dir")
    ap.add_argument("--child-sort", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.child_sort:
        return child_sort(a.log2n, a.seed)

    backend = get_backend()
    n = 1 << a.log2n
    n_runs = config.TIMING_RUNS_QUICK if a.quick else config.TIMING_RUNS_MIN
    command = "python bench/bitonic_smoke.py " + " ".join(shlex.quote(x) for x in (argv or sys.argv[1:]))
    run_dir = runs.new_run("M03", "bitonic_smoke", step="S6", owner="Aditya", command=command.strip(),
                           seed=a.seed, quick=a.quick, root=Path.cwd(), runs_dir=a.out, backend=backend,
                           params={"n": n, "T": DEFAULT_T, "warmup": config.TIMING_WARMUP, "runs": n_runs,
                                   "racecheck_n": 1 << RACECHECK_LOG2N})
    cols = make_cols(n, a.seed)
    attempts: list[dict] = []
    notes: list[str] = []
    if backend.is_gpu:
        with telemetry.Sampler(run_dir / "telemetry.csv") as sampler:
            for attempt in (1, 2):  # an unstable first attempt is repeated once and both are kept
                times, bad = time_sort(backend.xp, cols, config.TIMING_WARMUP, n_runs)
                attempts.append({"attempt": attempt, "mismatches": bad, "times_ms": times, **stats(times)})
                if bad or attempts[-1]["cv"] <= CV_LIMIT:
                    break
        with (run_dir / "raw.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["attempt", "run", "elapsed_ms"])
            for at in attempts:
                w.writerows((at["attempt"], i, t) for i, t in enumerate(at.pop("times_ms")))
        bad = attempts[-1]["mismatches"]
        race = racecheck(run_dir, a.seed)
        how, samples = "cupy.RawModule (nvrtc)", sampler.samples
    else:
        work = tuple(c.copy() for c in cols)
        gpu_bitonic_sort(*work)
        bad = mismatches(work, cols)
        race = {"status": NM, "reason": "numpy backend: no GPU on this machine"}
        how, samples = "numpy twins (vcloak.gpu.sim)", 0

    last = attempts[-1] if attempts else None
    reason = "numpy backend: no GPU on this machine"
    metrics = [
        {"id": f"K-BITONIC-SMOKE-MS-2^{a.log2n}", "value": round(last["median_ms"], 4) if last else NM, "unit": "ms",
         "stat": "median", "note": f"sort only, {last['runs']} runs, CUDA events; smoke, not an M07 result"
         if last else reason},
        {"id": f"K-BITONIC-SMOKE-CV-2^{a.log2n}", "value": round(last["cv"], 4) if last else NM, "unit": "-",
         "stat": "cv", "note": "std / mean of the timed runs" if last else reason},
        {"id": "K-BITONIC-RACECHECK-HAZARDS", "value": race.get("hazards", NM), "unit": "count", "stat": "value",
         "note": f"compute-sanitizer racecheck, n = 2^{RACECHECK_LOG2N}" if "hazards" in race else race["reason"]},
    ]
    (run_dir / "summary.json").write_text(json.dumps(
        {"metrics": metrics, "executed_by": how, "mismatches": bad, "attempts": attempts, "racecheck": race,
         "plan": plan_summary(n), "telemetry_samples": samples, "timer": "cupy.cuda.Event" if last else None,
         "device": backend.device_info()}, indent=2) + "\n", encoding="utf-8")

    if bad:
        status = "FAIL"
        notes.append(f"the sorted output differs from np.lexsort in {bad} elements")
    elif race["status"] == "FAIL":
        status = "FAIL"
        notes.append(f"racecheck reported {race['hazards']} hazard(s): see racecheck.txt")
    elif not backend.is_gpu:
        status = "NOT_MEASURED"
        notes.append("numpy backend: plumbing check only, no GPU metric measured")
    elif last["cv"] > CV_LIMIT:
        status = "UNSTABLE"
        notes.append(f"CV {last['cv']:.3f} > {CV_LIMIT} on both attempts; both are in raw.csv")
    else:
        status = "OK"
    if backend.is_gpu and race["status"] == NM:
        notes.append(f"racecheck NOT_MEASURED: {race['reason']}")
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))

    print(f"run dir     {run_dir}")
    print(f"backend     {backend.name}   executed by {how}")
    print(f"sort        n=2^{a.log2n} mismatches={bad}")
    for m in metrics:
        print(f"{m['id']:<28} {m['value']} {m['unit']}")
    print(f"racecheck   {race['status']}" + (f" ({race['reason']})" if "reason" in race else ""))
    print(f"status      {status}")
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
