"""Pure-NumPy ChaCha20 (RFC 8439) with vectorised quarter-rounds, plus the Poly1305 and AEAD it needs.

This is the oracle's stand-in server crypto until M02 delivers `vcloak.crypto.*_ref` (ADR-003). It is a
correctness reference only: Python integers and NumPy arrays are not constant-time and it must never be
used in a production path.
"""
from __future__ import annotations

import secrets

import numpy as np

_SIGMA = np.frombuffer(b"expand 32-byte k", dtype="<u4")
_P1305 = (1 << 130) - 5
_R_CLAMP = 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
TAG_LEN = 16


def _rotl(x: np.ndarray, r: int) -> np.ndarray:
    return (x << np.uint32(r)) | (x >> np.uint32(32 - r))


def _quarter_round(s: np.ndarray, a: int, b: int, c: int, d: int) -> None:
    s[a] += s[b]
    s[d] = _rotl(s[d] ^ s[a], 16)
    s[c] += s[d]
    s[b] = _rotl(s[b] ^ s[c], 12)
    s[a] += s[b]
    s[d] = _rotl(s[d] ^ s[a], 8)
    s[c] += s[d]
    s[b] = _rotl(s[b] ^ s[c], 7)


def _core(init: np.ndarray) -> np.ndarray:
    """20 rounds over a (16, m) uint32 state, one column per block. Returns (m, 64) uint8."""
    s = init.copy()
    for _ in range(10):
        _quarter_round(s, 0, 4, 8, 12)
        _quarter_round(s, 1, 5, 9, 13)
        _quarter_round(s, 2, 6, 10, 14)
        _quarter_round(s, 3, 7, 11, 15)
        _quarter_round(s, 0, 5, 10, 15)
        _quarter_round(s, 1, 6, 11, 12)
        _quarter_round(s, 2, 7, 8, 13)
        _quarter_round(s, 3, 4, 9, 14)
    s += init
    return np.ascontiguousarray(s.T, dtype="<u4").view(np.uint8).reshape(-1, 64)


def _init_state(key: bytes, m: int) -> np.ndarray:
    if len(key) != 32:
        raise ValueError("ChaCha20 key must be 32 bytes")
    init = np.empty((16, m), dtype=np.uint32)
    init[0:4] = _SIGMA[:, None]
    init[4:12] = np.frombuffer(key, dtype="<u4")[:, None]
    return init


def chacha20_blocks(key: bytes, nonce: bytes, counter: int = 0, nblocks: int = 1) -> np.ndarray:
    """`nblocks` consecutive 64-byte blocks starting at block `counter`. Returns (nblocks, 64) uint8."""
    if len(nonce) != 12:
        raise ValueError("ChaCha20 nonce must be 12 bytes")
    if counter < 0 or counter + nblocks > 1 << 32:
        raise ValueError("ChaCha20 block counter out of range")
    init = _init_state(key, nblocks)
    init[12] = (counter + np.arange(nblocks, dtype=np.uint64)).astype(np.uint32)
    init[13:16] = np.frombuffer(nonce, dtype="<u4")[:, None]
    return _core(init)


def chacha20_block_per_nonce(key: bytes, nonces: np.ndarray, counter: int = 0) -> np.ndarray:
    """One block per nonce (the PRF use). `nonces` is (m, 12) uint8. Returns (m, 64) uint8."""
    nonces = np.ascontiguousarray(nonces, dtype=np.uint8)
    if nonces.ndim != 2 or nonces.shape[1] != 12:
        raise ValueError("nonces must have shape (m, 12)")
    init = _init_state(key, nonces.shape[0])
    init[12] = np.uint32(counter)
    init[13:16] = nonces.view("<u4").T
    return _core(init)


def chacha20_keystream(key: bytes, nonce: bytes, nbytes: int, counter: int = 0) -> np.ndarray:
    """The first `nbytes` keystream bytes from block `counter` on, as uint8."""
    return chacha20_blocks(key, nonce, counter, max(1, -(-nbytes // 64))).reshape(-1)[:nbytes]


def poly1305_mac(otk: bytes, msg: bytes) -> bytes:
    """RFC 8439 §2.5 one-time authenticator."""
    r = int.from_bytes(otk[:16], "little") & _R_CLAMP
    s = int.from_bytes(otk[16:32], "little")
    acc = 0
    for o in range(0, len(msg), 16):
        acc = (acc + int.from_bytes(msg[o:o + 16] + b"\x01", "little")) * r % _P1305
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _aead_tag(key: bytes, nonce: bytes, aad: bytes, ct: bytes) -> bytes:
    otk = chacha20_blocks(key, nonce, 0, 1).tobytes()[:32]
    mac_data = (aad + bytes(-len(aad) % 16) + ct + bytes(-len(ct) % 16)
                + len(aad).to_bytes(8, "little") + len(ct).to_bytes(8, "little"))
    return poly1305_mac(otk, mac_data)


def _xor_stream(key: bytes, nonce: bytes, data: bytes) -> bytes:
    ks = chacha20_keystream(key, nonce, len(data), counter=1)
    return (np.frombuffer(data, dtype=np.uint8) ^ ks).tobytes()


def aead_seal(key: bytes, nonce: bytes, pt: bytes, aad: bytes) -> bytes:
    """RFC 8439 §2.8 AEAD_CHACHA20_POLY1305: returns ciphertext || 16-byte tag."""
    ct = _xor_stream(key, nonce, pt)
    return ct + _aead_tag(key, nonce, aad, ct)


def aead_open(key: bytes, nonce: bytes, boxed: bytes, aad: bytes) -> bytes | None:
    """Returns the plaintext, or None when the tag does not verify (never raises on a bad tag)."""
    if len(boxed) < TAG_LEN:
        return None
    ct, tag = boxed[:-TAG_LEN], boxed[-TAG_LEN:]
    if not secrets.compare_digest(tag, _aead_tag(key, nonce, aad, ct)):
        return None
    return _xor_stream(key, nonce, ct)
