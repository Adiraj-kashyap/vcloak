"""ISSUE-25 ingest gates of the kernel-only job: integrity and the reading rules f to l of the issue. Measures nothing."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from vcloak.bench import dudect  # noqa: E402

JOB = "20261013-005946_M08_issue25k"
RUNS = {"selftest": "20261013-022000_M08_i25k_selftest_quick", "s8": "20261013-022124_M08_dudect_i25k_s8",
        "s10": "20261013-024742_M08_dudect_i25k_s10"}
SEEDS = ("s8", "s10")
KERNELS = ("tags", "compact")
THR = 4.5
MAX_FLAGGED = 0.05  # rule f
MIN_MEDIAN_MS = 0.050  # ai/GPU_GUIDE.md section 7
out, bad = [], 0


def gate(ok, text, detail=""):
    global bad
    bad += not ok
    out.append(f"    {'PASS' if ok else 'FAIL'} {text}" + (f" - {detail}" if detail else ""))
    return bool(ok)


def note(text):
    out.append(f"    NOTE {text}")


def read(text):
    out.append(f"    READING {text}")


def load(name, file="summary.json"):
    return json.loads((ROOT / "runs" / RUNS[name] / file).read_text(encoding="utf-8"))


def maxt(times, classes, cal):
    test = dudect.OnlineTTest(dudect.crop_thresholds(cal))
    test.update(times, classes)
    m, at = test.max_abs_t()
    return m, at, test.t()


res = json.loads((ROOT / "gpujobs/out" / JOB / "result.json").read_text(encoding="utf-8"))
job = json.loads((ROOT / "gpujobs/out" / JOB / "job.json").read_text(encoding="utf-8"))
env = res["env"]
out.append(f"job {JOB} session {env['session_id']} runner {env['runner']} gpu {env['gpu']} driver {env['driver']} "
           f"cupy {env['cupy']} cuda_runtime {env['cuda_runtime']}")
failed = [c for c in res["commands"] if c["exit_code"] != 0]
out.append("    COMMANDS " + ", ".join(f"{c['name']}={c['exit_code']}" for c in res["commands"]))
gate(all(c["name"] == "clock_reset" for c in failed), "every command exits 0 except clock_reset",
     f"{len(res['commands'])} commands, non-zero: {', '.join(c['name'] + ' ' + str(c['exit_code']) for c in failed) or 'none'}")
gate(res["packed_from_git_sha"] == job["git_sha"], "git sha matches pack", job["git_sha"][:7])
gate(res["bundle_sha256"] == job["bundle_sha256"], "bundle sha matches pack")
gate(env["backend"] == "cupy", "backend cupy")
log4 = (ROOT / "gpujobs/out" / JOB / "logs/04_pytest_issue25k.txt").read_text(encoding="utf-8").strip().splitlines()[-1]
gate(" passed" in log4 and "failed" not in log4 and "skipped" not in log4, "tests of the kernel-only targets on the GPU",
     log4.strip("= "))
for name, d in RUNS.items():
    m = load(name, "manifest.json")
    gate(m["env"]["backend"] == "cupy" and m["gpu_job"]["job_id"] == JOB and m["env"]["session_id"] == env["session_id"],
         f"manifest {d}: cupy, this job, this session", f"status {m['status']}")

# rule k: the lock
locks = {name: load(name)["clock_lock"] for name in RUNS}
reset = (ROOT / "gpujobs/out" / JOB / "logs/08_clock_reset.txt").read_text(encoding="utf-8").strip().splitlines()[0]
for name, lk in locks.items():
    note(f"{name}: clock lock attempted {lk['attempted']} accepted {lk['accepted']} ({lk['command']}, returncode "
         f"{lk['returncode']}: {lk['output'].strip().splitlines()[0]})")
refused = all(lk["attempted"] and not lk["accepted"] for lk in locks.values())
gate(refused, "rule k: the lock was refused in every run, so clock_reset had nothing to reset; its exit 4 is the same refusal",
     reset)

# the self-test
st = {t["target"]: t for t in load("selftest")["targets"]}
leak, leakq, stnull = st["control_leak"], st["control_leak_q"], st["control_null"]
gate(leak["verdict"] == "FAIL" and leak["max_abs_t"] > 10 * THR, "planted leak detected, open window (control_leak)",
     f"max |t| {leak['max_abs_t']:.4f} at N {leak['n_per_class']} (quick)")
f_leakq = gate(leakq["verdict"] == "FAIL" and leakq["max_abs_t"] > 10 * THR, "rule f(1): control_leak_q FAILS",
               f"max |t| {leakq['max_abs_t']:.4f} at N {leakq['n_per_class']} (quick), r {leakq['r']}")
gate(stnull["verdict"] == "PASS", "self-test control_null PASS", f"max |t| {stnull['max_abs_t']:.4f}")
raw = np.load(ROOT / "runs" / RUNS["selftest"] / "dudect_control_leak_q_raw.npz")
tq, cq, qq, kq = raw["times_ms"][:, 0], raw["classes"], raw["queued"], raw["clocks_mhz"]
pq = leakq["per_sample"]
note(f"control_leak_q: {int(qq.sum())} of {qq.size} measurements were queued behind the blocker ({pq['unqueued']} unqueued, "
     f"{pq['off_clock']} off the clock, {pq['flagged']} flagged = {100 * pq['flagged'] / pq['measurements']:.2f}%); blocker "
     f"{leakq['params']['blocker_blocks']} blocks, fitted while the SM clock was {leakq['clock']['before_mhz']} MHz, the "
     f"measuring ran at {pq['steady_clock_mhz']} MHz (clock histogram {pq['clock_histogram_mhz']})")
note("so the FAIL of control_leak_q is that of a window that was NOT queued in almost every measurement: by itself it does "
     "not show that the queued window detects the planted leak")
n0q, n1q = int((qq & (cq == 0)).sum()), int((qq & (cq == 1)).sum())
x0, x1 = tq[qq & (cq == 0)], tq[qq & (cq == 1)]
tw = float(dudect.welch_t(n0q, x0.mean(), ((x0 - x0.mean()) ** 2).sum(), n1q, x1.mean(), ((x1 - x1.mean()) ** 2).sum()))
u0, u1 = tq[~qq & (cq == 0)], tq[~qq & (cq == 1)]
leak_ns = (leakq["series"]["ms"]["mean_class1"] - leakq["series"]["ms"]["mean_class0"]) * 1e6
q_power = gate(min(n0q, n1q) >= 30 and abs(tw) >= THR,
               "the queued measurements of control_leak_q alone detect the planted leak (raw Welch t, no crops)",
               f"t {tw:.4f}, {n0q} and {n1q} per class, means {x0.mean() * 1e3:.3f} and {x1.mean() * 1e3:.3f} us "
               f"(unqueued: {u0.mean() * 1e3:.3f} and {u1.mean() * 1e3:.3f} us), clocks of the queued ones: "
               f"{dict(zip(*[a.tolist() for a in np.unique(kq[qq], return_counts=True)]))}, positions "
               f"{int(np.where(qq)[0].min())} to {int(np.where(qq)[0].max())} of {qq.size}")
note(f"planted difference of the whole control_leak_q series: {leak_ns:.0f} ns per window of r {leakq['r']}")

# the measuring runs: every verdict recomputed from the raw data
S = {seed: {t["target"]: t for t in load(seed)["targets"]} for seed in SEEDS}
V = {}
for seed in SEEDS:
    s = load(seed)
    gate(not s["errors"] and not load(seed, "manifest.json")["quick"] and s["timer"] == "cupy.cuda.Event",
         f"{seed}: no target error, full N, CUDA events", f"{len(S[seed])} targets: {', '.join(S[seed])}")
    d = ROOT / "runs" / RUNS[seed]
    for name, t in S[seed].items():
        raw = np.load(d / f"dudect_{name}_raw.npz")
        times, classes, cal = raw["times_ms"][:, 0], raw["classes"], raw["calibration_ms"][:, 0]
        rec = t["series"]["ms"]
        n0, n1 = int((classes == 0).sum()), int((classes == 1).sum())
        gate(n0 == n1 == 100000 and t["mismatches"] == 0, f"{seed} {name}: 100000 measurements per class, outputs correct",
             f"r {t['r']}, {t['measure_seconds']:.0f} s")
        again, at, tv = maxt(times, classes, cal)
        gate(abs(again - rec["max_abs_t"]) < 1e-6 * max(1.0, again) and (again >= THR) == (rec["verdict"] == "FAIL"),
             f"{seed} {name}: max |t| recomputed from raw.npz equals the summary", f"{again:.4f} {rec['verdict']}")
        half = classes.size // 2
        halves = [maxt(times[sl], classes[sl], cal)[0] for sl in (slice(0, half), slice(half, None))]
        v = {"rec": rec, "t": t, "sign": "+" if tv[at] > 0 else "-", "halves": halves, "over": int((np.abs(tv) >= THR).sum()),
             "median": float(np.median(times)), "flag": None}
        sd = float(np.sqrt((rec["std_class0"] ** 2 + rec["std_class1"] ** 2) / 2))
        v["detect_ns"] = THR * sd * np.sqrt(2.0 / n0) * 1e6  # raw mean difference that gives |t| = 4.5 at this spread and N
        if "per_sample" in t:
            p = t["per_sample"]
            queued, clk = raw["queued"], raw["clocks_mhz"]
            modal = int(np.bincount(clk).argmax())
            off = np.abs(clk - modal) > p["clock_limit"] * modal
            flagged = ~queued | off
            gate(int((~queued).sum()) == p["unqueued"] and int(off.sum()) == p["off_clock"]
                 and int(flagged.sum()) == p["flagged"] and modal == p["steady_clock_mhz"],
                 f"{seed} {name}: flag counts recomputed from raw.npz equal the summary",
                 f"unqueued {p['unqueued']}, off clock {p['off_clock']}, flagged {p['flagged']}, modal clock {modal} MHz")
            un, _, _ = maxt(times[~flagged], classes[~flagged], cal)
            gate(abs(un - rec["unflagged"]["max_abs_t"]) < 1e-6 * max(1.0, un),
                 f"{seed} {name}: max |t| without the flagged measurements recomputed", f"{un:.4f}")
            fl0, fl1 = int((flagged & (classes == 0)).sum()), int((flagged & (classes == 1)).sum())
            v.update(flag=p["flagged"] / p["measurements"], modal=modal, at_modal=float((clk == modal).mean()), fl=(fl0, fl1),
                     off=p["off_clock"], unq=p["unqueued"], un=un, un_verdict=rec["unflagged"]["verdict"])
        V[(seed, name)] = v

out.append("    TABLE seed target verdict max|t| sign_at_max t_raw tests_over first_half second_half max|t|_unflagged "
           "flagged% unqueued off_clock flagged_class0/1 modal_MHz share_at_modal r blocker_blocks window_median_us "
           "diff_mean_ns detectable_ns clock_before->after(status) rule_50us [max_at]")
for (seed, name), v in V.items():
    r, t, ck = v["rec"], v["t"], v["t"]["clock"]
    k = (f"{v['un']:.4f} {100 * v['flag']:.2f} {v['unq']} {v['off']} {v['fl'][0]}/{v['fl'][1]} {v['modal']} {v['at_modal']:.5f}"
         if v["flag"] is not None else "- - - - - - -")
    out.append(f"    ROW {seed} {name} {r['verdict']} {r['max_abs_t']:.4f} {v['sign']} {r['t_raw']:.3f} {v['over']} "
               f"{v['halves'][0]:.4f} {v['halves'][1]:.4f} {k} {t['r']} {t['params'].get('blocker_blocks', '-')} "
               f"{v['median'] * 1e3:.2f} {(r['mean_class1'] - r['mean_class0']) * 1e6:.1f} {v['detect_ns']:.0f} "
               f"{ck['before_mhz']}->{ck['after_mhz']}({ck['status']}) "
               f"{'BELOW_50US' if v['median'] < MIN_MEDIAN_MS else 'ok'} [{r['max_at']}]")

# rule f, the remaining conditions
f_null = all([gate(V[(s, "control_null")]["rec"]["verdict"] == "PASS", f"rule f(2) {s}: full-N control_null PASS",
                   f"max |t| {V[(s, 'control_null')]['rec']['max_abs_t']:.4f}") for s in SEEDS])
f_mis = gate(all(v["t"]["mismatches"] == 0 for v in V.values()) and all(t["mismatches"] == 0 for t in st.values()),
             "rule f(3): 0 mismatches in every target")
kern = {k: v for k, v in V.items() if v["flag"] is not None}
worst = max(kern.items(), key=lambda kv: kv[1]["flag"])
f_flag = gate(all(v["flag"] < MAX_FLAGGED for v in kern.values()),
              f"rule f(4): fewer than 5% of the measurements flagged in each of the {len(kern)} kernel-window targets",
              f"{100 * min(v['flag'] for v in kern.values()):.2f}% to {100 * worst[1]['flag']:.2f}% "
              f"(worst {worst[0][0]} {worst[0][1]})")
note(f"rule f(4) read for control_leak_q as well would NOT hold ({100 * pq['flagged'] / pq['measurements']:.2f}% flagged): "
     "see the notes on the self-test")
below = sorted({name for (_, name), v in kern.items() if v["median"] < MIN_MEDIAN_MS})
note("windows with a median below the 50 us of ai/GPU_GUIDE.md section 7: " + (", ".join(below) or "none")
     + " (r was fitted from the single-launch time before the clock rose: "
     + ", ".join(f"{n} {S['s8'][n]['single_launch_median_ms'] * 1e3:.1f} us x r {S['s8'][n]['r']}"
                 for n in sorted(S["s8"]) if n != "control_null") + ")")
note("clock: lock refused, yet the modal SM clock of all kernel-window targets is "
     + "/".join(sorted({str(v["modal"]) for v in kern.values()}))
     + f" MHz with at least {100 * min(v['at_modal'] for v in kern.values()):.3f}% of the measurements at it and at most "
     f"{max(v['off'] for v in kern.values())} off the clock; control_null (no per-measurement clock) ran at "
     + ", ".join(f"{V[(s, 'control_null')]['t']['clock']['before_mhz']}->{V[(s, 'control_null')]['t']['clock']['after_mhz']}"
                 for s in SEEDS)
     + " MHz. The before->after status of a kernel target is taken around the target, the first reading before its blocker "
       "loop raised the clock")
usable = f_leakq and f_null and f_mis and f_flag
read(f"rule f, as written: control_leak_q FAILS {f_leakq}, control_null PASSES {f_null}, 0 mismatches {f_mis}, kernel targets "
     f"below 5% flagged {f_flag} -> {'USABLE' if usable else 'UNUSABLE'}; power of the QUEUED window shown by the queued "
     f"subset of control_leak_q: {q_power} ({n0q + n1q} measurements, not the full series)")

# rules g to j, per kernel
for k in KERNELS:
    nul = [V[(s, f"{k}_kernel_null")] for s in SEEDS]
    tgt = [V[(s, f"{k}_kernel")] for s in SEEDS]
    nf = [v["rec"]["verdict"] == "FAIL" for v in nul]
    tf = [v["rec"]["verdict"] == "FAIL" for v in tgt]
    vals = (f"null {', '.join(format(v['rec']['max_abs_t'], '.4f') for v in nul)}; target "
            f"{', '.join(format(v['rec']['max_abs_t'], '.4f') for v in tgt)} (seeds 8, 10); without flagged: null "
            f"{', '.join(format(v['un'], '.4f') for v in nul)}; target {', '.join(format(v['un'], '.4f') for v in tgt)}; "
            f"a raw mean difference of {max(v['detect_ns'] for v in tgt):.0f} ns per window (r {tgt[0]['t']['r']}) "
            "would give |t| = 4.5")
    if any(nf):
        rule = "h: the null FAILS in a seed, the target is not readable, UNUSABLE"
    elif all(tf) and len({v["sign"] for v in tgt}) == 1:
        rule = "i: null PASSES, target FAILS in both seeds with one sign: a dependence of the kernel time on its data is the reading"
    elif any(tf):
        rule = "j: null PASSES, target FAILS in one seed only: not decided, reported as measured"
    else:
        rule = "g: null PASSES and target PASSES in both seeds: no dependence detected at this N, on this device"
    read(f"{k}: rule {rule} - {vals}")
read("rule l: the lock was refused, so no locked run exists to compare; both seeds are unlocked runs at a steady modal clock "
     "(1590 MHz, not the 585 MHz the rule expected)")
out.append(f"SUMMARY {sum(1 for line in out if line.startswith('    PASS'))} gates PASS, {bad} FAIL")
print("\n".join(out))
sys.exit(1 if bad else 0)
