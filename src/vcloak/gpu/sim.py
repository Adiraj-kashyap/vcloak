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


# ── Poly1305 and the seq_enc AEAD (kernels/poly1305.cuh, poly1305.cu, aead_seq.cuh, aead_open.cu, aead_seal.cu) ──
# Limbs are rows of a (5, m) uint32 array, one column per thread. Like the ChaCha20 twins, these are
# written from the kernel source, not from a reference implementation.

SEQ_WORDS = 11  # same constants as kernels/aead_seq.cuh
SEQ_CT = 3
SEQ_TAG = 7
SEQ_AAD_WORDS = (0x6F6C6376, 0x732D6B61, 0x762D7165, 0x00000031)  # the AAD table of seq_tag
SEQ_LEN_WORDS = (13, 0, 16, 0)  # the LENS table of seq_tag
_POLY_LIMB = np.uint32(0x3FFFFFF)
_POLY_LIMB64 = np.uint64(0x3FFFFFF)
_POLY_HIBIT = np.uint32(0x1000000)
_POLY_CLAMP = (0x3FFFFFF, 0x3FFFF03, 0x3FFC0FF, 0x3F03FFF, 0x00FFFFF)


def _u32(x: Any) -> np.ndarray:
    return np.asarray(x, dtype=np.uint32)


def _limbs(w: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The 26-bit windows 0..3 of four little-endian words (uint32 shifts drop the high bits, as in C)."""
    w0, w1, w2, w3 = (_u32(x) for x in w)
    return (w0, (w0 >> np.uint32(26)) | (w1 << np.uint32(6)), (w1 >> np.uint32(20)) | (w2 << np.uint32(12)),
            (w2 >> np.uint32(14)) | (w3 << np.uint32(18)))


def _poly_init(key: Any, m: int) -> tuple[np.ndarray, np.ndarray]:
    """poly1305_init for m threads: (r, h) as (5, m) uint32; `key` holds at least the 4 words of r."""
    r = np.empty((5, m), dtype=np.uint32)
    for w, limb in enumerate((*_limbs(key[:4]), _u32(key[3]) >> np.uint32(8))):
        r[w] = limb & np.uint32(_POLY_CLAMP[w])
    return r, np.zeros((5, m), dtype=np.uint32)


def _poly_block(r: np.ndarray, h: np.ndarray, msg: Any, hibit: Any) -> None:
    """poly1305_block: h = (h + block) * r, partially reduced, in place."""
    r0, r1, r2, r3, r4 = (r[w].astype(np.uint64) for w in range(5))
    five = np.uint64(5)
    s1, s2, s3, s4 = r1 * five, r2 * five, r3 * five, r4 * five
    m0, m1, m2, m3 = _limbs(msg)
    h0 = (h[0] + (m0 & _POLY_LIMB)).astype(np.uint64)
    h1 = (h[1] + (m1 & _POLY_LIMB)).astype(np.uint64)
    h2 = (h[2] + (m2 & _POLY_LIMB)).astype(np.uint64)
    h3 = (h[3] + (m3 & _POLY_LIMB)).astype(np.uint64)
    h4 = (h[4] + ((_u32(msg[3]) >> np.uint32(8)) | np.uint32(hibit))).astype(np.uint64)
    d0 = h0 * r0 + h1 * s4 + h2 * s3 + h3 * s2 + h4 * s1
    d1 = h0 * r1 + h1 * r0 + h2 * s4 + h3 * s3 + h4 * s2
    d2 = h0 * r2 + h1 * r1 + h2 * r0 + h3 * s4 + h4 * s3
    d3 = h0 * r3 + h1 * r2 + h2 * r1 + h3 * r0 + h4 * s4
    d4 = h0 * r4 + h1 * r3 + h2 * r2 + h3 * r1 + h4 * r0
    sh = np.uint64(26)
    d1 = d1 + (d0 >> sh)
    d2 = d2 + (d1 >> sh)
    d3 = d3 + (d2 >> sh)
    d4 = d4 + (d3 >> sh)
    e0 = (d0 & _POLY_LIMB64) + (d4 >> sh) * five
    h[0] = (e0 & _POLY_LIMB64).astype(np.uint32)
    h[1] = ((d1 & _POLY_LIMB64) + (e0 >> sh)).astype(np.uint32)
    h[2] = (d2 & _POLY_LIMB64).astype(np.uint32)
    h[3] = (d3 & _POLY_LIMB64).astype(np.uint32)
    h[4] = (d4 & _POLY_LIMB64).astype(np.uint32)


def _load_le32(msg: np.ndarray, i: int) -> np.ndarray:
    """load_le32 for every thread: `msg` is (m, nbytes) uint8, i a public byte offset."""
    b = msg[:, i:i + 4].astype(np.uint32)
    return b[:, 0] | (b[:, 1] << np.uint32(8)) | (b[:, 2] << np.uint32(16)) | (b[:, 3] << np.uint32(24))


def _poly_bytes(r: np.ndarray, h: np.ndarray, msg: np.ndarray, nbytes: int, pad_byte: int, pad_hibit: int) -> None:
    """poly1305_bytes: `msg` is (m, nbytes) uint8 (or (1, nbytes), shared by every thread)."""
    full = nbytes // 16
    rem = nbytes - 16 * full
    for b in range(full):
        _poly_block(r, h, [_load_le32(msg, 16 * b + 4 * w) for w in range(4)], _POLY_HIBIT)
    if rem > 0:
        buf = np.zeros((msg.shape[0], 16), dtype=np.uint8)
        buf[:, :rem] = msg[:, 16 * full:]
        buf[:, rem] = pad_byte
        _poly_block(r, h, [_load_le32(buf, 4 * w) for w in range(4)], pad_hibit)


def _poly_finish(key: Any, h: np.ndarray) -> np.ndarray:
    """poly1305_finish: the tag as (4, m) uint32. key[4..7] are the words of s."""
    sh = np.uint32(26)
    h0, h1, h2, h3, h4 = (h[w].copy() for w in range(5))
    c = h1 >> sh
    h1 &= _POLY_LIMB
    h2 += c
    c = h2 >> sh
    h2 &= _POLY_LIMB
    h3 += c
    c = h3 >> sh
    h3 &= _POLY_LIMB
    h4 += c
    c = h4 >> sh
    h4 &= _POLY_LIMB
    h0 += c * np.uint32(5)
    c = h0 >> sh
    h0 &= _POLY_LIMB
    h1 += c
    g0 = h0 + np.uint32(5)
    c = g0 >> sh
    g0 &= _POLY_LIMB
    g1 = h1 + c
    c = g1 >> sh
    g1 &= _POLY_LIMB
    g2 = h2 + c
    c = g2 >> sh
    g2 &= _POLY_LIMB
    g3 = h3 + c
    c = g3 >> sh
    g3 &= _POLY_LIMB
    g4 = h4 + c - np.uint32(1 << 26)  # wraps below zero in uint32, like the kernel
    sel = (g4 >> np.uint32(31)) - np.uint32(1)
    h0 = (h0 & ~sel) | (g0 & sel)
    h1 = (h1 & ~sel) | (g1 & sel)
    h2 = (h2 & ~sel) | (g2 & sel)
    h3 = (h3 & ~sel) | (g3 & sel)
    h4 = (h4 & ~sel) | (g4 & sel)
    words = (h0 | (h1 << sh), (h1 >> np.uint32(6)) | (h2 << np.uint32(20)),
             (h2 >> np.uint32(12)) | (h3 << np.uint32(14)), (h3 >> np.uint32(18)) | (h4 << np.uint32(8)))
    tag = np.empty((4, h.shape[1]), dtype=np.uint32)
    f = np.zeros(h.shape[1], dtype=np.uint64)
    for w in range(4):
        f = words[w].astype(np.uint64) + _u32(key[4 + w]).astype(np.uint64) + (f >> np.uint64(32))
        tag[w] = f.astype(np.uint32)  # the low word
    return tag


def _seq_tag(otk: np.ndarray, ct: Any) -> np.ndarray:
    """seq_tag: the tag of the 4 ciphertext words of each thread under its one-time key block, (4, m) uint32."""
    r, h = _poly_init(otk, otk.shape[1])
    _poly_block(r, h, [np.uint32(w) for w in SEQ_AAD_WORDS], _POLY_HIBIT)
    _poly_block(r, h, ct, _POLY_HIBIT)
    _poly_block(r, h, [np.uint32(w) for w in SEQ_LEN_WORDS], _POLY_HIBIT)
    return _poly_finish(otk, h)


def _row_words(a: np.ndarray, per_row: int, t: np.ndarray, first: int, count: int) -> list[np.ndarray]:
    """a[per_row * t + first + w] for w < count: `count` word columns of the rows of the threads t."""
    return [a[np.uint32(per_row) * t + np.uint32(first + w)] for w in range(count)]


def _row_bytes(a: np.ndarray, nbytes: int, t: np.ndarray) -> np.ndarray:
    """The nbytes-byte message of each thread t as (m, nbytes) uint8."""
    if nbytes == 0:
        return np.empty((t.shape[0], 0), dtype=np.uint8)
    return a.reshape(-1, nbytes)[t]


@register("poly1305_mac")
def poly1305_mac(keys: np.ndarray, msgs: np.ndarray, out_tags: np.ndarray, nbytes: int, n: int,
                 *, grid: int, block: int) -> None:
    """Twin of the general Poly1305 kernel: thread t tags message t (nbytes bytes) under key words 8t .. 8t + 7."""
    t = _threads(grid, block, n)
    key = _row_words(keys, 8, t, 0, 8)
    r, h = _poly_init(key, t.shape[0])
    _poly_bytes(r, h, _row_bytes(msgs, nbytes, t), nbytes, 1, 0)
    tag = _poly_finish(key, h)
    for w in range(4):
        out_tags[np.uint32(4) * t + np.uint32(w)] = tag[w]


@register("aead_tag")
def aead_tag(key: np.ndarray, nonces: np.ndarray, aad: np.ndarray, boxes: np.ndarray, out_tags: np.ndarray,
             aad_nbytes: int, box_nbytes: int, n: int, *, grid: int, block: int) -> None:
    """Twin of the general AEAD-tag kernel: one shared aad, per-thread nonce and ciphertext."""
    t = _threads(grid, block, n)
    m = t.shape[0]
    otk = _chacha_block(key, np.uint32(0), tuple(_row_words(nonces, 3, t, 0, 3)), m)  # type: ignore[arg-type]
    r, h = _poly_init(otk, m)
    _poly_bytes(r, h, aad[:aad_nbytes].reshape(1, -1), aad_nbytes, 0, int(_POLY_HIBIT))
    _poly_bytes(r, h, _row_bytes(boxes, box_nbytes, t), box_nbytes, 0, int(_POLY_HIBIT))
    _poly_block(r, h, [np.uint32(aad_nbytes), np.uint32(0), np.uint32(box_nbytes), np.uint32(0)], _POLY_HIBIT)
    tag = _poly_finish(otk, h)
    for w in range(4):
        out_tags[np.uint32(4) * t + np.uint32(w)] = tag[w]


@register("aead_open_seq")
def aead_open_seq(kseq: np.ndarray, blobs: np.ndarray, n: int, q_conv: int, out_hi: np.ndarray,
                  out_lo: np.ndarray, out_ok: np.ndarray, *, grid: int, block: int) -> None:
    """Twin of the open kernel: per row, ok = tag verifies; hi = miss; lo = seq, zeroed on a miss."""
    t = _threads(grid, block, n)
    m = t.shape[0]
    nonce = tuple(_row_words(blobs, SEQ_WORDS, t, 0, 3))
    otk = _chacha_block(kseq, np.uint32(0), nonce, m)  # type: ignore[arg-type]
    ks = _chacha_block(kseq, np.uint32(1), nonce, m)  # type: ignore[arg-type]
    ct = _row_words(blobs, SEQ_WORDS, t, SEQ_CT, 4)
    tag = _seq_tag(otk, ct)
    diff = np.zeros(m, dtype=np.uint32)
    for w, stored in enumerate(_row_words(blobs, SEQ_WORDS, t, SEQ_TAG, 4)):
        diff |= tag[w] ^ stored
    ok = (diff == 0).astype(np.uint64)
    pt = [(ct[w] ^ ks[w]).astype(np.uint64) for w in range(4)]
    conv = pt[0] | (pt[1] << np.uint64(32))
    seq = pt[2] | (pt[3] << np.uint64(32))
    miss = (np.uint64(1) - ok) | (conv != np.uint64(q_conv)).astype(np.uint64)
    out_hi[t] = miss
    out_lo[t] = seq & ~_mask64(miss)
    out_ok[t] = ok.astype(np.uint32)


@register("aead_seal_seq")
def aead_seal_seq(kseq: np.ndarray, conv_ids: np.ndarray, seqs: np.ndarray, nonces: np.ndarray,
                  out_blobs: np.ndarray, n: int, *, grid: int, block: int) -> None:
    """Twin of the seal kernel: row t = nonce t || (LE64(conv) || LE64(seq)) xor keystream block 1 || tag."""
    t = _threads(grid, block, n)
    m = t.shape[0]
    nonce = tuple(_row_words(nonces, 3, t, 0, 3))
    otk = _chacha_block(kseq, np.uint32(0), nonce, m)  # type: ignore[arg-type]
    ks = _chacha_block(kseq, np.uint32(1), nonce, m)  # type: ignore[arg-type]
    conv, seq = conv_ids[t], seqs[t]
    lo32, sh = np.uint64(0xFFFFFFFF), np.uint64(32)
    ct = [(conv & lo32).astype(np.uint32) ^ ks[0], (conv >> sh).astype(np.uint32) ^ ks[1],
          (seq & lo32).astype(np.uint32) ^ ks[2], (seq >> sh).astype(np.uint32) ^ ks[3]]
    tag = _seq_tag(otk, ct)
    base = np.uint32(SEQ_WORDS) * t
    for w in range(3):
        out_blobs[base + np.uint32(w)] = nonce[w]
    for w in range(4):
        out_blobs[base + np.uint32(SEQ_CT + w)] = ct[w]
        out_blobs[base + np.uint32(SEQ_TAG + w)] = tag[w]
