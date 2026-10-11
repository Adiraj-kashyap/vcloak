"""M01 S3: write / re-shuffle / read references and end-to-end restoration."""
from __future__ import annotations

import numpy as np
import pytest

from testkeys import TEST_K_MASTER
from vcloak.oracle import crypto_hooks
from vcloak.oracle.reference import (
    RefKeys,
    StoredRow,
    Submission,
    dummy_row_ref,
    epoch_permutation_ref,
    oblivious_compact_ref,
    read_window_ref,
    reshuffle_permutation_ref,
    reshuffle_ref,
    window_of,
    write_epoch_ref,
)

KEYS = RefKeys.from_master(TEST_K_MASTER)


def _batch(n: int, conv_base: int = 100) -> list[Submission]:
    return [Submission(conv_base + i % 5, i // 5, f"payload-{i}".encode()) for i in range(n)]


def test_keys_are_not_printed() -> None:
    assert KEYS.k_tag.hex() not in repr(KEYS) and "k_tag" not in repr(KEYS)


@pytest.mark.parametrize("n", [1, 2, 64, 1024])
def test_permutations_are_bijections(n: int) -> None:
    for perm in (epoch_permutation_ref(KEYS.k_tag, 3, n), reshuffle_permutation_ref(KEYS.k_tag, 3, n)):
        assert perm.dtype == np.uint32 and np.array_equal(np.sort(perm), np.arange(n))
    if n >= 64:
        assert not np.array_equal(epoch_permutation_ref(KEYS.k_tag, 3, n), reshuffle_permutation_ref(KEYS.k_tag, 3, n))
        assert not np.array_equal(epoch_permutation_ref(KEYS.k_tag, 3, n), epoch_permutation_ref(KEYS.k_tag, 4, n))


def test_permutation_orders_slots_by_tag() -> None:
    hi, lo = crypto_hooks.tags_for_epoch(KEYS.k_tag, 11, 256)
    perm = epoch_permutation_ref(KEYS.k_tag, 11, 256)
    assert np.array_equal(perm, np.lexsort((np.arange(256), lo, hi)))


def test_compaction_puts_real_slots_first_in_order() -> None:
    perm = epoch_permutation_ref(KEYS.k_tag, 2, 64)
    out = oblivious_compact_ref(perm >= 10, perm)
    assert out[:10].tolist() == [p for p in perm.tolist() if p < 10]
    assert sorted(out[10:].tolist()) == list(range(10, 64))


def test_write_epoch_permutes_and_strips_dummies() -> None:
    batch = _batch(23)
    rows = write_epoch_ref(KEYS, 5, batch, 64, entropy=np.random.default_rng(1).bytes)
    assert len(rows) == 23 and sorted(r.payload for r in rows) == sorted(s.payload for s in batch)
    assert [r.payload for r in rows] != [s.payload for s in batch]
    by_payload = {s.payload: s for s in batch}
    for r in rows:
        sub = by_payload[r.payload]
        assert crypto_hooks.open_seq(KEYS.k_seq, r.seq_enc) == (True, sub.conv_id, sub.seq)
        assert r.bucket == int(crypto_hooks.bucket_prf(KEYS.k_bkt, np.array([sub.conv_id]), 64)[0])
        assert r.win == 0 and len(r.seq_enc) == 44 and r.row_id.version == 4
    assert len({r.row_id for r in rows}) == 23 and len({r.seq_enc[:12] for r in rows}) == 23


def test_write_order_does_not_depend_on_padding() -> None:
    batch = _batch(40)
    orders = [[r.payload for r in write_epoch_ref(KEYS, 9, batch, slots)] for slots in (64, 256, 1024)]
    assert orders[0] == orders[1] == orders[2]


def test_write_epoch_is_deterministic_given_entropy_and_epoch_dependent() -> None:
    batch = _batch(30)
    a = write_epoch_ref(KEYS, 4, batch, 64, entropy=np.random.default_rng(7).bytes)
    b = write_epoch_ref(KEYS, 4, batch, 64, entropy=np.random.default_rng(7).bytes)
    c = write_epoch_ref(KEYS, 5, batch, 64, entropy=np.random.default_rng(7).bytes)
    assert a == b and [r.payload for r in a] != [r.payload for r in c]


def test_write_epoch_edge_cases() -> None:
    assert write_epoch_ref(KEYS, 0, [], 64) == []
    assert len(write_epoch_ref(KEYS, 0, _batch(64), 64)) == 64
    with pytest.raises(ValueError):
        write_epoch_ref(KEYS, 0, _batch(65), 64)
    with pytest.raises(ValueError):
        write_epoch_ref(KEYS, 0, _batch(3), 48)


def test_window_of_epoch() -> None:
    assert [window_of(e, 200, 60) for e in (0, 299, 300, 899, 900)] == [0, 0, 1, 2, 3]
    rows = write_epoch_ref(KEYS, 650, _batch(3), 64, window_s=60, epoch_ms=200)
    assert {r.win for r in rows} == {2}


@pytest.mark.parametrize("m", [1, 2, 3, 37, 64, 100])
def test_reshuffle_is_a_permutation_of_the_window(m: int) -> None:
    rows = [StoredRow(dummy_row_ref(0, 6, 4).row_id, i % 8, 6, bytes(44), f"p{i}".encode()) for i in range(m)]
    out = reshuffle_ref(KEYS, 6, rows)
    assert sorted(r.payload for r in out) == sorted(r.payload for r in rows)
    assert all(a is b for a, b in zip(sorted(out, key=id), sorted(rows, key=id), strict=True))
    if m >= 37:
        assert [r.payload for r in out] != [r.payload for r in rows]
        assert [r.payload for r in out] != [r.payload for r in reshuffle_ref(KEYS, 7, [_rewin(r, 7) for r in rows])]


def _rewin(row: StoredRow, win: int) -> StoredRow:
    return StoredRow(row.row_id, row.bucket, win, row.seq_enc, row.payload)


def test_reshuffle_edge_cases() -> None:
    assert reshuffle_ref(KEYS, 1, []) == []
    with pytest.raises(ValueError):
        reshuffle_ref(KEYS, 1, [dummy_row_ref(0, 2, 4)])


def test_read_window_orders_hits_and_ignores_misses() -> None:
    ent = np.random.default_rng(3).bytes
    mine = [StoredRow(dummy_row_ref(0, 0, 1, ent).row_id, 2, 0, crypto_hooks.seal_seq(KEYS.k_seq, 77, s, ent(12)),
                      f"m{s}".encode()) for s in (5, 0, 3, 1, 4, 2)]
    other = [StoredRow(dummy_row_ref(0, 0, 1, ent).row_id, 2, 0, crypto_hooks.seal_seq(KEYS.k_seq, 78, s, ent(12)),
                       f"o{s}".encode()) for s in range(4)]
    cands = mine[:3] + other + [dummy_row_ref(2, 0, 8, ent) for _ in range(3)] + mine[3:]
    assert read_window_ref(KEYS, 77, cands, 13) == [f"m{s}".encode() for s in range(6)]
    assert read_window_ref(KEYS, 78, cands, 13) == [f"o{s}".encode() for s in range(4)]
    assert read_window_ref(KEYS, 79, cands, 13) == []
    assert read_window_ref(KEYS, 77, [dummy_row_ref(2, 0, 8, ent) for _ in range(8)], 8) == []
    with pytest.raises(ValueError):
        read_window_ref(KEYS, 77, cands, 16)


@pytest.mark.parametrize("reshuffle", [False, True])
def test_round_trip_restoration_20_conversations(reshuffle: bool) -> None:
    """S3 check: every conversation is restored in order through write -> (re-shuffle) -> read."""
    rng = np.random.default_rng(2026)
    ent = rng.bytes
    n_conv, slots, buckets, cand_k, n_epochs = 20, 64, 16, 64, 900  # 900 epochs of 200 ms = 3 windows of 60 s
    conv_ids = [int(c) for c in rng.integers(0, 2**63, n_conv, dtype=np.uint64)]
    sent: dict[int, list[bytes]] = {c: [] for c in conv_ids}
    heap: list[StoredRow] = []
    for epoch in range(0, n_epochs, 7):
        batch = []
        for c in rng.choice(conv_ids, size=int(rng.integers(0, 9)), replace=True).tolist():
            payload = ent(48)  # stands in for the opaque client ciphertext
            batch.append(Submission(c, len(sent[c]), payload))
            sent[c].append(payload)
        heap += write_epoch_ref(KEYS, epoch, batch, slots, buckets=buckets, entropy=ent)
    wins = sorted({r.win for r in heap})
    assert wins == [0, 1, 2] and sum(len(v) for v in sent.values()) == len(heap) > 300
    if reshuffle:
        heap = [r for w in wins for r in reshuffle_ref(KEYS, w, [x for x in heap if x.win == w])]
    for c in conv_ids:
        bucket = int(crypto_hooks.bucket_prf(KEYS.k_bkt, np.array([c], dtype=np.uint64), buckets)[0])
        got: list[bytes] = []
        for w in wins:
            pool = [r for r in heap if r.bucket == bucket and r.win == w]
            assert len(pool) <= cand_k
            pool += [dummy_row_ref(bucket, w, 48, ent) for _ in range(cand_k - len(pool))]
            pool = [pool[i] for i in rng.permutation(cand_k).tolist()]  # fetch order must not matter
            got += read_window_ref(KEYS, c, pool, cand_k)
        assert got == sent[c]
