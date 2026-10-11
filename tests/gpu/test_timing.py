"""M07 S1 on the runner: the CUDA-event timer against a kernel of known duration (`__nanosleep`).

Two things are checked separately. The timer itself: the event time of a launch must agree with the
host clock around the same synchronised launch. The kernel's nominal duration: the module asks for
±10%; the nanosleep instruction only promises an approximate sleep, so a nominal miss while the two
clocks agree is reported as an expected failure with the measured ratio, not hidden and not a pass.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from vcloak.bench import timing

pytestmark = pytest.mark.gpu

REPS = 50
SLEEP_NS = 1_000_000  # the instruction's documented maximum per call is 1 ms
NOMINAL_MS = REPS * SLEEP_NS / 1e6
TOLERANCE = 0.10


@pytest.fixture(scope="module")
def cp(backend):  # noqa: ANN001, ANN201
    return backend.xp


@pytest.fixture(scope="module")
def sleep(cp):  # noqa: ANN001, ANN201
    kernel = timing.sleep_kernel(cp)
    try:
        kernel((1,), (1,), (np.uint32(1), np.uint32(1000)))
        cp.cuda.get_current_stream().synchronize()
    except Exception as e:  # noqa: BLE001 - nvrtc without __nanosleep, or a device below CC 7.0
        pytest.skip(f"the __nanosleep kernel does not build on this runner: {type(e).__name__}: {e}"[:300])
    return lambda: kernel((1,), (1,), (np.uint32(REPS), np.uint32(SLEEP_NS)))


def _wall_ms(cp, fn, runs: int) -> list[float]:  # noqa: ANN001
    stream = cp.cuda.get_current_stream()
    out = []
    for _ in range(runs):
        stream.synchronize()
        t0 = time.perf_counter_ns()
        fn()
        stream.synchronize()
        out.append((time.perf_counter_ns() - t0) / 1e6)
    return out


def test_event_timer_agrees_with_host_clock(cp, sleep) -> None:  # noqa: ANN001
    events = timing.summarise(timing.time_gpu(sleep, warmup=3, runs=20))
    wall = timing.summarise(_wall_ms(cp, sleep, 20))
    ratio = events["median_ms"] / wall["median_ms"]
    print(f"\nsleep kernel: events {events['median_ms']:.3f} ms, host clock {wall['median_ms']:.3f} ms, "
          f"ratio {ratio:.4f}, nominal {NOMINAL_MS:.1f} ms")
    assert abs(ratio - 1.0) <= TOLERANCE


def test_sleep_kernel_within_10_percent_of_nominal(cp, sleep) -> None:  # noqa: ANN001
    events = timing.summarise(timing.time_gpu(sleep, warmup=3, runs=20))
    ratio = events["median_ms"] / NOMINAL_MS
    print(f"\nsleep kernel: events {events['median_ms']:.3f} ms, nominal {NOMINAL_MS:.1f} ms, ratio {ratio:.4f}, "
          f"cv {events['cv']:.4f}")
    if abs(ratio - 1.0) > TOLERANCE:
        pytest.xfail(f"the kernel slept {ratio:.3f} x its nominal {NOMINAL_MS:.0f} ms (median of 20, CUDA events); "
                     "the instruction's sleep is approximate, see test_event_timer_agrees_with_host_clock")


def test_time_gpu_setup_is_outside_the_timed_region(cp, sleep) -> None:  # noqa: ANN001
    """A slow `setup` on the same stream must not be charged to `fn`."""
    quick = cp.RawKernel(timing.SLEEP_KERNEL_SRC, "sleep_kernel")

    def fn() -> None:
        quick((1,), (1,), (np.uint32(1), np.uint32(100_000)))  # nominally 0.1 ms

    with_setup = timing.summarise(timing.time_gpu(fn, warmup=3, runs=20, setup=sleep))
    assert with_setup["median_ms"] < 0.5 * NOMINAL_MS
