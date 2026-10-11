"""M07 S6: the report builder. The run dirs here are made up in a temp folder: the tests check provenance
rules, sidecars and tags, not performance."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("matplotlib")

from vcloak.bench import report  # noqa: E402

SESSION = "20000101-000000"
LOGS = (10, 11)
STAGES = ("h2d", "tags", "sort", "compact", "d2h", "seal", "bucket", "open")


def _attempt(ms: float, stable: bool = True) -> dict[str, Any]:
    return {"attempt": 1, "median_ms": ms, "p5_ms": ms * 0.9, "p95_ms": ms * 1.1, "p99_ms": ms * 1.2, "cv": 0.05,
            "runs": 50, "stable": stable, "clock": {"after_mhz": 1000, "status": "OK"}}


def _run(root: Path, name: str, summary: dict[str, Any], *, backend: str = "cupy", session: str = SESSION,
         job: bool = True) -> Path:
    d = root / "runs" / f"20000101-000000_M07_{name}"
    d.mkdir(parents=True)
    man = {"run_id": d.name, "git_sha": "0" * 40, "quick": False, "status": "OK",
           "env": {"backend": backend, "runner": "kaggle", "session_id": session, "gpu": "Test GPU", "driver": "1",
                   "cuda": "1", "cupy": "1"}}
    if job:
        man["gpu_job"] = {"job_id": "20000101-000000_M07"}
    (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return d


def _make(root: Path, **kw: Any) -> dict[str, Path]:
    def pts(ms: float, unstable_at: int | None = None) -> list[dict[str, Any]]:
        return [{"log2n": v, "n": 2 ** v, "median_ms": ms * v, "cv": 0.05, "unstable": v == unstable_at,
                 "low_clock": False, "attempts": [_attempt(ms * v, v != unstable_at)], "bw_pct_of_peak": 10.0 * v}
                for v in LOGS]

    kernels = {"sweeps": {k: pts(1.0, 10 if k == "sort_e2e" else None)
                          for k in ("bitonic_global", "bitonic_fused", "sort_e2e", "chacha_tags", "aead_open",
                                    "bucket_prf")},
               "metrics": [{"id": "K-BITONIC-FUSED-MS-2^10", "value": 10.0},
                           {"id": "K-BITONIC-E2E-MS-2^10", "value": "UNSTABLE"}],
               "unstable": ["sort_e2e@2^10"], "peak_bw_gbs": 100.0, "host": {"cpu": "Test CPU", "cpu_count": 2}}
    cpu = {"sweeps": {b: pts(5.0) for b in ("oracle_bitonic", "views_bitonic", "numba_bitonic", "lexsort")},
           "metrics": [{"id": "CPU-BITONIC-MS-2^10", "value": 50.0}], "numba": {"numba": "0", "threads": 2},
           "oblivious": ["oracle_bitonic", "views_bitonic", "numba_bitonic"]}
    table = [{"log2n": v, "n": 2 ** v, "gpu_ms": 1.0, "cpu_ms": 5.0, "cpu_baseline": "numba_bitonic", "speedup": 5.0,
              "unstable": False} for v in LOGS]
    cross = {"table": table, "table_vs_lexsort": table, "metrics": [{"id": "X-SPEEDUP-2^16", "value": 5.0}],
             "crossover": {"kind": "at_or_below", "n": 1024, "unstable": True, "smallest_n": 1024},
             "inputs": {"session_id": kw.get("cross_session", SESSION)}}
    configs = []
    for kind, sizes in (("write_epoch", (64, 1024)), ("read_window", (64, 128))):
        for s in sizes:
            a = _attempt(float(s))
            a.update({"stage_median_ms": dict.fromkeys(STAGES, 0.5), "device": {"median_ms": 4.0, "p99_ms": 5.0},
                      "host": {"median_ms": float(s)}})
            configs.append({"kind": kind, "size": s, "attempts": [a]})
    pipe = {"configs": configs, "metrics": [{"id": "P-WRITE-EPOCH-P99-S64", "value": 76.8}], "unstable": [],
            "realtime_gate": [{"slots": 64, "epoch_ms": 200, "pass_total": True, "pass_device": True},
                              {"slots": 1024, "epoch_ms": 200, "pass_total": False, "pass_device": True}]}
    dirs = {"kernels": _run(root, "kernel_sweep", kernels, backend=kw.get("backend", "cupy"), job=kw.get("job", True)),
            "cpu": _run(root, "cpu_baselines", cpu, session=kw.get("cpu_session", SESSION)),
            "crossover": _run(root, "crossover", cross), "pipeline": _run(root, "pipeline", pipe)}
    (dirs["kernels"] / "telemetry.csv").write_text(
        "ts,sm_clock_mhz,power_w,temperature_c,power_limit_w\n1,1000,50,60,70\n2,900,60,61,70\n", encoding="utf-8")
    return dirs


def _generate(root: Path, dirs: dict[str, Path]) -> dict[str, Any]:
    return report.generate(dirs["kernels"], dirs["cpu"], dirs["crossover"], dirs["pipeline"], root / "results" / "perf",
                           notes=root / "docs" / "NOTES.md", root=root)


def test_every_figure_has_both_formats_and_a_sidecar_naming_its_run_dirs(tmp_path: Path) -> None:
    dirs = _make(tmp_path)
    s = _generate(tmp_path, dirs)
    out = tmp_path / "results" / "perf"
    assert len(s["figures"]) == len(report.FIGURES)
    for name in s["figures"]:
        side = json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
        assert (out / f"{name}.png").stat().st_size > 0 and (out / f"{name}.pdf").stat().st_size > 0
        assert side["run_dirs"] and all((tmp_path / d / "manifest.json").exists() for d in side["run_dirs"])
        assert side["session_id"] == SESSION and side["backend"] == "cupy" and side["metric_ids"]
    for t in s["tables"]:
        assert (out / t).read_text(encoding="utf-8").count("\n") > 1
    assert s["unstable"]["kernels"] == ["sort_e2e@2^10"]


def test_an_unstable_point_stays_in_the_table_and_is_flagged(tmp_path: Path) -> None:
    _generate(tmp_path, _make(tmp_path))
    rows = (tmp_path / "results" / "perf" / "kernel_sweep.csv").read_text(encoding="utf-8").splitlines()
    e2e = [r for r in rows if r.startswith("sort_e2e,10,")]
    assert len(e2e) == 1 and ",UNSTABLE," in e2e[0]


def test_notes_tag_every_metric_and_never_invent_a_missing_one(tmp_path: Path) -> None:
    _generate(tmp_path, _make(tmp_path))
    notes = (tmp_path / "docs" / "NOTES.md").read_text(encoding="utf-8")
    assert "10.0<!--M:K-BITONIC-FUSED-MS-2^10-->" in notes
    assert "UNSTABLE<!--M:K-BITONIC-E2E-MS-2^10-->" in notes
    assert "NOT_MEASURED<!--M:K-CHACHA-GBS-->" in notes  # absent from the made-up summaries
    assert "fails** the gate at SLOTS\n  1024" in notes


@pytest.mark.parametrize("kw, why", [({"backend": "numpy"}, "backend numpy"), ({"job": False}, "without an ingested"),
                                     ({"cpu_session": "other"}, "different runner sessions"),
                                     ({"cross_session": "other"}, "another session")])
def test_refuses_numpy_runs_and_mixed_sessions_and_writes_nothing(tmp_path: Path, kw: dict[str, Any], why: str) -> None:
    dirs = _make(tmp_path, **kw)
    with pytest.raises(report.ReportError, match=why):
        _generate(tmp_path, dirs)
    assert not list((tmp_path / "results").glob("**/*.png")) and not (tmp_path / "docs").exists()


def test_cli_reports_not_measured_instead_of_failing_loudly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dirs = _make(tmp_path, backend="numpy")
    rc = report.main(["--kernels", str(dirs["kernels"]), "--cpu", str(dirs["cpu"]), "--crossover",
                      str(dirs["crossover"]), "--pipeline", str(dirs["pipeline"]), "--out", str(tmp_path / "o")])
    assert rc == 1 and "NOT_MEASURED" in capsys.readouterr().out and not (tmp_path / "o").exists()
