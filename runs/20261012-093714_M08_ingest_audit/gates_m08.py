"""M08 ingest gates: S1-S4 checks and A1-A5 inputs, read from the ingested bundle. Measures nothing."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from vcloak.bench import dudect  # noqa: E402

JOB = "20261012-041010_M08"
RUNS = {"selftest": "20261012-031245_M08_dudect_selftest_quick", "dudect": "20261012-031331_M08_dudect",
        "sass": "20261012-040020_M08_sass", "ncu": "20261012-040027_M08_ncu"}
TARGETS = ("bitonic_equal", "bitonic_sorted", "write_epoch", "aead_tag", "aead_conv")
out, bad = [], 0


def gate(ok, text, detail=""):
    global bad
    bad += not ok
    out.append(f"    {'PASS' if ok else 'FAIL'} {text}" + (f" - {detail}" if detail else ""))


def note(text):
    out.append(f"    NOTE {text}")


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
log3 = (ROOT / "gpujobs/out" / JOB / "logs/03_pytest_planted_leak.txt").read_text(encoding="utf-8").strip().splitlines()[-1]
gate(" passed" in log3 and "failed" not in log3 and "skipped" not in log3,
     "parity: planted-leak kernel equals its NumPy twin on the GPU", log3.strip("= "))
for name, d in RUNS.items():
    m = load(name, "manifest.json")
    gate(m["env"]["backend"] == "cupy" and m["gpu_job"]["job_id"] == JOB and m["env"]["session_id"] == env["session_id"],
         f"manifest {d}: cupy, this job, this session", f"status {m['status']}")

# S1 / A1: the harness has power, and does not separate identical classes
st = {t["target"]: t for t in load("selftest")["targets"]}
full = {t["target"]: t for t in load("dudect")["targets"]}
leak, null_q, null_f = st["control_leak"], st["control_null"], full["control_null"]
gate(leak["verdict"] == "FAIL" and leak["max_abs_t"] > 10 * 4.5, "S1/A1 planted leak detected (|t| >> 4.5)",
     f"max |t| {leak['max_abs_t']:.4f} at N {leak['n_per_class']} (quick)")
gate(null_q["verdict"] == "PASS", "S1 null control not detected (quick)", f"max |t| {null_q['max_abs_t']:.4f}")
gate(null_f["verdict"] == "PASS", "S1 null control not detected (full N)",
     f"max |t| {null_f['max_abs_t']:.4f} at N {null_f['n_per_class']}")

# S2 / A2: five verdicts at full N, recomputed from the raw data of the bundle
gate(set(TARGETS) <= set(full) and not load("dudect", "manifest.json")["quick"], "S2/A2 five targets have verdicts at full N")
gate(load("dudect")["timer"] == "cupy.cuda.Event", "S2 timer is CUDA events")
fails = []
for name in ("control_null", *TARGETS):
    t = full[name]
    d = ROOT / "runs" / RUNS["dudect"]
    raw = np.load(d / f"dudect_{name}_raw.npz")
    times, classes, cal = raw["times_ms"], raw["classes"], raw["calibration_ms"]
    gate(int((classes == 0).sum()) == int((classes == 1).sum()) == 100000 and t["mismatches"] == 0,
         f"S2 {name}: 100000 measurements per class, outputs correct", f"r {t['r']}")
    for s, sname in enumerate(t["series"]):
        test = dudect.OnlineTTest(dudect.crop_thresholds(cal[:, s]))
        test.update(times[:, s], classes)
        again = float(test.max_abs_t()[0])
        rec = t["series"][sname]
        gate(abs(again - rec["max_abs_t"]) < 1e-6 * max(1.0, again) and (again >= 4.5) == (rec["verdict"] == "FAIL"),
             f"S2 {name}/{sname}: max |t| recomputed from raw.npz equals the summary", f"{again:.4f} {rec['verdict']}")
        gate((d / f"dudect_{name}.png").exists(), f"S2 {name}/{sname}: t-curve saved")
        if rec["verdict"] == "FAIL":
            fails.append(f"{name}/{sname} max |t| {rec['max_abs_t']:.4f} (mean class0 {rec['mean_class0']:.6f} ms, "
                         f"class1 {rec['mean_class1']:.6f} ms, t_raw {rec['t_raw']:.3f}, {rec['max_at']})")
    note(f"{name}: SM clock {t['clock']['before_mhz']}->{t['clock']['after_mhz']} MHz of {t['clock']['max_mhz']} "
         f"({t['clock']['status']}), {t['measure_seconds']:.0f} s")
for f in fails:
    out.append(f"    FINDING dudect FAIL {f}")
out.append(f"    A5 {len(fails)} target series FAIL -> a high-severity issue that BLOCKS M14 must be open")

# S3 / A3
sass = load("sass")
gate(all(v["ok"] for v in sass["log"]["files"].values()), "S3 nvcc -cubin + cuobjdump -sass for the three kernel files")
gate(sass["control"]["detected"], "S3 planted-leak control: divergence control found in its listing")
osum = json.loads((ROOT / "results/oblivious/oblivious_summary.json").read_text(encoding="utf-8"))
n_cond = sum(len(v) for v in sass["to_explain"].values())
gate(osum["sass_explained_public"] == n_cond == sum(f["conditional"] for fs in sass["functions"].values() for f in fs),
     "S3/A3 every conditional branch explained and checked against the listing", f"{n_cond} branches")
gate(all(f["sync"] == 0 for fs in sass["functions"].values() for f in fs), "S3 no BSSY/BSYNC in any kernel")
note("sass_check.py classifies all conditional branches as DATA (flow-insensitive trace); the explanations are a manual reading")
note("nvrtc listing: " + "; ".join(sorted({v["how"] for v in sass["log"]["nvrtc"].values() if not v["ok"]}) or ["saved"]))

# S4 / A4
ncu = load("ncu")
vals = {m["value"] for m in ncu["metrics"]}
gate(vals == {"NOT_MEASURED"} and "ERR_NVGPUCTRPERM" in (ncu["reason"] or "") or "NOT_MEASURED" not in vals,
     "S4/A4 ncu metrics collected, or NOT_MEASURED with the reason", ncu["reason"] or "collected")
gate("ERR_NVGPUCTRPERM" in (ROOT / "runs" / RUNS["ncu"] / "ncu_profile_raw.txt").read_text(encoding="utf-8"),
     "S4 the refusal is in the saved raw tool output")

out.append(f"gates: {sum(' PASS ' in x for x in out)} PASS, {bad} FAIL, {len(fails)} dudect findings")
print("\n".join(out))
sys.exit(1 if bad else 0)
