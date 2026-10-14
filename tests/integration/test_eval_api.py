"""M18 S4: `/v1/eval/attack`, the live order-recovery attack of the Experiments view.

The quick sizes keep these tests short; the full-size run that reproduces the stored M14 number is the S4
check of the session (runs/<...>_M18_s4_checks), not a test. Nothing here measures anything.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from vcloak.cli import build_backend, build_parser
from vcloak.eval import ablation, attack, traffic
from vcloak.gpu.runtime import get_backend
from vcloak.service.app import create_app
from vcloak.storage.repo import SqliteRepo

FORBIDDEN = ("conv", "payload", "digest", "token", "bucket", "seq_enc", "row_id")


def app_client(*, dev: bool) -> TestClient:
    # the backend is always built with the dev key; `dev` is what the routes are told (as in test_web_app)
    a = build_parser().parse_args(["serve", "--store", "sqlite", "--dev"])
    return TestClient(create_app(build_backend(a), dev=dev, web_dir=False))


def wait_done(c: TestClient, timeout_s: float = 240) -> dict[str, Any]:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        s = c.get("/v1/eval/attack").json()
        if s["state"] != "running":
            return s
        time.sleep(0.2)
    raise AssertionError("the attack run did not finish")


def keys_of(x: Any) -> set[str]:
    if isinstance(x, dict):
        return set(x) | set().union(*(keys_of(v) for v in x.values()))
    if isinstance(x, list):
        return set().union(*(keys_of(v) for v in x)) if x else set()
    return set()


def test_refused_without_dev() -> None:
    with app_client(dev=False) as c:
        assert c.get("/v1/eval/attack").status_code == 403
        assert c.post("/v1/eval/attack", json={"layout": "W60"}).status_code == 403


def test_unknown_layout_and_extra_fields_are_refused() -> None:
    with app_client(dev=True) as c:
        assert c.post("/v1/eval/attack", json={"layout": "W7"}).status_code == 422
        assert c.post("/v1/eval/attack", json={"layout": "W60", "seed": 1}).status_code == 422
        assert c.get("/v1/eval/attack").json() == {"state": "idle"}


def test_quick_run_matches_the_same_replay_run_directly() -> None:
    """The endpoint's number is the number of `run_layout` on the same seed, sizes and layout; a second
    start while it runs is refused; nothing that identifies a conversation or a row is served."""
    with app_client(dev=True) as c:
        r = c.post("/v1/eval/attack", json={"layout": "W10", "quick": True})
        assert r.status_code == 202 and r.json()["state"] == "running"
        busy = c.post("/v1/eval/attack", json={"layout": "W60", "quick": True})
        assert busy.status_code == 409 and busy.json()["error"] == "busy"
        s = wait_done(c)
    assert s["state"] == "done", s
    res = s["result"]
    assert res["ok"] and res["quick"] and res["backend"] == "numpy" and res["seed"] == ablation.SEED
    assert res["params"] == {**ablation.QUICK, "rate": ablation.RATE}

    lay = next(x for x in ablation.layouts(quick=True) if x["id"] == "W10")
    direct = ablation.run_layout(SqliteRepo(), get_backend("numpy"), lay, seed=ablation.SEED, **ablation.QUICK)
    assert res["turn_order_accuracy"] == direct["attack"]["turn_order_accuracy"]
    assert res["predicted_turn_accuracy"] == direct["attack"]["predicted_turn_accuracy"]

    smp = res["sample"]
    assert len(smp["turns"]) == 24 and smp["turns_total"] > 24
    rows = smp["round"]["rows"]
    assert rows and sorted(r["rank"] for r in rows) == list(range(1, len(rows) + 1))
    assert not keys_of(res) & set(FORBIDDEN), keys_of(res) & set(FORBIDDEN)


def test_baseline_layout_has_no_prediction() -> None:
    with app_client(dev=True) as c:
        assert c.post("/v1/eval/attack", json={"layout": "BASELINE", "quick": True}).status_code == 202
        s = wait_done(c)
    assert s["state"] == "done" and s["result"]["mode"] == "baseline"
    assert s["result"]["predicted_turn_accuracy"] is None
    assert s["result"]["turn_order_accuracy"] == 1.0  # arrival order: the dump is the order (a property, not a result)


def test_sample_agrees_with_the_attack_on_the_same_dump() -> None:
    """Over all turns, the hits of `sample` give `turn_order_accuracy` of `attack_dump`."""
    lay = next(x for x in ablation.layouts(quick=True) if x["id"] == "W10")
    seen: dict[str, Any] = {}
    store = SqliteRepo()
    events = traffic.burst_events(np.random.default_rng(ablation.SEED), ablation.QUICK["n_conv"],
                                  ablation.QUICK["duration_s"], ablation.RATE)
    res = ablation.run_layout(store, get_backend("numpy"), lay, seed=ablation.SEED, **ablation.QUICK,
                              sample=len(events))
    seen["acc"] = res["attack"]["turn_order_accuracy"]
    turns = res["sample"]["turns"]
    assert len(turns) == res["sample"]["turns_total"]
    assert sum(t["hit"] for t in turns) / len(turns) == seen["acc"]
    assert sum(t["same_round"] for t in turns) / len(turns) == res["attack"]["turns_same_round_frac"]
    assert attack.sample([], {}, 24) == {"turns": [], "turns_total": 0,
                                        "round": {"win": None, "rows_in_round": 0, "rows": []}}

