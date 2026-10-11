"""Client content crypto (ADR-003: the client side stays X25519 + HKDF-SHA256 + AES-256-GCM).

Two clients exchange X25519 prekeys, agree on K_content over a transcript both can compute, pad every
plaintext to exactly BLOCK bytes (`0x80` then zeros) and encrypt it with AES-256-GCM under a random
96-bit nonce. The server only ever sees the resulting payload: nonce(12) || ct(BLOCK) || tag(16).
"""
from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from vcloak.config import BLOCK

KEY_LEN = 32
PUBLIC_LEN = 32
NONCE_LEN = 12
TAG_LEN = 16
PAD_MARK = 0x80
PAYLOAD_LEN = NONCE_LEN + BLOCK + TAG_LEN
_INFO = b"vcloak-content-v1"


class ContentError(ValueError):
    """A payload failed authentication or is malformed."""


def generate_prekey() -> tuple[X25519PrivateKey, bytes]:
    """A fresh X25519 prekey: (private key object, 32-byte public key to publish)."""
    private = X25519PrivateKey.generate()
    return private, private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def transcript(public_a: bytes, public_b: bytes, context: bytes = b"") -> bytes:
    """The agreement transcript: both public keys in sorted order, then `context`. Either party computes the same."""
    if len(public_a) != PUBLIC_LEN or len(public_b) != PUBLIC_LEN:
        raise ValueError("X25519 public keys are 32 bytes")
    lo, hi = sorted((bytes(public_a), bytes(public_b)))
    return lo + hi + len(context).to_bytes(4, "little") + context


def derive_content_key(private: X25519PrivateKey, peer_public: bytes, transcript_bytes: bytes) -> bytes:
    """K_content = HKDF-SHA256(X25519(private, peer_public), info = label || transcript)."""
    shared = private.exchange(X25519PublicKey.from_public_bytes(peer_public))
    return HKDF(algorithm=hashes.SHA256(), length=KEY_LEN, salt=None, info=_INFO + transcript_bytes).derive(shared)


def pad(msg: bytes, block: int = BLOCK) -> bytes:
    """`msg || 0x80 || 00…` to exactly `block` bytes, so every plaintext has one length."""
    if len(msg) >= block:
        raise ValueError(f"message of {len(msg)} bytes does not fit a {block}-byte block")
    return msg + bytes([PAD_MARK]) + bytes(block - len(msg) - 1)


def unpad(padded: bytes, block: int = BLOCK) -> bytes:
    """Inverse of `pad`. Call it only on authenticated plaintext."""
    end = len(padded.rstrip(b"\0")) - 1
    if len(padded) != block or end < 0 or padded[end] != PAD_MARK:
        raise ContentError("bad padding")
    return padded[:end]


def encrypt_content(k_content: bytes, msg: bytes, aad: bytes = b"", block: int = BLOCK) -> bytes:
    """nonce(12) || AES-256-GCM(K_content, nonce, pad(msg), aad)."""
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(k_content).encrypt(nonce, pad(msg, block), aad)


def decrypt_content(k_content: bytes, payload: bytes, aad: bytes = b"", block: int = BLOCK) -> bytes:
    """The message inside `payload`; raises ContentError if it was tampered with or has the wrong size."""
    if len(payload) != NONCE_LEN + block + TAG_LEN:
        raise ContentError("payload has the wrong length")
    try:
        padded = AESGCM(k_content).decrypt(payload[:NONCE_LEN], payload[NONCE_LEN:], aad)
    except InvalidTag:
        raise ContentError("payload failed authentication") from None
    return unpad(padded, block)
