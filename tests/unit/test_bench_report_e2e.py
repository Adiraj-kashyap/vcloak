"""M15 S3: the end-to-end metrics derived from ingested cells, the tables and notes made from them, and the
rule of scripts/check_metrics.py for a derivation run (ADR-028). All inputs are synthetic; nothing is a measurement."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

import check_metrics
from vcloak.bench import report_e2e
from vcloak.bench.derive import NM, UNSTABLE
from vcloak.bench.report import ReportError

T0 = 1000.0
DRIVER = "20261014-010000_M15_e2e_cells"


def _manifest(name: str, backend: str = "cupy", session: str = "s1", runner: str = "kaggle") -> dict[str, Any]:
    man: dict[str, Any] = {
        "run_id": name, "module": "M15", "step": "S2", "owner": "Divyansh", "git_sha": "abcdef0123", "dirty": False,
        "command": "python bench/run_e2e_cells.py", "seed": 15, "quick": False, "params": {"slots": 256},
        "env": {"os": "Linux", "python": "3.13", "backend": backend, "runner": runner, "session_id": session,
                "gpu": "Tesla T4", "cc": "7.5", "cuda": "12090", "cupy": "14.0.1", "driver": "580", "cpu_count": 4},
        "telemetry_start": {}, "telemetry_end": {}, "outputs": [], "status": "OK", "notes": ""}
    if backend == "cupy":
        man["gpu_job"] = {"job_id": "job1"}
    return man


def _cell(root: Path, users: int, mode: str, rep: int, *, ack: float, generator: float = 30.0, overflow: int = 0,
          backend: str = "cupy", session: str = "s1", lost: bool = False) -> str:
    """One cell: 10 sends in the measured interval [20, 30) with one outlier, and one send of the warm-up."""
    name = f"20261014-{users:03d}{rep}{len(mode):02d}_M15_{mode}_u{users}_r{rep}"
    d = root / "runs" / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(_manifest(name, backend, session,
                                                           "kaggle" if backend == "cupy" else "local")))
    rows = [[0, 0, 5.0, 5.0, ack, ack + 250.0, 201, "", 0]]
    rows += [[i % users, (i % users) // 2, 20.0 + i, 20.0 + i, ack + (40.0 if i == 9 else 0.0), ack + 250.0, 201, "",
              1] for i in range(10)]
    if lost:
        rows[3][4:8] = ["", "", 0, "ReadError"]
    with (d / "samples.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["user", "conv", "t_sched_s", "t_submit_s", "ack_ms", "readable_ms", "status", "error", "counted"])
        w.writerows(rows)
    with (d / "cpu.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "cpu_pct", "cpu_max_core_pct", "service_cpu_pct", "generator_cpu_pct", "service_rss_mb"])
        w.writerow([T0 + 1, 99, 99, 99, 400.0, 1])  # outside the measured interval: never read
        w.writerows([T0 + 20 + i, 10, 20, 12.0, generator, 1] for i in range(10))
    with (d / "telemetry.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "power_w", "util_gpu_pct"])
        w.writerows([T0 + 20 + i / 2, 30.0, 4 if i < 19 else 50] for i in range(20))
    (d / "summary.json").write_text(json.dumps({
        "metrics": [], "mode": mode, "users": users, "users_per_conversation": 2, "rep": rep, "ack": "stored",
        "sessions": True, "ws_sockets": 0, "store": "pg", "rate_per_user_s": 0.15, "duration_s": 10.0,
        "warmup_s": 20.0, "drain_s": 5.0, "poll_ms": 500.0, "clock": "monotonic",
        "measured_unix": [T0 + 20.0, T0 + 30.0], "telemetry": {"available": True}, "cpu": {"available": True},
        "reads": {"requests": 100, "errors": {}}, "stats": {"achieved_msgs_s": 123.0},
        "service": {"windows": {"epoch_ms": 200, "window_s": 60},
                    "delta": {"epochs": 50 if mode == "vcloak" else 0, "overflow": overflow, "missed": rep}}}))
    return name


def _tree(tmp_path: Path, users: tuple[int, ...] = (10, 50), **kw: Any) -> Path:
    """Baseline acks at 5 ms, V-cloak at 105 ms; `kw` maps (users, mode, rep) to overrides of one cell."""
    names = []
    for rep in (1, 2):
        for u in users:
            for mode in ("baseline", "vcloak"):
                over = kw.get(f"u{u}_{mode}_r{rep}", {})
                names.append(_cell(tmp_path, u, mode, rep, **{"ack": 5.0 if mode == "baseline" else 105.0, **over}))
    d = tmp_path / "runs" / DRIVER
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(_manifest(DRIVER)))
    (d / "summary.json").write_text(json.dumps({"metrics": []}))
    with (d / "cells.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_dir", "exit_code"])
        w.writerows([n, 0] for n in names)
    return tmp_path


def _derive(root: Path) -> tuple[Path, dict[str, Any]]:
    run_dir = report_e2e.derive(root / "runs" / DRIVER, root / "runs", root)
    man = json.loads((run_dir / "manifest.json").read_text())
    man["git_sha"] = "abcdef0123"  # tmp_path is not a git checkout
    (run_dir / "manifest.json").write_text(json.dumps(man))
    s = json.loads((run_dir / "summary.json").read_text())
    return run_dir, {m["id"]: m for m in s["metrics"]}


def test_metrics_are_means_of_two_repetitions_over_the_measured_interval(tmp_path: Path) -> None:
    run_dir, m = _derive(_tree(tmp_path))
    assert m["E2E-P50-U10-baseline"]["value"] == 5.0 and m["E2E-P50-U10-vcloak"]["value"] == 105.0
    assert m["E2E-ADDED-P50-U10"]["value"] == 100.0 and m["E2E-ADDED-READABLE-P50-U50"]["value"] == 100.0
    # 10 acks arrived in the 10 s interval; the field of the ingested summary (123.0) is never read
    assert m["E2E-TPUT-U10-vcloak"]["value"] == 1.0
    assert m["E2E-OVERFLOW-U10"]["value"] == 0 and m["E2E-GPUUTIL-U50"]["value"] == 4.0
    assert m["E2E-GPUUTIL-P95-U10"]["value"] == 50.0 and m["E2E-POWER-W-U10"]["value"] == 30.0
    man = json.loads((run_dir / "manifest.json").read_text())
    assert man["env"]["backend"] == "numpy" and man["derived_from"]["backend"] == "cupy"
    assert man["derived_from"]["session_id"] == "s1" and len(man["derived_from"]["runs"]) == 9


def test_repetitions_more_than_15_percent_apart_are_unstable_and_so_is_what_is_made_from_them(tmp_path: Path) -> None:
    _, m = _derive(_tree(tmp_path, u10_baseline_r2={"ack": 6.0}))
    assert m["E2E-P50-U10-baseline"]["value"] == UNSTABLE and m["E2E-P50-U10-baseline"]["reps"] == [5.0, 6.0]
    assert "15 % apart" in m["E2E-P50-U10-baseline"]["cause"]
    assert m["E2E-ADDED-P50-U10"]["value"] == UNSTABLE and "baseline p50" in m["E2E-ADDED-P50-U10"]["cause"]
    assert m["E2E-P50-U10-vcloak"]["value"] == 105.0 and m["E2E-ADDED-P50-U50"]["value"] == 100.0
    assert report_e2e.spread_pct(0.0, 0.0) == 0.0 and report_e2e.spread_pct(0.0, 1.0) == float("inf")
    assert report_e2e.combine([100.0, 115.0])["value"] == 107.5
    assert report_e2e.combine([100.0, 115.1])["value"] == UNSTABLE


def test_a_user_count_whose_generator_was_above_one_core_is_unstable_and_in_no_table(tmp_path: Path) -> None:
    root = _tree(tmp_path, users=(10, 200), u200_vcloak_r2={"generator": 121.0, "lost": True})
    run_dir, m = _derive(root)
    at200 = [x for k, x in m.items() if "-U200" in k]
    assert at200 and all(x["value"] == UNSTABLE and "load generator at its limit" in x["cause"] for x in at200)
    assert m["E2E-P50-U10-vcloak"]["value"] == 105.0
    s = report_e2e.render(run_dir, root / "results" / "e2e", root / "notes.md", "ISSUE-51", root, "ISSUE-52")
    assert s["users_valid"] == [10] and s["excluded"]["200"]["status"] == UNSTABLE
    with (root / "results" / "e2e" / "e2e_cells.csv").open(newline="") as f:
        assert {r["users"] for r in csv.DictReader(f)} == {"10"}
    assert "U200" not in (root / "results" / "e2e" / "e2e_metrics.csv").read_text()
    notes = (root / "notes.md").read_text()
    assert "E2E-P50-U10-vcloak-->" in notes and "U200" not in notes
    assert "**200 users (two per conversation): `UNSTABLE`.**" in notes and "ISSUE-51" in notes
    assert "Scaling behaviour is untested" in notes and "One user counts are not a scaling curve" in notes
    assert "1 sends of the measured interval got no answer (1 ReadError" in notes and "(ISSUE-52)" in notes
    assert "0 acknowledged sends were not read back" in notes and "30 to 121 % of one core" in notes
    assert "It does not mean that every epoch was written inside" in notes
    assert "several generator processes" in notes and "CAND_K sizing rule" in notes


def test_notes_keep_the_rest_of_the_file_and_are_replaced_in_place(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    run_dir, _ = _derive(root)
    notes = root / "notes.md"
    notes.write_text("# before\n")
    for _ in range(2):
        report_e2e.render(run_dir, root / "out", notes, root=root)
    text = notes.read_text()
    assert text.startswith("# before\n") and text.count(report_e2e.M15_BEGIN) == 1
    assert "105.0<!--M:E2E-P50-U10-vcloak-->" in text and "two per conversation" in text
    assert "## 4.E.6 Limitations" in text and "Excluded from every table" not in text


@pytest.mark.parametrize("change", [{"u10_vcloak_r1": {"backend": "numpy"}}, {"u50_baseline_r2": {"session": "s2"}}])
def test_refuses_cells_that_are_not_one_ingested_device_session(tmp_path: Path, change: dict[str, Any]) -> None:
    root = _tree(tmp_path, **change)
    with pytest.raises(ReportError):
        report_e2e.derive(root / "runs" / DRIVER, root / "runs", root)
    assert report_e2e.main(["derive", "--cells", str(root / "runs" / DRIVER), "--out", str(root / "runs")]) == 1
    assert not list((root / "runs").glob("*_e2e_metrics"))


def test_render_refuses_a_run_that_is_not_a_derivation(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    with pytest.raises(ReportError, match=NM):
        report_e2e.render(root / "runs" / DRIVER, root / "out", root=root)


# ---------------------------------------------------------------- scripts/check_metrics.py, rule 6 (ADR-028)

def _index(root: Path, run_dir: Path, metric: dict[str, Any], backend: str = "cupy", runner: str = "kaggle") -> Path:
    index = root / "index.md"
    index.write_text("| ID | Value | Unit | Stat | Module | Run dir | Command | Date | Quick | Backend | Runner |\n"
                     "|---|---|---|---|---|---|---|---|---|---|---|\n"
                     f"| {metric['id']} | {metric['value']} | ms | p50 | M15 | runs/{run_dir.name} | cmd | 20261014 "
                     f"| no | {backend} | {runner} |\n")
    return index


def test_check_metrics_accepts_a_gpu_metric_derived_from_ingested_runs_of_one_session(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    run_dir, m = _derive(root)
    assert check_metrics.check(_index(root, run_dir, m["E2E-P50-U10-vcloak"]), root) == []
    # the row carries the backend and runner of the device runs, not those of the laptop that derived it
    errs = check_metrics.check(_index(root, run_dir, m["E2E-P50-U10-vcloak"], "numpy", "local"), root)
    assert any("index says backend numpy" in e for e in errs)
    # the value is the one the derivation wrote
    errs = check_metrics.check(_index(root, run_dir, {"id": "E2E-P50-U10-vcloak", "value": 99.0}), root)
    assert any("!= summary.json value" in e for e in errs)


@pytest.mark.parametrize(("edit", "why"), [
    (lambda src, root: src.update(runs=[]), "names no run"),
    (lambda src, root: src["runs"].append("runs/missing"), "does not exist"),
    (lambda src, root: src.update(session_id="s9"), "never merged"),
    (lambda src, root: src.update(job_id="other"), "derived_from says other"),
])
def test_check_metrics_rejects_a_derivation_whose_sources_cannot_back_it(tmp_path: Path, edit: Any, why: str) -> None:
    root = _tree(tmp_path)
    run_dir, m = _derive(root)
    man = json.loads((run_dir / "manifest.json").read_text())
    edit(man["derived_from"], root)
    (run_dir / "manifest.json").write_text(json.dumps(man))
    errs = check_metrics.check(_index(root, run_dir, m["E2E-P50-U10-vcloak"]), root)
    assert len(errs) == 1 and why in errs[0]


def test_check_metrics_rejects_a_derivation_from_a_numpy_run(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    run_dir, m = _derive(root)
    local = _cell(root, 10, "vcloak", 3, ack=1.0, backend="numpy")
    man = json.loads((run_dir / "manifest.json").read_text())
    man["derived_from"]["runs"].append(f"runs/{local}")
    (run_dir / "manifest.json").write_text(json.dumps(man))
    errs = check_metrics.check(_index(root, run_dir, m["E2E-P50-U10-vcloak"]), root)
    assert len(errs) == 1 and "not an ingested device run" in errs[0]


def test_index_rows_are_copied_with_the_backend_and_runner_of_the_device_runs(tmp_path: Path) -> None:
    root = _tree(tmp_path, users=(10, 200), u200_baseline_r1={"generator": 118.0})
    run_dir, m = _derive(root)
    index = root / "index.md"
    index.write_text("| ID | Value | Unit | Stat | Module | Run dir | Command | Date | Quick | Backend | Runner |\n"
                     "|---|---|---|---|---|---|---|---|---|---|---|\n")
    assert report_e2e.index_metrics(run_dir, index) == len(m)
    rows, errs = check_metrics.parse_index(index)
    assert errs == [] and check_metrics.check(index, root) == []
    got = {r["id"]: r for r in rows}
    assert got["E2E-P50-U10-vcloak"]["value"] == "105.0" and got["E2E-P50-U200-vcloak"]["value"] == UNSTABLE
    assert {(r["backend"], r["runner"], r["run_dir"]) for r in rows} == {("cupy", "kaggle", f"runs/{run_dir.name}")}
    with pytest.raises(ReportError, match="already in"):
        report_e2e.index_metrics(run_dir, index)
