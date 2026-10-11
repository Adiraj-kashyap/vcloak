"""M04: the ChaCha20 kernels (tags, subkeys, bucket PRF) and their NumPy twins against M02 (ai/TESTING.md §2b, §3).

Every test with the `xp` fixture runs twice: on NumPy arrays (the simulator twins, on any machine) and
on CuPy arrays (the CUDA kernels, marked `gpu`, on the runner only). Equality is byte equality.
The reference is `vcloak.crypto.chacha_ref`, itself checked against RFC 8439 and `cryptography` in M02.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import check_oblivious as co
from testkeys import TEST_K_MASTER
from vcloak.crypto import chacha_ref
from vcloak.gpu import kernels, sim
from vcloak.gpu.kernels import (
    DOMAIN_EPOCH,
    DOMAIN_RESHUFFLE,
    SUBKEY_BKT,
    SUBKEY_SEQ,
    SUBKEY_TAG,
    gpu_bucket_prf,
    gpu_chacha_blocks,
    gpu_derive_subkeys,
    gpu_reshuffle_tags,
    gpu_tags,
    gpu_tags_for_epoch,
    subkey,
)
from vcloak.gpu.runtime import get_backend

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
SIZES = (1 << 6, 1 << 10, 1 << 16)  # ai/TESTING.md §3; 2^max_log2n is test_max_log2n
SEEDS = (1, 2, 3)
# fixed test keys, derived here and used nowhere else (CONVENTIONS §3)
KEYS = {seed: hashlib.sha256(b"vcloak-test-key-%d" % seed).digest() for seed in SEEDS}
EDGE_KEYS = {"zero": bytes(32), "ones": b"\xff" * 32, "master": TEST_K_MASTER}
EPOCHS = (0, 1, 1 << 32, (1 << 64) - 1)
BUCKETS = (1, 2, 3, 7, 256, 1000, 1 << 16, 1 << 31, (1 << 32) - 1)
CONV_KINDS = ("random", "all_equal", "sorted", "reverse", "two_value")


def words(b: bytes) -> np.ndarray:
    """Key or nonce bytes as little-endian uint32 words (the layout the kernels read)."""
    return np.frombuffer(b, dtype="<u4").astype(np.uint32)


def conv_ids(kind: str, n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng([seed, n])
    if kind == "random":
        return rng.integers(0, 2**64, n, dtype=np.uint64)
    if kind == "all_equal":
        return np.full(n, 2**64 - 1, dtype=np.uint64)
    if kind == "sorted":
        return np.arange(n, dtype=np.uint64)
    if kind == "reverse":
        return (np.uint64(2**64 - 1) - np.arange(n, dtype=np.uint64)).astype(np.uint64)
    if kind == "two_value":
        return rng.integers(0, 2, n, dtype=np.uint64) * np.uint64(2**63)
    raise ValueError(kind)


def to_host(a: Any) -> np.ndarray:
    return a if isinstance(a, np.ndarray) else a.get()


def assert_same(got: Any, want: np.ndarray, what: str) -> None:
    g = to_host(got)
    assert g.dtype == want.dtype, f"{what}: dtype {g.dtype} != {want.dtype}"
    assert g.shape == want.shape, f"{what}: shape {g.shape} != {want.shape}"
    assert g.tobytes() == want.tobytes(), f"{what}: {int(np.count_nonzero(g != want))} elements differ"


def assert_tags(got: tuple[Any, Any], want: tuple[np.ndarray, np.ndarray], what: str) -> None:
    assert_same(got[0], want[0], what + " hi")
    assert_same(got[1], want[1], what + " lo")


@pytest.fixture(params=["numpy", pytest.param("cupy", marks=pytest.mark.gpu)])
def xp(request: pytest.FixtureRequest) -> Any:
    """Array module: numpy runs the simulator twins, cupy the CUDA kernels."""
    return np if request.param == "numpy" else pytest.importorskip("cupy")


def dev(xp: Any, b: bytes) -> Any:
    """Upload a TEST key or nonce (tests may do this; production wrappers never take key bytes)."""
    return xp.asarray(words(b))


# ── S1: the block function (A1) ──────────────────────────────────────────────


def test_rfc8439_2_3_2_block_from_a_one_thread_kernel(xp: Any) -> None:
    doc = json.loads((GOLDEN / "rfc8439_block.json").read_text(encoding="ascii"))
    assert doc["source"].startswith("RFC 8439 section 2.3.2")
    for v in doc["vectors"]:
        out = gpu_chacha_blocks(dev(xp, bytes.fromhex(v["key"])), dev(xp, bytes.fromhex(v["nonce"])), v["counter"], 1)
        assert to_host(out).astype("<u4").tobytes() == bytes.fromhex(v["block"])


def test_rfc8439_2_4_2_keystream(xp: Any) -> None:
    doc = json.loads((GOLDEN / "rfc8439_keystream.json").read_text(encoding="ascii"))
    assert doc["source"].startswith("RFC 8439 section 2.4.2")
    for v in doc["vectors"]:
        pt, ct = v["plaintext_ascii"].encode("ascii"), bytes.fromhex(v["ciphertext"])
        nblocks = -(-len(pt) // 64)
        out = gpu_chacha_blocks(dev(xp, bytes.fromhex(v["key"])), dev(xp, bytes.fromhex(v["nonce"])),
                                v["counter"], nblocks)
        ks = to_host(out).astype("<u4").tobytes()[: len(pt)]
        assert bytes(a ^ b for a, b in zip(pt, ks, strict=True)) == ct


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize(("counter0", "nblocks"), [(0, 1), (0, 257), (7, 1024), ((1 << 32) - 3, 3), (1 << 31, 300)])
def test_blocks_equal_reference(xp: Any, seed: int, counter0: int, nblocks: int) -> None:
    key, nonce = KEYS[seed], hashlib.sha256(b"vcloak-test-nonce-%d" % seed).digest()[:12]
    out = gpu_chacha_blocks(dev(xp, key), dev(xp, nonce), counter0, nblocks)
    want = chacha_ref.block(key, nonce, counter0, nblocks).reshape(-1).view("<u4").astype(np.uint32)
    assert_same(out, want, f"blocks seed={seed} counter0={counter0} nblocks={nblocks}")


# ── S2: tags (A2) ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("epoch", EPOCHS)
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n", SIZES)
def test_tags_equal_reference(xp: Any, n: int, seed: int, epoch: int) -> None:
    key = KEYS[seed]
    assert_tags(gpu_tags_for_epoch(dev(xp, key), epoch, n), chacha_ref.tags_for_epoch(key, epoch, n),
                f"epoch tags n={n} seed={seed} epoch={epoch}")
    assert_tags(gpu_reshuffle_tags(dev(xp, key), epoch, n), chacha_ref.reshuffle_tags(key, epoch, n),
                f"re-shuffle tags n={n} seed={seed} win={epoch}")


@pytest.mark.parametrize("name", sorted(EDGE_KEYS))
@pytest.mark.parametrize("n", [4, 8, 12, 64, 1020, 1 << 10])
def test_tags_edge_keys_and_lengths(xp: Any, n: int, name: str) -> None:
    """All-zero and all-one keys, and slot counts that are not powers of two or fill a partial block of threads."""
    key = EDGE_KEYS[name]
    assert_tags(gpu_tags_for_epoch(dev(xp, key), 3, n), chacha_ref.tags_for_epoch(key, 3, n), f"{name} n={n}")
    assert_tags(gpu_reshuffle_tags(dev(xp, key), 3, n), chacha_ref.reshuffle_tags(key, 3, n), f"{name} n={n}")


def test_tags_fill_the_given_columns_in_place(xp: Any) -> None:
    key, n = KEYS[1], 1 << 10
    d_hi, d_lo = xp.zeros(n, dtype=np.uint64), xp.zeros(n, dtype=np.uint64)
    assert gpu_tags(dev(xp, key), 9, DOMAIN_EPOCH, d_hi, d_lo) is None
    assert_tags((d_hi, d_lo), chacha_ref.tags_for_epoch(key, 9, n), "in place")
    gpu_tags(dev(xp, key), 9, DOMAIN_RESHUFFLE, d_hi, d_lo)
    assert_tags((d_hi, d_lo), chacha_ref.reshuffle_tags(key, 9, n), "in place, re-shuffle")


def test_epoch_and_reshuffle_tags_are_domain_separated(xp: Any) -> None:
    """Same key and same number: the nonce suffix alone separates the two streams."""
    key = dev(xp, KEYS[2])
    e_hi, e_lo = (to_host(a) for a in gpu_tags_for_epoch(key, 5, 1 << 10))
    r_hi, r_lo = (to_host(a) for a in gpu_reshuffle_tags(key, 5, 1 << 10))
    assert not np.any((e_hi == r_hi) & (e_lo == r_lo))
    n_hi, n_lo = (to_host(a) for a in gpu_tags_for_epoch(key, 6, 1 << 10))
    assert not np.any((e_hi == n_hi) & (e_lo == n_lo))
    assert words(chacha_ref.EPOCH_SUFFIX)[0] == DOMAIN_EPOCH
    assert words(chacha_ref.RESHUFFLE_SUFFIX)[0] == DOMAIN_RESHUFFLE


# ── S3: subkeys and bucket PRF (A2) ──────────────────────────────────────────


@pytest.mark.parametrize("master", [TEST_K_MASTER, *KEYS.values(), bytes(32), b"\xff" * 32])
def test_subkeys_equal_reference(xp: Any, master: bytes) -> None:
    keys_dev = gpu_derive_subkeys(dev(xp, master))
    want = chacha_ref.derive_subkeys(master)
    for index, k in zip((SUBKEY_TAG, SUBKEY_SEQ, SUBKEY_BKT), want, strict=True):
        assert_same(subkey(keys_dev, index), words(k), f"subkey {index}")
    assert len({bytes(k) for k in want}) == 3


def test_label_words_are_the_reference_labels() -> None:
    labels = (chacha_ref.LABEL_TAG, chacha_ref.LABEL_SEQ, chacha_ref.LABEL_BKT)
    assert [tuple(int(w) for w in words(label)) for label in labels] == [tuple(row) for row in sim.LABEL_WORDS]
    src = (kernels.KERNEL_DIR / "prf.cu").read_text(encoding="utf-8")
    table = src[src.index("LABELS[3 * N_SUBKEYS] = {"):]
    table = table[table.index("{") + 1: table.index("}")]
    assert [int(tok.strip().rstrip("u"), 16) for tok in table.split(",")] == [w for row in sim.LABEL_WORDS for w in row]


@pytest.mark.parametrize("kind", CONV_KINDS)
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n", SIZES)
def test_bucket_equals_reference(xp: Any, n: int, seed: int, kind: str) -> None:
    key, ids = KEYS[seed], conv_ids(kind, n, seed)
    n_buckets = BUCKETS[(seed + n.bit_length()) % len(BUCKETS)]
    for b in (n_buckets, 1 << 10):
        assert_same(gpu_bucket_prf(dev(xp, key), xp.asarray(ids), b), chacha_ref.bucket_prf(key, ids, b),
                    f"bucket n={n} seed={seed} {kind} B={b}")


@pytest.mark.parametrize("n_buckets", BUCKETS)
def test_bucket_every_modulus(xp: Any, n_buckets: int) -> None:
    key, ids = KEYS[1], conv_ids("random", 5000, 1)
    got = gpu_bucket_prf(dev(xp, key), xp.asarray(ids), n_buckets)
    assert_same(got, chacha_ref.bucket_prf(key, ids, n_buckets), f"B={n_buckets}")
    assert int(to_host(got).max()) < n_buckets


@pytest.mark.parametrize("n_buckets", [*BUCKETS, 5, 641, 6700417, (1 << 32) - 5, (1 << 31) + 1])
def test_mod_public_twin_is_exact_at_the_edges(n_buckets: int) -> None:
    """The Barrett reduction of kernels/common.cuh (through its twin) against `%`, at the values where a
    quotient that is one too small, or a remainder of B or more, would show."""
    b = n_buckets
    edge = {0, 1, b - 1, b, b + 1, 2 * b - 1, 2 * b, 3 * b, (1 << 32) - 1, (1 << 32) - 2, 1 << 31,
            ((1 << 32) - 1) // b * b, ((1 << 32) - 1) // b * b - 1}
    w = np.array(sorted(v for v in edge if 0 <= v < 1 << 32), dtype=np.uint32)
    w = np.concatenate([w, np.random.default_rng(b).integers(0, 2**32, 4096, dtype=np.uint32)])
    assert_same(sim._mod_public(w, b), (w.astype(np.uint64) % np.uint64(b)).astype(np.uint32), f"mod {b}")


def test_chain_from_master_on_the_device(xp: Any) -> None:
    """The production path: one upload of the master key, everything else from device buffers."""
    keys_dev = gpu_derive_subkeys(dev(xp, TEST_K_MASTER))
    k_tag, _, k_bkt = chacha_ref.derive_subkeys(TEST_K_MASTER)
    assert_tags(gpu_tags_for_epoch(subkey(keys_dev, SUBKEY_TAG), 11, 1 << 10),
                chacha_ref.tags_for_epoch(k_tag, 11, 1 << 10), "chain tags")
    assert_tags(gpu_reshuffle_tags(subkey(keys_dev, SUBKEY_TAG), 2, 1 << 10),
                chacha_ref.reshuffle_tags(k_tag, 2, 1 << 10), "chain re-shuffle tags")
    ids = conv_ids("random", 1 << 10, 1)
    assert_same(gpu_bucket_prf(subkey(keys_dev, SUBKEY_BKT), xp.asarray(ids), 64),
                chacha_ref.bucket_prf(k_bkt, ids, 64), "chain bucket")


# ── wrappers: keys come from device buffers only (A4), bad arguments are rejected ─


def test_wrappers_reject_key_bytes() -> None:
    key, ids = KEYS[1], conv_ids("random", 64, 1)
    hi, lo = np.zeros(64, dtype=np.uint64), np.zeros(64, dtype=np.uint64)
    calls = (lambda k: gpu_tags_for_epoch(k, 1, 64), lambda k: gpu_reshuffle_tags(k, 1, 64),
             lambda k: gpu_tags(k, 1, DOMAIN_EPOCH, hi, lo), gpu_derive_subkeys,
             lambda k: gpu_bucket_prf(k, ids, 16), lambda k: gpu_chacha_blocks(k, words(bytes(12)), 0, 1))
    for call in calls:
        for host_key in (key, bytearray(key), memoryview(key)):
            with pytest.raises(TypeError, match="not host bytes"):
                call(host_key)
        with pytest.raises(TypeError, match="uint32 array"):
            call(np.frombuffer(key, dtype=np.uint8).copy())
        with pytest.raises(ValueError, match="with 8 elements"):
            call(words(key)[:7].copy())


def test_rejects_bad_arguments() -> None:
    key, ids = words(KEYS[1]), conv_ids("random", 64, 1)
    hi, lo = np.zeros(64, dtype=np.uint64), np.zeros(64, dtype=np.uint64)
    with pytest.raises(ValueError, match="multiple of 4"):
        gpu_tags_for_epoch(key, 1, 6)
    with pytest.raises(ValueError, match="multiple of 4"):
        gpu_tags_for_epoch(key, 1, 0)
    with pytest.raises(ValueError, match="64 bits"):
        gpu_tags_for_epoch(key, 1 << 64, 64)
    with pytest.raises(ValueError, match="lo must be one-dimensional with 64"):
        gpu_tags(key, 1, DOMAIN_EPOCH, hi, lo[:32].copy())
    with pytest.raises(TypeError, match="hi must be a uint64"):
        gpu_tags(key, 1, DOMAIN_EPOCH, hi.astype(np.uint32), lo)
    with pytest.raises(ValueError, match="contiguous"):
        gpu_tags(key, 1, DOMAIN_EPOCH, np.repeat(hi, 2)[::2], lo)
    for bad in (0, 1 << 32, -1):
        with pytest.raises(ValueError, match="n_buckets"):
            gpu_bucket_prf(key, ids, bad)
    with pytest.raises(TypeError, match="conv_ids must be a uint64"):
        gpu_bucket_prf(key, ids.astype(np.uint32), 16)
    with pytest.raises(ValueError, match="conversation ids"):
        gpu_bucket_prf(key, ids[:0].copy(), 16)
    with pytest.raises(ValueError, match="counter out of range"):
        gpu_chacha_blocks(key, words(bytes(12)), (1 << 32) - 1, 2)
    with pytest.raises(ValueError, match="subkey index"):
        subkey(np.zeros(24, dtype=np.uint32), 3)


def test_every_chacha_kernel_has_a_twin_and_a_source() -> None:
    for name in (*kernels.CHACHA_KERNELS, *kernels.PRF_KERNELS):
        src = (kernels.KERNEL_DIR / kernels.KERNEL_FILES[name]).read_text(encoding="utf-8")
        assert name in sim.names() and f"void {name}(" in src and '#include "chacha20.cuh"' in src


# ── A3: the static check reads these kernels, and flags a leak planted in them ──


@pytest.mark.parametrize(("filename", "anchor", "plant", "rule"), [
    ("chacha_tags.cu", "    chacha_block(key, t, nonce, ks);\n", "    if (ks[0] > 5) { return; }\n", "BRANCH"),
    ("prf.cu", "    chacha_block(kbkt, 0, nonce, ks);\n", "    out_bucket[ks[0] & 3] = 0;\n", "INDEX"),
    ("chacha20.cuh", "    s[12] = ctr;\n", "    s[key[0] & 15] = ctr;\n", "INDEX"),
    ("common.cuh", "    u64 r = (u64)w - q * (u64)B;\n", "    if (r >= B) { r -= B; }\n", "BRANCH"),
])
def test_check_oblivious_flags_a_leak_planted_in_the_chacha_kernels(tmp_path: Path, filename: str, anchor: str,
                                                                   plant: str, rule: str) -> None:
    for f in kernels.KERNEL_DIR.iterdir():
        shutil.copy(f, tmp_path / f.name)
    assert co.check_paths([tmp_path], root=tmp_path)[0] == []
    src = (tmp_path / filename).read_text(encoding="utf-8")
    assert src.count(anchor) == 1
    at = src.index(anchor) + len(anchor)
    (tmp_path / filename).write_text(src[:at] + plant + src[at:], encoding="utf-8")
    line = src[:at].count("\n") + 1
    found = co.check_paths([tmp_path], root=tmp_path)[0]
    assert [(Path(f.path).name, f.line, f.rule) for f in found] == [(filename, line, rule)]


# ── runner only: simulator parity and the largest size ───────────────────────


@pytest.mark.gpu
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n", SIZES)
def test_gpu_equals_simulator(n: int, seed: int) -> None:
    cp = pytest.importorskip("cupy")
    key, nonce = words(KEYS[seed]), words(hashlib.sha256(b"vcloak-test-nonce-%d" % seed).digest()[:12])
    d_key, what = cp.asarray(key), f"gpu vs twin n={n} seed={seed}"
    assert_same(gpu_chacha_blocks(d_key, cp.asarray(nonce), seed, n // 4),
                gpu_chacha_blocks(key, nonce, seed, n // 4), what + " blocks")
    assert_tags(gpu_tags_for_epoch(d_key, seed, n), gpu_tags_for_epoch(key, seed, n), what + " epoch tags")
    assert_tags(gpu_reshuffle_tags(d_key, seed, n), gpu_reshuffle_tags(key, seed, n), what + " re-shuffle tags")
    assert_same(gpu_derive_subkeys(d_key), gpu_derive_subkeys(key), what + " subkeys")
    for kind in CONV_KINDS:
        ids = conv_ids(kind, n, seed)
        for b in (BUCKETS[seed], (1 << 32) - 1):
            assert_same(gpu_bucket_prf(d_key, cp.asarray(ids), b), gpu_bucket_prf(key, ids, b),
                        what + f" bucket {kind} B={b}")


@pytest.mark.gpu
@pytest.mark.slow
@pytest.mark.parametrize("seed", SEEDS)
def test_max_log2n(seed: int) -> None:
    """n = 2^max_log2n of the device: tags against the reference (and the twin, once), buckets against the
    reference in chunks of 2^20 ids so that the host never holds more than one chunk of blocks."""
    cp = pytest.importorskip("cupy")
    n = 1 << int(get_backend().device_info()["max_log2n"])
    key = KEYS[seed]
    d_key = cp.asarray(words(key))
    got = gpu_tags_for_epoch(d_key, seed, n)
    assert_tags(got, chacha_ref.tags_for_epoch(key, seed, n), f"epoch tags n={n} seed={seed}")
    if seed == 1:
        assert_tags(got, gpu_tags_for_epoch(words(key), seed, n), f"gpu vs twin n={n}")
    del got
    assert_tags(gpu_reshuffle_tags(d_key, seed, n), chacha_ref.reshuffle_tags(key, seed, n),
                f"re-shuffle tags n={n} seed={seed}")
    ids = conv_ids("random", n, seed)
    got_b = to_host(gpu_bucket_prf(d_key, cp.asarray(ids), 1000))
    chunk = 1 << 20
    for start in range(0, n, chunk):
        assert_same(got_b[start:start + chunk], chacha_ref.bucket_prf(key, ids[start:start + chunk], 1000),
                    f"bucket n={n} seed={seed} chunk at {start}")
