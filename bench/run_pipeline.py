#!/usr/bin/env python3
"""M06 S5 - smoke benchmark of the GPU engine pipeline, and with --full the M07 S5 pipeline breakdown.

    python bench/run_pipeline.py --dev --seed 6 [--quick] [--out runs]            (M06 smoke)
    python bench/run_pipeline.py --dev --full --seed 7 [--quick] [--out runs]     (M07 S5)

Smoke mode.

On the runner it times `GpuEngine.write_epoch` with a full batch at SLOTS in {64, 4096, 65536} and
`GpuEngine.read_window` at K in {128, 1024}. Each call is timed by the engine itself with CUDA events
on its stream (`last_timings`, per stage); after a warm-up, >= 30 calls are recorded (15 with --quick)
and the median of `total` is reported. Every configuration is first checked against the M01 oracle.

`total` covers one whole call: the kernels, the transfers and the host work of the engine (gather,
random bytes, building the rows). Payloads are 8-byte stand-ins: payload bytes never go to the device
(ADR-006), so their size does not change what is measured here.

`--dev` loads a fixed TEST master derived from the seed (never a production key). The sealed key and
its passphrase belong to the service boot (M10); this script has no other key source.

Full mode (M07 S5). write_epoch at SLOTS in {2^6, 2^10, 2^12, 2^14, 2^16} and read_window at
K in {64 ... 4096}, 200 timed calls each (30 with --quick), so that a p99 is more than the maximum.
Per call the engine's CUDA-event stages are kept apart: `device` is the sum of the device stages
(h2d, tags, sort, compact, d2h, seal, bucket, open) and `host` is the engine's Python work between
them (ISSUE-12). The real-time gate compares the p99 of `total` with EPOCH_MS, and separately the p99
of `device`. A configuration whose CV of `total` exceeds 10%, or whose SM clock moved by more than
15%, is repeated once; if it fails again both attempts are kept and its metrics are UNSTABLE.
The SM clock is recorded with every metric; it is not forced up, because an engine that is mostly
waiting for the host leaves the GPU at a low clock in service as well (ISSUE-11). The host stage of
the largest SLOTS is profiled with cProfile into host_profile.txt (function names and times only).

Under the numpy backend (the laptop) each configuration runs once on the simulator twins to check the
plumbing against the oracle, and every metric is recorded as NOT_MEASURED.
"""
from __future__ import annotations

import argparse
import cProfile
import csv
import io
import json
import pstats
import shlex
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chacha_smoke import CV_LIMIT, NM, clock_change, test_key  # noqa: E402
from vcloak import config, runs  # noqa: E402
from vcloak.bench import timing  # noqa: E402
from vcloak.gpu import telemetry  # noqa: E402
from vcloak.gpu.engine import ROW_ENTROPY, STAGES, GpuEngine, Submission  # noqa: E402
from vcloak.gpu.keystore import DeviceKeyStore  # noqa: E402
from vcloak.gpu.runtime import get_backend, host_info  # noqa: E402
from vcloak.oracle import reference as ref  # noqa: E402

WRITE_SLOTS = (64, 4096, 65536)
READ_K = (128, 1024)
WARM_SECONDS = 2.0  # ISSUE-7: a warm-up of a few milliseconds leaves the GPU at its idle clock
HIT_FRACTION = 8  # one candidate in 8 belongs to the conversation that is read
COLUMNS = (*STAGES, "total")

FULL_WRITE_SLOTS = (64, 1024, 4096, 16384, 65536)
FULL_READ_K = (64, 128, 256, 512, 1024, 2048, 4096)
FULL_RUNS, FULL_RUNS_QUICK = 200, 30
DEVICE_STAGES = tuple(s for s in STAGES if s != "host")
PROFILE_CALLS, PROFILE_LINES = 3, 30
UNSTABLE = timing.UNSTABLE


class Tape:
    """Public random bytes served in order, so that the engine and the oracle seal with the same values."""

    def __init__(self, data: bytes) -> None:
        self.data, self.pos = data, 0

    def __call__(self, n: int) -> bytes:
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out


def make_batch(n: int, seed: int, hits: int = 0) -> tuple[list[Submission], int]:
    """n submissions with 8-byte payloads; the first `hits` belong to one conversation, whose id is returned."""
    rng = np.random.default_rng([seed, n])
    conv = rng.integers(0, 2**64, n, dtype=np.uint64)
    target = int(conv[0])
    conv[:hits] = conv[0]
    seq = rng.integers(0, 2**64, n, dtype=np.uint64).tolist()
    pairs = zip(conv.tolist(), seq, strict=True)
    return [Submission(c, s, i.to_bytes(8, "little")) for i, (c, s) in enumerate(pairs)], target


def rows_equal(got: list[Any], want: list[Any]) -> int:
    """The number of rows that differ between an engine result and the oracle's (0 = bit-exact)."""
    fields = ("row_id", "bucket", "win", "seq_enc", "payload")
    bad = abs(len(got) - len(want))
    return bad + sum(any(getattr(g, f) != getattr(w, f) for f in fields) for g, w in zip(got, want, strict=False))


def check_write(store: DeviceKeyStore, keys: ref.RefKeys, slots: int, batch: list[Submission], seed: int) -> int:
    tape = np.random.default_rng([seed, slots, 1]).integers(0, 256, ROW_ENTROPY * len(batch), dtype=np.uint8).tobytes()
    got = GpuEngine(store, slots, entropy=Tape(tape)).write_epoch(seed, batch)
    subs = [ref.Submission(s.conv_id, s.seq, s.payload) for s in batch]
    return rows_equal(got, ref.write_epoch_ref(keys, seed, subs, slots, entropy=Tape(tape)))


def check_read(eng: GpuEngine, keys: ref.RefKeys, target: int, cands: list[Any], k: int) -> int:
    got = eng.read_window(target, cands, k)
    oracle_rows = [ref.StoredRow(r.row_id, r.bucket, r.win, r.seq_enc, r.payload) for r in cands]
    want = ref.read_window_ref(keys, target, oracle_rows, k)
    return int(got != want) + int(len(got) != k // HIT_FRACTION)


def stats(records: list[dict[str, float]]) -> dict[str, Any]:
    a = np.asarray([r["total"] for r in records], dtype=np.float64)
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if a.size > 1 else 0.0
    return {"runs": int(a.size), "median_ms": float(np.median(a)), "p5_ms": float(np.percentile(a, 5)),
            "p95_ms": float(np.percentile(a, 95)), "mean_ms": mean, "std_ms": std,
            "cv": std / mean if mean > 0 else 0.0,
            "stage_median_ms": {s: float(np.median([r[s] for r in records])) for s in STAGES}}


def timed(call: Any, eng: GpuEngine, warmup: int, n_runs: int) -> tuple[list[dict[str, float]], dict, dict]:
    """Warm up (at least `warmup` calls and WARM_SECONDS), then record `last_timings` of `n_runs` calls.
    The telemetry snapshots are taken after the warm-up and after the last timed call (ISSUE-7)."""
    t0, i = time.monotonic(), 0
    while i < warmup or time.monotonic() - t0 < WARM_SECONDS:
        call(i)
        i += 1
    snap_warm = telemetry.snapshot()
    records = []
    for r in range(n_runs):
        call(i + r)
        records.append(eng.last_timings())
    return records, snap_warm, telemetry.snapshot()


def measure(call: Any, eng: GpuEngine, n_runs: int) -> list[dict[str, Any]]:
    """Up to two attempts: an unstable first attempt is repeated once and both are kept."""
    attempts: list[dict[str, Any]] = []
    for attempt in (1, 2):
        records, snap_warm, snap_end = timed(call, eng, config.TIMING_WARMUP, n_runs)
        clock = clock_change(snap_warm, snap_end)
        attempts.append({"attempt": attempt, "records": records, "clock": clock, "telemetry_after_warmup": snap_warm,
                         "telemetry_after_runs": snap_end, **stats(records)})
        if attempts[-1]["cv"] <= CV_LIMIT and clock["status"] != "UNSTABLE":
            break
    return attempts


# ── full mode (M07 S5) ───────────────────────────────────────────────────────


def stats_full(records: list[dict[str, float]]) -> dict[str, Any]:
    """Statistics of `total`, of the device stages together and of the host stage, plus per-stage medians
    and p99s. `device` + `host` = `total` in every call, because the stages add up to the total."""
    total = [r["total"] for r in records]
    device = [sum(r[s] for s in DEVICE_STAGES) for r in records]
    host = [r["host"] for r in records]
    return {**timing.summarise(total), "device": timing.summarise(device), "host": timing.summarise(host),
            "host_share_of_median_total": float(np.median(host)) / float(np.median(total)),
            "stage_median_ms": {s: float(np.median([r[s] for r in records])) for s in STAGES},
            "stage_p99_ms": {s: float(np.percentile([r[s] for r in records], 99)) for s in STAGES}}


def measure_full(call: Any, eng: Any, warmup: int, n_runs: int, sample: Any = None) -> list[dict[str, Any]]:
    """Up to two attempts of `n_runs` calls after a warm-up of at least `warmup` calls and WARM_SECONDS.
    The clock readings are taken after the warm-up and after the last timed call (ISSUE-7)."""
    sample = sample or telemetry.sample
    attempts: list[dict[str, Any]] = []
    for attempt in (1, 2):
        t0, i = time.monotonic(), 0
        while i < warmup or time.monotonic() - t0 < WARM_SECONDS:
            call(i)
            i += 1
        snap_warm = sample()
        records = []
        for r in range(n_runs):
            call(i + r)
            records.append(eng.last_timings())
        snap_end = sample()
        clock = timing.clock_check(snap_warm, snap_end)
        s = stats_full(records)
        attempts.append({"attempt": attempt, "records": records, "clock": clock, "warmup_calls": i,
                         "telemetry_after_warmup": snap_warm, "telemetry_after_runs": snap_end,
                         "stable": timing.stable(s["cv"], clock, low_clock_is_unstable=False), **s})
        if attempts[-1]["stable"]:
            break
    return attempts


def realtime_gate(configs: list[dict[str, Any]], epoch_ms: int) -> list[dict[str, Any]]:
    """Per write_epoch configuration: does the p99 of a whole call, and of its device part, fit one epoch?"""
    gate = []
    for c in configs:
        if c["kind"] != "write_epoch" or not c.get("attempts"):
            continue
        last = c["attempts"][-1]
        gate.append({"slots": c["size"], "epoch_ms": epoch_ms, "p99_total_ms": last["p99_ms"],
                     "p99_device_ms": last["device"]["p99_ms"], "median_host_ms": last["host"]["median_ms"],
                     "pass_total": last["p99_ms"] < epoch_ms, "pass_device": last["device"]["p99_ms"] < epoch_ms,
                     "unstable": not last["stable"]})
    return gate


FULL_ROWS = (("P99", "p99", "whole call", lambda a: a["p99_ms"]),
             ("MS", "median", "whole call", lambda a: a["median_ms"]),
             ("DEVICE-MS", "median", "device stages only", lambda a: a["device"]["median_ms"]),
             ("DEVICE-P99", "p99", "device stages only", lambda a: a["device"]["p99_ms"]),
             ("HOST-MS", "median", "host stage only", lambda a: a["host"]["median_ms"]))


def full_metrics(configs: list[dict[str, Any]], epoch_ms: int, reason: str | None) -> list[dict[str, Any]]:
    """The indexed metrics of the full mode. `reason` is set when nothing was measured."""
    out: list[dict[str, Any]] = []
    for c in configs:
        write = c["kind"] == "write_epoch"
        base = f"P-WRITE-EPOCH-{{}}-S{c['size']}" if write else f"P-READ-WINDOW-{{}}-K{c['size']}"
        last = c["attempts"][-1] if c.get("attempts") else None
        for name, stat, what, get in FULL_ROWS:
            mid = base.format(name)
            if last is None:
                why = reason or ("not timed: the output differs from the oracle" if c["mismatches"] else "not timed")
                out.append({"id": mid, "value": NM, "unit": "ms", "stat": stat, "note": why})
                continue
            clock = last["clock"]
            note = (f"{c['kind']} {what}, {last['runs']} calls, CUDA events, CV of total {last['cv']:.3f}, SM clock "
                    f"{clock.get('after_mhz')} of {clock.get('max_mhz')} MHz ({clock['status']})")
            if write and name == "P99":
                verdict = "PASS" if last["p99_ms"] < epoch_ms else "FAIL"
                note += f"; real-time gate p99 < {epoch_ms} ms: {verdict}"
            if not last["stable"]:
                note += f"; UNSTABLE after {len(c['attempts'])} attempts, both in raw.csv and summary.json"
            out.append({"id": mid, "value": round(get(last), 4) if last["stable"] else UNSTABLE, "unit": "ms",
                        "stat": stat, "note": note})
    return out


def profile_host(eng: GpuEngine, batch: list[Submission], path: Path) -> dict[str, Any]:
    """cProfile of a few write_epoch calls: where the host stage spends its time (ISSUE-12). The report
    holds function names, call counts and times; it never holds arguments or data."""
    prof = cProfile.Profile()
    prof.enable()
    for i in range(PROFILE_CALLS):
        eng.write_epoch(5000 + i, batch)
    prof.disable()
    buf = io.StringIO()
    pstats.Stats(prof, stream=buf).strip_dirs().sort_stats("cumulative").print_stats(PROFILE_LINES)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return {"file": path.name, "calls": PROFILE_CALLS, "slots": eng.slots, "sorted_by": "cumulative time"}


def main_full(a: argparse.Namespace, backend: Any, command: str) -> int:
    n_runs = FULL_RUNS_QUICK if a.quick else FULL_RUNS
    warmup = config.TIMING_WARMUP
    run_dir = runs.new_run("M07", "pipeline", step="S5", owner="Aditya", command=command, seed=a.seed,
                           quick=a.quick, root=Path.cwd(), runs_dir=a.out, backend=backend,
                           params={"write_slots": list(FULL_WRITE_SLOTS), "read_k": list(FULL_READ_K),
                                   "n_real": "slots (full)", "read_hits": f"K/{HIT_FRACTION}",
                                   "buckets": config.BUCKETS, "window_s": config.WINDOW_S, "epoch_ms": config.EPOCH_MS,
                                   "warmup": warmup, "warm_seconds": WARM_SECONDS, "runs": n_runs,
                                   "device_stages": list(DEVICE_STAGES), "cv_limit": CV_LIMIT})
    master = test_key(a.seed)  # a fixed TEST key, like every bench key
    keys = ref.RefKeys.from_master(master)
    store = DeviceKeyStore(backend)
    store.load_master(bytearray(master))

    configs: list[dict[str, Any]] = []
    profile: dict[str, Any] | None = None
    with telemetry.Sampler(run_dir / "telemetry.csv") as sampler:
        for slots in FULL_WRITE_SLOTS:
            batch, _ = make_batch(slots, a.seed)
            entry: dict[str, Any] = {"kind": "write_epoch", "size": slots, "n_real": slots,
                                     "mismatches": check_write(store, keys, slots, batch, a.seed)}
            if backend.is_gpu and not entry["mismatches"]:
                eng = GpuEngine(store, slots)
                entry["attempts"] = measure_full(lambda i, eng=eng, batch=batch: eng.write_epoch(1000 + i, batch),
                                                 eng, warmup, n_runs)
                if slots == FULL_WRITE_SLOTS[-1]:
                    profile = profile_host(eng, batch, run_dir / "host_profile.txt")
            configs.append(entry)
        for k in FULL_READ_K:
            batch, target = make_batch(k, a.seed + 1, hits=k // HIT_FRACTION)
            eng = GpuEngine(store, k)
            cands = eng.write_epoch(a.seed, batch)
            entry = {"kind": "read_window", "size": k, "hits": k // HIT_FRACTION,
                     "mismatches": check_read(eng, keys, target, cands, k)}
            if backend.is_gpu and not entry["mismatches"]:
                entry["attempts"] = measure_full(lambda i, eng=eng, target=target, cands=cands, k=k:
                                                 eng.read_window(target, cands, k), eng, warmup, n_runs)
            configs.append(entry)
    timer = GpuEngine(store, FULL_WRITE_SLOTS[0]).timer
    store.zeroize()

    if backend.is_gpu:
        with (run_dir / "raw.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["kind", "size", "attempt", "run", *(c + "_ms" for c in COLUMNS)])
            for c in configs:
                for at in c.get("attempts", []):
                    w.writerows((c["kind"], c["size"], at["attempt"], i, *(rec[x] for x in COLUMNS))
                                for i, rec in enumerate(at.pop("records")))

    reason = None if backend.is_gpu else "numpy backend: no GPU on this machine"
    metrics = full_metrics(configs, config.EPOCH_MS, reason)
    gate = realtime_gate(configs, config.EPOCH_MS)
    bad = sum(c["mismatches"] for c in configs)
    unstable = [f"{c['kind']}@{c['size']}" for c in configs if c.get("attempts") and not c["attempts"][-1]["stable"]]
    (run_dir / "summary.json").write_text(json.dumps(
        {"metrics": metrics,
         "executed_by": "cupy.RawModule (nvrtc)" if backend.is_gpu else "numpy twins (vcloak.gpu.sim)",
         "mismatches": bad, "unstable": unstable, "realtime_gate": gate, "configs": configs,
         "host_profile": profile, "timer": timer if backend.is_gpu else None,
         "telemetry_samples": sampler.samples if backend.is_gpu else 0, "cv_limit": CV_LIMIT,
         "device": backend.device_info(), "host": host_info(),
         "payload_note": "8-byte payload stand-ins: payload bytes never go to the device (ADR-006)"}, indent=2) + "\n",
        encoding="utf-8")

    notes = []
    if bad:
        status = "FAIL"
        notes.append(f"{bad} engine results differ from the oracle")
    elif not backend.is_gpu:
        status = "NOT_MEASURED"
        notes.append("numpy backend: plumbing and oracle check only, no GPU metric measured")
    elif unstable:
        status = "UNSTABLE"
        notes.append("CV above the limit or SM clock change on both attempts: " + ", ".join(unstable))
    else:
        status = "OK"
    failed = [str(g["slots"]) for g in gate if not g["pass_total"]]
    if failed:
        notes.append(f"real-time gate (p99 of a whole call < {config.EPOCH_MS} ms) FAILS at SLOTS " + ", ".join(failed))
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))

    print(f"run dir     {run_dir}")
    print(f"backend     {backend.name}   timer {timer}   calls {n_runs}")
    for c in configs:
        last = c["attempts"][-1] if c.get("attempts") else None
        extra = (f"  p99={last['p99_ms']:.3f} device_p99={last['device']['p99_ms']:.3f} host_med="
                 f"{last['host']['median_ms']:.3f} cv={last['cv']:.3f} clock={last['clock']['status']}") if last else ""
        print(f"{c['kind']:<12} {c['size']:>6}  oracle_mismatches={c['mismatches']}{extra}")
    for g in gate:
        print(f"rt gate     SLOTS {g['slots']:>6}: total {'PASS' if g['pass_total'] else 'FAIL'}  "
              f"device {'PASS' if g['pass_device'] else 'FAIL'}")
    print(f"status      {status}")
    return 1 if status == "FAIL" else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dev", action="store_true", help="use the fixed TEST master derived from --seed (required)")
    ap.add_argument("--full", action="store_true", help="the M07 S5 pipeline breakdown instead of the M06 smoke")
    ap.add_argument("--seed", type=int, default=6)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="runs", help="parent directory for the run dir")
    a = ap.parse_args(argv)
    if not a.dev:
        ap.error("--dev is required: this smoke benchmark runs with the fixed TEST master only "
                 "(the sealed production key is unsealed by the service, M10)")

    backend = get_backend()
    n_runs = config.TIMING_RUNS_QUICK if a.quick else config.TIMING_RUNS_MIN
    command = "python bench/run_pipeline.py " + " ".join(shlex.quote(x) for x in (argv or sys.argv[1:]))
    if a.full:
        return main_full(a, backend, command.strip())
    run_dir = runs.new_run("M06", "pipeline_smoke", step="S5", owner="Aditya", command=command.strip(), seed=a.seed,
                           quick=a.quick, root=Path.cwd(), runs_dir=a.out, backend=backend,
                           params={"write_slots": list(WRITE_SLOTS), "read_k": list(READ_K), "n_real": "slots (full)",
                                   "read_hits": f"K/{HIT_FRACTION}", "buckets": config.BUCKETS,
                                   "window_s": config.WINDOW_S, "epoch_ms": config.EPOCH_MS,
                                   "warmup": config.TIMING_WARMUP, "warm_seconds": WARM_SECONDS, "runs": n_runs})
    master = test_key(a.seed)  # a fixed TEST key, like every bench key
    keys = ref.RefKeys.from_master(master)
    store = DeviceKeyStore(backend)
    store.load_master(bytearray(master))

    configs: list[dict[str, Any]] = []
    with telemetry.Sampler(run_dir / "telemetry.csv") as sampler:
        for slots in WRITE_SLOTS:
            batch, _ = make_batch(slots, a.seed)
            entry: dict[str, Any] = {"kind": "write_epoch", "size": slots, "metric": f"P-WRITE-EPOCH-MS-S{slots}",
                                     "n_real": slots, "mismatches": check_write(store, keys, slots, batch, a.seed)}
            if backend.is_gpu and not entry["mismatches"]:
                eng = GpuEngine(store, slots)
                entry["attempts"] = measure(lambda i, eng=eng, batch=batch: eng.write_epoch(1000 + i, batch),
                                            eng, n_runs)
            configs.append(entry)
        for k in READ_K:
            batch, target = make_batch(k, a.seed + 1, hits=k // HIT_FRACTION)
            eng = GpuEngine(store, k)
            cands = eng.write_epoch(a.seed, batch)
            entry = {"kind": "read_window", "size": k, "metric": f"P-READ-WINDOW-MS-K{k}", "hits": k // HIT_FRACTION,
                     "mismatches": check_read(eng, keys, target, cands, k)}
            if backend.is_gpu and not entry["mismatches"]:
                entry["attempts"] = measure(lambda i, eng=eng, target=target, cands=cands, k=k:
                                            eng.read_window(target, cands, k), eng, n_runs)
            configs.append(entry)
    timer = GpuEngine(store, WRITE_SLOTS[0]).timer
    store.zeroize()

    if backend.is_gpu:
        with (run_dir / "raw.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["kind", "size", "attempt", "run", *(c + "_ms" for c in COLUMNS)])
            for c in configs:
                for at in c.get("attempts", []):
                    w.writerows((c["kind"], c["size"], at["attempt"], i, *(rec[x] for x in COLUMNS))
                                for i, rec in enumerate(at.pop("records")))

    reason = "numpy backend: no GPU on this machine"
    metrics, notes = [], []
    bad = sum(c["mismatches"] for c in configs)
    unstable = []
    for c in configs:
        last = c["attempts"][-1] if c.get("attempts") else None
        if last:
            note = (f"{c['kind']} total per call, {last['runs']} runs, CUDA events, CV {last['cv']:.3f}, "
                    f"SM clock {last['clock'].get('after_mhz')} MHz; smoke, not an M07 result")
            if last["cv"] > CV_LIMIT or last["clock"]["status"] == "UNSTABLE":
                unstable.append(c["metric"])
        elif c["mismatches"]:
            note = "not timed: the output differs from the oracle"
        else:
            note = reason
        metrics.append({"id": c["metric"], "value": round(last["median_ms"], 4) if last else NM, "unit": "ms",
                        "stat": "median", "note": note})
    (run_dir / "summary.json").write_text(json.dumps(
        {"metrics": metrics,
         "executed_by": "cupy.RawModule (nvrtc)" if backend.is_gpu else "numpy twins (vcloak.gpu.sim)",
         "mismatches": bad, "configs": configs, "timer": timer if backend.is_gpu else None,
         "telemetry_samples": sampler.samples if backend.is_gpu else 0, "cv_limit": CV_LIMIT,
         "device": backend.device_info()}, indent=2) + "\n", encoding="utf-8")

    if bad:
        status = "FAIL"
        notes.append(f"{bad} engine results differ from the oracle")
    elif not backend.is_gpu:
        status = "NOT_MEASURED"
        notes.append("numpy backend: plumbing and oracle check only, no GPU metric measured")
    elif unstable:
        status = "UNSTABLE"
        notes.append("CV above the limit or SM clock change on both attempts: " + ", ".join(unstable))
    else:
        status = "OK"
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))

    print(f"run dir     {run_dir}")
    print(f"backend     {backend.name}   timer {timer}")
    for c, m in zip(configs, metrics, strict=True):
        last = c["attempts"][-1] if c.get("attempts") else None
        extra = f"  cv={last['cv']:.3f} clock={last['clock']['status']}" if last else ""
        print(f"{m['id']:<28} {m['value']} {m['unit']}  oracle_mismatches={c['mismatches']}{extra}")
    print(f"status      {status}")
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
