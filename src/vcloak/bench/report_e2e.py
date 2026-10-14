"""M15 S3 (E6): the end-to-end metrics, derived from the ingested cells, and the tables and notes made from them.

    python -m vcloak.bench.report_e2e derive --cells runs/<..._M15_e2e_cells> [--out runs]
                                             [--index state/METRICS_INDEX.md]
    python -m vcloak.bench.report_e2e render --metrics runs/<..._M15_e2e_metrics> [--out results/e2e]
                                             [--notes docs/REPORT_CH4_NOTES.md] [--issue-scale ISSUE-51]
                                             [--issue-lost ISSUE-52]

`derive` reads the cells of one driver run of `bench/run_e2e_cells.py` (samples.csv, cpu.csv, telemetry.csv and
summary.json of every cell) and writes a derivation run: `summary.json` with the E2E-* metrics and `cells.csv`
with one row per cell. It measures nothing. Its manifest is a local one and names the device runs it read in
`derived_from`; `scripts/check_metrics.py` accepts a GPU metric from such a run only when every one of those runs
is an ingested cupy run of one runner session (ADR-028). With `--index` the rows are appended to the metrics
index, copied from that summary, with the backend and the runner of the device runs.

How a metric is made (ai/modules/M15, with its amendments):
- a statistic is computed per cell, over the samples scheduled in the measured interval (audit A2);
- the value of a metric is the mean of the two repetitions; when they are more than 15 % apart
  (`|r1 - r2| / min`), the value is UNSTABLE (audit A3). A value made from an UNSTABLE value is UNSTABLE;
- a user count is not valid when the load generator used more than one core in any of its cells: the latencies
  then contain the generator's own queueing. Every metric of that user count is UNSTABLE, with that cause
  (ISSUE-51, decision of the owner), and `render` leaves it out of every table;
- the throughput is `vcloak.bench.e2e.completed` over the measured seconds, recomputed here from samples.csv:
  the `achieved_msgs_s` of an ingested summary counted by scheduled time and is never read.

`render` copies nothing it did not find in the derivation run: a metric that is missing prints as NOT_MEASURED.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from vcloak import runs as runs_mod
from vcloak.bench import e2e
from vcloak.bench.derive import NM, UNSTABLE
from vcloak.bench.report import ReportError, load_run, rel, tagged, write_csv

A3_GATE_PCT = 15.0  # ai/modules/M15, audit A3
GENERATOR_CORE_LIMIT_PCT = 100.0  # ISSUE-51: above one core the single-process generator is the limit
GENERATOR_CAUSE = "load generator at its limit"
CONDITIONS = ("ack", "sessions", "ws_sockets", "store", "users_per_conversation", "rate_per_user_s", "duration_s",
              "warmup_s", "drain_s", "poll_ms", "clock")
ENV = ("backend", "runner", "session_id", "gpu", "cuda", "cupy", "driver", "cpu_count")
SERIES = (("ack_ms", ""), ("readable_ms", "READABLE-"))  # (statistics key, part of the metric id)
QUANTILES = ("p50", "p95", "p99")
ADDED = ("p50", "p99")  # ai/modules/M15 S3: the added latency is stated at p50 and p99
M15_BEGIN, M15_END = "<!-- BEGIN M15 E2E -->", "<!-- END M15 E2E -->"
CELL_COLUMNS = ("users", "users_per_conversation", "mode", "rep", "run_dir", "scheduled", "acked", "send_errors",
                "readable_missing", "read_requests", "read_errors", "epochs", "epoch_overflow", "missed_epochs",
                "send_lag_p99_ms", "generator_cpu_pct", "service_cpu_pct", "machine_cpu_pct", "telemetry_samples")


def spread_pct(a: float, b: float) -> float:
    """How far two repetitions are apart, in percent of the smaller one (A3). Two zeros agree."""
    if a == b:
        return 0.0
    lo = min(abs(a), abs(b))
    return float("inf") if lo == 0 else abs(a - b) / lo * 100.0


def combine(values: list[float], digits: int = 3) -> dict[str, Any]:
    """The value of a metric from its repetitions: their mean, or UNSTABLE when they are apart by more than A3."""
    if len(values) != 2:
        raise ReportError(f"a cell needs exactly two repetitions, found {len(values)}")
    sp = spread_pct(*values)
    return {"value": round(statistics.fmean(values), digits) if sp <= A3_GATE_PCT else UNSTABLE,
            "reps": [round(v, digits) for v in values], "spread_pct": None if sp == float("inf") else round(sp, 2)}


def _inside(path: Path, lo: float, hi: float) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if lo <= float(r["ts"]) <= hi]


def _mean(rows: list[dict[str, str]], key: str) -> float | None:
    vals = [float(r[key]) for r in rows if r.get(key) not in (None, "")]
    return statistics.fmean(vals) if vals else None


def cell_record(run: dict[str, Any], root: Path) -> dict[str, Any]:
    """Everything S3 uses from one cell, read from its files; the statistics are recomputed from samples.csv."""
    s, d = run["summary"], run["dir"]
    lo, hi = s["measured_unix"]
    stats = e2e.summarise(e2e.load_samples(d / "samples.csv"), s["warmup_s"], s["duration_s"])
    cpu = _inside(d / "cpu.csv", lo, hi) if (s.get("cpu") or {}).get("available") else []
    tel = _inside(d / "telemetry.csv", lo, hi) if s["telemetry"].get("available") else []
    util = sorted(float(r["util_gpu_pct"]) for r in tel if r.get("util_gpu_pct") not in (None, ""))
    power = [float(r["power_w"]) for r in tel if r.get("power_w") not in (None, "")]
    return {
        "users": s["users"], "users_per_conversation": s["users_per_conversation"], "mode": s["mode"],
        "rep": s["rep"], "run_dir": rel(d, root), "stats": stats,
        "reads": s["reads"], "delta": s["service"]["delta"], "epoch_ms": s["service"]["windows"].get("epoch_ms"),
        "generator_cpu_pct": _mean(cpu, "generator_cpu_pct"), "service_cpu_pct": _mean(cpu, "service_cpu_pct"),
        "machine_cpu_pct": _mean(cpu, "cpu_pct"), "cpu_samples": len(cpu), "telemetry_samples": len(tel),
        "gpu_util_median": statistics.median(util) if util else None,
        "gpu_util_p95": util[min(len(util) - 1, int(0.95 * len(util)))] if util else None,
        "power_w_median": statistics.median(power) if power else None,
    }


def load_cells(driver: str | Path, root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """The driver run, its cells, and their one provenance. Anything that is not one ingested cupy session
    under one set of conditions is refused (audit A1): nothing is derived from it."""
    drv = load_run(driver)
    with (drv["dir"] / "cells.csv").open(newline="", encoding="utf-8") as f:
        listed = list(csv.DictReader(f))
    if not listed:
        raise ReportError(f"{drv['id']}: cells.csv lists no cell")
    cells = [load_run(drv["dir"].parent / r["run_dir"]) for r in listed]
    for r in [drv, *cells]:
        env = r["manifest"]["env"]
        if env.get("backend") != "cupy" or "gpu_job" not in r["manifest"] or env.get("runner") == "local":
            raise ReportError(f"run {r['id']} is backend {env.get('backend')}, runner {env.get('runner')}, without "
                              f"an ingested GPU job: {NM}, no end-to-end metric is derived")
    for c, row in zip(cells, listed, strict=True):
        if c["manifest"]["status"] != "OK" or int(row["exit_code"]) != 0:
            raise ReportError(f"cell {c['id']} did not complete (status {c['manifest']['status']}): it is reported "
                              "to the owner first (ADR-027), not derived from")
    envs = {json.dumps([r["manifest"]["env"].get(k) for k in ENV]) for r in [drv, *cells]}
    conds = {json.dumps([c["summary"].get(k) for k in CONDITIONS], sort_keys=True) for c in cells}
    jobs = {r["manifest"]["gpu_job"].get("job_id") for r in [drv, *cells]}
    if len(envs) != 1 or len(conds) != 1 or len(jobs) != 1:
        raise ReportError(f"the cells do not share one environment ({len(envs)}), one set of conditions "
                          f"({len(conds)}) and one job ({len(jobs)}): not comparable (audit A1)")
    man, summ = drv["manifest"], cells[0]["summary"]
    prov = {**{k: man["env"].get(k) for k in ENV}, "job_id": jobs.pop(), "git_sha": man["git_sha"],
            "seed": man["seed"], "quick": bool(man["quick"]), "driver_run": rel(drv["dir"], root),
            "conditions": {k: summ.get(k) for k in CONDITIONS}, "slots": man["params"].get("slots"),
            "epoch_ms": summ["service"]["windows"].get("epoch_ms"),
            "window_s": summ["service"]["windows"].get("window_s")}
    return drv, [cell_record(c, root) for c in cells], prov


def _metric(mid: str, unit: str, stat: str, c: dict[str, Any], cause: str | None) -> dict[str, Any]:
    out = {"id": mid, "value": UNSTABLE if cause else c["value"], "unit": unit, "stat": stat, "reps": c.get("reps"),
           "spread_pct": c.get("spread_pct")}
    if out["value"] == UNSTABLE:
        out["cause"] = cause or c.get("cause") or f"the two repetitions are more than {A3_GATE_PCT:g} % apart (A3)"
    return out


def derive_metrics(cells: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The E2E-* rows and, per user count, whether its cells are valid (see the module docstring)."""
    by: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for c in sorted(cells, key=lambda c: (c["users"], c["mode"], c["rep"])):
        by.setdefault((c["users"], c["mode"]), []).append(c)
    users = sorted({u for u, _ in by})
    validity: dict[str, Any] = {}
    metrics: list[dict[str, Any]] = []
    for u in users:
        mine = [c for (cu, _), cs in by.items() if cu == u for c in cs]
        gen = [c["generator_cpu_pct"] for c in mine]
        if any(g is None for g in gen):
            cause: str | None = "the CPU of the load generator was not sampled, so its cells cannot be shown valid"
        elif max(gen) > GENERATOR_CORE_LIMIT_PCT:
            cause = (f"{GENERATOR_CAUSE}: the single-process generator used more than one core "
                     f"(above {GENERATOR_CORE_LIMIT_PCT:g} % of a core) inside the measured interval")
        else:
            cause = None
        validity[str(u)] = {"valid": cause is None, "cause": cause, "users_per_conversation": 2,
                            "generator_cpu_pct": [None if g is None else round(g, 1) for g in gen],
                            "service_cpu_pct": [None if c["service_cpu_pct"] is None else
                                                round(c["service_cpu_pct"], 1) for c in mine],
                            "cells": [c["run_dir"] for c in mine]}
        lat: dict[tuple[str, str, str], dict[str, Any]] = {}
        for mode in e2e.MODES:
            reps = by.get((u, mode), [])
            for key, part in SERIES:
                for q in QUANTILES:
                    vals = [c["stats"][key][q] for c in reps]
                    if NM in vals:
                        raise ReportError(f"{u} users, {mode}: no {key} sample in a repetition")
                    lat[(mode, key, q)] = comb = combine(vals)
                    what = "submit to ack (ack: stored)" if key == "ack_ms" else "submit to readable by the peer"
                    metrics.append(_metric(f"E2E-{part}{q.upper()}-U{u}-{mode}", "ms",
                                           f"{q} of {what}, mean of 2 repetitions", comb, cause))
            tput = combine([c["stats"]["achieved_msgs_s"] for c in reps])
            metrics.append(_metric(f"E2E-TPUT-U{u}-{mode}", "msgs/s", "acks that arrived in the measured interval "
                                   "over its seconds, mean of 2 repetitions", tput, cause))
        for key, part in SERIES:
            for q in ADDED:
                v, b = lat[("vcloak", key, q)], lat[("baseline", key, q)]
                if UNSTABLE in (v["value"], b["value"]):
                    who = " and ".join(m for m, x in (("vcloak", v), ("baseline", b)) if x["value"] == UNSTABLE)
                    comb = {"value": UNSTABLE, "reps": None, "spread_pct": None,
                            "cause": f"made from an UNSTABLE value ({who} {q}: repetitions more than "
                                     f"{A3_GATE_PCT:g} % apart)"}
                else:
                    comb = {"value": round(v["value"] - b["value"], 3), "reps": None, "spread_pct": None}
                metrics.append(_metric(f"E2E-ADDED-{part}{q.upper()}-U{u}", "ms",
                                       f"vcloak minus baseline, {q}, each the mean of 2 repetitions", comb, cause))
        vc = by.get((u, "vcloak"), [])
        over = [c["delta"]["overflow"] for c in vc]
        metrics.append(_metric(f"E2E-OVERFLOW-U{u}", "submissions", "left for a later epoch, sum of 2 repetitions",
                               {"value": sum(over), "reps": over, "spread_pct": None}, cause))
        for name, key, unit, stat in (("GPUUTIL", "gpu_util_median", "%", "median of NVML utilisation at 10 Hz"),
                                      ("GPUUTIL-P95", "gpu_util_p95", "%", "p95 of NVML utilisation at 10 Hz"),
                                      ("POWER-W", "power_w_median", "W", "median NVML power draw at 10 Hz")):
            vals = [c[key] for c in vc]
            comb = ({"value": NM, "reps": None, "spread_pct": None} if any(v is None for v in vals)
                    else combine(vals))
            metrics.append(_metric(f"E2E-{name}-U{u}", unit, f"{stat} in the measured interval, vcloak cells, "
                                   "mean of 2 repetitions", comb, None if comb["value"] == NM else cause))
    return metrics, validity


def derive(cells_run: str | Path, out: str | Path = "runs", root: str | Path = ".") -> Path:
    root = Path(root)
    drv, cells, prov = load_cells(cells_run, root)
    metrics, validity = derive_metrics(cells)
    sources = [prov["driver_run"], *[c["run_dir"] for c in cells]]
    run_dir = runs_mod.new_run("M15", "e2e_metrics", step="S3", owner="Divyansh", seed=prov["seed"],
                               quick=prov["quick"], root=root, runs_dir=out,
                               command=f"python -m vcloak.bench.report_e2e derive --cells {prov['driver_run']}",
                               params={"a3_gate_pct": A3_GATE_PCT,
                                       "generator_core_limit_pct": GENERATOR_CORE_LIMIT_PCT})
    man = runs_mod.read_manifest(run_dir)
    man["derived_from"] = {"runs": sources, "backend": prov["backend"], "runner": prov["runner"],
                           "session_id": prov["session_id"], "job_id": prov["job_id"]}
    runs_mod.write_manifest(run_dir, man)
    write_csv(run_dir / "cells.csv", list(CELL_COLUMNS), [cell_row(c) for c in cells])
    (run_dir / "summary.json").write_text(json.dumps({
        "metrics": metrics, "provenance": prov, "validity": validity, "cells": cells,
        "note": "derived from the ingested cells named in the manifest (derived_from); nothing was measured here",
        "generated_by": "python -m vcloak.bench.report_e2e derive"}, indent=2) + "\n", encoding="utf-8")
    unstable = sum(m["value"] == UNSTABLE for m in metrics)
    runs_mod.finish_run(run_dir, status="OK", notes=f"{len(metrics)} metrics derived from {len(cells)} ingested "
                        f"cells of job {prov['job_id']}; {unstable} are UNSTABLE")
    return run_dir


def index_metrics(run_dir: str | Path, index: str | Path) -> int:
    """Append the metrics of a derivation run to the metrics index. Values are copied, never retyped; the
    Backend and Runner columns are those of the device runs it read (ADR-028)."""
    run, index = load_run(run_dir), Path(index)
    man, src = run["manifest"], run["manifest"]["derived_from"]
    text = index.read_text(encoding="utf-8")
    where = f"runs/{run['id']}"
    if f"| {where} |" in text:
        raise ReportError(f"{where} is already in {index.as_posix()}")
    rows = ["| " + " | ".join(str(x).replace("|", "/") for x in (
        m["id"], m["value"], m["unit"], m["stat"], man["module"], where, man["command"], run["id"][:8],
        "yes" if man["quick"] else "no", src["backend"], src["runner"])) + " |" for m in run["summary"]["metrics"]]
    index.write_text(text.rstrip("\n") + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return len(rows)


def cell_row(c: dict[str, Any]) -> list[Any]:
    def r1(x: float | None) -> Any:
        return NM if x is None else round(x, 1)

    s = c["stats"]
    return [c["users"], c["users_per_conversation"], c["mode"], c["rep"], c["run_dir"], s["scheduled"], s["acked"],
            sum(s["errors"].values()), s["readable_missing"], c["reads"]["requests"],
            sum(c["reads"]["errors"].values()), c["delta"]["epochs"], c["delta"]["overflow"], c["delta"]["missed"],
            r1(s["send_lag_ms"]["p99"]), r1(c["generator_cpu_pct"]), r1(c["service_cpu_pct"]),
            r1(c["machine_cpu_pct"]), c["telemetry_samples"]]


# ---------------------------------------------------------------- tables and notes

def _md_table(header: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header),
            *("| " + " | ".join(str(x) for x in r) + " |" for r in rows)]


def build_section(run: dict[str, Any], issue_scale: str, issue_lost: str = "no issue") -> str:
    s, prov, val = run["summary"], run["summary"]["provenance"], run["summary"]["validity"]
    c = prov["conditions"]

    def t(mid: str) -> str:
        return tagged({"m": run}, mid)

    valid = [int(u) for u, v in val.items() if v["valid"]]
    excluded = [int(u) for u, v in val.items() if not v["valid"]]
    cells = [x for x in s["cells"] if x["users"] in valid]
    vcells = [x for x in cells if x["mode"] == "vcloak"]
    pop = " and ".join(str(u) for u in valid)

    def per_users(u: int, key: str) -> str:
        return ", ".join(str(x["delta"][key]) for x in vcells if x["users"] == u)

    L = [M15_BEGIN, "# Chapter 4 notes: end-to-end performance against the unprotected baseline (M15, E6)", "",
         "Generated by `python -m vcloak.bench.report_e2e render` from the derivation run "
         f"`{run['id']}`; do not edit by hand. Every value carries a `<!--M:ID-->` tag that names its row in "
         "`state/METRICS_INDEX.md`; a count without a tag is read from the cell run named beside it "
         "(`results/e2e/e2e_cells.csv`).", "",
         "## 4.E.1 Setup and scope",
         f"- Device runs: job `{prov['job_id']}`, runner session {prov['session_id']} ({prov['runner']}, "
         f"{prov['gpu']}, {prov['cpu_count']} vCPU, driver {prov['driver']}, CUDA {prov['cuda']}, CuPy "
         f"{prov['cupy']}), packed from `{str(prov['git_sha'])[:7]}`; driver run `{prov['driver_run']}`. One "
         "environment and one set of conditions over all cells (audit A1).",
         f"- **Two users per conversation.** Every population below is a number of users in two-party "
         f"conversations (conversations = users / 2, ADR-027). Each user sends at {c['rate_per_user_s']} messages "
         f"per second (Poisson, open loop) and polls its conversation every {c['poll_ms']:g} ms.",
         f"- Both modes run back to back on the same schedule: `ack: {c['ack']}`, sessions "
         f"{'on' if c['sessions'] else 'off'} (per-user DPoP), {c['ws_sockets']} WebSockets, store {c['store']}, "
         f"SLOTS {prov['slots']}, EPOCH_MS {prov['epoch_ms']}, {c['duration_s']:g} s measured after "
         f"{c['warmup_s']:g} s of warm-up (samples counted by their scheduled time, audit A2), two repetitions.",
         "- Latencies are wall-clock differences in the generator process; the generator, the service, PostgreSQL "
         "and the GPU driver share one machine. `submit to readable` is quantised by the poll interval.",
         f"- A value is the mean of the two repetitions, and `UNSTABLE` when they are more than {A3_GATE_PCT:g} % "
         "apart (audit A3). `UNSTABLE` is not a number: no such cell is quoted or drawn.", "",
         f"## 4.E.2 Latency ({pop} users, two per conversation)",
         *_md_table(["users (2 per conversation)", "mode", "ack p50 (ms)", "ack p95 (ms)", "ack p99 (ms)",
                     "readable p50 (ms)", "readable p95 (ms)", "readable p99 (ms)"],
                    [[u, mode, *[t(f"E2E-{part}{q.upper()}-U{u}-{mode}") for _, part in SERIES for q in QUANTILES]]
                     for u in valid for mode in e2e.MODES]), "",
         "## 4.E.3 Latency added by V-cloak",
         *_md_table(["users (2 per conversation)", "added ack p50 (ms)", "added ack p99 (ms)",
                     "added readable p50 (ms)", "added readable p99 (ms)"],
                    [[u, *[t(f"E2E-ADDED-{part}{q.upper()}-U{u}") for _, part in SERIES for q in ADDED]]
                     for u in valid]), "",
         f"- Where it comes from: with `ack: stored` the answer waits for the epoch that holds the message to be "
         f"written. EPOCH_MS is {prov['epoch_ms']} ms, so a message waits half an epoch on average "
         "before its epoch closes (a property of the parameter, not a measurement); the table is what was measured.",
         "- An added latency made from an `UNSTABLE` value is `UNSTABLE`.", "",
         "## 4.E.4 Throughput, epochs and the GPU",
         *_md_table(["users (2 per conversation)", "baseline (msgs/s)", "V-cloak (msgs/s)", "epoch overflow",
                     "missed epoch boundaries (r1, r2)", "GPU utilisation median (%)", "GPU utilisation p95 (%)",
                     "power (W)"],
                    [[u, t(f"E2E-TPUT-U{u}-baseline"), t(f"E2E-TPUT-U{u}-vcloak"), t(f"E2E-OVERFLOW-U{u}"),
                      per_users(u, "missed"), t(f"E2E-GPUUTIL-U{u}"), t(f"E2E-GPUUTIL-P95-U{u}"),
                      t(f"E2E-POWER-W-U{u}")] for u in valid]), "",
         "- Throughput is the number of acknowledgements that arrived inside the measured interval, over its "
         "length. The load is open loop at a fixed offered rate, so these cells show that the offered rate was "
         "served; they are not a capacity.",
         "- Epoch overflow counts submissions left for a later epoch because their epoch was full. A missed "
         "boundary is an epoch boundary that passed while an earlier epoch was still being written; it is read "
         "from the service counters of each V-cloak cell and is not an indexed metric.",
         "- GPU utilisation and power are NVML samples at 10 Hz inside the measured interval of the V-cloak "
         "cells; NVML reports utilisation in whole percent.", "",
         "## 4.E.5 What these cells show",
         f"- In every valid cell ({pop} users, both modes, both repetitions) every scheduled send was "
         f"acknowledged and read back by its peer: {sum(x['stats']['scheduled'] for x in cells)} sends counted "
         f"over {len(cells)} cells, {sum(sum(x['stats']['errors'].values()) for x in cells)} send errors, "
         f"{sum(x['stats']['readable_missing'] for x in cells)} acknowledged sends not read back, "
         f"{sum(sum(x['reads']['errors'].values()) for x in cells)} read errors.",
         f"- The claim these cells support: V-cloak is demonstrated correct and within budget at {pop} "
         "concurrent users in two-party conversations, on this runner, at this send rate. Within budget means "
         "that no submission overflowed its epoch (4.E.4). It does not mean that every epoch was written inside "
         "EPOCH_MS: at the missed boundaries of 4.E.4 an earlier epoch was still being written.",
         f"- **Scaling behaviour is untested.** {_count(len(valid))} user counts are not a scaling curve: no "
         "trend is "
         "drawn through them, nothing is extrapolated from them, and they do not show how the system behaves as "
         "the number of users grows.", ""]
    if excluded:
        L += ["## 4.E.6 Excluded from every table"]
        for u in excluded:
            v = val[str(u)]
            mine = [x for x in s["cells"] if x["users"] == u]
            svc = [x["service_cpu_pct"] for x in mine if x["mode"] == "vcloak" and x["service_cpu_pct"] is not None]
            gen = [x["generator_cpu_pct"] for x in mine if x["generator_cpu_pct"] is not None]
            errs: dict[str, int] = {}
            for x in mine:
                for k, n in x["stats"]["errors"].items():
                    errs[k] = errs.get(k, 0) + n
            L.append(f"- **{u} users (two per conversation): `UNSTABLE`.** Cause: {v['cause']}. The latencies of "
                     "these cells contain the generator's own queueing, so the limit was the measuring harness "
                     f"and not the system; the rows stay in the run record as `UNSTABLE` ({issue_scale}) and in "
                     "no table or figure. They were not measured again and no cell was added.")
            if gen and svc:
                L.append(f"  - What the cause rests on: the generator process used {min(gen):.0f} to {max(gen):.0f} % "
                         f"of one core in the {len(mine)} cells, and the service process {min(svc):.0f} to "
                         f"{max(svc):.0f} % of a core in the V-cloak cells (psutil, 2 Hz, measured interval).")
            L.append(f"  - Correctness in these cells: "
                     f"{sum(x['stats']['readable_missing'] for x in mine)} acknowledged sends were not read back. "
                     + (f"{sum(errs.values())} sends of the measured interval got no answer "
                        f"({', '.join(f'{n} {k}' for k, n in sorted(errs.items()))}: the connection broke, the "
                        "request did not time out). They were never acknowledged, and whether the service stored "
                        f"them is not known from these runs ({issue_lost})." if errs else
                        "No send failed."))
        L += [""]
    L += [f"## 4.E.{7 if excluded else 6} Limitations",
          f"- Two populations ({pop} users), one send rate, one runner session, two repetitions per cell. "
          "Nothing is stated for a larger population.",
          "- Scaling is future work and needs two things that do not exist yet: a load harness that runs several "
          "generator processes, and the CAND_K sizing rule applied to the layouts of larger populations "
          "(`docs/REFINEMENTS.md`).",
          "- The client and the service share the CPU of one machine: the latencies include that contention.",
          "- Two-party conversations only (ADR-027).", M15_END]
    return "\n".join(L) + "\n"


def _count(n: int) -> str:
    return {1: "One", 2: "Two", 3: "Three", 4: "Four"}.get(n, str(n))


def merge_notes(path: Path, section: str) -> None:
    """Replace the M15 block of the notes, or append it; the rest of the file is left as it is."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if M15_BEGIN in old and M15_END in old:
        new = old[:old.index(M15_BEGIN)] + section.strip("\n") + old[old.index(M15_END) + len(M15_END):]
    else:
        new = old.rstrip("\n") + ("\n\n" if old else "") + section.strip("\n") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")


def render(metrics_run: str | Path, out: str | Path = "results/e2e", notes: str | Path | None = None,
           issue_scale: str = "no issue", root: str | Path = ".", issue_lost: str = "no issue") -> dict[str, Any]:
    root, out = Path(root), Path(out)
    run = load_run(metrics_run)
    s = run["summary"]
    if "derived_from" not in run["manifest"] or s["provenance"].get("backend") != "cupy":
        raise ReportError(f"{run['id']} is not a derivation of ingested cupy cells: {NM}, nothing is written")
    valid = {int(u) for u, v in s["validity"].items() if v["valid"]}
    out.mkdir(parents=True, exist_ok=True)
    src = rel(run["dir"], root)

    def users_of(mid: str) -> int:
        return int(next(p for p in mid.split("-") if p.startswith("U") and p[1:].isdigit())[1:])

    shown = [m for m in s["metrics"] if users_of(m["id"]) in valid]
    write_csv(out / "e2e_metrics.csv", ["metric_id", "users", "users_per_conversation", "value", "unit", "stat",
                                        "run_dir"],
              [[m["id"], users_of(m["id"]), 2, m["value"], m["unit"], m["stat"], src] for m in shown])
    write_csv(out / "e2e_cells.csv", list(CELL_COLUMNS), [cell_row(c) for c in s["cells"] if c["users"] in valid])
    summary = {"provenance": s["provenance"], "metrics_run": src, "users_valid": sorted(valid),
               "users_per_conversation": 2,
               "excluded": {u: {"status": UNSTABLE, "cause": v["cause"], "cells": v["cells"], "issue": issue_scale}
                            for u, v in s["validity"].items() if not v["valid"]},
               "metrics": len(shown), "metrics_unstable": sorted(m["id"] for m in shown if m["value"] == UNSTABLE),
               "scaling": "untested: the valid user counts are not a scaling curve; no trend, no extrapolation",
               "files": ["e2e_cells.csv", "e2e_metrics.csv", "e2e_summary.json"],
               "generated_by": "python -m vcloak.bench.report_e2e render"}
    (out / "e2e_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if notes:
        merge_notes(Path(notes), build_section(run, issue_scale, issue_lost))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("derive", help="derive the E2E-* metrics from the ingested cells of one driver run")
    d.add_argument("--cells", required=True, help="driver run dir of bench/run_e2e_cells.py")
    d.add_argument("--out", default="runs")
    d.add_argument("--index", default=None, help="append the rows to this metrics index")
    r = sub.add_parser("render", help="write results/e2e and the notes section from a derivation run")
    r.add_argument("--metrics", required=True, help="derivation run dir written by `derive`")
    r.add_argument("--out", default="results/e2e")
    r.add_argument("--notes", default=None, help="merge the M15 section into these notes")
    r.add_argument("--issue-scale", default="no issue", help="issue quoted for an excluded user count")
    r.add_argument("--issue-lost", default="no issue", help="issue quoted for sends that got no answer")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "derive":
            run_dir = derive(a.cells, a.out)
            s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            print(f"report_e2e: {len(s['metrics'])} metrics -> {run_dir}")
            if a.index:
                print(f"  {index_metrics(run_dir, a.index)} rows appended to {a.index}")
            for u, v in s["validity"].items():
                print(f"  {u} users: {'valid' if v['valid'] else UNSTABLE + ' - ' + str(v['cause'])}")
            return 0
        s = render(a.metrics, a.out, a.notes, a.issue_scale, issue_lost=a.issue_lost)
    except ReportError as e:
        print(f"report_e2e: {NM} - {e}")
        return 1
    print(f"report_e2e: users {s['users_valid']} (two per conversation)  {s['metrics']} metrics, "
          f"{len(s['metrics_unstable'])} UNSTABLE -> {a.out}; excluded {sorted(s['excluded']) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
