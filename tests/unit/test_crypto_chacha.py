"""M02 S1-S2: the ChaCha20 reference against RFC 8439 and `cryptography`, and the constructions of ARCHITECTURE §5."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from scipy.stats import chisquare

from testkeys import TEST_K_MASTER
from vcloak.crypto import chacha_ref
from vcloak.oracle import chacha_np

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
MIB = 1 << 20
# fixed test inputs, derived here and used nowhere else (CONVENTIONS §3)
KEYS = [hashlib.sha256(b"vcloak-test-key-%d" % i).digest() for i in range(3)]
NONCES = [hashlib.sha256(b"vcloak-test-nonce-%d" % i).digest()[:12] for i in range(3)]


def _vectors(name: str) -> list[dict]:
    doc = json.loads((GOLDEN / name).read_text(encoding="ascii"))
    assert doc["source"].startswith("RFC 8439 section")
    return doc["vectors"]


def _openssl_keystream(key: bytes, nonce: bytes, nbytes: int, counter: int = 0) -> bytes:
    """`cryptography`'s ChaCha20: its 16-byte nonce is LE32(counter) || the 12-byte nonce."""
    enc = Cipher(algorithms.ChaCha20(key, counter.to_bytes(4, "little") + nonce), mode=None).encryptor()
    return enc.update(bytes(nbytes))


def test_rfc8439_2_3_2_block() -> None:
    for v in _vectors("rfc8439_block.json"):
        got = chacha_ref.block(bytes.fromhex(v["key"]), bytes.fromhex(v["nonce"]), v["counter"])
        assert got.shape == (1, 64) and got.tobytes() == bytes.fromhex(v["block"])


def test_rfc8439_2_4_2_keystream() -> None:
    for v in _vectors("rfc8439_keystream.json"):
        pt = np.frombuffer(v["plaintext_ascii"].encode("ascii"), dtype=np.uint8)
        ks = chacha_ref.keystream(bytes.fromhex(v["key"]), bytes.fromhex(v["nonce"]), pt.size, v["counter"])
        assert (pt ^ ks).tobytes() == bytes.fromhex(v["ciphertext"])


@pytest.mark.parametrize("ki", range(3))
@pytest.mark.parametrize("ni", range(3))
def test_keystream_equals_cryptography_over_1_mib(ki: int, ni: int) -> None:
    got = chacha_ref.keystream(KEYS[ki], NONCES[ni], MIB)
    assert got.dtype == np.uint8 and got.tobytes() == _openssl_keystream(KEYS[ki], NONCES[ni], MIB)


@pytest.mark.parametrize("counter,nbytes", [(1, 1), (7, 63), (7, 64), (7, 65), (1000, 1000), ((1 << 32) - 2, 128)])
def test_keystream_counter_and_ragged_lengths(counter: int, nbytes: int) -> None:
    got = chacha_ref.keystream(KEYS[0], NONCES[0], nbytes, counter)
    assert got.tobytes() == _openssl_keystream(KEYS[0], NONCES[0], nbytes, counter)


def test_keystream_is_independent_of_chunking(monkeypatch: pytest.MonkeyPatch) -> None:
    whole = chacha_ref.keystream(KEYS[1], NONCES[1], 5000).copy()
    monkeypatch.setattr(chacha_ref, "_CHUNK_BLOCKS", 7)
    assert np.array_equal(chacha_ref.keystream(KEYS[1], NONCES[1], 5000), whole)
    assert chacha_ref.keystream(KEYS[1], NONCES[1], 0).size == 0


def test_block_per_nonce_equals_block() -> None:
    nonces = np.frombuffer(b"".join(NONCES), dtype=np.uint8).reshape(3, 12)
    got = chacha_ref.block_per_nonce(KEYS[2], nonces, counter=5)
    for i, nonce in enumerate(NONCES):
        assert got[i].tobytes() == chacha_ref.block(KEYS[2], nonce, 5)[0].tobytes()


def test_agrees_with_the_independent_oracle_implementation() -> None:
    ours, theirs = chacha_ref.block(KEYS[0], NONCES[1], 3, 40), chacha_np.chacha20_blocks(KEYS[0], NONCES[1], 3, 40)
    assert np.array_equal(ours, theirs)


def test_bad_arguments_rejected() -> None:
    for call in (lambda: chacha_ref.block(b"short", bytes(12)),
                 lambda: chacha_ref.block(KEYS[0], bytes(8)),
                 lambda: chacha_ref.block(KEYS[0], bytes(12), counter=(1 << 32) - 1, nblocks=2),
                 lambda: chacha_ref.block_per_nonce(KEYS[0], np.zeros((2, 8), dtype=np.uint8)),
                 lambda: chacha_ref.keystream(KEYS[0], bytes(12), -1),
                 lambda: chacha_ref.bucket_prf(KEYS[0], np.arange(4), 0)):
        with pytest.raises(ValueError):
            call()


def test_subkeys_follow_the_label_format() -> None:
    subkeys = chacha_ref.derive_subkeys(TEST_K_MASTER)
    assert len({*subkeys, TEST_K_MASTER}) == 4 and all(len(k) == 32 for k in subkeys)
    for key, label in zip(subkeys, (b"vcloak-tag\0\0", b"vcloak-seq\0\0", b"vcloak-bkt\0\0"), strict=True):
        assert len(label) == 12 and key == _openssl_keystream(TEST_K_MASTER, label, 32)


@pytest.mark.parametrize("n", [1, 4, 5, 64, 1000, 4097])
def test_tag_i_is_keystream_bytes_16i(n: int) -> None:
    k_tag, _, _ = chacha_ref.derive_subkeys(TEST_K_MASTER)
    for number, suffix, fn in ((7, "00000000", chacha_ref.tags_for_epoch), (7, "00000080", chacha_ref.reshuffle_tags),
                               ((1 << 64) - 1, "00000000", chacha_ref.tags_for_epoch)):
        ks = _openssl_keystream(k_tag, number.to_bytes(8, "little") + bytes.fromhex(suffix), 16 * n)
        hi, lo = fn(k_tag, number, n)
        assert hi.dtype == np.uint64 and lo.dtype == np.uint64 and hi.shape == lo.shape == (n,)
        for i in (0, n // 2, n - 1):
            assert int(hi[i]) == int.from_bytes(ks[16 * i:16 * i + 8], "little")
            assert int(lo[i]) == int.from_bytes(ks[16 * i + 8:16 * i + 16], "little")
        assert np.column_stack([hi, lo]).astype("<u8").tobytes() == ks


def test_epoch_and_reshuffle_tags_are_domain_separated() -> None:
    k_tag, _, _ = chacha_ref.derive_subkeys(TEST_K_MASTER)
    epoch, reshuffle = chacha_ref.tags_for_epoch(k_tag, 3, 256), chacha_ref.reshuffle_tags(k_tag, 3, 256)
    assert not np.array_equal(epoch[0], reshuffle[0])
    assert not np.array_equal(epoch[0], chacha_ref.tags_for_epoch(k_tag, 4, 256)[0])


def test_bucket_follows_the_block_format() -> None:
    _, _, k_bkt = chacha_ref.derive_subkeys(TEST_K_MASTER)
    conv_ids = np.array([0, 1, 2, 12345, (1 << 64) - 1], dtype=np.uint64)
    for n_buckets in (1, 7, 256, 1 << 32):
        got = chacha_ref.bucket_prf(k_bkt, conv_ids, n_buckets)
        assert got.dtype == np.uint32
        for conv, bucket in zip(conv_ids.tolist(), got.tolist(), strict=True):
            word = _openssl_keystream(k_bkt, conv.to_bytes(8, "little") + bytes(4), 4)
            assert bucket == int.from_bytes(word, "little") % n_buckets


@pytest.mark.parametrize("n_buckets", [16, 256, 1000])
def test_bucket_is_uniform_over_b(n_buckets: int) -> None:
    _, _, k_bkt = chacha_ref.derive_subkeys(TEST_K_MASTER)
    buckets = chacha_ref.bucket_prf(k_bkt, np.arange(100_000, dtype=np.uint64), n_buckets)
    stat, p = chisquare(np.bincount(buckets, minlength=n_buckets))
    print(f"bucket chi2: B={n_buckets} ids=100000 chi2={stat:.3f} p={p:.4f}")
    assert p > 0.01


def test_the_oracle_is_wired_to_these_references() -> None:
    from vcloak.crypto import aead_ref
    from vcloak.oracle import crypto_hooks

    assert chacha_ref.IMPLEMENTED and aead_ref.IMPLEMENTED
    assert crypto_hooks.backend_name() == "vcloak.crypto.chacha_ref"
    assert crypto_hooks.derive_subkeys(TEST_K_MASTER) == chacha_ref.derive_subkeys(TEST_K_MASTER)
