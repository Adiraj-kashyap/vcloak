"""What the two local correctness cells of M15 S1 show about the generator. Read from the run dirs; these are
numpy runs and no value printed here is a performance result or an index row.

    python runs/20261014-015940_M15_s1_checks/read_cells.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CELLS = ("20261014-015841_M15_e2e_baseline_u10", "20261014-015857_M15_e2e_vcloak_u10")


def main() -> int:
    ok, scheds = True, []
    for name in CELLS:
        d = ROOT / "runs" / name
        s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        rows = list(csv.DictReader((d / "samples.csv").open(encoding="utf-8")))
        st = s["stats"]
        counted = [r for r in rows if r["counted"] == "1"]
        in_warmup = [r for r in rows if float(r["t_sched_s"]) < s["warmup_s"]]
        scheds.append([(r["user"], r["t_sched_s"]) for r in rows])
        print(f"{name}: status {m['status']} backend {m['env']['backend']} mode {s['mode']} ack {s['ack']} "
              f"sessions {s['sessions']} ws_sockets {s['ws_sockets']} metrics offered {len(s['metrics'])}")
        print(f"  rows {len(rows)}  counted {len(counted)}  scheduled in warm-up {len(in_warmup)} "
              f"(counted among them: {sum(r['counted'] == '1' for r in in_warmup)})  acked {st['acked']}  "
              f"errors {st['errors']}  readable missing {st['readable_missing']}  "
              f"epochs {s['service']['delta']['epochs']}")
        ok &= m["status"] == "OK" and m["env"]["backend"] == "numpy" and s["metrics"] == []
        ok &= len(counted) == st["scheduled"] == st["acked"] and not any(r["counted"] == "1" for r in in_warmup)
        ok &= st["readable_missing"] == 0 and (s["service"]["delta"]["epochs"] > 0) == (s["mode"] == "vcloak")
    same = scheds[0] == scheds[1]
    print(f"GATE both modes got the same schedule (user, scheduled time): {'PASS' if same else 'FAIL'}")
    print(f"GATE every counted send acknowledged and read back, warm-up excluded, no metric offered: "
          f"{'PASS' if ok else 'FAIL'}")
    return 0 if ok and same else 1


if __name__ == "__main__":
    raise SystemExit(main())
