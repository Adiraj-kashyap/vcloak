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
