"""NVML telemetry (ai/GPU_GUIDE.md §6): a snapshot and a 10 Hz background sampler.

Without NVML (the laptop) every call is a no-op that records `available: false`, so local runs
still produce a complete manifest.
"""
from __future__ import annotations

import csv
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

FIELDS = ("ts", "sm_clock_mhz", "mem_clock_mhz", "temperature_c", "power_w", "power_limit_w",
          "util_gpu_pct", "util_mem_pct", "throttle_reasons", "pstate", "mem_used_mb")


def _nvml() -> Any | None:
    try:
        import pynvml  # type: ignore[import-not-found]

        pynvml.nvmlInit()
        return pynvml
    except Exception:  # noqa: BLE001 - absent library, absent driver, or no device
        return None


def _try(fn: Any, *args: Any) -> Any:
    """One NVML query; None when this device or driver does not support it."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        return None


def _text(v: Any) -> Any:
    return v.decode() if isinstance(v, bytes) else v


def _sample(nv: Any, h: Any) -> dict[str, Any]:
    util = _try(nv.nvmlDeviceGetUtilizationRates, h)
    mem = _try(nv.nvmlDeviceGetMemoryInfo, h)
    power = _try(nv.nvmlDeviceGetPowerUsage, h)
    limit = _try(nv.nvmlDeviceGetEnforcedPowerLimit, h)
    return {
        "ts": time.time(),
        "sm_clock_mhz": _try(nv.nvmlDeviceGetClockInfo, h, nv.NVML_CLOCK_SM),
        "mem_clock_mhz": _try(nv.nvmlDeviceGetClockInfo, h, nv.NVML_CLOCK_MEM),
        "temperature_c": _try(nv.nvmlDeviceGetTemperature, h, nv.NVML_TEMPERATURE_GPU),
        "power_w": None if power is None else power / 1000.0,
        "power_limit_w": None if limit is None else limit / 1000.0,
        "util_gpu_pct": None if util is None else util.gpu,
        "util_mem_pct": None if util is None else util.memory,
        "throttle_reasons": _try(nv.nvmlDeviceGetCurrentClocksThrottleReasons, h),
        "pstate": _try(nv.nvmlDeviceGetPerformanceState, h),
        "mem_used_mb": None if mem is None else mem.used / 2**20,
    }


def _clock_lock() -> str:
    """Report whether the SM clock is locked. We never try to lock it on a shared runner."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=clocks.sm", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=20)
        return "unlocked" if out.returncode == 0 else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def snapshot(index: int = 0) -> dict[str, Any]:
    """One telemetry reading for a manifest's `telemetry_start` / `telemetry_end`."""
    nv = _nvml()
    if nv is None:
        return {"available": False, "reason": "NVML not available (no NVIDIA GPU or pynvml missing)",
                "ts": time.time()}
    try:
        h = nv.nvmlDeviceGetHandleByIndex(index)
        snap: dict[str, Any] = {"available": True,
                                "gpu": _text(_try(nv.nvmlDeviceGetName, h)),
                                "driver": _text(_try(nv.nvmlSystemGetDriverVersion)),
                                "clocks": _clock_lock(),
                                "sm_clock_max_mhz": _try(nv.nvmlDeviceGetMaxClockInfo, h, nv.NVML_CLOCK_SM)}
        snap.update(_sample(nv, h))
        return snap
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": f"NVML error: {type(e).__name__}", "ts": time.time()}


def sample(index: int = 0) -> dict[str, Any]:
    """A cheap reading for use between timed runs: the sampler fields plus the maximum SM clock, with no
    subprocess (unlike `snapshot`), so the device is not left idle while it is taken."""
    nv = _nvml()
    if nv is None:
        return {"available": False, "ts": time.time()}
    h = _try(nv.nvmlDeviceGetHandleByIndex, index)
    if h is None:
        return {"available": False, "ts": time.time()}
    out: dict[str, Any] = {"available": True, **_sample(nv, h)}
    out["sm_clock_max_mhz"] = _try(nv.nvmlDeviceGetMaxClockInfo, h, nv.NVML_CLOCK_SM)
    return out


class Sampler:
    """Background sampler writing `telemetry.csv`. Use as a context manager around a long run."""

    def __init__(self, path: str | Path, hz: float = 10.0, index: int = 0) -> None:
        self.path = Path(path)
        self.period = 1.0 / hz
        self.index = index
        self.available = False
        self.samples = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self, nv: Any, h: Any) -> None:
        with self.path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            while not self._stop.is_set():
                w.writerow(_sample(nv, h))
                self.samples += 1
                self._stop.wait(self.period)

    def start(self) -> Sampler:
        nv = _nvml()
        if nv is None:
            return self
        h = _try(nv.nvmlDeviceGetHandleByIndex, self.index)
        if h is None:
            return self
        self.available = True
        self._thread = threading.Thread(target=self._loop, args=(nv, h), daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return {"available": self.available, "samples": self.samples,
                "file": self.path.name if self.available else None}

    def __enter__(self) -> Sampler:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
