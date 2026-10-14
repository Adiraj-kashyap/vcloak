"""M15 S1: the schedule, the warm-up rule and the statistics of the end-to-end load generator.
All inputs are synthetic; nothing here is a measurement."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from vcloak.bench import e2e
from vcloak.bench.derive import NM

ROOT = Path(__file__).resolve().parents[2]


def _script():
    spec = importlib.util.spec_from_file_location("run_e2e", ROOT / "bench" / "run_e2e.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_users_talk_in_pairs_and_an_odd_number_is_refused() -> None:
    assert e2e.pairs(6) == [(0, 1), (2, 3), (4, 5)]
    for bad in (0, 1, 7):
        with pytest.raises(ValueError, match="even number"):
            e2e.pairs(bad)


def test_poisson_times_are_increasing_inside_the_run_and_near_the_rate() -> None:
    t = e2e.poisson_times(np.random.default_rng(1), 5.0, 2000.0)
    assert all(b > a for a, b in zip(t, t[1:], strict=False)) and 0 < t[0] and t[-1] < 2000.0
    assert abs(len(t) / 2000.0 - 5.0) < 0.25  # 10000 expected, sd 100
    with pytest.raises(ValueError):
        e2e.poisson_times(np.random.default_rng(1), 0.0, 10.0)


def test_schedule_is_fixed_by_the_seed_and_is_the_same_for_both_modes() -> None:
    a, b = e2e.schedule(10, 1.0, 60.0, seed=15), e2e.schedule(10, 1.0, 60.0, seed=15)
    assert a == b and a != e2e.schedule(10, 1.0, 60.0, seed=16)
    assert [s.t for s in a] == sorted(s.t for s in a)
    assert {s.user for s in a} == set(range(10)) and all(s.conv == s.user // 2 for s in a)
    # a user's stream does not depend on how many other users there are
    small = [s for s in e2e.schedule(4, 1.0, 60.0, seed=15)]
    assert small == [s for s in e2e.schedule(10, 1.0, 60.0, seed=15) if s.user < 4]


def _sample(t: float, ack: float | None = 10.0, readable: float | None = 50.0, error: str = "") -> e2e.Sample:
    return e2e.Sample(user=0, conv=0, t_sched=t, t_submit=t + 0.001, ack_ms=ack, readable_ms=readable,
                      status=0 if error else 201, error=error)


def test_warmup_is_excluded_by_the_scheduled_time_not_by_the_answer() -> None:
    # scheduled in the warm-up but answered long after it: still excluded; scheduled at the boundary: counted
    late = _sample(19.9, ack=5000.0)
    samples = [late, _sample(20.0), _sample(139.999), _sample(140.0)]
    m = e2e.measured(samples, warmup_s=20.0, duration_s=120.0)
    assert [s.t_sched for s in m] == [20.0, 139.999]
    s = e2e.summarise(samples, 20.0, 120.0)
    assert (s["scheduled"], s["excluded_warmup"], s["excluded_after"]) == (2, 1, 1)
    assert s["ack_ms"]["max"] == 10.0


def test_a_failed_send_is_counted_and_is_in_no_latency_series() -> None:
    samples = [_sample(1.0), _sample(2.0, ack=None, readable=None, error="queue_full"),
               _sample(3.0, readable=None), _sample(4.0, ack=30.0, readable=70.0)]
    s = e2e.summarise(samples, 0.0, 10.0)
    assert (s["scheduled"], s["acked"], s["errors"]) == (4, 3, {"queue_full": 1})
    assert s["ack_ms"]["n"] == 3 and s["readable_ms"]["n"] == 2 and s["readable_missing"] == 1
    assert s["offered_msgs_s"] == 0.4 and s["achieved_msgs_s"] == pytest.approx(0.3)
    assert s["ack_ms"]["p50"] == 10.0 and s["ack_ms"]["max"] == 30.0


def test_an_empty_series_is_not_measured_never_zero() -> None:
    s = e2e.summarise([_sample(1.0, ack=None, readable=None, error="ReadTimeout")], 0.0, 10.0)
    assert s["acked"] == 0 and s["ack_ms"] == {"n": 0, "p50": NM, "p95": NM, "p99": NM, "mean": NM, "max": NM}
    assert s["readable_ms"]["p99"] == NM


def test_the_service_is_never_started_with_compare_and_gets_the_public_parameters() -> None:
    mod = _script()
    a = mod.build_parser().parse_args(["--mode", "vcloak", "--users", "4", "--slots", "256", "--epoch-ms", "100"])
    args = mod.serve_args(a, 8123)
    assert "--compare" not in args and "--sessions" in args
    assert args[args.index("--slots") + 1] == "256" and args[args.index("--epoch-ms") + 1] == "100"
    assert args[args.index("--mode") + 1] == "vcloak" and args[args.index("--host") + 1] == "127.0.0.1"
    assert mod.serve_child(["--bench-users", "4", "--mode", "vcloak", "--store", "sqlite", "--compare"]) == 2
    off = mod.build_parser().parse_args(["--mode", "baseline", "--users", "2", "--sessions", "off"])
    assert "--sessions" not in mod.serve_args(off, 1)
