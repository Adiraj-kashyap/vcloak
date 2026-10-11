"""M07 ingest gates, recomputed from the ingested files of GPU job 20261011-224124_M07."""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

job = Path(sys.argv[1])
runs = Path(sys.argv[2])
out = Path(sys.argv[3])
RK, RC, RX, RP = (runs / d for d in ("20261011-213207_M07_kernel_sweep", "20261011-213731_M07_cpu_baselines",
                                     "20261011-215652_M07_crossover", "20261011-215653_M07_pipeline"))
res = json.loads((job / "result.json").read_text())
jobj = json.loads((job / "job.json").read_text())
logs = {c["name"]: (job / c["log"]).read_text(encoding="utf-8", errors="replace") for c in res["commands"]}
man = {r: json.loads((r / "manifest.json").read_text()) for r in (RK, RC, RX, RP)}
summ = {r: json.loads((r / "summary.json").read_text()) for r in (RK, RC, RX, RP)}
index = (runs.parent / "state" / "METRICS_INDEX.md").read_text(encoding="utf-8")
lines, ok_all = [], True


# Labels use spaces: check_secrets reads a long underscore-joined name as a key-like run.
def gate(name, ok, detail=""):
    global ok_all
    ok_all &= bool(ok)
    lines.append(f"    {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


def note(text):
    lines.append("    NOTE " + text)


def close(a, b, rel=1e-6):
    return abs(a - b) <= rel * max(abs(a), abs(b), 1e-12)


e = res["env"]
lines.append(f"job {res['job_id']} session {e['session_id']} runner {e['runner']} gpu {e['gpu']} driver {e['driver']} "
             f"cupy {e['cupy']} cuda_runtime {e['cuda_runtime']}")
gate("all commands exit 0", all(c["exit_code"] == 0 for c in res["commands"]) and res["overall_exit"] == 0,
     f"{len(res['commands'])} commands")
gate("git sha matches pack", res["packed_from_git_sha"] == jobj["git_sha"], jobj["git_sha"][:7])
gate("bundle sha matches pack", res["bundle_sha256"] == jobj["bundle_sha256"])
gate("backend cupy", e["backend"] == "cupy")
for lg in ("pytest_timing", "pytest_engine_regression"):
    tail = [ln for ln in logs[lg].splitlines() if re.search(r"\d+ passed", ln)][-1].strip(" =")
    gate("no fail/error/skip/xfail: " + lg, not re.search(r"\b(FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", logs[lg]), tail)

# S1: the event timer against the host clock and against the nominal sleep, as printed by the test on the T4
m = re.search(r"events ([\d.]+) ms, host clock ([\d.]+) ms, ratio ([\d.]+), nominal ([\d.]+)", logs["pytest_timing"])
gate("S1 event timer within 10% of the host clock", m and abs(float(m[3]) - 1) <= 0.10, m and f"ratio {m[3]}")
m = re.search(r"events ([\d.]+) ms, nominal ([\d.]+) ms, ratio ([\d.]+)", logs["pytest_timing"])
gate("S1 sleep kernel within 10% of nominal", m and abs(float(m[3]) - 1) <= 0.10, m and f"ratio {m[3]}")

# Provenance of the four run dirs (G2b, A3)
sid = e["session_id"]
for r in (RK, RC, RX, RP):
    mm = man[r]
    gate(f"manifest {r.name}: cupy, this job, this session",
         mm["env"]["backend"] == "cupy" and mm["gpu_job"]["job_id"] == res["job_id"]
         and mm["env"]["session_id"] == sid and mm["git_sha"] == jobj["git_sha"], f"status {mm['status']}")

# S2 kernel sweep
sk = summ[RK]
raw = defaultdict(list)
for row in csv.DictReader((RK / "raw.csv").open(encoding="utf-8")):
    raw[(row["kernel"], int(row["log2n"]), int(row["attempt"]))].append(float(row["elapsed_ms"]))
kernels = ["bitonic_global", "bitonic_fused", "sort_e2e", "chacha_tags", "aead_open", "bucket_prf"]
gate("S2 run dir complete", all((RK / f).exists() for f in ("raw.csv", "summary.json", "telemetry.csv", "manifest.json")))
gate("S2 six kernels x 2^10..2^22", all([p["log2n"] for p in sk["sweeps"][k]] == list(range(10, 23)) for k in kernels))
gate("S2 at least 50 timed runs in every attempt", min(len(v) for v in raw.values()) >= 50,
     f"{len(raw)} attempts, min {min(len(v) for v in raw.values())} runs")
gate("S2 timer is CUDA events", sk["timer"] == "cupy.cuda.Event")
gate("S2 every timed output equals its reference", sk["mismatches"] == 0
     and all(p["mismatches"] == 0 for k in kernels for p in sk["sweeps"][k]))
gate("A5 fused equals global-only at every n", sk["fused_differs_from_global"] == [], "13 sizes")
n_un = n_ok = n_low = 0
bad = []
for k in kernels:
    for p in sk["sweeps"][k]:
        atts = p["attempts"]
        for a in atts:  # the statistics of every attempt are those of its raw rows
            v = raw[(k, p["log2n"], a["attempt"])]
            cv_ok = close(float(np.std(v) / np.mean(v)), a["cv"], 1e-3) or close(float(np.std(v, ddof=1) / np.mean(v)), a["cv"], 1e-3)
            if not (close(float(np.median(v)), a["median_ms"]) and cv_ok):
                bad.append(f"{k}@2^{p['log2n']} attempt {a['attempt']} differs from raw.csv")
        last = atts[-1]
        ok_last = last["cv"] <= sk["cv_limit"] and abs(last["clock"]["relative_change"]) <= 0.15
        if p["unstable"]:
            n_un += 1
            if len(atts) != 2 or ok_last:
                bad.append(f"{k}@2^{p['log2n']} flagged unstable without two failed attempts")
        else:
            n_ok += 1
            n_low += bool(p["low_clock"])
            if not ok_last or not close(p["median_ms"], last["median_ms"]):
                bad.append(f"{k}@2^{p['log2n']} numeric although its last attempt breaks the CV or clock rule")
gate("S2 summary statistics equal raw.csv; CV <= 0.10 and clock change <= 15% for every numeric point",
     not bad, "; ".join(bad[:4]) or f"{n_ok} stable ({n_low} at a LOW clock), {n_un} UNSTABLE of {n_ok + n_un}")
un_ids = [x["id"] for x in sk["metrics"] if x["value"] == "UNSTABLE"]
gate("A4 unstable kernel configurations are indexed as UNSTABLE, with both attempts in raw.csv",
     len(sk["unstable"]) == n_un and all(f"| {i} | UNSTABLE |" in index for i in un_ids),
     f"{n_un} configurations, {len(un_ids)} metric rows")
for k in kernels:
    u = [p["log2n"] for p in sk["sweeps"][k] if p["unstable"]]
    note(f"{k}: UNSTABLE at log2n {u}" if u else f"{k}: no unstable point")
bw = {p["log2n"]: p["bw_pct_of_peak"] for p in sk["sweeps"]["bitonic_global"]}
over = [n for n, v in bw.items() if v > 100]
note(f"K-BITONIC-BW-PCT is above 100% of the theoretical peak at log2n {over}: {bw[over[0]]:.1f}%" if over
     else "K-BITONIC-BW-PCT never above 100%")
per = {p["log2n"]: 1e3 * p["median_ms"] / p["rounds"] for p in sk["sweeps"]["bitonic_global"]}
note("bitonic_global microseconds per launch (median / rounds): " + ", ".join(f"2^{n} {v:.1f}" for n, v in per.items()))
tel = list(csv.DictReader((RK / "telemetry.csv").open(encoding="utf-8")))
clk = [float(r["sm_clock_mhz"]) for r in tel]
pw = [float(r["power_w"]) for r in tel]
thr = sum(int(r["throttle_reasons"]) != 0 for r in tel)
mets = {x["id"]: x["value"] for r in (RK, RC, RX, RP) for x in summ[r]["metrics"]}
gate("TEL medians equal telemetry.csv", close(float(np.median(clk)), mets["TEL-SMCLK-MEDIAN"], 1e-3)
     and close(float(np.median(pw)), mets["TEL-POWER-W-MEDIAN"], 1e-3),
     f"{len(tel)} samples, SM clock median {np.median(clk):.0f} MHz, power median {np.median(pw):.2f} W")
note(f"telemetry: {thr} of {len(tel)} samples have a non-zero throttle-reasons mask (values "
     f"{sorted({int(r['throttle_reasons']) for r in tel})}); temperature max {max(int(r['temperature_c']) for r in tel)} C; "
     f"power limit {tel[0]['power_limit_w']} W")

# S3 CPU baselines
sc = summ[RC]
rawc = defaultdict(list)
for row in csv.DictReader((RC / "raw.csv").open(encoding="utf-8")):
    rawc[(row["baseline"], int(row["log2n"]), int(row["attempt"]))].append(float(row["elapsed_ms"]))
bl = ["oracle_bitonic", "views_bitonic", "numba_bitonic", "lexsort"]
gate("S3 four baselines x 2^10..2^22", all([p["log2n"] for p in sc["sweeps"][b]] == list(range(10, 23)) for b in bl))
few = [f"{b}@2^{n}:{len(v)}" for (b, n, _), v in rawc.items() if len(v) < (10 if n <= 20 else 5)]
gate("S3 at least 10 runs up to 2^20 and 5 above", not few, "; ".join(few) or
     "runs per point: " + str(sorted({len(v) for v in rawc.values()})))
gate("S3 timer is perf_counter_ns", sc["timer"] == "time.perf_counter_ns")
gate("S3 medians equal raw.csv, every output equals its reference, no unstable point",
     all(close(float(np.median(rawc[(b, p["log2n"], len(p["attempts"]))])), p["median_ms"]) and p["mismatches"] == 0
         and p["cv"] <= sc["cv_limit"] for b in bl for p in sc["sweeps"][b]) and sc["unstable"] == [],
     f"max CV {max(p['cv'] for b in bl for p in sc['sweeps'][b]):.3f}")
for b in bl:
    for p in sc["sweeps"][b]:
        if len(p["attempts"]) > 1:
            note(f"{b} at 2^{p['log2n']} was repeated: CV " + ", ".join(f"{a['cv']:.3f}" for a in p["attempts"])
                 + "; the last attempt is the indexed one, both are in raw.csv")
gate("S3 numba measured", sc["numba"].get("numba") is not None, str(sc["numba"]))

# S4 crossover (A3)
sx = summ[RX]
gate("A3 GPU and CPU sweeps come from the session of the crossover", sx["inputs"]["session_id"] == sid
     and man[RK]["env"]["session_id"] == man[RC]["env"]["session_id"] == sid, sid)
gate("A3 GPU series includes the transfers", "H2D" in sx["inputs"]["gpu_series"] and "D2H" in sx["inputs"]["gpu_series"],
     sx["inputs"]["gpu_series"])
gate("A3 shared-runner caveat recorded", "shared" in sx["caveat"] and "shared" in man[RX]["notes"])
e2e = {p["log2n"]: p for p in sk["sweeps"]["sort_e2e"]}
obl = {n: min((sc["sweeps"][b][n - 10]["median_ms"], b) for b in sc["oblivious"]) for n in range(10, 23)}
okx = all(close(t["gpu_ms"], e2e[t["log2n"]]["attempts"][-1]["median_ms"]) and close(t["cpu_ms"], obl[t["log2n"]][0])
          and t["cpu_baseline"] == obl[t["log2n"]][1] and close(t["speedup"], t["cpu_ms"] / t["gpu_ms"]) for t in sx["table"])
gate("S4 table recomputed from the two sweeps (best oblivious CPU baseline per n)", okx,
     "best baseline: " + ", ".join(sorted({t["cpu_baseline"] for t in sx["table"]})))
tb = {t["log2n"]: t for t in sx["table"]}
gate("S4 summary.json has n* and the speed-ups at 2^16 and 2^20",
     "crossover" in sx and close(mets["X-SPEEDUP-2^16"], tb[16]["speedup"], 1e-4)
     and close(mets["X-SPEEDUP-2^20"], tb[20]["speedup"], 1e-4),
     f"n* {sx['crossover']['kind']} {sx['crossover']['n']} (unstable input: {sx['crossover']['unstable']}), "
     f"x{mets['X-SPEEDUP-2^16']} at 2^16, x{mets['X-SPEEDUP-2^20']} at 2^20")
slow = min(sx["table"], key=lambda t: t["speedup"])
gate("S4 the GPU is faster at every compared n", all(t["gpu_faster"] for t in sx["table"]),
     f"smallest speed-up x{slow['speedup']:.2f} at 2^{slow['log2n']}")
note("X-CROSSOVER-N is UNSTABLE: sort_e2e at 2^10 has CV " + ", ".join(f"{a['cv']:.3f}" for a in e2e[10]["attempts"]))

# S5 pipeline
sp = summ[RP]
rawp = defaultdict(list)
for row in csv.DictReader((RP / "raw.csv").open(encoding="utf-8")):
    rawp[(row["kind"], int(row["size"]), int(row["attempt"]))].append({k: float(v) for k, v in row.items() if k.endswith("_ms")})
STAGES = ("h2d", "tags", "sort", "compact", "d2h", "seal", "bucket", "open", "host")
gap = max(abs(sum(r[s + "_ms"] for s in STAGES) - r["total_ms"]) / r["total_ms"] for v in rawp.values() for r in v)
gate("S5 200 timed calls in every attempt", min(len(v) for v in rawp.values()) >= 200, f"{len(rawp)} attempts")
gate("S5 stages add up to the total in every timed call", gap < 1e-5, f"worst relative gap {gap:.2e}")
gate("S5 every call equals the oracle", sp["mismatches"] == 0 and all(c["mismatches"] == 0 for c in sp["configs"]),
     f"{len(sp['configs'])} configurations")
dev = [s for s in STAGES if s != "host"]
okg = True
for g in sp["realtime_gate"]:
    att = max(a for (kd, sz, a) in rawp if kd == "write_epoch" and sz == g["slots"])
    v = rawp[("write_epoch", g["slots"], att)]
    p99t = float(np.percentile([r["total_ms"] for r in v], 99))
    p99d = float(np.percentile([sum(r[s + "_ms"] for s in dev) for r in v], 99))
    okg &= close(p99t, g["p99_total_ms"], 1e-6) and close(p99d, g["p99_device_ms"], 1e-6) \
        and g["pass_total"] == (p99t < g["epoch_ms"]) and g["pass_device"] == (p99d < g["epoch_ms"])
    note(f"real-time gate SLOTS {g['slots']:>5}: p99 total {p99t:8.3f} ms {'PASS' if g['pass_total'] else 'FAIL'}, "
         f"p99 device {p99d:7.3f} ms {'PASS' if g['pass_device'] else 'FAIL'}, host median {g['median_host_ms']:.3f} ms"
         f"{', UNSTABLE' if g['unstable'] else ''} (EPOCH_MS {g['epoch_ms']})")
gate("S5 real-time gate evaluated and recorded; p99 recomputed from raw.csv", okg and len(sp["realtime_gate"]) == 5,
     "whole call misses the budget at SLOTS " + str([g["slots"] for g in sp["realtime_gate"] if not g["pass_total"]])
     + "; device part misses it at " + str([g["slots"] for g in sp["realtime_gate"] if not g["pass_device"]]))
unp = [x["id"] for x in sp["metrics"] if x["value"] == "UNSTABLE"]
gate("A4 unstable pipeline configurations are indexed as UNSTABLE", all(f"| {i} | UNSTABLE |" in index for i in unp)
     and len(sp["unstable"]) == 3, f"{len(sp['unstable'])} configurations, {len(unp)} metric rows")
gate("host profile present", (RP / "host_profile.txt").stat().st_size > 0)

m07 = [ln for ln in index.splitlines() if "| M07 |" in ln]
gate("every metric of the four summaries is indexed", len(m07) == sum(len(summ[r]["metrics"]) for r in summ),
     f"{len(m07)} rows, {sum('| UNSTABLE |' in ln for ln in m07)} of them UNSTABLE")
lines.append(f"RESULT: {'PASS' if ok_all else 'FAIL'}")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(ln for ln in lines if " FAIL " in ln[:10] or ln.startswith(("RESULT", "job"))))
sys.exit(0 if ok_all else 1)
