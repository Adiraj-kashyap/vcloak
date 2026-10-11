"""Session 14 bookkeeping for M07: evidence copies, sidecar/tag checks, issues, audit, logs, state."""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
R = ROOT / "runs" / "20261012-033804_M07_ingest_audit"
JOB = ROOT / "gpujobs" / "out" / "20261011-224124_M07"
RK = "runs/20261011-213207_M07_kernel_sweep"
RC = "runs/20261011-213731_M07_cpu_baselines"
RX = "runs/20261011-215652_M07_crossover"
RP = "runs/20261011-215653_M07_pipeline"
AUD = "runs/20261012-033804_M07_ingest_audit"
JOBSRC = "gpujobs/out/20261011-224124_M07/logs (job 20261011-224124_M07, git c40696b)"
DATE = "2026-10-12"

# ---- A1 / G2: sidecars and note tags against the index
index = {}
for line in (ROOT / "state" / "METRICS_INDEX.md").read_text(encoding="utf-8").splitlines():
    c = [x.strip() for x in line.strip().strip("|").split("|")]
    if len(c) == 11 and c[4] == "M07" and c[5] in (RK, RC, RX, RP):
        index[c[0]] = c[1]
out, ok = [], True
perf = ROOT / "results" / "perf"
sides = sorted(p for p in perf.glob("fig_*.json"))
for s in sides:
    d = json.loads(s.read_text(encoding="utf-8"))
    dirs_ok = all((ROOT / x / "manifest.json").exists() for x in d["run_dirs"])
    missing = [m for m in d["metric_ids"] if m not in index]
    files_ok = all((perf / f).stat().st_size > 0 for f in d["files"])
    good = dirs_ok and not missing and files_ok and d["session_id"] == "20261011-213139" and d["backend"] == "cupy"
    ok &= good
    out.append(f"{'PASS' if good else 'FAIL'} {s.name}: {len(d['metric_ids'])} metric ids all indexed, run dirs "
               f"{d['run_dirs']}, files {d['files']}" + (f", MISSING {missing[:3]}" if missing else ""))
notes = (ROOT / "docs" / "REPORT_CH4_NOTES.md").read_text(encoding="utf-8")
tags = [t for t in re.findall(r"([^\s|<]+)<!--M:([^>]+?)-->", notes) if t[1] != "ID"]  # "ID" is the format example
bad = [(v, m) for v, m in tags if m not in index or index[m] != v and float(index[m]) != float(v)]
ok &= not bad and len(tags) > 0
out.append(f"{'PASS' if not bad else 'FAIL'} docs/REPORT_CH4_NOTES.md: {len(tags)} tagged values, each equal to its "
           f"METRICS_INDEX row ({sum(v == 'UNSTABLE' for v, _ in tags)} of them UNSTABLE)" + (f" BAD {bad[:3]}" if bad else ""))
out.append(f"RESULT: {'PASS' if ok else 'FAIL'} ({len(sides)} sidecars)")
(R / "a1_sidecars_and_tags.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
print(out[-2][:150])
print(out[-1])
if not ok:
    sys.exit(1)

# ---- evidence (copied, never retyped)
ev = ROOT / "evidence"
copies = [
    (JOB / "logs" / "01_nvidia_smi.txt", ev / "gpu" / "M07_nvidia_smi.txt"),
    (JOB / "logs" / "09_nvidia_smi_after.txt", ev / "gpu" / "M07_nvidia_smi_after.txt"),
    (JOB / "logs" / "02_cpu_info.txt", ev / "gpu" / "M07_cpu_info.txt"),
    (ROOT / RP / "host_profile.txt", ev / "terminal" / "M07_host_profile.txt"),
    (R / "gates.txt", ev / "terminal" / "M07_gates.txt"),
    (R / "pytest.txt", ev / "terminal" / "M07_pytest_local.txt"),
    (perf / "perf_summary.json", ev / "gpu" / "M07_perf_summary.json"),
]
for src, dst in copies:
    shutil.copyfile(src, dst)
ks = json.loads((ROOT / RK / "summary.json").read_text(encoding="utf-8"))
(ev / "gpu" / "M07_device_and_telemetry.json").write_text(json.dumps(
    {"source": RK + "/summary.json", "device": ks["device"], "host": ks["host"], "peak_bw_gbs": ks["peak_bw_gbs"],
     "telemetry": ks["telemetry"], "telemetry_samples": ks["telemetry_samples"], "ramps": ks["ramps"]}, indent=2) + "\n",
    encoding="utf-8")
logs = "".join(f"===== {p.name} =====\n{p.read_text(encoding='utf-8', errors='replace')}\n"
               for p in sorted((JOB / "logs").glob("0[3-8]_*.txt")))
(ev / "terminal" / "M07_gpu_run_output.txt").write_text(logs, encoding="utf-8")
figs = sorted(perf.glob("fig_*.png")) + sorted(perf.glob("fig_*.pdf"))
for f in figs:
    shutil.copyfile(f, ev / "figures" / ("M07_" + f.name))

fig_what = {json.loads(s.read_text(encoding="utf-8"))["figure"]: json.loads(s.read_text(encoding="utf-8")) for s in sides}
rows = [
    f"| GPU-M07-SMI | gpu/M07_nvidia_smi.txt, gpu/M07_nvidia_smi_after.txt — nvidia-smi on the runner before and after the M07 job | M07 | {DATE} | {JOBSRC} | measured | — |",
    f"| GPU-M07-CPU | gpu/M07_cpu_info.txt — lscpu of the runner host, the CPU side of the GPU/CPU comparison | M07 | {DATE} | {JOBSRC} | measured | — |",
    f"| GPU-M07-DEVICE | gpu/M07_device_and_telemetry.json — device properties, host, theoretical peak bandwidth and the telemetry summary (2625 NVML samples) of the kernel sweep, extracted from its summary.json | M07 | {DATE} | {RK} (job 20261011-224124_M07, git c40696b) | measured | — |",
    f"| GPU-M07-PERFSUM | gpu/M07_perf_summary.json — provenance, run status, real-time gate, crossover and the list of unstable configurations behind results/perf | M07 | {DATE} | {RK}, {RC}, {RX}, {RP} (git c40696b) | measured | — |",
    f"| TERM-M07-GPURUN | terminal/M07_gpu_run_output.txt — runner output of the timer tests (event timer vs host clock), the engine regression, the kernel sweep, the CPU baselines, the crossover and the pipeline with the real-time gate | M07 | {DATE} | {JOBSRC} | measured | — |",
    f"| TERM-M07-HOSTPROFILE | terminal/M07_host_profile.txt — cProfile of three write_epoch calls at SLOTS 65536 on the runner (ISSUE-12) | M07 | {DATE} | {RP} (job 20261011-224124_M07, git c40696b) | measured | — |",
    f"| TERM-M07-GATES | terminal/M07_gates.txt — M07 gates recomputed from the ingested raw.csv, summary.json and telemetry.csv: 45 of 78 kernel configurations UNSTABLE, real-time gate fails for the whole call at SLOTS 65536 | M07 | {DATE} | {AUD} (git 00f6fe1, dirty) | measured | — |",
    f"| TERM-M07-PYTEST | terminal/M07_pytest_local.txt — module tests on the laptop (numpy backend; correctness only, 3 GPU tests skipped) | M07 | {DATE} | {AUD} (git 00f6fe1, dirty) | measured | — |",
    f"| TERM-M07-AUDIT | terminal/M07_audit.txt — M07 audit table A1–A5, G1–G10 | M07 | {DATE} | {AUD} (git 00f6fe1, dirty) | measured | — |",
]
for name, d in fig_what.items():
    rows.append(f"| FIG-M07-{name[4:].upper().replace('_', '-')} | figures/M07_{name}.png + .pdf (300 dpi; copy of results/perf, "
                f"sidecar results/perf/{name}.json) — {d['what']}; UNSTABLE points drawn hollow | M07 | {DATE} | "
                f"{', '.join(d['run_dirs'])} (job 20261011-224124_M07, git c40696b) | measured | — |")
with (ev / "INDEX.md").open("a", encoding="utf-8") as f:
    f.write("\n".join(rows) + "\n")
print(f"evidence: {len(copies) + 2 + len(figs)} files, {len(rows)} index rows")
