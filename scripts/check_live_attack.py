#!/usr/bin/env python3
"""M18 S4 check: the live attack of the Experiments view gives the stored number.

    python scripts/check_live_attack.py [--layouts W300,W60,...] [--out runs]

Starts `vcloak serve --dev --sessions --store sqlite` on a loopback port (a real HTTP server), and for each
layout POSTs /v1/eval/attack, polls GET /v1/eval/attack until the run ends, and compares the live
`turn_order_accuracy` with the value web/data/dashboard.json carries for that layout (the index row, full
precision), after checking that seed and sizes are the same. Writes live_attack.json and a table to the run dir.
Exit 1 if any layout fails, differs or is not comparable.

This is a correctness check, not a measurement: the live run computes on the numpy backend; no number is new.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from demo_two_users import LocalServer  # noqa: E402
from vcloak import runs  # noqa: E402
from vcloak.service.evalapi import LAYOUT_IDS  # noqa: E402

DASH = ROOT / "web" / "data" / "dashboard.json"
POLL_S, TIMEOUT_S = 1.0, 900
SIZES = ("n_conv", "duration_s", "buckets", "rate")


def run_one(client: httpx.Client, layout: str) -> dict[str, Any]:
    r = client.post("/v1/eval/attack", json={"layout": layout})
    if r.status_code != 202:
        return {"state": "refused", "status": r.status_code}
    t0 = time.monotonic()
    while time.monotonic() - t0 < TIMEOUT_S:
        s = client.get("/v1/eval/attack").json()
        if s["state"] != "running":
            return s
        time.sleep(POLL_S)
    return {"state": "timeout"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layouts", default=",".join(LAYOUT_IDS))
    ap.add_argument("--out", default=str(ROOT / "runs"))
    ap.add_argument("--owner", default="Abhishek")
    a = ap.parse_args(argv)
    layouts = [x for x in a.layouts.split(",") if x]
    stored = {x["layout"]: x for x in json.loads(DASH.read_text(encoding="utf-8"))["experiments"]["attack"]["layouts"]}

    run_dir = runs.new_run("M18", "s4_live_attack", step="S4", owner=a.owner, runs_dir=a.out, root=ROOT,
                           command="python scripts/check_live_attack.py " + " ".join(argv or sys.argv[1:]),
                           params={"layouts": layouts, "serve": "--dev --sessions --store sqlite",
                                   "compared_with": str(DASH.relative_to(ROOT))})
    server = LocalServer(["--dev", "--store", "sqlite"]).start()
    rows, ok = [], True
    try:
        with httpx.Client(base_url=server.base, timeout=30) as client:
            for lay in layouts:
                s = run_one(client, lay)
                st = stored.get(lay, {})
                res = s.get("result") or {}
                same = (s["state"] == "done" and st.get("value") is not None and res.get("seed") == st.get("seed")
                        and all(res["params"].get(k) == st["params"].get(k) for k in SIZES))
                equal = same and res["turn_order_accuracy"] == st["value"]
                row = {"layout": lay, "state": s["state"], "seconds": s.get("seconds"), "run_ok": res.get("ok"),
                       "comparable": same, "identical": equal, "live": res.get("turn_order_accuracy"),
                       "stored": st.get("value"), "metric_id": st.get("metric_id"), "stored_run": st.get("run"),
                       "stored_backend": st.get("backend"), "stored_runner": st.get("runner"),
                       "live_backend": res.get("backend"), "error": s.get("error")}
                rows.append(row)
                ok &= bool(equal and res.get("ok"))
                mark = "ok  " if equal and res.get("ok") else "FAIL"
                print(f"{mark} {lay}: live {row['live']} stored {row['stored']} "
                      f"({row['metric_id']}, {row['stored_backend']}/{row['stored_runner']}) in {row['seconds']} s",
                      flush=True)
                (run_dir / "live_attack.json").write_text(json.dumps({"layouts": rows}, indent=2) + "\n",
                                                          encoding="utf-8")
    finally:
        server.stop()
    runs.finish_run(run_dir, status="PASS" if ok else "FAIL",
                    notes="correctness check of /v1/eval/attack against the indexed S-TURNACC values; no metric")
    print(f"{'PASS' if ok else 'FAIL'}: {sum(r['identical'] for r in rows)} of {len(rows)} identical -> {run_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
