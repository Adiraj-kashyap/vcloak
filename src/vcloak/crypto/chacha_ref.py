"""ChaCha20 reference constructions (RFC 8439; byte formats of ai/ARCHITECTURE.md §5, ADR-003).

The block function is NumPy, vectorised over blocks, and is the CPU ground truth for the GPU kernels of
M04. It is validated against the RFC 8439 vectors and against `cryptography`'s ChaCha20 (tests/unit/
test_crypto_chacha.py). It is a correctness reference only: NumPy is not constant-time, so it must never
hold a production key.
"""
from __future__ import annotations

import numpy as np

IMPLEMENTED = True

KEY_LEN = 32
NONCE_LEN = 12
BLOCK_LEN = 64
TAG_BYTES = 16  # one (hi, lo) tag per slot
LABEL_TAG = b"vcloak-tag\0\0"
LABEL_SEQ = b"vcloak-seq\0\0"
LABEL_BKT = b"vcloak-bkt\0\0"
EPOCH_SUFFIX = bytes.fromhex("00000000")
RESHUFFLE_SUFFIX = bytes.fromhex("00000080")  # domain separation from epoch tags

_SIGMA = np.frombuffer(b"expand 32-byte k", dtype="<u4")
_QUARTER_ROUNDS = ((0, 4, 8, 12), (1, 5, 9, 13), (2, 6, 10, 14), (3, 7, 11, 15),
                   (0, 5, 10, 15), (1, 6, 11, 12), (2, 7, 8, 13), (3, 4, 9, 14))
_CHUNK_BLOCKS = 1 << 16  # keystream is produced 4 MiB at a time to bound the working set


def _rotl(x: np.ndarray, r: int) -> np.ndarray:
    return (x << np.uint32(r)) | (x >> np.uint32(32 - r))


def _rounds(init: np.ndarray) -> np.ndarray:
    """20 rounds plus the feed-forward over a (16, m) uint32 state, one column per block → (m, 64) uint8."""
    s = init.copy()
    for _ in range(10):
        for a, b, c, d in _QUARTER_ROUNDS:
            s[a] += s[b]
            s[d] = _rotl(s[d] ^ s[a], 16)
            s[c] += s[d]
            s[b] = _rotl(s[b] ^ s[c], 12)
            s[a] += s[b]
            s[d] = _rotl(s[d] ^ s[a], 8)
            s[c] += s[d]
            s[b] = _rotl(s[b] ^ s[c], 7)
    s += init
    return np.ascontiguousarray(s.T).astype("<u4", copy=False).view(np.uint8).reshape(-1, BLOCK_LEN)


def _state(key: bytes, m: int) -> np.ndarray:
    if len(key) != KEY_LEN:
        raise ValueError("ChaCha20 key must be 32 bytes")
    init = np.empty((16, m), dtype=np.uint32)
    init[0:4] = _SIGMA[:, None]
    init[4:12] = np.frombuffer(key, dtype="<u4")[:, None]
    return init


def block(key: bytes, nonce: bytes, counter: int = 0, nblocks: int = 1) -> np.ndarray:
    """`nblocks` consecutive 64-byte blocks from block `counter` on (RFC 8439 §2.3). Returns (nblocks, 64) uint8."""
    if len(nonce) != NONCE_LEN:
        raise ValueError("ChaCha20 nonce must be 12 bytes")
    if nblocks < 1 or counter < 0 or counter + nblocks > 1 << 32:
        raise ValueError("ChaCha20 block counter out of range")
    init = _state(key, nblocks)
    init[12] = (counter + np.arange(nblocks, dtype=np.uint64)).astype(np.uint32)
    init[13:16] = np.frombuffer(nonce, dtype="<u4")[:, None]
    return _rounds(init)


def block_per_nonce(key: bytes, nonces: np.ndarray, counter: int = 0) -> np.ndarray:
    """One block per nonce (the PRF use). `nonces` is (m, 12) uint8. Returns (m, 64) uint8."""
    nonces = np.ascontiguousarray(nonces, dtype=np.uint8)
    if nonces.ndim != 2 or nonces.shape[1] != NONCE_LEN:
        raise ValueError("nonces must have shape (m, 12)")
    init = _state(key, nonces.shape[0])
    init[12] = np.uint32(counter)
    init[13:16] = nonces.view("<u4").T
    return _rounds(init)


def keystream(key: bytes, nonce: bytes, nbytes: int, counter: int = 0) -> np.ndarray:
    """The first `nbytes` keystream bytes from block `counter` on (RFC 8439 §2.4), as uint8."""
    if nbytes < 0:
        raise ValueError("nbytes must be non-negative")
    nblocks = -(-nbytes // BLOCK_LEN)
    out = np.empty(nblocks * BLOCK_LEN, dtype=np.uint8)
    for start in range(0, nblocks, _CHUNK_BLOCKS):
        m = min(_CHUNK_BLOCKS, nblocks - start)
        out[start * BLOCK_LEN:(start + m) * BLOCK_LEN] = block(key, nonce, counter + start, m).reshape(-1)
    return out[:nbytes]


def _le64(x: int) -> bytes:
    return int(x).to_bytes(8, "little")


def _tags(k_tag: bytes, nonce: bytes, n: int) -> tuple[np.ndarray, np.ndarray]:
    limbs = keystream(k_tag, nonce, TAG_BYTES * n).view("<u8").reshape(n, 2)
    return limbs[:, 0].astype(np.uint64), limbs[:, 1].astype(np.uint64)


def derive_subkeys(k_master: bytes) -> tuple[bytes, bytes, bytes]:
    """(K_tag, K_seq, K_bkt): K_x = ChaCha20Block(K_master, counter=0, nonce=label_x)[0:32]."""
    k_tag, k_seq, k_bkt = (block(k_master, label)[0, :KEY_LEN].tobytes()
                           for label in (LABEL_TAG, LABEL_SEQ, LABEL_BKT))
    return k_tag, k_seq, k_bkt


def tags_for_epoch(k_tag: bytes, epoch: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    """(hi, lo) limbs for slots 0..n-1: LE64 halves of keystream bytes [16i, 16i+16), nonce LE64(epoch)||00000000."""
    return _tags(k_tag, _le64(epoch) + EPOCH_SUFFIX, n)


def reshuffle_tags(k_tag: bytes, win: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    """As `tags_for_epoch` for the re-shuffle of window `win`: nonce LE64(win)||00000080."""
    return _tags(k_tag, _le64(win) + RESHUFFLE_SUFFIX, n)


def bucket_prf(k_bkt: bytes, conv_ids: np.ndarray, n_buckets: int) -> np.ndarray:
    """LE32(ChaCha20Block(K_bkt, counter=0, nonce=LE64(conv_id)||00000000)[0:4]) mod B, per conversation id."""
    if not 0 < n_buckets <= 1 << 32:
        raise ValueError("n_buckets must be in [1, 2^32]")
    conv_ids = np.asarray(conv_ids, dtype=np.uint64).reshape(-1)
    nonces = np.zeros((conv_ids.shape[0], NONCE_LEN), dtype=np.uint8)
    nonces[:, :8] = conv_ids.astype("<u8").view(np.uint8).reshape(-1, 8)
    words = block_per_nonce(k_bkt, nonces)[:, :4].copy().view("<u4").reshape(-1)
    return (words.astype(np.uint64) % np.uint64(n_buckets)).astype(np.uint32)
