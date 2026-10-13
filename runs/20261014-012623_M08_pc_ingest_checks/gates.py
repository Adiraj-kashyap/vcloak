"""Reading of the two PC runner results (jobs 20261013-224820_M00 and 20261013-224820_M08_ncu) against the closing
condition of ISSUE-18: counters that carry values and a planted-leak control that shows divergence.
Every value printed here is read from the ingested run dirs; nothing is typed in.

    python runs/20261014-012623_M08_pc_ingest_checks/gates.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NCU = ROOT / "runs" / "20261014-003929_M08_ncu"
PROBE = ROOT / "runs" / "20261014-001653_M00_gpu_probe"
JOBS = ("20261013-224820_M00", "20261013-224820_M08_ncu")
NM = "NOT_MEASURED"


def main() -> int:
    ok = True
    for job in JOBS:
        res = json.loads((ROOT / "gpujobs" / "out" / job / "result.json").read_text(encoding="utf-8"))
        print(f"job {job}: overall exit {res.get('exit_code', res.get('overall_exit'))}")
        for c in res.get("commands", []):
            print(f"  {c.get('name')}: exit {c.get('exit_code')}{' (optional)' if c.get('optional') else ''}")
            if c.get("exit_code") and not c.get("optional"):
                ok = False

    for d in (PROBE, NCU):
        env = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        e = env["env"]
        print(f"{d.name}: status {env['status']} git {env['git_sha'][:7]} dirty {env['dirty']} runner {e['runner']} "
              f"gpu {e['gpu']} cc {e['cc']} driver {e['driver']} cuda {e['cuda']} cupy {e['cupy']} "
              f"os {e['os']} cpu_count {e.get('cpu_count')}")
        ok &= env["status"] == "OK" and e["backend"] == "cupy" and e["runner"].startswith("pc-")

    s = json.loads((NCU / "summary.json").read_text(encoding="utf-8"))
    print(f"ncu: {s['ncu_version'].splitlines()[-1]}; reason {s['reason']}; rows {s['rows']}; "
          f"{len(s['branch_metrics_queried'])} branch metric names queried")
    measured = [m for m in s["metrics"] if str(m["value"]) != NM]
    print(f"metrics measured: {len(measured)} of {len(s['metrics'])}")
    for m in s["metrics"]:
        print(f"  {m['id']}: {m['value']} {m['unit']} ({m['note']})")
    c = s["control"]
    print(f"control {c['kernel']}: divergent {c['divergent']} uniform {c['uniform']} efficiency {c['efficiency_pct']} "
          f"launches {c['launches']} divergent_seen {c['divergent_seen']}")
    print("per kernel (divergent / uniform / launches):")
    for k, v in s["per_kernel"].items():
        flag = "   <- no branch target counted at all" if not v["uniform"] and not v["divergent"] else ""
        print(f"  {k}: {v['divergent']} / {v['uniform']} / {v['launches']}{flag}")

    g1 = s["reason"] is None and len(measured) > 0
    g2 = bool(c["divergent_seen"]) and c["divergent"] > 0
    g3 = all(m["value"] == 0.0 for m in s["metrics"] if "DIVERGENT" in m["id"])
    print(f"GATE counters carry values: {'PASS' if g1 else 'FAIL'}")
    print(f"GATE planted-leak control shows divergence: {'PASS' if g2 else 'FAIL'}")
    print(f"GATE the four audited kernels report 0 divergent: {'PASS' if g3 else 'FAIL'}")
    p = json.loads((PROBE / "summary.json").read_text(encoding="utf-8"))
    print("probe summary keys:", ", ".join(sorted(p)))
    ok &= g1 and g2 and g3
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
