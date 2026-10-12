"""ISSUE-17 ingest gates: integrity, void conditions and the reading rules of the issue. Measures nothing."""
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from vcloak.bench import dudect  # noqa: E402

JOB = "20261012-113437_M08_issue17"
RUNS = {"selftest": "20261012-061335_M08_dudect_issue17_selftest_quick", "s8": "20261012-061420_M08_dudect_issue17_s8",
        "s9": "20261012-080629_M08_dudect_issue17_s9"}
M08 = "20261012-031331_M08_dudect"
THR = 4.5
ORIGINALS = (("aead_conv", "ms"), ("aead_tag", "ms"), ("write_epoch", "call_ms"))
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
log3 = (ROOT / "gpujobs/out" / JOB / "logs/03_pytest_issue17.txt").read_text(encoding="utf-8").strip().splitlines()[-1]
gate(" passed" in log3 and "failed" not in log3 and "skipped" not in log3, "tests of the diagnostics on the GPU", log3.strip("= "))
for name, d in RUNS.items():
    m = load(name, "manifest.json")
    gate(m["env"]["backend"] == "cupy" and m["gpu_job"]["job_id"] == JOB and m["env"]["session_id"] == env["session_id"],
         f"manifest {d}: cupy, this job, this session", f"status {m['status']}")
m08_env = json.loads((ROOT / "runs" / M08 / "manifest.json").read_text(encoding="utf-8"))["env"]
note(f"the M08 job ran in session {m08_env.get('session_id')} (driver {m08_env.get('driver', '?')}); this job in "
     f"{env['session_id']} (driver {env['driver']}): two runner sessions, values are not pooled")

st = {t["target"]: t for t in load("selftest")["targets"]}
S = {seed: {t["target"]: t for t in load(seed)["targets"]} for seed in ("s8", "s9")}
leak = st["control_leak"]
gate(leak["verdict"] == "FAIL" and leak["max_abs_t"] > 10 * THR, "planted leak detected in this session (|t| >> 4.5)",
     f"max |t| {leak['max_abs_t']:.4f} at N {leak['n_per_class']} (quick)")
for seed in ("s8", "s9"):
    gate(not load(seed)["errors"] and not load(seed, "manifest.json")["quick"] and load(seed)["timer"] == "cupy.cuda.Event",
         f"{seed}: no target error, full N, CUDA events", f"{len(S[seed])} targets")

# every verdict recomputed from the raw data of the bundle
rows = []
for seed in ("s8", "s9"):
    d = ROOT / "runs" / RUNS[seed]
    for name, t in S[seed].items():
        raw = np.load(d / f"dudect_{name}_raw.npz")
        times, classes, cal = raw["times_ms"], raw["classes"], raw["calibration_ms"]
        n0, n1 = int((classes == 0).sum()), int((classes == 1).sum())
        gate(n0 == n1 == 100000 and t["mismatches"] == 0, f"{seed} {name}: 100000 measurements per class, outputs correct",
             f"r {t['r']}, clock {t['clock']['before_mhz']}->{t['clock']['after_mhz']} MHz {t['clock']['status']}, "
             f"{t['measure_seconds']:.0f} s")
        for s, sname in enumerate(t["series"]):
            test = dudect.OnlineTTest(dudect.crop_thresholds(cal[:, s]))
            test.update(times[:, s], classes)
            again = float(test.max_abs_t()[0])
            rec = t["series"][sname]
            gate(abs(again - rec["max_abs_t"]) < 1e-6 * max(1.0, again) and (again >= THR) == (rec["verdict"] == "FAIL"),
                 f"{seed} {name}/{sname}: max |t| recomputed from raw.npz equals the summary", f"{again:.4f} {rec['verdict']}")
            x0, x1 = times[classes == 0, s], times[classes == 1, s]
            se = math.sqrt(x0.var(ddof=1) / n0 + x1.var(ddof=1) / n1)
            med = float(np.median(x1) - np.median(x0))
            rows.append((seed, name, sname, rec, se, med, t))

V = {(seed, name, sname): rec for seed, name, sname, rec, *_ in rows}
out.append("    TABLE seed target/series verdict max|t| t_raw mean0_ms mean1_ms diff_mean_ns diff_median_ns "
           "raw_shift_at_4.5_ns max_at")
for seed, name, sname, rec, se, med, t in rows:
    out.append(f"    ROW {seed} {name}/{sname} {rec['verdict']} {rec['max_abs_t']:.4f} {rec['t_raw']:.3f} "
               f"{rec['mean_class0']:.6f} {rec['mean_class1']:.6f} {(rec['mean_class1'] - rec['mean_class0']) * 1e6:.1f} "
               f"{med * 1e6:.1f} {THR * se * 1e6:.1f} [{rec['max_at']}]")

# void conditions of the issue
for seed in ("s8", "s9"):
    c = V[(seed, "control_null", "ms")]
    gate(c["verdict"] == "PASS", f"{seed}: full-N control_null PASS (else the run is void)", f"max |t| {c['max_abs_t']:.4f}")
    for name, sname in ORIGINALS:
        r = V[(seed, name, sname)]
        gate(r["verdict"] == "FAIL", f"{seed}: original {name}/{sname} FAILS again (the M08 finding is reproduced)",
             f"max |t| {r['max_abs_t']:.4f}, t_raw {r['t_raw']:.3f}")
    r = V[(seed, "write_epoch", "device_ms")]
    note(f"{seed}: write_epoch/device_ms {r['verdict']} {r['max_abs_t']:.4f} (PASS in M08: 2.7559)")

# reading rules (state/ISSUES.md, ISSUE-17). A reading, not a proof.
for kind, hyp in (("aead_conv", "H1"), ("aead_tag", "H2")):
    for seed in ("s8", "s9"):
        o, n, w = (V[(seed, kind + x, "ms")] for x in ("", "_null", "_swap"))
        sy, k = V[(seed, kind + "_sym", "ms")], V[(seed, kind + "_kernel", "ms")]
        read(f"{seed} {kind}_null {n['verdict']} {n['max_abs_t']:.4f}: "
             + (f"the staging alone separates two classes with the same contents ({hyp})" if n["verdict"] == "FAIL"
                else f"the staging alone does not separate the classes ({hyp} not supported)"))
        same = (o["t_raw"] < 0) == (w["t_raw"] < 0)
        read(f"{seed} {kind}_swap t_raw {w['t_raw']:.3f} vs original {o['t_raw']:.3f}: "
             + ("same sign, the difference follows the staging role" if same
                else "opposite sign, the difference follows the contents"))
        read(f"{seed} {kind}_sym {sy['verdict']} {sy['max_abs_t']:.4f}, {kind}_kernel {k['verdict']} {k['max_abs_t']:.4f}: "
             + ("harness staging; no data dependence detected with symmetric staging"
                if sy["verdict"] == k["verdict"] == "PASS" else "H3 stays open"))
for seed in ("s8", "s9"):
    for name in ("write_epoch_null", "write_epoch_age", "write_epoch_fresh"):
        if (seed, name, "call_ms") in V:
            c, dv = V[(seed, name, "call_ms")], V[(seed, name, "device_ms")]
            read(f"{seed} {name}: call_ms {c['verdict']} {c['max_abs_t']:.4f}, device_ms {dv['verdict']} {dv['max_abs_t']:.4f}")
unexpected = [f"{seed} {name}/{sname} {rec['max_abs_t']:.4f}" for seed, name, sname, rec, *_ in rows
              if sname == "device_ms" and rec["verdict"] == "FAIL"]
for u in unexpected:
    out.append(f"    FINDING device-stage series FAIL, not covered by the reading rules: {u}")
note("clock: every FAIL series ran at 585 MHz (LOW); *_sym ran at the full clock (OK), *_kernel in between (LOW). "
     "The staging and the clock state change together, so their effects are not separated by this job")
note("write_epoch_null and write_epoch_age ran at seed 8 only (not in issue17_rep)")

out.append(f"gates: {sum(' PASS ' in x for x in out)} PASS, {bad} FAIL, {len(unexpected)} unexpected device-stage findings")
print("\n".join(out))
sys.exit(1 if bad else 0)
