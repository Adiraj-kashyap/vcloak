"""M04: compile the real kernels/chacha_tags.cu and kernels/prf.cu with g++ and run them on the CPU (tests/cuda_shim).

The laptop has no nvcc, so without this the CUDA source is first compiled on the runner. The outputs
must equal the M02 reference and the NumPy twins byte for byte. It checks the logic of the C++ source,
not the code nvcc generates: the GPU job remains the acceptance gate. Windows fibers only, so it is
skipped elsewhere. The key files it writes hold TEST keys, under pytest's temporary directory.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from test_chacha import BUCKETS, CONV_KINDS, EDGE_KEYS, GOLDEN, KEYS, SEEDS, assert_same, conv_ids, words

from testkeys import TEST_K_MASTER
from vcloak.crypto import chacha_ref
from vcloak.gpu import kernels, sim
from vcloak.gpu.kernels import CHACHA_BLOCK, DOMAIN_EPOCH, DOMAIN_RESHUFFLE, KERNEL_DIR

SHIM_DIR = Path(__file__).resolve().parent.parent / "cuda_shim"
GXX = shutil.which("g++")

pytestmark = pytest.mark.skipif(sys.platform != "win32" or GXX is None,
                                reason="needs Windows fibers and g++ (the stand-in for nvcc on the laptop)")


@pytest.fixture(scope="module")
def host(tmp_path_factory: pytest.TempPathFactory) -> Path:
    exe = tmp_path_factory.mktemp("cuda_shim") / "chacha_host.exe"
    p = subprocess.run([str(GXX), "-std=c++14", "-O1", "-Wall", "-I", str(SHIM_DIR), "-I", str(KERNEL_DIR),
                        str(SHIM_DIR / "chacha_host.cpp"), "-o", str(exe)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return exe


def launch(nthreads: int) -> tuple[int, int]:
    """(grid, block) as vcloak.gpu.kernels._run_threads chooses them."""
    block = min(CHACHA_BLOCK, nthreads)
    return -(-nthreads // block), block


def run_host(host: Path, tmp: Path, mode: str, data: bytes, *args: int) -> bytes:
    (tmp / "in.bin").write_bytes(data)
    r = subprocess.run([str(host), mode, str(tmp / "in.bin"), str(tmp / "out.bin"), *map(str, args)])
    assert r.returncode == 0, f"chacha_host {mode} exit {r.returncode}"
    return (tmp / "out.bin").read_bytes()


def cu_tags(host: Path, tmp: Path, key: bytes, nonce64: int, domain: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    raw = run_host(host, tmp, "tags", key, nonce64, domain, n // 4, *launch(n // 4))
    assert len(raw) == 16 * n
    return np.frombuffer(raw, np.uint64, n, 0), np.frombuffer(raw, np.uint64, n, 8 * n)


def test_cu_block_is_rfc8439_2_3_2(host: Path, tmp_path: Path) -> None:
    for v in json.loads((GOLDEN / "rfc8439_block.json").read_text(encoding="ascii"))["vectors"]:
        raw = run_host(host, tmp_path, "blocks", bytes.fromhex(v["key"]) + bytes.fromhex(v["nonce"]),
                       v["counter"], 1, 1, 1)
        assert raw == bytes.fromhex(v["block"])


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize(("counter0", "nblocks"), [(0, 257), ((1 << 32) - 3, 3), (1 << 31, 300)])
def test_cu_blocks_equal_reference(host: Path, tmp_path: Path, seed: int, counter0: int, nblocks: int) -> None:
    key, nonce = KEYS[seed], hashlib.sha256(b"vcloak-test-nonce-%d" % seed).digest()[:12]
    raw = run_host(host, tmp_path, "blocks", key + nonce, counter0, nblocks, *launch(nblocks))
    assert raw == chacha_ref.block(key, nonce, counter0, nblocks).tobytes()


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize(("n", "epoch"), [(64, 0), (1020, 1), (1 << 10, 1 << 32), (1 << 16, (1 << 64) - 1)])
def test_cu_tags_equal_reference_and_twin(host: Path, tmp_path: Path, n: int, epoch: int, seed: int) -> None:
    key = KEYS[seed]
    for domain, ref in ((DOMAIN_EPOCH, chacha_ref.tags_for_epoch), (DOMAIN_RESHUFFLE, chacha_ref.reshuffle_tags)):
        got = cu_tags(host, tmp_path, key, epoch, domain, n)
        twin = np.zeros(n, dtype=np.uint64), np.zeros(n, dtype=np.uint64)
        kernels.gpu_tags(words(key), epoch, domain, *twin)
        for g, w, t, col in zip(got, ref(key, epoch, n), twin, ("hi", "lo"), strict=True):
            assert_same(g, w, f"shim vs reference n={n} epoch={epoch} domain={domain:#x} {col}")
            assert_same(g, t, f"shim vs twin n={n} epoch={epoch} domain={domain:#x} {col}")


@pytest.mark.parametrize("name", sorted(EDGE_KEYS))
def test_cu_tags_edge_keys(host: Path, tmp_path: Path, name: str) -> None:
    key = EDGE_KEYS[name]
    for g, w in zip(cu_tags(host, tmp_path, key, 3, DOMAIN_EPOCH, 256), chacha_ref.tags_for_epoch(key, 3, 256),
                    strict=True):
        assert_same(g, w, f"shim {name}")


@pytest.mark.parametrize("master", [TEST_K_MASTER, *KEYS.values(), bytes(32), b"\xff" * 32])
def test_cu_subkeys_equal_reference(host: Path, tmp_path: Path, master: bytes) -> None:
    assert run_host(host, tmp_path, "subkeys", master, *launch(sim.N_SUBKEYS)) == b"".join(
        chacha_ref.derive_subkeys(master))
    assert run_host(host, tmp_path, "subkeys", master, 2, 4) == b"".join(chacha_ref.derive_subkeys(master))  # guard


@pytest.mark.parametrize("kind", CONV_KINDS)
@pytest.mark.parametrize(("n", "seed"), [(64, 1), (1 << 10, 2), (5000, 3), (1 << 16, 1)])
def test_cu_bucket_equals_reference_and_twin(host: Path, tmp_path: Path, n: int, seed: int, kind: str) -> None:
    key, ids = KEYS[seed], conv_ids(kind, n, seed)
    for b in (BUCKETS[(seed + n.bit_length()) % len(BUCKETS)], 1000, (1 << 32) - 1):
        got = np.frombuffer(run_host(host, tmp_path, "bucket", key + ids.tobytes(), n, b, *launch(n)), np.uint32)
        assert_same(got, chacha_ref.bucket_prf(key, ids, b), f"shim vs reference n={n} {kind} B={b}")
        assert_same(got, kernels.gpu_bucket_prf(words(key), ids, b), f"shim vs twin n={n} {kind} B={b}")


@pytest.mark.parametrize("n_buckets", [*BUCKETS, 5, 641, 6700417, (1 << 32) - 5, (1 << 31) + 1])
def test_cu_mod_public_is_exact_at_the_edges(host: Path, tmp_path: Path, n_buckets: int) -> None:
    b = n_buckets
    edge = {0, 1, b - 1, b, b + 1, 2 * b - 1, 2 * b, 3 * b, (1 << 32) - 1, (1 << 32) - 2, 1 << 31,
            ((1 << 32) - 1) // b * b, ((1 << 32) - 1) // b * b - 1}
    w = np.array(sorted(v for v in edge if 0 <= v < 1 << 32), dtype=np.uint32)
    w = np.concatenate([w, np.random.default_rng(b).integers(0, 2**32, 4096, dtype=np.uint32)])
    got = np.frombuffer(run_host(host, tmp_path, "mod", w.tobytes(), w.shape[0], b), np.uint32)
    assert_same(got, (w.astype(np.uint64) % np.uint64(b)).astype(np.uint32), f"mod_public B={b}")
    assert_same(got, sim._mod_public(w, b), f"mod_public vs twin B={b}")
