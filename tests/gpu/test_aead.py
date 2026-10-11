"""M05: Poly1305 and the seq_enc AEAD kernels (seal, open) and their NumPy twins (ai/TESTING.md §2, §2b, §3).

Every test with the `xp` fixture runs twice: on NumPy arrays (the simulator twins, on any machine) and
on CuPy arrays (the CUDA kernels, marked `gpu`, on the runner only). Equality is byte equality.
The references are `cryptography` (Poly1305) and `vcloak.crypto.aead_ref` (ChaCha20-Poly1305), checked
against RFC 8439 in M02.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from cryptography.hazmat.primitives.poly1305 import Poly1305
from test_chacha import (
    CONV_KINDS,
    EDGE_KEYS,
    GOLDEN,
    KEYS,
    SEEDS,
    SIZES,
    assert_same,
    conv_ids,
    dev,
    to_host,
    words,
    xp,  # noqa: F401 - the numpy / cupy fixture
)

import check_oblivious as co
from vcloak.crypto import aead_ref
from vcloak.gpu import kernels, sim
from vcloak.gpu.kernels import (
    SEQ_ENC_LEN,
    SEQ_WORDS,
    gpu_aead_tag,
    gpu_chacha_blocks,
    gpu_open_and_key,
    gpu_poly1305,
    gpu_seal_seq,
    pack_seq_enc,
    unpack_seq_enc,
)
from vcloak.gpu.runtime import get_backend

LENGTHS = (0, 1, 15, 16, 17, 31, 32, 33, 34, 48, 63, 64, 65, 114, 255)  # every alignment of a 16-byte block
ROW_KINDS = ("hit", "hit", "hit", "other_conv", "bad_tag", "bad_ct", "bad_nonce", "dummy")
P1305 = (1 << 130) - 5


def tag_bytes(tags: Any) -> bytes:
    return to_host(tags).astype("<u4").tobytes()


def rand_bytes(seed: int, what: str, n: int) -> bytes:
    """n deterministic public bytes (nonces, messages, dummy rows)."""
    return np.random.default_rng([seed, int.from_bytes(what.encode(), "little") % (1 << 32), n]).integers(
        0, 256, n, dtype=np.uint8).tobytes()


def ref_seal(key: bytes, conv: np.ndarray, seq: np.ndarray, nonces: bytes) -> list[bytes]:
    return [aead_ref.seal_seq(key, int(c), int(s), nonces[12 * i:12 * i + 12])
            for i, (c, s) in enumerate(zip(conv.tolist(), seq.tolist(), strict=True))]


def ref_open_columns(key: bytes, blobs: list[bytes], q_conv: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(hi, lo, ok) as the module spec defines them, from the CPU reference."""
    n = len(blobs)
    hi, lo, ok = np.ones(n, dtype=np.uint64), np.zeros(n, dtype=np.uint64), np.zeros(n, dtype=np.uint32)
    for i, blob in enumerate(blobs):
        good, conv, seq = aead_ref.open_seq(key, blob)
        ok[i] = int(good)
        if good and conv == q_conv:
            hi[i], lo[i] = 0, seq
    return hi, lo, ok


def flip(blob: bytes, bit: int) -> bytes:
    b = bytearray(blob)
    b[bit // 8] ^= 1 << (bit % 8)
    return bytes(b)


def mixed_rows(key: bytes, n: int, seed: int, q_conv: int) -> list[bytes]:
    """n candidate rows: rows of q_conv, rows of another conversation, rows of q_conv with one bit of the
    tag, the ciphertext or the nonce flipped, and random 44-byte dummies."""
    rng = np.random.default_rng([seed, n, 5])
    kinds = [ROW_KINDS[i % len(ROW_KINDS)] for i in range(n)]
    conv = np.array([(q_conv + 1) % (1 << 64) if k == "other_conv" else q_conv for k in kinds], dtype=np.uint64)
    seq = rng.integers(0, 2**64, n, dtype=np.uint64)
    seq[:4] = (0, 2**64 - 1, 1, 2**63)
    rows = ref_seal(key, conv, seq, rand_bytes(seed, "nonce", 12 * n))
    dummies = rand_bytes(seed, "dummy", SEQ_ENC_LEN * n)
    spans = {"bad_nonce": (0, 96), "bad_ct": (96, 224), "bad_tag": (224, 352)}
    for i, k in enumerate(kinds):
        if k == "dummy":
            rows[i] = dummies[SEQ_ENC_LEN * i:SEQ_ENC_LEN * (i + 1)]
        elif k in spans:
            rows[i] = flip(rows[i], int(rng.integers(*spans[k])))
    return rows


def assert_open(got: tuple[Any, Any, Any], want: tuple[np.ndarray, np.ndarray, np.ndarray], what: str) -> None:
    for g, w, col in zip(got, want, ("hi", "lo", "ok"), strict=True):
        assert_same(g, w, f"{what} {col}")


# ── S1: Poly1305 (A1) ────────────────────────────────────────────────────────


def test_rfc8439_2_5_2_poly1305(xp: Any) -> None:  # noqa: F811
    doc = json.loads((GOLDEN / "rfc8439_poly1305.json").read_text(encoding="ascii"))
    assert doc["source"].startswith("RFC 8439 section 2.5.2")
    for v in doc["vectors"]:
        msg = v["message_ascii"].encode("ascii")
        tags = gpu_poly1305(dev(xp, bytes.fromhex(v["key"])), xp.asarray(np.frombuffer(msg, np.uint8)), len(msg))
        assert tag_bytes(tags) == bytes.fromhex(v["tag"])


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("nbytes", LENGTHS)
def test_poly1305_equals_reference_at_every_alignment(xp: Any, nbytes: int, seed: int) -> None:  # noqa: F811
    n = 300  # more than one launch block, and the last block is not full
    keys, msgs = rand_bytes(seed, "otk", 32 * n), rand_bytes(seed, "msg", nbytes * n)
    got = tag_bytes(gpu_poly1305(dev(xp, keys), xp.asarray(np.frombuffer(msgs, np.uint8)), nbytes))
    want = b"".join(Poly1305.generate_tag(keys[32 * t:32 * t + 32], msgs[nbytes * t:nbytes * (t + 1)])
                    for t in range(n))
    assert got == want


def test_poly1305_final_reduction_edges(xp: Any) -> None:  # noqa: F811
    """Small r (1, 2), the largest clamped r and blocks of 0xff / 0xfa..0xfc bytes: sums that land on or
    next to multiples of p = 2^130 - 5, where the masked final subtraction and the carries into s decide
    the tag. The expected tags come from the reference."""
    def le(v: int, size: int = 16) -> bytes:
        return v.to_bytes(size, "little")

    cases = []
    for r in (1, 2, (1 << 124) - 1 & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF):
        for s in (0, 1, (1 << 128) - 1):
            key = le(r) + le(s)
            for blocks in ((b"\xff" * 16,), (b"\xff" * 16, b"\xfb" + b"\xff" * 15), (b"\xff" * 16,) * 3,
                           (b"\xff" * 16,) * 4, (le(P1305 % (1 << 128) - 1),) * 4, (b"\x00" * 16,) * 4,
                           (b"\xfa" + b"\xff" * 15,) * 4, (b"\xfb" + b"\xff" * 15,) * 4, (b"\xfc" + b"\xff" * 15,) * 4):
                cases.append((key, b"".join(blocks)))
    for nbytes in sorted({len(m) for _, m in cases}):
        batch = [(k, m) for k, m in cases if len(m) == nbytes]
        keys, msgs = b"".join(k for k, _ in batch), b"".join(m for _, m in batch)
        got = tag_bytes(gpu_poly1305(dev(xp, keys), xp.asarray(np.frombuffer(msgs, np.uint8)), nbytes))
        assert got == b"".join(Poly1305.generate_tag(k, m) for k, m in batch), f"reduction edge, {nbytes} bytes"


# ── S2: AEAD tag, seal, open (A1, A2) ────────────────────────────────────────


def test_rfc8439_2_8_2_aead(xp: Any) -> None:  # noqa: F811
    doc = json.loads((GOLDEN / "rfc8439_aead.json").read_text(encoding="ascii"))
    assert doc["source"].startswith("RFC 8439 section 2.8.2")
    for v in doc["vectors"]:
        key, nonce = dev(xp, bytes.fromhex(v["key"])), dev(xp, bytes.fromhex(v["nonce"]))
        pt, ct = v["plaintext_ascii"].encode("ascii"), bytes.fromhex(v["ciphertext"])
        ks = to_host(gpu_chacha_blocks(key, nonce, 1, -(-len(pt) // 64))).astype("<u4").tobytes()[: len(pt)]
        assert bytes(a ^ b for a, b in zip(pt, ks, strict=True)) == ct
        aad = xp.asarray(np.frombuffer(bytes.fromhex(v["aad"]), np.uint8))
        tags = gpu_aead_tag(key, nonce, aad, xp.asarray(np.frombuffer(ct, np.uint8)), len(ct))
        assert tag_bytes(tags) == bytes.fromhex(v["tag"])


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize(("aad_len", "box_len"), [(0, 0), (13, 16), (12, 114), (16, 32), (1, 1), (17, 15), (40, 65)])
def test_aead_tag_equals_reference(xp: Any, aad_len: int, box_len: int, seed: int) -> None:  # noqa: F811
    n, key = 70, KEYS[seed]
    nonces, aad = rand_bytes(seed, "nonce", 12 * n), rand_bytes(seed, "aad", aad_len)
    pts = rand_bytes(seed, "pt", box_len * n)
    boxed = [aead_ref.aead_seal(key, nonces[12 * i:12 * i + 12], pts[box_len * i:box_len * (i + 1)], aad)
             for i in range(n)]
    boxes = np.frombuffer(b"".join(b[:box_len] for b in boxed), np.uint8)
    got = gpu_aead_tag(dev(xp, key), dev(xp, nonces), xp.asarray(np.frombuffer(aad, np.uint8)), xp.asarray(boxes),
                       box_len)
    assert tag_bytes(got) == b"".join(b[box_len:] for b in boxed)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n", SIZES)
def test_seal_equals_reference(xp: Any, n: int, seed: int) -> None:  # noqa: F811
    key = KEYS[seed]
    kind = CONV_KINDS[(seed + n.bit_length()) % len(CONV_KINDS)]
    conv, seq = conv_ids(kind, n, seed), conv_ids("random", n, seed + 10)
    nonces = rand_bytes(seed, "nonce", 12 * n)
    got = gpu_seal_seq(dev(xp, key), xp.asarray(conv), xp.asarray(seq), dev(xp, nonces))
    assert unpack_seq_enc(got) == ref_seal(key, conv, seq, nonces), f"seal n={n} seed={seed} {kind}"


@pytest.mark.parametrize("kind", CONV_KINDS)
def test_seal_adversarial_columns(xp: Any, kind: str) -> None:  # noqa: F811
    n, key = 1000, EDGE_KEYS["master"]
    conv, seq, nonces = conv_ids(kind, n, 1), conv_ids(kind, n, 2), bytes(12 * n)  # also: one repeated nonce
    got = gpu_seal_seq(dev(xp, key), xp.asarray(conv), xp.asarray(seq), dev(xp, nonces))
    assert unpack_seq_enc(got) == ref_seal(key, conv, seq, nonces)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n", SIZES)
def test_open_equals_reference_on_valid_tampered_and_dummy_rows(xp: Any, n: int, seed: int) -> None:  # noqa: F811
    key, q_conv = KEYS[seed], (0, 2**64 - 1, 0x0123456789ABCDEF)[seed - 1]
    rows = mixed_rows(key, n, seed, q_conv)
    want = ref_open_columns(key, rows, q_conv)
    assert 0 < int((want[0] == 0).sum()) < n and 0 < int(want[2].sum()) < n  # the mix has hits, misses, failures
    assert_open(gpu_open_and_key(dev(xp, key), xp.asarray(pack_seq_enc(rows)), q_conv), want, f"open n={n}")
    other = (q_conv + 1) % (1 << 64)  # the same rows read for the other conversation
    assert_open(gpu_open_and_key(dev(xp, key), xp.asarray(pack_seq_enc(rows)), other),
                ref_open_columns(key, rows, other), f"open n={n} other conversation")


@pytest.mark.parametrize("name", sorted(EDGE_KEYS))
def test_every_single_bit_flip_is_a_miss(xp: Any, name: str) -> None:  # noqa: F811
    key, q_conv, seq = EDGE_KEYS[name], 7, 2**64 - 1
    blob = aead_ref.seal_seq(key, q_conv, seq, bytes(range(12)))
    rows = [blob] + [flip(blob, bit) for bit in range(8 * SEQ_ENC_LEN)]
    hi, lo, ok = (to_host(c) for c in gpu_open_and_key(dev(xp, key), xp.asarray(pack_seq_enc(rows)), q_conv))
    assert (int(hi[0]), int(lo[0]), int(ok[0])) == (0, seq, 1)
    assert not ok[1:].any() and (hi[1:] == 1).all() and not lo[1:].any()
    assert_open((hi, lo, ok), ref_open_columns(key, rows, q_conv), "bit flips")


def test_open_under_the_wrong_key_misses_everything(xp: Any) -> None:  # noqa: F811
    n = 256
    conv, seq = np.full(n, 3, dtype=np.uint64), np.arange(n, dtype=np.uint64)
    blobs = gpu_seal_seq(dev(xp, KEYS[1]), xp.asarray(conv), xp.asarray(seq), dev(xp, rand_bytes(1, "nonce", 12 * n)))
    hi, lo, ok = (to_host(c) for c in gpu_open_and_key(dev(xp, KEYS[2]), blobs, 3))
    assert not ok.any() and (hi == 1).all() and not lo.any()
    hi, lo, ok = (to_host(c) for c in gpu_open_and_key(dev(xp, KEYS[1]), blobs, 3))
    assert ok.all() and not hi.any() and (lo == seq).all()


def test_pack_and_unpack_are_inverse() -> None:
    rows = [rand_bytes(i, "row", SEQ_ENC_LEN) for i in range(5)]
    packed = pack_seq_enc(rows)
    assert packed.dtype == np.uint32 and packed.shape == (5 * SEQ_WORDS,) and unpack_seq_enc(packed) == rows
    with pytest.raises(ValueError, match="44 bytes"):
        pack_seq_enc([bytes(43)])


# ── wrappers: keys come from device buffers only, bad arguments are rejected ──


def test_wrappers_reject_key_bytes() -> None:
    key, n = KEYS[1], 4
    col, nonces = np.zeros(n, dtype=np.uint64), np.zeros(3 * n, dtype=np.uint32)
    blobs, empty = np.zeros(SEQ_WORDS * n, dtype=np.uint32), np.zeros(0, dtype=np.uint8)
    calls = (lambda k: gpu_seal_seq(k, col, col, nonces), lambda k: gpu_open_and_key(k, blobs, 1),
             lambda k: gpu_aead_tag(k, nonces, empty, empty, 0))
    for call in calls:
        for host_key in (key, bytearray(key), memoryview(key)):
            with pytest.raises(TypeError, match="not host bytes"):
                call(host_key)
        with pytest.raises(TypeError, match="uint32 array"):
            call(np.frombuffer(key, dtype=np.uint8).copy())
        with pytest.raises(ValueError, match="with 8 elements"):
            call(words(key)[:7].copy())
    with pytest.raises(TypeError, match="not host bytes"):
        gpu_poly1305(key, empty, 0)


def test_rejects_bad_arguments() -> None:
    key, n = words(KEYS[1]), 4
    col, nonces = np.zeros(n, dtype=np.uint64), np.zeros(3 * n, dtype=np.uint32)
    blobs = np.zeros(SEQ_WORDS * n, dtype=np.uint32)
    with pytest.raises(ValueError, match="blobs must hold 11 elements"):
        gpu_open_and_key(key, blobs[:-1].copy(), 1)
    with pytest.raises(ValueError, match="blobs must hold 11 elements"):
        gpu_open_and_key(key, blobs[:0].copy(), 1)
    with pytest.raises(TypeError, match="blobs must be a uint32"):
        gpu_open_and_key(key, blobs.astype(np.uint8), 1)
    for bad in (-1, 1 << 64):
        with pytest.raises(ValueError, match="64 bits"):
            gpu_open_and_key(key, blobs, bad)
    with pytest.raises(ValueError, match="seqs must be one-dimensional with 4"):
        gpu_seal_seq(key, col, col[:3].copy(), nonces)
    with pytest.raises(ValueError, match="nonces must be one-dimensional with 12"):
        gpu_seal_seq(key, col, col, nonces[:-3].copy())
    with pytest.raises(TypeError, match="conv_ids must be a uint64"):
        gpu_seal_seq(key, col.astype(np.uint32), col, nonces)
    with pytest.raises(ValueError, match="msgs must be one-dimensional with 16"):
        gpu_poly1305(np.zeros(16, dtype=np.uint32), np.zeros(17, dtype=np.uint8), 8)
    with pytest.raises(ValueError, match="message length"):
        gpu_poly1305(key, np.zeros(0, dtype=np.uint8), 1 << 16)
    with pytest.raises(ValueError, match="boxes must be one-dimensional with 8"):
        gpu_aead_tag(key, nonces, np.zeros(1, dtype=np.uint8), np.zeros(9, dtype=np.uint8), 2)


def test_every_aead_kernel_has_a_twin_and_a_source() -> None:
    for name in (*kernels.POLY_KERNELS, *kernels.AEAD_KERNELS):
        src = (kernels.KERNEL_DIR / kernels.KERNEL_FILES[name]).read_text(encoding="utf-8")
        assert name in sim.names() and f"void {name}(" in src
    seq_src = (kernels.KERNEL_DIR / "aead_seq.cuh").read_text(encoding="utf-8")
    for word in sim.SEQ_AAD_WORDS:
        assert f"0x{word:08x}u" in seq_src
    assert b"".join(w.to_bytes(4, "little") for w in sim.SEQ_AAD_WORDS) == aead_ref.SEQ_AAD + bytes(3)
    assert sim.SEQ_LEN_WORDS == (len(aead_ref.SEQ_AAD), 0, aead_ref.SEQ_PT_LEN, 0)
    assert SEQ_ENC_LEN == aead_ref.SEQ_ENC_LEN


# ── A3: the static check reads these kernels, and flags a leak planted in them ──


@pytest.mark.parametrize(("filename", "anchor", "plant", "rule"), [
    ("aead_open.cu", "    u64 ok = (u64)(diff == 0);\n", "    if (ok) { out_lo[t] = 0; }\n", "BRANCH"),
    ("aead_open.cu", "    seq_tag(otk, ct, tag);\n", "    out_ok[tag[0] & 1] = 0;\n", "INDEX"),
    ("aead_open.cu", "    u64 ok = (u64)(diff == 0);\n", "    out_lo[t] = (conv == q_conv) ? seq : 0;\n", "TERNARY"),
    ("aead_seal.cu", "    u64 seq = seqs[t];\n", "    out_blobs[seq & 3] = 0;\n", "INDEX"),
    ("poly1305.cuh", "    u32 g4 = h4 + c - (1u << 26);\n", "    if (g4 >> 31) { return; }\n", "BRANCH"),
    ("poly1305.cuh", "    u64 r0 = r[0];\n", "    h[msg[0] & 3] = 0;\n", "INDEX"),
    ("poly1305.cu", "    chacha_block(key, 0, nonce, otk);\n", "    while (otk[0] > 5) { return; }\n", "BRANCH"),
    ("aead_seq.cuh", "    poly1305_init(otk, r, h);\n", "    if (ct[0] == 0) { return; }\n", "BRANCH"),
])
def test_check_oblivious_flags_a_leak_planted_in_the_aead_kernels(tmp_path: Path, filename: str, anchor: str,
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
    key, what = words(KEYS[seed]), f"gpu vs twin n={n} seed={seed}"
    d_key = cp.asarray(key)
    nonces = words(rand_bytes(seed, "nonce", 12 * n))
    for kind in CONV_KINDS:
        conv, seq = conv_ids(kind, n, seed), conv_ids("random", n, seed + 10)
        got = gpu_seal_seq(d_key, cp.asarray(conv), cp.asarray(seq), cp.asarray(nonces))
        assert_same(got, gpu_seal_seq(key, conv, seq, nonces), what + f" seal {kind}")
    q_conv = seed
    rows = pack_seq_enc(mixed_rows(KEYS[seed], n, seed, q_conv))
    for q in (q_conv, q_conv + 1):
        assert_open(gpu_open_and_key(d_key, cp.asarray(rows), q), gpu_open_and_key(key, rows, q), what + " open")
    m = n // 16
    for nbytes in (0, 13, 16, 34, 100):
        keys = words(rand_bytes(seed, "otk", 32 * m))
        msgs = np.frombuffer(rand_bytes(seed, "msg", nbytes * m), np.uint8)
        assert_same(gpu_poly1305(cp.asarray(keys), cp.asarray(msgs), nbytes), gpu_poly1305(keys, msgs, nbytes),
                    what + f" poly1305 {nbytes} bytes")
        aad = np.frombuffer(rand_bytes(seed, "aad", 13), np.uint8)
        assert_same(gpu_aead_tag(d_key, cp.asarray(nonces[:3 * m]), cp.asarray(aad), cp.asarray(msgs), nbytes),
                    gpu_aead_tag(key, nonces[:3 * m].copy(), aad, msgs, nbytes), what + f" aead_tag {nbytes} bytes")


@pytest.mark.gpu
@pytest.mark.slow
@pytest.mark.parametrize("seed", SEEDS)
def test_max_log2n(seed: int) -> None:
    """n = 2^max_log2n rows: seal on the device, open on the device (every row authentic, seq restored),
    2^14 sampled rows against the reference, and for seed 1 every row against the twin in chunks of 2^20."""
    cp = pytest.importorskip("cupy")
    n = 1 << int(get_backend().device_info()["max_log2n"])
    key = KEYS[seed]
    d_key = cp.asarray(words(key))
    rng = np.random.default_rng([seed, n, 9])
    conv = rng.integers(0, 2, n, dtype=np.uint64) + np.uint64(40)  # two conversations: 40 and 41
    seq = rng.integers(0, 2**64, n, dtype=np.uint64)
    nonces = rng.integers(0, 2**32, 3 * n, dtype=np.uint32)
    d_blobs = gpu_seal_seq(d_key, cp.asarray(conv), cp.asarray(seq), cp.asarray(nonces))
    d_hi, d_lo, d_ok = gpu_open_and_key(d_key, d_blobs, 40)
    assert int(d_ok.sum()) == n
    assert_same(d_hi, (conv != 40).astype(np.uint64), f"hi n={n} seed={seed}")
    assert_same(d_lo, np.where(conv == 40, seq, np.uint64(0)).astype(np.uint64), f"lo n={n} seed={seed}")
    del d_hi, d_lo, d_ok
    blobs = to_host(d_blobs).reshape(n, SEQ_WORDS)
    del d_blobs
    sample = np.sort(rng.choice(n, 1 << 14, replace=False))
    nonce_rows = nonces.reshape(n, 3)
    for i in sample.tolist():
        want = aead_ref.seal_seq(key, int(conv[i]), int(seq[i]), nonce_rows[i].astype("<u4").tobytes())
        assert blobs[i].astype("<u4").tobytes() == want, f"row {i} of n={n} seed={seed}"
    if seed == 1:
        chunk = 1 << 20
        for start in range(0, n, chunk):
            end = start + chunk
            twin = gpu_seal_seq(words(key), conv[start:end].copy(), seq[start:end].copy(),
                                nonces[3 * start:3 * end].copy())
            assert_same(blobs[start:end].reshape(-1), twin, f"gpu vs twin n={n} chunk at {start}")
