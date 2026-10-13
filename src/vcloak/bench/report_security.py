"""M14: the security tables, figures and Chapter 4 notes, built only from ingested run dirs.

    python -m vcloak.bench.report_security --s1 runs/<security_s1> --attack runs/<security_e0e1> \
        --uniformity runs/<security_e2> --trace runs/<security_e3> --tests runs/<cuda_tests> \
        --oblivious results/oblivious/oblivious_summary.json --oracle runs/<oracle_compare> \
        --anonymity runs/<security_anon> --out results/security --notes docs/REPORT_CH4_NOTES.md

Nothing here measures. Every table cell and plotted point is read from a run's summary.json or stage JSON, every
gate is copied from the run that evaluated it, and every figure gets a sidecar JSON naming its run dir. The runs must
be `cupy` runs of one runner session with a gpu_job block, and the traffic runs must say mode=vcloak, db=postgres,
engine=gpu (audit A1); otherwise nothing is written. The dudect verdicts of M08 are quoted from the summary that
`report_oblivious` wrote, never retyped. The comparison with the CPU oracle (S7) is copied from the local run of
`bench/run_oracle_compare.py`, which is accepted only if it compared exactly the device runs given here. The
anonymity-set run (S6) may come from a runner session of its own: it passes the same checks and is reported with its
own provenance line, and none of its values is merged into a table of the other session.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

from vcloak.bench.derive import NM
from vcloak.bench.report import (
    C1,
    C2,
    INK2,
    M14_BEGIN,
    M14_END,
    MUTED,
    ReportError,
    _md_table,
    _plt,
    _save,
    load_run,
    rel,
    tagged,
    write_csv,
)

REAL_STACK = {"mode": "vcloak", "db": "postgres", "engine": "gpu"}  # audit A1
STAGE_FILES = {"s1": ("s1_traffic.json",), "attack": ("e1_attack.json", "e0_restoration.json", "attack_table.csv"),
               "uniformity": ("e2_uniformity.json",), "trace": ("e3_trace.json",), "tests": ("cuda_tests.json",),
               "anonymity": ("s6_anonymity.json", "anonymity_table.csv")}
OWN_SESSION = ("anonymity",)  # stages that may come from a runner session of their own
WINDOW_LAYOUTS = ("W1", "W10", "W60", "W300")
ORACLE_FILES = ("oracle_comparison.json", "oracle_comparison.csv")


def _stage(run: dict[str, Any], name: str) -> Any:
    try:
        return json.loads((run["dir"] / name).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ReportError(f"{run['id']}: {name} missing") from e


def _provenance(run: dict[str, Any]) -> dict[str, Any]:
    man = run["manifest"]
    env = man["env"]
    return {"session_id": env["session_id"], "runner": env["runner"], "gpu": env["gpu"], "driver": env.get("driver"),
            "cuda": env.get("cuda"), "cupy": env.get("cupy"), "git_sha": man["git_sha"],
            "job_id": man["gpu_job"]["job_id"], "seed": man["seed"], **REAL_STACK}


def check_inputs(runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Refuse anything that is not one cupy session of an ingested job on the real stack; return its provenance.

    The stages of OWN_SESSION pass every check but the one-session one."""
    for name, r in runs.items():
        man = r["manifest"]
        if man["env"].get("backend") != "cupy" or "gpu_job" not in man:
            raise ReportError(f"{name} run {r['id']} is backend {man['env'].get('backend')} without an ingested "
                              f"GPU job: {NM}, nothing is written")
        if man.get("quick"):
            raise ReportError(f"{name} run {r['id']} is a quick run: not reported")
        if man.get("status") != "OK":
            raise ReportError(f"{name} run {r['id']} has status {man.get('status')}")
    sessions = {r["manifest"]["env"].get("session_id") for name, r in runs.items() if name not in OWN_SESSION}
    if len(sessions) != 1:
        raise ReportError(f"runs come from different runner sessions {sorted(map(str, sessions))}: not merged")
    for name in ("s1", "attack", *(n for n in OWN_SESSION if n in runs)):
        params = runs[name]["manifest"]["params"]
        got = {k: params.get(k) for k in REAL_STACK}
        if got != REAL_STACK:
            raise ReportError(f"{name} run {runs[name]['id']} did not run on the real stack: {got}")
    return _provenance(runs["attack"])


def check_oracle(orun: dict[str, Any], runs: dict[str, dict[str, Any]]) -> None:
    """The oracle comparison is reported only if it is a full, finished run over these very device runs."""
    man = orun["manifest"]
    if man.get("status") != "OK" or man.get("quick"):
        raise ReportError(f"oracle run {orun['id']} has status {man.get('status')}, quick {man.get('quick')}")
    want = {k: runs[k]["id"] for k in ("s1", "attack", "uniformity", "trace")}
    got = man.get("params", {}).get("device_runs")
    if got != want:
        raise ReportError(f"oracle run {orun['id']} compared other device runs: {got}")


def oracle_section(orun: dict[str, Any], cmp: dict[str, Any], runs: dict[str, dict[str, Any]], root: Path,
                   issues: dict[str, str]) -> list[str]:
    """The device values beside the oracle values, both tagged; intervals and verdicts copied from the run."""
    def span(r: dict[str, Any]) -> str:
        return "-" if r["lo"] is None else f"{r['lo']:.6g} to {r['hi']:.6g}"

    def o(metric_id: str) -> str:
        return tagged({"oracle": orun}, metric_id)

    rows = [[r["experiment"], r["quantity"], tagged(runs, r["device_metric"]), o(r["oracle_metric"]), span(r),
             r["verdict"]] for r in cmp["rows"]]
    L = [f"- The oracle `{orun['manifest']['params']['oracle']}` ran unchanged on the laptop CPU with seed "
         f"{cmp['seed']} and the sizes of the device runs (`{rel(orun['dir'], root)}`). It is the reference for the "
         "logic: it is not a GPU run and none of its timings is used.",
         "- The two sides use different keys (the oracle draws its keys from the OS), so a key-dependent number is "
         "expected to come from the same distribution, not to be equal.",
         f"- EQUAL: fixed by the traffic or the schedule, the values agree to 1e-9. WITHIN_NOISE: for E0 and E1 the "
         f"device value lies inside the prediction interval of {cmp['oracle_reps']} repetitions of the oracle's attack "
         f"with fresh keys on the same traffic (level {cmp['family_alpha']} shared over {cmp['spread_rows']} rows); "
         "for E2 both values lie inside the interval that theory or the ideal-sampler calibration gives. "
         "NOT_COMPARABLE: the two sides define the quantity differently.", "",
         _md_table(["experiment", "quantity", "device (T4 + PostgreSQL)", "CPU oracle", "interval", "verdict"], rows),
         "", f"- {len(cmp['rows'])} rows: {o('S-ORACLE-CMP-EQUAL')} EQUAL, {o('S-ORACLE-CMP-WITHIN-NOISE')} "
         f"WITHIN_NOISE, {o('S-ORACLE-CMP-DIFFERS')} DIFFERS, {o('S-ORACLE-CMP-NOT-COMPARABLE')} NOT_COMPARABLE "
         "(`results/security/oracle_comparison.csv`)."]
    for r in (r for r in cmp["rows"] if r["verdict"] == "DIFFERS"):
        sides = [] if r["lo"] is None else [n for n in ("device", "oracle") if not r["lo"] <= r[n] <= r["hi"]]
        where = f"; outside the interval: the {' and the '.join(sides)} value" if sides else ""
        L.append(f"- DIFFERS: {r['experiment']} / {r['quantity']}{where} ({issues.get('oracle', 'no issue')}).")
    L += [f"- NOT_COMPARABLE: {r['quantity']} - {r['criterion']}." for r in cmp["rows"]
          if r["verdict"] == "NOT_COMPARABLE"]
    if cmp["counts"]["DIFFERS"] == 0:
        L.append("- No row differs beyond the noise defined above. That is agreement of one device replay with one "
                 "oracle run at one seed; it is not a proof that the two implementations are equivalent.")
    return L


def gate_rows(stages: dict[str, Any], runs: dict[str, dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    """Every gate the runs evaluated, copied with the run that evaluated it."""
    rows: list[dict[str, Any]] = []

    def add(exp: str, scope: str, gates: dict[str, Any], run: str) -> None:
        rows.extend({"experiment": exp, "scope": scope, "gate": g, "result": "PASS" if ok else "FAIL",
                     "run_dir": rel(runs[run]["dir"], root)} for g, ok in gates.items())

    add("S1", "traffic", stages["s1"].get("checks", {}), "s1")
    for layout in stages["e1"]["layouts"].values():
        add("E1", layout["layout"], layout["checks"], "attack")
    add("E0", "W60", stages["e0"]["checks"], "attack")
    add("E2", "chi2", stages["e2"]["chi2"]["gates"], "uniformity")
    add("E2", "tau band", stages["e2"]["tau_band"]["gates"], "uniformity")
    add("E3", "sort", stages["e3"]["sort"]["gates"], "trace")
    add("E3", "write_epoch", stages["e3"]["write_epoch"]["gates"], "trace")
    if "tests" in stages:
        add("tests", "pytest -m gpu", stages["tests"]["checks"], "tests")
    if "s6" in stages:
        for pop in stages["s6"]["populations"]:
            add("S6", f"{pop['users']} users", pop["checks"], "anonymity")
    return rows


def anonymity_section(run: dict[str, Any], s6: dict[str, Any], prov: dict[str, Any],
                      issues: dict[str, str]) -> list[str]:
    """S6: the counts of real rows per window and per bucket-window, tagged, with the provenance of its own run."""
    def t(metric_id: str) -> str:
        return tagged({"anonymity": run}, metric_id)

    own = _provenance(run)
    par = s6["params"]
    where = ("the runner session of the sections above" if own["session_id"] == prov["session_id"] else
             "a runner session of its own, not the one of the sections above")
    L = [f"- Runner: {own['runner']}, {own['gpu']}, driver {own['driver']}, CUDA runtime {own['cuda']}, CuPy "
         f"{own['cupy']}; runner session {own['session_id']} ({where}), GPU job {own['job_id']}, packed from commit "
         f"`{own['git_sha'][:7]}`.",
         f"- Stack: mode={own['mode']}, db={own['db']} (PostgreSQL {s6.get('db_server_version', NM)}, in the "
         f"runner), engine={own['engine']}.",
         f"- Traffic: {s6['mapping']}; {par['duration_s']} simulated seconds, seed {own['seed']}, "
         f"{par['buckets']} buckets, layout W = {par['window_s']} s. One replay per population, one seed: no "
         "confidence interval is given.", ""]
    rows, seen = [], []
    for pop in s6["populations"]:
        u, an = pop["users"], pop["anonymity"]
        w, bw = an["per_window"], an["per_bucket_window"]
        rows.append([str(u), str(pop["conversations"]), t(f"S-ANON-MSGS-U{u}"), t(f"S-ANON-MED-U{u}"),
                     t(f"S-ANON-P5-U{u}"), t(f"S-ANON-BW-MED-U{u}"), t(f"S-ANON-BW-P5-U{u}"),
                     f"{bw['empty']} of {bw['cells']}", t(f"S-ANON-BW-PEAK-U{u}"), t(f"S-TURNACC-W60-U{u}"),
                     t(f"S-F-W60-U{u}"), f"{pop['attack']['predicted_turn_accuracy']:.4f}"])
        seen.append(f"{u} users: {w['msg_median']:g} / {w['msg_p5']:g} per window, {bw['msg_median']:g} / "
                    f"{bw['msg_p5']:g} per bucket-window")
    L += [_md_table(["users", "conversations", "messages", "per window: median", "per window: p5",
                     "per bucket-window: median", "per bucket-window: p5", "empty bucket-windows",
                     "fullest bucket-window", "turn-order accuracy", "f (turns inside one round)",
                     "predicted 1 − f/2"], rows), "",
          "- A cell is a window, or one bucket of one window; the values are real rows in a cell, counted over every "
          "cell of the run, the empty ones as 0. p5 is the 5th percentile with linear interpolation.",
          "- The same count as a real row sees it (median / p5 of the size of the cell the row is stored in, from "
          f"`s6_anonymity.json`): {'; '.join(seen)}.",
          "- The attack is the one of 4.S.3 on the dump of each population. S6 has no acceptance gate of its own; "
          "the checks of the stage are in the gate table."]
    for pop in s6["populations"]:
        if pop["peak_bucket_window_above_cand_k"]:
            L.append(f"- Limit: at {pop['users']} users the fullest bucket-window holds "
                     f"{pop['occupancy']['peak']} real rows, above CAND_K {pop['cand_k']}, so a read of that "
                     f"bucket-window would answer `candidate_overflow`. This population was dumped and counted, "
                     f"never read ({issues.get('overflow', 'no issue')}).")
    return L


def _sidecar(out: Path, name: str, files: list[str], run: dict[str, Any], root: Path, metric_ids: list[str],
             prov: dict[str, Any]) -> dict[str, Any]:
    side = {"figure": name, "files": files, "run_dirs": [rel(run["dir"], root)], "metric_ids": metric_ids,
            "session_id": prov["session_id"], "generated_by": "python -m vcloak.bench.report_security"}
    (out / f"{name}.json").write_text(json.dumps(side, indent=2) + "\n", encoding="utf-8")
    return side


def _foot(fig: Any, prov: dict[str, Any], extra: str, device: str) -> None:
    fig.text(0.01, 0.005, f"{extra}\n{device}, {prov['runner']} session {prov['session_id']}, seed {prov['seed']}",
             fontsize=6, color=MUTED, ha="left", va="bottom", linespacing=1.3)


def fig_window_ablation(plt: Any, e1: dict[str, Any], run: dict[str, Any], prov: dict[str, Any], out: Path,
                        root: Path) -> dict[str, Any]:
    lay = e1["layouts"]
    ws = [lay[k]["window_s"] for k in WINDOW_LAYOUTS]
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    ax.plot(ws, [lay[k]["attack"]["turn_order_accuracy"] for k in WINDOW_LAYOUTS], color=C1, marker="o",
            label="measured: V-cloak, visible round = window W", zorder=3)
    # the prediction falls on the measured points, so it is drawn as rings around them, not as a second line
    ax.plot(ws, [lay[k]["attack"]["predicted_turn_accuracy"] for k in WINDOW_LAYOUTS], linestyle="none", marker="o",
            markersize=11, markerfacecolor="none", markeredgecolor=INK2, markeredgewidth=1.2,
            label="predicted 1 − f/2 (f = turns inside one visible round)", zorder=4)
    for key, label, colour, dy, va in (("BASELINE", "baseline service (arrival order stored)", C2, 3, "bottom"),
                                       ("EPOCH", "V-cloak, visible round = epoch", INK2, -3, "top")):
        y = lay[key]["attack"]["turn_order_accuracy"]
        ax.axhline(y, color=colour, linewidth=1.2, linestyle=":", zorder=1)
        ax.annotate(label, (ws[-1], y), xytext=(0, dy), textcoords="offset points", ha="right", va=va, fontsize=7,
                    color=colour)
    ax.axhline(0.5, color=MUTED, linewidth=0.8, zorder=1)
    ax.annotate("coin flip", (ws[0], 0.5), xytext=(0, 3), textcoords="offset points", fontsize=7, color=MUTED)
    ax.set_xscale("log")
    ax.set_xticks(ws)
    ax.set_xticklabels([str(w) for w in ws])
    ax.minorticks_off()
    ax.set_ylim(0.45, 1.06)
    ax.set_xlabel("re-shuffle window W (s)")
    ax.set_ylabel("turn-order accuracy of the attacker")
    ax.set_title("Order recovered from the stored layout falls with the window")
    ax.legend(loc="lower left", bbox_to_anchor=(0.02, 0.12))
    _foot(fig, prov, f"{lay['W60']['attack']['rows']} rows dumped per layout, one replay",
          f"{prov['gpu']} + PostgreSQL")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    files = _save(fig, out, "fig_window_ablation")
    plt.close(fig)
    ids = [f"S-TURNACC-{k}" for k in lay] + [f"S-F-{k}" for k in WINDOW_LAYOUTS]
    return _sidecar(out, "fig_window_ablation", files, run, root, ids, prov)


def fig_tau_histogram(plt: Any, e2: dict[str, Any], run: dict[str, Any], prov: dict[str, Any], out: Path,
                      root: Path) -> dict[str, Any]:
    band = e2["tau_band"]
    edges, counts = band["histogram"]["z_edges"], band["histogram"]["counts"]

    def cdf(z: float) -> float:
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    mids = [(a + b) / 2 for a, b in zip(edges[:-1], edges[1:], strict=True)]
    ideal = [band["epochs"] * (cdf(b) - cdf(a)) for a, b in zip(edges[:-1], edges[1:], strict=True)]
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    ax.bar(mids, counts, width=(edges[1] - edges[0]) * 0.92, color=C1, label="device permutations", zorder=2)
    ax.plot(mids, ideal, color=INK2, linestyle="--", linewidth=1.2, label="uniform permutation (normal limit)",
            zorder=3)
    for z in (-3, 3):
        ax.axvline(z, color=MUTED, linewidth=0.8, zorder=1)
    ax.annotate("±3σ", (3, max(counts)), xytext=(3, -2), textcoords="offset points", fontsize=7, color=MUTED)
    ax.set_xlabel("Kendall τ of one epoch's permutation, in units of the theoretical σ")
    ax.set_ylabel("epochs")
    ax.set_title(f"τ of {band['epochs']} permutations of n = {band['n']}")
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)
    _foot(fig, prov, f"{band['inside_band']} of {band['epochs']} epochs inside ±3σ; development key (public)",
          prov["gpu"])
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    files = _save(fig, out, "fig_tau_histogram")
    plt.close(fig)
    return _sidecar(out, "fig_tau_histogram", files, run, root, ["S-TAUBAND-PCT", "S-TAU-SIGMA-MEAS"], prov)


def oblivious_link(path: Path | None) -> list[str]:
    """The M08 timing verdicts, read from the summary of report_oblivious (audit A4)."""
    if path is None or not path.exists():
        return [f"- Timing (M08): {NM} here - no oblivious summary was given to the generator."]
    obl = json.loads(path.read_text(encoding="utf-8"))
    issues = obl.get("issues", {})
    fails = ", ".join(f"`{x}`" for x in obl.get("fails", [])) or "none"
    return [
        f"- Timing is not part of this experiment. The dudect runs of M08 (section 4.O, summary `{path.as_posix()}`, "
        f"job {obl['provenance']['job_id']}) gave the verdict FAIL for these series: {fails} "
        f"({issues.get('fail', 'no issue')}). The reading of those verdicts, with its diagnostics and limits, is "
        "section 4.O.3; it is not repeated here.",
        f"- Nsight Compute divergence: {NM} ({obl.get('ncu_reason') or 'see 4.O.5'}; {issues.get('ncu', 'no issue')}).",
        "- So the result of this section is about the logical trace only: which pairs are compared and which "
        "launches are issued does not depend on the data. The timing property is claimed for the kernels only, and "
        "host timing is a stated limitation (ADR-023).",
    ]


def build_section(runs: dict[str, dict[str, Any]], stages: dict[str, Any], prov: dict[str, Any], root: Path,
                  gates: list[dict[str, Any]], figures: list[dict[str, Any]], oblivious: Path | None,
                  issues: dict[str, str], orun: dict[str, Any] | None = None,
                  cmp: dict[str, Any] | None = None) -> str:
    def t(metric_id: str) -> str:
        return tagged(runs, metric_id)

    lay, e0, e2, e3 = stages["e1"]["layouts"], stages["e0"], stages["e2"], stages["e3"]
    failed = [g for g in gates if g["result"] != "PASS"]
    L = [M14_BEGIN, "# Chapter 4 notes: security evaluation on the real system (M14)", "",
         "Generated by `python -m vcloak.bench.report_security` from ingested run dirs. Do not edit by hand: every "
         "value", "carries a `<!--M:ID-->` tag that names its row in `state/METRICS_INDEX.md`. Gates are copied from "
         "the runs.", "", "## 4.S.1 Setup",
         f"- Runner: {prov['runner']}, {prov['gpu']}, driver {prov['driver']}, CUDA runtime {prov['cuda']}, CuPy "
         f"{prov['cupy']}; runner session {prov['session_id']}, GPU job {prov['job_id']}, packed from commit "
         f"`{prov['git_sha'][:7]}`.",
         f"- Stack: mode={prov['mode']}, db={prov['db']} (PostgreSQL {stages['e1'].get('db_server_version', NM)}, in "
         f"the runner), engine={prov['engine']}; the service objects run in-process with the simulated clock and the "
         "scheduler is stepped by the replay.",
         f"- Traffic: seed {prov['seed']}, {stages['s1']['params']['n_conv']} conversations over "
         f"{stages['s1']['params']['duration_s']} simulated seconds, {t('S-TRAFFIC-MSGS')} messages; the same traffic "
         "is replayed into every layout. One replay, one seed: no confidence interval is given.", "- Runs:"]
    L += [f"  - `{rel(r['dir'], root)}` ({name}, status {r['manifest']['status']})" for name, r in runs.items()]
    L += ["", "## 4.S.2 E0: restoration through the read path",
          f"- {t('S-E0-RESTORE')} of {e0['conversations_checked']} conversations read back in exact order on the "
          f"W = 60 s layout ({e0['messages_checked']} messages, {e0['reads']} window reads, "
          f"{len(e0['reads_failed'])} failed).",
          f"- CAND_K {t('S-CANDK')}; bucket-window occupancy on that layout: peak {t('S-OCC-PEAK')}, mean "
          f"{t('S-OCC-MEAN')}.", "", "## 4.S.3 E1: order recovery from the stored layout",
          "The attacker reads the table in physical order (`ORDER BY ctid`) and guesses that order is arrival order.",
          ""]
    rows = []
    for key, v in lay.items():
        a = v["attack"]
        rows.append([key, str(a["visible_rounds"]), t(f"S-TAU-GLOBAL-{key}"), t(f"S-TAU-WITHIN-{key}"),
                     t(f"S-TURNACC-{key}"), t(f"S-F-{key}"), f"{a['predicted_turn_accuracy']:.4f}"])
    L += [_md_table(["layout", "visible rounds", "τ global", "τ within a round", "turn-order accuracy",
                     "f (turns inside one round)", "predicted 1 − f/2"], rows), "",
          "- BASELINE stores arrival order; EPOCH is V-cloak with the epoch as the visible round (the Review-1 "
          "design); W*n* is V-cloak re-shuffling each window of *n* seconds.",
          "- For BASELINE the prediction does not apply: nothing is shuffled inside its rounds.",
          "- Global τ stays high in every layout because the order of the rounds themselves is public; the "
          "protection is inside a round, where τ is near zero."]
    over = [(k, v["occupancy"]["peak"]) for k, v in lay.items()
            if "occupancy" in v and v["occupancy"]["peak"] > e0["cand_k"]]
    for k, peak in over:
        L.append(f"- Limit of the ablation: on layout {k} the peak bucket-window occupancy is {peak}, above CAND_K "
                 f"{e0['cand_k']}, so a read at that window size would answer `candidate_overflow`. That layout is "
                 f"only dumped, never read ({issues.get('overflow', 'no issue')}).")
    chi, band = e2["chi2"], e2["tau_band"]
    L += ["", "## 4.S.4 E2: uniformity of the permutations from device tags",
          f"- χ² at n = {chi['n']} over {chi['reps']} epochs, with the (n−1)/n correction: statistic {t('S-CHI2')} at "
          f"{chi['dof']} degrees of freedom, p = {t('S-CHI2-P')}. Calibration with {chi['ideal_sampler']['tables']} "
          f"tables of an ideal sampler: statistic between {chi['ideal_sampler']['chi2_min']:.1f} and "
          f"{chi['ideal_sampler']['chi2_max']:.1f} (the first table has p = {t('S-CHI2-P-IDEAL')}).",
          f"- τ band at n = {band['n']} over {band['epochs']} epochs: {t('S-TAUBAND-PCT')} % inside ±3σ "
          f"({band['inside_band']} epochs; the central 99 % interval of Binomial({band['epochs']}, 0.9973) is "
          f"{band['binomial_99_bounds'][0]} to {band['binomial_99_bounds'][1]}); measured σ {t('S-TAU-SIGMA-MEAS')} "
          f"against the theoretical {band['sigma_theory']:.6f}.",
          f"- The permutations come from the {e2['key']}. A pass says that these tests did not reject uniformity at "
          "these sizes, not that the permutation is proven uniform.",
          "", "## 4.S.5 E3: comparator trace (logical)",
          f"- Device sort at n = {e3['sort']['n']}: {t('S-TRACE-DISTINCT-DEVICE')} distinct trace over "
          f"{len(e3['sort']['rows'])} inputs, equal to the trace of the oracle; merge sort on the same inputs: "
          f"{t('S-TRACE-DISTINCT-MERGESORT')} distinct traces.",
          f"- `write_epoch` at {e3['write_epoch']['slots']} slots: the launch list and the pair schedule are "
          f"identical over {len(e3['write_epoch']['rows'])} batches. The hook records public launch arguments only; "
          f"digests are {e3['sort']['digest']}."]
    L += oblivious_link(oblivious)
    if "tests" in stages:
        L += ["", "## 4.S.6 Tests marked `gpu` on the device",
              f"- {t('S-CUDA-TESTS-PASSED')} passed, {t('S-CUDA-TESTS-FAILED')} failed, {t('S-CUDA-TESTS-ERRORS')} "
              f"errors, {t('S-CUDA-TESTS-SKIPPED')} skipped, in one pytest process on the runner."]
    L += ["", "## 4.S.7 Acceptance gates",
          f"{len(gates)} gates evaluated by the runs, {len(gates) - len(failed)} PASS, {len(failed)} FAIL "
          "(`results/security/gates.csv`)."]
    L += [f"- FAIL: {g['experiment']} / {g['scope']} / {g['gate']} (`{g['run_dir']}`)" for g in failed]
    L += ["", "## 4.S.8 Figures"]
    L += [f"- `results/security/{f['files'][0]}` from `{f['run_dirs'][0]}`" for f in figures]
    missing, n = [], 9
    if orun is not None and cmp is not None:
        L += ["", f"## 4.S.{n} Comparison with the CPU oracle", *oracle_section(orun, cmp, runs, root, issues)]
        n += 1
    else:
        missing.append("the comparison with the CPU oracle (S7)")
    if "s6" in stages:
        L += ["", f"## 4.S.{n} S6: anonymity set", *anonymity_section(runs["anonymity"], stages["s6"], prov, issues)]
        n += 1
    else:
        missing.insert(0, "the anonymity-set study (S6)")
    if missing:
        text = " and ".join(missing)
        L += ["", f"## 4.S.{n} Not in this section",
              f"- {text[0].upper()}{text[1:]}: {NM} ({issues.get('pending', 'no issue')})."]
    L.append(M14_END)
    return "\n".join(L) + "\n"


def merge_notes(path: Path, section: str) -> None:
    """Replace the M14 block of the notes, or append it; the rest of the file is left as it is."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if M14_BEGIN in old and M14_END in old:
        new = old[:old.index(M14_BEGIN)] + section.strip("\n") + old[old.index(M14_END) + len(M14_END):]
    else:
        new = old.rstrip("\n") + ("\n\n" if old else "") + section.strip("\n") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")


def generate(s1: str | Path, attack: str | Path, uniformity: str | Path, trace: str | Path, out: str | Path,
             tests: str | Path | None = None, oblivious: str | Path | None = None, notes: str | Path | None = None,
             issues: dict[str, str] | None = None, root: str | Path = ".",
             oracle: str | Path | None = None, anonymity: str | Path | None = None) -> dict[str, Any]:
    root, out, issues = Path(root), Path(out), issues or {}
    runs = {"s1": load_run(s1), "attack": load_run(attack), "uniformity": load_run(uniformity),
            "trace": load_run(trace)}
    if tests:
        runs["tests"] = load_run(tests)
    if anonymity:
        runs["anonymity"] = load_run(anonymity)
    prov = check_inputs(runs)
    orun = load_run(oracle) if oracle else None
    cmp = None
    if orun is not None:
        check_oracle(orun, runs)
        cmp = _stage(orun, ORACLE_FILES[0])
    stages = {"s1": _stage(runs["s1"], "s1_traffic.json"), "e1": _stage(runs["attack"], "e1_attack.json"),
              "e0": _stage(runs["attack"], "e0_restoration.json"),
              "e2": _stage(runs["uniformity"], "e2_uniformity.json"), "e3": _stage(runs["trace"], "e3_trace.json")}
    if tests:
        stages["tests"] = _stage(runs["tests"], "cuda_tests.json")
    if anonymity:
        stages["s6"] = _stage(runs["anonymity"], "s6_anonymity.json")
    stages["e1"]["layouts"] = {v["layout"]: v for v in stages["e1"]["layouts"]}
    gates = gate_rows(stages, runs, root)
    out.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    for name, run in runs.items():
        for f in STAGE_FILES[name]:
            shutil.copyfile(run["dir"] / f, out / f)
            files.append(f)
    if orun is not None:
        for f in ORACLE_FILES:
            shutil.copyfile(orun["dir"] / f, out / f)
            files.append(f)
    write_csv(out / "gates.csv", ["experiment", "scope", "gate", "result", "run_dir"],
              [[g[k] for k in ("experiment", "scope", "gate", "result", "run_dir")] for g in gates])
    files.append("gates.csv")
    plt = _plt()
    figures = [fig_window_ablation(plt, stages["e1"], runs["attack"], prov, out, root),
               fig_tau_histogram(plt, stages["e2"], runs["uniformity"], prov, out, root)]
    for f in figures:
        files += [*f["files"], f"{f['figure']}.json"]
    obl = Path(oblivious) if oblivious else None
    summary = {"provenance": prov, "backend": "cupy", "run_dirs": {k: rel(r["dir"], root) for k, r in runs.items()},
               "gates": len(gates), "gates_failed": [g for g in gates if g["result"] != "PASS"],
               "oblivious_summary": obl.as_posix() if obl else None, "issues": issues, "files": sorted(files),
               "not_measured": ([] if anonymity else ["S6 anonymity set"])
               + ([] if cmp else ["S7 comparison with the CPU oracle"]),
               "anonymity_provenance": _provenance(runs["anonymity"]) if anonymity else None,
               "oracle_comparison": {"run_dir": rel(orun["dir"], root), "counts": cmp["counts"],
                                     "rows": len(cmp["rows"])} if orun is not None and cmp is not None else None,
               "generated_by": "python -m vcloak.bench.report_security"}
    (out / "security_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if notes:
        merge_notes(Path(notes), build_section(runs, stages, prov, root, gates, figures, obl, issues, orun, cmp))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("s1", "attack", "uniformity", "trace"):
        ap.add_argument(f"--{name}", required=True, help=f"run dir of the {name} stage")
    ap.add_argument("--tests", default=None, help="run dir of the tests marked gpu")
    ap.add_argument("--oblivious", default=None, help="oblivious_summary.json written by report_oblivious")
    ap.add_argument("--oracle", default=None, help="run dir of bench/run_oracle_compare.py (S7)")
    ap.add_argument("--anonymity", default=None, help="run dir of the anonymity stage (S6), own session allowed")
    ap.add_argument("--out", default="results/security")
    ap.add_argument("--notes", default=None, help="merge the M14 section into these notes")
    ap.add_argument("--issue-overflow", default="no issue", help="issue quoted for an occupancy above CAND_K")
    ap.add_argument("--issue-oracle", default="no issue", help="issue quoted for a row that differs from the oracle")
    ap.add_argument("--issue-pending", default="no issue", help="issue quoted for the steps not measured yet")
    a = ap.parse_args(argv)
    try:
        s = generate(a.s1, a.attack, a.uniformity, a.trace, a.out, a.tests, a.oblivious, a.notes,
                     {"overflow": a.issue_overflow, "pending": a.issue_pending, "oracle": a.issue_oracle},
                     oracle=a.oracle, anonymity=a.anonymity)
    except ReportError as e:
        print(f"report_security: {NM} - {e}")
        return 1
    print(f"report_security: session {s['provenance']['session_id']}  {len(s['files'])} files -> {a.out}")
    print(f"  gates {s['gates'] - len(s['gates_failed'])}/{s['gates']} PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
