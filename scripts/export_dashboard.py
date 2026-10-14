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

from vcloak import config  # noqa: E402

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
ATTACK_LAYOUTS = (("BASELINE", "Arrival order"), ("EPOCH", "Per epoch"), ("W1", "W = 1 s"), ("W10", "W = 10 s"),
                  ("W60", "W = 60 s"), ("W300", "W = 300 s"))
# Charts not built yet (M18 S3) are left out: a placeholder would render NOT MEASURED for metrics that exist.


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


def attack_chart(best: dict[str, dict[str, str]]) -> dict[str, Any]:
    ids = [f"S-TURNACC-{k}" for k, _ in ATTACK_LAYOUTS]
    rows = [best.get(i) for i in ids]
    values = [None if r is None or _num(r["value"]) is None else round(float(r["value"]) * 100, 1) for r in rows]
    return {"id": "attack_ablation", "kind": "groupedBar", "title": "Order-recovery attack vs visible window",
            "categories": [name for _, name in ATTACK_LAYOUTS],
            "series": [{"name": "Measured", "slot": 1, "values": values}], "unit": "%", "yMin": 0, "yMax": 100,
            "refLine": {"value": 50, "label": "chance"},  # a public reference: a coin flip, not a result
            "note": "Turn-order accuracy: for two consecutive messages of a conversation, does the dump order them "
                    "correctly? 50 % is chance.",
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
    charts = [gpu_util_chart(best, valid), attack_chart(best)]
    return {
        "generated_at": max(r["date"] for r in rows),
        "git_sha": None,
        "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        "source": "metrics-index",
        "provenance": provenance(best, root),
        "groups": [{"id": "gpu", "title": "The GPU under load"}, {"id": "security", "title": "Order privacy"}],
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
