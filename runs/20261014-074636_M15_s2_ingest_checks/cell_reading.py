"""Reading of the 12 ingested M15 cells (job 20261014-065041_M15) for the S2 ingest checks.

Everything printed is read from the ingested run dirs; nothing here is a metric of its own
(the S3 metrics and their UNSTABLE marks are computed by S3). Run from the repository root:

    python runs/20261014-074636_M15_s2_ingest_checks/cell_reading.py
"""
from __future__ import annotations

import csv
import glob
import json
import statistics as st

DRIVER = "runs/20261014-013858_M15_e2e_cells"
CONDITIONS = ("ack", "sessions", "ws_sockets", "store", "users_per_conversation", "rate_per_user_s",
              "duration_s", "warmup_s", "drain_s", "poll_ms", "power", "clock")
ENV = ("os", "python", "backend", "runner", "session_id", "gpu", "cuda", "cupy", "driver", "cpu_count")


def spread(a: float, b: float) -> float:
    return abs(a - b) / min(a, b) * 100.0


def main() -> None:
    cells = {}
    for d in sorted(glob.glob("runs/20261014-0[12]*_M15_*_u*_r[12]")):
        s = json.load(open(d + "/summary.json"))
        m = json.load(open(d + "/manifest.json"))
        cells[(s["users"], s["mode"], s["rep"])] = (d, s, m)
    print(f"cells found: {len(cells)} (expected 12)")

    # A1: identical conditions
    cond = {json.dumps([s[k] for k in CONDITIONS], sort_keys=True) for _, s, _ in cells.values()}
    env = {json.dumps([m["env"].get(k) for k in ENV]) for _, _, m in cells.values()}
    sha = {(m["git_sha"], m["dirty"], m["status"], m["gpu_job"].get("job") if isinstance(m.get("gpu_job"), dict)
            else str(m.get("gpu_job"))) for _, _, m in cells.values()}
    slots = {json.dumps(m["params"].get("slots")) for _, _, m in cells.values()}
    print(f"A1 distinct condition sets: {len(cond)}; distinct env sets: {len(env)}; "
          f"distinct (sha, dirty, status, job): {len(sha)}; distinct slots params: {len(slots)}")
    print("   conditions:", cond.pop() if len(cond) == 1 else cond)
    print("   env:", env.pop() if len(env) == 1 else env)
    print("   sha/dirty/status/job:", sha)

    # A2: warm-up
    print("A2 warm-up: counted samples by scheduled time")
    for key in sorted(cells):
        d, s, _ = cells[key]
        rows = list(csv.DictReader(open(d + "/samples.csv")))
        counted = [r for r in rows if r["counted"] in ("1", "True", "true")]
        lo = min(float(r["t_sched_s"]) for r in counted)
        hi = max(float(r["t_sched_s"]) for r in counted)
        print(f"   u{key[0]:<4}{key[1]:<9}r{key[2]} rows {len(rows):5} counted {len(counted):5} "
              f"sched range [{lo:7.2f}, {hi:7.2f}] s  excluded_warmup {s['stats']['excluded_warmup']} "
              f"excluded_after {s['stats']['excluded_after']}")

    # per cell: completion, errors, load of the two processes inside the measured interval
    print("cells: errors, missed epochs, send lag, CPU inside the measured interval (mean % of one core)")
    for key in sorted(cells):
        d, s, _ = cells[key]
        a, b = s["measured_unix"]
        rows = [r for r in csv.DictReader(open(d + "/cpu.csv")) if a <= float(r["ts"]) <= b]
        tel = [r for r in csv.DictReader(open(d + "/telemetry.csv")) if a <= float(r["ts"]) <= b]

        def mean(col: str) -> float:
            v = [float(r[col]) for r in rows if r[col] not in ("", "None")]
            return st.mean(v) if v else float("nan")

        delta = s["service"]["delta"]
        stats = s["stats"]
        print(f"   u{key[0]:<4}{key[1]:<9}r{key[2]} sched {stats['scheduled']:5} acked {stats['acked']:5} "
              f"send_err {stats['errors']} read_req {s['reads']['requests']:6} read_err {s['reads']['errors']} "
              f"readable_missing {stats['readable_missing']} epochs {delta['epochs']} overflow {delta['overflow']} "
              f"missed {delta['missed']} send_lag p50/p99 {stats['send_lag_ms']['p50']:.0f}/"
              f"{stats['send_lag_ms']['p99']:.0f} ms | cpu n {len(rows)} service {mean('service_cpu_pct'):.0f} "
              f"generator {mean('generator_cpu_pct'):.0f} machine {mean('cpu_pct'):.0f} | nvml n {len(tel)}")

    # A3: the two repetitions
    print("A3 repetitions: r1, r2, spread = |r1 - r2| / min (%); gate 15 %")
    for users in (10, 50, 200):
        for mode in ("baseline", "vcloak"):
            s1, s2 = cells[(users, mode, 1)][1]["stats"], cells[(users, mode, 2)][1]["stats"]
            parts = []
            for series in ("ack_ms", "readable_ms"):
                for q in ("p50", "p99"):
                    x, y = s1[series][q], s2[series][q]
                    sp = spread(x, y)
                    parts.append(f"{series}.{q} {x:.1f} {y:.1f} {sp:.1f}%{' OVER' if sp > 15 else ''}")
            parts.append(f"achieved {s1['achieved_msgs_s']:.3f} {s2['achieved_msgs_s']:.3f}")
            print(f"   u{users:<4}{mode:<9}" + " | ".join(parts))


if __name__ == "__main__":
    main()
