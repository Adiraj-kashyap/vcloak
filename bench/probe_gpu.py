#!/usr/bin/env python3
"""M00 S6 - probe the remote GPU runner.

Records the device properties, compiles and runs a vector-add RawKernel and checks it against NumPy,
measures device-to-device copy bandwidth with CUDA events, and derives max_log2n from free VRAM.

    python bench/probe_gpu.py --seed 7 [--quick] [--out runs]

Under the numpy backend (the laptop) it only exercises the plumbing: the kernel's NumPy twin runs,
and every GPU metric is recorded as NOT_MEASURED.
"""
from __future__ import annotations

import argparse
import csv
import json
import shlex
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import config, runs  # noqa: E402
from vcloak.gpu import sim, telemetry  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402

KERNEL = ROOT / "kernels" / "vector_add.cu"
D2D_BYTES = 256 * 2**20
BLOCK = 256
CV_LIMIT = 0.10
NM = "NOT_MEASURED"


def stats(times_ms: list[float]) -> dict[str, float]:
    a = np.asarray(times_ms, dtype=np.float64)
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if a.size > 1 else 0.0
    return {"runs": int(a.size), "median_ms": float(np.median(a)), "p5_ms": float(np.percentile(a, 5)),
            "p95_ms": float(np.percentile(a, 95)), "mean_ms": mean, "std_ms": std,
            "cv": std / mean if mean > 0 else 0.0}


def vector_add(backend, n: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 2**32, size=n, dtype=np.uint32)
    b = rng.integers(0, 2**32, size=n, dtype=np.uint32)
    expected = a + b  # uint32 wraparound, same as the kernel
    if backend.is_gpu:
        cp = backend.xp
        mod = cp.RawModule(code=KERNEL.read_text(encoding="utf-8"), options=("-std=c++17",))
        fn = mod.get_function("vector_add")
        d_a, d_b, d_out = cp.asarray(a), cp.asarray(b), cp.zeros(n, dtype=cp.uint32)
        fn(((n + BLOCK - 1) // BLOCK,), (BLOCK,), (d_a, d_b, d_out, np.uint32(n)))
        got = cp.asnumpy(d_out)
        how = "cupy.RawModule (nvrtc)"
    else:
        got = np.zeros(n, dtype=np.uint32)
        sim.get("vector_add")(a, b, got, n)
        how = "numpy twin (vcloak.gpu.sim)"
    mismatches = int(np.count_nonzero(got != expected))
    return {"n": n, "executed_by": how, "mismatches": mismatches, "correct": mismatches == 0}


def d2d_copy(cp, run_dir: Path, warmup: int, n_runs: int) -> dict:
    """Device-to-device memcpy timed with CUDA events on one stream (ai/GPU_GUIDE.md §4)."""
    src = cp.full(D2D_BYTES, 0xA5, dtype=cp.uint8)
    dst = cp.zeros(D2D_BYTES, dtype=cp.uint8)
    stream = cp.cuda.get_current_stream()
    start, end = cp.cuda.Event(), cp.cuda.Event()

    def run() -> None:
        dst.data.copy_from_device_async(src.data, D2D_BYTES, stream)

    for _ in range(warmup):
        run()
    stream.synchronize()
    times: list[float] = []
    with telemetry.Sampler(run_dir / "telemetry.csv") as sampler:
        for _ in range(n_runs):
            start.record(stream)
            run()
            end.record(stream)
            end.synchronize()
            times.append(float(cp.cuda.get_elapsed_time(start, end)))
    copied_ok = bool(cp.all(dst[:: 4096] == 0xA5)) and int(dst[-1]) == 0xA5
    with (run_dir / "d2d_times.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run", "elapsed_ms"])
        w.writerows(enumerate(times))
    s = stats(times)
    copy_gbs = D2D_BYTES / 1e9 / (s["median_ms"] / 1e3)
    s.update({"bytes": D2D_BYTES, "warmup": warmup, "copied_ok": copied_ok,
              "copy_rate_gbs": copy_gbs,
              # a copy reads N bytes and writes N bytes: memory traffic is 2N (ai/GPU_GUIDE.md §5)
              "effective_bw_gbs": 2 * copy_gbs,
              "telemetry_samples": sampler.samples, "timer": "cupy.cuda.Event"})
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="runs", help="parent directory for the run dir")
    a = ap.parse_args(argv)

    backend = get_backend()
    info = backend.device_info()  # read free VRAM before this script allocates anything
    command = "python bench/probe_gpu.py " + " ".join(shlex.quote(x) for x in (argv or sys.argv[1:]))
    n_runs = config.TIMING_RUNS_QUICK if a.quick else config.TIMING_RUNS_MIN
    n_add = 1 << (16 if a.quick else 20)
    run_dir = runs.new_run("M00", "gpu_probe", step="S6", owner="Aditya", command=command.strip(),
                           seed=a.seed, quick=a.quick, root=Path.cwd(), runs_dir=a.out, backend=backend,
                           params={"vector_add_n": n_add, "d2d_bytes": D2D_BYTES,
                                   "warmup": config.TIMING_WARMUP, "runs": n_runs})
    try:
        smi = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=60)
        (run_dir / "nvidia_smi.txt").write_text(smi.stdout + smi.stderr, encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - absent on the laptop
        (run_dir / "nvidia_smi.txt").write_text(f"nvidia-smi unavailable: {type(e).__name__}\n", encoding="utf-8")

    va = vector_add(backend, n_add, a.seed)
    d2d = d2d_copy(backend.xp, run_dir, config.TIMING_WARMUP, n_runs) if backend.is_gpu else None

    peak = info.get("peak_bw_gbs")
    free = info.get("vram_free_bytes")
    reason = "numpy backend: no GPU on this machine" if not backend.is_gpu else "device attribute not reported"
    metrics = [
        {"id": "ENV-PEAK-BW", "value": round(peak, 3) if peak else NM, "unit": "GB/s", "stat": "theoretical",
         "note": "2 x mem_clock x bus_width / 8" if peak else reason},
        {"id": "ENV-D2D-BW", "value": round(d2d["effective_bw_gbs"], 3) if d2d else NM, "unit": "GB/s",
         "stat": "median", "note": "read+write traffic of a 256 MiB D2D copy" if d2d else reason},
        {"id": "ENV-MAX-LOG2N", "value": info["max_log2n"] if backend.is_gpu else NM, "unit": "log2(n)",
         "stat": "value", "note": "floor(log2(0.5 x free VRAM / 48 B)), capped at 24" if backend.is_gpu else reason},
        {"id": "ENV-VRAM-FREE", "value": round(free / 1e9, 3) if free else NM, "unit": "GB", "stat": "value",
         "note": "free VRAM at probe start" if free else reason},
    ]
    (run_dir / "device.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(
        {"metrics": metrics, "vector_add": va, "d2d_copy": d2d, "device": info}, indent=2) + "\n",
        encoding="utf-8")

    notes = []
    if not va["correct"]:
        status = "FAIL"
        notes.append(f"vector-add produced {va['mismatches']} wrong elements")
    elif not backend.is_gpu:
        status = "NOT_MEASURED"
        notes.append("numpy backend: plumbing check only, no GPU metric measured")
    elif d2d["cv"] > CV_LIMIT or not d2d["copied_ok"]:
        status = "UNSTABLE"
        notes.append(f"D2D copy CV {d2d['cv']:.3f} > {CV_LIMIT} or copy check failed; re-run before use")
    else:
        status = "OK"
    if backend.is_gpu and peak and d2d and d2d["effective_bw_gbs"] > peak:
        status = "UNSTABLE"
        notes.append("measured D2D bandwidth exceeds the theoretical peak: check the device attributes")
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))

    print(f"run dir     {run_dir}")
    print(f"backend     {backend.name}   device {info.get('device')}")
    print(f"vector-add  n={va['n']} mismatches={va['mismatches']} ({va['executed_by']})")
    for m in metrics:
        print(f"{m['id']:<14} {m['value']} {m['unit']}")
    print(f"status      {status}")
    return 0 if va["correct"] else 1


if __name__ == "__main__":
    sys.exit(main())
