#!/usr/bin/env python3
"""E6: the cells of M15 S2: modes {baseline, vcloak} x users x repetitions, each one a run of `bench/run_e2e.py`.

    python bench/run_e2e_cells.py [--users 10,50,200] [--reps 2] [--quick] [--store pg|sqlite] [--out runs]
                                  [--rate 0.15] [--slots 256] [--poll-ms 500] [--seed 15] [--pause 5]
                                  [--duration S] [--warmup S] [--buckets N] [--window-s N] [--epoch-ms N] [--cand-k N]

The population is declared scope, not a default (ADR-027): two users per conversation, 10, 50 and 200 users
(`--quick`: 10 and 50 users, 30 s). The cells run in the order of `vcloak.bench.e2e.cell_order`: within a
repetition the two modes of one user count run back to back, the baseline first. Every cell gets the same seed,
so both modes and both repetitions replay the same schedule; with PostgreSQL every cell writes into a schema of
its own (`e2e_<mode>_u<users>_r<rep>`), dropped first. A cell that fails is recorded and the next one runs: this
script never retries, never drops and never shrinks a cell.

Before the first cell the script writes `bucket_bound.json`: for each user count, how many sends of the schedule
can fall into one bucket-window at most (`e2e.bucket_span_peaks`), beside CAND_K. That is arithmetic on the seed,
the public layout and the public development key of `--dev`: it says where a read may answer `candidate_overflow`
(ADR-014), it is not a measurement.

Outputs in its own run dir: cells.csv (one row per cell: its run dir, exit code and the counts its summary gives),
bucket_bound.json, cell_<...>.txt (the output of each cell), summary.json. No latency is copied here: S3 reads the
cells. On the numpy backend the whole matrix is a correctness run.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from vcloak import config, runs  # noqa: E402
from vcloak.bench import e2e  # noqa: E402
from vcloak.crypto import chacha_ref  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402
from vcloak.service.app import dev_master  # noqa: E402
from vcloak.service.models import conv_id_of  # noqa: E402

USERS = (10, 50, 200)  # ADR-027
USERS_QUICK = (10, 50)
SLOTS = 256  # ISSUE-49 (2): one value for every cell and both modes
RATE = 0.15  # ISSUE-49 (1), the owner in session 50: at 0.2 the 200-user schedule can exceed CAND_K in two buckets
PASS_THROUGH = ("duration", "warmup", "buckets", "window_s", "epoch_ms", "cand_k")
CELL_TIMEOUT_EXTRA_S = 900.0  # service start, account setup (two Argon2id hashes per user), drain
FIELDS = ("rep", "users", "mode", "exit_code", "status", "run_dir", "scheduled", "acked", "errors",
          "readable_missing", "read_errors", "epochs", "epoch_overflow", "telemetry_samples", "cpu_samples",
          "schema_bytes", "wall_s")


def bucket_bound(users: int, a: argparse.Namespace, total_s: float) -> dict[str, Any]:
    """Where the schedule of this user count can exceed CAND_K in one bucket-window (see the module docstring)."""
    buckets = a.buckets or config.BUCKETS
    window_s = a.window_s or config.WINDOW_S
    cand_k = a.cand_k or config.CAND_K
    tokens = e2e.conv_tokens(np.random.default_rng([a.seed, 0xE2E]), users // 2)  # the tokens of run_e2e.Cell
    ids = np.array([conv_id_of(t) for t in tokens], dtype=np.uint64)
    k_bkt = chacha_ref.derive_subkeys(bytes(dev_master()))[2]  # the public development key, not a secret
    bucket = [int(b) for b in chacha_ref.bucket_prf(k_bkt, ids, buckets)]
    peaks = e2e.bucket_span_peaks(e2e.schedule(users, a.rate, total_s, a.seed), bucket, float(window_s))
    over = sorted(b for b, n in peaks.items() if n > cand_k)
    convs = [bucket.count(b) for b in sorted(set(bucket))]
    return {"users": users, "conversations": users // 2, "rate_per_user_s": a.rate, "buckets": buckets,
            "window_s": window_s, "cand_k": cand_k, "buckets_used": len(convs),
            "conversations_in_fullest_bucket": max(convs),
            "max_sends_in_one_window_span": max(peaks.values()),
            "buckets_that_can_exceed_cand_k": len(over),
            "conversations_in_those_buckets": sum(bucket.count(b) for b in over),
            "kind": "arithmetic on the schedule, the layout and the public development key: an upper bound over "
                    "every alignment of the wall-clock window, not a measurement"}


def cell_command(a: argparse.Namespace, rep: int, users: int, mode: str) -> list[str]:
    cmd = [sys.executable, str(ROOT / "bench" / "run_e2e.py"), "--mode", mode, "--users", str(users),
           "--rep", str(rep), "--rate", str(a.rate), "--slots", str(a.slots), "--poll-ms", str(a.poll_ms),
           "--seed", str(a.seed), "--store", a.store, "--out", str(a.out)]
    if a.store == "pg":
        cmd += ["--schema", f"e2e_{mode}_u{users}_r{rep}"]
    if a.quick:
        cmd.append("--quick")
    for name in PASS_THROUGH:
        if getattr(a, name) is not None:
            cmd += ["--" + name.replace("_", "-"), str(getattr(a, name))]
    return cmd


def read_cell(out: str) -> tuple[str, dict[str, Any]]:
    """The run dir a cell printed and the counts of its summary, or what is missing."""
    line = next((x for x in out.splitlines() if x.startswith("run dir")), "")
    run_dir = Path(line.split(None, 2)[2]) if line else None
    if run_dir is None or not (run_dir / "manifest.json").exists():
        return "", {"status": "NO_RUN_DIR"}
    row: dict[str, Any] = {"status": runs.read_manifest(run_dir).get("status")}
    if (run_dir / "summary.json").exists():
        s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        st, delta = s["stats"], s["service"]["delta"]
        row.update({"scheduled": st["scheduled"], "acked": st["acked"], "errors": sum(st["errors"].values()),
                    "readable_missing": st["readable_missing"], "read_errors": sum(s["reads"]["errors"].values()),
                    "epochs": delta["epochs"], "epoch_overflow": delta["overflow"],
                    "telemetry_samples": s["telemetry"]["samples"],
                    "cpu_samples": (s.get("cpu") or {}).get("samples", 0),
                    "schema_bytes": s["db"].get("schema_bytes", "")})
    return run_dir.name, row


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--users", default=None, help="comma-separated user counts (default 10,50,200; quick 10,50)")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--rate", type=float, default=RATE, help="sends per second of one user")
    ap.add_argument("--slots", type=int, default=SLOTS)
    ap.add_argument("--poll-ms", type=float, default=500.0)
    ap.add_argument("--seed", type=int, default=15)
    ap.add_argument("--store", choices=("pg", "sqlite"), default="pg")
    ap.add_argument("--pause", type=float, default=5.0, help="seconds between two cells")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--warmup", type=float, default=None)
    for name in PASS_THROUGH[2:]:
        ap.add_argument("--" + name.replace("_", "-"), type=int, default=None, help="passed to every cell")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    a = build_parser().parse_args(argv)
    users = [int(x) for x in a.users.split(",")] if a.users else list(USERS_QUICK if a.quick else USERS)
    for u in users:
        e2e.pairs(u)
    order = e2e.cell_order(users, a.reps)
    backend = get_backend()
    a.out = str(Path(a.out).resolve())
    duration = a.duration if a.duration is not None else (30.0 if a.quick else 120.0)
    total_s = (20.0 if a.warmup is None else a.warmup) + duration
    plan = {"users": users, "users_per_conversation": 2, "reps": a.reps, "modes": list(e2e.MODES),
            "rate": a.rate, "slots": a.slots, "poll_ms": a.poll_ms, "store": a.store, "ack": "stored",
            "sessions": True, "duration_s": duration, "pause_s": a.pause,
            **{k: getattr(a, k) for k in PASS_THROUGH[1:]}}
    run_dir = runs.new_run("M15", "e2e_cells", step="S2", owner="Divyansh", seed=a.seed, quick=a.quick,
                           command="python bench/run_e2e_cells.py " + " ".join(shlex.quote(x) for x in argv),
                           root=Path.cwd(), runs_dir=a.out, backend=backend, params=plan)
    bounds = [bucket_bound(u, a, total_s) for u in users]
    (run_dir / "bucket_bound.json").write_text(json.dumps(bounds, indent=2) + "\n", encoding="utf-8")
    for b in bounds:
        print(f"bound       users {b['users']}: at most {b['max_sends_in_one_window_span']} sends in one "
              f"bucket-window, CAND_K {b['cand_k']}, buckets that can exceed it: "
              f"{b['buckets_that_can_exceed_cand_k']}", flush=True)

    rows: list[dict[str, Any]] = []
    with (run_dir / "cells.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, restval="")
        w.writeheader()
        for i, (rep, u, mode) in enumerate(order):
            if i:
                time.sleep(a.pause)
            cmd = cell_command(a, rep, u, mode)
            t = time.monotonic()
            try:
                r = subprocess.run(cmd, cwd=Path.cwd(), capture_output=True, text=True, env=dict(os.environ),
                                   timeout=total_s + CELL_TIMEOUT_EXTRA_S)
                code, out = r.returncode, r.stdout + r.stderr
            except subprocess.TimeoutExpired as e:
                code, out = 124, f"TIMEOUT after {e.timeout:.0f} s\n{e.stdout or ''}{e.stderr or ''}"
            (run_dir / f"cell_{mode}_u{u}_r{rep}.txt").write_text(out, encoding="utf-8")
            name, got = read_cell(out)
            row = {"rep": rep, "users": u, "mode": mode, "exit_code": code, "run_dir": name,
                   "wall_s": f"{time.monotonic() - t:.1f}", **got}
            rows.append(row)
            w.writerow(row)
            f.flush()
            print(f"cell {i + 1:2d}/{len(order)}  r{rep} u{u:<4d} {mode:8s} exit {code}  {got.get('status')}  "
                  f"acked {got.get('acked', '-')}/{got.get('scheduled', '-')}  "
                  f"unread {got.get('readable_missing', '-')}  {row['wall_s']} s  {name}", flush=True)

    failed = [r for r in rows if r["exit_code"] != 0 or r["status"] != "OK"]
    reason = None if backend.is_gpu else "numpy backend: a correctness run of the driver, never a performance result"
    (run_dir / "summary.json").write_text(json.dumps({
        "metrics": [], "reason": reason, "plan": plan, "order": [list(x) for x in order],
        "cells": len(rows), "failed": [f"r{r['rep']} u{r['users']} {r['mode']}" for r in failed],
        "bucket_bound": bounds}, indent=2) + "\n", encoding="utf-8")
    notes = [f"{len(failed)} of {len(rows)} cells failed"] if failed else []
    runs.finish_run(run_dir, status="FAIL" if failed else "OK", notes="; ".join(notes + ([reason] if reason else [])))
    print(f"run dir     {run_dir}")
    print(f"status      {'FAIL' if failed else 'OK'}   {len(rows) - len(failed)} of {len(rows)} cells OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
