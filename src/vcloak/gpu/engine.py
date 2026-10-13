"""The GPU engine (ai/ARCHITECTURE.md §2, §4): the only server component that uses the subkeys.

    write_epoch       S5-S9: pad to SLOTS, epoch tags, bitonic permute, oblivious compaction, seal, bucket
    reshuffle_window  S10:   a fresh permutation of one closed window
    read_window       R1-R4: open seq_enc of K candidates, restore sort, ordered payloads
    bucket_of         the bucket PRF for the storage layer

Every key use is a kernel launch on device buffers of the `DeviceKeyStore`. What crosses back to the
host is public at the database level: the stored order of the real rows, seq_enc ciphertexts, buckets,
and the positions of the hits of one read. Payloads never go to the device: they are gathered on the
host by the downloaded indices (ADR-006). All D2H goes through `GpuEngine._d2h`, which is never given
a key buffer (audit A3).

Transfers use pinned host buffers and one CUDA stream per engine; each call records per-stage CUDA
events (`last_timings`). Under the `numpy` backend the same steps run on the simulator twins and the
stage clock is the host clock: those numbers are never performance results (ai/GPU_RUNNER.md §3).

An engine is not thread-safe: use one engine per thread.
"""
from __future__ import annotations

import contextlib
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from itertools import repeat
from typing import Any

import numpy as np

from vcloak import config
from vcloak.gpu.kernels import (
    SEQ_ENC_LEN,
    TAGS_PER_BLOCK,
    gpu_bitonic_sort,
    gpu_bucket_prf,
    gpu_compact,
    gpu_open_and_key,
    gpu_reshuffle_tags,
    gpu_restore_sort,
    gpu_seal_seq,
    gpu_tags_for_epoch,
    pack_seq_enc,
)
from vcloak.gpu.keystore import DeviceKeyStore

Entropy = Callable[[int], bytes]  # n -> n random bytes; public values only (row ids, nonces, dummy filler)

UUID_LEN = 16
NONCE_LEN = 12
ROW_ENTROPY = UUID_LEN + NONCE_LEN  # per stored row: the uuid4 bytes, then the seq_enc nonce
STAGES = ("h2d", "tags", "sort", "compact", "d2h", "seal", "bucket", "open", "host")
TIMER_GPU = "cupy.cuda.Event"
TIMER_SIM = "time.perf_counter (numpy simulator: not a performance result)"


def row_ids(raw: np.ndarray) -> list[uuid.UUID]:
    """The uuid4 of every row of an (n, 16) uint8 matrix: equal to `uuid.UUID(bytes=row, version=4)`.

    The version and variant bits are set for all rows at once and the objects are filled through their two
    slots, because `UUID.__init__` once per row was most of the host stage of `write_epoch` (ISSUE-12)."""
    ids = np.array(raw, dtype=np.uint8)
    ids[:, 6] = (ids[:, 6] & 0x0F) | 0x40
    ids[:, 8] = (ids[:, 8] & 0x3F) | 0x80
    words = ids.view(">u8")
    new, put, unknown = object.__new__, object.__setattr__, uuid.SafeUUID.unknown
    out = []
    for hi, lo in zip(words[:, 0].tolist(), words[:, 1].tolist(), strict=True):
        u = new(uuid.UUID)
        put(u, "int", (hi << 64) | lo)
        put(u, "is_safe", unknown)
        out.append(u)
    return out


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


class _StageClock:
    """Consecutive marks on one stream: the time between two marks belongs to the stage named by the
    second, so the stages add up to the total. CUDA events on the device, the host clock on the simulator."""

    def __init__(self, cp: Any | None, stream: Any | None) -> None:
        self._cp, self._stream = cp, stream
        self._marks: list[Any] = [self._now()]
        self._names: list[str] = []

    def _now(self) -> Any:
        if self._cp is None:
            return time.perf_counter() * 1e3
        event = self._cp.cuda.Event()
        event.record(self._stream)
        return event

    def mark(self, stage: str) -> None:
        self._marks.append(self._now())
        self._names.append(stage)

    def _elapsed(self, a: Any, b: Any) -> float:
        return float(b - a) if self._cp is None else float(self._cp.cuda.get_elapsed_time(a, b))

    def finish(self) -> dict[str, float]:
        if self._cp is not None:
            self._marks[-1].synchronize()
        out = dict.fromkeys(STAGES, 0.0)
        for name, a, b in zip(self._names, self._marks[:-1], self._marks[1:], strict=True):
            out[name] += self._elapsed(a, b)
        out["total"] = self._elapsed(self._marks[0], self._marks[-1])
        return out


class GpuEngine:
    """See the module docstring. `entropy` is the test hook for the public random values: it is called
    once per `write_epoch` for ROW_ENTROPY * n_real bytes (row p of the output takes bytes
    [28p, 28p + 16) as its uuid4 and the next 12 as its seq_enc nonce) and once per `read_window`
    that has to pad, for 44 bytes per missing candidate."""

    def __init__(self, keys: DeviceKeyStore, slots: int = config.SLOTS, buckets: int = config.BUCKETS,
                 window_s: int = config.WINDOW_S, epoch_ms: int = config.EPOCH_MS, *,
                 entropy: Entropy = os.urandom) -> None:
        if slots < TAGS_PER_BLOCK or slots & (slots - 1):
            raise ValueError(f"slots must be a power of two >= {TAGS_PER_BLOCK}, got {slots}")
        if not 0 < buckets < 1 << 32:
            raise ValueError("buckets must be in [1, 2^32 - 1]")
        if window_s < 1 or epoch_ms < 1:
            raise ValueError("window_s and epoch_ms must be positive")
        self._keys = keys
        self.slots, self.buckets, self.window_s, self.epoch_ms = slots, buckets, window_s, epoch_ms
        self._entropy = entropy
        self._xp = keys.backend.xp
        self._cp = self._xp if keys.backend.is_gpu else None
        self._stream = self._cp.cuda.Stream(non_blocking=True) if self._cp is not None else None
        self._pin: dict[str, tuple[Any, int]] = {}
        self._timings: dict[str, float] = {**dict.fromkeys(STAGES, 0.0), "total": 0.0}

    # ── plumbing: stream, pinned transfers, stage clock ──────────────────────

    @property
    def timer(self) -> str:
        """What `last_timings` was measured with."""
        return TIMER_GPU if self._cp is not None else TIMER_SIM

    def last_timings(self) -> dict[str, float]:
        """Per-stage milliseconds of the last call, with every key of STAGES and `total`."""
        return dict(self._timings)

    def _on_stream(self) -> Any:
        return self._stream if self._stream is not None else contextlib.nullcontext()

    def _clock(self) -> _StageClock:
        return _StageClock(self._cp, self._stream)

    def _done(self, clock: _StageClock, result: Any) -> Any:
        self._timings = clock.finish()
        return result

    def _pinned(self, name: str, dtype: Any, count: int) -> np.ndarray:
        """A page-locked host array of `count` elements, reused between calls under `name`."""
        nbytes = count * np.dtype(dtype).itemsize
        mem, size = self._pin.get(name, (None, 0))
        if size < nbytes:
            mem, size = self._cp.cuda.alloc_pinned_memory(nbytes), nbytes
            self._pin[name] = (mem, size)
        return np.frombuffer(mem, dtype=dtype, count=count)

    def _h2d(self, name: str, host: np.ndarray) -> Any:
        """Upload a host array through the pinned buffer `name`."""
        if self._cp is None:
            return np.ascontiguousarray(host)
        staged = self._pinned(name, host.dtype, host.size)
        staged[:] = host
        dev = self._cp.empty(host.size, dtype=host.dtype)
        dev.set(staged, stream=self._stream)
        return dev

    def _d2h(self, name: str, dev: Any) -> np.ndarray:
        """Download a device array of public values into the pinned buffer `name`. The result is valid
        until the next download under the same name."""
        if self._cp is None:
            return dev
        return dev.get(stream=self._stream, out=self._pinned(name, dev.dtype, int(dev.size)))

    # ── shared steps ─────────────────────────────────────────────────────────

    def _real_order(self, hi: Any, lo: Any, n_real: int, clock: _StageClock) -> list[int]:
        """Permute slots 0..n-1 by their tags, move the dummies (slot index >= n_real) behind the real
        slots, and return the real slots in stored order. The launches depend on n only; n_real is
        public at the database level."""
        xp = self._xp
        n = int(hi.shape[0])
        slot, perm = xp.arange(n, dtype=np.uint32), xp.arange(n, dtype=np.uint32)
        gpu_bitonic_sort(hi, lo, slot, perm)
        clock.mark("sort")
        is_dummy = (perm >= np.uint32(n_real)).astype(np.uint32)
        order = gpu_compact(is_dummy, perm)
        clock.mark("compact")
        if n_real == 0:
            return []
        host = self._d2h("order", order[:n_real]).tolist()
        clock.mark("d2h")
        return host

    def window_of(self, epoch: int) -> int:
        """The coarse visible round of an epoch (ADR-004)."""
        return (epoch * self.epoch_ms) // (1000 * self.window_s)

    # ── the interface of ai/ARCHITECTURE.md §4 ───────────────────────────────

    def write_epoch(self, epoch: int, batch: list[Submission]) -> list[StoredRow]:
        """The rows of one epoch in stored order: permuted, dummies stripped, sealed, bucketed."""
        n_real = len(batch)
        if n_real > self.slots:
            raise ValueError(f"batch of {n_real} does not fit in {self.slots} slots")
        with self._on_stream():
            clock = self._clock()
            hi, lo = gpu_tags_for_epoch(self._keys.k_tag, epoch, self.slots)
            clock.mark("tags")
            order = self._real_order(hi, lo, n_real, clock)
            if n_real == 0:
                return self._done(clock, [])

            # host gather (ADR-006): the submissions in stored order
            subs = [batch[i] for i in order]
            conv = np.fromiter((s.conv_id for s in subs), dtype=np.uint64, count=n_real)
            seqs = np.fromiter((s.seq for s in subs), dtype=np.uint64, count=n_real)
            ent = self._entropy(ROW_ENTROPY * n_real)
            if len(ent) != ROW_ENTROPY * n_real:
                raise ValueError("the entropy source returned the wrong number of bytes")
            per_row = np.frombuffer(ent, dtype=np.uint8).reshape(n_real, ROW_ENTROPY)
            nonces = np.ascontiguousarray(per_row[:, UUID_LEN:]).view("<u4").reshape(-1).astype(np.uint32)
            clock.mark("host")

            d_conv, d_seqs = self._h2d("conv", conv), self._h2d("seq", seqs)
            d_nonces = self._h2d("nonce", nonces)
            clock.mark("h2d")
            d_blobs = gpu_seal_seq(self._keys.k_seq, d_conv, d_seqs, d_nonces)
            clock.mark("seal")
            d_bkt = gpu_bucket_prf(self._keys.k_bkt, d_conv, self.buckets)
            clock.mark("bucket")
            sealed = self._d2h("blobs", d_blobs).astype("<u4").tobytes()
            bkt = self._d2h("bkt", d_bkt).tolist()
            clock.mark("d2h")

            win = self.window_of(epoch)
            blobs = [sealed[i:i + SEQ_ENC_LEN] for i in range(0, SEQ_ENC_LEN * n_real, SEQ_ENC_LEN)]
            rows = list(map(StoredRow, row_ids(per_row[:, :UUID_LEN]), bkt, repeat(win), blobs,
                            [s.payload for s in subs]))
            clock.mark("host")
            return self._done(clock, rows)

    def reshuffle_window(self, win: int, rows: list[StoredRow]) -> list[StoredRow]:
        """The rows of one closed window in a fresh permutation (padded to a power of two, dummies stripped)."""
        if any(r.win != win for r in rows):
            raise ValueError("every row must belong to the window being re-shuffled")
        m = len(rows)
        n = 1 << max(0, (m - 1).bit_length())
        with self._on_stream():
            clock = self._clock()
            if m < 2:
                return self._done(clock, list(rows))
            # the tag of a slot does not depend on n: a window of two takes the first two of one block
            hi, lo = gpu_reshuffle_tags(self._keys.k_tag, win, max(n, TAGS_PER_BLOCK))
            hi, lo = hi[:n], lo[:n]
            clock.mark("tags")
            order = self._real_order(hi, lo, m, clock)
            out = [rows[i] for i in order]
            clock.mark("host")
            return self._done(clock, out)

    def bucket_of(self, conv_ids: np.ndarray) -> np.ndarray:
        """Bucket of each conversation id (uint64 array) as uint32."""
        conv = np.ascontiguousarray(conv_ids)
        if conv.dtype != np.uint64 or conv.ndim != 1:
            raise TypeError("conv_ids must be a one-dimensional uint64 array")
        with self._on_stream():
            clock = self._clock()
            if conv.size == 0:
                return self._done(clock, np.empty(0, dtype=np.uint32))
            d_conv = self._h2d("conv", conv)
            clock.mark("h2d")
            d_bkt = gpu_bucket_prf(self._keys.k_bkt, d_conv, self.buckets)
            clock.mark("bucket")
            out = self._d2h("bkt", d_bkt).copy()
            clock.mark("d2h")
            return self._done(clock, out)

    def read_window(self, conv_id: int, candidates: list[StoredRow], K: int) -> list[bytes]:  # noqa: N803
        """Payloads of the rows of `conv_id` among K candidates, in sequence order. Fewer than K
        candidates are padded with random seq_enc values, which fail authentication (misses). The
        number of hits is public at the database level."""
        if K < 1 or len(candidates) > K:
            raise ValueError(f"expected at most K={K} candidates (K >= 1), got {len(candidates)}")
        blobs = [r.seq_enc for r in candidates]
        pad = K - len(blobs)
        if pad:
            filler = self._entropy(SEQ_ENC_LEN * pad)
            blobs += [filler[SEQ_ENC_LEN * i:SEQ_ENC_LEN * (i + 1)] for i in range(pad)]
        words = pack_seq_enc(blobs)
        with self._on_stream():
            clock = self._clock()
            d_blobs = self._h2d("cand", words)
            clock.mark("h2d")
            hi, lo, _ok = gpu_open_and_key(self._keys.k_seq, d_blobs, conv_id)
            clock.mark("open")
            perm, hits = gpu_restore_sort(hi, lo)
            clock.mark("sort")
            idx: list[int] = []
            if hits:
                idx = self._d2h("perm", perm[:hits]).tolist()
                clock.mark("d2h")
            out = [candidates[i].payload for i in idx]
            clock.mark("host")
            return self._done(clock, out)
