"""ChaCha20 reference constructions (ai/ARCHITECTURE.md §5). Stub: implemented in M02 S1-S2.

`vcloak.oracle.crypto_hooks` calls these once IMPLEMENTED is True; until then it uses
`vcloak.oracle.chacha_np`, which follows the same byte formats.
"""
from __future__ import annotations

import numpy as np

IMPLEMENTED = False


def derive_subkeys(k_master: bytes) -> tuple[bytes, bytes, bytes]:
    """(K_tag, K_seq, K_bkt) from K_master."""
    raise NotImplementedError("vcloak.crypto.chacha_ref is implemented in M02")


def tags_for_epoch(k_tag: bytes, epoch: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    """(hi, lo) uint64 tag limbs for slots 0..n-1 of `epoch`."""
    raise NotImplementedError("vcloak.crypto.chacha_ref is implemented in M02")


def reshuffle_tags(k_tag: bytes, win: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    """(hi, lo) uint64 tag limbs for the re-shuffle of window `win`."""
    raise NotImplementedError("vcloak.crypto.chacha_ref is implemented in M02")


def bucket_prf(k_bkt: bytes, conv_ids: np.ndarray, n_buckets: int) -> np.ndarray:
    """Bucket id per conversation id."""
    raise NotImplementedError("vcloak.crypto.chacha_ref is implemented in M02")
