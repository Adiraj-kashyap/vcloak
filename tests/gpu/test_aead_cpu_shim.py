"""M05: compile the real kernels/poly1305.cu, aead_open.cu and aead_seal.cu with g++ and run them on the CPU
(tests/cuda_shim).

The laptop has no nvcc, so without this the CUDA source is first compiled on the runner. The outputs
must equal the references and the NumPy twins byte for byte. It checks the logic of the C++ source,
not the code nvcc generates: the GPU job remains the acceptance gate. Windows fibers only, so it is
skipped elsewhere. The key files it writes hold TEST keys, under pytest's temporary directory.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives.poly1305 import Poly1305
from test_aead import LENGTHS, mixed_rows, rand_bytes, ref_open_columns, ref_seal
from test_chacha import CONV_KINDS, EDGE_KEYS, GOLDEN, KEYS, assert_same, conv_ids, words

from vcloak.crypto import aead_ref
from vcloak.gpu import kernels
from vcloak.gpu.kernels import CHACHA_BLOCK, KERNEL_DIR, SEQ_ENC_LEN, pack_seq_enc

SHIM_DIR = Path(__file__).resolve().parent.parent / "cuda_shim"
GXX = shutil.which("g++")

pytestmark = pytest.mark.skipif(sys.platform != "win32" or GXX is None,
                                reason="needs Windows fibers and g++ (the stand-in for nvcc on the laptop)")


@pytest.fixture(scope="module")
def host(tmp_path_factory: pytest.TempPathFactory) -> Path:
    exe = tmp_path_factory.mktemp("cuda_shim") / "aead_host.exe"
    p = subprocess.run([str(GXX), "-std=c++14", "-O1", "-Wall", "-I", str(SHIM_DIR), "-I", str(KERNEL_DIR),
                        str(SHIM_DIR / "aead_host.cpp"), "-o", str(exe)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert "warning" not in p.stderr, p.stderr
    return exe


def launch(nthreads: int) -> tuple[int, int]:
    """(grid, block) as vcloak.gpu.kernels._run_threads chooses them."""
    block = min(CHACHA_BLOCK, nthreads)
    return -(-nthreads // block), block


def run_host(host: Path, tmp: Path, mode: str, data: bytes, *args: int) -> bytes:
    (tmp / "in.bin").write_bytes(data)
    r = subprocess.run([str(host), mode, str(tmp / "in.bin"), str(tmp / "out.bin"), *map(str, args)])
    assert r.returncode == 0, f"aead_host {mode} exit {r.returncode}"
    return (tmp / "out.bin").read_bytes()


def cu_open(host: Path, tmp: Path, key: bytes, rows: list[bytes], q_conv: int) -> tuple[np.ndarray, ...]:
    n = len(rows)
    raw = run_host(host, tmp, "open", key + b"".join(rows), n, q_conv, *launch(n))
    assert len(raw) == 20 * n
    return (np.frombuffer(raw, np.uint64, n, 0), np.frombuffer(raw, np.uint64, n, 8 * n),
            np.frombuffer(raw, np.uint32, n, 16 * n))


def test_cu_poly1305_is_rfc8439_2_5_2(host: Path, tmp_path: Path) -> None:
    for v in json.loads((GOLDEN / "rfc8439_poly1305.json").read_text(encoding="ascii"))["vectors"]:
        msg = v["message_ascii"].encode("ascii")
        assert run_host(host, tmp_path, "poly", bytes.fromhex(v["key"]) + msg, len(msg), 1, 1, 1) == bytes.fromhex(
            v["tag"])


def test_cu_aead_tag_is_rfc8439_2_8_2(host: Path, tmp_path: Path) -> None:
    for v in json.loads((GOLDEN / "rfc8439_aead.json").read_text(encoding="ascii"))["vectors"]:
        aad, ct = bytes.fromhex(v["aad"]), bytes.fromhex(v["ciphertext"])
        raw = run_host(host, tmp_path, "tag", bytes.fromhex(v["key"]) + bytes.fromhex(v["nonce"]) + aad + ct,
                       len(aad), len(ct), 1, 1, 1)
        assert raw == bytes.fromhex(v["tag"])


@pytest.mark.parametrize("nbytes", LENGTHS)
def test_cu_poly1305_equals_reference_and_twin(host: Path, tmp_path: Path, nbytes: int) -> None:
    n, seed = 300, 1 + nbytes % 3
    keys, msgs = rand_bytes(seed, "otk", 32 * n), rand_bytes(seed, "msg", nbytes * n)
    got = run_host(host, tmp_path, "poly", keys + msgs, nbytes, n, *launch(n))
    assert got == b"".join(Poly1305.generate_tag(keys[32 * t:32 * t + 32], msgs[nbytes * t:nbytes * (t + 1)])
                           for t in range(n))
    twin = kernels.gpu_poly1305(words(keys), np.frombuffer(msgs, np.uint8), nbytes)
    assert got == twin.astype("<u4").tobytes()


@pytest.mark.parametrize(("aad_len", "box_len"), [(0, 0), (13, 16), (12, 114), (16, 32), (1, 1), (17, 15), (40, 65)])
def test_cu_aead_tag_equals_reference(host: Path, tmp_path: Path, aad_len: int, box_len: int) -> None:
    n, key = 70, KEYS[2]
    nonces, aad = rand_bytes(2, "nonce", 12 * n), rand_bytes(2, "aad", aad_len)
    pts = rand_bytes(2, "pt", box_len * n)
    boxed = [aead_ref.aead_seal(key, nonces[12 * i:12 * i + 12], pts[box_len * i:box_len * (i + 1)], aad)
             for i in range(n)]
    raw = run_host(host, tmp_path, "tag", key + nonces + aad + b"".join(b[:box_len] for b in boxed),
                   aad_len, box_len, n, *launch(n))
    assert raw == b"".join(b[box_len:] for b in boxed)


@pytest.mark.parametrize("kind", CONV_KINDS)
@pytest.mark.parametrize(("n", "seed"), [(64, 1), (1 << 10, 2), (5000, 3), (1 << 16, 1)])
def test_cu_seal_equals_reference_and_twin(host: Path, tmp_path: Path, n: int, seed: int, kind: str) -> None:
    key = KEYS[seed]
    conv, seq, nonces = conv_ids(kind, n, seed), conv_ids("random", n, seed + 10), rand_bytes(seed, "nonce", 12 * n)
    raw = run_host(host, tmp_path, "seal", key + conv.tobytes() + seq.tobytes() + nonces, n, *launch(n))
    assert [raw[i:i + SEQ_ENC_LEN] for i in range(0, len(raw), SEQ_ENC_LEN)] == ref_seal(key, conv, seq, nonces)
    twin = kernels.gpu_seal_seq(words(key), conv, seq, words(nonces))
    assert raw == twin.astype("<u4").tobytes()


@pytest.mark.parametrize(("n", "seed"), [(64, 1), (1 << 10, 2), (5000, 3), (1 << 16, 1)])
def test_cu_open_equals_reference_and_twin(host: Path, tmp_path: Path, n: int, seed: int) -> None:
    key, q_conv = KEYS[seed], (0, 2**64 - 1, 0x0123456789ABCDEF)[seed - 1]
    rows = mixed_rows(key, n, seed, q_conv)
    for q in (q_conv, (q_conv + 1) % (1 << 64)):
        got = cu_open(host, tmp_path, key, rows, q)
        twin = kernels.gpu_open_and_key(words(key), pack_seq_enc(rows), q)
        for g, w, t, col in zip(got, ref_open_columns(key, rows, q), twin, ("hi", "lo", "ok"), strict=True):
            assert_same(g, w, f"shim vs reference n={n} q={q} {col}")
            assert_same(g, t, f"shim vs twin n={n} q={q} {col}")


@pytest.mark.parametrize("name", sorted(EDGE_KEYS))
def test_cu_every_single_bit_flip_is_a_miss(host: Path, tmp_path: Path, name: str) -> None:
    key, seq = EDGE_KEYS[name], 2**64 - 1
    blob = aead_ref.seal_seq(key, 7, seq, bytes(range(12)))
    rows = [blob]
    for bit in range(8 * SEQ_ENC_LEN):
        b = bytearray(blob)
        b[bit // 8] ^= 1 << (bit % 8)
        rows.append(bytes(b))
    hi, lo, ok = cu_open(host, tmp_path, key, rows, 7)
    assert (int(hi[0]), int(lo[0]), int(ok[0])) == (0, seq, 1)
    assert not ok[1:].any() and (hi[1:] == 1).all() and not lo[1:].any()
