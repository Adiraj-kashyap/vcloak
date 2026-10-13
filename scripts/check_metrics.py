#!/usr/bin/env python3
"""Audit check G2 / G2b: every indexed metric is backed by a real run, and no GPU metric came from numpy.

    python scripts/check_metrics.py              # check state/METRICS_INDEX.md
    python scripts/check_metrics.py --self-test  # prove the checker rejects a numpy-backed performance metric

Rules, per row of the index:
  1. the row has all 11 columns and a unique (metric id, run dir);
  2. the run dir exists and holds a valid manifest (vcloak.runs.validate_manifest);
  3. the row's Backend / Runner / Quick columns agree with that manifest;
  4. a GPU metric (performance, side channel or device property) must have backend cupy, a `gpu_job`
     block in its manifest, and a non-local runner - unless its value is NOT_MEASURED;
  5. if the run has a summary.json listing metrics, the indexed value must equal the value in it, or be
     NOT_MEASURED: a value may be withdrawn by a recorded decision (an ANN note of the index), never changed.
The frontend literal scan (ADR-013) is added to this script when the dashboard is wired (M13/M18).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import runs  # noqa: E402

COLUMNS = ("id", "value", "unit", "stat", "module", "run_dir", "command", "date", "quick", "backend", "runner")
# Metric areas that can only be produced on a real GPU: kernels, pipeline, timing side channels,
# end-to-end latency, and the runner's device properties.
GPU_PREFIXES = ("K-", "P-", "T-", "E2E-", "ENV-")
NOT_MEASURED = "NOT_MEASURED"


def is_gpu_metric(metric_id: str) -> bool:
    return metric_id.startswith(GPU_PREFIXES)


def parse_index(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    rows, errs = [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set(cells[0]) <= {"-", ":"}:  # separator: the row above it was the header
            if rows and rows[-1]["line"] == str(n - 1):
                rows.pop()
            elif errs and errs[-1].startswith(f"line {n - 1}:"):
                errs.pop()
            continue
        if len(cells) != len(COLUMNS):
            errs.append(f"line {n}: expected {len(COLUMNS)} columns, found {len(cells)}")
            continue
        row = dict(zip(COLUMNS, cells, strict=True))
        row["line"] = str(n)
        rows.append(row)
    return rows, errs


def _same_value(a: object, b: str) -> bool:
    try:
        return float(a) == float(b)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(a) == b


def check(index: Path, root: Path) -> list[str]:
    rows, errs = parse_index(index)
    seen: set[tuple[str, str]] = set()
    for r in rows:
        where = f"line {r['line']} {r['id']}"
        key = (r["id"], r["run_dir"])
        if key in seen:
            errs.append(f"{where}: duplicate row for the same run dir")
        seen.add(key)
        run_dir = root / r["run_dir"].strip("`")
        if not run_dir.is_dir():
            errs.append(f"{where}: run dir {r['run_dir']} does not exist")
            continue
        merrs = runs.validate_manifest(run_dir)
        if merrs:
            errs.append(f"{where}: invalid manifest ({merrs[0]})")
            continue
        m = runs.read_manifest(run_dir)
        env = m["env"]
        if r["backend"] != env["backend"]:
            errs.append(f"{where}: index says backend {r['backend']}, manifest says {env['backend']}")
        if r["runner"] != env["runner"]:
            errs.append(f"{where}: index says runner {r['runner']}, manifest says {env['runner']}")
        if (r["quick"].lower() in ("yes", "true", "quick")) != bool(m["quick"]):
            errs.append(f"{where}: quick column disagrees with the manifest")
        if is_gpu_metric(r["id"]) and r["value"] != NOT_MEASURED:
            if env["backend"] != "cupy":
                errs.append(f"{where}: GPU metric recorded with backend {env['backend']} - "
                            "a numpy number is never a performance result")
            if "gpu_job" not in m:
                errs.append(f"{where}: GPU metric without a gpu_job block (not from an ingested bundle)")
            if env["runner"] == "local":
                errs.append(f"{where}: GPU metric with runner local (this laptop has no GPU)")
        summary = run_dir / "summary.json"
        if summary.exists():
            listed = {x.get("id"): x for x in json.loads(summary.read_text(encoding="utf-8")).get("metrics", [])}
            if r["id"] not in listed:
                errs.append(f"{where}: not present in {r['run_dir']}/summary.json")
            elif r["value"] != NOT_MEASURED and not _same_value(listed[r["id"]].get("value"), r["value"]):
                errs.append(f"{where}: index value {r['value']} != summary.json value {listed[r['id']].get('value')}")
        elif r["value"] != NOT_MEASURED:
            errs.append(f"{where}: run dir has no summary.json to back the value")
    return errs


def self_test() -> int:
    """Build throwaway run dirs in a temp folder and confirm the rules fire. Writes nothing to the repo."""
    from vcloak.gpu.runtime import get_backend

    header = "| " + " | ".join(COLUMNS) + " |\n|" + "---|" * len(COLUMNS) + "\n"
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        d = runs.new_run("M00", "selftest", step="S4", owner="selftest", command="self-test", root=ROOT,
                         runs_dir=root / "runs", backend=get_backend("numpy"))
        (d / "summary.json").write_text(json.dumps({"metrics": [
            {"id": "K-SELFTEST-MS", "value": 1.5}, {"id": "S-SELFTEST", "value": 0.5}]}), encoding="utf-8")
        # The self-test also runs inside a job bundle, where the manifest's runner is colab/kaggle, not local.
        runner = runs.finish_run(d, status="OK")["env"]["runner"]
        rel = d.relative_to(root).as_posix()
        tail = f"| {rel} | self-test | 2000-01-01 | no | numpy | {runner} |\n"

        def run_case(name: str, body: str, want_error: str | None) -> None:
            idx = root / f"{name}.md"
            idx.write_text(header + body, encoding="utf-8")
            errs = check(idx, root)
            ok = any(want_error in e for e in errs) if want_error else not errs
            shown = next((e for e in errs if want_error and want_error in e), errs[0] if errs else "accepted")
            print(f"  {'ok  ' if ok else 'FAIL'} {name}: {shown}")
            if not ok:
                failures.append(name)

        run_case("numpy_performance_metric_rejected", "| K-SELFTEST-MS | 1.5 | ms | median | M00 " + tail,
                 "never a performance result")
        run_case("numpy_correctness_metric_accepted", "| S-SELFTEST | 0.5 | - | value | M00 " + tail, None)
        run_case("metric_absent_from_summary_rejected", "| S-INVENTED | 0.5 | - | value | M00 " + tail,
                 "not present in")
        run_case("value_mismatch_rejected", "| S-SELFTEST | 0.75 | - | value | M00 " + tail, "!= summary.json")
        run_case("missing_run_dir_rejected",
                 "| S-SELFTEST | 0.5 | - | value | M00 | runs/nope | x | 2000-01-01 | no | numpy | local |\n",
                 "does not exist")
        run_case("backend_column_lie_rejected",
                 f"| K-SELFTEST-MS | 1.5 | ms | median | M00 | {rel} | x | 2000-01-01 | no | cupy | colab |\n",
                 "manifest says numpy")
    print("self-test:", "FAIL " + ", ".join(failures) if failures else "PASS (6 cases)")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default=str(ROOT / "state" / "METRICS_INDEX.md"))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    errs = check(Path(a.index), ROOT)
    rows, _ = parse_index(Path(a.index))
    for e in errs:
        print("FAIL:", e)
    print(f"check_metrics: {len(rows)} metric rows, {len(errs)} problems -> {'FAIL' if errs else 'PASS'}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
