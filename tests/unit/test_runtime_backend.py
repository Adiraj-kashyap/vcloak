import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from vcloak.gpu import runtime, sim, telemetry
from vcloak.gpu.runtime import NoGpuError, get_backend

SRC = str(Path(__file__).resolve().parents[2] / "src")
HAS_GPU = get_backend("auto").is_gpu
no_gpu_only = pytest.mark.skipif(HAS_GPU, reason="this machine has a CUDA device")


def test_numpy_backend_explicit():
    b = get_backend("numpy")
    assert (b.name, b.is_gpu) == ("numpy", False)
    assert b.xp is np


def test_backend_from_env(monkeypatch):
    monkeypatch.setenv(runtime.ENV_VAR, "NumPy ")
    assert get_backend().name == "numpy"


def test_invalid_backend_name(monkeypatch):
    monkeypatch.setenv(runtime.ENV_VAR, "opencl")
    with pytest.raises(ValueError, match="VCLOAK_BACKEND"):
        get_backend()


@no_gpu_only
def test_auto_falls_back_to_numpy(monkeypatch):
    monkeypatch.delenv(runtime.ENV_VAR, raising=False)
    assert get_backend().name == "numpy"


@no_gpu_only
def test_cupy_without_gpu_is_a_clear_error():
    with pytest.raises(NoGpuError) as e:
        get_backend("cupy")
    assert "runner" in str(e.value) and "gpujob.py pack" in str(e.value)


@no_gpu_only
def test_cupy_without_gpu_prints_no_traceback():
    env = dict(os.environ, VCLOAK_BACKEND="cupy", PYTHONPATH=SRC)
    p = subprocess.run([sys.executable, "-c", "from vcloak.gpu.runtime import get_backend; print(get_backend().name)"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 1
    assert "Traceback" not in p.stderr
    assert "Colab/Kaggle runner" in p.stderr


def test_host_device_info():
    info = get_backend("numpy").device_info()
    assert info["is_gpu"] is False and info["backend"] == "numpy"
    assert info["cpu"] and info["cpu_count"] >= 1


def test_sim_registry_roundtrip():
    @sim.register("_test_twin")
    def twin(x):
        return x + 1

    assert sim.get("_test_twin") is twin
    assert "_test_twin" in sim.names()
    with pytest.raises(ValueError, match="already registered"):
        sim.register("_test_twin")(lambda x: x)
    with pytest.raises(KeyError, match="no simulator twin"):
        sim.get("_missing")


def test_vector_add_twin_wraps_like_uint32():
    a = np.array([1, 2**32 - 1, 7], dtype=np.uint32)
    b = np.array([2, 2, 0], dtype=np.uint32)
    out = np.zeros(3, dtype=np.uint32)
    sim.get("vector_add")(a, b, out, 2)
    assert out.tolist() == [3, 1, 0]  # element 2 is beyond n: untouched


@no_gpu_only
def test_telemetry_is_a_noop_without_nvml(tmp_path):
    snap = telemetry.snapshot()
    assert snap["available"] is False and "reason" in snap
    with telemetry.Sampler(tmp_path / "telemetry.csv") as s:
        pass
    assert s.stop() == {"available": False, "samples": 0, "file": None}
    assert not (tmp_path / "telemetry.csv").exists()


@pytest.mark.gpu
def test_gpu_device_info(backend):
    info = backend.device_info()
    assert info["is_gpu"] and info["vram_free_bytes"] > 0 and 0 < info["max_log2n"] <= 24
