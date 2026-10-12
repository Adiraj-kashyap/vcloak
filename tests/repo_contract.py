"""The repository contract (M09 A4): one set of tests, run against SqliteRepo (tests/unit) and PgRepo
(tests/integration). A subclass only provides the `repo` fixture."""
from __future__ import annotations

import dataclasses
import random
import uuid
from typing import Any

import numpy as np
import pytest

from testkeys import dev_keystore
from vcloak.crypto.aead_ref import SEQ_ENC_LEN
from vcloak.gpu.engine import GpuEngine, StoredRow, Submission
from vcloak.gpu.runtime import get_backend
from vcloak.storage.repo import CandidateOverflow, RewriteMismatch
from vcloak.storage.reshuffle import ReshuffleError, reshuffle_window

PAYLOAD = 96  # short test payloads; the length is public


def make_rows(n: int, win: int, seed: int, buckets: int = 4, payload: int = PAYLOAD) -> list[StoredRow]:
    rng = random.Random(seed * 1_000_003 + win)
    return [StoredRow(uuid.UUID(bytes=rng.randbytes(16), version=4), rng.randrange(buckets), win,
                      rng.randbytes(SEQ_ENC_LEN), rng.randbytes(payload)) for _ in range(n)]


class SeededEngine:
    """Stands in for GpuEngine.reshuffle_window: a fixed permutation chosen by a seed."""

    def __init__(self, seed: int) -> None:
        self.seed = seed

    def reshuffle_window(self, win: int, rows: list[StoredRow]) -> list[StoredRow]:
        out = list(rows)
        random.Random(self.seed).shuffle(out)
        return out


class RepoContract:
    @pytest.fixture
    def repo(self) -> Any:
        raise NotImplementedError

    # -- insert / dump --------------------------------------------------------------------------
    def test_an_empty_store_dumps_nothing(self, repo: Any) -> None:
        assert repo.dump() == []
        assert repo.window_rows(0) == []

    def test_dump_is_the_insertion_order_of_each_window(self, repo: Any) -> None:
        epochs = [make_rows(20, 3, seed) for seed in range(4)]
        for rows in epochs:
            repo.insert_rows(rows)
        flat = [r for rows in epochs for r in rows]
        assert repo.dump() == flat
        assert repo.window_rows(3) == flat

    def test_dump_lists_one_window_after_the_other(self, repo: Any) -> None:
        a, b, c = make_rows(10, 7, 1), make_rows(10, 2, 2), make_rows(10, 7, 3)
        for rows in (a, b, c):
            repo.insert_rows(rows)
        assert repo.dump() == b + a + c
        assert repo.window_rows(7) == a + c
        assert repo.window_rows(5) == []

    def test_one_epoch_may_span_two_windows(self, repo: Any) -> None:
        rows = make_rows(6, 4, 1) + make_rows(6, 5, 1)
        mixed = [rows[i // 2 + 6 * (i % 2)] for i in range(12)]
        repo.insert_rows(mixed)
        assert repo.window_rows(4) == rows[:6]
        assert repo.window_rows(5) == rows[6:]

    def test_insert_rows_is_one_transaction(self, repo: Any) -> None:
        repo.insert_rows(make_rows(5, 1, 1))
        bad = make_rows(5, 1, 2)
        bad.append(dataclasses.replace(bad[0], payload=b"again"))  # the same row id twice
        with pytest.raises(Exception):  # noqa: B017 - the driver's integrity error, different per backend
            repo.insert_rows(bad)
        assert repo.dump() == make_rows(5, 1, 1)
        repo.insert_rows(make_rows(5, 9, 3))  # the repository still works after the failure
        assert len(repo.dump()) == 10

    def test_insert_accepts_the_numpy_integers_of_the_engine(self, repo: Any) -> None:
        rows = make_rows(4, 2, 1)
        repo.insert_rows([dataclasses.replace(r, bucket=np.uint32(r.bucket), win=np.int64(r.win)) for r in rows])
        assert repo.dump() == rows
        assert all(type(r.bucket) is int and type(r.win) is int for r in repo.dump())

    def test_insert_rejects_a_bad_row(self, repo: Any) -> None:
        row = make_rows(1, 1, 1)[0]
        for bad in (dataclasses.replace(row, seq_enc=row.seq_enc[:-1]), dataclasses.replace(row, win=-1),
                    dataclasses.replace(row, win=2**31 - 1)):
            with pytest.raises(ValueError):
                repo.insert_rows([bad])
        assert repo.dump() == []

    # -- fetch_candidates (A2) --------------------------------------------------------------------
    @pytest.mark.parametrize("k,n_real", [(k, n) for k in (1, 5, 16, 128) for n in (0, 1, 5) if n <= k])
    def test_fetch_candidates_returns_exactly_k_rows(self, repo: Any, k: int, n_real: int) -> None:
        real = [dataclasses.replace(r, bucket=2) for r in make_rows(n_real, 6, 1)]
        other = [dataclasses.replace(r, bucket=3) for r in make_rows(7, 6, 2)] + make_rows(7, 8, 3)
        repo.insert_rows(real + other)
        got = repo.fetch_candidates(2, 6, k)
        assert len(got) == k
        assert len({r.row_id for r in got}) == k
        assert all(r in got for r in real), "every real row of the bucket-window is a candidate"
        assert not any(r in got for r in other)
        for r in got:
            assert (r.bucket, r.win, len(r.seq_enc), len(r.payload)) == (2, 6, SEQ_ENC_LEN, PAYLOAD)
            assert isinstance(r.row_id, uuid.UUID) and r.row_id.version == 4

    def test_fetch_candidates_with_exactly_k_real_rows_has_no_dummy(self, repo: Any) -> None:
        real = [dataclasses.replace(r, bucket=1) for r in make_rows(16, 6, 1)]
        repo.insert_rows(real)
        got = repo.fetch_candidates(1, 6, 16)
        assert sorted(got, key=lambda r: r.row_id.bytes) == sorted(real, key=lambda r: r.row_id.bytes)

    def test_fetch_candidates_fails_when_the_bucket_window_exceeds_k(self, repo: Any) -> None:
        repo.insert_rows([dataclasses.replace(r, bucket=1) for r in make_rows(9, 6, 1)])
        with pytest.raises(CandidateOverflow):
            repo.fetch_candidates(1, 6, 8)
        assert len(repo.fetch_candidates(1, 6, 9)) == 9

    def test_dummy_payloads_take_the_length_of_the_real_rows(self, repo: Any) -> None:
        repo.insert_rows([dataclasses.replace(r, bucket=0) for r in make_rows(1, 6, 1, payload=333)])
        assert {len(r.payload) for r in repo.fetch_candidates(0, 6, 12)} == {333}

    def test_an_empty_bucket_window_is_padded_at_the_configured_length(self, repo: Any) -> None:
        got = repo.fetch_candidates(0, 99, 12)
        assert len(got) == 12 and {len(r.payload) for r in got} == {PAYLOAD}

    def test_fetch_candidates_order_is_random_and_dummies_are_fresh(self, repo: Any) -> None:
        real = [dataclasses.replace(r, bucket=1) for r in make_rows(8, 6, 1)]
        repo.insert_rows(real)
        fetches = [repo.fetch_candidates(1, 6, 32) for _ in range(12)]
        ids = {r.row_id for r in real}
        positions = {tuple(i for i, r in enumerate(f) if r.row_id in ids) for f in fetches}
        orders = {tuple(r.row_id for r in f if r.row_id in ids) for f in fetches}
        assert len(positions) > 1, "the real rows must not sit at fixed positions"
        assert len(orders) > 1, "the real rows must not come back in a fixed order"
        dummies = [r.row_id for f in fetches for r in f if r.row_id not in ids]
        assert len(set(dummies)) == len(dummies) == 12 * 24
        assert repo.dump() == real, "a read stores nothing"

    @pytest.mark.parametrize("k", [0, -1, True, 1.5])
    def test_fetch_candidates_rejects_a_bad_k(self, repo: Any, k: Any) -> None:
        with pytest.raises(ValueError):
            repo.fetch_candidates(0, 0, k)

    # -- rewrite_window (A3) ----------------------------------------------------------------------
    @pytest.mark.parametrize("n", [1, 2, 64, 257])
    def test_rewrite_window_stores_the_given_order(self, repo: Any, n: int) -> None:
        before, after = make_rows(13, 4, 9), make_rows(13, 6, 9)
        rows = make_rows(n, 5, 1)
        for part in (before, rows[:n // 2], after, rows[n // 2:]):
            repo.insert_rows(part)
        new = SeededEngine(n).reshuffle_window(5, rows)
        repo.rewrite_window(5, new)
        assert repo.window_rows(5) == new
        assert repo.dump() == before + new + after, "the other windows are untouched"

    def test_rewrite_window_twice(self, repo: Any) -> None:
        rows = make_rows(40, 5, 1)
        repo.insert_rows(rows)
        for seed in (1, 2, 3):
            new = SeededEngine(seed).reshuffle_window(5, rows)
            repo.rewrite_window(5, new)
            assert repo.window_rows(5) == new

    def test_rewrite_window_refuses_a_different_row_count(self, repo: Any) -> None:
        rows = make_rows(10, 5, 1)
        repo.insert_rows(rows)
        for bad in (rows[:-1], rows + make_rows(1, 5, 2), []):
            with pytest.raises(RewriteMismatch):
                repo.rewrite_window(5, bad)
            assert repo.dump() == rows
        with pytest.raises(RewriteMismatch):
            repo.rewrite_window(8, make_rows(3, 8, 1))  # a window that holds nothing
        assert repo.dump() == rows
        repo.rewrite_window(5, rows[::-1])  # and it still works afterwards
        assert repo.dump() == rows[::-1]

    def test_rewrite_window_refuses_rows_of_another_window(self, repo: Any) -> None:
        rows = make_rows(10, 5, 1)
        repo.insert_rows(rows)
        with pytest.raises(ValueError):
            repo.rewrite_window(5, rows[:-1] + make_rows(1, 6, 1))
        assert repo.dump() == rows

    def test_rewrite_of_an_empty_window_is_a_no_op(self, repo: Any) -> None:
        repo.rewrite_window(5, [])
        assert repo.dump() == []
        repo.insert_rows(make_rows(3, 5, 1))
        assert repo.dump() == make_rows(3, 5, 1)

    def test_rows_can_be_read_after_a_rewrite(self, repo: Any) -> None:
        rows = make_rows(50, 5, 1)
        repo.insert_rows(rows)
        repo.rewrite_window(5, rows[::-1])
        for b in range(4):
            real = [r for r in rows if r.bucket == b]
            got = repo.fetch_candidates(b, 5, 64)
            assert len(got) == 64 and all(r in got for r in real)

    # -- pending windows (ISSUE-22, ADR-016) ------------------------------------------------------
    def test_pending_windows_lists_the_marked_windows_in_order(self, repo: Any) -> None:
        assert repo.pending_windows() == []
        for win in (7, 2, 7, 5, 2):  # marking twice is one mark
            repo.mark_pending(win)
        assert repo.pending_windows() == [2, 5, 7]
        assert repo.dump() == [], "a mark stores no row"

    def test_a_rewrite_takes_its_window_off_the_pending_list(self, repo: Any) -> None:
        rows5, rows6 = make_rows(20, 5, 1), make_rows(20, 6, 1)
        for win, rows in ((5, rows5), (6, rows6)):
            repo.mark_pending(win)
            repo.insert_rows(rows)
        assert repo.pending_windows() == [5, 6], "storing rows does not clear a mark"
        repo.rewrite_window(5, rows5[::-1])
        assert repo.pending_windows() == [6]
        repo.rewrite_window(5, rows5)  # a window that is not listed can still be rewritten
        assert repo.pending_windows() == [6]

    def test_a_refused_rewrite_keeps_the_pending_mark(self, repo: Any) -> None:
        rows = make_rows(10, 5, 1)
        repo.mark_pending(5)
        repo.insert_rows(rows)
        with pytest.raises(RewriteMismatch):
            repo.rewrite_window(5, rows[:-1])
        assert repo.pending_windows() == [5] and repo.dump() == rows

    def test_a_mark_without_rows_is_cleared_by_the_re_shuffle(self, repo: Any) -> None:
        """The service was killed between the mark and the first rows of the window."""
        repo.mark_pending(9)
        assert reshuffle_window(repo, SeededEngine(1), 9) == 0
        assert repo.pending_windows() == [] and repo.dump() == []
        repo.insert_rows(make_rows(3, 9, 1))
        assert repo.dump() == make_rows(3, 9, 1)

    @pytest.mark.parametrize("win", [-1, 2**31 - 1, True, 1.5, "3"])
    def test_mark_pending_rejects_a_bad_window(self, repo: Any, win: Any) -> None:
        with pytest.raises(ValueError):
            repo.mark_pending(win)
        assert repo.pending_windows() == []

    # -- reshuffle.py -----------------------------------------------------------------------------
    def test_reshuffle_window_writes_the_order_of_the_engine(self, repo: Any) -> None:
        rows, other = make_rows(100, 5, 1), make_rows(10, 6, 1)
        repo.insert_rows(rows)
        repo.insert_rows(other)
        assert reshuffle_window(repo, SeededEngine(7), 5) == 100
        assert repo.window_rows(5) == SeededEngine(7).reshuffle_window(5, rows) != rows
        assert repo.window_rows(6) == other

    @pytest.mark.parametrize("fault", ["drop", "duplicate", "alter", "foreign"])
    def test_reshuffle_window_writes_nothing_unless_it_is_a_permutation(self, repo: Any, fault: str) -> None:
        rows = make_rows(20, 5, 1)
        repo.insert_rows(rows)

        class Broken:
            def reshuffle_window(self, win: int, got: list[StoredRow]) -> list[StoredRow]:
                out = got[::-1]
                if fault == "drop":
                    return out[:-1]
                if fault == "duplicate":
                    return out[:-1] + [out[0]]
                if fault == "alter":
                    return out[:-1] + [dataclasses.replace(out[-1], payload=bytes(PAYLOAD))]
                return out[:-1] + make_rows(1, 5, 99)

        with pytest.raises(ReshuffleError):
            reshuffle_window(repo, Broken(), 5)
        assert repo.dump() == rows

    def test_write_reshuffle_read_through_the_store(self, repo: Any) -> None:
        """Engine (thread-model backend, correctness only) -> store -> re-shuffle -> candidates -> engine."""
        k = 128
        eng = GpuEngine(dev_keystore(get_backend("numpy")), 64, buckets=4)
        rng = np.random.default_rng(13)
        convs = [int(c) for c in rng.integers(0, 2**64, 3, dtype=np.uint64)]
        sent: dict[int, list[bytes]] = {c: [] for c in convs}
        for epoch in range(300, 304):  # window 1 with EPOCH_MS = 200 and WINDOW_S = 60
            batch = []
            for i in rng.permutation(18).tolist():
                c = convs[i % 3]
                payload = (b"%020d|%03d" % (c, len(sent[c]))).ljust(PAYLOAD, b".")
                batch.append(Submission(c, len(sent[c]), payload))
                sent[c].append(payload)
            repo.insert_rows(eng.write_epoch(epoch, batch))
        stored = repo.window_rows(1)
        assert len(stored) == 72 and repo.dump() == stored
        buckets = eng.bucket_of(np.array(convs, dtype=np.uint64)).tolist()

        def read_all() -> None:
            for c, b in zip(convs, buckets, strict=True):
                assert eng.read_window(c, repo.fetch_candidates(b, 1, k), k) == sent[c]

        read_all()
        assert reshuffle_window(repo, eng, 1) == 72
        assert repo.window_rows(1) == eng.reshuffle_window(1, stored)
        assert repo.window_rows(1) != stored
        read_all()
