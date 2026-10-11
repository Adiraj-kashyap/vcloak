#!/usr/bin/env python3
"""M07 S2-S4 - kernel sweeps, CPU baselines and the GPU/CPU crossover.

    python bench/run_kernels.py --part gpu       --seed 7 [--quick] [--sweep 10:22] [--runs 50] [--out runs]
    python bench/run_kernels.py --part cpu       --seed 7 [--quick] [--sweep 10:22] [--out runs]
    python bench/run_kernels.py --part crossover --seed 7 [--quick] [--out runs]

The three parts are three run dirs. They must run in ONE runner session (one GPU job): the crossover
compares a GPU with the CPU beside it, and refuses inputs whose `session_id` differs from its own.

gpu        For n = 2^lo ... 2^hi, timed with CUDA events on one stream after a warm-up that lasts until
           the SM clock stops rising (ISSUE-7): the bitonic network as global launches only, the fused
           (shared-memory) sort, the sort including its transfers through pinned memory (`sort_e2e`),
           ChaCha20 tags, the seq_enc AEAD open, and the bucket PRF. Every output is checked.
           A configuration whose CV exceeds 10% or whose SM clock moved by more than 15% is repeated
           once; if it fails again both attempts are kept and its metrics are recorded as UNSTABLE,
           not as numbers. A configuration whose clock is steady but below 85% of the device maximum
           is repeated once after a load that raises the clock; if the clock is still low (a short
           kernel does not keep a GPU busy) the number is kept and labelled LOW clock.
cpu        The same records sorted on the host with perf_counter_ns: the M01 oracle network, the same
           network on NumPy views, a numba parallel loop when numba is installed, and np.lexsort
           (not oblivious: a lower bound, never part of the crossover).
crossover  n* and the speed-ups at 2^16 and 2^20: `sort_e2e` (kernels + H2D + D2H) against the best
           oblivious CPU baseline at each n.

Keys are fixed TEST keys derived from the seed (never production keys).

Under the numpy backend (the laptop) each part runs once at small n to check the plumbing and the
outputs, and every metric is NOT_MEASURED: a laptop number is never a result (ai/GPU_RUNNER.md §3).
"""
from __future__ import annotations

import argparse
import csv
import json
import shlex
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chacha_smoke import test_key  # noqa: E402
from vcloak import config, runs  # noqa: E402
from vcloak.bench import baselines, derive, timing  # noqa: E402
from vcloak.bench.timing import CV_LIMIT, NM, UNSTABLE  # noqa: E402
from vcloak.crypto import chacha_ref  # noqa: E402
from vcloak.gpu import telemetry  # noqa: E402
from vcloak.gpu.kernels import (  # noqa: E402
    DEFAULT_T,
    DOMAIN_EPOCH,
    SUBKEY_BKT,
    SUBKEY_SEQ,
    SUBKEY_TAG,
    global_only_plan,
    gpu_bitonic_sort,
    gpu_bucket_prf,
    gpu_derive_subkeys,
    gpu_open_and_key,
    gpu_seal_seq,
    gpu_tags,
    run_launch,
    subkey,
)
from vcloak.gpu.runtime import Backend, get_backend, host_info  # noqa: E402

GPU_KERNELS = ("bitonic_global", "bitonic_fused", "sort_e2e", "chacha_tags", "aead_open", "bucket_prf")
CPU_METRIC = {"oracle_bitonic": "CPU-BITONIC-MS", "views_bitonic": "CPU-BITONIC-VIEWS-MS",
              "numba_bitonic": "CPU-BITONIC-NUMBA-MS", "lexsort": "CPU-LEXSORT-MS"}
SWEEP_LO = 10
QUICK_HI = 18
QUICK_WARMUP = 5
LOCAL_SIZES = (10, 12)  # numpy backend: plumbing only
EPOCH = 1
HIT_FRACTION = 8  # one row in 8 belongs to the conversation that the open kernel is asked for
REF_CHECK_MAX_LOG2N = 20  # the host references of tags and buckets are checked up to here
WARM_MIN_S, WARM_MAX_S = 0.5, 4.0
RAMP_LOG2N, RAMP_MAX_S = 20, 8.0
CPU_RUNS, CPU_RUNS_LARGE, CPU_RUNS_QUICK, CPU_LARGE_LOG2N = 10, 5, 5, 20
CPU_BUDGET_S = 1200.0  # per (baseline, n): the number of runs is cut, and the cut noted, beyond this
CPU_REPEAT_MAX_S = 120.0  # an unstable CPU configuration is repeated only if one attempt is shorter
SPEEDUP_LOG2N = (16, 20)
SHARED_GPU_CAVEAT = ("Free Colab/Kaggle GPUs and their host CPUs are shared and may be throttled; the GPU and "
                     "CPU numbers were taken in one runner session and are valid for this GPU/CPU pair only.")


def make_cols(n: int, seed: int) -> baselines.Cols:
    rng = np.random.default_rng([seed, n])
    return (rng.integers(0, 2**64, n, dtype=np.uint64), rng.integers(0, 2**64, n, dtype=np.uint64),
            np.arange(n, dtype=np.uint32), rng.integers(0, 2**32, n, dtype=np.uint32))


def metric(mid: str, value: Any, unit: str, stat: str, note: str) -> dict[str, Any]:
    return {"id": mid, "value": value, "unit": unit, "stat": stat, "note": note}


def write_summary(run_dir: Path, body: dict[str, Any]) -> None:
    (run_dir / "summary.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


# ── part: gpu ────────────────────────────────────────────────────────────────


class Workloads:
    """The six timed workloads at one n, on the device (cupy) or on the simulator twins (numpy)."""

    def __init__(self, backend: Backend, n: int, seed: int, master: bytes) -> None:
        self.xp, self.is_gpu, self.n = backend.xp, backend.is_gpu, n
        xp = self.xp
        self.stream = xp.cuda.get_current_stream() if self.is_gpu else None
        self.cols = make_cols(n, seed)
        self.src = tuple(xp.asarray(c) for c in self.cols)
        self.work = tuple(xp.empty_like(c) for c in self.src)
        self.gplan = global_only_plan(n)

        self._pins: list[Any] = []  # keeps the page-locked allocations alive
        self.e2e_dev = tuple(xp.empty_like(c) for c in self.src)
        self.pin_in = tuple(self._pinned(c) for c in self.cols)
        self.pin_out = tuple(self._pinned(c, fill=False) for c in self.cols)

        self.k_tag, self.k_seq, self.k_bkt = chacha_ref.derive_subkeys(master)  # host copies, for the checks
        keys_dev = gpu_derive_subkeys(xp.asarray(np.frombuffer(master, dtype="<u4").astype(np.uint32)))
        self.d_ktag, self.d_kseq, self.d_kbkt = (subkey(keys_dev, i) for i in (SUBKEY_TAG, SUBKEY_SEQ, SUBKEY_BKT))
        self.d_hi, self.d_lo = xp.empty(n, dtype=np.uint64), xp.empty(n, dtype=np.uint64)

        rng = np.random.default_rng([seed, n, 1])
        self.conv = rng.integers(0, 2**64, n, dtype=np.uint64)
        self.conv[: max(1, n // HIT_FRACTION)] = self.conv[0]
        self.q = int(self.conv[0])
        self.seq = rng.integers(0, 2**64, n, dtype=np.uint64)
        self.d_conv = xp.asarray(self.conv)
        nonces = xp.asarray(rng.integers(0, 2**32, 3 * n, dtype=np.uint32))
        self.blobs = gpu_seal_seq(self.d_kseq, self.d_conv, xp.asarray(self.seq), nonces)
        self.out: dict[str, Any] = {}

    def _pinned(self, col: np.ndarray, fill: bool = True) -> np.ndarray:
        if not self.is_gpu:
            return col.copy()
        mem = self.xp.cuda.alloc_pinned_memory(col.nbytes)
        self._pins.append(mem)
        host = np.frombuffer(mem, dtype=col.dtype, count=col.size)
        if fill:
            host[:] = col
        return host

    def host(self, a: Any) -> np.ndarray:
        return self.xp.asnumpy(a) if self.is_gpu else a

    # setup (not timed)
    def reset(self) -> None:
        for w, s in zip(self.work, self.src, strict=True):
            self.xp.copyto(w, s)

    # timed bodies
    def bitonic_global(self) -> None:
        for launch in self.gplan:
            run_launch(self.work, launch)

    def bitonic_fused(self) -> None:
        gpu_bitonic_sort(*self.work)

    def sort_e2e(self) -> None:
        if not self.is_gpu:
            for d, h in zip(self.e2e_dev, self.pin_in, strict=True):
                d[:] = h
            gpu_bitonic_sort(*self.e2e_dev)
            for d, h in zip(self.e2e_dev, self.pin_out, strict=True):
                h[:] = d
            return
        for d, h in zip(self.e2e_dev, self.pin_in, strict=True):
            d.set(h, stream=self.stream)
        gpu_bitonic_sort(*self.e2e_dev)
        for d, h in zip(self.e2e_dev, self.pin_out, strict=True):
            d.get(stream=self.stream, out=h)

    def chacha_tags(self) -> None:
        gpu_tags(self.d_ktag, EPOCH, DOMAIN_EPOCH, self.d_hi, self.d_lo)

    def aead_open(self) -> None:
        self.out["open"] = gpu_open_and_key(self.d_kseq, self.blobs, self.q)

    def bucket_prf(self) -> None:
        self.out["bucket"] = gpu_bucket_prf(self.d_kbkt, self.d_conv, config.BUCKETS)

    def setup_of(self, kernel: str) -> Callable[[], None] | None:
        return self.reset if kernel in ("bitonic_global", "bitonic_fused") else None

    # checks of the last output; (mismatching elements, what was compared)
    def check(self, kernel: str) -> tuple[int, str]:
        n, small = self.n, self.n <= 1 << REF_CHECK_MAX_LOG2N
        if kernel in ("bitonic_global", "bitonic_fused"):
            return baselines.mismatches(tuple(self.host(w) for w in self.work), self.cols), "np.lexsort"
        if kernel == "sort_e2e":
            return baselines.mismatches(self.pin_out, self.cols), "np.lexsort"
        if kernel == "chacha_tags":
            if not small:
                return 0, f"not compared above 2^{REF_CHECK_MAX_LOG2N}"
            want = chacha_ref.tags_for_epoch(self.k_tag, EPOCH, n)
            got = (self.host(self.d_hi), self.host(self.d_lo))
            return sum(int(np.count_nonzero(g != w)) for g, w in zip(got, want, strict=True)), "chacha_ref"
        if kernel == "aead_open":
            hi, lo, ok = (self.host(x) for x in self.out["open"])
            hit = self.conv == np.uint64(self.q)
            bad = int(np.count_nonzero(ok != 1)) + int(np.count_nonzero((hi == 0) != hit))
            return bad + int(np.count_nonzero(lo[hit] != self.seq[hit])), "sealed inputs"
        if not small:
            return 0, f"not compared above 2^{REF_CHECK_MAX_LOG2N}"
        want_b = chacha_ref.bucket_prf(self.k_bkt, self.conv, config.BUCKETS)
        return int(np.count_nonzero(self.host(self.out["bucket"]) != want_b)), "chacha_ref"


def make_ramp(backend: Backend, seed: int) -> Callable[[], dict[str, Any]]:
    """A load that brings the SM clock up: fused sorts at 2^RAMP_LOG2N until the clock stops rising."""
    cp = backend.xp
    stream = cp.cuda.get_current_stream()
    src = tuple(cp.asarray(c) for c in make_cols(1 << RAMP_LOG2N, seed))
    work = tuple(cp.empty_like(c) for c in src)

    def load() -> None:
        for w, s in zip(work, src, strict=True):
            cp.copyto(w, s)
        gpu_bitonic_sort(*work)

    def ramp() -> dict[str, Any]:
        r = timing.warm_until_stable(load, min_calls=3, snapshot=telemetry.sample, sync=stream.synchronize,
                                     min_seconds=1.0, max_seconds=RAMP_MAX_S)
        return {"calls": r["calls"], "seconds": round(r["seconds"], 3), "clocks_mhz": r["clocks_mhz"]}

    return ramp


def measure_gpu(w: Workloads, kernel: str, warmup: int, n_runs: int, ramp: Callable[[], dict]) -> list[dict]:
    """Up to two attempts at one (kernel, n); an unstable or low-clock first attempt is repeated once
    (after the ramp load when the clock was the reason) and both are kept. The last attempt is reported."""
    cp, stream = w.xp, w.stream
    fn, setup = getattr(w, kernel), w.setup_of(kernel)

    def once() -> None:
        if setup is not None:
            setup()
        fn()

    attempts: list[dict[str, Any]] = []
    for attempt in (1, 2):
        warm = timing.warm_until_stable(once, min_calls=warmup, snapshot=telemetry.sample, sync=stream.synchronize,
                                        min_seconds=WARM_MIN_S, max_seconds=WARM_MAX_S)
        t_start = time.time()
        times = timing.time_gpu(fn, 0, n_runs, stream, setup=setup, cp=cp)
        snap_end = telemetry.sample()
        clock = timing.clock_check(warm["snapshot"], snap_end)
        s = timing.summarise(times)
        entry = {"attempt": attempt, "times_ms": times, "t_start": t_start, "t_end": time.time(), "clock": clock,
                 "warm": {"calls": warm["calls"], "seconds": round(warm["seconds"], 3),
                          "clocks_mhz": warm["clocks_mhz"]},
                 "telemetry_after_warmup": warm["snapshot"], "telemetry_after_runs": snap_end,
                 "stable": timing.stable(s["cv"], clock, low_clock_is_unstable=False),
                 "low_clock": clock["status"] == "LOW", **s}
        attempts.append(entry)
        if entry["stable"] and not entry["low_clock"]:
            break
        if attempt == 1 and clock["status"] in ("LOW", UNSTABLE):
            entry["ramp_before_repeat"] = ramp()
    return attempts


def gpu_point(kernel: str, n: int, attempts: list[dict], bad: int, compared: str, peak: float | None) -> dict:
    """One sweep point: the last attempt's statistics plus the derived metrics of ai/GPU_GUIDE.md §5."""
    last = attempts[-1]
    med = last["median_ms"]
    p: dict[str, Any] = {"n": n, "log2n": n.bit_length() - 1, "median_ms": med, "cv": last["cv"],
                         "unstable": not last["stable"], "low_clock": last["low_clock"],
                         "clock": last["clock"]["status"],
                         "sm_clock_mhz": last["clock"].get("after_mhz"), "mismatches": bad, "compared_with": compared,
                         "attempts": attempts}
    if kernel in ("bitonic_global", "bitonic_fused", "sort_e2e"):
        p["keys_per_s"] = derive.per_second(n, med)
    if kernel in ("bitonic_global", "bitonic_fused"):
        p["rounds"] = derive.rounds(n)
        p["bytes_moved_model"] = derive.bitonic_bytes(n)
        p["effective_gbs"] = derive.gbs(derive.bitonic_bytes(n), med)
        p["bw_pct_of_peak"] = derive.bandwidth_pct(n, med, peak)
    elif kernel == "chacha_tags":
        p["gbs"] = derive.gbs(16 * n, med)
    elif kernel in ("aead_open", "bucket_prf"):
        p["rows_per_s"] = derive.per_second(n, med)
    return p


def telemetry_medians(path: Path) -> dict[str, Any]:
    """Medians over the sampler's rows. None when the file or the column is empty."""
    out: dict[str, Any] = {"samples": 0, "sm_clock_mhz": None, "power_w": None, "temperature_c": None,
                           "util_gpu_pct": None}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out["samples"] = len(rows)
    for col in ("sm_clock_mhz", "power_w", "temperature_c", "util_gpu_pct"):
        vals = [float(r[col]) for r in rows if r.get(col) not in (None, "")]
        out[col] = statistics.median(vals) if vals else None
    return out


def gpu_metrics(sweeps: dict[str, list[dict]], tel: dict[str, Any], reason: str | None) -> list[dict]:
    """The indexed metrics. `reason` is set when nothing was measured (numpy backend)."""
    out: list[dict[str, Any]] = []

    def add(mid: str, p: dict, key: str, unit: str, what: str, digits: int = 5) -> None:
        if reason:
            out.append(metric(mid, NM, unit, "median", reason))
            return
        note = (f"{what}; {p['attempts'][-1]['runs']} runs, CUDA events, CV {p['cv']:.3f}, "
                f"SM clock {p['sm_clock_mhz']} MHz ({p['clock']})")
        if p["low_clock"]:
            note += (f"; LOW clock: below {timing.LOW_CLOCK_FRACTION:.0%} of the device maximum after the ramp "
                     "and a repeat")
        if p["unstable"]:
            note += f"; UNSTABLE after {len(p['attempts'])} attempts, both in raw.csv and summary.json"
        out.append(metric(mid, derive.value_or_flag(p.get(key), p["unstable"], digits), unit, "median", note))

    for p in sweeps["bitonic_global"]:
        size = f"2^{p['log2n']}"
        add(f"K-BITONIC-GLOBAL-MS-{size}", p, "median_ms", "ms", "bitonic network, global launches only")
        add(f"K-BITONIC-BW-PCT-{size}", p, "bw_pct_of_peak", "%",
            "global-only variant: rounds x n x 24 B x 2 / median, over the theoretical peak", 3)
    for p in sweeps["bitonic_fused"]:
        add(f"K-BITONIC-FUSED-MS-2^{p['log2n']}", p, "median_ms", "ms", f"fused shared-memory sort, T={DEFAULT_T}")
    for p in sweeps["sort_e2e"]:
        add(f"K-BITONIC-E2E-MS-2^{p['log2n']}", p, "median_ms", "ms",
            "pinned H2D of 4 columns + fused sort + pinned D2H of 4 columns")
    for kernel, name in (("chacha_tags", "CHACHA"), ("aead_open", "AEADOPEN"), ("bucket_prf", "BUCKETPRF")):
        for p in sweeps[kernel]:
            add(f"K-{name}-MS-2^{p['log2n']}", p, "median_ms", "ms", f"{kernel} kernel only")
    for kernel, mid, key, unit in (("chacha_tags", "K-CHACHA-GBS", "gbs", "GB/s"),
                                   ("aead_open", "K-AEADOPEN-ROWS-S", "rows_per_s", "rows/s"),
                                   ("bucket_prf", "K-BUCKETPRF-ROWS-S", "rows_per_s", "rows/s")):
        p = sweeps[kernel][-1]  # the headline value is the largest swept n
        add(mid, p, key, unit, f"{kernel} at n = 2^{p['log2n']} (largest swept n)", 4 if unit == "GB/s" else 1)
    tel_note = reason or f"median of {tel['samples']} NVML samples at 10 Hz over the whole sweep"
    for mid, key, unit in (("TEL-SMCLK-MEDIAN", "sm_clock_mhz", "MHz"), ("TEL-POWER-W-MEDIAN", "power_w", "W")):
        v = None if reason else tel.get(key)
        out.append(metric(mid, NM if v is None else round(float(v), 2), unit, "median",
                          tel_note if v is not None or reason else "NVML returned no samples for this field"))
    return out


def part_gpu(a: argparse.Namespace, backend: Backend, command: str) -> int:
    sizes = sweep_sizes(a, backend)
    warmup = QUICK_WARMUP if a.quick else config.TIMING_WARMUP
    n_runs = a.runs or (config.TIMING_RUNS_QUICK if a.quick else config.TIMING_RUNS)
    run_dir = runs.new_run("M07", "kernel_sweep", step="S2", owner="Aditya", command=command, seed=a.seed,
                           quick=a.quick, root=Path.cwd(), runs_dir=a.out, backend=backend,
                           params={"n_log2": [sizes[0], sizes[-1]], "runs": n_runs, "warmup": warmup,
                                   "kernels": list(GPU_KERNELS), "T": DEFAULT_T,
                                   "warm_seconds": [WARM_MIN_S, WARM_MAX_S],
                                   "cv_limit": CV_LIMIT, "clock_limit": timing.CLOCK_LIMIT,
                                   "low_clock_fraction": timing.LOW_CLOCK_FRACTION, "buckets": config.BUCKETS})
    master = test_key(a.seed)
    info = backend.device_info()
    peak = info.get("peak_bw_gbs") if backend.is_gpu else None
    sweeps: dict[str, list[dict]] = {k: [] for k in GPU_KERNELS}
    ramp_log: list[dict] = []
    with telemetry.Sampler(run_dir / "telemetry.csv") as sampler:
        ramp = make_ramp(backend, a.seed) if backend.is_gpu else None
        if ramp:
            ramp_log.append(ramp())
        for lg in sizes:
            n = 1 << lg
            w = Workloads(backend, n, a.seed, master)
            for kernel in GPU_KERNELS:
                if backend.is_gpu:
                    attempts = measure_gpu(w, kernel, warmup, n_runs, ramp)
                else:
                    setup = w.setup_of(kernel)
                    if setup is not None:
                        setup()
                    getattr(w, kernel)()
                    attempts = []
                bad, compared = w.check(kernel)
                if attempts:
                    sweeps[kernel].append(gpu_point(kernel, n, attempts, bad, compared, peak))
                else:
                    sweeps[kernel].append({"n": n, "log2n": lg, "mismatches": bad, "compared_with": compared})
            if backend.is_gpu:
                # A5: the fused and the global-only variants must leave the same bytes
                w.reset()
                w.bitonic_global()
                ref_cols = tuple(c.copy() for c in w.work)
                w.reset()
                w.bitonic_fused()
                same = all(bool(backend.xp.array_equal(x, y)) for x, y in zip(ref_cols, w.work, strict=True))
                sweeps["bitonic_fused"][-1]["identical_to_global"] = same
                del w, ref_cols
                backend.xp.get_default_memory_pool().free_all_blocks()
        samples = sampler.samples

    if backend.is_gpu:
        with (run_dir / "raw.csv").open("w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow(["kernel", "log2n", "attempt", "run", "elapsed_ms"])
            for kernel, points in sweeps.items():
                for p in points:
                    for at in p["attempts"]:
                        wr.writerows((kernel, p["log2n"], at["attempt"], i, t)
                                     for i, t in enumerate(at.pop("times_ms")))
    tel = telemetry_medians(run_dir / "telemetry.csv")
    reason = None if backend.is_gpu else "numpy backend: no GPU on this machine"
    metrics = gpu_metrics(sweeps, tel, reason)
    bad = sum(p["mismatches"] for pts in sweeps.values() for p in pts)
    differ = [p["log2n"] for p in sweeps["bitonic_fused"] if p.get("identical_to_global") is False]
    unstable = [f"{k}@2^{p['log2n']}" for k, pts in sweeps.items() for p in pts if p.get("unstable")]
    low = [f"{k}@2^{p['log2n']}" for k, pts in sweeps.items() for p in pts if p.get("low_clock")]
    write_summary(run_dir, {
        "metrics": metrics,
        "executed_by": "cupy.RawModule (nvrtc)" if backend.is_gpu else "numpy twins (vcloak.gpu.sim)",
        "timer": "cupy.cuda.Event" if backend.is_gpu else None, "mismatches": bad, "fused_differs_from_global": differ,
        "unstable": unstable, "low_clock": low, "sweeps": sweeps, "telemetry": tel,
        "telemetry_samples": samples, "ramps": ramp_log,
        "peak_bw_gbs": peak, "cv_limit": CV_LIMIT, "device": info, "host": host_info(),
        "bw_model": "rounds(n) x n x 24 B x 2 (read + write); rounds = log2(n)(log2(n)+1)/2 (ai/GPU_GUIDE.md §5)"})

    notes = []
    if bad or differ:
        status = "FAIL"
        notes.append(f"{bad} output elements differ from the reference; fused != global at log2n {differ}")
    elif not backend.is_gpu:
        status = "NOT_MEASURED"
        notes.append("numpy backend: plumbing and output checks only, no GPU metric measured")
    elif unstable:
        status = "UNSTABLE"
        notes.append(f"{len(unstable)} configuration(s) unstable after two attempts: " + ", ".join(unstable))
    else:
        status = "OK"
    if low:
        notes.append(f"{len(low)} configuration(s) measured at a LOW SM clock (kept, labelled): " + ", ".join(low))
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))
    print(f"run dir     {run_dir}")
    print(f"backend     {backend.name}   sizes 2^{sizes[0]}..2^{sizes[-1]}   runs {n_runs}")
    print(f"checks      mismatches={bad} fused_differs_from_global={differ}")
    print(f"unstable    {len(unstable)}: {', '.join(unstable[:12])}")
    print(f"low clock   {len(low)}: {', '.join(low[:12])}")
    print(f"metrics     {len(metrics)}   telemetry samples {samples}")
    print(f"status      {status}")
    return 1 if status == "FAIL" else 0


# ── part: cpu ────────────────────────────────────────────────────────────────


def cpu_runs_for(lg: int, quick: bool) -> int:
    if quick:
        return CPU_RUNS_QUICK
    return CPU_RUNS_LARGE if lg > CPU_LARGE_LOG2N else CPU_RUNS


def measure_cpu(fn: Callable[[], Any], n_runs: int, first_s: float) -> tuple[list[dict], str]:
    """Time `fn` (already warmed up by one checked call that took `first_s`). Returns (attempts, note)."""
    note = ""
    if first_s * n_runs > CPU_BUDGET_S:
        cut = max(3, int(CPU_BUDGET_S // max(first_s, 1e-9)))
        note = f"runs cut from {n_runs} to {cut}: one call takes {first_s:.1f} s (budget {CPU_BUDGET_S:.0f} s)"
        n_runs = cut
    attempts = []
    for attempt in (1, 2):
        times = timing.time_cpu(fn, 0, n_runs)
        s = timing.summarise(times)
        attempts.append({"attempt": attempt, "times_ms": times, "stable": s["cv"] <= CV_LIMIT, **s})
        if attempts[-1]["stable"] or first_s * n_runs > CPU_REPEAT_MAX_S:
            break
    return attempts, note


def part_cpu(a: argparse.Namespace, backend: Backend, command: str) -> int:
    sizes = sweep_sizes(a, backend)
    measured = backend.is_gpu  # on the runner, beside the GPU; the laptop only checks the plumbing
    stage, numba_info = baselines.numba_stage()
    fns: dict[str, Callable[[baselines.Cols], baselines.Cols] | None] = {
        "oracle_bitonic": baselines.oracle_bitonic, "views_bitonic": baselines.views_bitonic,
        "numba_bitonic": (lambda c: baselines.pairs_bitonic(c, stage)) if stage else None,
        "lexsort": baselines.lexsort}
    run_dir = runs.new_run("M07", "cpu_baselines", step="S3", owner="Aditya", command=command, seed=a.seed,
                           quick=a.quick, root=Path.cwd(), runs_dir=a.out, backend=backend,
                           params={"n_log2": [sizes[0], sizes[-1]], "warmup": 1,
                                   "runs": {f"<=2^{CPU_LARGE_LOG2N}": cpu_runs_for(SWEEP_LO, a.quick),
                                            f">2^{CPU_LARGE_LOG2N}": cpu_runs_for(CPU_LARGE_LOG2N + 1, a.quick)},
                                   "baselines": list(fns), "timer": "time.perf_counter_ns", "cv_limit": CV_LIMIT,
                                   "budget_s": CPU_BUDGET_S})
    sweeps: dict[str, list[dict]] = {b: [] for b in fns}
    for lg in sizes:
        n = 1 << lg
        cols = make_cols(n, a.seed)
        for name, fn in fns.items():
            if fn is None:
                continue
            t0 = time.perf_counter()
            got = fn(cols)  # the warm-up call; for numba the first one also compiles
            first_s = time.perf_counter() - t0
            p: dict[str, Any] = {"n": n, "log2n": lg, "mismatches": baselines.mismatches(got, cols)}
            if measured and not p["mismatches"]:
                if name == "numba_bitonic" and lg == sizes[0]:
                    t0 = time.perf_counter()
                    fn(cols)
                    first_s = time.perf_counter() - t0  # without the compilation
                attempts, note = measure_cpu(lambda fn=fn, cols=cols: fn(cols), cpu_runs_for(lg, a.quick), first_s)
                last = attempts[-1]
                p.update({"median_ms": last["median_ms"], "cv": last["cv"], "unstable": not last["stable"],
                          "keys_per_s": derive.per_second(n, last["median_ms"]), "note": note, "attempts": attempts})
            sweeps[name].append(p)

    if measured:
        with (run_dir / "raw.csv").open("w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow(["baseline", "log2n", "attempt", "run", "elapsed_ms"])
            for name, points in sweeps.items():
                for p in points:
                    for at in p.get("attempts", []):
                        wr.writerows((name, p["log2n"], at["attempt"], i, t) for i, t in enumerate(at.pop("times_ms")))
    reason = None if measured else ("not on the runner: the CPU baselines must come from the runner session of "
                                    "the GPU sweep (ai/GPU_RUNNER.md §7)")
    metrics = []
    for name, points in sweeps.items():
        kind = "oblivious" if name in baselines.OBLIVIOUS else "not oblivious, lower bound"
        for lg in sizes:
            mid = f"{CPU_METRIC[name]}-2^{lg}"
            p = next((x for x in points if x["log2n"] == lg), None)
            if p is None:
                metrics.append(metric(mid, NM, "ms", "median", numba_info.get("reason", "not run")))
            elif "median_ms" not in p:
                metrics.append(metric(mid, NM, "ms", "median", reason or "the output differs from np.lexsort"))
            else:
                last = p["attempts"][-1]
                note = f"{name} ({kind}), {last['runs']} runs, perf_counter_ns, CV {p['cv']:.3f}"
                note += f"; {p['note']}" if p["note"] else ""
                note += "; UNSTABLE: CV above the limit, attempts in raw.csv and summary.json" if p["unstable"] else ""
                value = derive.value_or_flag(p["median_ms"], p["unstable"], 4)
                metrics.append(metric(mid, value, "ms", "median", note))
    bad = sum(p["mismatches"] for pts in sweeps.values() for p in pts)
    unstable = [f"{k}@2^{p['log2n']}" for k, pts in sweeps.items() for p in pts if p.get("unstable")]
    write_summary(run_dir, {"metrics": metrics, "timer": "time.perf_counter_ns" if measured else None,
                            "mismatches": bad, "unstable": unstable, "sweeps": sweeps, "numba": numba_info,
                            "host": host_info(), "numpy": np.__version__, "cv_limit": CV_LIMIT,
                            "oblivious": list(baselines.OBLIVIOUS), "not_oblivious": list(baselines.NON_OBLIVIOUS)})
    notes = [] if stage else [f"numba baseline NOT_MEASURED: {numba_info['reason']}"]
    if bad:
        status = "FAIL"
        notes.append(f"{bad} output elements differ from np.lexsort")
    elif not measured:
        status = "NOT_MEASURED"
        notes.append("plumbing and output checks only: " + str(reason))
    elif unstable:
        status = "UNSTABLE"
        notes.append(f"{len(unstable)} configuration(s) above the CV limit: " + ", ".join(unstable))
    else:
        status = "OK"
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))
    print(f"run dir     {run_dir}")
    print(f"host        {host_info()['cpu']} x{host_info()['cpu_count']}   numba {numba_info}")
    print(f"checks      mismatches={bad}   unstable {len(unstable)}: {', '.join(unstable[:12])}")
    print(f"metrics     {len(metrics)}")
    print(f"status      {status}")
    return 1 if status == "FAIL" else 0


# ── part: crossover ──────────────────────────────────────────────────────────


def find_run(out: Path, name: str, session_id: str, quick: bool) -> tuple[Path | None, str]:
    """The newest measured `M07_<name>` run dir of this runner session, or (None, why not)."""
    seen = 0
    for d in sorted(out.glob(f"*_M07_{name}*"), reverse=True):
        if not (d / "manifest.json").exists() or not (d / "summary.json").exists():
            continue
        m = runs.read_manifest(d)
        seen += 1
        if m["env"].get("session_id") == session_id and bool(m["quick"]) == quick and m["status"] in ("OK", UNSTABLE) \
                and m["env"].get("backend") == "cupy":
            return d, ""
    return None, f"no measured M07 {name} run of session {session_id} (quick={quick}) in {out.name}/ ({seen} other)"


def points_by_n(points: list[dict]) -> dict[int, dict]:
    return {p["n"]: p for p in points if p.get("median_ms")}


def part_crossover(a: argparse.Namespace, backend: Backend, command: str) -> int:
    out = Path(a.out).resolve()
    run_dir = runs.new_run("M07", "crossover", step="S4", owner="Aditya", command=command, seed=a.seed,
                           quick=a.quick, root=Path.cwd(), runs_dir=a.out, backend=backend, params={})
    session_id = runs.read_manifest(run_dir)["env"]["session_id"]
    gpu_dir, why_g = find_run(out, "kernel_sweep", session_id, a.quick)
    cpu_dir, why_c = find_run(out, "cpu_baselines", session_id, a.quick)
    ids = ["X-CROSSOVER-N", *(f"X-SPEEDUP-2^{lg}" for lg in SPEEDUP_LOG2N),
           *(f"X-SPEEDUP-VS-LEXSORT-2^{lg}" for lg in SPEEDUP_LOG2N)]
    if gpu_dir is None or cpu_dir is None:
        reason = "; ".join(x for x in (why_g, why_c) if x)
        metrics = [metric(i, NM, "n" if i == "X-CROSSOVER-N" else "x", "value", reason) for i in ids]
        write_summary(run_dir, {"metrics": metrics, "inputs": None, "reason": reason})
        runs.finish_run(run_dir, status="NOT_MEASURED", notes=reason)
        print(f"run dir     {run_dir}\nstatus      NOT_MEASURED ({reason})")
        return 0

    g_sum = json.loads((gpu_dir / "summary.json").read_text(encoding="utf-8"))
    c_sum = json.loads((cpu_dir / "summary.json").read_text(encoding="utf-8"))
    gpu = points_by_n(g_sum["sweeps"]["sort_e2e"])
    cpu = {b: points_by_n(pts) for b, pts in c_sum["sweeps"].items()}
    table = derive.compare(gpu, cpu, baselines.OBLIVIOUS)
    table_lex = derive.compare(gpu, cpu, baselines.NON_OBLIVIOUS)
    x = derive.crossover(table)
    pair = f"{g_sum['device'].get('gpu')} / {c_sum['host'].get('cpu')} x{c_sum['host'].get('cpu_count')}"
    where = f"same runner session {session_id}; {pair}"

    if x["kind"] == "no_data":
        metrics = [metric("X-CROSSOVER-N", NM, "n", "value", "no n measured on both sides")]
    elif x["kind"] == "none":
        metrics = [metric("X-CROSSOVER-N", "NONE", "n", "value",
                          f"the GPU (kernels + transfers) is not faster than the best oblivious CPU baseline at "
                          f"the largest compared n = {x['largest_n']}; {where}")]
    else:
        bound = "smallest n from which the GPU (kernels + transfers) is faster at every compared n" \
            if x["kind"] == "at" else "the GPU is faster at every compared n, so n* is at most this smallest swept n"
        metrics = [metric("X-CROSSOVER-N", UNSTABLE if x["unstable"] else x["n"], "n",
                          "value" if x["kind"] == "at" else "upper-bound",
                          f"{bound}; against the best oblivious CPU baseline; {where}")]
    for rows, prefix, what in ((table, "X-SPEEDUP", "best oblivious CPU baseline"),
                               (table_lex, "X-SPEEDUP-VS-LEXSORT", "np.lexsort (not oblivious, lower bound)")):
        for lg in SPEEDUP_LOG2N:
            r = next((r for r in rows if r["log2n"] == lg), None)
            if r is None:
                metrics.append(metric(f"{prefix}-2^{lg}", NM, "x", "ratio", f"2^{lg} was not measured on both sides"))
            else:
                metrics.append(metric(f"{prefix}-2^{lg}", derive.value_or_flag(r["speedup"], r["unstable"], 3), "x",
                                      "ratio", f"{what} ({r['cpu_baseline']}) median / GPU sort_e2e median; {where}"))
    write_summary(run_dir, {"metrics": metrics, "crossover": x, "table": table, "table_vs_lexsort": table_lex,
                            "inputs": {"gpu_run": f"runs/{gpu_dir.name}", "cpu_run": f"runs/{cpu_dir.name}",
                                       "session_id": session_id, "gpu_series": "sort_e2e (H2D + fused sort + D2H)"},
                            "pair": pair, "caveat": SHARED_GPU_CAVEAT})
    unstable = [m["id"] for m in metrics if m["value"] == UNSTABLE]
    m = runs.read_manifest(run_dir)
    m["params"] = {"gpu_run": gpu_dir.name, "cpu_run": cpu_dir.name, "session_id": session_id,
                   "speedup_log2n": list(SPEEDUP_LOG2N)}
    runs.write_manifest(run_dir, m)
    runs.finish_run(run_dir, status=UNSTABLE if unstable else "OK",
                    notes=SHARED_GPU_CAVEAT + (f" Unstable inputs behind: {', '.join(unstable)}." if unstable else ""))
    print(f"run dir     {run_dir}")
    print(f"inputs      {gpu_dir.name}  {cpu_dir.name}")
    for mm in metrics:
        print(f"{mm['id']:<28} {mm['value']} {mm['unit']}")
    print(f"status      {UNSTABLE if unstable else 'OK'}")
    return 0


# ── main ─────────────────────────────────────────────────────────────────────


def sweep_sizes(a: argparse.Namespace, backend: Backend) -> list[int]:
    """log2(n) values: --sweep lo:hi, else 2^10 up to min(SWEEP_LOG2N_CAP, the device's max_log2n);
    2^18 with --quick; two small sizes on the numpy backend."""
    if a.sweep:
        lo, hi = (int(x) for x in a.sweep.split(":"))
    elif not backend.is_gpu:
        lo, hi = LOCAL_SIZES
        return list(range(lo, hi + 1, hi - lo))
    else:
        cap = min(config.SWEEP_LOG2N_CAP, int(backend.device_info().get("max_log2n") or config.SWEEP_LOG2N_CAP))
        lo, hi = SWEEP_LO, min(QUICK_HI, cap) if a.quick else cap
    if not 2 <= lo <= hi <= config.MAX_LOG2N_CAP:
        raise SystemExit(f"--sweep must satisfy 2 <= lo <= hi <= {config.MAX_LOG2N_CAP}")
    return list(range(lo, hi + 1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--part", required=True, choices=("gpu", "cpu", "crossover"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--sweep", help="lo:hi as log2(n), e.g. 10:22")
    ap.add_argument("--runs", type=int, help="timed GPU runs per configuration (default 50; 15 with --quick)")
    ap.add_argument("--out", default="runs", help="parent directory for the run dir")
    a = ap.parse_args(argv)
    if a.runs is not None and a.runs < 2:
        ap.error("--runs must be at least 2")
    backend = get_backend()
    command = ("python bench/run_kernels.py " + " ".join(shlex.quote(x) for x in (argv or sys.argv[1:]))).strip()
    return {"gpu": part_gpu, "cpu": part_cpu, "crossover": part_crossover}[a.part](a, backend, command)


if __name__ == "__main__":
    sys.exit(main())
