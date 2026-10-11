#!/usr/bin/env python3
"""M06 S5 - smoke benchmark of the GPU engine pipeline (the full sweeps are M07).

    python bench/run_pipeline.py --dev --seed 6 [--quick] [--out runs]

On the runner it times `GpuEngine.write_epoch` with a full batch at SLOTS in {64, 4096, 65536} and
`GpuEngine.read_window` at K in {128, 1024}. Each call is timed by the engine itself with CUDA events
on its stream (`last_timings`, per stage); after a warm-up, >= 30 calls are recorded (15 with --quick)
and the median of `total` is reported. Every configuration is first checked against the M01 oracle.

`total` covers one whole call: the kernels, the transfers and the host work of the engine (gather,
random bytes, building the rows). Payloads are 8-byte stand-ins: payload bytes never go to the device
(ADR-006), so their size does not change what is measured here.

`--dev` loads a fixed TEST master derived from the seed (never a production key). The sealed key and
its passphrase belong to the service boot (M10); this script has no other key source.

Under the numpy backend (the laptop) each configuration runs once on the simulator twins to check the
plumbing against the oracle, and every metric is recorded as NOT_MEASURED.
"""
from __future__ import annotations

import argparse
import csv
import json
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
from vcloak.gpu import telemetry  # noqa: E402
from vcloak.gpu.engine import ROW_ENTROPY, STAGES, GpuEngine, Submission  # noqa: E402
from vcloak.gpu.keystore import DeviceKeyStore  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402
from vcloak.oracle import reference as ref  # noqa: E402

WRITE_SLOTS = (64, 4096, 65536)
READ_K = (128, 1024)
WARM_SECONDS = 2.0  # ISSUE-7: a warm-up of a few milliseconds leaves the GPU at its idle clock
HIT_FRACTION = 8  # one candidate in 8 belongs to the conversation that is read
COLUMNS = (*STAGES, "total")


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dev", action="store_true", help="use the fixed TEST master derived from --seed (required)")
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
