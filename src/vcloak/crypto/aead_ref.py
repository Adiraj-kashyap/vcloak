"""seq_enc AEAD reference (ai/ARCHITECTURE.md §5, ADR-003): ChaCha20-Poly1305 through `cryptography`.

seq_enc (44 B) = nonce(12) || ChaCha20-Poly1305(K_seq, nonce, pt=LE64(conv_id)||LE64(seq), aad=b"vcloak-seq-v1").
The tag comparison happens inside OpenSSL; this module never looks at tag bytes.

Without `cryptography` the module still imports, with IMPLEMENTED False: `vcloak.oracle.crypto_hooks` then
keeps its pure-NumPy stand-in, which is tested byte-for-byte against this one.
"""
from __future__ import annotations

import os

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
except ImportError:  # pragma: no cover - exercised in a subprocess by test_oracle_imports_without_cryptography
    ChaCha20Poly1305 = None

IMPLEMENTED = ChaCha20Poly1305 is not None

SEQ_AAD = b"vcloak-seq-v1"
NONCE_LEN = 12
TAG_LEN = 16
SEQ_PT_LEN = 16
SEQ_ENC_LEN = NONCE_LEN + SEQ_PT_LEN + TAG_LEN  # 44


def aead_seal(key: bytes, nonce: bytes, pt: bytes, aad: bytes) -> bytes:
    """RFC 8439 §2.8 AEAD_CHACHA20_POLY1305: ciphertext || 16-byte tag."""
    return ChaCha20Poly1305(key).encrypt(nonce, pt, aad)


def aead_open(key: bytes, nonce: bytes, boxed: bytes, aad: bytes) -> bytes | None:
    """The plaintext, or None when the tag does not verify."""
    try:
        return ChaCha20Poly1305(key).decrypt(nonce, boxed, aad)
    except InvalidTag:
        return None


def seal_seq(k_seq: bytes, conv_id: int, seq: int, nonce: bytes | None = None) -> bytes:
    """44-byte seq_enc; a random 96-bit nonce is drawn when `nonce` is None (public data, CONVENTIONS §3)."""
    nonce = os.urandom(NONCE_LEN) if nonce is None else nonce
    if len(nonce) != NONCE_LEN:
        raise ValueError("seq_enc nonce must be 12 bytes")
    pt = int(conv_id).to_bytes(8, "little") + int(seq).to_bytes(8, "little")
    return nonce + aead_seal(k_seq, nonce, pt, SEQ_AAD)


def open_seq(k_seq: bytes, blob: bytes) -> tuple[bool, int, int]:
    """(ok, conv_id, seq). A bad tag or a wrong length gives (False, 0, 0), never an exception."""
    if len(blob) != SEQ_ENC_LEN:  # the length is public
        return False, 0, 0
    pt = aead_open(k_seq, blob[:NONCE_LEN], blob[NONCE_LEN:], SEQ_AAD)
    if pt is None:
        return False, 0, 0
    return True, int.from_bytes(pt[:8], "little"), int.from_bytes(pt[8:], "little")
