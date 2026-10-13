"""Host driver for the CUDA kernels (ai/GPU_GUIDE.md §2-§3).

M03, the bitonic sorting network: the launch sequence is a function of the public values n and T only
(`launch_plan`); the data never influences which kernel runs, with which grid, or how often.
M04, ChaCha20 tags, subkeys and bucket PRF: every key argument is a device buffer of 8 uint32 words;
no wrapper accepts key bytes (ADR-003, audit A4).
M05, Poly1305 and the seq_enc AEAD (seal, open), the restore sort and the oblivious compaction; the two
sorts are the M03 network on other key columns.

Device arrays (CuPy) run the kernels in `kernels/*.cu`; NumPy arrays run their twins in
`vcloak.gpu.sim` with the same launch configuration.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from vcloak.gpu import sim

KERNEL_DIR = Path(__file__).resolve().parents[3] / "kernels"
BITONIC_KERNELS = ("bitonic_pairs_global", "bitonic_shared", "bitonic_shared_full")
CHACHA_KERNELS = ("chacha_blocks", "chacha_tags")
PRF_KERNELS = ("derive_subkeys", "bucket_prf")
POLY_KERNELS = ("poly1305_mac", "aead_tag")
AEAD_KERNELS = ("aead_open_seq", "aead_seal_seq")
KERNEL_FILES = {**dict.fromkeys(BITONIC_KERNELS, "bitonic.cu"), **dict.fromkeys(CHACHA_KERNELS, "chacha_tags.cu"),
                **dict.fromkeys(PRF_KERNELS, "prf.cu"), **dict.fromkeys(POLY_KERNELS, "poly1305.cu"),
                "aead_open_seq": "aead_open.cu", "aead_seal_seq": "aead_seal.cu"}
DEFAULT_T = 256  # threads per block in the shared kernels; a tile is 2T records. Public.
GLOBAL_BLOCK = 256
COLUMN_DTYPES = (np.uint64, np.uint64, np.uint32, np.uint32)  # hi, lo, slot, pay


@dataclass(frozen=True)
class Launch:
    """One kernel launch. `stages` are the (k, j) network stages it performs, in order."""

    kernel: str
    grid: int
    block: int
    k: int
    j: int
    stages: tuple[tuple[int, int], ...]


def _check_pow2(name: str, v: int) -> None:
    if v < 1 or v & (v - 1):
        raise ValueError(f"{name} must be a power of two, got {v}")


def clamp_tile(n: int, T: int = DEFAULT_T) -> int:  # noqa: N803 - T is the spec's name
    """Threads per shared block for n records: T, clamped to n / 2 so one tile never exceeds the array."""
    _check_pow2("n", n)
    _check_pow2("T", T)
    if T > sim.MAX_T:
        raise ValueError(f"T must be <= {sim.MAX_T} (the shared arrays in kernels/bitonic.cu), got {T}")
    return max(1, min(T, n // 2))


def _global(n: int, k: int, j: int) -> Launch:
    npairs = n // 2
    block = min(GLOBAL_BLOCK, npairs)
    return Launch("bitonic_pairs_global", npairs // block, block, k, j, ((k, j),))


@lru_cache(maxsize=64)
def launch_plan(n: int, T: int = DEFAULT_T) -> tuple[Launch, ...]:  # noqa: N803
    """The launches that sort n records: a local sort of every tile (k <= 2T), then for each k > 2T one
    global launch per j > T and one shared launch for j = T, ..., 1. Depends only on n and T."""
    t = clamp_tile(n, T)
    if n < 2:
        return ()
    local = tuple((k, j) for k in _pow2_range(2, 2 * t) for j in _pow2_down(k // 2))
    plan = [Launch("bitonic_shared_full", n // (2 * t), t, 2 * t, t, local)]
    for k in _pow2_range(4 * t, n):
        plan += [_global(n, k, j) for j in _pow2_down(k // 2) if j > t]
        plan.append(Launch("bitonic_shared", n // (2 * t), t, k, t, tuple((k, j) for j in _pow2_down(t))))
    return tuple(plan)


def global_only_plan(n: int) -> tuple[Launch, ...]:
    """Every stage as a global launch (no shared memory). Used to test the global kernel on its own."""
    _check_pow2("n", n)
    return tuple(_global(n, k, j) for k in _pow2_range(2, n) for j in _pow2_down(k // 2))


def _pow2_range(lo: int, hi: int) -> list[int]:
    out = []
    while lo <= hi:
        out.append(lo)
        lo *= 2
    return out


def _pow2_down(hi: int) -> list[int]:
    out = []
    while hi >= 1:
        out.append(hi)
        hi //= 2
    return out


@lru_cache(maxsize=8)
def _module(filename: str) -> Any:
    import cupy as cp  # type: ignore[import-not-found]

    src = (KERNEL_DIR / filename).read_text(encoding="utf-8")
    return cp.RawModule(code=src, options=("-std=c++17", "-I" + str(KERNEL_DIR)))


def _check_columns(cols: tuple[Any, ...]) -> int:
    n = int(cols[0].shape[0])
    for name, c, dt in zip(("hi", "lo", "slot", "pay"), cols, COLUMN_DTYPES, strict=True):
        if c.ndim != 1 or int(c.shape[0]) != n:
            raise ValueError(f"column {name} must be one-dimensional with {n} elements, got shape {c.shape}")
        if c.dtype != dt:
            raise TypeError(f"column {name} must be {np.dtype(dt).name}, got {c.dtype}")
        if not c.flags.c_contiguous:
            raise ValueError(f"column {name} must be contiguous")
    _check_pow2("n", n)
    return n


_launch_hook: Callable[[int, Launch], None] | None = None


def set_launch_hook(hook: Callable[[int, Launch], None] | None) -> Callable[[int, Launch], None] | None:
    """Debug hook (M14 S5): `hook(n, launch)` is called for every bitonic launch the driver issues, before
    it is issued. Both arguments are public; the hook never sees a record. Returns the hook it replaces."""
    global _launch_hook
    previous, _launch_hook = _launch_hook, hook
    return previous


def run_launch(cols: tuple[Any, ...], launch: Launch) -> None:
    """Execute one launch in place: the CUDA kernel for device arrays, its NumPy twin for host arrays."""
    n = int(cols[0].shape[0])
    if _launch_hook is not None:
        _launch_hook(n, launch)
    if launch.kernel == "bitonic_pairs_global":
        scalars = (launch.k, launch.j, n // 2)
    elif launch.kernel == "bitonic_shared":
        scalars = (launch.k, launch.j, n)
    else:
        scalars = (n,)
    if isinstance(cols[0], np.ndarray):
        sim.get(launch.kernel)(*cols, *scalars, grid=launch.grid, block=launch.block)
    else:
        fn = _module(KERNEL_FILES[launch.kernel]).get_function(launch.kernel)
        fn((launch.grid,), (launch.block,), (*cols, *(np.uint32(s) for s in scalars)))


def gpu_bitonic_sort(d_hi: Any, d_lo: Any, d_slot: Any, d_pay: Any, *, T: int = DEFAULT_T) -> None:  # noqa: N803
    """Sort the records (hi, lo, slot, pay) in place by (hi, lo, slot); `pay` travels with its key.

    hi and lo are uint64, slot and pay uint32, all of the same power-of-two length. The slot column
    must make the keys unique. Device arrays are sorted on the GPU; NumPy arrays by the simulator.
    """
    cols = (d_hi, d_lo, d_slot, d_pay)
    n = _check_columns(cols)
    for launch in launch_plan(n, T):
        run_launch(cols, launch)


# ── ChaCha20: tags, subkeys, bucket PRF (kernels/chacha_tags.cu, kernels/prf.cu) ──

CHACHA_BLOCK = 256  # threads per block of the one-thread-per-item kernels. Public.
KEY_WORDS = 8
NONCE_WORDS = 3
TAGS_PER_BLOCK = 4  # a 64-byte block is four 16-byte (hi, lo) tags
N_SUBKEYS = sim.N_SUBKEYS
SUBKEY_TAG, SUBKEY_SEQ, SUBKEY_BKT = range(N_SUBKEYS)  # order of derive_subkeys' output
DOMAIN_EPOCH = 0x00000000  # nonce word 2: LE32 of the suffix 00000000 (ai/ARCHITECTURE.md §5)
DOMAIN_RESHUFFLE = 0x80000000  # LE32 of the suffix 00000080


def _xp(a: Any) -> Any:
    """The array module of `a`: numpy for host arrays, cupy for device arrays."""
    if isinstance(a, np.ndarray):
        return np
    import cupy as cp  # type: ignore[import-not-found]

    return cp


def _check_buffer(name: str, a: Any, dtype: Any, size: int | None = None) -> None:
    if isinstance(a, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} must be a device buffer, not host bytes (ADR-003)")
    if not hasattr(a, "dtype") or a.dtype != dtype:
        raise TypeError(f"{name} must be a {np.dtype(dtype).name} array, got {getattr(a, 'dtype', type(a).__name__)}")
    if a.ndim != 1 or (size is not None and int(a.shape[0]) != size):
        raise ValueError(f"{name} must be one-dimensional" + (f" with {size} elements" if size is not None else "")
                         + f", got shape {a.shape}")
    if not a.flags.c_contiguous:
        raise ValueError(f"{name} must be contiguous")


def _run_threads(kernel: str, nthreads: int, args: tuple[Any, ...]) -> None:
    """Launch `kernel` with at least `nthreads` threads: the CUDA kernel for device arrays, its NumPy
    twin for host arrays. The grid depends on the public thread count only."""
    block = min(CHACHA_BLOCK, nthreads)
    grid = -(-nthreads // block)
    if isinstance(args[0], np.ndarray):
        sim.get(kernel)(*args, grid=grid, block=block)
    else:
        _module(KERNEL_FILES[kernel]).get_function(kernel)((grid,), (block,), args)


def gpu_chacha_blocks(key_dev: Any, nonce_dev: Any, counter0: int, nblocks: int) -> Any:
    """`nblocks` ChaCha20 blocks from block `counter0` on, as 16 * nblocks little-endian uint32 words.

    `key_dev` holds the 8 key words and `nonce_dev` the 3 nonce words, on the device of the result.
    """
    _check_buffer("key_dev", key_dev, np.uint32, KEY_WORDS)
    _check_buffer("nonce_dev", nonce_dev, np.uint32, NONCE_WORDS)
    if nblocks < 1 or counter0 < 0 or counter0 + nblocks > 1 << 32:
        raise ValueError("ChaCha20 block counter out of range")
    out = _xp(key_dev).empty(16 * nblocks, dtype=np.uint32)
    _run_threads("chacha_blocks", nblocks, (key_dev, nonce_dev, out, np.uint32(counter0), np.uint32(nblocks)))
    return out


def gpu_tags(key_dev: Any, nonce64: int, domain: int, d_hi: Any, d_lo: Any) -> None:
    """Fill the tag columns in place: slot i gets the LE64 halves of keystream bytes [16i, 16i + 16) under
    nonce LE64(nonce64) || LE32(domain). The columns are uint64 with the same multiple-of-4 length."""
    _check_buffer("key_dev", key_dev, np.uint32, KEY_WORDS)
    _check_buffer("hi", d_hi, np.uint64)
    n = int(d_hi.shape[0])
    _check_buffer("lo", d_lo, np.uint64, n)
    if n < TAGS_PER_BLOCK or n % TAGS_PER_BLOCK or n > 1 << 31:
        raise ValueError(f"the number of slots must be a multiple of {TAGS_PER_BLOCK} in [4, 2^31], got {n}")
    if not 0 <= nonce64 < 1 << 64:
        raise ValueError("the epoch or window must fit in 64 bits")
    nblocks = n // TAGS_PER_BLOCK
    _run_threads("chacha_tags", nblocks,
                 (key_dev, np.uint64(nonce64), np.uint32(domain), d_hi, d_lo, np.uint32(nblocks)))


def _new_tags(key_dev: Any, nonce64: int, domain: int, n: int) -> tuple[Any, Any]:
    _check_buffer("key_dev", key_dev, np.uint32, KEY_WORDS)
    xp = _xp(key_dev)
    d_hi, d_lo = xp.empty(n, dtype=np.uint64), xp.empty(n, dtype=np.uint64)
    gpu_tags(key_dev, nonce64, domain, d_hi, d_lo)
    return d_hi, d_lo


def gpu_tags_for_epoch(ktag_dev: Any, epoch: int, n: int) -> tuple[Any, Any]:
    """(hi, lo) tag columns of slots 0..n-1 for `epoch` (the device counterpart of chacha_ref.tags_for_epoch)."""
    return _new_tags(ktag_dev, epoch, DOMAIN_EPOCH, n)


def gpu_reshuffle_tags(ktag_dev: Any, win: int, n: int) -> tuple[Any, Any]:
    """As `gpu_tags_for_epoch` for the re-shuffle of window `win` (domain-separated by the nonce suffix)."""
    return _new_tags(ktag_dev, win, DOMAIN_RESHUFFLE, n)


def gpu_derive_subkeys(master_dev: Any) -> Any:
    """Derive (K_tag, K_seq, K_bkt) from the master key on its device: 3 x 8 uint32 words in one buffer.
    Use `subkey(keys_dev, SUBKEY_TAG)` etc. to address one key; nothing is copied to the host."""
    _check_buffer("master_dev", master_dev, np.uint32, KEY_WORDS)
    out = _xp(master_dev).empty(N_SUBKEYS * KEY_WORDS, dtype=np.uint32)
    _run_threads("derive_subkeys", N_SUBKEYS, (master_dev, out))
    return out


def subkey(keys_dev: Any, index: int) -> Any:
    """The view of subkey `index` inside the buffer returned by `gpu_derive_subkeys`."""
    _check_buffer("keys_dev", keys_dev, np.uint32, N_SUBKEYS * KEY_WORDS)
    if not 0 <= index < N_SUBKEYS:
        raise ValueError(f"subkey index must be in [0, {N_SUBKEYS}), got {index}")
    return keys_dev[index * KEY_WORDS:(index + 1) * KEY_WORDS]


def gpu_bucket_prf(kbkt_dev: Any, conv_ids_dev: Any, n_buckets: int) -> Any:
    """Bucket of each conversation id (uint64 column) as uint32: the block PRF under K_bkt, mod `n_buckets`."""
    _check_buffer("kbkt_dev", kbkt_dev, np.uint32, KEY_WORDS)
    _check_buffer("conv_ids", conv_ids_dev, np.uint64)
    n = int(conv_ids_dev.shape[0])
    if not 0 < n_buckets < 1 << 32:
        raise ValueError("n_buckets must be in [1, 2^32 - 1]")
    if not 0 < n < 1 << 32:
        raise ValueError("the number of conversation ids must be in [1, 2^32 - 1]")
    out = _xp(kbkt_dev).empty(n, dtype=np.uint32)
    _run_threads("bucket_prf", n, (kbkt_dev, conv_ids_dev, out, np.uint32(n), np.uint32(n_buckets)))
    return out


# ── Poly1305, seq_enc AEAD, restore sort, compaction (kernels/poly1305.cu, aead_open.cu, aead_seal.cu) ──

SEQ_WORDS = sim.SEQ_WORDS  # a 44-byte seq_enc is 11 little-endian words: nonce(3) || ciphertext(4) || tag(4)
SEQ_ENC_LEN = 4 * SEQ_WORDS
TAG_WORDS = 4
MAX_ROWS = 1 << 28  # keeps every word index of a row below 2^32. Public.
MAX_MSG_BYTES = 1 << 16  # the general Poly1305 kernels are test surfaces; the service uses 16-byte rows


def pack_seq_enc(blobs: Any) -> np.ndarray:
    """Host: 44-byte seq_enc values (stored rows, public ciphertext) as the uint32 words the kernels read."""
    if any(len(b) != SEQ_ENC_LEN for b in blobs):
        raise ValueError(f"every seq_enc must be {SEQ_ENC_LEN} bytes")
    return np.frombuffer(b"".join(blobs), dtype="<u4").astype(np.uint32)


def unpack_seq_enc(words: Any) -> list[bytes]:
    """Host: the inverse of `pack_seq_enc` for a device or host word buffer (D2H of public ciphertext)."""
    host = words if isinstance(words, np.ndarray) else words.get()
    raw = host.astype("<u4").tobytes()
    return [raw[i:i + SEQ_ENC_LEN] for i in range(0, len(raw), SEQ_ENC_LEN)]


def _rows(name: str, a: Any, dtype: Any, per_row: int) -> int:
    _check_buffer(name, a, dtype)
    n, rest = divmod(int(a.shape[0]), per_row)
    if rest or not 0 < n <= MAX_ROWS:
        raise ValueError(f"{name} must hold {per_row} elements for each of 1 to 2^28 rows, got {int(a.shape[0])}")
    return n


def gpu_poly1305(keys_dev: Any, msgs_dev: Any, nbytes: int) -> Any:
    """Poly1305 tags (4 uint32 words each) of n messages of `nbytes` bytes: message t under the one-time
    key words keys[8t .. 8t + 7]. `msgs_dev` is the uint8 concatenation of the messages."""
    n = _rows("keys_dev", keys_dev, np.uint32, KEY_WORDS)
    if not 0 <= nbytes < MAX_MSG_BYTES:
        raise ValueError("the message length must be in [0, 2^16)")
    _check_buffer("msgs", msgs_dev, np.uint8, n * nbytes)
    out = _xp(keys_dev).empty(TAG_WORDS * n, dtype=np.uint32)
    _run_threads("poly1305_mac", n, (keys_dev, msgs_dev, out, np.uint32(nbytes), np.uint32(n)))
    return out


def gpu_aead_tag(key_dev: Any, nonces_dev: Any, aad_dev: Any, boxes_dev: Any, box_nbytes: int) -> Any:
    """RFC 8439 §2.8 tags (4 uint32 words each) of n ciphertexts of `box_nbytes` bytes: ciphertext t under
    (key, nonce words 3t .. 3t + 2), all with the same aad (uint8). The ciphertexts are a uint8 concatenation."""
    _check_buffer("key_dev", key_dev, np.uint32, KEY_WORDS)
    n = _rows("nonces", nonces_dev, np.uint32, NONCE_WORDS)
    _check_buffer("aad", aad_dev, np.uint8)
    aad_nbytes = int(aad_dev.shape[0])
    if not 0 <= box_nbytes < MAX_MSG_BYTES or aad_nbytes >= MAX_MSG_BYTES:
        raise ValueError("the aad and ciphertext lengths must be in [0, 2^16)")
    _check_buffer("boxes", boxes_dev, np.uint8, n * box_nbytes)
    out = _xp(key_dev).empty(TAG_WORDS * n, dtype=np.uint32)
    _run_threads("aead_tag", n, (key_dev, nonces_dev, aad_dev, boxes_dev, out, np.uint32(aad_nbytes),
                                 np.uint32(box_nbytes), np.uint32(n)))
    return out


def gpu_seal_seq(kseq_dev: Any, conv_ids_dev: Any, seqs_dev: Any, nonces_dev: Any) -> Any:
    """seq_enc of each (conv_id, seq) row under K_seq and the host-supplied nonce (3 uint32 words per row):
    11 uint32 words per row, the device counterpart of aead_ref.seal_seq."""
    _check_buffer("kseq_dev", kseq_dev, np.uint32, KEY_WORDS)
    n = _rows("conv_ids", conv_ids_dev, np.uint64, 1)
    _check_buffer("seqs", seqs_dev, np.uint64, n)
    _check_buffer("nonces", nonces_dev, np.uint32, NONCE_WORDS * n)
    out = _xp(kseq_dev).empty(SEQ_WORDS * n, dtype=np.uint32)
    _run_threads("aead_seal_seq", n, (kseq_dev, conv_ids_dev, seqs_dev, nonces_dev, out, np.uint32(n)))
    return out


def gpu_open_and_key(kseq_dev: Any, blobs_dev: Any, q_conv: int,
                     out: tuple[Any, Any, Any] | None = None) -> tuple[Any, Any, Any]:
    """Open every seq_enc row (11 uint32 words each) and return the restore-sort columns (hi, lo, ok):
    hi = 0 for an authentic row of conversation `q_conv` and 1 for a miss, lo = its seq (0 on a miss),
    ok = 1 where the tag verified. Nothing is copied to the host. `out` gives the three columns to
    write into (n rows each, on the device of the input) instead of new ones."""
    _check_buffer("kseq_dev", kseq_dev, np.uint32, KEY_WORDS)
    n = _rows("blobs", blobs_dev, np.uint32, SEQ_WORDS)
    if not 0 <= q_conv < 1 << 64:
        raise ValueError("the conversation id must fit in 64 bits")
    xp = _xp(kseq_dev)
    if out is None:
        d_hi, d_lo, d_ok = xp.empty(n, dtype=np.uint64), xp.empty(n, dtype=np.uint64), xp.empty(n, dtype=np.uint32)
    else:
        d_hi, d_lo, d_ok = out
        _check_buffer("out hi", d_hi, np.uint64, n)
        _check_buffer("out lo", d_lo, np.uint64, n)
        _check_buffer("out ok", d_ok, np.uint32, n)
    _run_threads("aead_open_seq", n, (kseq_dev, blobs_dev, np.uint32(n), np.uint64(q_conv), d_hi, d_lo, d_ok))
    return d_hi, d_lo, d_ok


def gpu_restore_sort(d_hi: Any, d_lo: Any, *, T: int = DEFAULT_T) -> tuple[Any, int]:  # noqa: N803
    """Sort K candidate rows by (hi = miss, lo = seq, slot = row index) with the M03 network.

    Returns (perm, hits): perm[p] is the input row at output position p (uint32, on the device of the
    input) and the first `hits` positions are the conversation in sequence order. K need not be a power
    of two: the columns are padded with misses up to the next one, which is a function of K only. `hits`
    is the count j of matching rows, public at the database level (ai/modules/M05, presenter note 3).
    """
    _check_buffer("hi", d_hi, np.uint64)
    k = int(d_hi.shape[0])
    _check_buffer("lo", d_lo, np.uint64, k)
    if not 0 < k <= MAX_ROWS:
        raise ValueError("the number of candidate rows must be in [1, 2^28]")
    xp = _xp(d_hi)
    n = 1 << (k - 1).bit_length()
    s_hi, s_lo = xp.ones(n, dtype=np.uint64), xp.zeros(n, dtype=np.uint64)
    s_hi[:k] = d_hi
    s_lo[:k] = d_lo
    slot, perm = xp.arange(n, dtype=np.uint32), xp.arange(n, dtype=np.uint32)
    gpu_bitonic_sort(s_hi, s_lo, slot, perm, T=T)
    return perm, int(xp.count_nonzero(s_hi == 0))


def gpu_compact(d_is_dummy: Any, d_order: Any, *, T: int = DEFAULT_T) -> Any:  # noqa: N803
    """Oblivious compaction: sort by (is_dummy, current position, slot) with the M03 network and return
    the `order` column in the new arrangement. Real rows come first and keep their relative order.
    `d_is_dummy` (uint32, 0 or 1) and `d_order` (uint32) have the same power-of-two length; neither is modified."""
    _check_buffer("is_dummy", d_is_dummy, np.uint32)
    n = int(d_is_dummy.shape[0])
    _check_buffer("order", d_order, np.uint32, n)
    xp = _xp(d_is_dummy)
    hi, lo = d_is_dummy.astype(np.uint64), xp.arange(n, dtype=np.uint64)
    slot, pay = xp.arange(n, dtype=np.uint32), d_order.copy()
    gpu_bitonic_sort(hi, lo, slot, pay, T=T)
    return pay
