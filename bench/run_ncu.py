#!/usr/bin/env python3
"""M08 S4 - warp divergence of the kernels, measured with Nsight Compute (`ncu`).

    bash bench/run_ncu.sh [--seed 8] [--log2n 16] [--out runs]      (Linux runner)
    pwsh bench/run_ncu.ps1 ...                                      (Windows with an NVIDIA GPU)

Steps (ai/GPU_GUIDE.md §7):
  1. `ncu --query-metrics`: the branch metrics of THIS ncu version are read from its own list
     (saved as ncu_query_metrics.txt); nothing is assumed about their names beyond "branch".
  2. `ncu --csv --metrics <those> python bench/ncu_workload.py`: every launch of the workload is
     profiled (raw output: ncu_profile_raw.txt, rows: ncu_branches.csv, per kernel: ncu_by_kernel.csv).
  3. Per kernel, over all its launches: the sum of the divergent-branch counter, and the branch
     efficiency 100 * uniform / (uniform + divergent) when both counters exist.
The planted-leak kernel is profiled as a positive control: it must show divergent branches.

If ncu is missing, or the driver refuses the performance counters (ERR_NVGPUCTRPERM, usual inside a
shared container), every metric is NOT_MEASURED with that reason: the run still exits 0, because a
refusal is a fact about the runner and not a failure of the kernels.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import runs  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402

NM = "NOT_MEASURED"
KERNELS = ("bitonic_pairs_global", "bitonic_shared", "bitonic_shared_full", "aead_open_seq")
CONTROL = "planted_leak"
PERM_ERRORS = ("ERR_NVGPUCTRPERM", "permission to access NVIDIA GPU Performance Counters")
QUERY_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*branch[A-Za-z0-9_]*)\b", re.IGNORECASE)
FALLBACK_SECTION = "SourceCounters"


def _run(cmd: list[str], timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, f"{type(e).__name__}: {e}"


def branch_metric_names(query_output: str) -> list[str]:
    """Metric names that contain "branch", in the order `ncu --query-metrics` lists them."""
    names: list[str] = []
    for line in query_output.splitlines():
        m = QUERY_RE.match(line)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


def parse_csv(output: str) -> list[dict[str, str]]:
    """The rows of `ncu --csv` (the workload's own prints may precede the header)."""
    lines = output.splitlines()
    start = next((i for i, line in enumerate(lines) if "Kernel Name" in line and "Metric Name" in line), None)
    if start is None:
        return []
    return [row for row in csv.DictReader(io.StringIO("\n".join(lines[start:])))
            if row.get("Kernel Name") and row.get("Metric Name")]


def _number(text: str | None) -> float | None:
    try:
        return float((text or "").replace(",", ""))
    except ValueError:
        return None


def kernel_of(name: str) -> str:
    return name.split("(", 1)[0].strip()


def by_kernel(rows: list[dict[str, str]]) -> dict[str, dict[str, dict[str, float]]]:
    """kernel -> metric -> {sum, min, max, launches} over the numeric values of all launches."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        v = _number(row.get("Metric Value"))
        if v is None:
            continue
        agg = out.setdefault(kernel_of(row["Kernel Name"]), {}).setdefault(
            row["Metric Name"], {"sum": 0.0, "min": v, "max": v, "launches": 0})
        agg["sum"] += v
        agg["min"], agg["max"] = min(agg["min"], v), max(agg["max"], v)
        agg["launches"] += 1
    return out


def _pick(metrics: dict[str, dict[str, float]], word: str) -> tuple[str, dict[str, float]] | None:
    """The counter of thread-level branch outcomes named by `word` (divergent / uniform); a `sass` counter
    is preferred, a rate or percentage is never taken for a count."""
    names = [n for n in metrics if word in n.lower() and "branch" in n.lower()
             and not any(x in n.lower() for x in ("pct", "ratio", "rate", "efficiency"))]
    names.sort(key=lambda n: ("sass" not in n.lower(), len(n)))
    return (names[0], metrics[names[0]]) if names else None


def divergence(metrics: dict[str, dict[str, float]]) -> dict[str, Any]:
    div, uni = _pick(metrics, "divergent"), _pick(metrics, "uniform")
    out: dict[str, Any] = {"divergent": None, "divergent_metric": None, "efficiency_pct": None,
                           "uniform_metric": None, "launches": None}
    if div:
        out.update({"divergent": div[1]["sum"], "divergent_metric": div[0], "launches": int(div[1]["launches"])})
    if div and uni:
        total = div[1]["sum"] + uni[1]["sum"]
        out.update({"uniform_metric": uni[0], "uniform": uni[1]["sum"],
                    "efficiency_pct": 100.0 * uni[1]["sum"] / total if total > 0 else None})
    return out


def metrics_of(per_kernel: dict[str, dict[str, Any]], reason: str | None) -> list[dict[str, Any]]:
    out = []
    for k in KERNELS:
        mid = k.upper().replace("_", "-")
        d = per_kernel.get(k)
        why = reason or (None if d else "the kernel does not appear in the ncu output")
        if why or d is None:
            out.append({"id": f"T-NCU-DIVERGENT-{mid}", "value": NM, "unit": "branches", "stat": "sum", "note": why})
            out.append({"id": f"T-NCU-BRANCHEFF-{mid}", "value": NM, "unit": "%", "stat": "ratio of sums", "note": why})
            continue
        n = f"over {d['launches']} profiled launch(es)"
        out.append({"id": f"T-NCU-DIVERGENT-{mid}", "unit": "branches", "stat": "sum",
                    "value": NM if d["divergent"] is None else round(d["divergent"], 4),
                    "note": f"{d['divergent_metric']} {n}" if d["divergent"] is not None
                    else "no divergent-branch counter in this ncu version"})
        out.append({"id": f"T-NCU-BRANCHEFF-{mid}", "unit": "%", "stat": "ratio of sums",
                    "value": NM if d["efficiency_pct"] is None else round(d["efficiency_pct"], 4),
                    "note": f"100 * {d['uniform_metric']} / (uniform + divergent) {n}"
                    if d["efficiency_pct"] is not None
                    else "needs a uniform and a divergent counter with a non-zero total"})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--seed", type=int, default=8)
    ap.add_argument("--log2n", type=int, default=16)
    ap.add_argument("--out", default="runs")
    ap.add_argument("--timeout", type=int, default=1800)
    a = ap.parse_args(argv)
    command = "python bench/run_ncu.py " + " ".join(shlex.quote(x) for x in (argv if argv is not None
                                                                           else sys.argv[1:]))
    backend = get_backend()
    run_dir = runs.new_run("M08", "ncu", step="S4", owner="Aditya", command=command, seed=a.seed, root=Path.cwd(),
                           runs_dir=a.out, backend=backend,
                           params={"log2n": a.log2n, "kernels": list(KERNELS), "control": CONTROL})
    reason: str | None = None
    names: list[str] = []
    rows: list[dict[str, str]] = []
    profile_cmd: list[str] = []
    version = None
    if not backend.is_gpu:
        reason = "numpy backend: no GPU on this machine"
    elif shutil.which("ncu") is None:
        reason = "ncu (Nsight Compute) is not installed on this runner"
    else:
        _, version = _run(["ncu", "--version"], 120)
        rc, query = _run(["ncu", "--query-metrics"], 600)
        (run_dir / "ncu_query_metrics.txt").write_text(query, encoding="utf-8")
        names = branch_metric_names(query) if rc == 0 else []
        select = ["--metrics", ",".join(names)] if names else ["--section", FALLBACK_SECTION]
        profile_cmd = ["ncu", "--csv", *select, sys.executable, str(ROOT / "bench" / "ncu_workload.py"),
                       "--log2n", str(a.log2n), "--seed", str(a.seed)]
        rc, out = _run(profile_cmd, a.timeout)
        (run_dir / "ncu_profile_raw.txt").write_text(out, encoding="utf-8")
        rows = parse_csv(out)
        if any(e in out for e in PERM_ERRORS):
            reason = "the driver refused the GPU performance counters to this user (ERR_NVGPUCTRPERM)"
        elif "mismatches=0" not in out:
            reason = f"the profiled workload did not finish correctly (ncu exit {rc}); see ncu_profile_raw.txt"
        elif not rows:
            reason = f"ncu printed no metric rows (exit {rc}); see ncu_profile_raw.txt"

    agg = by_kernel(rows)
    per_kernel = {k: divergence(m) for k, m in agg.items()}
    if rows:
        with (run_dir / "ncu_branches.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "kernel", "block_size", "grid_size", "metric", "unit", "value"])
            w.writerows((r.get("ID"), kernel_of(r["Kernel Name"]), r.get("Block Size"), r.get("Grid Size"),
                         r["Metric Name"], r.get("Metric Unit"), r.get("Metric Value")) for r in rows)
        with (run_dir / "ncu_by_kernel.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["kernel", "metric", "launches", "sum", "min", "max"])
            w.writerows((k, m, int(v["launches"]), v["sum"], v["min"], v["max"])
                        for k, ms in sorted(agg.items()) for m, v in sorted(ms.items()))
    control = per_kernel.get(CONTROL, {})
    control_seen = None if reason or control.get("divergent") is None else bool(control["divergent"] > 0)
    metrics = metrics_of(per_kernel, reason)
    (run_dir / "summary.json").write_text(json.dumps({
        "metrics": metrics, "reason": reason, "ncu_version": (version or "").strip() or None,
        "branch_metrics_queried": names, "profile_command": " ".join(profile_cmd), "rows": len(rows),
        "per_kernel": per_kernel, "control": {"kernel": CONTROL, "divergent_seen": control_seen, **control},
        "device": backend.device_info()}, indent=2) + "\n", encoding="utf-8")

    notes = []
    measured = [m for m in metrics if m["value"] != NM]
    if reason:
        status = NM
        notes.append(reason)
    elif control_seen is False:
        status = "FAIL"
        notes.append("the planted-leak kernel shows no divergent branch: these counters do not see divergence")
    elif not measured:
        status = NM
        notes.append("no divergence counter could be read from the ncu output; see ncu_branches.csv")
    else:
        status = "OK"
        if control_seen is None:
            notes.append("the positive control has no divergent-branch counter: not confirmed")
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))
    print(f"run dir     {run_dir}")
    print(f"ncu         {(version or 'absent').strip().splitlines()[0] if version else 'absent'}")
    print(f"metrics     queried {len(names)} branch metric(s), {len(rows)} csv rows")
    for k in (*KERNELS, CONTROL):
        d = per_kernel.get(k)
        print(f"  {k:<22} " + (f"divergent {d['divergent']}  efficiency {d['efficiency_pct']}  launches {d['launches']}"
                               if d else "-"))
    print(f"status      {status}   {'; '.join(notes)}")
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
