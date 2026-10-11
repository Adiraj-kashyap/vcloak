"""M01 S2: the NumPy ChaCha20 stand-in and the crypto hooks (byte formats of ARCHITECTURE §5)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from testkeys import TEST_K_MASTER

from vcloak.crypto import aead_ref, chacha_ref
from vcloak.oracle import chacha_np, crypto_hooks

ROOT = Path(__file__).resolve().parents[2]
RFC_KEY = bytes(range(32))


def test_rfc8439_2_3_2_block_vector() -> None:
    nonce = bytes.fromhex("000000090000004a00000000")
    expected = bytes.fromhex(
        "10f1e7e4d13b5915500fdd1fa32071c4c7d1f4c733c068030422aa9ac3d46c4e"
        "d2826446079faa0914c2d705d98b02a2b5129cd1de164eb9cbd083e8a2503c4e")
    assert chacha_np.chacha20_blocks(RFC_KEY, nonce, counter=1)[0].tobytes() == expected


def test_rfc8439_2_5_2_poly1305_vector() -> None:
    otk = bytes.fromhex("85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b")
    tag = chacha_np.poly1305_mac(otk, b"Cryptographic Forum Research Group")
    assert tag.hex() == "a8061dc1305136c6c22b8baf0c0127a9"


def test_rfc8439_2_8_2_aead_vector() -> None:
    key = bytes(range(0x80, 0xA0))
    nonce = bytes.fromhex("070000004041424344454647")
    aad = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
    pt = (b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, "
          b"sunscreen would be it.")
    boxed = chacha_np.aead_seal(key, nonce, pt, aad)
    assert boxed[:16].hex() == "d31a8d34648e60db7b86afbc53ef7ec2"
    assert boxed[-16:].hex() == "1ae10b594f09e26a7e902ecbd0600691"
    assert chacha_np.aead_open(key, nonce, boxed, aad) == pt
    assert chacha_np.aead_open(key, nonce, boxed, aad + b"x") is None


def test_keystream_is_block_concatenation_and_counter_offsets() -> None:
    nonce = bytes(range(12))
    blocks = chacha_np.chacha20_blocks(RFC_KEY, nonce, counter=0, nblocks=5)
    assert chacha_np.chacha20_keystream(RFC_KEY, nonce, 300).tobytes() == blocks.tobytes()[:300]
    assert np.array_equal(chacha_np.chacha20_blocks(RFC_KEY, nonce, counter=3, nblocks=2), blocks[3:5])
    per_nonce = chacha_np.chacha20_block_per_nonce(RFC_KEY, np.frombuffer(nonce, dtype=np.uint8)[None, :])
    assert np.array_equal(per_nonce[0], blocks[0])
    for c in range(5):  # the single-block integer path equals the vectorised path
        assert np.array_equal(chacha_np.chacha20_blocks(RFC_KEY, nonce, counter=c)[0], blocks[c])


def test_matches_cryptography_library() -> None:
    ciphers = pytest.importorskip("cryptography.hazmat.primitives.ciphers")
    aead = pytest.importorskip("cryptography.hazmat.primitives.ciphers.aead")
    rng = np.random.default_rng(5)
    for _ in range(3):
        key, nonce = rng.bytes(32), rng.bytes(12)
        algo = ciphers.algorithms.ChaCha20(key, (7).to_bytes(4, "little") + nonce)
        enc = ciphers.Cipher(algo, mode=None).encryptor()
        assert enc.update(bytes(4096)) == chacha_np.chacha20_keystream(key, nonce, 4096, counter=7).tobytes()
        pt, aad = rng.bytes(int(rng.integers(0, 200))), rng.bytes(int(rng.integers(0, 40)))
        assert aead.ChaCha20Poly1305(key).encrypt(nonce, pt, aad) == chacha_np.aead_seal(key, nonce, pt, aad)


def test_bad_arguments_rejected() -> None:
    with pytest.raises(ValueError):
        chacha_np.chacha20_blocks(b"short", bytes(12))
    with pytest.raises(ValueError):
        chacha_np.chacha20_blocks(RFC_KEY, bytes(8))
    with pytest.raises(ValueError):
        chacha_np.chacha20_blocks(RFC_KEY, bytes(12), counter=(1 << 32) - 1, nblocks=2)


def test_hooks_use_numpy_reference_until_m02() -> None:
    if chacha_ref.IMPLEMENTED or aead_ref.IMPLEMENTED:
        pytest.skip("M02 references are wired in")
    assert crypto_hooks.backend_name() == "vcloak.oracle.chacha_np"
    with pytest.raises(NotImplementedError):
        chacha_ref.tags_for_epoch(TEST_K_MASTER, 0, 4)


def test_subkeys_follow_the_label_format() -> None:
    k_tag, k_seq, k_bkt = crypto_hooks.derive_subkeys(TEST_K_MASTER)
    assert len({k_tag, k_seq, k_bkt, TEST_K_MASTER}) == 4 and all(len(k) == 32 for k in (k_tag, k_seq, k_bkt))
    assert k_tag == chacha_np.chacha20_blocks(TEST_K_MASTER, b"vcloak-tag\0\0")[0, :32].tobytes()
    assert k_seq == chacha_np.chacha20_blocks(TEST_K_MASTER, b"vcloak-seq\0\0")[0, :32].tobytes()
    assert k_bkt == chacha_np.chacha20_blocks(TEST_K_MASTER, b"vcloak-bkt\0\0")[0, :32].tobytes()


@pytest.mark.parametrize("n", [1, 4, 5, 64, 1000])
def test_tag_i_is_keystream_bytes_16i(n: int) -> None:
    k_tag, _, _ = crypto_hooks.derive_subkeys(TEST_K_MASTER)
    for number, suffix, fn in ((7, "00000000", crypto_hooks.tags_for_epoch),
                               (7, "00000080", crypto_hooks.reshuffle_tags)):
        nonce = number.to_bytes(8, "little") + bytes.fromhex(suffix)
        ks = chacha_np.chacha20_keystream(k_tag, nonce, 16 * n).tobytes()
        hi, lo = fn(k_tag, number, n)
        assert hi.dtype == lo.dtype == np.uint64 and hi.shape == lo.shape == (n,)
        for i in (0, n // 2, n - 1):
            assert int(hi[i]) == int.from_bytes(ks[16 * i:16 * i + 8], "little")
            assert int(lo[i]) == int.from_bytes(ks[16 * i + 8:16 * i + 16], "little")


def test_epoch_and_reshuffle_tags_are_domain_separated() -> None:
    k_tag, _, _ = crypto_hooks.derive_subkeys(TEST_K_MASTER)
    e, r = crypto_hooks.tags_for_epoch(k_tag, 3, 64), crypto_hooks.reshuffle_tags(k_tag, 3, 64)
    assert not np.array_equal(e[0], r[0])
    assert not np.array_equal(e[0], crypto_hooks.tags_for_epoch(k_tag, 4, 64)[0])


def test_bucket_prf_format_and_range() -> None:
    _, _, k_bkt = crypto_hooks.derive_subkeys(TEST_K_MASTER)
    ids = np.array([0, 1, 2**40 + 5, 2**64 - 1], dtype=np.uint64)
    got = crypto_hooks.bucket_prf(k_bkt, ids, 64)
    for cid, b in zip(ids.tolist(), got.tolist(), strict=True):
        block = chacha_np.chacha20_blocks(k_bkt, cid.to_bytes(8, "little") + bytes(4))[0].tobytes()
        assert b == int.from_bytes(block[:4], "little") % 64
    many = crypto_hooks.bucket_prf(k_bkt, np.arange(5000, dtype=np.uint64), 64)
    assert many.min() >= 0 and many.max() < 64 and len(np.unique(many)) == 64


def test_seq_enc_round_trip_and_tamper() -> None:
    _, k_seq, k_bkt = crypto_hooks.derive_subkeys(TEST_K_MASTER)
    blob = crypto_hooks.seal_seq(k_seq, 2**63 + 9, 41, nonce=bytes(range(12)))
    assert len(blob) == 44 and blob[:12] == bytes(range(12))
    assert crypto_hooks.open_seq(k_seq, blob) == (True, 2**63 + 9, 41)
    assert crypto_hooks.seal_seq(k_seq, 1, 1) != crypto_hooks.seal_seq(k_seq, 1, 1)  # fresh nonce per row
    for pos in (0, 12, 27, 43):
        bad = bytearray(blob)
        bad[pos] ^= 1
        assert crypto_hooks.open_seq(k_seq, bytes(bad)) == (False, 0, 0)
    assert crypto_hooks.open_seq(k_bkt, blob) == (False, 0, 0)
    assert crypto_hooks.open_seq(k_seq, blob[:-1]) == (False, 0, 0)


def test_no_server_side_hkdf_hmac_aes_in_oracle() -> None:
    """Audit A4, kept as a test so it cannot regress."""
    hits = []
    for path in sorted((ROOT / "src" / "vcloak" / "oracle").glob("*.py")):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(word in line for word in ("HKDF", "hmac", "AESGCM")):
                hits.append(f"{path.name}:{no}")
    assert hits == []


def test_oracle_imports_without_cryptography() -> None:
    code = ("import sys; sys.modules['cryptography'] = None; "
            "import vcloak.oracle.crypto_hooks, vcloak.oracle.reference; print('ok')")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, env=env)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr
