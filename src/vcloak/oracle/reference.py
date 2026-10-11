"""Reference bitonic network and write/read/re-shuffle paths (ported from seed/vcloak_oracle.py).

The comparator schedule depends on n only, so the access pattern is data-independent. Swaps are
arithmetic selects (`np.where`), the CPU analogue of the masked compare-exchange in kernels/bitonic.cu.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import numpy as np

from vcloak import config
from vcloak.oracle import crypto_hooks

Entropy = Callable[[int], bytes]  # n -> n random bytes; public values only (row ids, nonces, dummy filler)


@dataclass(frozen=True)
class RefKeys:
    """The three server subkeys. In production they exist in GPU memory only; here they are test keys."""

    k_tag: bytes = field(repr=False)
    k_seq: bytes = field(repr=False)
    k_bkt: bytes = field(repr=False)

    @classmethod
    def from_master(cls, k_master: bytes) -> RefKeys:
        return cls(*crypto_hooks.derive_subkeys(k_master))


@dataclass
class Submission:
    conv_id: int
    seq: int
    payload: bytes  # client ciphertext (opaque)


@dataclass
class StoredRow:
    row_id: uuid.UUID
    bucket: int
    win: int
    seq_enc: bytes
    payload: bytes


def _check_pow2(n: int) -> None:
    if n < 1 or n & (n - 1):
        raise ValueError(f"n must be a power of two, got {n}")


def bitonic_stages(n: int) -> Iterator[tuple[int, int]]:
    """The public (k, j) stage sequence: k = 2, 4, ..., n and j = k/2, k/4, ..., 1."""
    _check_pow2(n)
    k = 2
    while k <= n:
        j = k // 2
        while j >= 1:
            yield k, j
            j //= 2
        k *= 2


def bitonic_schedule(n: int) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Comparator schedule as (lo, hi, asc) index arrays per stage, in the seed's partner-XOR form."""
    idx = np.arange(n, dtype=np.int64)
    sched = []
    for k, j in bitonic_stages(n):
        part = idx ^ j
        m = part > idx
        lo, hi = idx[m], part[m]
        sched.append((lo, hi, (lo & k) == 0))
    return sched


def bitonic_pairs(n: int) -> Iterator[tuple[int, int, np.ndarray, np.ndarray, np.ndarray]]:
    """Yield (k, j, i, l, asc) per stage using the one-thread-per-pair indexing of ai/GPU_GUIDE.md §3:
    thread t in [0, n/2) handles i = (t / j) * 2j + (t % j), l = i + j, asc = ((i & k) == 0)."""
    t = np.arange(n // 2, dtype=np.int64)
    for k, j in bitonic_stages(n):
        i = (t // j) * 2 * j + (t % j)
        yield k, j, i, i + j, (i & k) == 0


def bitonic_sort(keys: list[np.ndarray], payload: list[np.ndarray] | None = None,
                 trace: list[bytes] | None = None) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Sort lexicographically by keys[0], keys[1], ... (SoA limbs). The last limb must make the keys
    unique (callers append the slot index). Returns (sorted keys, payload columns in the same order).
    If `trace` is given, a digest of each stage's accessed indices is appended to it."""
    n = keys[0].shape[0]
    cols = [k.copy() for k in keys] + [p.copy() for p in (payload or [])]
    nk = len(keys)
    for lo, hi, asc in bitonic_schedule(n):
        if trace is not None:
            trace.append(hashlib.sha256(lo.tobytes() + hi.tobytes()).digest())
        gt = np.zeros(lo.shape[0], dtype=bool)
        eq = np.ones(lo.shape[0], dtype=bool)
        for c in cols[:nk]:
            a, b = c[lo], c[hi]
            gt |= eq & (a > b)
            eq &= a == b
        swap = np.where(asc, gt, ~gt)  # select, no branch on data
        for c in cols:
            a, b = c[lo], c[hi]
            c[lo] = np.where(swap, b, a)
            c[hi] = np.where(swap, a, b)
    return cols[:nk], cols[nk:]


def _permutation(hi: np.ndarray, lo: np.ndarray) -> np.ndarray:
    slot = np.arange(hi.shape[0], dtype=np.uint32)
    _, (perm,) = bitonic_sort([hi, lo, slot], [slot])
    return perm


def epoch_permutation_ref(k_tag: bytes, epoch: int, slots: int) -> np.ndarray:
    """perm[p] = input slot stored at output position p for `epoch` (uint32, length `slots`)."""
    _check_pow2(slots)
    return _permutation(*crypto_hooks.tags_for_epoch(k_tag, epoch, slots))


def reshuffle_permutation_ref(k_tag: bytes, win: int, n: int) -> np.ndarray:
    """perm[p] = input position stored at output position p when window `win` is re-shuffled."""
    _check_pow2(n)
    return _permutation(*crypto_hooks.reshuffle_tags(k_tag, win, n))


def oblivious_compact_ref(is_dummy: np.ndarray, order_idx: np.ndarray) -> np.ndarray:
    """Sort-based oblivious compaction: real slots first, keeping their (already random) order."""
    n = is_dummy.shape[0]
    _, (out,) = bitonic_sort([is_dummy.astype(np.uint32), np.arange(n, dtype=np.uint32)], [order_idx])
    return out


def window_of(epoch: int, epoch_ms: int = config.EPOCH_MS, window_s: int = config.WINDOW_S) -> int:
    """The coarse visible round of an epoch (ADR-004)."""
    return (epoch * epoch_ms) // (1000 * window_s)


def write_epoch_ref(keys: RefKeys, epoch: int, batch: list[Submission], slots: int, *,
                    buckets: int = config.BUCKETS, window_s: int = config.WINDOW_S,
                    epoch_ms: int = config.EPOCH_MS, entropy: Entropy = os.urandom) -> list[StoredRow]:
    """Pad the batch to `slots`, permute it by the epoch tags, strip the dummies and seal each row.
    The order of the real rows depends on their slot tags only, so it is the same for any `slots`."""
    n_real = len(batch)
    if n_real > slots:
        raise ValueError(f"batch of {n_real} does not fit in {slots} slots")
    perm = epoch_permutation_ref(keys.k_tag, epoch, slots)
    order = oblivious_compact_ref(perm >= n_real, perm)[:n_real]
    bkt = crypto_hooks.bucket_prf(keys.k_bkt, np.array([s.conv_id for s in batch], dtype=np.uint64), buckets)
    win = window_of(epoch, epoch_ms, window_s)
    rows = []
    for i in order.tolist():
        sub = batch[i]
        row_id = uuid.UUID(bytes=entropy(16), version=4)
        seq_enc = crypto_hooks.seal_seq(keys.k_seq, sub.conv_id, sub.seq, entropy(12))
        rows.append(StoredRow(row_id, int(bkt[i]), win, seq_enc, sub.payload))
    return rows


def reshuffle_ref(keys: RefKeys, win: int, rows: list[StoredRow]) -> list[StoredRow]:
    """Rewrite one closed window in a fresh permutation (padded to a power of two, dummies stripped)."""
    if any(r.win != win for r in rows):
        raise ValueError("every row must belong to the window being re-shuffled")
    if not rows:
        return []
    n = 1 << (len(rows) - 1).bit_length()
    perm = reshuffle_permutation_ref(keys.k_tag, win, n)
    order = oblivious_compact_ref(perm >= len(rows), perm)[:len(rows)]
    return [rows[i] for i in order.tolist()]


def dummy_row_ref(bucket: int, win: int, payload_len: int, entropy: Entropy = os.urandom) -> StoredRow:
    """A candidate-set filler: its random seq_enc fails authentication, so the read path sees a miss."""
    return StoredRow(uuid.UUID(bytes=entropy(16), version=4), bucket, win,
                     entropy(crypto_hooks.SEQ_ENC_LEN), entropy(payload_len))


def read_window_ref(keys: RefKeys, conv_id: int, candidates: list[StoredRow], K: int) -> list[bytes]:
    """Open seq_enc of exactly K candidates, sort by (miss, seq, index) and return the hits' payloads
    in conversation order. Rows of other conversations and dummies are misses."""
    if len(candidates) != K:
        raise ValueError(f"expected exactly K={K} candidates, got {len(candidates)}")
    n = 1 << max(0, (K - 1).bit_length())
    miss = np.ones(n, dtype=np.uint32)
    seqk = np.zeros(n, dtype=np.uint64)
    for i, row in enumerate(candidates):
        ok, conv, seq = crypto_hooks.open_seq(keys.k_seq, row.seq_enc)
        hit = ok and conv == conv_id
        miss[i] = 0 if hit else 1
        seqk[i] = seq if hit else 0
    idx = np.arange(n, dtype=np.uint32)
    _, (perm,) = bitonic_sort([miss, seqk, idx], [idx])
    hits = int((miss == 0).sum())
    return [candidates[i].payload for i in perm[:hits].tolist()]
