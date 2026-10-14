#!/usr/bin/env python3
"""M18: write web/data/dashboard.json from state/METRICS_INDEX.md and runs/. No number is typed here (ADR-013).

    python scripts/export_dashboard.py            # write web/data/dashboard.json
    python scripts/export_dashboard.py --check    # write nothing; exit 1 if the file on disk would change

Rules (ai/modules/M18 S1, ai/FRONTEND.md section 4):
  - every tile names a METRIC-ID and the run dir of the index row it shows;
  - a metric with no index row, or whose row is UNSTABLE or NOT_MEASURED, renders NOT MEASURED and is listed in
    `missing` with what would produce it;
  - a quick row is shown with its QUICK chip and never as a headline tile;
  - user counts whose E6 rows are UNSTABLE are listed in `excluded` with their cause and drawn nowhere (ADR-028).
The first group is the GPU-utilisation framing: what the GPU does under the measured load, read from the E6 rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import check_metrics  # noqa: E402
import numpy as np  # noqa: E402

from vcloak import config  # noqa: E402
from vcloak.bench import dudect  # noqa: E402

OUT = ROOT / "web" / "data" / "dashboard.json"
NO_VALUE = ("UNSTABLE", check_metrics.NOT_MEASURED)
E2E_HOW = "M15 · python bench/run_e2e_cells.py on the GPU runner, then python -m vcloak.bench.report_e2e derive"
UNSTABLE_E6 = "UNSTABLE by cause: the load generator ran above one core (ADR-028); no rerun (ADR-027)"

# (metric id, label, display scale, digits, unit shown, what produces it). Labels and commands only, no values.
GPU_FIXED = (
    ("K-BITONIC-FUSED-MS-2^16", "Bitonic shuffle kernel, 2^16 slots (GPU)", 1, 3, "ms",
     "M07 · python bench/run_kernels.py --part gpu on the GPU runner"),
    ("X-CROSSOVER-N", "GPU beats the CPU above n =", 1, 0, "",
     "M07 · GPU and CPU baselines from one runner session"),
)
# Per user count u of the E6 cells: (id pattern, label pattern, scale, digits, unit).
GPU_PER_USERS = (
    ("E2E-GPUUTIL-U{u}", "GPU utilisation, median, {u} users", 1, 1, "%"),
    ("E2E-GPUUTIL-P95-U{u}", "GPU utilisation, p95, {u} users", 1, 1, "%"),
    ("E2E-POWER-W-U{u}", "GPU power, median, {u} users", 1, 1, "W"),
    ("E2E-ADDED-P50-U{u}", "Ack latency added by V-cloak, p50, {u} users", 1, 1, "ms"),
    ("E2E-OVERFLOW-U{u}", "Submissions that overflowed their epoch, {u} users", 1, 0, ""),
)
SECURITY = (
    ("S-TURNACC-BASELINE", "Turn order recovered: arrival order, no shuffle", 100, 1, "%",
     "M14 · python bench/run_security_eval.py --stage attack"),
    ("S-TURNACC-EPOCH", "Turn order recovered: shuffle per epoch only", 100, 1, "%",
     "M14 · python bench/run_security_eval.py --stage attack"),
    ("S-TURNACC-W300", "Turn order recovered: window W = 300 s", 100, 1, "%",
     "M14 · python bench/run_security_eval.py --stage attack"),
    ("S-E0-RESTORE", "Conversations restored in exact order", 1, 0, "",
     "M14 · python bench/run_security_eval.py --stage attack"),
    ("S-CHI2-P", "Permutation uniformity, χ² p-value", 1, 3, "",
     "M14 · python bench/run_security_eval.py --stage uniformity"),
    ("S-TRACE-DISTINCT-DEVICE", "Distinct comparator traces over adversarial inputs", 1, 0, "",
     "M14 · python bench/run_security_eval.py --stage trace"),
    ("SEC-E5-PASS", "Session-security scenarios behaving as expected", 1, 0, "",
     "M11 · python bench/run_session_matrix.py"),
)
DUDECT_HOW = "M08 · python bench/run_dudect.py --targets control_null,targets --seed 8 --out runs on the GPU runner"
# dudect max |t| against the threshold of vcloak.bench.dudect. The kernel rows carry the claim of ADR-023; the
# whole-call row is shown beside them because it FAILs: host timing is outside the claim, and the page says so.
DUDECT = (
    ("T-DUDECT-MAXT-BITONIC-EQUAL", "dudect max |t|: shuffle kernel, 2^16, equal vs random tags", "kernel"),
    ("T-DUDECT-MAXT-BITONIC-SORTED", "dudect max |t|: shuffle kernel, 2^16, sorted vs random tags", "kernel"),
    ("T-DUDECT-MAXT-WRITE-EPOCH-CALL", "dudect max |t|: whole write_epoch call, host code included", "host"),
)
ATTACK_LAYOUTS = (("BASELINE", "Arrival order"), ("EPOCH", "Per epoch"), ("W1", "W = 1 s"), ("W10", "W = 10 s"),
                  ("W60", "W = 60 s"), ("W300", "W = 300 s"))
# (b) kernel sweep: (legend name, id pattern over the exponent e, palette slot). Labels only, no values.
KERNEL_SERIES = (("GPU shuffle kernel (fused bitonic)", "K-BITONIC-FUSED-MS-2^{e}", 1),
                 ("CPU bitonic network (numba)", "CPU-BITONIC-NUMBA-MS-2^{e}", 2),
                 ("CPU lexsort (not oblivious)", "CPU-LEXSORT-MS-2^{e}", 3))


def _rank(row: dict[str, str]) -> tuple[int, int, str, int]:
    """Preferred row of a metric id: not quick, then measured on the GPU, then the newest, then the last line."""
    return (row["quick"] == "no", row["backend"] == "cupy", row["date"], int(row["line"]))


def pick(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    best: dict[str, dict[str, str]] = {}
    for r in rows:
        if r["id"] not in best or _rank(r) > _rank(best[r["id"]]):
            best[r["id"]] = r
    return best


def _num(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _shown(row: dict[str, str], scale: float, digits: int) -> Any:
    x = _num(row["value"])
    if x is None:  # a ratio such as 26/26 is shown as recorded
        return row["value"]
    return round(x * scale, digits) if digits else int(round(x * scale))


def tile(best: dict[str, dict[str, str]], mid: str, label: str, scale: float, digits: int, unit: str, how: str,
         group: str, missing: list[dict[str, str]]) -> dict[str, Any]:
    t: dict[str, Any] = {"id": "t-" + mid.lower(), "group": group, "label": label, "unit": unit, "metric_id": mid,
                         "value": None, "state": "na", "quick": False, "headline": False}
    row = best.get(mid)
    if row is None:
        t["how"] = how
        missing.append({"metric_id": mid, "how": how})
        return t
    t.update(run=row["run_dir"], backend=row["backend"], runner=row["runner"], stat=row["stat"])
    if row["value"] in NO_VALUE:
        t["how"] = f"{row['value']} in {row['run_dir']}. {how}"
        missing.append({"metric_id": mid, "how": t["how"]})
        return t
    t.update(value=_shown(row, scale, digits), raw=row["value"], state="", quick=row["quick"] != "no")
    t["headline"] = not t["quick"]
    return t


def dudect_tile(best: dict[str, dict[str, str]], mid: str, label: str, scope: str,
                missing: list[dict[str, str]]) -> dict[str, Any]:
    t = tile(best, mid, label, 1, 2, "", DUDECT_HOW, "timing", missing)
    if t["value"] is None:
        return t
    passed = abs(float(t["raw"])) < dudect.T_THRESHOLD
    t["state"] = "good" if passed else "crit"
    t["sub"] = (f"{'PASS' if passed else 'FAIL'}: threshold |t| < {dudect.T_THRESHOLD}. " +
                ("Kernel-level claim (ADR-023): a pass of this test, not a proof." if scope == "kernel" else
                 "Host timing is outside the claim (ADR-023): reported, not hidden."))
    t["headline"] = t["headline"] and scope == "kernel"
    return t


def user_counts(best: dict[str, dict[str, str]]) -> tuple[list[int], list[int]]:
    """User counts of the E6 cells: valid (throughput measured) and excluded (UNSTABLE)."""
    seen = sorted({int(m.group(1)) for k in best if (m := re.fullmatch(r"E2E-TPUT-U(\d+)-vcloak", k))})
    valid = [u for u in seen if best[f"E2E-TPUT-U{u}-vcloak"]["value"] not in NO_VALUE]
    return valid, [u for u in seen if u not in valid]


def gpu_framing(best: dict[str, dict[str, str]], valid: list[int]) -> dict[str, Any]:
    ids = [f"E2E-GPUUTIL-U{u}" for u in valid] + [f"E2E-ADDED-P50-U{u}" for u in valid]
    stat = next((best[i]["stat"] for i in ids if i in best), None)
    points = [
        f"Utilisation is the share of NVML sample periods in which a kernel was running ({stat})." if stat else
        "Utilisation: NOT MEASURED.",
        f"The GPU works in one short burst per epoch of {config.EPOCH_MS} ms (config.EPOCH_MS), so a low value "
        "describes this load, not a capacity.",
        "NVML reports utilisation in whole percent, so a series near the bottom of the scale is at the resolution of "
        "the counter.",
        "The ack latency V-cloak adds comes from waiting for the epoch to close, not from GPU compute "
        "(docs/REPORT_CH4_NOTES.md section 4.E.3).",
        "Low utilisation is not evidence of headroom or of how the system scales: scaling is untested (ADR-028).",
        "Populations are users in two-party conversations, two users per conversation (ADR-027).",
    ]
    return {"id": "gpu_utilisation", "title": "What the GPU does under the measured load", "points": points,
            "metric_ids": [i for i in ids if i in best]}


def attack_chart(best: dict[str, dict[str, str]], root: Path) -> dict[str, Any]:
    ids = [f"S-TURNACC-{k}" for k, _ in ATTACK_LAYOUTS]
    rows = [best.get(i) for i in ids]
    values = [None if r is None or _num(r["value"]) is None else round(float(r["value"]) * 100, 1) for r in rows]
    predicted = attack_prediction(root, rows)
    series = [{"name": "Measured", "slot": 1, "values": values}]
    if any(v is not None for v in predicted):
        series.append({"name": "Predicted 1 − f/2", "slot": 3, "values": predicted})
    return {"id": "attack_ablation", "kind": "groupedBar", "title": "Order-recovery attack vs visible window",
            "categories": [name for _, name in ATTACK_LAYOUTS],
            "series": series, "unit": "%", "yMin": 0, "yMax": 100,
            "refLine": {"value": 50, "label": "chance"},  # a public reference: a coin flip, not a result
            "note": "Turn-order accuracy: for two consecutive messages of a conversation, does the dump order them "
                    "correctly? 50 % is chance. Predicted 1 − f/2, with f the share of turns inside one visible "
                    "round, is the attack run's own model (e1_attack.json); arrival order has no prediction.",
            "metric_ids": ids, "runs": sorted({r["run_dir"] for r in rows if r})}


def gpu_util_chart(best: dict[str, dict[str, str]], valid: list[int]) -> dict[str, Any]:
    def vals(pattern: str) -> list[Any]:
        return [_num(best[pattern.format(u=u)]["value"]) if pattern.format(u=u) in best else None for u in valid]
    ids = [p.format(u=u) for p in ("E2E-GPUUTIL-U{u}", "E2E-GPUUTIL-P95-U{u}") for u in valid]
    return {"id": "e2e_gpu_util", "kind": "groupedBar", "title": "GPU utilisation during the E6 cells",
            "categories": [f"{u} users" for u in valid],
            "series": [{"name": "median", "slot": 1, "values": vals("E2E-GPUUTIL-U{u}")},
                       {"name": "p95", "slot": 3, "values": vals("E2E-GPUUTIL-P95-U{u}")}],
            "unit": "%", "yMin": 0, "yMax": 100,
            "note": "Two users per conversation. Categories, not a trend: no line joins two user counts (ADR-028).",
            "metric_ids": [i for i in ids if i in best], "runs": sorted({best[i]["run_dir"] for i in ids if i in best})}


def _manifest(root: Path, run_dir: str) -> dict[str, Any]:
    return json.loads((root / run_dir / "manifest.json").read_text(encoding="utf-8"))


def _json(root: Path, run_dir: str, name: str) -> dict[str, Any]:
    return json.loads((root / run_dir / name).read_text(encoding="utf-8"))


def _chart_runs(best: dict[str, dict[str, str]], ids: list[str]) -> list[str]:
    return sorted({best[i]["run_dir"] for i in ids if i in best})


def attack_prediction(root: Path, rows: list[dict[str, str] | None]) -> list[Any]:
    """1 − f/2 per layout, as the attack run wrote it (e1_attack.json of the run the measured rows come from).
    The prediction is about shuffled rounds, so the unshuffled baseline has none."""
    runs = {r["run_dir"] for r in rows if r}
    if len(runs) != 1 or not (root / next(iter(runs)) / "e1_attack.json").exists():
        return [None] * len(ATTACK_LAYOUTS)
    lay = {x["layout"]: x for x in _json(root, runs.pop(), "e1_attack.json")["layouts"]}
    return [None if k not in lay or lay[k].get("mode") == "baseline" else
            round(float(lay[k]["attack"]["predicted_turn_accuracy"]) * 100, 1) for k, _ in ATTACK_LAYOUTS]


def kernel_chart(best: dict[str, dict[str, str]], root: Path) -> dict[str, Any]:
    """(b) The shuffle kernel against two CPU baselines, log–log. Every point comes from one runner session
    (ADR-024); an UNSTABLE size is a gap in its line, never a point. The crossover is marked only when measured."""
    exps = sorted({int(m.group(1)) for k in best if (m := re.fullmatch(r"K-BITONIC-FUSED-MS-2\^(\d+)", k))})
    ids_all: list[str] = []
    series = []
    for name, pattern, slot in KERNEL_SERIES:
        pts = []
        for e in exps:
            mid = pattern.format(e=e)
            if mid in best:
                ids_all.append(mid)
            pts.append([2 ** e, _num(best[mid]["value"]) if mid in best else None])
        series.append({"name": name, "slot": slot, "points": pts})
    runs = _chart_runs(best, ids_all)
    sessions = {(_manifest(root, r).get("env") or {}).get("session_id") for r in runs}
    if len(sessions) != 1:
        raise SystemExit(f"kernel chart: points from {len(sessions)} runner sessions, not comparable (ADR-024)")
    cross = best.get("X-CROSSOVER-N")
    cross_n = _num(cross["value"]) if cross else None
    gaps = sorted({p[0] for s in series for p in s["points"] if p[1] is None})
    note = ("Median kernel time per call, one T4 runner session. The CPU bitonic network does the same comparisons "
            "as the GPU kernel; lexsort is the fastest CPU sort and is not oblivious.")
    if gaps:
        note += " Gaps are sizes whose timing was UNSTABLE on the shared runner (ISSUE-15): no point is drawn."
    if cross_n is None:
        note += (" Crossover: NOT MEASURED (" + (cross["value"] if cross else "no row") +
                 (f", {cross['run_dir']}" if cross else "") + "), so no crossover is marked.")
    return {"id": "kernel_sweep", "kind": "lineLog", "title": "Shuffle kernel vs CPU baselines",
            "series": series, "unit": " ms", "xLabel": "slots n", "crossover": cross_n,
            "refLine": {"value": config.EPOCH_MS, "label": f"epoch budget {config.EPOCH_MS} ms (config.EPOCH_MS)"},
            "note": note, "metric_ids": ids_all + (["X-CROSSOVER-N"] if cross else []),
            "runs": sorted(set(runs) | ({cross["run_dir"]} if cross else set()))}


def pipeline_chart(rows: list[dict[str, str]], root: Path) -> dict[str, Any]:
    """(d) The device stages of write_epoch against the epoch budget, from the one run with the most valid sizes.
    The host stage and the whole call are not drawn: for the current code the whole call at 65536 slots is
    unmeasured under valid conditions (ISSUE-12), and an older run's host time would be read as today's."""
    pat = re.compile(r"P-WRITE-EPOCH-DEVICE-MS-S(\d+)")
    by_run: dict[str, dict[int, dict[str, str]]] = {}
    for r in rows:
        m = pat.fullmatch(r["id"])
        if m and r["quick"] == "no" and r["backend"] == "cupy" and r["value"] not in NO_VALUE:
            by_run.setdefault(r["run_dir"], {})[int(m.group(1))] = r
    run = max(by_run, key=lambda k: (len(by_run[k]), next(iter(by_run[k].values()))["date"]))
    pts = by_run[run]
    man = _manifest(root, run)
    sizes = sorted(pts)
    return {"id": "pipeline_device", "kind": "groupedBar", "title": "write_epoch device stages vs the epoch budget",
            "categories": [f"{s} slots" for s in sizes],
            "series": [{"name": "device stages, median", "slot": 1,
                        "values": [round(float(pts[s]["value"]), 3) for s in sizes]}],
            "unit": " ms", "yMin": 0, "yMax": config.EPOCH_MS * 1.1,
            "refLine": {"value": config.EPOCH_MS, "label": f"epoch budget {config.EPOCH_MS} ms (config.EPOCH_MS)"},
            "note": f"CUDA events, sizes whose device time was stable in run {run} ({man.get('env', {}).get('runner')}, "
                    f"code {str(man.get('git_sha'))[:9]}); the other sizes were UNSTABLE. Host stage and whole call "
                    "not drawn: for the current code the whole call at 65536 slots is unmeasured under valid "
                    "conditions (ISSUE-12).",
            "metric_ids": [f"P-WRITE-EPOCH-DEVICE-MS-S{s}" for s in sizes], "runs": [run]}


def tau_chart(best: dict[str, dict[str, str]], root: Path) -> dict[str, Any] | None:
    """(c) Per-epoch Kendall τ in units of its theoretical σ, from the histogram the uniformity run wrote."""
    row = best.get("S-TAUBAND-PCT")
    if row is None or not (root / row["run_dir"] / "e2_uniformity.json").exists():
        return None
    tb = _json(root, row["run_dir"], "e2_uniformity.json")["tau_band"]
    edges, counts = tb["histogram"]["z_edges"], tb["histogram"]["counts"]
    ids = [i for i in ("S-TAUBAND-PCT", "S-TAU-SIGMA-MEAS") if i in best]
    return {"id": "tau_hist", "kind": "histogram", "title": "Per-epoch Kendall τ, in units of σ",
            "binCenters": [round((a + b) / 2, 3) for a, b in zip(edges, edges[1:])], "counts": counts,
            "band": round(tb["band_3sigma"] / tb["sigma_theory"], 6), "xLabel": "τ / σ (theoretical σ)",
            "yLabel": "epochs",
            "note": f"{tb['epochs']} epochs at n = {tb['n']}. Inside the ±3σ band: {row['value']} % (S-TAUBAND-PCT); "
                    "a uniform shuffle puts about 99.7 % there. The band is the definition of the test, not a result.",
            "metric_ids": ids, "runs": _chart_runs(best, ids)}


def session_chart(best: dict[str, dict[str, str]], root: Path) -> dict[str, Any] | None:
    """(e) The E5 attack matrix as a pass/fail grid, row by row from the run of SEC-E5-PASS."""
    row = best.get("SEC-E5-PASS")
    if row is None or not (root / row["run_dir"] / "e5_matrix.json").exists():
        return None
    m = _json(root, row["run_dir"], "e5_matrix.json")
    return {"id": "session_matrix", "kind": "matrix", "title": "Session-security attack matrix (E5)",
            "rows": [{"name": r["scenario"], "expected": r["expected"], "observed": r["observed"],
                      "ok": bool(r["as_expected"]), "why": r.get("failed_check") or "—"} for r in m["rows"]],
            "note": f"{row['value']} scenarios behaved as expected (SEC-E5-PASS). A rejection must fail the expected "
                    "check: a rejection for another reason counts as a failure. Backend "
                    f"{row['backend']}, runner {row['runner']}: this matrix tests protocol logic, not the GPU.",
            "metric_ids": ["SEC-E5-PASS"], "runs": [row["run_dir"]]}


def latency_charts(best: dict[str, dict[str, str]], root: Path, valid: list[int]) -> list[dict[str, Any]]:
    """(f) The empirical CDF of submit to ack, V-cloak vs the unprotected baseline, one chart per valid user count,
    one curve per cell: the two repetitions are drawn apart, never pooled (as in results/e2e). Each curve is given
    at the percentiles 0..100 of the acknowledged sends scheduled in the measured interval of its cell."""
    from vcloak.bench import e2e, report_e2e  # noqa: PLC0415 (heavy: only when E6 rows exist)

    out = []
    for u in valid:
        ids = [f"E2E-{q}-U{u}-{mode}" for mode in e2e.MODES for q in ("P50", "P95", "P99")]
        runs = _chart_runs(best, ids)
        if len(runs) != 1:
            continue
        _, cells = report_e2e.figure_cells(report_e2e.load_run(root / runs[0]), root)
        series = []
        for c in [c for c in cells if c["users"] == u]:
            s = c["dir"] / "summary.json"
            cond = json.loads(s.read_text(encoding="utf-8"))
            m = e2e.measured(e2e.load_samples(c["dir"] / "samples.csv"), cond["warmup_s"], cond["duration_s"])
            vals = [x.ack_ms for x in m if not x.error and x.ack_ms is not None]
            if not vals:
                continue
            qs = np.percentile(np.asarray(vals, dtype=np.float64), np.arange(101))
            name = ("V-cloak" if c["mode"] == "vcloak" else "baseline (unprotected)") + f", repetition {c['rep']}"
            series.append({"name": name, "slot": 1 if c["mode"] == "vcloak" else 2, "dash": c["rep"] > 1,
                           "n": len(vals), "run": c["run_dir"],
                           "points": [[round(float(v), 3), p / 100] for p, v in enumerate(qs)]})
        out.append({"id": f"e2e_latency_u{u}", "kind": "cdf",
                    "title": f"Submit to ack, {u} users (2 per conversation)", "series": series, "unit": " ms",
                    "xLabel": "latency (ms, log scale)", "yLabel": "fraction of sends",
                    "refLine": {"value": config.EPOCH_MS, "label": f"epoch {config.EPOCH_MS} ms"},
                    "note": "Empirical CDF per cell, ack: stored, sends scheduled in the measured interval. Solid: "
                            "repetition 1, dashed: repetition 2. V-cloak waits for its epoch to close; the baseline "
                            "stores at once.",
                    "metric_ids": [i for i in ids if i in best], "runs": runs + [s["run"] for s in series]})
    return out


def provenance(best: dict[str, dict[str, str]], root: Path) -> dict[str, Any]:
    gpu = [r for r in best.values() if r["backend"] == "cupy"]
    if not gpu:
        return {"backend": "numpy", "runner": "none", "session_id": None, "note": "No GPU run is indexed."}
    newest = max(gpu, key=lambda r: (r["date"], int(r["line"])))
    p: dict[str, Any] = {"backend": "cupy", "runner": newest["runner"], "run": newest["run_dir"], "date": newest["date"]}
    man = root / newest["run_dir"] / "manifest.json"
    if man.exists():
        m = json.loads(man.read_text(encoding="utf-8"))
        src = m.get("derived_from") or m.get("env") or {}
        p["session_id"] = src.get("session_id")
        for run in (src.get("runs") or [])[:1]:  # the first run of a derivation is its driver run
            env = json.loads((root / run / "manifest.json").read_text(encoding="utf-8")).get("env", {})
            p.update(gpu=env.get("gpu"), cpu_count=env.get("cpu_count"))
    p["note"] = "GPU numbers come from a free shared cloud runner; timings vary between its sessions."
    return p


def build(index: Path, root: Path) -> dict[str, Any]:
    rows, errs = check_metrics.parse_index(index)
    if errs:
        raise SystemExit("index does not parse: " + "; ".join(errs[:3]))
    best = pick(rows)
    valid, excluded = user_counts(best)
    missing: list[dict[str, str]] = []
    tiles = [tile(best, p.format(u=u), lab.format(u=u) + " (2 per conversation)", s, d, unit, E2E_HOW, "gpu", missing)
             for u in valid for p, lab, s, d, unit in GPU_PER_USERS]
    tiles += [tile(best, *spec, group="gpu", missing=missing) for spec in GPU_FIXED]
    tiles += [tile(best, *spec, group="security", missing=missing) for spec in SECURITY]
    tiles += [dudect_tile(best, mid, label, scope, missing) for mid, label, scope in DUDECT]
    charts = [gpu_util_chart(best, valid), *latency_charts(best, root, valid), kernel_chart(best, root),
              pipeline_chart(rows, root), attack_chart(best, root), tau_chart(best, root), session_chart(best, root)]
    charts = [c for c in charts if c is not None]
    return {
        "generated_at": max(r["date"] for r in rows),
        "git_sha": None,
        "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        "source": "metrics-index",
        "provenance": provenance(best, root),
        "groups": [{"id": "gpu", "title": "The GPU under load", "framing": "gpu_utilisation"},
                   {"id": "security", "title": "Order privacy",
                    "note": "Against a passive adversary holding a snapshot of the store. V-cloak conceals the "
                            "order in which messages were stored within a window. It does not conceal the full "
                            "read/write access pattern, and it does not conceal which rows belong to the same "
                            "conversation: bucket tags reveal partial conversation identity, and window ids and "
                            "per-window message counts are visible (ADR-031). The epoch order of the newest data "
                            "is also visible until its window closes (ai/PROJECT_BRIEF.md section 5)."},
                   {"id": "timing", "title": "Kernel timing (dudect, on the GPU runner)",
                    "note": "The claim is obliviousness of the server-side kernels against an adversary who sees "
                            "the store and no timing (ADR-023)."}],
        "framing": [gpu_framing(best, valid)],
        "tiles": tiles,
        "charts": charts,
        "missing": missing,
        "excluded": [{"users": u, "reason": UNSTABLE_E6} for u in excluded],
    }


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", type=Path, default=ROOT / "state" / "METRICS_INDEX.md")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    text = render(build(a.index, a.root))
    if a.check:
        same = a.out.exists() and a.out.read_text(encoding="utf-8") == text
        print("dashboard.json is current" if same else f"dashboard.json is STALE: run {Path(__file__).name}")
        return 0 if same else 1
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text, encoding="utf-8")
    print(f"wrote {a.out.relative_to(ROOT) if a.out.is_relative_to(ROOT) else a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
