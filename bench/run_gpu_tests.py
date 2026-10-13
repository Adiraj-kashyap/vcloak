#!/usr/bin/env python3
"""Run the tests marked `gpu` and record the result as a run (they SKIP on the laptop: no CUDA device).

    python bench/run_gpu_tests.py [--expect 674] [--deselect-slow] [--out runs]

The run dir holds pytest_gpu.txt (the whole output), junit.xml, cuda_tests.json (the counts, and every
test that did not pass with its reason) and summary.json. Exit 0 only if tests passed and none failed
or errored. Skips are counted and listed with their reasons, and `--expect` records whether the marker
selected as many tests as it did when the job was packed; neither changes the exit code. A count is
recorded as it is: under the numpy backend every test is skipped and the run is FAIL, never a pass.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import runs  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402

OUTCOMES = ("failure", "error", "skipped")


def parse_junit(path: Path) -> dict[str, Any]:
    """Counts and the tests that did not pass, from a pytest junit file."""
    cases = list(ET.parse(path).getroot().iter("testcase"))
    counts = {"selected": len(cases), "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    not_passed = []
    for case in cases:
        hit = next((child for child in case if child.tag in OUTCOMES), None)
        if hit is None:
            counts["passed"] += 1
            continue
        counts[{"failure": "failed", "error": "errors", "skipped": "skipped"}[hit.tag]] += 1
        not_passed.append({"test": f"{case.get('classname')}::{case.get('name')}", "outcome": hit.tag,
                           "message": (hit.get("message") or "")[:300]})
    return {**counts, "not_passed": not_passed}


def verdict(counts: dict[str, Any]) -> dict[str, bool]:
    return {"tests_passed": counts["passed"] > 0, "none_failed": counts["failed"] == 0 and counts["errors"] == 0}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expect", type=int, default=None, help="the number of tests the marker selected when packed")
    ap.add_argument("--deselect-slow", action="store_true", help="leave out the tests also marked `slow`")
    ap.add_argument("--timeout", type=int, default=7000, help="seconds before pytest is stopped")
    ap.add_argument("--out", default="runs", help="parent directory of the run dir")
    a = ap.parse_args(argv)
    gpu = get_backend("auto")
    marker = "gpu and not slow" if a.deselect_slow else "gpu"
    command = "python bench/run_gpu_tests.py " + " ".join(argv if argv is not None else sys.argv[1:])
    run_dir = runs.new_run("M14", "cuda_tests", step="S5", owner="Abhishek", command=command.strip(), root=ROOT,
                           runs_dir=a.out, backend=gpu, params={"marker": marker, "expect": a.expect})
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rs", "-m", marker,
           f"--junitxml={run_dir / 'junit.xml'}", "tests"]
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=a.timeout)
        out, rc = (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired as e:
        out, rc = f"TIMEOUT after {a.timeout}s\n{e.stdout or ''}{e.stderr or ''}", 124
    (run_dir / "pytest_gpu.txt").write_text(out, encoding="utf-8")
    junit = run_dir / "junit.xml"
    if not junit.exists():
        runs.finish_run(run_dir, status="FAIL", notes=f"pytest wrote no junit file (exit {rc}): see pytest_gpu.txt")
        print("\n".join(out.splitlines()[-15:]))
        return 1
    counts = parse_junit(junit)
    checks = verdict(counts)
    ok = all(checks.values()) and rc == 0
    doc = {"marker": marker, "expect": a.expect, "pytest_exit": rc, "backend": gpu.name,
           "selected_as_expected": None if a.expect is None else counts["selected"] == a.expect,
           **counts, "checks": checks}
    (run_dir / "cuda_tests.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    stat = f"pytest -m '{marker}', {counts['selected']} selected"
    metrics = [{"id": f"S-CUDA-TESTS-{k.upper()}", "value": counts[k], "unit": "tests", "stat": stat}
               for k in ("passed", "failed", "errors", "skipped")]
    (run_dir / "summary.json").write_text(json.dumps({"metrics": metrics}, indent=2) + "\n", encoding="utf-8")
    where = "on a CUDA device" if gpu.is_gpu else "numpy backend: the tests are skipped, this is not a pass"
    runs.finish_run(run_dir, status="OK" if ok else "FAIL", notes=f"the tests marked gpu, {where}")
    for name, passed in checks.items():
        print(f"{'ok  ' if passed else 'FAIL'} {name}")
    print(f"selected {counts['selected']} (expected {a.expect}): passed {counts['passed']}, failed {counts['failed']}, "
          f"errors {counts['errors']}, skipped {counts['skipped']} (pytest exit {rc}, backend {gpu.name})")
    for t in counts["not_passed"][:20]:
        print(f"  {t['outcome']}: {t['test']} - {t['message'][:120]}")
    print("run dir:", run_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
