"""ISSUE-25 ingest gates: integrity, void conditions and the reading rules a-e of the issue. Measures nothing."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from vcloak.bench import dudect  # noqa: E402

JOB = "20261012-191630_M08_issue25"
RUNS = {"selftest": "20261012-135342_M08_i25_selftest_quick", "s8": "20261012-135427_M08_dudect_i25_s8",
        "s10": "20261012-145303_M08_dudect_i25_s10", "s11": "20261012-155223_M08_dudect_i25_s11",
        "s12": "20261012-165055_M08_dudect_i25_s12"}
SEEDS = ("s8", "s10", "s11", "s12")
ISSUE17 = "20261012-061420_M08_dudect_issue17_s8"
THR = 4.5
MIN_MEDIAN_MS = 0.050  # ai/GPU_GUIDE.md section 7, rule e of the issue
NULL, AGE, FRESH = "write_epoch_null_st", "write_epoch_age_st", "write_epoch_fresh_st"
out, bad = [], 0


def gate(ok, text, detail=""):
    global bad
    bad += not ok
    out.append(f"    {'PASS' if ok else 'FAIL'} {text}" + (f" - {detail}" if detail else ""))


def note(text):
    out.append(f"    NOTE {text}")


def read(text):
    out.append(f"    READING {text}")


def load(name, file="summary.json"):
    return json.loads((ROOT / "runs" / RUNS[name] / file).read_text(encoding="utf-8"))


res = json.loads((ROOT / "gpujobs/out" / JOB / "result.json").read_text(encoding="utf-8"))
job = json.loads((ROOT / "gpujobs/out" / JOB / "job.json").read_text(encoding="utf-8"))
env = res["env"]
out.append(f"job {JOB} session {env['session_id']} runner {env['runner']} gpu {env['gpu']} driver {env['driver']} "
           f"cupy {env['cupy']} cuda_runtime {env['cuda_runtime']}")
gate(all(c["exit_code"] == 0 for c in res["commands"]), "all commands exit 0", f"{len(res['commands'])} commands")
gate(res["packed_from_git_sha"] == job["git_sha"], "git sha matches pack", job["git_sha"][:7])
gate(res["bundle_sha256"] == job["bundle_sha256"], "bundle sha matches pack")
gate(env["backend"] == "cupy", "backend cupy")
log3 = (ROOT / "gpujobs/out" / JOB / "logs/03_pytest_issue25.txt").read_text(encoding="utf-8").strip().splitlines()[-1]
gate(" passed" in log3 and "failed" not in log3 and "skipped" not in log3, "tests of the diagnostics on the GPU", log3.strip("= "))
for name, d in RUNS.items():
    m = load(name, "manifest.json")
    gate(m["env"]["backend"] == "cupy" and m["gpu_job"]["job_id"] == JOB and m["env"]["session_id"] == env["session_id"],
         f"manifest {d}: cupy, this job, this session", f"status {m['status']}")
i17 = json.loads((ROOT / "runs" / ISSUE17 / "manifest.json").read_text(encoding="utf-8"))["env"]
note(f"the ISSUE-17 job ran in session {i17.get('session_id')} (driver {i17.get('driver', '?')}); this job in "
     f"{env['session_id']} (driver {env['driver']}): two runner sessions, values are not pooled")

st = {t["target"]: t for t in load("selftest")["targets"]}
if "control_leak" in st:
    leak = st["control_leak"]
    gate(leak["verdict"] == "FAIL" and leak["max_abs_t"] > 10 * THR, "planted leak detected in this session (|t| >> 4.5)",
         f"max |t| {leak['max_abs_t']:.4f} at N {leak['n_per_class']} (quick)")
else:
    note(f"the quick self-test has no control_leak target (targets: {', '.join(st)})")
S = {seed: {t["target"]: t for t in load(seed)["targets"]} for seed in SEEDS}
for seed in SEEDS:
    gate(not load(seed)["errors"] and not load(seed, "manifest.json")["quick"] and load(seed)["timer"] == "cupy.cuda.Event",
         f"{seed}: no target error, full N, CUDA events", f"{len(S[seed])} targets")

# every verdict recomputed from the raw data of the bundle; V[(seed, target, series)] = facts of one series
V, clocks = {}, []
for seed in SEEDS:
    d = ROOT / "runs" / RUNS[seed]
    for name, t in S[seed].items():
        raw = np.load(d / f"dudect_{name}_raw.npz")
        times, classes, cal = raw["times_ms"], raw["classes"], raw["calibration_ms"]
        if times.ndim == 1:
            times, cal = times[:, None], cal[:, None]
        n0, n1 = int((classes == 0).sum()), int((classes == 1).sum())
        ck = t["clock"]
        clocks.append((seed, name, ck["before_mhz"], ck["after_mhz"], ck["status"]))
        gate(n0 == n1 == 100000 and t["mismatches"] == 0, f"{seed} {name}: 100000 measurements per class, outputs correct",
             f"r {t['r']}, clock {ck['before_mhz']}->{ck['after_mhz']} MHz {ck['status']}, {t['measure_seconds']:.0f} s")
        gate(len(t["series"]) == times.shape[1], f"{seed} {name}: one raw column per series", f"{times.shape[1]} series")
        for s, sname in enumerate(t["series"]):
            test = dudect.OnlineTTest(dudect.crop_thresholds(cal[:, s]))
            test.update(times[:, s], classes)
            tv = test.t()
            again, at = test.max_abs_t()
            rec = t["series"][sname]
            gate(abs(again - rec["max_abs_t"]) < 1e-6 * max(1.0, again) and (again >= THR) == (rec["verdict"] == "FAIL"),
                 f"{seed} {name}/{sname}: max |t| recomputed from raw.npz equals the summary", f"{again:.4f} {rec['verdict']}")
            half = len(classes) // 2
            halves = []
            for sl in (slice(0, half), slice(half, None)):
                h = dudect.OnlineTTest(dudect.crop_thresholds(cal[:, s]))
                h.update(times[sl, s], classes[sl])
                halves.append(h.max_abs_t()[0])
            over = tv[np.abs(tv) >= THR]
            V[(seed, name, sname)] = {
                "rec": rec, "fail": rec["verdict"] == "FAIL", "sign": "+" if tv[at] > 0 else "-", "over": int(over.size),
                "over_pos": int((over > 0).sum()), "halves": halves, "median0": float(np.median(times[classes == 0, s])),
                "median1": float(np.median(times[classes == 1, s])),
                "below": float(np.median(times[:, s])) < MIN_MEDIAN_MS}

out.append("    TABLE seed target/series verdict max|t| sign_at_max t_raw tests_over(positive) first_half second_half "
           "median0_us median1_us diff_mean_ns rule_e max_at")
for (seed, name, sname), v in V.items():
    r = v["rec"]
    out.append(f"    ROW {seed} {name}/{sname} {r['verdict']} {r['max_abs_t']:.4f} {v['sign']} {r['t_raw']:.3f} "
               f"{v['over']}({v['over_pos']}) {v['halves'][0]:.4f} {v['halves'][1]:.4f} {v['median0'] * 1e3:.2f} "
               f"{v['median1'] * 1e3:.2f} {(r['mean_class1'] - r['mean_class0']) * 1e6:.1f} "
               f"{'BELOW_50US' if v['below'] else 'ok'} [{r['max_at']}]")

# void condition: the full-N control of each run
void = []
for seed in SEEDS:
    c = V[(seed, "control_null", "ms")]
    gate(c["rec"]["verdict"] == "PASS", f"{seed}: full-N control_null PASS (else the run is void)",
         f"max |t| {c['rec']['max_abs_t']:.4f}")
    if c["fail"]:
        void.append(seed)
SERIES = list(S["s8"][NULL]["series"])

# rule e
for sname in SERIES:
    low = [f"{seed} {name} {min(V[(seed, name, sname)]['median0'], V[(seed, name, sname)]['median1']) * 1e3:.2f} us"
           for seed in SEEDS for name in (NULL, AGE, FRESH) if V[(seed, name, sname)]["below"]]
    if low:
        note(f"rule e: {sname} has a median below 50 us in {len(low)} of {len(SEEDS) * 3} runs "
             f"(e.g. {low[0]}): its FAIL or PASS is below the rule")

# rule d: counts per run, the control target of the same run is the gauge
out.append("    COUNT seed target series_FAIL_of_10 failing_series")
for seed in SEEDS:
    for name in (NULL, AGE, FRESH):
        f = [s for s in SERIES if V[(seed, name, s)]["fail"]]
        out.append(f"    COUNT {seed} {name} {len(f)} {','.join(f) or '-'}")

# rule a (H5, transfers)
dev_fail = [(seed, name) for seed in SEEDS for name in (NULL, AGE, FRESH) if V[(seed, name, "device_ms")]["fail"]]
if not dev_fail:
    read("rule a: no device_ms series FAILS in this job, so the rule has no case to decide: H5 is neither supported "
         "nor refuted here")
for seed, name in dev_fail:
    tr = [s for s in ("h2d_ms", "d2h_ms") if V[(seed, name, s)]["fail"]]
    core = V[(seed, name, "core_ms")]
    read(f"rule a: {seed} {name} device_ms FAIL {V[(seed, name, 'device_ms')]['rec']['max_abs_t']:.4f}; transfers failing: "
         f"{','.join(tr) or 'none'}; core_ms {core['rec']['verdict']} {core['rec']['max_abs_t']:.4f}: "
         + ("H5 not supported (core_ms FAILS)" if core["fail"] else "H5 supported" if tr
            else "H5 not decided (no transfer FAILS, core_ms PASSES)"))

# rule b (H6) and rule c (contents)
out.append("    SEEDS series null_st age_st fresh_st (seeds with FAIL and sign of t at the max)")
more, dep = [], []
for sname in SERIES:
    f = {name: [seed for seed in SEEDS if V[(seed, name, sname)]["fail"]] for name in (NULL, AGE, FRESH)}
    cell = {name: ",".join(f"{seed}{V[(seed, name, sname)]['sign']}" for seed in f[name]) or "-" for name in f}
    out.append(f"    SEEDS {sname} {cell[NULL]} {cell[AGE]} {cell[FRESH]}"
               + (" BELOW_50US" if any(V[(seed, n, sname)]["below"] for seed in SEEDS for n in f) else ""))
    for name in (AGE, FRESH):
        if len(f[name]) > len(f[NULL]):
            more.append(f"{name}/{sname} {len(f[name])} vs null {len(f[NULL])}")
    clean = [seed for seed in f[FRESH] if seed not in f[NULL] and seed not in f[AGE]]
    for sign in "+-":
        same = [seed for seed in clean if V[(seed, FRESH, sname)]["sign"] == sign]
        if len(same) >= 2:
            dep.append(f"{sname} ({','.join(same)}, sign {sign})")
read("rule b: " + ("H6 (chance or runner drift) is the reading: no series of age_st or fresh_st FAILS in more seeds than "
                   "the same series of null_st. A reading, not a proof of independence" if not more
                   else "H6 is NOT the reading: " + "; ".join(more)))
read("rule c: " + ("a dependence on the contents is the reading for " + "; ".join(dep) if dep
                   else "the condition is not met for any series (no series of fresh_st FAILS in two seeds with the same "
                        "sign while null_st and age_st PASS there): a dependence on the contents is not the reading"))

# the seed-8 finding of the earlier job
for name in (AGE, FRESH):
    v = V[("s8", name, "device_ms")]
    note(f"seed 8 again: {name}/device_ms {v['rec']['verdict']} {v['rec']['max_abs_t']:.4f} "
         f"(the same call FAILED in job 20261012-113437_M08_issue17 at seed 8; another runner session)")
lo = sorted({(b, a, s) for _, _, b, a, s in clocks})
note("SM clock before->after and status over the 16 targets: " + ", ".join(f"{b}->{a} {s}" for b, a, s in lo[:8])
     + (" ..." if len(lo) > 8 else "") + f"; min {min(c[2] for c in clocks)} MHz, max {max(c[2] for c in clocks)} MHz. "
     "The earlier FAILs ran at 585 MHz: the job cannot set the clock, so that state is "
     + ("covered" if any(c[2] <= 600 for c in clocks) else "NOT covered by this job"))
if void:
    note(f"void runs (control FAIL): {', '.join(void)}")
nf = sum(v["fail"] for v in V.values())
out.append(f"gates: {sum(' PASS ' in x for x in out)} PASS, {bad} FAIL; series FAIL {nf} of {len(V)}")
print("\n".join(out))
sys.exit(1 if bad else 0)
