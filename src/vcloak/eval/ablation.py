"""The order-recovery attack per store layout, on the real stack (M14 S2 + S3), as a library.

`run_layout` replays the bursty traffic of a seed through the service into one empty store, dumps the store in
physical order and runs the attack of the oracle on the dump. `bench/run_security_eval.py --stage attack` runs it
for every layout of `layouts`; the dev endpoint `/v1/eval/attack` of the web app runs it for one (M18 S4). The
same seed, sizes and layout give the same dump, whichever backend computes (numpy or cupy) and whichever store
holds it: the stored M14 numbers are reproduced exactly, not approximately.

The service app is imported here, so the service imports this module lazily (inside the endpoint).
"""
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

import httpx
import numpy as np

from vcloak import config
from vcloak.crypto.client import decrypt_content
from vcloak.eval import attack, traffic
from vcloak.gpu.engine import StoredRow
from vcloak.service.app import VcloakBackend, create_app, dev_master
from vcloak.service.baseline import BaselineBackend
from vcloak.service.models import decode_payload
from vcloak.service.scheduler import SimClock
from vcloak.storage.repo import PgRepo

SEED = 2026
RATE = 0.05  # first messages and pauses per second and conversation (the oracle's rate)
FULL = {"n_conv": 200, "duration_s": 900, "buckets": config.BUCKETS}
QUICK = {"n_conv": 40, "duration_s": 120, "buckets": 16}
WINDOWS_QUICK = (10, 60)
DROP_BATCH = 100
DUMP_COLS = "row_id, bucket, win, seq_enc, payload"  # the fields of StoredRow, in order


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


def layouts(quick: bool) -> list[dict[str, Any]]:
    """The stores the attack is run on: the unprotected baseline, V-cloak with the epoch as the visible
    round (the Review-1 design), and V-cloak with W seconds as the visible round."""
    windows = WINDOWS_QUICK if quick else config.WINDOW_S_ABLATION
    out: list[dict[str, Any]] = [
        {"id": "BASELINE", "mode": "baseline", "visible_round": "window", "window_s": config.WINDOW_S},
        {"id": "EPOCH", "mode": "vcloak", "visible_round": "epoch", "window_s": config.WINDOW_S}]
    out += [{"id": f"W{w}", "mode": "vcloak", "visible_round": "window", "window_s": w} for w in windows]
    return out


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
               cand_k: int = config.CAND_K, inspect: Any = None, sample: int = 0) -> dict[str, Any]:
    """Replay the traffic of `seed` into one layout, dump the store and run the attack on the dump.
    With `read_convs`, that many conversations are first read back through the service (E0).
    `inspect(rows)` may add results computed from the dump. With `sample`, `res["sample"]` is
    `attack.sample` of the dump with that many turns (the Experiments view, M18 S4)."""
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
    if sample and intact:
        res["sample"] = attack.sample(rows, sent.by_digest(), sample)
    if e0 is not None:
        e0["cand_k"] = cand_k
        e0["checks"] = {"every_conversation_in_exact_order": e0["exact_order"] == e0["conversations_checked"],
                        "no_read_failed": not e0["reads_failed"],
                        "cand_k_above_peak_occupancy": cand_k >= res["occupancy"]["peak"]}
        res["e0"] = e0
        checks.update({f"e0_{k}": v for k, v in e0["checks"].items()})
    res["ok"] = all(checks.values())
    return res
