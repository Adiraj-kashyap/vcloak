"""Backend selection (ai/GPU_RUNNER.md §3).

`VCLOAK_BACKEND` = `auto` (default) | `cupy` | `numpy`.
  cupy  - the real GPU path; only works on the Colab/Kaggle runner.
  numpy - the thread-model simulator: same kernel semantics, correctness only, never a performance result.
  auto  - cupy if a CUDA device is present, else numpy.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from vcloak import config

ENV_VAR = "VCLOAK_BACKEND"

NO_GPU_HELP = (
    "V-cloak: VCLOAK_BACKEND=cupy was requested, but this machine has no usable CUDA GPU ({reason}).\n"
    "The laptop has no GPU: CUDA work runs on the free Colab/Kaggle runner.\n"
    "  - for local correctness work use VCLOAK_BACKEND=numpy (or leave it unset)\n"
    "  - for real GPU numbers run: python scripts/gpujob.py pack <Mxx>   (see ai/GPU_RUNNER.md)"
)


class NoGpuError(SystemExit):
    """cupy was requested explicitly and no CUDA device is available.

    Subclasses SystemExit so that a command-line use ends with the help text and exit status 1
    instead of a traceback. Library callers can still catch it by name.
    """


@dataclass(frozen=True)
class Backend:
    """The selected array backend. `xp` is the `numpy` or `cupy` module."""

    name: str
    is_gpu: bool
    xp: ModuleType

    def device_info(self) -> dict[str, Any]:
        """Describe the device that executes kernels: the GPU on cupy, the host CPU on numpy."""
        return _gpu_info(self.xp) if self.is_gpu else _host_info()


def _try_cupy() -> tuple[ModuleType | None, str]:
    """Return (cupy, "") if a CUDA device is usable, else (None, reason)."""
    try:
        import cupy  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001 - ImportError, or a broken CUDA install raising anything
        return None, f"CuPy is not installed ({type(e).__name__})"
    try:
        if cupy.cuda.runtime.getDeviceCount() < 1:
            return None, "CuPy found no CUDA device"
    except Exception as e:  # noqa: BLE001
        return None, f"CUDA is not available ({type(e).__name__})"
    return cupy, ""


def get_backend(name: str | None = None) -> Backend:
    """Select the backend from `name`, or from the VCLOAK_BACKEND environment variable."""
    choice = (name or os.environ.get(ENV_VAR) or "auto").strip().lower()
    if choice not in config.BACKENDS:
        raise ValueError(f"{ENV_VAR} must be one of {config.BACKENDS}, got {choice!r}")
    if choice in ("auto", "cupy"):
        cupy, reason = _try_cupy()
        if cupy is not None:
            return Backend(name="cupy", is_gpu=True, xp=cupy)
        if choice == "cupy":
            raise NoGpuError(NO_GPU_HELP.format(reason=reason))
    import numpy

    return Backend(name="numpy", is_gpu=False, xp=numpy)


def runner_name() -> str:
    """Where this process runs: `colab`, `kaggle` or `local` (VCLOAK_RUNNER overrides, as in colab/gpu_entry.py)."""
    if os.environ.get("VCLOAK_RUNNER"):
        return os.environ["VCLOAK_RUNNER"]
    if "COLAB_GPU" in os.environ or "COLAB_RELEASE_TAG" in os.environ:
        return "colab"
    if os.environ.get("KAGGLE_KERNEL_RUN_TYPE"):
        return "kaggle"
    return "local"


# ── device descriptions ──────────────────────────────────────────────────────


def _cpu_name() -> str:
    try:
        if sys.platform == "win32":
            import winreg

            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True)
            return out.stdout.strip() or platform.processor()
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:  # noqa: BLE001 - a probe must never break the run
        pass
    return platform.processor() or "unknown"


def _ram_gb() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                    (n, ctypes.c_ulonglong)
                    for n in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                              "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")
                ]

            st = _MemStatus()
            st.dwLength = ctypes.sizeof(st)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return round(st.ullTotalPhys / 2**30, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except Exception:  # noqa: BLE001
        return None


def _host_info() -> dict[str, Any]:
    return {
        "backend": "numpy",
        "is_gpu": False,
        "device": _cpu_name(),
        "cpu": _cpu_name(),
        "cpu_count": os.cpu_count(),
        "ram_gb": _ram_gb(),
        "os": platform.platform(),
        "python": platform.python_version(),
    }


def _gpu_info(cp: ModuleType) -> dict[str, Any]:
    """Device properties from the CUDA runtime. Missing attributes are reported as None, never guessed."""
    dev = cp.cuda.Device()
    props = cp.cuda.runtime.getDeviceProperties(dev.id)
    free, total = cp.cuda.runtime.memGetInfo()
    name = props.get("name", b"unknown")
    mem_clock_khz = props.get("memoryClockRate")
    bus_bits = props.get("memoryBusWidth")
    peak = None
    if mem_clock_khz and bus_bits:
        # peak = 2 x mem_clock x bus_width / 8 (ai/GPU_GUIDE.md §5), in GB/s
        peak = 2 * (mem_clock_khz * 1e3) * bus_bits / 8 / 1e9
    return {
        "backend": "cupy",
        "is_gpu": True,
        "device": name.decode() if isinstance(name, bytes) else str(name),
        "gpu": name.decode() if isinstance(name, bytes) else str(name),
        "cc": f'{props.get("major")}.{props.get("minor")}',
        "sm_count": props.get("multiProcessorCount"),
        "vram_total_bytes": int(total),
        "vram_free_bytes": int(free),
        "mem_clock_khz": mem_clock_khz,
        "mem_bus_width_bits": bus_bits,
        "peak_bw_gbs": peak,
        "max_log2n": config.max_log2n(int(free)),
        "cuda": str(cp.cuda.runtime.runtimeGetVersion()),
        "cupy": cp.__version__,
        "os": platform.platform(),
        "python": platform.python_version(),
    }


def host_info() -> dict[str, Any]:
    """The host CPU, whatever the backend: CPU baselines run beside the GPU on the runner."""
    info = _host_info()
    return {k: info[k] for k in ("cpu", "cpu_count", "ram_gb", "os", "python")}
