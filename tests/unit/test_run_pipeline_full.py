"""M07 S5: the full mode of bench/run_pipeline.py. Stage records are made up here to check the
bookkeeping (device/host split, p99, real-time gate, UNSTABLE handling); they are not measurements."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import fakecupy
from vcloak import runs
from vcloak.gpu.engine import STAGES
from vcloak.gpu.runtime import get_backend

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import run_pipeline as rp  # noqa: E402


def record(device_ms: float, host_ms: float) -> dict[str, float]:
    """A stage record whose device stages share `device_ms` equally."""
    r = dict.fromkeys(STAGES, device_ms / len(rp.DEVICE_STAGES))
    r["host"] = host_ms
    r["total"] = device_ms + host_ms
    return r


class StubEngine:
    def __init__(self, records: list[dict[str, float]]) -> None:
        self.records, self.calls = records, 0

    def call(self, i: int) -> None:
        self.calls += 1

    def last_timings(self) -> dict[str, float]:
        return self.records[self.calls % len(self.records)]


def test_device_stages_exclude_only_the_host() -> None:
    assert "host" not in rp.DEVICE_STAGES and set(rp.DEVICE_STAGES) | {"host"} == set(STAGES)
    assert rp.FULL_WRITE_SLOTS == (2**6, 2**10, 2**12, 2**14, 2**16)
    assert rp.FULL_READ_K[0] == 64 and rp.FULL_READ_K[-1] == 4096
    assert rp.FULL_RUNS >= 100  # a p99 needs more than the 50 runs of a kernel timing


def test_stats_full_splits_device_and_host() -> None:
    s = rp.stats_full([record(8.0, 200.0), record(8.0, 202.0), record(8.0, 198.0)])
    assert s["median_ms"] == pytest.approx(208.0)
    assert s["device"]["median_ms"] == pytest.approx(8.0) and s["host"]["median_ms"] == pytest.approx(200.0)
    assert s["host_share_of_median_total"] == pytest.approx(200.0 / 208.0)
    assert s["stage_median_ms"]["sort"] == pytest.approx(1.0) and set(s["stage_p99_ms"]) == set(STAGES)


def test_measure_full_stops_after_a_stable_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "WARM_SECONDS", 0.0)
    eng = StubEngine([record(1.0, 1.0)])
    attempts = rp.measure_full(eng.call, eng, warmup=10, n_runs=20, sample=fakecupy.clock_sample)
    assert len(attempts) == 1 and attempts[0]["stable"] and attempts[0]["runs"] == 20
    assert attempts[0]["warmup_calls"] == 10 and eng.calls == 30


def test_measure_full_repeats_once_and_keeps_both(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "WARM_SECONDS", 0.0)
    eng = StubEngine([record(1.0, 1.0), record(1.0, 9.0)])  # CV far above the limit
    attempts = rp.measure_full(eng.call, eng, warmup=1, n_runs=10, sample=fakecupy.clock_sample)
    assert [a["attempt"] for a in attempts] == [1, 2] and not attempts[-1]["stable"]
    assert all(len(a["records"]) == 10 for a in attempts)


def test_low_clock_is_recorded_but_not_unstable_for_the_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "WARM_SECONDS", 0.0)
    eng = StubEngine([record(1.0, 1.0)])
    (a,) = rp.measure_full(eng.call, eng, warmup=1, n_runs=5, sample=lambda: fakecupy.clock_sample(585))
    assert a["stable"] and a["clock"]["status"] == "LOW" and a["clock"]["after_mhz"] == 585


def config_entry(kind: str, size: int, records: list[dict[str, float]], stable: bool = True) -> dict:
    return {"kind": kind, "size": size, "mismatches": 0,
            "attempts": [{"attempt": 1, "stable": stable, "clock": {"status": "OK", "after_mhz": 1590, "max_mhz": 1590},
                          **rp.stats_full(records)}]}


def test_realtime_gate_and_metrics() -> None:
    configs = [config_entry("write_epoch", 4096, [record(2.0, 9.0)] * 5),
               config_entry("write_epoch", 65536, [record(8.0, 200.0)] * 5),
               config_entry("read_window", 128, [record(0.4, 0.1)] * 5),
               config_entry("read_window", 1024, [record(0.4, 0.1)] * 5, stable=False),
               {"kind": "read_window", "size": 2048, "mismatches": 3}]
    gate = rp.realtime_gate(configs, 200)
    assert [(g["slots"], g["pass_total"], g["pass_device"]) for g in gate] == [(4096, True, True), (65536, False, True)]

    by_id = {m["id"]: m for m in rp.full_metrics(configs, 200, None)}
    assert len(by_id) == 5 * len(configs)
    assert by_id["P-WRITE-EPOCH-P99-S65536"]["value"] == pytest.approx(208.0)
    assert "FAIL" in by_id["P-WRITE-EPOCH-P99-S65536"]["note"] and "PASS" in by_id["P-WRITE-EPOCH-P99-S4096"]["note"]
    assert by_id["P-WRITE-EPOCH-DEVICE-P99-S65536"]["value"] == pytest.approx(8.0)
    assert by_id["P-WRITE-EPOCH-HOST-MS-S65536"]["value"] == pytest.approx(200.0)
    assert by_id["P-READ-WINDOW-P99-K128"]["value"] == pytest.approx(0.5)
    assert by_id["P-READ-WINDOW-P99-K1024"]["value"] == "UNSTABLE"  # reported, not replaced by its median
    assert by_id["P-READ-WINDOW-MS-K2048"]["value"] == "NOT_MEASURED"
    assert "oracle" in by_id["P-READ-WINDOW-MS-K2048"]["note"]

    nothing = rp.full_metrics([{"kind": "write_epoch", "size": 64, "mismatches": 0}], 200, "numpy backend")
    assert all(m["value"] == "NOT_MEASURED" and m["note"] == "numpy backend" for m in nothing)


def test_full_mode_on_numpy_measures_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "get_backend", lambda: get_backend("numpy"))
    monkeypatch.setattr(rp, "FULL_WRITE_SLOTS", (64, 1024))
    monkeypatch.setattr(rp, "FULL_READ_K", (64, 128))
    assert rp.main(["--dev", "--full", "--seed", "7", "--out", str(tmp_path)]) == 0
    (d,) = tmp_path.glob("*_M07_pipeline")
    m = runs.read_manifest(d)
    s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    assert m["module"] == "M07" and m["step"] == "S5" and m["status"] == "NOT_MEASURED"
    assert s["mismatches"] == 0 and s["realtime_gate"] == [] and s["host_profile"] is None
    assert len(s["metrics"]) == 20 and all(x["value"] == "NOT_MEASURED" for x in s["metrics"])
    assert not (d / "raw.csv").exists() and not (d / "host_profile.txt").exists()
