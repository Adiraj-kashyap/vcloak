"""Timers and statistics for every benchmark (ai/GPU_GUIDE.md §4).

GPU work is timed with CUDA events on one stream (`time_gpu`), CPU work with `perf_counter_ns`
(`time_cpu`). `summarise` turns a list of per-run milliseconds into the statistics that are reported.
`warm_until_stable` keeps the device busy until its SM clock stops rising, because a warm-up of a few
milliseconds leaves a GPU at its idle clock (ISSUE-7, ISSUE-11).

Nothing here decides what a number means: a time taken under the numpy backend is never a
performance result (ai/GPU_RUNNER.md §3).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np

CV_LIMIT = 0.10  # ai/GPU_RUNNER.md §7
CLOCK_LIMIT = 0.15  # SM clock change between the post-warm-up and the final snapshot
LOW_CLOCK_FRACTION = 0.85  # below this share of the device's maximum SM clock a run counts as low-clock
NM = "NOT_MEASURED"
UNSTABLE = "UNSTABLE"

# A kernel of known duration for the timer self-test: one thread sleeps `reps` times for `ns` nanoseconds.
SLEEP_KERNEL_SRC = r"""
extern "C" __global__ void sleep_kernel(unsigned int reps, unsigned int ns)
{
    for (unsigned int r = 0; r < reps; ++r) {
        __nanosleep(ns);
    }
}
"""


def summarise(times_ms: Any) -> dict[str, float]:
    """runs, median, p5, p95, p99, min, max, mean, std (ddof 1) and CV = std / mean of per-run times in ms."""
    a = np.asarray(times_ms, dtype=np.float64)
    if a.ndim != 1 or a.size == 0:
        raise ValueError("summarise needs a non-empty one-dimensional list of times")
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if a.size > 1 else 0.0
    return {"runs": int(a.size), "median_ms": float(np.median(a)), "p5_ms": float(np.percentile(a, 5)),
            "p95_ms": float(np.percentile(a, 95)), "p99_ms": float(np.percentile(a, 99)),
            "min_ms": float(a.min()), "max_ms": float(a.max()), "mean_ms": mean, "std_ms": std,
            "cv": std / mean if mean > 0 else 0.0}


def _check_counts(warmup: int, runs: int) -> None:
    if warmup < 0 or runs < 1:
        raise ValueError("warmup must be >= 0 and runs >= 1")


def time_gpu(fn: Callable[[], Any], warmup: int, runs: int, stream: Any = None, *,
             setup: Callable[[], Any] | None = None, cp: Any = None) -> list[float]:
    """Per-run milliseconds of `fn` between two CUDA events on `stream` (default: the current stream).

    `setup`, when given, runs before every call and outside the timed region (it restores the input).
    Both events are recorded on the stream, so work that `setup` queued is finished before the start
    event fires and `fn`'s work is finished before the end event does.
    """
    _check_counts(warmup, runs)
    if cp is None:
        import cupy as cp  # type: ignore[import-not-found,no-redef]
    stream = stream if stream is not None else cp.cuda.get_current_stream()
    start, end = cp.cuda.Event(), cp.cuda.Event()
    for _ in range(warmup):
        if setup is not None:
            setup()
        fn()
    stream.synchronize()
    times: list[float] = []
    for _ in range(runs):
        if setup is not None:
            setup()
        start.record(stream)
        fn()
        end.record(stream)
        end.synchronize()
        times.append(float(cp.cuda.get_elapsed_time(start, end)))
    return times


def time_cpu(fn: Callable[[], Any], warmup: int, runs: int, *,
             setup: Callable[[], Any] | None = None) -> list[float]:
    """Per-run milliseconds of `fn` on the host, with `time.perf_counter_ns`. `setup` is not timed."""
    _check_counts(warmup, runs)
    for _ in range(warmup):
        if setup is not None:
            setup()
        fn()
    times: list[float] = []
    for _ in range(runs):
        if setup is not None:
            setup()
        t0 = time.perf_counter_ns()
        fn()
        times.append((time.perf_counter_ns() - t0) / 1e6)
    return times


def warm_until_stable(fn: Callable[[], Any], *, min_calls: int, snapshot: Callable[[], dict[str, Any]],
                      sync: Callable[[], Any] | None = None, min_seconds: float = 1.0,
                      max_seconds: float = 6.0, poll_seconds: float = 0.25) -> dict[str, Any]:
    """Call `fn` (then `sync`) until at least `min_calls` calls and `min_seconds` have passed and the SM
    clock has not risen over two consecutive polls, or until `max_seconds`. Returns the last snapshot plus
    the calls, the seconds spent and the polled clocks. Without NVML the loop ends at `min_seconds`.
    `snapshot` should be cheap (`telemetry.sample`): the device idles while it runs."""
    t0 = time.monotonic()
    calls, flat, last_poll = 0, 0, t0
    clocks: list[Any] = []
    while True:
        fn()
        if sync is not None:
            sync()  # launches are asynchronous: without this the loop would only fill the queue
        calls += 1
        now = time.monotonic()
        if now - last_poll >= poll_seconds:
            last_poll = now
            clock = snapshot().get("sm_clock_mhz")
            if clock is None:
                flat = 2  # no clock to wait for
            else:
                flat = flat + 1 if clocks and clock <= clocks[-1] else 0
                clocks.append(clock)
        elapsed = now - t0
        if calls >= min_calls and elapsed >= min_seconds and (flat >= 2 or elapsed >= max_seconds):
            break
    return {"snapshot": snapshot(), "calls": calls, "seconds": time.monotonic() - t0, "clocks_mhz": clocks}


def clock_check(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare the SM clock after the warm-up with the one after the last timed run.

    status: OK, UNSTABLE (changed by more than CLOCK_LIMIT in either direction), LOW (stable, but below
    LOW_CLOCK_FRACTION of the device's maximum SM clock) or NOT_MEASURED when NVML gave no clock."""
    a, b = before.get("sm_clock_mhz"), after.get("sm_clock_mhz")
    top = after.get("sm_clock_max_mhz") or before.get("sm_clock_max_mhz")
    if not a or not b:
        return {"status": NM, "reason": "NVML reported no SM clock", "before_mhz": a, "after_mhz": b,
                "max_mhz": top}
    rel = (float(b) - float(a)) / float(a)
    out = {"before_mhz": a, "after_mhz": b, "max_mhz": top, "relative_change": rel,
           "fraction_of_max": min(float(a), float(b)) / float(top) if top else None}
    if abs(rel) > CLOCK_LIMIT:
        out["status"] = UNSTABLE
    elif top and min(float(a), float(b)) < LOW_CLOCK_FRACTION * float(top):
        out["status"] = "LOW"
    else:
        out["status"] = "OK"
    return out


def stable(cv: float, clock: dict[str, Any], *, low_clock_is_unstable: bool = True) -> bool:
    """The acceptance rule of one attempt: CV within the limit and a clock that neither moved nor,
    for kernel sweeps, stayed low. A clock that NVML could not report does not fail the attempt."""
    if cv > CV_LIMIT or clock.get("status") == UNSTABLE:
        return False
    return not (low_clock_is_unstable and clock.get("status") == "LOW")


def sleep_kernel(cp: Any) -> Any:
    """The compiled self-test kernel (needs compute capability >= 7.0 for the nanosleep instruction)."""
    return cp.RawKernel(SLEEP_KERNEL_SRC, "sleep_kernel")
