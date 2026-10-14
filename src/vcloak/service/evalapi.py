"""The live order-recovery attack of the Experiments view (M18 S4): `/v1/eval/attack`, dev only.

The store the service is running cannot be scored: the server never knows the arrival order or the
conversation of a row (that is the point), so an attack on it has nothing to be compared with. The endpoint
therefore does what M14 did, live: it replays the bursty traffic of the M14 seed through a second service
into a new, empty in-memory store of the chosen layout, dumps that store in physical order and runs the
attack of the oracle on the dump (`vcloak.eval.ablation.run_layout`). Ground truth stays in the replay.

- `POST /v1/eval/attack {"layout": "W300"}` starts one run in a thread of its own and answers 202; 409 while
  a run is going, 403 without `--dev`. `"quick": true` uses the quick sizes of M14 (for tests; a quick
  result is not comparable with a stored one).
- `GET /v1/eval/attack` says how the last run stands: `idle`, `running` (with the seconds so far), `done`
  (with the result) or `failed` (with the type of the error, never its text).

The run computes on the numpy backend, whatever the service runs on: the service's engine belongs to one
thread (ADR-015), and the M14 attack numbers are the same on both backends (the index has them from both).
Nothing here is a measurement: no timing is reported as a metric, and nothing is written to disk.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

LAYOUT_IDS = ("BASELINE", "EPOCH", "W1", "W10", "W60", "W300")
NO_STORE = {"Cache-Control": "no-store"}
SAMPLE = 24  # turns the page animates


class AttackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layout: Literal["BASELINE", "EPOCH", "W1", "W10", "W60", "W300"]
    quick: bool = False


def run_attack(layout_id: str, quick: bool) -> dict[str, Any]:
    """One layout of the M14 attack on a fresh in-memory store; what the page shows of it."""
    from vcloak.eval import ablation  # the service app is imported there: lazily
    from vcloak.gpu.runtime import get_backend
    from vcloak.service.baseline import SqliteBaselineStore
    from vcloak.storage.repo import SqliteRepo

    sizes = ablation.QUICK if quick else ablation.FULL
    layout = next(x for x in ablation.layouts(quick=False) + ablation.layouts(quick=True) if x["id"] == layout_id)
    store = SqliteBaselineStore() if layout["mode"] == "baseline" else SqliteRepo()
    res = ablation.run_layout(store, get_backend("numpy"), layout, seed=ablation.SEED, **sizes, sample=SAMPLE)
    a = res["attack"] or {}
    out = {
        "layout": layout_id, "mode": layout["mode"], "visible_round": layout["visible_round"],
        "window_s": layout["window_s"], "seed": ablation.SEED, "quick": quick,
        "params": {**sizes, "rate": ablation.RATE},
        "backend": "numpy", "store": "sqlite, in memory, new for this run",
        "messages": res["messages"], "rows": res["rows_stored"], "ok": res["ok"], "checks": res["checks"],
        "turn_order_accuracy": a.get("turn_order_accuracy"),
        "predicted_turn_accuracy": a.get("predicted_turn_accuracy") if layout["mode"] == "vcloak" else None,
        "turns_same_round_frac": a.get("turns_same_round_frac"),
        "visible_rounds": a.get("visible_rounds"),
        "sample": res.get("sample"),
    }
    return out


class AttackRunner:
    """At most one run at a time; the state of the last one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"state": "idle"}
        self._t0 = 0.0

    def state(self) -> dict[str, Any]:
        with self._lock:
            s = dict(self._state)
            if s["state"] == "running":
                s["elapsed_s"] = round(time.monotonic() - self._t0, 1)
            return s

    def start(self, layout: str, quick: bool) -> bool:
        with self._lock:
            if self._state["state"] == "running":
                return False
            self._t0 = time.monotonic()
            self._state = {"state": "running", "layout": layout, "quick": quick}
        threading.Thread(target=self._run, args=(layout, quick), name="eval-attack", daemon=True).start()
        return True

    def _run(self, layout: str, quick: bool) -> None:
        try:
            result = run_attack(layout, quick)
            done = {"state": "done", "layout": layout, "quick": quick, "result": result}
        except Exception as e:  # noqa: BLE001 - the page is told the type only, never the text
            done = {"state": "failed", "layout": layout, "quick": quick, "error": type(e).__name__}
        with self._lock:
            done["seconds"] = round(time.monotonic() - self._t0, 1)
            self._state = done


def add_eval_routes(app: FastAPI, *, dev: bool) -> None:
    runner = AttackRunner() if dev else None

    @app.get("/v1/eval/attack")
    async def attack_state() -> JSONResponse:
        if runner is None:
            return JSONResponse({"error": "dev_only"}, status_code=403, headers=NO_STORE)
        return JSONResponse(runner.state(), headers=NO_STORE)

    @app.post("/v1/eval/attack")
    async def attack_start(body: AttackIn) -> JSONResponse:
        if runner is None:
            return JSONResponse({"error": "dev_only"}, status_code=403, headers=NO_STORE)
        if not runner.start(body.layout, body.quick):
            return JSONResponse({"error": "busy", **runner.state()}, status_code=409, headers=NO_STORE)
        return JSONResponse(runner.state(), status_code=202, headers=NO_STORE)
