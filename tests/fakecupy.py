"""A stand-in for the small part of the cupy API that the benchmark drivers use, built on NumPy.

It exists so that the GPU-only code paths of bench/*.py (event timing loops, pinned transfers, CSV and
summary writing, the crossover) run on the laptop before a job is shipped to the runner. "Device"
arrays are NumPy arrays, so kernels run on the simulator twins and events read the host clock.
Whatever it times is meaningless: tests write to tmp_path and nothing produced with it is a result.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import numpy as np

from vcloak.gpu.runtime import Backend

SM_CLOCK_MAX = 1590


class Dev(np.ndarray):
    """A NumPy array with the two transfer methods of cupy.ndarray."""

    def set(self, host: np.ndarray, stream: Any = None) -> None:  # noqa: A003, ARG002
        self[...] = host

    def get(self, stream: Any = None, out: np.ndarray | None = None) -> np.ndarray:  # noqa: ARG002
        if out is None:
            return np.array(self)
        out[...] = self
        return out


class _Event:
    def __init__(self) -> None:
        self.t = 0.0

    def record(self, stream: Any = None) -> None:  # noqa: ARG002
        self.t = time.perf_counter()

    def synchronize(self) -> None:
        pass


def _dev(a: Any) -> Dev:
    return np.ascontiguousarray(a).view(Dev)


class _Stream:
    def __init__(self, non_blocking: bool = False) -> None:  # noqa: ARG002
        pass

    def synchronize(self) -> None:
        pass

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


def module() -> SimpleNamespace:
    stream = _Stream()
    props = {"name": b"Fake GPU (numpy)", "major": 0, "minor": 0, "multiProcessorCount": 1,
             "memoryClockRate": 1_000_000, "memoryBusWidth": 64}
    cuda = SimpleNamespace(
        Event=_Event, Stream=_Stream, get_current_stream=lambda: stream,
        get_elapsed_time=lambda a, b: (b.t - a.t) * 1e3,
        alloc_pinned_memory=lambda nbytes: bytearray(nbytes),
        Device=lambda: SimpleNamespace(id=0),
        runtime=SimpleNamespace(getDeviceProperties=lambda i: props, memGetInfo=lambda: (2**30, 2**30),
                                runtimeGetVersion=lambda: 0))
    return SimpleNamespace(
        cuda=cuda, __version__="fake",
        asarray=lambda a, dtype=None: _dev(np.array(a, dtype=dtype)),
        empty=lambda n, dtype=float: _dev(np.empty(n, dtype=dtype)),
        empty_like=lambda a: _dev(np.empty_like(a)),
        copyto=np.copyto, asnumpy=lambda a: np.asarray(a).view(np.ndarray), array_equal=np.array_equal,
        get_default_memory_pool=lambda: SimpleNamespace(free_all_blocks=lambda: None))


def backend() -> Backend:
    return Backend(name="cupy", is_gpu=True, xp=module())  # type: ignore[arg-type]


def clock_sample(mhz: int = SM_CLOCK_MAX) -> dict[str, Any]:
    """What `telemetry.sample` returns on a device running at `mhz`."""
    return {"available": True, "ts": time.time(), "sm_clock_mhz": mhz, "sm_clock_max_mhz": SM_CLOCK_MAX,
            "power_w": 30.0}
