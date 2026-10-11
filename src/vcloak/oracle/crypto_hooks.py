"""The oracle's only door to server-side crypto (ADR-003, byte formats of ai/ARCHITECTURE.md §5).

Every call goes to `vcloak.crypto.*_ref` once M02 has implemented it; until then the same formats are
computed with the pure-NumPy reference in `chacha_np`.
"""
from __future__ import annotations

import os

import numpy as np

from vcloak.crypto import aead_ref, chacha_ref
from vcloak.oracle import chacha_np

LABEL_TAG = b"vcloak-tag\0\0"
LABEL_SEQ = b"vcloak-seq\0\0"
LABEL_BKT = b"vcloak-bkt\0\0"
SEQ_AAD = b"vcloak-seq-v1"
SEQ_ENC_LEN = 44
_EPOCH_SUFFIX = bytes.fromhex("00000000")
_RESHUFFLE_SUFFIX = bytes.fromhex("00000080")  # domain separation from epoch tags


def backend_name() -> str:
    """Which implementation answers the hooks: recorded in the golden files."""
    return "vcloak.crypto.chacha_ref" if chacha_ref.IMPLEMENTED else "vcloak.oracle.chacha_np"


def _le64(x: int) -> bytes:
    return int(x).to_bytes(8, "little")


def _tags(k_tag: bytes, nonce: bytes, n: int) -> tuple[np.ndarray, np.ndarray]:
    ks = chacha_np.chacha20_keystream(k_tag, nonce, 16 * n).view("<u8").reshape(n, 2)
    return ks[:, 0].astype(np.uint64), ks[:, 1].astype(np.uint64)


def derive_subkeys(k_master: bytes) -> tuple[bytes, bytes, bytes]:
    """(K_tag, K_seq, K_bkt): K_x = ChaCha20Block(K_master, counter=0, nonce=label_x)[0:32]."""
    if chacha_ref.IMPLEMENTED:
        return chacha_ref.derive_subkeys(k_master)
    k_tag, k_seq, k_bkt = (chacha_np.chacha20_blocks(k_master, label)[0, :32].tobytes()
                           for label in (LABEL_TAG, LABEL_SEQ, LABEL_BKT))
    return k_tag, k_seq, k_bkt


def tags_for_epoch(k_tag: bytes, epoch: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    """(hi, lo) for slots 0..n-1: LE64 halves of keystream bytes [16i, 16i+16), nonce LE64(epoch)||00000000."""
    if chacha_ref.IMPLEMENTED:
        return chacha_ref.tags_for_epoch(k_tag, epoch, n)
    return _tags(k_tag, _le64(epoch) + _EPOCH_SUFFIX, n)


def reshuffle_tags(k_tag: bytes, win: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    """As `tags_for_epoch` with nonce LE64(win)||00000080."""
    if chacha_ref.IMPLEMENTED:
        return chacha_ref.reshuffle_tags(k_tag, win, n)
    return _tags(k_tag, _le64(win) + _RESHUFFLE_SUFFIX, n)


def bucket_prf(k_bkt: bytes, conv_ids: np.ndarray, n_buckets: int) -> np.ndarray:
    """LE32(ChaCha20Block(K_bkt, counter=0, nonce=LE64(conv_id)||00000000)[0:4]) mod B, per conversation id."""
    conv_ids = np.asarray(conv_ids, dtype=np.uint64)
    if chacha_ref.IMPLEMENTED:
        return chacha_ref.bucket_prf(k_bkt, conv_ids, n_buckets)
    nonces = np.zeros((conv_ids.shape[0], 12), dtype=np.uint8)
    nonces[:, :8] = conv_ids.astype("<u8").view(np.uint8).reshape(-1, 8)
    words = chacha_np.chacha20_block_per_nonce(k_bkt, nonces)[:, :4].copy().view("<u4").reshape(-1)
    return (words % np.uint32(n_buckets)).astype(np.uint32)


def seal_seq(k_seq: bytes, conv_id: int, seq: int, nonce: bytes | None = None) -> bytes:
    """seq_enc (44 B) = nonce(12) || ChaCha20-Poly1305(K_seq, nonce, LE64(conv_id)||LE64(seq), aad)."""
    if aead_ref.IMPLEMENTED:
        return aead_ref.seal_seq(k_seq, conv_id, seq, nonce)
    nonce = os.urandom(12) if nonce is None else nonce  # public data (CONVENTIONS §3)
    return nonce + chacha_np.aead_seal(k_seq, nonce, _le64(conv_id) + _le64(seq), SEQ_AAD)


def open_seq(k_seq: bytes, blob: bytes) -> tuple[bool, int, int]:
    """(ok, conv_id, seq). A bad tag or a wrong length gives (False, 0, 0), never an exception."""
    if aead_ref.IMPLEMENTED:
        return aead_ref.open_seq(k_seq, blob)
    pt = chacha_np.aead_open(k_seq, blob[:12], blob[12:], SEQ_AAD) if len(blob) == SEQ_ENC_LEN else None
    if pt is None:
        return False, 0, 0
    return True, int.from_bytes(pt[:8], "little"), int.from_bytes(pt[8:], "little")
