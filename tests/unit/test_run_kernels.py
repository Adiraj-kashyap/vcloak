"""M07 S2-S4: bench/run_kernels.py. The numpy backend must measure nothing; the measuring code paths
are driven with tests/fakecupy.py (a stand-in device) into tmp_path, to check the flow and the
bookkeeping only. No number produced here is a result."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

import fakecupy
from vcloak import runs
from vcloak.bench import derive
from vcloak.gpu import telemetry
from vcloak.gpu.runtime import get_backend

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import run_kernels as rk  # noqa: E402


def summary(run_dir: Path) -> dict:
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))


def only_run(out: Path, name: str) -> Path:
    (d,) = out.glob(f"*_M07_{name}*")
    return d


@pytest.fixture
def numpy_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rk, "get_backend", lambda: get_backend("numpy"))


@pytest.fixture
def fake_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rk, "get_backend", fakecupy.backend)
    monkeypatch.setattr(telemetry, "sample", fakecupy.clock_sample)
    monkeypatch.setattr(rk, "RAMP_LOG2N", 6)
    monkeypatch.setattr(rk, "WARM_MIN_S", 0.0)
    monkeypatch.setattr(rk, "WARM_MAX_S", 0.2)
    monkeypatch.setenv("VCLOAK_SESSION_ID", "20260101-000000")
    monkeypatch.setenv("VCLOAK_RUNNER", "kaggle")


@pytest.mark.parametrize("part", ["gpu", "cpu", "crossover"])
def test_numpy_backend_measures_nothing(part: str, tmp_path: Path, numpy_backend: None) -> None:
    assert rk.main(["--part", part, "--seed", "7", "--out", str(tmp_path)]) == 0
    d = only_run(tmp_path, {"gpu": "kernel_sweep", "cpu": "cpu_baselines", "crossover": "crossover"}[part])
    m = runs.read_manifest(d)
    s = summary(d)
    assert m["status"] == "NOT_MEASURED" and m["env"]["backend"] == "numpy"
    assert s["metrics"] and all(x["value"] == "NOT_MEASURED" for x in s["metrics"])
    assert not (d / "raw.csv").exists()
    assert s.get("mismatches", 0) == 0


def test_gpu_part_flow_with_stand_in_device(tmp_path: Path, fake_gpu: None) -> None:
    assert rk.main(["--part", "gpu", "--seed", "7", "--sweep", "6:7", "--runs", "3", "--out", str(tmp_path)]) == 0
    d = only_run(tmp_path, "kernel_sweep")
    s = summary(d)
    assert s["mismatches"] == 0 and s["fused_differs_from_global"] == []
    assert set(s["sweeps"]) == set(rk.GPU_KERNELS)
    for kernel, points in s["sweeps"].items():
        assert [p["log2n"] for p in points] == [6, 7], kernel
        for p in points:
            assert p["median_ms"] > 0 and p["attempts"] and "times_ms" not in p["attempts"][0]
            assert p["attempts"][0]["warm"]["calls"] >= 10  # ai/GPU_GUIDE.md §4: WARMUP >= 10
    assert all(p["identical_to_global"] for p in s["sweeps"]["bitonic_fused"])
    with (d / "raw.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    attempts = sum(len(p["attempts"]) for pts in s["sweeps"].values() for p in pts)
    assert len(rows) == 3 * attempts
    ids = [x["id"] for x in s["metrics"]]
    assert len(ids) == len(set(ids))
    for want in ("K-BITONIC-GLOBAL-MS-2^6", "K-BITONIC-FUSED-MS-2^7", "K-BITONIC-BW-PCT-2^6", "K-BITONIC-E2E-MS-2^7",
                 "K-CHACHA-MS-2^6", "K-AEADOPEN-MS-2^6", "K-BUCKETPRF-MS-2^7", "K-CHACHA-GBS", "K-AEADOPEN-ROWS-S",
                 "K-BUCKETPRF-ROWS-S", "TEL-SMCLK-MEDIAN", "TEL-POWER-W-MEDIAN"):
        assert want in ids
    # every metric is either a number backed by a stable point or the UNSTABLE flag: never a silent drop
    by_id = {x["id"]: x for x in s["metrics"]}
    for p in s["sweeps"]["bitonic_fused"]:
        v = by_id[f"K-BITONIC-FUSED-MS-2^{p['log2n']}"]["value"]
        assert v == "UNSTABLE" if p["unstable"] else v == pytest.approx(p["median_ms"], abs=1e-5)
    g = s["sweeps"]["bitonic_global"][0]
    assert g["rounds"] == derive.rounds(64) == 21 and g["bytes_moved_model"] == 21 * 64 * 24 * 2


def test_low_clock_is_repeated_once_and_labelled(tmp_path: Path, fake_gpu: None,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry, "sample", lambda: fakecupy.clock_sample(585))
    assert rk.main(["--part", "gpu", "--seed", "7", "--sweep", "6:6", "--runs", "3", "--out", str(tmp_path)]) == 0
    s = summary(only_run(tmp_path, "kernel_sweep"))
    p = s["sweeps"]["chacha_tags"][0]
    assert len(p["attempts"]) == 2 and "ramp_before_repeat" in p["attempts"][0]
    assert p["low_clock"] and p["clock"] == "LOW"
    assert "chacha_tags@2^6" in s["low_clock"]
    note = next(x["note"] for x in s["metrics"] if x["id"] == "K-CHACHA-MS-2^6")
    assert "LOW clock" in note and "585" in note


def test_cpu_and_crossover_flow_in_one_session(tmp_path: Path, fake_gpu: None) -> None:
    common = ["--seed", "7", "--sweep", "6:7", "--out", str(tmp_path)]
    assert rk.main(["--part", "gpu", "--runs", "3", *common]) == 0
    assert rk.main(["--part", "cpu", *common]) == 0
    c = summary(only_run(tmp_path, "cpu_baselines"))
    assert c["mismatches"] == 0 and c["timer"] == "time.perf_counter_ns"
    for name in ("oracle_bitonic", "views_bitonic", "lexsort"):
        assert [p["log2n"] for p in c["sweeps"][name]] == [6, 7]
        assert all(p["attempts"][-1]["runs"] == rk.CPU_RUNS for p in c["sweeps"][name])
    ids = {x["id"] for x in c["metrics"]}
    assert {"CPU-BITONIC-MS-2^6", "CPU-BITONIC-VIEWS-MS-2^7", "CPU-LEXSORT-MS-2^6", "CPU-BITONIC-NUMBA-MS-2^6"} <= ids

    assert rk.main(["--part", "crossover", "--seed", "7", "--out", str(tmp_path)]) == 0
    d = only_run(tmp_path, "crossover")
    x = summary(d)
    assert x["inputs"]["session_id"] == "20260101-000000"
    assert x["inputs"]["gpu_run"].endswith("kernel_sweep") and x["inputs"]["cpu_run"].endswith("cpu_baselines")
    assert [r["log2n"] for r in x["table"]] == [6, 7]
    assert all(r["cpu_baseline"] in ("oracle_bitonic", "views_bitonic", "numba_bitonic") for r in x["table"])
    assert all(r["cpu_baseline"] == "lexsort" for r in x["table_vs_lexsort"])
    by_id = {m["id"]: m for m in x["metrics"]}
    assert by_id["X-SPEEDUP-2^16"]["value"] == "NOT_MEASURED"  # 2^16 was not swept here
    assert "X-CROSSOVER-N" in by_id and x["caveat"] and "Fake GPU" in x["pair"]
    assert runs.read_manifest(d)["params"]["session_id"] == "20260101-000000"


def test_crossover_refuses_another_session(tmp_path: Path, fake_gpu: None, monkeypatch: pytest.MonkeyPatch) -> None:
    common = ["--seed", "7", "--sweep", "6:6", "--out", str(tmp_path)]
    assert rk.main(["--part", "gpu", "--runs", "3", *common]) == 0
    monkeypatch.setenv("VCLOAK_SESSION_ID", "20260102-000000")  # the CPU side comes from a later session
    assert rk.main(["--part", "cpu", *common]) == 0
    assert rk.main(["--part", "crossover", "--seed", "7", "--out", str(tmp_path)]) == 0
    d = only_run(tmp_path, "crossover")
    assert runs.read_manifest(d)["status"] == "NOT_MEASURED"
    assert all(m["value"] == "NOT_MEASURED" for m in summary(d)["metrics"])
    assert "kernel_sweep" in summary(d)["reason"]


def test_cpu_runs_and_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    assert rk.cpu_runs_for(20, False) == 10 and rk.cpu_runs_for(21, False) == 5 and rk.cpu_runs_for(12, True) == 5
    monkeypatch.setattr(rk, "CPU_BUDGET_S", 0.0)
    attempts, note = rk.measure_cpu(lambda: None, 10, first_s=1.0)
    assert attempts[-1]["runs"] == 3 and "runs cut from 10 to 3" in note


def test_sweep_sizes(numpy_backend: None) -> None:
    ns = lambda **kw: type("A", (), {"sweep": None, "quick": False, **kw})()  # noqa: E731
    assert rk.sweep_sizes(ns(), get_backend("numpy")) == [10, 12]
    assert rk.sweep_sizes(ns(sweep="10:22"), get_backend("numpy")) == list(range(10, 23))
    gpu = fakecupy.backend()  # reports 2^30 free bytes, so max_log2n is below the sweep cap
    top = gpu.device_info()["max_log2n"]
    assert rk.sweep_sizes(ns(), gpu) == list(range(10, min(22, top) + 1))
    assert rk.sweep_sizes(ns(quick=True), gpu)[-1] == min(18, top)
    with pytest.raises(SystemExit):
        rk.sweep_sizes(ns(sweep="12:10"), gpu)
