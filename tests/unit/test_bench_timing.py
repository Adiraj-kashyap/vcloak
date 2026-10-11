"""M07 S1: the timer library. The CUDA path is exercised here with a stand-in for the cupy event API
(logic only); the real events are tested on the runner in tests/gpu/test_timing.py."""
from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest

from vcloak.bench import timing


def test_summarise_known_values() -> None:
    s = timing.summarise([1.0, 2.0, 3.0, 4.0, 5.0])
    assert s["runs"] == 5
    assert s["median_ms"] == 3.0
    assert s["mean_ms"] == 3.0
    assert s["min_ms"] == 1.0 and s["max_ms"] == 5.0
    assert s["std_ms"] == pytest.approx(np.std([1, 2, 3, 4, 5], ddof=1))
    assert s["cv"] == pytest.approx(s["std_ms"] / 3.0)
    assert s["p5_ms"] == pytest.approx(1.2) and s["p95_ms"] == pytest.approx(4.8)
    assert s["p99_ms"] == pytest.approx(4.96)


def test_summarise_single_run_and_bad_input() -> None:
    s = timing.summarise([7.5])
    assert s["std_ms"] == 0.0 and s["cv"] == 0.0 and s["median_ms"] == 7.5
    with pytest.raises(ValueError):
        timing.summarise([])
    with pytest.raises(ValueError):
        timing.summarise([[1.0, 2.0]])


def test_time_cpu_measures_a_known_sleep() -> None:
    times = timing.time_cpu(lambda: time.sleep(0.05), warmup=1, runs=5)
    assert len(times) == 5
    # a lower bound that holds on any OS; the upper bound is loose because Windows sleeps overshoot
    assert 50.0 <= timing.summarise(times)["median_ms"] < 90.0


def test_time_cpu_calls_and_setup_order() -> None:
    log: list[str] = []
    times = timing.time_cpu(lambda: log.append("fn"), warmup=2, runs=3, setup=lambda: log.append("setup"))
    assert len(times) == 3 and all(t >= 0 for t in times)
    assert log == ["setup", "fn"] * 5
    with pytest.raises(ValueError):
        timing.time_cpu(lambda: None, warmup=0, runs=0)


class _FakeEvent:
    def __init__(self, log: list[str]) -> None:
        self.log, self.t = log, 0.0

    def record(self, stream: object) -> None:
        self.t = time.perf_counter()
        self.log.append("record")

    def synchronize(self) -> None:
        self.log.append("event.sync")


def _fake_cp(log: list[str]) -> SimpleNamespace:
    stream = SimpleNamespace(synchronize=lambda: log.append("stream.sync"))
    cuda = SimpleNamespace(Event=lambda: _FakeEvent(log), get_current_stream=lambda: stream,
                           get_elapsed_time=lambda a, b: (b.t - a.t) * 1e3)
    return SimpleNamespace(cuda=cuda)


def test_time_gpu_event_protocol() -> None:
    log: list[str] = []
    times = timing.time_gpu(lambda: log.append("fn"), warmup=2, runs=3, setup=lambda: log.append("setup"),
                            cp=_fake_cp(log))
    assert len(times) == 3 and all(t >= 0 for t in times)
    # warm-up, one synchronisation, then setup outside each (record, fn, record, wait) region
    assert log == ["setup", "fn"] * 2 + ["stream.sync"] + ["setup", "record", "fn", "record", "event.sync"] * 3


def test_warm_until_stable_waits_for_a_flat_clock() -> None:
    clocks = iter([600, 900, 1400, 1590, 1590, 1590, 1590, 1590])
    calls = {"fn": 0, "sync": 0}

    def bump(name: str) -> None:
        calls[name] += 1

    out = timing.warm_until_stable(lambda: bump("fn"), min_calls=5, snapshot=lambda: {"sm_clock_mhz": next(clocks)},
                                   sync=lambda: bump("sync"), min_seconds=0.0, max_seconds=5.0, poll_seconds=0.01)
    assert out["clocks_mhz"][:4] == [600, 900, 1400, 1590]
    assert out["clocks_mhz"][-3:] == [1590, 1590, 1590]  # two polls without a rise after reaching it
    assert out["calls"] >= 5 and calls["sync"] == calls["fn"] == out["calls"]


def test_warm_until_stable_without_nvml_stops_at_min() -> None:
    out = timing.warm_until_stable(lambda: None, min_calls=3, snapshot=lambda: {"available": False},
                                   min_seconds=0.05, max_seconds=5.0, poll_seconds=0.01)
    assert out["calls"] >= 3 and out["clocks_mhz"] == [] and 0.05 <= out["seconds"] < 2.0


def test_warm_until_stable_gives_up_at_max_seconds() -> None:
    rising = iter(range(100, 100000))
    out = timing.warm_until_stable(lambda: None, min_calls=1, snapshot=lambda: {"sm_clock_mhz": next(rising)},
                                   min_seconds=0.0, max_seconds=0.1, poll_seconds=0.01)
    assert 0.1 <= out["seconds"] < 2.0


@pytest.mark.parametrize(("before", "after", "top", "status"), [
    (1590, 1590, 1590, "OK"),
    (1590, 1400, 1590, "OK"),  # -12%: inside the 15% limit and above 85% of the maximum
    (1590, 1200, 1590, "UNSTABLE"),
    (800, 1590, 1590, "UNSTABLE"),  # a rise counts as well
    (585, 585, 1590, "LOW"),
    (585, 585, None, "OK"),  # no maximum reported: only the change can be judged
    (None, 1590, 1590, "NOT_MEASURED"),
])
def test_clock_check(before: int | None, after: int | None, top: int | None, status: str) -> None:
    c = timing.clock_check({"sm_clock_mhz": before}, {"sm_clock_mhz": after, "sm_clock_max_mhz": top})
    assert c["status"] == status


def test_stable_rule() -> None:
    ok, low, moved, unknown = ({"status": s} for s in ("OK", "LOW", "UNSTABLE", "NOT_MEASURED"))
    assert timing.stable(0.05, ok) and timing.stable(0.05, unknown)
    assert not timing.stable(0.11, ok)
    assert not timing.stable(0.05, moved)
    assert not timing.stable(0.05, low)
    assert timing.stable(0.05, low, low_clock_is_unstable=False)
