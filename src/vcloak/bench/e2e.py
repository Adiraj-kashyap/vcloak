"""M15 (E6): the parts of the end-to-end load generator that need no network and no clock.

Who talks to whom, when every user sends, which samples count, and the statistics of what was recorded.
`bench/run_e2e.py` does the I/O. Nothing here is a measurement.

Rules that the audit of M15 reads here:
- the schedule is fixed by (users, rate, duration, seed) before anything is sent, so both modes of a cell get the
  same sends at the same offsets (A1);
- a sample is counted by the time it was *scheduled*, never by when its answer came: `warmup_s <= t_sched <
  warmup_s + duration_s` (A2). A slow answer cannot move a sample out of the measured interval.
"""
from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np

from vcloak.bench.derive import NM


@dataclass(frozen=True)
class Send:
    """One scheduled submission: `t` seconds after the start of the run."""
    user: int
    conv: int
    t: float


@dataclass
class Sample:
    """What happened to one scheduled submission. Times are seconds after the start of the run."""
    user: int
    conv: int
    t_sched: float
    t_submit: float | None = None  # when the request really left; None: never sent
    ack_ms: float | None = None  # submit -> the answer of POST /v1/messages
    readable_ms: float | None = None  # submit -> first poll of the peer that returned the payload
    status: int = 0
    error: str = ""  # empty: acknowledged with 201 or 202


def pairs(users: int) -> list[tuple[int, int]]:
    """Conversation pairs: users 2i and 2i+1 share conversation i."""
    if users < 2 or users % 2:
        raise ValueError(f"users must be an even number >= 2, got {users}")
    return [(2 * i, 2 * i + 1) for i in range(users // 2)]


def poisson_times(rng: np.random.Generator, rate_per_s: float, total_s: float) -> list[float]:
    """Arrival times of a Poisson process of this rate in [0, total_s): exponential gaps, summed."""
    if rate_per_s <= 0 or total_s <= 0:
        raise ValueError("rate and duration must be positive")
    out: list[float] = []
    t = float(rng.exponential(1.0 / rate_per_s))
    while t < total_s:
        out.append(t)
        t += float(rng.exponential(1.0 / rate_per_s))
    return out


def schedule(users: int, rate_per_s: float, total_s: float, seed: int) -> list[Send]:
    """Every send of the run, ordered by time. Each user has its own stream, so a run with more users contains
    the sends of the run with fewer; the mode is not an input."""
    sends = []
    for conv, members in enumerate(pairs(users)):
        for user in members:
            rng = np.random.default_rng([seed, user])
            sends += [Send(user, conv, t) for t in poisson_times(rng, rate_per_s, total_s)]
    return sorted(sends, key=lambda s: (s.t, s.user))


def measured(samples: list[Sample], warmup_s: float, duration_s: float) -> list[Sample]:
    """The samples of the measured interval, chosen by their scheduled time (see the module docstring)."""
    return [s for s in samples if warmup_s <= s.t_sched < warmup_s + duration_s]


def percentiles(values: list[float]) -> dict[str, Any]:
    """n, p50, p95, p99, mean and max of a series; every statistic is NOT_MEASURED when the series is empty."""
    if not values:
        return {"n": 0, "p50": NM, "p95": NM, "p99": NM, "mean": NM, "max": NM}
    a = np.asarray(values, dtype=np.float64)
    p50, p95, p99 = (float(x) for x in np.percentile(a, [50, 95, 99]))
    return {"n": int(a.size), "p50": p50, "p95": p95, "p99": p99, "mean": float(a.mean()), "max": float(a.max())}


def summarise(samples: list[Sample], warmup_s: float, duration_s: float) -> dict[str, Any]:
    """The statistics of one cell over the measured interval. A failed submission is counted, never dropped:
    it is in `scheduled` and in `errors`, and it is in no latency series."""
    m = measured(samples, warmup_s, duration_s)
    ok = [s for s in m if not s.error and s.ack_ms is not None]
    seen = [s for s in ok if s.readable_ms is not None]
    lag = [(s.t_submit - s.t_sched) * 1000.0 for s in m if s.t_submit is not None]
    return {
        "scheduled": len(m), "acked": len(ok), "errors": dict(sorted(Counter(s.error for s in m if s.error).items())),
        "offered_msgs_s": len(m) / duration_s, "achieved_msgs_s": len(ok) / duration_s,
        "ack_ms": percentiles([s.ack_ms for s in ok if s.ack_ms is not None]),
        "readable_ms": percentiles([s.readable_ms for s in seen if s.readable_ms is not None]),
        "readable_missing": len(ok) - len(seen),
        # how late the generator itself was; a large value means the client, not the service, was the limit
        "send_lag_ms": percentiles(lag),
        "excluded_warmup": sum(s.t_sched < warmup_s for s in samples),
        "excluded_after": sum(s.t_sched >= warmup_s + duration_s for s in samples),
    }


# ---------------------------------------------------------------- the cells of S2

MODES = ("baseline", "vcloak")


def conv_tokens(rng: np.random.Generator, conversations: int) -> list[str]:
    """One conv_token per conversation, in the form a client derives (docs/API.md): 24 random bytes, base64url."""
    return [base64.urlsafe_b64encode(rng.bytes(24)).decode() for _ in range(conversations)]


def cell_order(users: list[int], reps: int, modes: tuple[str, ...] = MODES) -> list[tuple[int, int, str]]:
    """(repetition, users, mode) in the order the cells run: the modes of one user count back to back, so the
    two sides of a comparison see the same state of the machine (A1); a repetition is a full pass."""
    if reps < 1 or not users or not modes:
        raise ValueError("at least one repetition, one user count and one mode")
    return [(rep, u, mode) for rep in range(1, reps + 1) for u in users for mode in modes]


def bucket_span_peaks(sends: list[Send], bucket_of_conv: list[int], window_s: float) -> dict[int, int]:
    """For every bucket that receives a send: the largest number of sends that fall into one span of `window_s`
    seconds. A window of the store is such a span whose start the wall clock fixes at run time, so this is an
    upper bound on the rows of any bucket-window of the run, for every alignment. Arithmetic on the schedule and
    the public layout: not a measurement."""
    times: dict[int, list[float]] = {}
    for s in sends:
        times.setdefault(int(bucket_of_conv[s.conv]), []).append(s.t)
    peaks = {}
    for bucket, ts in times.items():
        a = np.sort(np.asarray(ts, dtype=np.float64))
        peaks[bucket] = int((np.searchsorted(a, a + window_s, side="left") - np.arange(a.size)).max())
    return dict(sorted(peaks.items()))
