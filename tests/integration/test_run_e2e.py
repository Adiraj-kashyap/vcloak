"""M15 S1: the load generator against the real service, both modes, sessions on (per-user DPoP clients).
A correctness run on the numpy backend and the in-memory store: no number of it is a result."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mode", ["baseline", "vcloak"])
def test_one_small_cell_is_sent_acknowledged_and_read_back(mode: str, tmp_path: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "bench" / "run_e2e.py"), "--mode", mode, "--users", "2", "--rate", "3",
         "--duration", "3", "--warmup", "1", "--drain", "3", "--poll-ms", "100", "--store", "sqlite",
         "--out", str(tmp_path)], cwd=ROOT, capture_output=True, text=True, timeout=300,
        env={**os.environ, "VCLOAK_BACKEND": "numpy"})
    assert r.returncode == 0, r.stdout + r.stderr
    run_dir = next(tmp_path.iterdir())
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    man = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert man["status"] == "OK" and man["env"]["backend"] == "numpy"
    assert s["metrics"] == [] and "never a performance result" in s["reason"]  # numpy: no metric is offered
    assert s["mode"] == mode == s["service"]["windows"]["mode"]
    assert (s["ack"], s["sessions"], s["ws_sockets"]) == ("stored", True, 0)
    st = s["stats"]
    assert st["acked"] == st["scheduled"] > 0 and st["errors"] == {} and st["readable_missing"] == 0
    assert (s["service"]["delta"]["epochs"] > 0) == (mode == "vcloak")
    rows = list(csv.DictReader((run_dir / "samples.csv").open(encoding="utf-8")))
    assert sum(int(x["counted"]) for x in rows) == st["scheduled"]
    assert all(float(x["t_sched_s"]) >= 1.0 for x in rows if x["counted"] == "1")
    assert all(x["status"] == "201" for x in rows)


def test_the_cells_of_s2_run_in_order_and_each_leaves_its_own_run(tmp_path: Path) -> None:
    """The driver on the in-memory store: two modes x one user count x two repetitions, no metric offered."""
    r = subprocess.run(
        [sys.executable, str(ROOT / "bench" / "run_e2e_cells.py"), "--users", "2", "--reps", "2", "--rate", "3",
         "--duration", "2", "--warmup", "1", "--poll-ms", "100", "--pause", "0", "--store", "sqlite",
         "--out", str(tmp_path)], cwd=ROOT, capture_output=True, text=True, timeout=600,
        env={**os.environ, "VCLOAK_BACKEND": "numpy"})
    assert r.returncode == 0, r.stdout + r.stderr
    matrix = next(p for p in tmp_path.iterdir() if p.name.endswith("_M15_e2e_cells"))
    rows = list(csv.DictReader((matrix / "cells.csv").open(encoding="utf-8")))
    assert [(x["rep"], x["mode"]) for x in rows] == [("1", "baseline"), ("1", "vcloak"), ("2", "baseline"),
                                                    ("2", "vcloak")]
    assert all(x["exit_code"] == "0" and x["status"] == "OK" and x["acked"] == x["scheduled"] for x in rows)
    assert len({x["run_dir"] for x in rows}) == 4 and all((tmp_path / x["run_dir"]).is_dir() for x in rows)
    assert rows[0]["scheduled"] == rows[2]["scheduled"] == rows[1]["scheduled"]  # one schedule for every cell
    s = json.loads((matrix / "summary.json").read_text(encoding="utf-8"))
    assert s["metrics"] == [] and s["failed"] == [] and s["plan"]["users_per_conversation"] == 2
    cell = json.loads((tmp_path / rows[1]["run_dir"] / "summary.json").read_text(encoding="utf-8"))
    assert cell["rep"] == 1 and cell["users_per_conversation"] == 2 and cell["metrics"] == []
    assert cell["telemetry"]["available"] is False and cell["telemetry"]["reason"]  # no NVML on the laptop
    assert cell["db"]["available"] is False and cell["measured_unix"][1] - cell["measured_unix"][0] == 2.0
    bound = json.loads((matrix / "bucket_bound.json").read_text(encoding="utf-8"))
    assert bound[0]["users"] == 2 and "not a measurement" in bound[0]["kind"]
