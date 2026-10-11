"""Simulator registry: kernel name -> NumPy twin (ai/GPU_GUIDE.md §2).

Each CUDA kernel added to `kernels/` gets a NumPy function here (or registered from its own module)
that takes the same arguments and computes the same thread-indexed arithmetic over
`t = arange(nthreads)`. The twins give correctness on a GPU-less laptop; they say nothing about speed.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

_REGISTRY: dict[str, Callable[..., Any]] = {}


def register(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register `fn` as the NumPy twin of the CUDA kernel `name`."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name in _REGISTRY and _REGISTRY[name] is not fn:
            raise ValueError(f"simulator twin {name!r} is already registered")
        _REGISTRY[name] = fn
        return fn

    return deco


def get(name: str) -> Callable[..., Any]:
    """Return the NumPy twin of kernel `name`."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"no simulator twin registered for kernel {name!r}; known: {names()}") from None


def names() -> list[str]:
    """Registered kernel names, sorted."""
    return sorted(_REGISTRY)


@register("vector_add")
def vector_add(a: np.ndarray, b: np.ndarray, out: np.ndarray, n: int) -> None:
    """Twin of the M00 probe kernel: out[t] = a[t] + b[t] for thread ids t < n (uint32 wraparound)."""
    t = np.arange(n)
    out[t] = a[t] + b[t]


# ── bitonic network (kernels/common.cuh, kernels/bitonic.cu) ─────────────────
# The twins take the kernel's arguments plus the launch configuration (`grid` blocks of `block`
# threads), because blockIdx and blockDim are inputs of the thread-indexed arithmetic.

MAX_T = 256  # same constant as kernels/bitonic.cu


def _mask64(c: np.ndarray) -> np.ndarray:
    """mask64: all ones where c is non-zero, computed as 0 - (c != 0) in uint64 like the kernel."""
    return np.negative((c != 0).astype(np.uint64))


def _lex_gt3(hi_a: np.ndarray, lo_a: np.ndarray, slot_a: np.ndarray,
             hi_b: np.ndarray, lo_b: np.ndarray, slot_b: np.ndarray) -> np.ndarray:
    gt_hi = (hi_a > hi_b).astype(np.uint64)
    eq_hi = (hi_a == hi_b).astype(np.uint64)
    gt_lo = (lo_a > lo_b).astype(np.uint64)
    eq_lo = (lo_a == lo_b).astype(np.uint64)
    gt_slot = (slot_a > slot_b).astype(np.uint64)
    return _mask64(gt_hi | (eq_hi & (gt_lo | (eq_lo & gt_slot))))


def _cmp_exchange(hi: np.ndarray, lo: np.ndarray, slot: np.ndarray, pay: np.ndarray,
                  i: Any, l: Any, asc: np.ndarray) -> None:  # noqa: E741 - `l` is the kernel's name
    """cmp_exchange over a vector of pairs. `i` and `l` are index expressions into the four columns."""
    a_hi, b_hi = hi[i], hi[l]
    a_lo, b_lo = lo[i], lo[l]
    a_slot, b_slot = slot[i], slot[l]
    a_pay, b_pay = pay[i], pay[l]
    sw = ~(asc ^ _lex_gt3(a_hi, a_lo, a_slot, b_hi, b_lo, b_slot))
    sw32 = sw.astype(np.uint32)  # (u32)m: the low 32 bits of the mask
    for col, a, b, m in ((hi, a_hi, b_hi, sw), (lo, a_lo, b_lo, sw),
                         (slot, a_slot, b_slot, sw32), (pay, a_pay, b_pay, sw32)):
        d = (a ^ b) & m
        col[i] = a ^ d
        col[l] = b ^ d


@register("bitonic_pairs_global")
def bitonic_pairs_global(hi: np.ndarray, lo: np.ndarray, slot: np.ndarray, pay: np.ndarray,
                         k: int, j: int, npairs: int, *, grid: int, block: int) -> None:
    """Twin of the global stage: thread t owns the pair (i, i + j), i = t + (t & ~(j - 1))."""
    t = np.arange(grid * block, dtype=np.uint32)
    t = t[t < np.uint32(npairs)]
    i = t + (t & ~np.uint32(j - 1))
    l = i + np.uint32(j)  # noqa: E741
    asc = _mask64((i & np.uint32(k)) == 0)
    _cmp_exchange(hi, lo, slot, pay, i, l, asc)


def _tiles(cols: tuple[np.ndarray, ...], n: int, grid: int, block: int) -> tuple[list[np.ndarray], np.ndarray, int]:
    """The shared-memory load: one row of 2T records per block whose tile starts below n."""
    if block > MAX_T:
        raise ValueError(f"block size {block} exceeds MAX_T = {MAX_T}")
    base = np.arange(grid, dtype=np.uint32) * np.uint32(2 * block)
    base = base[base < np.uint32(n)]
    live = base.shape[0]
    return [c[: live * 2 * block].reshape(live, 2 * block).copy() for c in cols], base, live


def _tile_stage(s: list[np.ndarray], base: np.ndarray, k: int, j: int, block: int) -> None:
    t = np.arange(block, dtype=np.uint32)
    i = t + (t & ~np.uint32(j - 1))
    l = i + np.uint32(j)  # noqa: E741
    asc = _mask64(((base[:, None] + i[None, :]) & np.uint32(k)) == 0)
    _cmp_exchange(s[0], s[1], s[2], s[3], (slice(None), i), (slice(None), l), asc)


def _store(cols: tuple[np.ndarray, ...], s: list[np.ndarray], live: int, block: int) -> None:
    for c, sc in zip(cols, s, strict=True):
        c[: live * 2 * block] = sc.reshape(-1)


@register("bitonic_shared")
def bitonic_shared(hi: np.ndarray, lo: np.ndarray, slot: np.ndarray, pay: np.ndarray,
                   k: int, j_start: int, n: int, *, grid: int, block: int) -> None:
    """Twin of the shared stages of one k: j = j_start, j_start / 2, ..., 1 inside each tile of 2T."""
    cols = (hi, lo, slot, pay)
    s, base, live = _tiles(cols, n, grid, block)
    j = j_start
    while j > 0:
        _tile_stage(s, base, k, j, block)
        j >>= 1
    _store(cols, s, live, block)


@register("bitonic_shared_full")
def bitonic_shared_full(hi: np.ndarray, lo: np.ndarray, slot: np.ndarray, pay: np.ndarray,
                        n: int, *, grid: int, block: int) -> None:
    """Twin of the initial local sort: every stage with k <= 2T inside each tile."""
    cols = (hi, lo, slot, pay)
    s, base, live = _tiles(cols, n, grid, block)
    k = 2
    while k <= 2 * block:
        j = k >> 1
        while j > 0:
            _tile_stage(s, base, k, j, block)
            j >>= 1
        k <<= 1
    _store(cols, s, live, block)


# ── ChaCha20 (kernels/chacha20.cuh, chacha_tags.cu, prf.cu) ──────────────────
# The twins repeat the kernels' word arithmetic over a vector of thread ids. They are written from
# the kernel source, not from vcloak.crypto.chacha_ref, so that the tests compare two implementations.
# A simulator is for correctness on test keys only: NumPy is not constant-time (hard rule 4).

N_SUBKEYS = 3  # same constant as kernels/prf.cu
_CHACHA_SIGMA = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)
_CHACHA_QR = ((0, 4, 8, 12), (1, 5, 9, 13), (2, 6, 10, 14), (3, 7, 11, 15),
              (0, 5, 10, 15), (1, 6, 11, 12), (2, 7, 8, 13), (3, 4, 9, 14))
LABEL_WORDS = ((0x6F6C6376, 0x742D6B61, 0x00006761),  # the LABELS table of derive_subkeys: tag, seq, bkt
               (0x6F6C6376, 0x732D6B61, 0x00007165),
               (0x6F6C6376, 0x622D6B61, 0x0000746B))


def _threads(grid: int, block: int, limit: int) -> np.ndarray:
    """Thread ids of a launch that pass the kernel's `if (t >= limit) return;` guard."""
    t = np.arange(grid * block, dtype=np.uint32)
    return t[t < np.uint32(limit)]


def _rotl32(x: np.ndarray, r: int) -> np.ndarray:
    return (x << np.uint32(r)) | (x >> np.uint32(32 - r))


def _chacha_block(key: np.ndarray, ctr: Any, nonce: tuple[Any, Any, Any], m: int) -> np.ndarray:
    """chacha_block for m threads: (16, m) uint32, column t = the 16 output words of thread t.
    `ctr` and the three nonce words are scalars or per-thread vectors."""
    s = np.empty((16, m), dtype=np.uint32)
    for w in range(4):
        s[w] = np.uint32(_CHACHA_SIGMA[w])
    for w in range(8):
        s[4 + w] = key[w]
    s[12] = ctr
    for w in range(3):
        s[13 + w] = nonce[w]
    x = s.copy()
    for _ in range(10):
        for a, b, c, d in _CHACHA_QR:
            x[a] += x[b]
            x[d] = _rotl32(x[d] ^ x[a], 16)
            x[c] += x[d]
            x[b] = _rotl32(x[b] ^ x[c], 12)
            x[a] += x[b]
            x[d] = _rotl32(x[d] ^ x[a], 8)
            x[c] += x[d]
            x[b] = _rotl32(x[b] ^ x[c], 7)
    x += s
    return x


def _mod_public(w: np.ndarray, B: int) -> np.ndarray:  # noqa: N803 - B is the spec's name
    """mod_public of kernels/common.cuh: Barrett reduction of uint32 w by the public modulus B."""
    m = 0xFFFFFFFFFFFFFFFF // int(B)
    m_hi, m_lo = np.uint64(m >> 32), np.uint64(m & 0xFFFFFFFF)
    w64 = w.astype(np.uint64)
    q = (w64 * m_hi + ((w64 * m_lo) >> np.uint64(32))) >> np.uint64(32)
    r = w64 - q * np.uint64(B)
    r -= np.uint64(B) & _mask64(r >= np.uint64(B))
    return r.astype(np.uint32)


@register("chacha_blocks")
def chacha_blocks(key: np.ndarray, nonce: np.ndarray, out: np.ndarray, counter0: int, nblocks: int,
                  *, grid: int, block: int) -> None:
    """Twin of the raw block kernel: thread t writes block counter0 + t to out[16t .. 16t + 15]."""
    t = _threads(grid, block, nblocks)
    ks = _chacha_block(key, np.uint32(counter0) + t, (nonce[0], nonce[1], nonce[2]), t.shape[0])
    for w in range(16):
        out[np.uint32(16) * t + np.uint32(w)] = ks[w]


@register("chacha_tags")
def chacha_tags(key: np.ndarray, nonce_lo: int, nonce_hi: int, out_hi: np.ndarray, out_lo: np.ndarray,
                nblocks: int, *, grid: int, block: int) -> None:
    """Twin of the tag kernel: thread t owns block t = the (hi, lo) tags of slots 4t .. 4t + 3."""
    t = _threads(grid, block, nblocks)
    nonce = (np.uint32(int(nonce_lo) & 0xFFFFFFFF), np.uint32(int(nonce_lo) >> 32), np.uint32(nonce_hi))
    ks = _chacha_block(key, t, nonce, t.shape[0]).astype(np.uint64)
    for q in range(4):
        i = np.uint32(4) * t + np.uint32(q)
        out_hi[i] = ks[4 * q] | (ks[4 * q + 1] << np.uint64(32))
        out_lo[i] = ks[4 * q + 2] | (ks[4 * q + 3] << np.uint64(32))


@register("derive_subkeys")
def derive_subkeys(master: np.ndarray, out_keys: np.ndarray, *, grid: int, block: int) -> None:
    """Twin of the subkey kernel: thread t writes subkey t (tag, seq, bkt) to out_keys[8t .. 8t + 7]."""
    t = _threads(grid, block, N_SUBKEYS)
    labels = np.asarray(LABEL_WORDS, dtype=np.uint32).reshape(-1)
    nonce = tuple(labels[np.uint32(3) * t + np.uint32(w)] for w in range(3))
    ks = _chacha_block(master, np.uint32(0), nonce, t.shape[0])  # type: ignore[arg-type]
    for w in range(8):
        out_keys[np.uint32(8) * t + np.uint32(w)] = ks[w]


@register("bucket_prf")
def bucket_prf(kbkt: np.ndarray, conv_ids: np.ndarray, out_bucket: np.ndarray, n: int, B: int,  # noqa: N803
               *, grid: int, block: int) -> None:
    """Twin of the bucket kernel: one thread per conversation id, word 0 of its block reduced mod B."""
    t = _threads(grid, block, n)
    conv = conv_ids[t]
    nonce = ((conv & np.uint64(0xFFFFFFFF)).astype(np.uint32), (conv >> np.uint64(32)).astype(np.uint32),
             np.uint32(0))
    ks = _chacha_block(kbkt, np.uint32(0), nonce, t.shape[0])
    out_bucket[t] = _mod_public(ks[0], B)
