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
go = [g for g in so["realtime_gate"] if g["slots"] == 65536][0]
def verdict(g):
    if g["unstable"]: return "NO VERDICT (UNSTABLE on every attempt: gpu-bench rule 10, the attempts above are not values)"
    return f"whole call {'PASS' if g['pass_total'] else 'FAIL'}, device part {'PASS' if g['pass_device'] else 'FAIL'} (stable)"
L.append("")
L.append(f"VERDICT at 65536 slots after the fix: {verdict(gn)}")
L.append(f"VERDICT at 65536 slots before the fix: {verdict(go)}")
keys = ("runner", "cuda", "driver", "cupy", "python", "os")
plat = {k: (mn["env"].get(k), mo["env"].get(k)) for k in keys}
plat["cpu"] = (sn["host"]["cpu"], so["host"]["cpu"]); plat["cpu_count"] = (sn["host"]["cpu_count"], so["host"]["cpu_count"])
L.append("platform, after | before (ADR-024):")
for k, (x, y) in plat.items(): L.append(f"  {k}: {x} | {y}  {'same' if x == y else 'DIFFERENT'}")
same = all(x == y for x, y in plat.values())
L.append(f"Same platform and image in both runs: {same}.")
valid = same and not gn["unstable"] and not go["unstable"]
L.append(f"Before/after comparison of write_epoch at 65536 slots: {'valid' if valid else 'NOT_MEASURED (one side is UNSTABLE or the platforms differ)'}")
stable = [f"{c['kind']}@{c['size']}" for c in sn["configs"] if f"{c['kind']}@{c['size']}" not in sn["unstable"]]
L.append(f"stable configurations of the new run ({len(stable)} of {len(sn['configs'])}): {', '.join(stable)}")
open(out, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
