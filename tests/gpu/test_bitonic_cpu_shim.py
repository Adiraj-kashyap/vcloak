"""M03: compile the real kernels/bitonic.cu with g++ and run it on the CPU (tests/cuda_shim).

The laptop has no nvcc, so without this the CUDA source is first compiled on the runner. The shim
gives each kernel thread a fiber and makes __syncthreads() a real barrier; the outputs must equal the
NumPy twins byte for byte. It checks the logic of the C++ source, not the code nvcc generates: the
GPU job remains the acceptance gate. Windows fibers only, so it is skipped elsewhere.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from test_bitonic import CASES, assert_bytes_equal, make_cols

from vcloak.gpu.kernels import DEFAULT_T, KERNEL_DIR, global_only_plan, gpu_bitonic_sort, launch_plan, run_launch

SHIM_DIR = Path(__file__).resolve().parent.parent / "cuda_shim"
GXX = shutil.which("g++")

pytestmark = pytest.mark.skipif(sys.platform != "win32" or GXX is None,
                                reason="needs Windows fibers and g++ (the stand-in for nvcc on the laptop)")


@pytest.fixture(scope="module")
def host(tmp_path_factory: pytest.TempPathFactory) -> Path:
    exe = tmp_path_factory.mktemp("cuda_shim") / "bitonic_host.exe"
    p = subprocess.run([str(GXX), "-std=c++14", "-O1", "-Wall", "-I", str(SHIM_DIR), "-I", str(KERNEL_DIR),
                        str(SHIM_DIR / "bitonic_host.cpp"), "-o", str(exe)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return exe


def run_on_cpu(host: Path, tmp: Path, cols: tuple[np.ndarray, ...], plan: tuple) -> tuple[np.ndarray, ...]:
    n = cols[0].shape[0]
    (tmp / "in.bin").write_bytes(b"".join(c.tobytes() for c in cols))
    (tmp / "plan.txt").write_text(
        "".join(f"{p.kernel} {p.grid} {p.block} {p.k} {p.j}\n" for p in plan), encoding="ascii")
    r = subprocess.run([str(host), str(tmp / "in.bin"), str(tmp / "out.bin"), str(n), str(tmp / "plan.txt")])
    assert r.returncode == 0, f"bitonic_host exit {r.returncode}"
    raw = (tmp / "out.bin").read_bytes()
    assert len(raw) == 24 * n
    return (np.frombuffer(raw, np.uint64, n, 0), np.frombuffer(raw, np.uint64, n, 8 * n),
            np.frombuffer(raw, np.uint32, n, 16 * n), np.frombuffer(raw, np.uint32, n, 20 * n))


@pytest.mark.parametrize(("kind", "seed"), CASES)
@pytest.mark.parametrize(("n", "T"), [(2, 1), (64, DEFAULT_T), (256, 8), (1 << 10, DEFAULT_T), (1 << 12, DEFAULT_T)])
def test_cu_source_equals_twin(host: Path, tmp_path: Path, n: int, T: int, kind: str, seed: int) -> None:  # noqa: N803
    cols = make_cols(kind, n, seed)
    twin = tuple(c.copy() for c in cols)
    gpu_bitonic_sort(*twin, T=T)
    assert_bytes_equal(run_on_cpu(host, tmp_path, cols, launch_plan(n, T)), twin, f"shim n={n} T={T} {kind}")


def test_cu_global_kernel_alone_equals_twin(host: Path, tmp_path: Path) -> None:
    cols = make_cols("random", 1 << 10, 3)
    twin = tuple(c.copy() for c in cols)
    for launch in global_only_plan(1 << 10):
        run_launch(twin, launch)
    assert_bytes_equal(run_on_cpu(host, tmp_path, cols, global_only_plan(1 << 10)), twin, "shim global only")


def test_cu_partial_plan_equals_twin(host: Path, tmp_path: Path) -> None:
    """The tile-local sort alone, then further launches: intermediate states, not only the sorted result."""
    cols = make_cols("random", 1 << 12, 2)
    for upto in (1, 3, 6):
        plan = launch_plan(1 << 12)[:upto]
        twin = tuple(c.copy() for c in cols)
        for launch in plan:
            run_launch(twin, launch)
        assert_bytes_equal(run_on_cpu(host, tmp_path, cols, plan), twin, f"shim first {upto} launches")
