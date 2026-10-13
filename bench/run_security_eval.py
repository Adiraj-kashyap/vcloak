#!/usr/bin/env python3
"""M14: the security evaluation on the real stack (E0 to E3, anonymity set).

    python bench/run_security_eval.py --stage s1|attack|uniformity|trace|anonymity [--quick] [--seed 2026]
                                      [--store pg|sqlite] [--schema m14_eval] [--backend auto|cupy|numpy] [--out runs]

s1          Replays the bursty traffic of the seed oracle (200 conversations, 900 simulated seconds, rate 0.05/s;
            `--quick`: 40 conversations, 120 s, 16 buckets) through the service API on a simulated clock and
            counts what the store holds afterwards.
attack      S2 + S3. The same replay into every layout (unprotected baseline; V-cloak with the epoch as the
            visible round; V-cloak with W = 1, 10, 60, 300 s; `--quick`: W = 10, 60), each in a schema of its
            own. The store is dumped in physical order and the order-recovery attack of the oracle runs on
            the dump. On the W = 60 layout, 60 conversations are first read back through `POST /v1/read` (E0).
uniformity  S4. Permutations from the device tags and the device sort: chi-square at n = 64 over 20,000 epochs
            against 200 tables of the ideal sampler, Kendall tau band at n = 2^16 over 1,000 epochs.
trace       S5. The comparator trace of the device sort (the launches the driver issued) for five key
            vectors, against the oracle's trace and a merge sort; the launches of `write_epoch`.
anonymity   S6. The traffic of 10, 100 and 1000 users (`--quick`: 10 and 100), two users per conversation,
            replayed into the W = 60 layout, each in a schema of its own. From the dump: the real messages
            per window and per bucket-window (median, 5th percentile, empty cells counted) and the attack.

The app runs in-process with the objects `vcloak serve --dev --clock sim` builds, except that the scheduler
is stepped by the replay (`autorun=False`), so that every arrival falls into the epoch of its simulated time.
With `--store pg` the schemas are dropped first and left in place afterwards. The manifest records the seed,
the store and the backend that executed the kernels. A run on the numpy simulator has the kernel semantics
of the device and is no evidence about a GPU: audit A1 of M14 asks for engine=gpu.

Outputs in the run dir: summary.json and s1_traffic.json | e1_attack.json, attack_table.csv,
e0_restoration.json | e2_uniformity.json | e3_trace.json | s6_anonymity.json, anonymity_table.csv.
Figures are drawn from these files, not here.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
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
from vcloak.crypto.client import PAYLOAD_LEN, decrypt_content  # noqa: E402
from vcloak.eval import anonymity, attack, trace, traffic, uniformity  # noqa: E402
from vcloak.gpu.engine import GpuEngine, StoredRow  # noqa: E402
from vcloak.gpu.keystore import DeviceKeyStore  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402
from vcloak.service.app import VcloakBackend, create_app, dev_master  # noqa: E402
from vcloak.service.baseline import BaselineBackend, PgBaselineStore, SqliteBaselineStore  # noqa: E402
from vcloak.service.models import decode_payload  # noqa: E402
from vcloak.service.scheduler import SimClock  # noqa: E402
from vcloak.storage.repo import PgRepo, SqliteRepo  # noqa: E402

SEED = 2026
RATE = 0.05  # first messages and pauses per second and conversation (the oracle's rate)
FULL = {"n_conv": 200, "duration_s": 900, "buckets": config.BUCKETS}
QUICK = {"n_conv": 40, "duration_s": 120, "buckets": 16}
SCHEMA = "m14_eval"
MSGS_METRIC = "S-TRAFFIC-MSGS"
WINDOWS_QUICK = (10, 60)
E0_LAYOUT = f"W{config.WINDOW_S}"  # the layout whose conversations are read back
READ_CONVS, READ_CONVS_QUICK = 60, 15
UNIFORMITY_FULL = {"n": 64, "reps": 20_000, "calibration": 200, "n_tau": 1 << 16, "epochs_tau": 1000}
UNIFORMITY_QUICK = {"n": 64, "reps": 2000, "calibration": 200, "n_tau": 1 << 12, "epochs_tau": 100}
TRACE_N = 1024
USERS, USERS_QUICK = (10, 100, 1000), (10, 100)  # S6: two users per conversation
DROP_BATCH = 100
DUMP_COLS = "row_id, bucket, win, seq_enc, payload"  # the fields of StoredRow, in order


def drop_schema(store: Any, schema: str) -> None:
    """Drop `schema` and its tables. The tables go first, a hundred at a time: one statement over the
    thousands of partitions of the epoch layout takes more locks than a default server allows.
    `schema` passed the identifier check of the store; the table names come from the catalog."""
    names = [t for (t,) in store.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = %s AND tablename <> 'messages' ORDER BY 1", (schema,))]
    for i in range(0, len(names), DROP_BATCH):
        store.execute("DROP TABLE IF EXISTS " + ", ".join(f'{schema}."{t}"' for t in names[i:i + DROP_BATCH]))
    store.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def dump_epoch_rounds(repo: PgRepo, rounds: int) -> list[StoredRow]:
    """The rows of the epoch layout in the physical order of `PgRepo.dump`, a hundred rounds per statement.
    The bounds are literals: with a parameter the server may switch to a generic plan, which locks every
    partition again (see `drop_schema`)."""
    rows: list[StoredRow] = []
    for lo in range(0, rounds, DROP_BATCH):
        got = repo.execute(f"SELECT {DUMP_COLS} FROM messages WHERE win >= {lo:d} AND win < {lo + DROP_BATCH:d} "
                           "ORDER BY win, ctid")
        rows += [StoredRow(*r) for r in got]
    return rows


def open_repo(store: str, dsn: str | None, schema: str) -> Any:
    if store == "sqlite":
        return SqliteRepo()
    repo = PgRepo(dsn, schema=schema)
    drop_schema(repo, schema)
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


# ── S2 + S3: every layout on the real stack, the attack on its dump, the read-back ─────────────────


def layouts(quick: bool) -> list[dict[str, Any]]:
    """The stores the attack is run on: the unprotected baseline, V-cloak with the epoch as the visible
    round (the Review-1 design), and V-cloak with W seconds as the visible round."""
    windows = WINDOWS_QUICK if quick else config.WINDOW_S_ABLATION
    out: list[dict[str, Any]] = [
        {"id": "BASELINE", "mode": "baseline", "visible_round": "window", "window_s": config.WINDOW_S},
        {"id": "EPOCH", "mode": "vcloak", "visible_round": "epoch", "window_s": config.WINDOW_S}]
    out += [{"id": f"W{w}", "mode": "vcloak", "visible_round": "window", "window_s": w} for w in windows]
    return out


def open_store(layout: dict[str, Any], store: str, dsn: str | None, schema: str) -> Any:
    """The store of one layout, empty: its own schema in PostgreSQL, or an in-memory SQLite database."""
    name = f"{schema}_{layout['id'].lower()}"
    if layout["mode"] == "baseline":
        if store == "sqlite":
            return SqliteBaselineStore()
        base = PgBaselineStore(dsn, schema=name)
        drop_schema(base, name)
        return base
    return open_repo(store, dsn, name)


async def read_back(client: httpx.AsyncClient, sent: traffic.Replay, convs: list[int],
                    n_windows: int) -> dict[str, Any]:
    """E0: read conversations back through `POST /v1/read`, window by window, and compare the decrypted
    messages with what was sent, in order. Every window is asked for, the empty ones too."""
    exact, wrong, failed, messages = 0, [], [], 0
    for c in convs:
        key = traffic.conversation_key(sent.seed, c)
        want = [traffic.message_text(e) for e in sent.events if e.conv == c]
        got: list[bytes] = []
        for win in range(n_windows):
            r = await client.post("/v1/read", json={"conv_token": sent.tokens[c], "win": win})
            if r.status_code != 200:
                failed.append({"conv": c, "win": win, "status": r.status_code})
                continue
            got += [decrypt_content(key, decode_payload(p)) for p in r.json()["payloads_b64"]]
        messages += len(want)
        if got == want:
            exact += 1
        else:
            wrong.append(c)
    return {"conversations_checked": len(convs), "exact_order": exact, "messages_checked": messages,
            "conversations_wrong": wrong, "reads_failed": failed, "reads": len(convs) * n_windows}


def run_layout(store: Any, gpu: Any, layout: dict[str, Any], *, seed: int, n_conv: int, duration_s: int,
               buckets: int, read_convs: int = 0, slots: int = config.SLOTS, epoch_ms: int = config.EPOCH_MS,
               cand_k: int = config.CAND_K, inspect: Any = None) -> dict[str, Any]:
    """Replay the traffic of `seed` into one layout, dump the store and run the attack on the dump.
    With `read_convs`, that many conversations are first read back through the service (E0).
    `inspect(rows)` may add results computed from the dump."""
    events = traffic.burst_events(np.random.default_rng(seed), n_conv, duration_s, RATE)
    clock = SimClock()
    window_s = layout["window_s"]
    if layout["mode"] == "baseline":
        backend: Any = BaselineBackend(store, clock, window_s=window_s, epoch_ms=epoch_ms)
    else:
        backend = VcloakBackend(store, clock, dev_master, gpu=gpu, slots=slots, buckets=buckets, window_s=window_s,
                                epoch_ms=epoch_ms, cand_k=cand_k, visible_round=layout["visible_round"],
                                autorun=False)
    with_messages = sorted({e.conv for e in events})
    picked = sorted(int(c) for c in np.random.default_rng(seed + 1).choice(
        with_messages, size=min(read_convs, len(with_messages)), replace=False)) if read_convs else []

    async def main() -> tuple[traffic.Replay, dict[str, Any], dict[str, Any] | None]:
        app = create_app(backend, web_dir=False)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://vcloak.test") as client:
                sent = await traffic.replay(backend, clock, client, events, seed=seed,
                                            duration_ms=duration_s * 1000, epoch_ms=epoch_ms)
                e0 = await read_back(client, sent, picked, -(-duration_s // window_s) + 1) if picked else None
            sched = getattr(backend, "scheduler", None)
            state: dict[str, Any] = {}
            if sched is not None:
                state = {"epochs_written": sched.epochs, "epoch_errors": sched.errors, "overflow": sched.overflow,
                         "missed": sched.missed, "queued": sched.queued, "windows_rewritten": len(sched.rewrites),
                         "max_rewrites_of_a_window": max(sched.rewrites.values(), default=0),
                         "compute": dict(backend._compute or {})}
            return sent, state, e0

    sent, state, e0 = asyncio.run(main())
    by_rounds = isinstance(store, PgRepo) and layout["visible_round"] == "epoch"
    rows = dump_epoch_rounds(store, sent.epochs) if by_rounds else store.dump()
    payloads = [bytes(r[2]) if isinstance(r, tuple) else bytes(r.payload) for r in rows]
    checks = {"every_post_accepted": not sent.refused,
              "row_count_equals_message_count": len(rows) == len(events),
              "stored_ciphertexts_are_the_sent_ones": Counter(map(traffic.digest, payloads)) == Counter(sent.digests)}
    if state:
        checks.update({"no_epoch_failed": state["epoch_errors"] == 0, "nothing_left_queued": state["queued"] == 0})
        if layout["visible_round"] == "window":
            checks.update({"no_window_left_unshuffled": store.pending_windows() == [],
                           "each_window_rewritten_once": state["max_rewrites_of_a_window"] <= 1})
    intact = checks["stored_ciphertexts_are_the_sent_ones"]
    res: dict[str, Any] = {
        "layout": layout["id"], "mode": layout["mode"], "visible_round": layout["visible_round"],
        "window_s": window_s, "messages": len(events), "rows_stored": len(rows), "epochs_passed": sent.epochs,
        "scheduler": state, "checks": checks,
        "attack": attack.attack_dump(rows, sent.by_digest()) if intact else None,
    }
    if layout["mode"] == "vcloak":
        res["occupancy"] = attack.occupancy(rows)
    if inspect is not None and intact:
        res.update(inspect(rows))
    if e0 is not None:
        e0["cand_k"] = cand_k
        e0["checks"] = {"every_conversation_in_exact_order": e0["exact_order"] == e0["conversations_checked"],
                        "no_read_failed": not e0["reads_failed"],
                        "cand_k_above_peak_occupancy": cand_k >= res["occupancy"]["peak"]}
        res["e0"] = e0
        checks.update({f"e0_{k}": v for k, v in e0["checks"].items()})
    res["ok"] = all(checks.values())
    return res


ATTACK_COLUMNS = ("layout", "mode", "visible_round", "window_s", "rows", "visible_rounds", "tau_global",
                  "tau_within_round", "turn_order_accuracy", "turns_same_round_frac", "predicted_turn_accuracy",
                  "turn_accuracy_same_round", "adjacent_pair_accuracy")


def attack_metrics(results: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    stat = f"seed {seed}, one replay"
    out: list[dict[str, Any]] = []
    for r in results:
        a = r["attack"]
        if a is None:
            continue
        out += [{"id": f"S-TAU-GLOBAL-{r['layout']}", "value": a["tau_global"], "unit": "-", "stat": stat},
                {"id": f"S-TAU-WITHIN-{r['layout']}", "value": a["tau_within_round"], "unit": "-",
                 "stat": f"size-weighted over rounds of 3 rows or more, {stat}"},
                {"id": f"S-TURNACC-{r['layout']}", "value": a["turn_order_accuracy"], "unit": "fraction", "stat": stat},
                {"id": f"S-F-{r['layout']}", "value": a["turns_same_round_frac"], "unit": "fraction", "stat": stat}]
        if "e0" in r:
            e0, occ = r["e0"], r["occupancy"]
            of = f"of {e0['conversations_checked']} conversations, layout {r['layout']}, {stat}"
            out += [{"id": "S-E0-RESTORE", "value": e0["exact_order"], "unit": "conversations", "stat": of},
                    {"id": "S-CANDK", "value": e0["cand_k"], "unit": "rows", "stat": "public parameter"},
                    {"id": "S-OCC-PEAK", "value": occ["peak"], "unit": "rows",
                     "stat": f"max over {occ['bucket_windows']} bucket-windows, layout {r['layout']}, {stat}"},
                    {"id": "S-OCC-MEAN", "value": occ["mean"], "unit": "rows",
                     "stat": f"mean over {occ['bucket_windows']} bucket-windows, layout {r['layout']}, {stat}"}]
    return out


def stage_attack(a: argparse.Namespace, gpu: Any, run_dir: Path, sizes: dict[str, int]) -> tuple[bool, list, str]:
    results, server = [], None
    for layout in layouts(a.quick):
        store = open_store(layout, a.store, a.dsn, a.schema)
        try:
            if a.store == "pg" and server is None:
                server = str(store.execute("SHOW server_version")[0][0])
            res = run_layout(store, gpu, layout, seed=a.seed, **sizes,
                             read_convs=a.read_convs if layout["id"] == E0_LAYOUT else 0)
        except Exception as e:  # noqa: BLE001 - a layout that breaks is recorded; the others still run
            res = {"layout": layout["id"], "mode": layout["mode"], "visible_round": layout["visible_round"],
                   "window_s": layout["window_s"], "rows_stored": None, "attack": None, "ok": False,
                   "checks": {"layout_completed": False}, "error": f"{type(e).__name__}: {e}"[:400]}
        finally:
            store.close()
        results.append(res)
        acc = res["attack"]["turn_order_accuracy"] if res["attack"] else float("nan")
        print(f"{'ok  ' if res['ok'] else 'FAIL'} layout {res['layout']}: {res['rows_stored']} rows, "
              f"turn-order accuracy {acc:.4f}", flush=True)
        for name, passed in res["checks"].items():
            if not passed:
                print(f"     FAIL {name}")
    doc = {"stage": "S2+S3", "seed": a.seed, "db_server_version": server, "layouts": results,
           "params": {**sizes, "rate": RATE, "slots": config.SLOTS, "epoch_ms": config.EPOCH_MS,
                      "cand_k": config.CAND_K}}
    (run_dir / "e1_attack.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    with (run_dir / "attack_table.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(ATTACK_COLUMNS)
        for r in results:
            if r["attack"] is not None:
                w.writerow([r.get(c, r["attack"].get(c)) for c in ATTACK_COLUMNS])
    e0 = next((r["e0"] for r in results if "e0" in r), None)
    if e0 is not None:
        (run_dir / "e0_restoration.json").write_text(json.dumps(e0, indent=2) + "\n", encoding="utf-8")
        print(f"E0: {e0['exact_order']} of {e0['conversations_checked']} conversations in exact order "
              f"({e0['messages_checked']} messages, {e0['reads']} reads)")
    ok = all(r["ok"] for r in results)
    return ok, attack_metrics(results, a.seed), "S2 read-back and S3 attack on the dump of every layout"


# ── S4: uniformity of the device permutations ────────────────────────────────


def device_keys(gpu: Any) -> DeviceKeyStore:
    """The subkeys of the public development key on the device: what the service derives with `--dev`."""
    keys = DeviceKeyStore(gpu)
    keys.load_master(dev_master())
    return keys


def stage_uniformity(a: argparse.Namespace, gpu: Any, run_dir: Path, sizes: dict[str, int]) -> tuple[bool, list, str]:
    p = UNIFORMITY_QUICK if a.quick else UNIFORMITY_FULL
    keys = device_keys(gpu)
    try:
        chi = uniformity.chi2_study(keys, p["n"], p["reps"], calibration=p["calibration"], seed=a.seed)
        band = uniformity.tau_band_study(keys, p["n_tau"], p["epochs_tau"])
    finally:
        keys.zeroize()
    doc = {"stage": "S4", "seed": a.seed, "key": "development key (public)", "params": p, "chi2": chi,
           "tau_band": band}
    (run_dir / "e2_uniformity.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    gates = {**chi["gates"], **band["gates"]}
    for name, passed in gates.items():
        print(f"{'ok  ' if passed else 'FAIL'} {name}")
    ideal = chi["ideal_sampler"]
    print(f"chi2 {chi['chi2']:.1f} (dof {chi['dof']}, p {chi['p_value']:.4f}); ideal sampler range "
          f"{ideal['chi2_min']:.1f} to {ideal['chi2_max']:.1f} over {ideal['tables']} tables")
    print(f"tau band: {band['inside_band']} of {band['epochs']} epochs inside 3 sigma at n {band['n']} "
          f"(binomial 99% bounds {band['binomial_99_bounds']})")
    at = f"n {chi['n']}, {chi['reps']} epochs"
    metrics = [
        {"id": "S-CHI2", "value": chi["chi2"], "unit": "-", "stat": f"corrected statistic, dof {chi['dof']}, {at}"},
        {"id": "S-CHI2-P", "value": chi["p_value"], "unit": "-", "stat": f"p-value, {at}"},
        {"id": "S-CHI2-P-IDEAL", "value": ideal["p_first"], "unit": "-",
         "stat": f"p-value of the first of {ideal['tables']} ideal-sampler tables, seed {a.seed}, {at}"},
        {"id": "S-TAUBAND-PCT", "value": 100 * band["frac_in_band"], "unit": "%",
         "stat": f"epochs with abs(tau) below 3 sigma, n {band['n']}, {band['epochs']} epochs"},
        {"id": "S-TAU-SIGMA-MEAS", "value": band["std_tau"], "unit": "-",
         "stat": f"sample standard deviation of tau, n {band['n']}, {band['epochs']} epochs"}]
    return all(gates.values()), metrics, "S4 uniformity of the permutations from device tags"


# ── S5: comparator trace ─────────────────────────────────────────────────────


def stage_trace(a: argparse.Namespace, gpu: Any, run_dir: Path, sizes: dict[str, int]) -> tuple[bool, list, str]:
    sort = trace.sort_traces(gpu, TRACE_N, a.seed)
    keys = device_keys(gpu)
    try:
        eng = trace.engine_traces(GpuEngine(keys, slots=config.SLOTS, buckets=sizes["buckets"]), PAYLOAD_LEN, a.seed)
    finally:
        keys.zeroize()
    doc = {"stage": "S5", "seed": a.seed, "sort": sort, "write_epoch": eng,
           "note": "the logical trace only: which pairs are compared. Timing is the dudect work of M08."}
    (run_dir / "e3_trace.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    gates = {**sort["gates"], **eng["gates"]}
    for name, passed in gates.items():
        print(f"{'ok  ' if passed else 'FAIL'} {name}")
    print(f"distinct traces over {len(sort['rows'])} inputs at n {sort['n']}: "
          f"device {sort['device_distinct_traces']}, merge sort {sort['merge_sort_distinct_traces']}")
    over = f"over {len(sort['rows'])} inputs, n {sort['n']}"
    metrics = [
        {"id": "S-TRACE-DISTINCT-DEVICE", "value": sort["device_distinct_traces"], "unit": "traces", "stat": over},
        {"id": "S-TRACE-DISTINCT-MERGESORT", "value": sort["merge_sort_distinct_traces"], "unit": "traces",
         "stat": over}]
    return all(gates.values()), metrics, "S5 comparator trace of the device sort and of write_epoch"


# ── S6: anonymity set ────────────────────────────────────────────────────────

ANON_COLUMNS = ("users", "conversations", "messages", "window_median", "window_p5", "window_empty", "windows",
                "bucket_window_median", "bucket_window_p5", "bucket_window_empty", "bucket_windows",
                "bucket_window_peak", "turn_order_accuracy", "turns_same_round_frac", "predicted_turn_accuracy")


def run_users(store: Any, gpu: Any, users: int, *, seed: int, duration_s: int, buckets: int,
              window_s: int = config.WINDOW_S, **kw: Any) -> dict[str, Any]:
    """S6 for one population: `users` users in pairs, replayed into the layout with `window_s` as the
    visible round. The traffic of every population is drawn from a fresh generator of `seed`."""
    if duration_s % window_s:
        raise ValueError("the duration must be a whole number of windows")
    n_conv, n_windows = anonymity.conversations(users), duration_s // window_s
    layout = {"id": f"W{window_s}", "mode": "vcloak", "visible_round": "window", "window_s": window_s}
    res = run_layout(store, gpu, layout, seed=seed, n_conv=n_conv, duration_s=duration_s, buckets=buckets,
                     inspect=lambda rows: {"anonymity": anonymity.anonymity(rows, n_windows, buckets)}, **kw)
    res.setdefault("anonymity", None)
    res.update({"users": users, "conversations": n_conv})
    return res


def anon_row(r: dict[str, Any]) -> dict[str, Any]:
    w, b, a = r["anonymity"]["per_window"], r["anonymity"]["per_bucket_window"], r["attack"]
    return {"users": r["users"], "conversations": r["conversations"], "messages": r["messages"],
            "window_median": w["median"], "window_p5": w["p5"], "window_empty": w["empty"], "windows": w["cells"],
            "bucket_window_median": b["median"], "bucket_window_p5": b["p5"], "bucket_window_empty": b["empty"],
            "bucket_windows": b["cells"], "bucket_window_peak": b["max"],
            "turn_order_accuracy": a["turn_order_accuracy"], "turns_same_round_frac": a["turns_same_round_frac"],
            "predicted_turn_accuracy": a["predicted_turn_accuracy"]}


def anon_metrics(results: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in results:
        if r.get("anonymity") is None or r["attack"] is None:
            continue
        u, lay = r["users"], r["layout"]
        w, b = r["anonymity"]["per_window"], r["anonymity"]["per_bucket_window"]
        stat = f"{u} users in {r['conversations']} conversations, layout {lay}, seed {seed}, one replay"
        over_w = f"over {w['cells']} windows ({w['empty']} empty), {stat}"
        over_b = f"over {b['cells']} bucket-windows ({b['empty']} empty), {stat}"
        out += [{"id": f"S-ANON-MSGS-U{u}", "value": r["messages"], "unit": "messages", "stat": f"count, {stat}"},
                {"id": f"S-ANON-MED-U{u}", "value": w["median"], "unit": "rows", "stat": f"median real rows {over_w}"},
                {"id": f"S-ANON-P5-U{u}", "value": w["p5"], "unit": "rows",
                 "stat": f"5th percentile (linear) of real rows {over_w}"},
                {"id": f"S-ANON-BW-MED-U{u}", "value": b["median"], "unit": "rows",
                 "stat": f"median real rows {over_b}"},
                {"id": f"S-ANON-BW-P5-U{u}", "value": b["p5"], "unit": "rows",
                 "stat": f"5th percentile (linear) of real rows {over_b}"},
                {"id": f"S-ANON-BW-PEAK-U{u}", "value": b["max"], "unit": "rows", "stat": f"max real rows {over_b}"},
                {"id": f"S-TURNACC-{lay}-U{u}", "value": r["attack"]["turn_order_accuracy"], "unit": "fraction",
                 "stat": stat},
                {"id": f"S-F-{lay}-U{u}", "value": r["attack"]["turns_same_round_frac"], "unit": "fraction",
                 "stat": stat}]
    return out


def stage_anonymity(a: argparse.Namespace, gpu: Any, run_dir: Path, sizes: dict[str, int]) -> tuple[bool, list, str]:
    results, server = [], None
    for users in (USERS_QUICK if a.quick else USERS):
        store = open_store({"id": f"u{users}", "mode": "vcloak"}, a.store, a.dsn, a.schema)
        try:
            if a.store == "pg" and server is None:
                server = str(store.execute("SHOW server_version")[0][0])
            res = run_users(store, gpu, users, seed=a.seed, duration_s=sizes["duration_s"], buckets=sizes["buckets"])
            res["cand_k"] = config.CAND_K
            if res["anonymity"] is not None:
                # Not a gate: above CAND_K a read of the fullest bucket-window answers candidate_overflow.
                peak = res["anonymity"]["per_bucket_window"]["max"]
                res["peak_bucket_window_above_cand_k"] = bool(peak > config.CAND_K)
        except Exception as e:  # noqa: BLE001 - a population that breaks is recorded; the others still run
            res = {"users": users, "layout": f"W{config.WINDOW_S}", "rows_stored": None, "attack": None,
                   "anonymity": None, "ok": False, "checks": {"population_completed": False},
                   "error": f"{type(e).__name__}: {e}"[:400]}
        finally:
            store.close()
        results.append(res)
        if res["anonymity"] is not None and res["attack"] is not None:
            row = anon_row(res)
            print(f"{'ok  ' if res['ok'] else 'FAIL'} {users} users: {row['messages']} messages, per window median "
                  f"{row['window_median']:g} p5 {row['window_p5']:g}, per bucket-window median "
                  f"{row['bucket_window_median']:g} p5 {row['bucket_window_p5']:g} peak {row['bucket_window_peak']}, "
                  f"turn-order accuracy {row['turn_order_accuracy']:.4f}", flush=True)
        else:
            print(f"FAIL {users} users: {res.get('error', 'the store does not hold what was sent')}", flush=True)
        for name, passed in res["checks"].items():
            if not passed:
                print(f"     FAIL {name}")
    doc = {"stage": "S6", "seed": a.seed, "db_server_version": server,
           "mapping": "two users per conversation, every user in exactly one (conversations = users / 2)",
           "populations": results,
           "params": {"duration_s": sizes["duration_s"], "buckets": sizes["buckets"], "rate": RATE,
                      "window_s": config.WINDOW_S, "slots": config.SLOTS, "epoch_ms": config.EPOCH_MS,
                      "cand_k": config.CAND_K}}
    (run_dir / "s6_anonymity.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    with (run_dir / "anonymity_table.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ANON_COLUMNS)
        w.writeheader()
        for r in results:
            if r["anonymity"] is not None and r["attack"] is not None:
                w.writerow(anon_row(r))
    ok = all(r["ok"] for r in results)
    return ok, anon_metrics(results, a.seed), "S6 anonymity set: real messages per window and per bucket-window"


STAGES = {"attack": ("security_e0e1", "S3", stage_attack), "uniformity": ("security_e2", "S4", stage_uniformity),
          "trace": ("security_e3", "S5", stage_trace), "anonymity": ("security_anon", "S6", stage_anonymity)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=("s1", *STAGES), required=True)
    ap.add_argument("--quick", action="store_true", help="the oracle's quick sizes")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--store", choices=("pg", "sqlite"), default="pg")
    ap.add_argument("--dsn", default=None, help="PostgreSQL DSN (default: VCLOAK_PG_DSN or the development database)")
    ap.add_argument("--schema", default=SCHEMA)
    ap.add_argument("--backend", choices=config.BACKENDS, default="auto")
    ap.add_argument("--read-convs", type=int, default=None, help="conversations read back for E0 (60; quick: 15)")
    ap.add_argument("--out", default="runs", help="parent directory of the run dir")
    a = ap.parse_args(argv)
    sizes = QUICK if a.quick else FULL
    if a.read_convs is None:
        a.read_convs = READ_CONVS_QUICK if a.quick else READ_CONVS
    gpu = get_backend(a.backend)
    db = "postgres" if a.store == "pg" else "sqlite"
    engine = "gpu" if gpu.is_gpu else "numpy-simulator"
    command = "python bench/run_security_eval.py " + " ".join(argv if argv is not None else sys.argv[1:])
    engine_note = "CUDA device." if gpu.is_gpu else (
        "numpy simulator behind the API: kernel semantics only, not evidence about a GPU (M14 A1 not met by this run).")
    if a.stage != "s1":
        name, step, fn = STAGES[a.stage]
        params = {**sizes, "rate": RATE, "mode": "vcloak", "clock": "sim", "engine": engine}
        if a.stage == "attack":
            params.update({"db": db, "schema": a.schema, "layouts": [x["id"] for x in layouts(a.quick)],
                           "read_convs": a.read_convs})
        if a.stage == "anonymity":
            del params["n_conv"]  # set by the number of users, not by the sizes of the other stages
            params.update({"db": db, "schema": a.schema, "users": list(USERS_QUICK if a.quick else USERS),
                           "users_per_conversation": 2, "layout": f"W{config.WINDOW_S}"})
        run_dir = runs.new_run("M14", name, step=step, owner="Abhishek", command=command.strip(), seed=a.seed,
                               quick=a.quick, root=ROOT, runs_dir=a.out, backend=gpu, params=params)
        ok, metrics, what = fn(a, gpu, run_dir, sizes)
        (run_dir / "summary.json").write_text(json.dumps({"metrics": metrics}, indent=2) + "\n", encoding="utf-8")
        runs.finish_run(run_dir, status="OK" if ok else "FAIL", notes=f"{what}; {engine_note}")
        print(f"engine {engine}" + (f", db {db}" if a.stage in ("attack", "anonymity") else ""))
        print("run dir:", run_dir)
        return 0 if ok else 1
    run_dir = runs.new_run("M14", "security_s1", step="S1", owner="Abhishek", command=command.strip(),
                           seed=a.seed, quick=a.quick, root=ROOT, runs_dir=a.out, backend=gpu,
                           params={**sizes, "rate": RATE, "mode": "vcloak", "db": db, "schema": a.schema,
                                   "clock": "sim", "engine": engine})
    repo = open_repo(a.store, a.dsn, a.schema)
    try:
        res = run_s1(repo, gpu, seed=a.seed, **sizes)
        if a.store == "pg":
            res["rows_counted_by_sql"] = int(repo.execute("SELECT count(*) FROM messages")[0][0])
            res["checks"]["sql_count_equals_message_count"] = res["rows_counted_by_sql"] == res["messages"]
            res["ok"] = all(res["checks"].values())
    finally:
        repo.close()
    res.update({"run_id": run_dir.name, "db": db, "engine": engine})
    (run_dir / "s1_traffic.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    summary = {"metrics": [{"id": MSGS_METRIC, "value": res["messages"], "unit": "messages",
                            "stat": f"count, seed {a.seed}, {sizes['n_conv']} conversations, {sizes['duration_s']} s"}]}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
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
