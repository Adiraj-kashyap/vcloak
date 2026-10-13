"""M08 S5: the obliviousness summary table, results/oblivious/ and the Chapter 4 notes section.

    python -m vcloak.bench.report_oblivious --selftest runs/<dudect_selftest> --dudect runs/<dudect> \
        --sass runs/<sass> --ncu runs/<ncu> --out results/oblivious --notes docs/REPORT_CH4_NOTES.md

Nothing here measures. Every cell is read from a run's summary.json; the four runs must be `cupy` runs of one
runner session and one GPU job, otherwise nothing is written. A verdict is copied, never recomputed: a FAIL
stays a FAIL in the table and in the notes (audit A5). The branch explanations of bench/sass_explained.json are
checked against the saved listing, instruction by instruction, before they are counted as explained.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np

from vcloak.bench import dudect
from vcloak.bench.derive import NM
from vcloak.bench.report import M08_BEGIN, M08_END, ReportError, _md_table, load_run, rel, tagged

BEGIN, END = M08_BEGIN, M08_END
TARGETS = ("bitonic_equal", "bitonic_sorted", "write_epoch", "aead_tag", "aead_conv")
# dudect target -> the kernels it launches that have a SASS listing and an ncu metric
KERNELS_OF = {
    "bitonic_equal": ("bitonic_shared_full", "bitonic_shared", "bitonic_pairs_global"),
    "bitonic_sorted": ("bitonic_shared_full", "bitonic_shared", "bitonic_pairs_global"),
    "write_epoch": ("chacha_tags", "bitonic_shared_full", "bitonic_shared", "bitonic_pairs_global"),
    "aead_tag": ("aead_open_seq",),
    "aead_conv": ("aead_open_seq",),
}
_INSTR = re.compile(r"\s*/\*([0-9a-f]{4})\*/\s+(.*?)\s*;")


def metric_id(prefix: str, name: str) -> str:
    return f"{prefix}-{name.upper().replace('_', '-')}"


def check_inputs(runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    first = runs["dudect"]["manifest"]
    for name, r in runs.items():
        m = r["manifest"]
        if m["env"]["backend"] != "cupy":
            raise ReportError(f"{name}: backend {m['env']['backend']} (only ingested cupy runs are reported)")
        if "gpu_job" not in m:
            raise ReportError(f"{name}: no gpu_job block (not from an ingested bundle)")
        for key in ("session_id", "runner", "gpu"):
            if m["env"][key] != first["env"][key]:
                raise ReportError(f"{name}: {key} differs from the dudect run (never merge two sessions)")
    if runs["dudect"]["manifest"]["quick"]:
        raise ReportError("the dudect run is a quick run")
    env = first["env"]
    return {"session_id": env["session_id"], "runner": env["runner"], "gpu": env["gpu"],
            "driver": env.get("driver", NM), "cuda": env.get("cuda", NM), "cupy": env.get("cupy", NM),
            "git_sha": first["git_sha"], "job_id": first["gpu_job"].get("job_id", NM)}


def listing_instructions(path: Path) -> dict[str, dict[str, str]]:
    """function -> {address: instruction} of a cuobjdump -sass listing."""
    out: dict[str, dict[str, str]] = {}
    cur: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "Function :" in line:
            cur = out.setdefault(line.split("Function :")[1].strip(), {})
        elif cur is not None:
            m = _INSTR.match(line)
            if m:
                cur[m.group(1)] = " ".join(m.group(2).split())
    return out


def check_explanations(sass: dict[str, Any], explained: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per conditional branch of the SASS run, joined with its explanation. Raises if one is missing,
    is not marked public, or names an instruction that is not at that address in the saved listing."""
    by_key = {(b["file"], b["function"], b["addr"]): b for b in explained["branches"]}
    rows = []
    for file, branches in sass["summary"]["to_explain"].items():
        listing = listing_instructions(sass["dir"] / f"sass_{Path(file).stem}.txt")
        for b in branches:
            e = by_key.get((file, b["function"], b["addr"]))
            where = f"{file} {b['function']} {b['addr']}"
            if e is None:
                raise ReportError(f"SASS branch without an explanation: {where} {b['instr']}")
            ins = listing.get(b["function"], {})
            if ins.get(b["addr"]) != e["instr"] or b["instr"] != e["instr"]:
                raise ReportError(f"SASS explanation is stale: {where} is `{ins.get(b['addr'])}`")
            s_addr, s_instr = e["setter"].split(" ", 1)
            if ins.get(s_addr) != s_instr:
                raise ReportError(f"SASS explanation names a wrong setter: {where} at {s_addr} is `{ins.get(s_addr)}`")
            if not e["public"]:
                raise ReportError(f"SASS branch not explained as public: {where}")
            rows.append({**e, "checker_class": b["class"]})
    return rows


def write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def summary_rows(runs: dict[str, dict[str, Any]], branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The S5 table: one row per series of the two controls and the five targets."""
    cond = {(b["function"]): 0 for b in branches}
    for b in branches:
        cond[b["function"]] += 1
    ncu = runs["ncu"]["metrics"]
    rows = []

    def add(run: str, t: dict[str, Any]) -> None:
        kernels = KERNELS_OF.get(t["target"], ())
        div = {str(ncu[m]["value"]) for k in kernels if (m := metric_id("T-NCU-DIVERGENT", k)) in ncu}
        for s, st in t["series"].items():
            mid = metric_id("T-DUDECT-MAXT", t["target"]) + ("-CALL" if s == "call_ms" else "")
            rows.append({
                "run": run, "target": t["target"], "series": s, "title": t["title"], "n_per_class": st["n_class0"],
                "max_abs_t": st["max_abs_t"], "max_at": st["max_at"], "verdict": st["verdict"],
                "expected": t["expected_verdict"] if s != "call_ms" else "PASS", "metric": mid,
                "n_metric": metric_id("T-DUDECT-N", t["target"]), "clock": t["clock"]["status"],
                "sm_clock_mhz": f"{t['clock']['before_mhz']}-{t['clock']['after_mhz']}", "r": t["r"],
                "mismatches": t["mismatches"], "kernels": list(kernels),
                "sass_conditional": sum(cond.get(k, 0) for k in kernels) if kernels else None,
                "ncu_divergent": "" if not kernels else NM if not div else div.pop() if len(div) == 1 else "mixed",
            })

    for t in runs["selftest"]["summary"]["targets"]:
        add("selftest", t)
    for t in runs["dudect"]["summary"]["targets"]:
        add("dudect", t)
    return rows


def build_section(runs: dict[str, dict[str, Any]], prov: dict[str, Any], root: Path, rows: list[dict[str, Any]],
                  branches: list[dict[str, Any]], issues: dict[str, str]) -> str:
    def t(run: str, mid: str) -> str:
        return tagged({run: runs[run]}, mid)

    def verdict(r: dict[str, Any]) -> str:
        return f"**{r['verdict']}**" if r["verdict"] != r["expected"] else r["verdict"]

    def sass_cell(r: dict[str, Any]) -> str:
        if r["sass_conditional"] is None:
            return "-"
        return f"{r['sass_conditional']} of {r['sass_conditional']} ({', '.join(r['kernels'])})"

    label = {"ms": "", "device_ms": " (device stages)", "call_ms": " (whole call)"}
    table = _md_table(
        ["target", "run", "N / class", "max \\|t\\|", "verdict", "SASS conditional branches explained",
         "ncu divergent branches"],
        [[f"{r['target']}{label[r['series']]}", "quick self-test" if r["run"] == "selftest" else "full",
          t(r["run"], r["n_metric"]), t(r["run"], r["metric"]), verdict(r), sass_cell(r),
          str(r["ncu_divergent"]) if r["kernels"] else "-"] for r in rows])
    fails = [r for r in rows if r["verdict"] == "FAIL" and r["expected"] == "PASS"]
    fail_list = "\n".join(
        f"- `{r['target']}`{label[r['series']]}: max |t| {t('dudect', r['metric'])}, largest at {r['max_at']}; "
        f"SM clock {r['sm_clock_mhz']} MHz ({r['clock']}); class means, percentiles and the t of every crop are in "
        f"`results/oblivious/dudect_{r['target']}.json`." for r in fails) or "- none"
    sass = runs["sass"]["summary"]
    fn_tbl = _md_table(
        ["kernel", "instructions", "branch instructions", "conditional", "explained as public", "BSSY/BSYNC"],
        [[f["function"], str(f["instructions"]), t("sass", metric_id("T-SASS-BRA", f["function"])),
          str(f["conditional"]), str(sum(b["function"] == f["function"] for b in branches)), str(f["sync"])]
         for fs in sass["functions"].values() for f in fs])
    br_tbl = _md_table(["kernel", "address", "branch", "predicate set by", "source construct", "depends on"],
                       [[b["function"], b["addr"], f"`{b['instr']}`", f"`{b['setter']}`",
                         b["source"].replace("|", "\\|"),
                         b["depends_on"]] for b in branches])
    nvrtc_ok = any(v.get("ok") for v in sass["log"].get("nvrtc", {}).values())
    ncu = runs["ncu"]["summary"]
    ncu_ids = [m["id"] for m in ncu["metrics"]]
    ncu_measured = [i for i in ncu_ids if str(runs["ncu"]["metrics"][i]["value"]) != NM]
    run_list = "\n".join(f"- `{rel(r['dir'], root)}` ({name}, status {r['manifest']['status']})"
                         for name, r in runs.items())
    d = runs["dudect"]["summary"]
    crops = runs["dudect"]["manifest"]["params"]["percentile_crops"]
    n_series = sum(r["run"] == "dudect" and r["target"] in TARGETS for r in rows)
    leak_t, n_full = t("selftest", "T-DUDECT-MAXT-CONTROL-LEAK"), t("dudect", "T-DUDECT-N-AEAD-CONV")
    return f"""{BEGIN}
# Chapter 4 notes — obliviousness, physical (M08, E3)

Generated by `python -m vcloak.bench.report_oblivious` from ingested run dirs. Do not edit by hand: every value
carries a `<!--M:ID-->` tag that names its row in `state/METRICS_INDEX.md`. Verdicts are copied from the runs.

## 4.O.1 Measurement setup
- Runner: {prov['runner']}, {prov['gpu']}, driver {prov['driver']}, CUDA runtime {prov['cuda']}, CuPy {prov['cupy']};
  runner session {prov['session_id']}, GPU job {prov['job_id']}, packed from commit `{prov['git_sha'][:7]}`.
- Runs:
{run_list}
- dudect: two input classes, randomly interleaved, exactly N of each; one measurement is r launches between two
  CUDA events (`{d['timer']}`); Welch t on the raw data and on {crops}
  percentile crops whose thresholds come from a calibration batch that is not tested. The verdict is FAIL when the
  largest |t| of these tests reaches {d['t_threshold']}. dudect's second-order test is not implemented.
- The code that ran is CuPy's nvrtc build of `kernels/*.cu` ({d['executed_by']}).
- {d['caveat']}

## 4.O.2 Summary
{table}

A verdict in bold differs from the verdict that was expected. The two controls are not targets: `control_leak` must
FAIL (the planted `if (x) spin(1000)` kernel) and `control_null` must PASS (the same input in both classes).
The SASS column counts conditional branches of the nvcc-built listing; the bitonic and write_epoch rows share the
three comparator kernels. The kernels of write_epoch that have no listing in this job are not counted.

## 4.O.3 dudect findings
{len(fails)} of the {n_series} target series FAIL at N = {n_full} per class:
{fail_list}

What these results do and do not show:
- The harness has power: the planted leak is detected in quick mode (max |t| {leak_t}),
  and the null control stays below the threshold at full N (max |t| {t('dudect', 'T-DUDECT-MAXT-CONTROL-NULL')}).
- The fused bitonic sort shows no dependence on the tag order at this N, and neither do the device stages of
  write_epoch.
- The FAILs are recorded as findings and are **not explained**. The static evidence (no data-dependent branch in
  `aead_open_seq`, section 4.O.4) does not remove them: a timing difference between the classes was measured.
  Whether it comes from the device, from host work inside the timed window, or from the way the two classes are
  staged by the harness is not known from this job; {issues['fail']} lists the hypotheses and the controls that
  would separate them, and it blocks M14.
- The whole-call series of write_epoch includes the engine's host stage, which is Python code working on the
  submissions; it is not covered by the kernel rules of `ai/CONVENTIONS.md §2`.
- All three failing series, and the device series of write_epoch, were measured with the SM clock at a low
  frequency (column `clock` of `results/oblivious/summary_table.csv`).

## 4.O.4 SASS branches
Built with `{sass['log']['files']['bitonic.cu']['command'].split(' -I')[0]}` and listed with
`{sass['log']['files']['bitonic.cu']['disassembler']}`. Branch instructions per kernel (conditional, unconditional
`EXIT` and the trailing self-`BRA`):

{fn_tbl}

Every conditional branch, read in the saved listing (`bench/sass_explained.json`, checked against the listing by
the generator):

{br_tbl}

- No kernel listing contains `BSSY`/`BSYNC` (divergence control), `BRX`, `JMP` or `CALL`. The planted-leak
  control, compiled the same way, does contain divergence control (detected: {sass['control']['detected']}).
- `sass_check.py` labels all of these branches `DATA`: its trace is {sass['analysis'].split(';')[0]}, and a register
  that held a loaded value is later reused as a loop counter. The table above is the manual reading that the
  module asks for ({issues['sass']}).
- Limitation: the listing is the nvcc build. A listing of the nvrtc build that CuPy executes was
  {'saved' if nvrtc_ok else f'not obtained ({NM}: neither cuobjdump nor nvdisasm produced one on the runner)'}.

## 4.O.5 Nsight Compute divergence
{len(ncu_measured)} of {len(ncu_ids)} metrics measured. Reason: {ncu['reason'] or 'none'}.
`ncu --query-metrics` returned {len(ncu['branch_metrics_queried'])} branch metric names for the same reason. The
branch-efficiency and divergent-branch metrics of the four profiled kernels are `{NM}` in the index
({issues['ncu']}); the raw tool output is `results/oblivious/ncu_profile_raw.txt`.

## 4.O.6 Limitations
- One runner session on a shared GPU; no repeat on a second session or a second GPU model.
- dudect can show a dependence, not its absence; N is {t('dudect', 'T-DUDECT-N-BITONIC-EQUAL')} per class.
- Three target series FAIL and are open ({issues['fail']}).
- No dynamic divergence measurement ({issues['ncu']}); no listing of the executed nvrtc code ({issues['sass']}).
- P3 is a claim about the kernels. The host code that issues the launches (Python) is not constant time and is
  not claimed to be: timing can be observed only on a live server, which the threat model excludes (ADR-023).
  A whole-call or per-stage series that FAILS with equal contents stays in the tables as measured.
{END}
"""


# ---------------------------------------------------------------- kernel-only window (ISSUE-25)

MIN_WINDOW_MS = 0.050  # ai/GPU_GUIDE.md section 7
MAX_FLAGGED = 0.05     # reading rule f of ISSUE-25
SAME_INPUT_STAGES = ("tags_ms", "sort_ms", "compact_ms")


def _queued_only_t(run: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Raw Welch t over the measurements of a kernel-window target that were queued behind the blocker."""
    raw = np.load(run["dir"] / target["raw"])
    x, c, q = raw["times_ms"][:, 0], raw["classes"], raw["queued"]
    a, b = x[q & (c == 0)], x[q & (c == 1)]
    if min(a.size, b.size) < 2:
        return {"n0": int(a.size), "n1": int(b.size), "t": None, "clocks": []}
    t = float(dudect.welch_t(a.size, a.mean(), ((a - a.mean()) ** 2).sum(),
                             b.size, b.mean(), ((b - b.mean()) ** 2).sum()))
    return {"n0": int(a.size), "n1": int(b.size), "t": t, "clocks": sorted({int(v) for v in raw["clocks_mhz"][q]})}


def kernel_window_rows(seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for r in seeds:
        for t in r["summary"]["targets"]:
            st = t["series"]["ms"]
            p = t.get("per_sample")
            rows.append({
                "run": r, "seed": r["manifest"]["seed"], "target": t["target"], "n_per_class": st["n_class0"],
                "max_abs_t": st["max_abs_t"], "verdict": st["verdict"], "expected": t["expected_verdict"],
                "metric": metric_id("T-DUDECT-MAXT", t["target"]), "r": t["r"], "mismatches": t["mismatches"],
                "median_us": st["summary_class0"]["median_ms"] * 1e3,
                "below": st["summary_class0"]["median_ms"] < MIN_WINDOW_MS,
                "unflagged": st["unflagged"]["max_abs_t"] if p else None,
                "flagged": p["flagged"] if p else None, "unqueued": p["unqueued"] if p else None,
                "off_clock": p["off_clock"] if p else None,
                "flagged_share": p["flagged"] / p["measurements"] if p else None,
                "clock_mhz": p["steady_clock_mhz"] if p else f"{t['clock']['before_mhz']}-{t['clock']['after_mhz']}",
            })
    return rows


def kernel_window_reading(rows: list[dict[str, Any]], kernel: str) -> str:
    """Reading rules g to j of ISSUE-25, applied to the copied verdicts of one kernel."""
    nul = [r for r in rows if r["target"] == f"{kernel}_kernel_null"]
    tgt = [r for r in rows if r["target"] == f"{kernel}_kernel"]
    if not nul or not tgt:
        return f"{NM} (no series)"
    if any(r["verdict"] == "FAIL" for r in nul):
        return "unusable: the same-contents null FAILS in a seed, so the target is not readable (rule h)"
    fails = [r for r in tgt if r["verdict"] == "FAIL"]
    if len(fails) == len(tgt):
        return "**a dependence of the kernel time on its data is the reading** (rule i): the target FAILS in every seed"
    if fails:
        return "not decided (rule j): the target FAILS in one seed only; reported as measured"
    return (f"no dependence detected at this N, on this device (rule g): the null and the target PASS in "
            f"{len(tgt)} of {len(tgt)} seeds")


def build_kernel_window(selftest: dict[str, Any], seeds: list[dict[str, Any]], stage_runs: list[dict[str, Any]],
                        root: Path, issue: str) -> tuple[str, list[dict[str, Any]]]:
    """Section 4.O.7 and its rows. Verdicts are copied; the reading of a kernel is the rule applied to them."""
    runs = [selftest, *seeds]
    first = seeds[0]["manifest"]
    for r in runs:
        m = r["manifest"]
        if m["env"]["backend"] != "cupy" or "gpu_job" not in m:
            raise ReportError(f"{r['id']}: not an ingested cupy run")
        if m["env"]["session_id"] != first["env"]["session_id"] or m["gpu_job"]["job_id"] != first["gpu_job"]["job_id"]:
            raise ReportError(f"{r['id']}: session or job differs (never merge two sessions)")
    if any(r["manifest"]["quick"] for r in seeds):
        raise ReportError("a kernel-window run is a quick run")
    rows = kernel_window_rows(seeds)
    kern = [r for r in rows if r["flagged"] is not None]
    kernels = sorted({r["target"].split("_kernel")[0] for r in kern})
    env = first["env"]

    def t(r: dict[str, Any]) -> str:
        return tagged({"x": r["run"]}, r["metric"])

    table = _md_table(
        ["seed", "target", "N / class", "max \\|t\\|", "verdict", "max \\|t\\| without flagged", "flagged",
         "SM clock MHz (mode)", "window median", "r"],
        [[str(r["seed"]), f"`{r['target']}`", str(r["n_per_class"]), t(r),
          f"**{r['verdict']}**" if r["verdict"] != r["expected"] else r["verdict"],
          "-" if r["unflagged"] is None else f"{r['unflagged']:.4f}",
          "-" if r["flagged"] is None else f"{r['flagged']} ({100 * r['flagged_share']:.2f}%)", str(r["clock_mhz"]),
          f"{r['median_us']:.1f} us" + (" (below 50 us)" if r["below"] else ""), str(r["r"])] for r in rows])

    st = {x["target"]: x for x in selftest["summary"]["targets"]}
    leakq = st["control_leak_q"]
    pq, leakq_verdict = leakq["per_sample"], leakq["series"]["ms"]["verdict"]
    qo = _queued_only_t(selftest, leakq)
    qo_text = (f"Welch t {qo['t']:.2f} on {qo['n0']} and {qo['n1']} measurements per class, taken at SM clocks "
               f"{', '.join(str(c) for c in qo['clocks'])} MHz" if qo["t"] is not None else f"{NM} (too few)")
    lock = seeds[0]["summary"]["clock_lock"]
    lock_out = lock["output"].strip().splitlines()[0] if lock["output"].strip() else ""
    usable = (leakq_verdict == "FAIL" and all(r["verdict"] == "PASS" for r in rows if r["target"] == "control_null")
              and all(r["mismatches"] == 0 for r in rows) and all(r["flagged_share"] < MAX_FLAGGED for r in kern))
    below = sorted({r["target"] for r in kern if r["below"]})
    par = {x["target"]: x for x in seeds[0]["summary"]["targets"]}
    classes = "\n".join(f"- `{k}_kernel`: {par[f'{k}_kernel']['class0']} vs {par[f'{k}_kernel']['class1']} "
                        f"({par[f'{k}_kernel']['params']['kernel']}, {par[f'{k}_kernel']['params']['slots']} slots); "
                        f"`{k}_kernel_null` has the same contents in both classes." for k in kernels)
    readings = "\n".join(f"- {k}: {kernel_window_reading(rows, k)}." for k in kernels)
    run_list = ", ".join(f"`{rel(r['dir'], root)}`" for r in runs)

    stage = [(x["target"], s, v["verdict"]) for r in stage_runs for x in r["summary"]["targets"]
             if x["target"].endswith("_st") for s, v in x["series"].items()]
    same = [x for x in stage if x[1] in SAME_INPUT_STAGES]
    stage_note = ""
    if stage:
        job = stage_runs[0]["manifest"]["gpu_job"]["job_id"]
        stage_note = f"""
Note on the per-stage series of job `{job}` (annotation ANN-1 of `state/METRICS_INDEX.md`; every value is kept):
{len(stage)} series, {sum(1 for x in stage if x[2] == 'FAIL')} FAIL and {sum(1 for x in stage if x[2] == 'PASS')} PASS.
In `write_epoch` the stages tags, sort and compact never receive the submissions, so the device inputs of these
{len(same)} series were byte-identical in both classes: a FAIL among them is not a dependence of a kernel on its
data, and a PASS among them is not evidence of independence. The table above is the test of the tags and
compaction kernels against their own data.
"""
    section = f"""
## 4.O.7 Kernel-only window: tags and compaction against their own data ({issue})
Job `{first['gpu_job']['job_id']}`, runner session {env['session_id']} ({env['gpu']}, driver {env.get('driver', NM)}),
run dirs {run_list}. This is another runner session than the tables above; values are not pooled. Window:
{par[f'{kernels[0]}_kernel']['params']['window']} (a blocker launch of public size, then the start event, the launches
and the end event are enqueued while the device is busy). A measurement whose start event had already been reached
when the end event was enqueued is flagged unqueued; the SM clock is read after every measurement.

{classes}

{table}

- Rule f of {issue} (usable run): `control_leak_q` {leakq_verdict}S, every `control_null` PASSES, 0 output
  mismatches, fewer than 5% of the measurements flagged in every kernel-window target:
  {'met' if usable else '**not met**'}.
- Positive control of the queued window, as measured: `control_leak_q` max |t|
  {tagged({'x': selftest}, 'T-DUDECT-MAXT-CONTROL-LEAK-Q')} (quick, N {leakq['n_per_class']}), but
  {pq['unqueued']} of its {pq['measurements']} measurements were not queued behind the blocker
  (its blocker was fitted before the SM clock rose). Its queued measurements alone:
  {qo_text}.
  The power of the queued window therefore rests on these few measurements, not on the full series; the clock of
  the targets is in the table.
- Clock: the lock was attempted and {'accepted' if lock['accepted'] else 'refused'} (`{lock['command']}`: {lock_out})
  The mode of the per-measurement clock is in the table.
{readings}
- Limits: one runner session, one GPU model, one size; N is {rows[0]['n_per_class']} per class. dudect can show a
  dependence, not its absence. Windows with a median below the 50 us of the measurement rule:
  {', '.join(f'`{b}`' for b in below) or 'none'}.
{stage_note}"""
    return section, rows


def merge_notes(path: Path, section: str) -> None:
    """Replace the M08 block of the notes, or append it; the rest of the file is left as it is."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if BEGIN in old and END in old:
        new = old[:old.index(BEGIN)] + section.strip("\n") + old[old.index(END) + len(END):]
    else:
        new = old.rstrip("\n") + ("\n\n" if old else "") + section.strip("\n") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")


def generate(selftest: str | Path, dudect: str | Path, sass: str | Path, ncu: str | Path, out: str | Path,
             explained: str | Path, issues: dict[str, str], notes: str | Path | None = None,
             root: str | Path = ".", kernel_window: dict[str, Any] | None = None) -> dict[str, Any]:
    root, out = Path(root), Path(out)
    runs = {"selftest": load_run(selftest), "dudect": load_run(dudect), "sass": load_run(sass), "ncu": load_run(ncu)}
    prov = check_inputs(runs)
    branches = check_explanations(runs["sass"], json.loads(Path(explained).read_text(encoding="utf-8")))
    rows = summary_rows(runs, branches)
    missing = [x for x in TARGETS if x not in {r["target"] for r in rows if r["run"] == "dudect"}]
    if missing:
        raise ReportError(f"targets without a verdict at full N: {', '.join(missing)}")
    out.mkdir(parents=True, exist_ok=True)
    run_dirs = {name: rel(r["dir"], root) for name, r in runs.items()}

    copied = []
    for name in ("selftest", "dudect"):  # the full-N null control overwrites the quick one
        for src in sorted(runs[name]["dir"].glob("dudect_*")):
            if src.suffix in (".json", ".png"):
                shutil.copyfile(src, out / src.name)
                copied.append(src.name)
    for src in sorted(runs["sass"]["dir"].glob("sass_*.txt")):
        shutil.copyfile(src, out / src.name)
        copied.append(src.name)
    for src in sorted(runs["ncu"]["dir"].glob("ncu_*")):
        shutil.copyfile(src, out / src.name)
        copied.append(src.name)

    write_csv(out / "summary_table.csv",
              ["target", "series", "run", "n_per_class", "max_abs_t", "max_at", "verdict", "expected_verdict",
               "sm_clock_mhz", "clock", "r", "output_mismatches", "sass_conditional_explained", "ncu_divergent",
               "metric_id", "run_dir"],
              [[r["target"], r["series"], r["run"], r["n_per_class"], r["max_abs_t"], r["max_at"], r["verdict"],
                r["expected"], r["sm_clock_mhz"], r["clock"], r["r"], r["mismatches"],
                "" if r["sass_conditional"] is None else r["sass_conditional"], r["ncu_divergent"], r["metric"],
                run_dirs[r["run"]]] for r in rows])
    write_csv(out / "sass_branches_explained.csv",
              ["file", "function", "addr", "instr", "setter", "source", "depends_on", "public", "checker_class",
               "run_dir"],
              [[b["file"], b["function"], b["addr"], b["instr"], b["setter"], b["source"], b["depends_on"],
                b["public"], b["checker_class"], run_dirs["sass"]] for b in branches])
    write_csv(out / "ncu_divergence.csv", ["metric_id", "value", "unit", "stat", "note", "run_dir"],
              [[m["id"], m["value"], m["unit"], m["stat"], m["note"], run_dirs["ncu"]]
               for m in runs["ncu"]["summary"]["metrics"]])

    extra, kw_files, kw_dirs = "", [], {}
    if kernel_window:
        kw_seeds = [load_run(d) for d in kernel_window["seeds"]]
        kw_self = load_run(kernel_window["selftest"])
        kw_stage = [load_run(d) for d in kernel_window.get("stage_runs", [])]
        extra, kw_rows = build_kernel_window(kw_self, kw_seeds, kw_stage, root, kernel_window.get("issue", "no issue"))
        write_csv(out / "kernel_window.csv",
                  ["seed", "target", "n_per_class", "max_abs_t", "verdict", "expected_verdict", "max_abs_t_unflagged",
                   "flagged", "unqueued", "off_clock", "sm_clock_mhz", "window_median_us", "r", "output_mismatches",
                   "metric_id", "run_dir"],
                  [[r["seed"], r["target"], r["n_per_class"], r["max_abs_t"], r["verdict"], r["expected"],
                    "" if r["unflagged"] is None else r["unflagged"], "" if r["flagged"] is None else r["flagged"],
                    "" if r["unqueued"] is None else r["unqueued"], "" if r["off_clock"] is None else r["off_clock"],
                    r["clock_mhz"], round(r["median_us"], 3), r["r"], r["mismatches"], r["metric"],
                    rel(r["run"]["dir"], root)] for r in kw_rows])
        kw_files = ["kernel_window.csv"]
        kw_dirs = {"issue": kernel_window.get("issue", "no issue"), "selftest": rel(kw_self["dir"], root),
                   "seeds": [rel(r["dir"], root) for r in kw_seeds],
                   "stage_runs": [rel(r["dir"], root) for r in kw_stage]}

    fails = [f"{r['target']}:{r['series']}" for r in rows if r["verdict"] == "FAIL" and r["expected"] == "PASS"]
    controls_ok = all(r["verdict"] == r["expected"] for r in rows if r["target"].startswith("control_"))
    summary = {"provenance": prov, "backend": "cupy", "run_dirs": run_dirs, "controls_ok": controls_ok,
               "fails": fails, "sass_conditional_branches": len(branches), "sass_explained_public": len(branches),
               "ncu_reason": runs["ncu"]["summary"]["reason"], "issues": issues,
               "files": sorted(set(copied) | {"summary_table.csv", "sass_branches_explained.csv",
                                              "ncu_divergence.csv"} | set(kw_files)),
               "generated_by": "python -m vcloak.bench.report_oblivious"}
    if kw_dirs:
        summary["kernel_window"] = kw_dirs
    (out / "oblivious_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if notes:
        section = build_section(runs, prov, root, rows, branches, issues)
        merge_notes(Path(notes), section.replace(END, extra.strip("\n") + "\n" + END) if extra else section)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("selftest", "dudect", "sass", "ncu"):
        ap.add_argument(f"--{name}", required=True, help=f"run dir of the {name} run")
    ap.add_argument("--out", default="results/oblivious")
    ap.add_argument("--explained", default="bench/sass_explained.json")
    ap.add_argument("--notes", default=None, help="merge the M08 section into these notes")
    for key in ("fail", "ncu", "sass"):
        ap.add_argument(f"--issue-{key}", default="no issue", help=f"issue id quoted for the {key} finding")
    ap.add_argument("--kernel-selftest", default=None, help="self-test run dir of the kernel-only window job")
    ap.add_argument("--kernel-window", nargs="*", default=[], help="full-N run dirs of the kernel-only window job")
    ap.add_argument("--stage-runs", nargs="*", default=[], help="per-stage run dirs counted by the ANN-1 note")
    ap.add_argument("--issue-kernel-window", default="no issue")
    a = ap.parse_args(argv)
    issues = {"fail": a.issue_fail, "ncu": a.issue_ncu, "sass": a.issue_sass}
    kw = None
    if a.kernel_window:
        if not a.kernel_selftest:
            ap.error("--kernel-window needs --kernel-selftest")
        kw = {"selftest": a.kernel_selftest, "seeds": a.kernel_window, "stage_runs": a.stage_runs,
              "issue": a.issue_kernel_window}
    try:
        s = generate(a.selftest, a.dudect, a.sass, a.ncu, a.out, a.explained, issues, a.notes, kernel_window=kw)
    except ReportError as e:
        print(f"report_oblivious: {NM} - {e}")
        return 1
    print(f"report_oblivious: session {s['provenance']['session_id']}  {len(s['files'])} files -> {a.out}")
    print(f"  controls {'OK' if s['controls_ok'] else 'NOT AS EXPECTED'}   "
          f"dudect FAIL: {', '.join(s['fails']) or 'none'}")
    print(f"  SASS conditional branches explained {s['sass_explained_public']}/{s['sass_conditional_branches']}"
          f"   ncu: {s['ncu_reason'] or 'measured'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
