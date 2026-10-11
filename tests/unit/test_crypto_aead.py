"""M02 S3: the seq_enc AEAD reference (RFC 8439 §2.5.2 and §2.8.2 vectors, round trip, tamper)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.poly1305 import Poly1305

from testkeys import TEST_K_MASTER
from vcloak.crypto import aead_ref, chacha_ref
from vcloak.oracle import chacha_np

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
K_SEQ = chacha_ref.derive_subkeys(TEST_K_MASTER)[1]
U64_MAX = (1 << 64) - 1


def _vectors(name: str) -> list[dict]:
    doc = json.loads((GOLDEN / name).read_text(encoding="ascii"))
    assert doc["source"].startswith("RFC 8439 section")
    return doc["vectors"]


def test_rfc8439_2_5_2_poly1305() -> None:
    for v in _vectors("rfc8439_poly1305.json"):
        key, msg = bytes.fromhex(v["key"]), v["message_ascii"].encode("ascii")
        assert Poly1305.generate_tag(key, msg).hex() == v["tag"]
        assert chacha_np.poly1305_mac(key, msg).hex() == v["tag"]


def test_rfc8439_2_8_2_aead() -> None:
    for v in _vectors("rfc8439_aead.json"):
        key, nonce, aad = (bytes.fromhex(v[f]) for f in ("key", "nonce", "aad"))
        pt, boxed = v["plaintext_ascii"].encode("ascii"), bytes.fromhex(v["ciphertext"] + v["tag"])
        assert aead_ref.aead_seal(key, nonce, pt, aad) == boxed
        assert aead_ref.aead_open(key, nonce, boxed, aad) == pt
        assert aead_ref.aead_open(key, nonce, boxed, aad + b"x") is None
        assert chacha_np.aead_seal(key, nonce, pt, aad) == boxed


def test_seq_enc_layout() -> None:
    nonce = bytes(range(12))
    blob = aead_ref.seal_seq(K_SEQ, 0x0102030405060708, 9, nonce)
    assert len(blob) == aead_ref.SEQ_ENC_LEN == 44 and blob[:12] == nonce
    pt = (0x0102030405060708).to_bytes(8, "little") + (9).to_bytes(8, "little")
    assert blob[12:] == aead_ref.aead_seal(K_SEQ, nonce, pt, b"vcloak-seq-v1")
    assert blob[12:] == chacha_np.aead_seal(K_SEQ, nonce, pt, b"vcloak-seq-v1")  # the independent implementation
    # the ciphertext is the plaintext under keystream block 1 (RFC 8439 §2.8)
    ks = chacha_ref.keystream(K_SEQ, nonce, 16, counter=1).tobytes()
    assert bytes(a ^ b for a, b in zip(blob[12:28], ks, strict=True)) == pt


@pytest.mark.parametrize("conv_id,seq", [(0, 0), (1, 2), (U64_MAX, U64_MAX), (0xDEADBEEF, 1 << 40)])
def test_round_trip(conv_id: int, seq: int) -> None:
    blob = aead_ref.seal_seq(K_SEQ, conv_id, seq)
    assert len(blob) == 44 and aead_ref.open_seq(K_SEQ, blob) == (True, conv_id, seq)


def test_random_nonce_per_row() -> None:
    blobs = {aead_ref.seal_seq(K_SEQ, 5, 6) for _ in range(64)}
    assert len(blobs) == 64 and len({b[:12] for b in blobs}) == 64


def test_every_single_bit_flip_is_rejected_without_an_exception() -> None:
    blob = aead_ref.seal_seq(K_SEQ, 77, 3)
    for byte in range(44):
        for bit in range(8):
            bad = bytearray(blob)
            bad[byte] ^= 1 << bit
            assert aead_ref.open_seq(K_SEQ, bytes(bad)) == (False, 0, 0)


def test_wrong_key_and_wrong_lengths_are_rejected_without_an_exception() -> None:
    blob = aead_ref.seal_seq(K_SEQ, 77, 3)
    assert aead_ref.open_seq(chacha_ref.derive_subkeys(TEST_K_MASTER)[0], blob) == (False, 0, 0)
    for bad in (b"", blob[:43], blob + b"\0", bytes(44), blob[12:]):
        assert aead_ref.open_seq(K_SEQ, bad) == (False, 0, 0)


def test_seal_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        aead_ref.seal_seq(K_SEQ, 1, 2, nonce=bytes(8))
    with pytest.raises(OverflowError):
        aead_ref.seal_seq(K_SEQ, 1 << 64, 2)
