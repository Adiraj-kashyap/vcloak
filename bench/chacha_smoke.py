#!/usr/bin/env python3
"""M04 S4 - quick throughput smoke of ChaCha20 tag generation.

    python bench/chacha_smoke.py --seed 4 [--quick] [--log2n 20] [--out runs]

On the runner it times `gpu_tags` (the `chacha_tags` kernel alone, into columns that already exist) at
n = 2^log2n slots with CUDA events (warm-up, then >= 30 runs; 15 with --quick), checks the tags against
the M02 reference, and reports GB/s of generated tag bytes (16 n). It only confirms that the kernel
runs at a sane speed: the real measurements are M07.

The key is a fixed TEST key derived from the seed; it is uploaded once, like every test key.

Under the numpy backend (the laptop) the NumPy twin generates the tags once to exercise the plumbing,
and every metric is recorded as NOT_MEASURED.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shlex
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import config, runs  # noqa: E402
from vcloak.crypto import chacha_ref  # noqa: E402
from vcloak.gpu import telemetry  # noqa: E402
from vcloak.gpu.kernels import CHACHA_BLOCK, DOMAIN_EPOCH, TAGS_PER_BLOCK, gpu_tags  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402

CV_LIMIT = 0.10
CLOCK_LIMIT = 0.15  # SM clock change between the post-warm-up and the final snapshot (ai/GPU_RUNNER.md §7)
TAG_BYTES = 16
EPOCH = 1
NM = "NOT_MEASURED"


def test_key(seed: int) -> bytes:
    """A fixed TEST key (CONVENTIONS §3): never a production key."""
    return hashlib.sha256(b"vcloak-bench-test-key-%d" % seed).digest()


def mismatches(got: tuple[np.ndarray, np.ndarray], key: bytes, n: int) -> int:
    want = chacha_ref.tags_for_epoch(key, EPOCH, n)
    return sum(int(np.count_nonzero(g != w)) for g, w in zip(got, want, strict=True))


def stats(times_ms: list[float], nbytes: int) -> dict[str, float]:
    a = np.asarray(times_ms, dtype=np.float64)
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if a.size > 1 else 0.0
    median = float(np.median(a))
    return {"runs": int(a.size), "median_ms": median, "p5_ms": float(np.percentile(a, 5)),
            "p95_ms": float(np.percentile(a, 95)), "mean_ms": mean, "std_ms": std,
            "cv": std / mean if mean > 0 else 0.0, "gbs": nbytes / 1e9 / (median / 1e3) if median > 0 else 0.0}


def clock_change(before: dict, after: dict) -> dict:
    """Relative SM clock change between two snapshots, or NOT_MEASURED when NVML gave no clock."""
    a, b = before.get("sm_clock_mhz"), after.get("sm_clock_mhz")
    if not a or not b:
        return {"status": NM, "reason": "NVML reported no SM clock", "before_mhz": a, "after_mhz": b}
    rel = (float(b) - float(a)) / float(a)
    return {"status": "OK" if abs(rel) <= CLOCK_LIMIT else "UNSTABLE", "before_mhz": a, "after_mhz": b,
            "relative_change": rel}


def time_tags(cp, d_key, n: int, warmup: int, n_runs: int) -> tuple[list[float], tuple, dict, dict]:
    """Time the tag kernel alone with CUDA events on one stream (ai/GPU_GUIDE.md §4). The telemetry
    snapshots are taken after the warm-up and after the last timed run, so both see a busy device."""
    d_hi, d_lo = cp.empty(n, dtype=np.uint64), cp.empty(n, dtype=np.uint64)
    stream = cp.cuda.get_current_stream()
    start, end = cp.cuda.Event(), cp.cuda.Event()
    for _ in range(warmup):
        gpu_tags(d_key, EPOCH, DOMAIN_EPOCH, d_hi, d_lo)
    stream.synchronize()
    snap_warm = telemetry.snapshot()
    times: list[float] = []
    for _ in range(n_runs):
        start.record(stream)
        gpu_tags(d_key, EPOCH, DOMAIN_EPOCH, d_hi, d_lo)
        end.record(stream)
        end.synchronize()
        times.append(float(cp.cuda.get_elapsed_time(start, end)))
    snap_end = telemetry.snapshot()
    return times, (cp.asnumpy(d_hi), cp.asnumpy(d_lo)), snap_warm, snap_end


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--log2n", type=int, default=20)
    ap.add_argument("--out", default="runs", help="parent directory for the run dir")
    a = ap.parse_args(argv)

    backend = get_backend()
    n = 1 << a.log2n
    nbytes = TAG_BYTES * n
    n_runs = config.TIMING_RUNS_QUICK if a.quick else config.TIMING_RUNS_MIN
    command = "python bench/chacha_smoke.py " + " ".join(shlex.quote(x) for x in (argv or sys.argv[1:]))
    run_dir = runs.new_run("M04", "chacha_smoke", step="S4", owner="Aditya", command=command.strip(),
                           seed=a.seed, quick=a.quick, root=Path.cwd(), runs_dir=a.out, backend=backend,
                           params={"n": n, "blocks": n // TAGS_PER_BLOCK, "threads_per_block": CHACHA_BLOCK,
                                   "tag_bytes": nbytes, "warmup": config.TIMING_WARMUP, "runs": n_runs})
    key = test_key(a.seed)
    key_words = np.frombuffer(key, dtype="<u4").astype(np.uint32)
    attempts: list[dict] = []
    notes: list[str] = []
    clock: dict = {"status": NM, "reason": "numpy backend: no GPU on this machine"}
    if backend.is_gpu:
        cp = backend.xp
        d_key = cp.asarray(key_words)
        with telemetry.Sampler(run_dir / "telemetry.csv") as sampler:
            for attempt in (1, 2):  # an unstable first attempt is repeated once and both are kept
                times, got, snap_warm, snap_end = time_tags(cp, d_key, n, config.TIMING_WARMUP, n_runs)
                clock = clock_change(snap_warm, snap_end)
                attempts.append({"attempt": attempt, "mismatches": mismatches(got, key, n), "times_ms": times,
                                 "clock": clock, "telemetry_after_warmup": snap_warm, "telemetry_after_runs": snap_end,
                                 **stats(times, nbytes)})
                if attempts[-1]["mismatches"] or (attempts[-1]["cv"] <= CV_LIMIT and clock["status"] != "UNSTABLE"):
                    break
        with (run_dir / "raw.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["attempt", "run", "elapsed_ms"])
            for at in attempts:
                w.writerows((at["attempt"], i, t) for i, t in enumerate(at.pop("times_ms")))
        bad = attempts[-1]["mismatches"]
        how, samples = "cupy.RawModule (nvrtc)", sampler.samples
    else:
        got = np.empty(n, dtype=np.uint64), np.empty(n, dtype=np.uint64)
        gpu_tags(key_words, EPOCH, DOMAIN_EPOCH, *got)
        bad = mismatches(got, key, n)
        how, samples = "numpy twins (vcloak.gpu.sim)", 0

    last = attempts[-1] if attempts else None
    reason = "numpy backend: no GPU on this machine"
    size = f"2^{a.log2n}"
    metrics = [
        {"id": f"K-CHACHA-TAGS-SMOKE-GBS-{size}", "value": round(last["gbs"], 4) if last else NM, "unit": "GB/s",
         "stat": "median", "note": f"{nbytes} tag bytes / median kernel time; smoke, not an M07 result"
         if last else reason},
        {"id": f"K-CHACHA-TAGS-SMOKE-MS-{size}", "value": round(last["median_ms"], 4) if last else NM, "unit": "ms",
         "stat": "median", "note": f"chacha_tags kernel only, {last['runs']} runs, CUDA events" if last else reason},
        {"id": f"K-CHACHA-TAGS-SMOKE-CV-{size}", "value": round(last["cv"], 4) if last else NM, "unit": "-",
         "stat": "cv", "note": "std / mean of the timed runs" if last else reason},
    ]
    (run_dir / "summary.json").write_text(json.dumps(
        {"metrics": metrics, "executed_by": how, "mismatches": bad, "attempts": attempts, "clock": clock,
         "telemetry_samples": samples, "timer": "cupy.cuda.Event" if last else None,
         "device": backend.device_info()}, indent=2) + "\n", encoding="utf-8")

    if bad:
        status = "FAIL"
        notes.append(f"the tags differ from chacha_ref.tags_for_epoch in {bad} elements")
    elif not backend.is_gpu:
        status = "NOT_MEASURED"
        notes.append("numpy backend: plumbing check only, no GPU metric measured")
    elif last["cv"] > CV_LIMIT:
        status = "UNSTABLE"
        notes.append(f"CV {last['cv']:.3f} > {CV_LIMIT} on both attempts; both are in raw.csv")
    elif clock["status"] == "UNSTABLE":
        status = "UNSTABLE"
        notes.append(f"SM clock changed by {clock['relative_change']:+.1%} during the timed runs")
    else:
        status = "OK"
    if backend.is_gpu and clock["status"] == NM:
        notes.append(f"clock stability NOT_MEASURED: {clock['reason']}")
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))

    print(f"run dir     {run_dir}")
    print(f"backend     {backend.name}   executed by {how}")
    print(f"tags        n={size} mismatches={bad}")
    for m in metrics:
        print(f"{m['id']:<32} {m['value']} {m['unit']}")
    print(f"clock       {clock['status']}" + (f" ({clock['reason']})" if "reason" in clock else ""))
    print(f"status      {status}")
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
