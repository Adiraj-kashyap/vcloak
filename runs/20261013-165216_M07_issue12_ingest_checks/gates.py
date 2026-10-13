"""Gate reading of an ingested pipeline run against the M07 run: every value is read from the two summary.json."""
import json, sys
new, old, out = sys.argv[1], sys.argv[2], sys.argv[3]
L = []
def load(r): return json.load(open(f"{r}/summary.json")), json.load(open(f"{r}/manifest.json"))
(sn, mn), (so, mo) = load(new), load(old)
L.append("ISSUE-12 gate reading (generated; nothing here is measured or typed: values are read from summary.json)")
for tag, r, s, m in (("after the fix", new, sn, mn), ("before the fix (M07)", old, so, mo)):
    e = m.get("env", {})
    L.append(f"\n== {tag}: {r}")
    L.append(f"git {m.get('git_sha')}  gpu_job {m.get('gpu_job', {}).get('job_id')}  runner {e.get('runner')}  session {e.get('session_id')}")
    L.append(f"device {s['device']['gpu']}  cuda {s['device']['cuda']}  host cpu {s['host']['cpu']} x{s['host']['cpu_count']}  ram_gb {s['host']['ram_gb']}  timer {s['timer']}")
    L.append(f"oracle mismatches {s['mismatches']}  cv_limit {s['cv_limit']}  unstable configs {len(s['unstable'])} of {len(s['configs'])}: {', '.join(s['unstable'])}")
    L.append("slots | attempt | stable | cv_total | median_total_ms | p99_total_ms | median_device_ms | p99_device_ms | median_host_ms | host_share | clock")
    for c in s["configs"]:
        if c["kind"] != "write_epoch": continue
        for a in c["attempts"]:
            L.append(f"{c['size']} | {a['attempt']} | {a['stable']} | {a['cv']:.4f} | {a['median_ms']:.4f} | {a['p99_ms']:.4f} | "
                     f"{a['device']['median_ms']:.4f} | {a['device']['p99_ms']:.4f} | {a['host']['median_ms']:.4f} | "
                     f"{a['host_share_of_median_total']:.4f} | {a['clock']['before_mhz']}->{a['clock']['after_mhz']} of {a['clock']['max_mhz']} MHz ({a['clock']['status']})")
    L.append("real-time gate (p99 of the last attempt < EPOCH_MS):")
    for g in s["realtime_gate"]:
        L.append(f"  slots {g['slots']}: epoch_ms {g['epoch_ms']}  p99_total_ms {g['p99_total_ms']:.4f}  total {'PASS' if g['pass_total'] else 'FAIL'}  "
                 f"p99_device_ms {g['p99_device_ms']:.4f}  device {'PASS' if g['pass_device'] else 'FAIL'}  unstable {g['unstable']}")
gn = [g for g in sn["realtime_gate"] if g["slots"] == 65536][0]
L.append(f"\nVERDICT at 65536 slots after the fix: whole call {'PASS' if gn['pass_total'] else 'FAIL'}, device part {'PASS' if gn['pass_device'] else 'FAIL'}, "
         f"measurement {'UNSTABLE' if gn['unstable'] else 'stable'}.")
same = (sn['host']['cpu'], sn['host']['cpu_count'], mn['env'].get('runner')) == (so['host']['cpu'], so['host']['cpu_count'], mo['env'].get('runner'))
L.append(f"Same runner and CPU count in both runs: {same}. If False, the host-stage times of the two runs are not a before/after comparison.")
open(out, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
