#!/usr/bin/env python3
"""M14: the security evaluation on the real stack. Stage S1: the traffic.

    python bench/run_security_eval.py --stage s1 [--quick] [--seed 2026] [--store pg|sqlite] [--schema m14_eval]
                                      [--backend auto|cupy|numpy] [--out runs]

S1 replays the bursty traffic of the seed oracle (200 conversations, 900 simulated seconds, rate 0.05/s;
`--quick`: 40 conversations, 120 s, 16 buckets) through the service API on a simulated clock and counts
what the store holds afterwards. The app runs in-process with the objects `vcloak serve --dev --clock sim`
builds, except that the scheduler is stepped by the replay (`autorun=False`), so that every arrival
falls into the epoch of its simulated time.

With `--store pg` the rows go to their own schema of the development database; the schema is dropped
first and left in place afterwards. The manifest records the seed, the store and the backend that
executed the kernels. A run on the numpy simulator has the kernel semantics of the device and is no
evidence about a GPU: audit A1 of M14 asks for engine=gpu.

Outputs in the run dir: s1_traffic.json, summary.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import config, runs  # noqa: E402
from vcloak.eval import traffic  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402
from vcloak.service.app import VcloakBackend, create_app, dev_master  # noqa: E402
from vcloak.service.scheduler import SimClock  # noqa: E402
from vcloak.storage.repo import PgRepo, SqliteRepo  # noqa: E402

SEED = 2026
RATE = 0.05  # first messages and pauses per second and conversation (the oracle's rate)
FULL = {"n_conv": 200, "duration_s": 900, "buckets": config.BUCKETS}
QUICK = {"n_conv": 40, "duration_s": 120, "buckets": 16}
SCHEMA = "m14_eval"
MSGS_METRIC = "S-TRAFFIC-MSGS"


def open_repo(store: str, dsn: str | None, schema: str) -> Any:
    if store == "sqlite":
        return SqliteRepo()
    repo = PgRepo(dsn, schema=schema)
    repo.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")  # `schema` passed the identifier check of PgRepo
    return repo


def run_s1(repo: Any, gpu: Any, *, seed: int, n_conv: int, duration_s: int, buckets: int,
           slots: int = config.SLOTS, window_s: int = config.WINDOW_S, epoch_ms: int = config.EPOCH_MS,
           cand_k: int = config.CAND_K) -> dict[str, Any]:
    """Replay the traffic of `seed` and compare the store with what was sent."""
    events = traffic.burst_events(np.random.default_rng(seed), n_conv, duration_s, RATE)
    clock = SimClock()
    backend = VcloakBackend(repo, clock, dev_master, gpu=gpu, slots=slots, buckets=buckets, window_s=window_s,
                            epoch_ms=epoch_ms, cand_k=cand_k, autorun=False)

    async def main() -> tuple[traffic.Replay, dict[str, Any]]:
        app = create_app(backend, web_dir=False)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://vcloak.test") as client:
                sent = await traffic.replay(backend, clock, client, events, seed=seed,
                                            duration_ms=duration_s * 1000, epoch_ms=epoch_ms)
            sched = backend.scheduler
            state = {"epochs_written": sched.epochs, "epoch_errors": sched.errors, "overflow": sched.overflow,
                     "missed": sched.missed, "queued": sched.queued, "windows_rewritten": len(sched.rewrites),
                     "max_rewrites_of_a_window": max(sched.rewrites.values(), default=0),
                     "compute": dict(backend._compute or {})}
            return sent, state

    sent, state = asyncio.run(main())
    rows = repo.dump()
    stored = Counter(traffic.digest(r.payload) for r in rows)
    per_conv = Counter(e.conv for e in events)
    per_window = Counter(r.win for r in rows)
    per_epoch = Counter(e.t_ms // epoch_ms for e in events)
    checks = {
        "every_post_accepted": not sent.refused,
        "row_count_equals_message_count": len(rows) == len(events),
        "stored_ciphertexts_are_the_sent_ones": stored == Counter(sent.digests),
        "no_epoch_failed": state["epoch_errors"] == 0,
        "nothing_left_queued": state["queued"] == 0,
        "no_window_left_unshuffled": repo.pending_windows() == [],
        "each_window_rewritten_once": state["max_rewrites_of_a_window"] <= 1,
    }
    return {
        "stage": "S1", "seed": seed, "mode": "vcloak", "visible_round": "window",
        "params": {"n_conv": n_conv, "duration_s": duration_s, "rate": RATE, "slots": slots, "buckets": buckets,
                   "window_s": window_s, "epoch_ms": epoch_ms, "cand_k": cand_k},
        "messages": len(events), "accepted": sent.accepted, "rows_stored": len(rows),
        "epochs_passed": sent.epochs, "scheduler": state,
        "messages_per_conversation": {"min": min(per_conv.values()), "median": statistics.median(per_conv.values()),
                                      "max": max(per_conv.values()), "conversations_with_messages": len(per_conv)},
        "rows_per_window": {str(w): n for w, n in sorted(per_window.items())},
        "peak_messages_in_one_epoch": max(per_epoch.values()),
        "checks": checks, "ok": all(checks.values()),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=("s1",), required=True)
    ap.add_argument("--quick", action="store_true", help="the oracle's quick sizes")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--store", choices=("pg", "sqlite"), default="pg")
    ap.add_argument("--dsn", default=None, help="PostgreSQL DSN (default: VCLOAK_PG_DSN or the development database)")
    ap.add_argument("--schema", default=SCHEMA)
    ap.add_argument("--backend", choices=config.BACKENDS, default="auto")
    ap.add_argument("--out", default="runs", help="parent directory of the run dir")
    a = ap.parse_args(argv)
    sizes = QUICK if a.quick else FULL
    gpu = get_backend(a.backend)
    db = "postgres" if a.store == "pg" else "sqlite"
    command = "python bench/run_security_eval.py " + " ".join(argv if argv is not None else sys.argv[1:])
    run_dir = runs.new_run("M14", "security_s1", step="S1", owner="Abhishek", command=command.strip(),
                           seed=a.seed, quick=a.quick, root=ROOT, runs_dir=a.out, backend=gpu,
                           params={**sizes, "rate": RATE, "mode": "vcloak", "db": db, "schema": a.schema,
                                   "clock": "sim", "engine": "gpu" if gpu.is_gpu else "numpy-simulator"})
    repo = open_repo(a.store, a.dsn, a.schema)
    try:
        res = run_s1(repo, gpu, seed=a.seed, **sizes)
        if a.store == "pg":
            res["rows_counted_by_sql"] = int(repo.execute("SELECT count(*) FROM messages")[0][0])
            res["checks"]["sql_count_equals_message_count"] = res["rows_counted_by_sql"] == res["messages"]
            res["ok"] = all(res["checks"].values())
    finally:
        repo.close()
    res.update({"run_id": run_dir.name, "db": db, "engine": "gpu" if gpu.is_gpu else "numpy-simulator"})
    (run_dir / "s1_traffic.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    summary = {"metrics": [{"id": MSGS_METRIC, "value": res["messages"], "unit": "messages",
                            "stat": f"count, seed {a.seed}, {sizes['n_conv']} conversations, {sizes['duration_s']} s"}]}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    engine_note = "CUDA device." if gpu.is_gpu else (
        "numpy simulator behind the API: kernel semantics only, not evidence about a GPU (M14 A1 not met by this run).")
    note = "S1 traffic through the service API on the sim clock; " + engine_note
    runs.finish_run(run_dir, status="OK" if res["ok"] else "FAIL", notes=note)
    for name, passed in res["checks"].items():
        print(f"{'ok  ' if passed else 'FAIL'} {name}")
    print(f"{MSGS_METRIC} {res['messages']} (rows stored {res['rows_stored']}, epochs {res['epochs_passed']}, "
          f"db {db}, engine {res['engine']})")
    print("run dir:", run_dir)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
