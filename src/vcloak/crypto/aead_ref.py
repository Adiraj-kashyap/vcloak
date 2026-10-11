"""seq_enc AEAD reference (ai/ARCHITECTURE.md §5). Stub: implemented in M02 S3.

`vcloak.oracle.crypto_hooks` calls these once IMPLEMENTED is True.
"""
from __future__ import annotations

IMPLEMENTED = False


def seal_seq(k_seq: bytes, conv_id: int, seq: int, nonce: bytes | None = None) -> bytes:
    """44-byte seq_enc; a random 96-bit nonce is drawn when `nonce` is None."""
    raise NotImplementedError("vcloak.crypto.aead_ref is implemented in M02")


def open_seq(k_seq: bytes, blob: bytes) -> tuple[bool, int, int]:
    """(ok, conv_id, seq); ok is False on a bad tag, never an exception."""
    raise NotImplementedError("vcloak.crypto.aead_ref is implemented in M02")
