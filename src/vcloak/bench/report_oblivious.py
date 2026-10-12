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
{END}
"""


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
             root: str | Path = ".") -> dict[str, Any]:
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

    fails = [f"{r['target']}:{r['series']}" for r in rows if r["verdict"] == "FAIL" and r["expected"] == "PASS"]
    controls_ok = all(r["verdict"] == r["expected"] for r in rows if r["target"].startswith("control_"))
    summary = {"provenance": prov, "backend": "cupy", "run_dirs": run_dirs, "controls_ok": controls_ok,
               "fails": fails, "sass_conditional_branches": len(branches), "sass_explained_public": len(branches),
               "ncu_reason": runs["ncu"]["summary"]["reason"], "issues": issues,
               "files": sorted(set(copied) | {"summary_table.csv", "sass_branches_explained.csv",
                                              "ncu_divergence.csv"}),
               "generated_by": "python -m vcloak.bench.report_oblivious"}
    (out / "oblivious_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if notes:
        merge_notes(Path(notes), build_section(runs, prov, root, rows, branches, issues))
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
    a = ap.parse_args(argv)
    issues = {"fail": a.issue_fail, "ncu": a.issue_ncu, "sass": a.issue_sass}
    try:
        s = generate(a.selftest, a.dudect, a.sass, a.ncu, a.out, a.explained, issues, a.notes)
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
