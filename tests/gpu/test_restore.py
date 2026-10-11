"""M05: the restore sort (R3) and the oblivious compaction (S8) on the M03 network (ai/TESTING.md §3, §4).

Every test with the `xp` fixture runs twice: on NumPy arrays (the simulator twins) and on CuPy arrays
(the CUDA kernels, marked `gpu`, on the runner only). The reference is the M01 oracle
(`read_window_ref`, `oblivious_compact_ref`, `epoch_permutation_ref`); equality is exact.
"""
from __future__ import annotations

import uuid
from typing import Any

import numpy as np
import pytest
from test_chacha import (
    SEEDS,
    SIZES,
    assert_same,
    dev,
    to_host,
    xp,  # noqa: F401 - the numpy / cupy fixture
)

from testkeys import TEST_K_MASTER
from vcloak.gpu.kernels import (
    SUBKEY_SEQ,
    SUBKEY_TAG,
    gpu_bitonic_sort,
    gpu_compact,
    gpu_derive_subkeys,
    gpu_open_and_key,
    gpu_restore_sort,
    gpu_tags_for_epoch,
    pack_seq_enc,
    subkey,
)
from vcloak.gpu.runtime import get_backend
from vcloak.oracle import crypto_hooks
from vcloak.oracle.reference import (
    RefKeys,
    StoredRow,
    dummy_row_ref,
    epoch_permutation_ref,
    oblivious_compact_ref,
    read_window_ref,
)

N_WINDOWS = 50
WINDOW_K = (1, 2, 3, 5, 8, 16, 31, 64, 100, 257)  # the candidate count K; most are not powers of two
LO_KINDS = ("random", "all_equal", "sorted", "reverse", "two_value")
DUMMY_KINDS = ("random", "none", "all", "alternate", "first_half", "one_real")
REF_KEYS = RefKeys.from_master(TEST_K_MASTER)


def entropy(rng: np.random.Generator) -> Any:
    """A deterministic stand-in for os.urandom (row ids, nonces and dummy filler are public)."""
    return lambda n: rng.integers(0, 256, n, dtype=np.uint8).tobytes()


def make_window(w: int) -> tuple[int, list[StoredRow]]:
    """Window w: K candidates of one bucket = rows of the conversation read, rows of other conversations
    that share the bucket, and dummies, in random order. Some windows repeat a seq (replayed row), so
    the slot tie-break is exercised; the counts cover no hit, all hits and everything between."""
    rng = np.random.default_rng([w, 77])
    ent = entropy(rng)
    k = WINDOW_K[w % len(WINDOW_K)]
    conv_id = int(rng.integers(0, 2**64, dtype=np.uint64))
    others = [int(v) for v in rng.integers(0, 2**64, 3, dtype=np.uint64)] + [conv_id ^ 1]
    n_hit = (0, k, k // 2, int(rng.integers(0, k + 1)))[w % 4]
    n_other = int(rng.integers(0, k - n_hit + 1))
    seqs = rng.integers(0, 2**64, n_hit, dtype=np.uint64) if w % 3 else rng.integers(0, 4, n_hit, dtype=np.uint64)
    rows = []
    sealed = [(conv_id, s) for s in seqs.tolist()]
    sealed += [(others[int(rng.integers(0, 4))], int(rng.integers(0, 9))) for _ in range(n_other)]
    for conv, s in sealed:
        seq_enc = crypto_hooks.seal_seq(REF_KEYS.k_seq, conv, s, ent(12))
        rows.append(StoredRow(uuid.UUID(bytes=ent(16), version=4), 5, w, seq_enc, ent(24)))
    rows += [dummy_row_ref(5, w, 24, ent) for _ in range(k - n_hit - n_other)]
    return conv_id, [rows[i] for i in rng.permutation(k).tolist()]


def device_read(xp: Any, kseq_dev: Any, conv_id: int, candidates: list[StoredRow]) -> list[bytes]:  # noqa: F811
    """R2 + R3 as the engine will run them: open on the device, restore sort, gather on the host."""
    blobs = xp.asarray(pack_seq_enc([r.seq_enc for r in candidates]))
    d_hi, d_lo, _ = gpu_open_and_key(kseq_dev, blobs, conv_id)
    perm, hits = gpu_restore_sort(d_hi, d_lo)
    return [candidates[i].payload for i in to_host(perm)[:hits].tolist()]


def lo_column(kind: str, n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng([seed, n, 3])
    if kind == "random":
        return rng.integers(0, 2**64, n, dtype=np.uint64)
    if kind == "all_equal":
        return np.full(n, 2**64 - 1, dtype=np.uint64)
    if kind == "sorted":
        return np.arange(n, dtype=np.uint64)
    if kind == "reverse":
        return (np.uint64(n) - np.arange(n, dtype=np.uint64)).astype(np.uint64)
    return rng.integers(0, 2, n, dtype=np.uint64) * np.uint64(2**63)


def dummy_column(kind: str, n: int, seed: int) -> np.ndarray:
    d = np.zeros(n, dtype=np.uint32)
    if kind == "random":
        d = np.random.default_rng([seed, n, 4]).integers(0, 2, n, dtype=np.uint32)
    elif kind == "all":
        d[:] = 1
    elif kind == "alternate":
        d[::2] = 1
    elif kind == "first_half":
        d[: n // 2] = 1
    elif kind == "one_real":
        d[:] = 1
        d[n - 1] = 0
    return d


def expected_restore(hi: np.ndarray, lo: np.ndarray) -> tuple[np.ndarray, int]:
    """The (hi, lo, index) order of the rows padded with misses to a power of two."""
    k = hi.shape[0]
    n = 1 << (k - 1).bit_length()
    p_hi, p_lo = np.ones(n, dtype=np.uint64), np.zeros(n, dtype=np.uint64)
    p_hi[:k], p_lo[:k] = hi, lo
    return np.lexsort((np.arange(n), p_lo, p_hi)).astype(np.uint32), int((hi == 0).sum())


def stable_partition(is_dummy: np.ndarray, order: np.ndarray) -> np.ndarray:
    return np.concatenate([order[is_dummy == 0], order[is_dummy != 0]])


# ── S3: restore sort (A4) ────────────────────────────────────────────────────


def test_windows_cover_the_cases() -> None:
    hits = []
    for w in range(N_WINDOWS):
        conv_id, cands = make_window(w)
        assert len(cands) == WINDOW_K[w % len(WINDOW_K)]
        hits.append(len(read_window_ref(REF_KEYS, conv_id, cands, len(cands))) / len(cands))
    assert min(hits) == 0 and max(hits) == 1 and any(0 < h < 1 for h in hits)


@pytest.mark.parametrize("w", range(N_WINDOWS))
def test_read_window_equals_oracle(xp: Any, w: int) -> None:  # noqa: F811
    kseq_dev = subkey(gpu_derive_subkeys(dev(xp, TEST_K_MASTER)), SUBKEY_SEQ)
    conv_id, cands = make_window(w)
    want = read_window_ref(REF_KEYS, conv_id, cands, len(cands))
    assert device_read(xp, kseq_dev, conv_id, cands) == want
    other = conv_id ^ 1  # the same candidates read for a conversation that shares the bucket
    assert device_read(xp, kseq_dev, other, cands) == read_window_ref(REF_KEYS, other, cands, len(cands))


@pytest.mark.parametrize("kind", LO_KINDS)
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("k", [*SIZES, 1, 3, 100, 1000, 5000])
def test_restore_sort_equals_lexicographic_order(xp: Any, k: int, seed: int, kind: str) -> None:  # noqa: F811
    hi = np.random.default_rng([seed, k, 2]).integers(0, 2, k, dtype=np.uint64)
    lo = lo_column(kind, k, seed)
    perm, hits = gpu_restore_sort(xp.asarray(hi), xp.asarray(lo))
    want_perm, want_hits = expected_restore(hi, lo)
    assert_same(perm, want_perm, f"restore k={k} seed={seed} {kind}")
    assert hits == want_hits


def test_restore_sort_leaves_its_inputs_alone(xp: Any) -> None:  # noqa: F811
    hi, lo = np.array([1, 0, 1, 0, 0], dtype=np.uint64), np.array([9, 7, 9, 2, 7], dtype=np.uint64)
    d_hi, d_lo = xp.asarray(hi), xp.asarray(lo)
    perm, hits = gpu_restore_sort(d_hi, d_lo)
    assert (to_host(perm)[:hits].tolist(), hits) == ([3, 1, 4], 3)
    assert_same(d_hi, hi, "hi after the sort")
    assert_same(d_lo, lo, "lo after the sort")


# ── S4: compaction ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", DUMMY_KINDS)
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n", SIZES)
def test_compact_equals_oracle(xp: Any, n: int, seed: int, kind: str) -> None:  # noqa: F811
    is_dummy = dummy_column(kind, n, seed)
    order = np.random.default_rng([seed, n, 6]).permutation(n).astype(np.uint32)
    d_dummy, d_order = xp.asarray(is_dummy), xp.asarray(order)
    got = gpu_compact(d_dummy, d_order)
    assert_same(got, oblivious_compact_ref(is_dummy, order), f"compact n={n} seed={seed} {kind}")
    assert_same(got, stable_partition(is_dummy, order), f"compact keeps the order n={n} seed={seed} {kind}")
    assert_same(d_dummy, is_dummy, "is_dummy after the compaction")
    assert_same(d_order, order, "order after the compaction")


@pytest.mark.parametrize(("slots", "n_real"), [(64, 0), (64, 1), (64, 37), (64, 64), (1 << 10, 700), (1 << 16, 40000)])
@pytest.mark.parametrize("seed", SEEDS)
def test_write_path_order_equals_oracle(xp: Any, seed: int, slots: int, n_real: int) -> None:  # noqa: F811
    """S6-S8 on device buffers: tags from K_tag, permute, compact. The oracle's write path does the same."""
    ktag_dev = subkey(gpu_derive_subkeys(dev(xp, TEST_K_MASTER)), SUBKEY_TAG)
    d_hi, d_lo = gpu_tags_for_epoch(ktag_dev, seed, slots)
    slot, perm = xp.arange(slots, dtype=np.uint32), xp.arange(slots, dtype=np.uint32)
    gpu_bitonic_sort(d_hi, d_lo, slot, perm)
    want_perm = epoch_permutation_ref(REF_KEYS.k_tag, seed, slots)
    assert_same(perm, want_perm, f"permutation slots={slots} epoch={seed}")
    is_dummy = (perm >= np.uint32(n_real)).astype(np.uint32)  # n_real is public
    order = to_host(gpu_compact(is_dummy, perm))[:n_real]
    assert_same(order, oblivious_compact_ref(want_perm >= n_real, want_perm)[:n_real], f"order n_real={n_real}")
    assert sorted(order.tolist()) == list(range(n_real))


def test_rejects_bad_arguments() -> None:
    hi, lo = np.zeros(8, dtype=np.uint64), np.zeros(8, dtype=np.uint64)
    d, order = np.zeros(8, dtype=np.uint32), np.arange(8, dtype=np.uint32)
    with pytest.raises(TypeError, match="hi must be a uint64"):
        gpu_restore_sort(hi.astype(np.uint32), lo)
    with pytest.raises(ValueError, match="lo must be one-dimensional with 8"):
        gpu_restore_sort(hi, lo[:7].copy())
    with pytest.raises(ValueError, match="candidate rows"):
        gpu_restore_sort(hi[:0].copy(), lo[:0].copy())
    with pytest.raises(TypeError, match="is_dummy must be a uint32"):
        gpu_compact(d.astype(bool), order)
    with pytest.raises(ValueError, match="order must be one-dimensional with 8"):
        gpu_compact(d, order[:4].copy())
    with pytest.raises(ValueError, match="power of two"):
        gpu_compact(d[:6].copy(), order[:6].copy())


# ── runner only: simulator parity and the largest size ───────────────────────


@pytest.mark.gpu
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n", SIZES)
def test_gpu_equals_simulator(n: int, seed: int) -> None:
    cp = pytest.importorskip("cupy")
    hi = np.random.default_rng([seed, n, 2]).integers(0, 2, n, dtype=np.uint64)
    for kind in LO_KINDS:
        lo = lo_column(kind, n, seed)
        for k in (n, n - 1):  # a full power of two and a padded window
            got, hits = gpu_restore_sort(cp.asarray(hi[:k]), cp.asarray(lo[:k]))
            twin, twin_hits = gpu_restore_sort(hi[:k].copy(), lo[:k].copy())
            assert_same(got, twin, f"gpu vs twin restore k={k} seed={seed} {kind}")
            assert hits == twin_hits
    order = np.random.default_rng([seed, n, 6]).permutation(n).astype(np.uint32)
    for kind in DUMMY_KINDS:
        is_dummy = dummy_column(kind, n, seed)
        assert_same(gpu_compact(cp.asarray(is_dummy), cp.asarray(order)), gpu_compact(is_dummy, order),
                    f"gpu vs twin compact n={n} seed={seed} {kind}")


@pytest.mark.gpu
@pytest.mark.slow
@pytest.mark.parametrize("seed", SEEDS)
def test_max_log2n(seed: int) -> None:
    """n = 2^max_log2n of the device: both sorts against the host's stable order."""
    cp = pytest.importorskip("cupy")
    n = 1 << int(get_backend().device_info()["max_log2n"])
    rng = np.random.default_rng([seed, n, 8])
    hi, lo = rng.integers(0, 2, n, dtype=np.uint64), rng.integers(0, 1 << 20, n, dtype=np.uint64)  # many equal seqs
    perm, hits = gpu_restore_sort(cp.asarray(hi), cp.asarray(lo))
    want_perm, want_hits = expected_restore(hi, lo)
    assert_same(perm, want_perm, f"restore n={n} seed={seed}")
    assert hits == want_hits
    del perm
    is_dummy, order = rng.integers(0, 2, n, dtype=np.uint32), rng.permutation(n).astype(np.uint32)
    assert_same(gpu_compact(cp.asarray(is_dummy), cp.asarray(order)), stable_partition(is_dummy, order),
                f"compact n={n} seed={seed}")
