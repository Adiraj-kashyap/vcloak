"""M06: the GPU engine against the M01 oracle (ai/modules/M06 S2-S3, audit A1; ai/TESTING.md §2b, §3).

`write_epoch`, `reshuffle_window`, `read_window` and `bucket_of` must give exactly what the oracle
gives for the same keys and the same public random bytes (row ids, nonces, dummy filler). Every test
with the `xp` fixture runs under the simulator twins (numpy) and on the CUDA kernels (cupy, marked
`gpu`); the `gpu` tests at the end compare the two engines with each other (simulator parity, G5).
"""
from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import numpy as np
import pytest
from test_chacha import (
    SEEDS,
    SIZES,
    conv_ids,
    xp,  # noqa: F401 - the numpy / cupy fixture
)
from test_restore import N_WINDOWS, make_window

from testkeys import TEST_K_MASTER, dev_keystore
from vcloak import config
from vcloak.crypto import chacha_ref
from vcloak.gpu.engine import ROW_ENTROPY, GpuEngine, StoredRow, Submission
from vcloak.gpu.runtime import get_backend
from vcloak.oracle import crypto_hooks
from vcloak.oracle import reference as ref

REF_KEYS = ref.RefKeys.from_master(TEST_K_MASTER)
EPOCHS = (0, 1, 299, 300, 1 << 32, (1 << 64) - 1)
CONV_KINDS = ("random", "all_equal", "sorted", "reverse", "two_value")
RESHUFFLE_M = (0, 1, 2, 3, 4, 5, 8, 63, 64, 65, 1000, 4096)
PAYLOAD_LEN = 24


class Tape:
    """Public random bytes served in order, whatever the chunking: the oracle asks for 16 and 12 bytes
    per row, the engine for all rows at once, and both read the same bytes for the same row."""

    def __init__(self, data: bytes) -> None:
        self.data, self.pos = data, 0

    def __call__(self, n: int) -> bytes:
        out = self.data[self.pos:self.pos + n]
        assert len(out) == n, "the tape is too short"
        self.pos += n
        return out


def backend_of(xp: Any) -> Any:  # noqa: F811
    return get_backend("numpy" if xp is np else "cupy")


def engine(xp: Any, slots: int = config.SLOTS, tape: bytes | None = None, **kwargs: int) -> GpuEngine:  # noqa: F811
    hooks = {"entropy": Tape(tape)} if tape is not None else {}
    return GpuEngine(dev_keystore(backend_of(xp)), slots, **kwargs, **hooks)


def rows_of(rows: list[Any]) -> list[tuple[Any, ...]]:
    """Engine rows and oracle rows as plain tuples (the two StoredRow classes are separate types)."""
    for r in rows:
        assert isinstance(r.row_id, uuid.UUID) and isinstance(r.seq_enc, bytes) and isinstance(r.payload, bytes)
        assert type(r.bucket) is int and type(r.win) is int
    return [dataclasses.astuple(r) for r in rows]


def to_engine(rows: list[ref.StoredRow]) -> list[StoredRow]:
    return [StoredRow(*dataclasses.astuple(r)) for r in rows]


def to_oracle(rows: list[StoredRow]) -> list[ref.StoredRow]:
    return [ref.StoredRow(*dataclasses.astuple(r)) for r in rows]


def make_batch(n: int, seed: int, kind: str = "random") -> list[Submission]:
    rng = np.random.default_rng([seed, n, 6])
    conv = conv_ids(kind, n, seed).tolist()
    seq = rng.integers(0, 2**64, n, dtype=np.uint64).tolist()
    pay = rng.integers(0, 256, (n, PAYLOAD_LEN), dtype=np.uint8)
    return [Submission(conv[i], seq[i], pay[i].tobytes()) for i in range(n)]


def tape_for(n_real: int, seed: int) -> bytes:
    return np.random.default_rng([seed, n_real, 9]).integers(0, 256, ROW_ENTROPY * n_real, dtype=np.uint8).tobytes()


def oracle_write(epoch: int, batch: list[Submission], slots: int, tape: bytes, **kwargs: int) -> list[ref.StoredRow]:
    subs = [ref.Submission(s.conv_id, s.seq, s.payload) for s in batch]
    return ref.write_epoch_ref(REF_KEYS, epoch, subs, slots, entropy=Tape(tape), **kwargs)


def check_write(xp: Any, epoch: int, batch: list[Submission], slots: int, seed: int, **kwargs: int) -> None:  # noqa: F811
    tape = tape_for(len(batch), seed)
    got = engine(xp, slots, tape, **kwargs).write_epoch(epoch, batch)
    want = oracle_write(epoch, batch, slots, tape, **kwargs)
    assert len(got) == len(batch)
    assert rows_of(got) == rows_of(want), f"write_epoch differs from the oracle: slots={slots} n_real={len(batch)}"


# ── S2: write_epoch (A1) ─────────────────────────────────────────────────────


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("slots", SIZES)
def test_write_epoch_equals_the_oracle(xp: Any, slots: int, seed: int) -> None:  # noqa: F811
    """A full epoch, a partly filled one and one real row, at the sizes of ai/TESTING.md §3."""
    for n_real in (slots, slots // 2 + 1, 1):
        check_write(xp, 1000 + seed, make_batch(n_real, seed), slots, seed)


@pytest.mark.parametrize("kind", CONV_KINDS)
def test_write_epoch_equals_the_oracle_on_adversarial_batches(xp: Any, kind: str) -> None:  # noqa: F811
    check_write(xp, 5, make_batch(700, 2, kind), 1 << 10, 2)


@pytest.mark.parametrize("epoch", EPOCHS)
def test_write_epoch_equals_the_oracle_for_any_epoch(xp: Any, epoch: int) -> None:  # noqa: F811
    check_write(xp, epoch, make_batch(40, 1), 64, 1)


@pytest.mark.parametrize(("buckets", "window_s", "epoch_ms"), [(1, 1, 200), (7, 10, 200), (64, 60, 200),
                                                               (1000, 300, 50), ((1 << 32) - 1, 60, 1000)])
def test_write_epoch_equals_the_oracle_for_any_public_parameters(xp: Any, buckets: int, window_s: int,  # noqa: F811
                                                                 epoch_ms: int) -> None:
    check_write(xp, 123456, make_batch(50, 3), 64, 3, buckets=buckets, window_s=window_s, epoch_ms=epoch_ms)


def test_the_stored_order_does_not_depend_on_slots(xp: Any) -> None:  # noqa: F811
    """The real rows are ordered by their slot tags only, so padding to more slots changes nothing."""
    batch, tape = make_batch(50, 1), tape_for(50, 1)
    out = [rows_of(engine(xp, slots, tape).write_epoch(9, batch)) for slots in (64, 256, 4096)]
    assert out[0] == out[1] == out[2]


def test_write_epoch_is_a_permutation_with_the_window_of_the_epoch(xp: Any) -> None:  # noqa: F811
    batch = make_batch(64, 2)
    eng = engine(xp, 64)  # os.urandom: no test hook
    rows = eng.write_epoch(900, batch)
    assert sorted(r.payload for r in rows) == sorted(s.payload for s in batch)
    assert [r.payload for r in rows] != [s.payload for s in batch], "the stored order is the arrival order"
    assert {r.win for r in rows} == {ref.window_of(900)} == {3}
    assert len({r.row_id for r in rows}) == 64 and len({r.seq_enc[:12] for r in rows}) == 64
    by_payload = {s.payload: s for s in batch}
    for r in rows:
        s = by_payload[r.payload]
        assert crypto_hooks.open_seq(REF_KEYS.k_seq, r.seq_enc) == (True, s.conv_id, s.seq)


# ── S3: reshuffle_window, bucket_of, read_window (A1) ────────────────────────


def window_rows(m: int, win: int) -> list[ref.StoredRow]:
    rng = np.random.default_rng([m, 11])
    ent = lambda n: rng.integers(0, 256, n, dtype=np.uint8).tobytes()  # noqa: E731
    return [ref.dummy_row_ref(int(rng.integers(0, 64)), win, PAYLOAD_LEN, ent) for _ in range(m)]


@pytest.mark.parametrize("m", RESHUFFLE_M)
def test_reshuffle_equals_the_oracle(xp: Any, m: int) -> None:  # noqa: F811
    for win in (0, 7, (1 << 64) - 1):
        rows = window_rows(m, win)
        got = engine(xp).reshuffle_window(win, to_engine(rows))
        assert rows_of(got) == rows_of(ref.reshuffle_ref(REF_KEYS, win, rows)), f"reshuffle m={m} win={win}"


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n", SIZES)
def test_bucket_of_equals_the_reference(xp: Any, n: int, seed: int) -> None:  # noqa: F811
    for kind in CONV_KINDS:
        conv = conv_ids(kind, n, seed)
        got = engine(xp, buckets=1000).bucket_of(conv)
        want = chacha_ref.bucket_prf(REF_KEYS.k_bkt, conv, 1000)
        assert got.dtype == np.uint32 and got.tobytes() == want.astype(np.uint32).tobytes(), f"{kind} n={n}"


def test_read_window_equals_the_oracle_for_50_windows(xp: Any) -> None:  # noqa: F811
    eng = engine(xp)
    hits = 0
    for w in range(N_WINDOWS):
        conv_id, cands = make_window(w)
        got = eng.read_window(conv_id, to_engine(cands), len(cands))
        assert got == ref.read_window_ref(REF_KEYS, conv_id, cands, len(cands)), f"window {w}"
        hits += len(got)
    assert hits > 0


def test_read_window_pads_to_k_with_misses(xp: Any) -> None:  # noqa: F811
    """Fewer than K candidates: the same answer as the oracle on the candidates plus dummy rows."""
    for w in range(0, N_WINDOWS, 3):
        conv_id, cands = make_window(w)
        k = 2 * len(cands) + 3
        filler = np.random.default_rng([w, 12]).integers(0, 256, 44 * (k - len(cands)), dtype=np.uint8).tobytes()
        got = engine(xp, tape=filler).read_window(conv_id, to_engine(cands), k)
        padded = cands + [ref.StoredRow(uuid.uuid4(), 5, w, filler[i:i + 44], b"") for i in range(0, len(filler), 44)]
        assert got == ref.read_window_ref(REF_KEYS, conv_id, padded, k), f"window {w}"
    assert engine(xp).read_window(1, [], 128) == []


def test_write_reshuffle_read_round_trip(xp: Any) -> None:  # noqa: F811
    """Three conversations written over several epochs of one window, the window re-shuffled, then each
    conversation read back from its bucket in sequence order."""
    eng = engine(xp, 64, buckets=4)
    rng = np.random.default_rng(13)
    convs = [int(c) for c in rng.integers(0, 2**64, 3, dtype=np.uint64)]
    sent: dict[int, list[bytes]] = {c: [] for c in convs}
    stored: list[StoredRow] = []
    for epoch in range(300, 306):  # window 1 with EPOCH_MS = 200 and WINDOW_S = 60
        batch = []
        for i in rng.permutation(30).tolist():
            c = convs[i % 3]
            payload = b"%020d|%03d" % (c, len(sent[c]))
            batch.append(Submission(c, len(sent[c]), payload))
            sent[c].append(payload)
        batch += [Submission(int(rng.integers(0, 2**64, dtype=np.uint64)), 0, b"other") for _ in range(20)]
        stored += eng.write_epoch(epoch, batch)
    assert {r.win for r in stored} == {1}
    for rows in (stored, eng.reshuffle_window(1, stored)):
        assert len(rows) == len(stored)
        buckets = eng.bucket_of(np.array(convs, dtype=np.uint64)).tolist()
        for c, b in zip(convs, buckets, strict=True):
            cands = [r for r in rows if r.bucket == b]
            assert len(cands) <= 512
            got = eng.read_window(c, cands, 512)
            assert got == sent[c], "a conversation must come back complete and in sequence order"
            assert got == ref.read_window_ref(REF_KEYS, c, to_oracle(cands), len(cands))


# ── simulator parity and the largest size (G5): on the runner only ───────────


@pytest.mark.gpu
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("slots", SIZES)
def test_gpu_engine_equals_the_simulator_engine(slots: int, seed: int) -> None:
    cp = pytest.importorskip("cupy")
    n_real = slots - slots // 4
    batch, tape = make_batch(n_real, seed), tape_for(n_real, seed)
    gpu, twin = engine(cp, slots, tape), engine(np, slots, tape)
    rows = gpu.write_epoch(40 + seed, batch)
    assert rows_of(rows) == rows_of(twin.write_epoch(40 + seed, batch)), "write_epoch: gpu vs twin"
    win = rows[0].win
    assert rows_of(gpu.reshuffle_window(win, rows)) == rows_of(twin.reshuffle_window(win, rows)), "reshuffle"
    conv = np.array([s.conv_id for s in batch], dtype=np.uint64)
    assert gpu.bucket_of(conv).tobytes() == twin.bucket_of(conv).tobytes(), "bucket_of: gpu vs twin"
    k = min(n_real, 1024)
    for s in batch[:3]:
        got = gpu.read_window(s.conv_id, rows[:k], k)
        assert got == twin.read_window(s.conv_id, rows[:k], k), "read_window: gpu vs twin"


@pytest.mark.gpu
@pytest.mark.slow
@pytest.mark.parametrize("seed", SEEDS)
def test_max_log2n(seed: int) -> None:
    """SLOTS = 2^max_log2n of the device with 1000 real rows, against the host's stable order."""
    cp = pytest.importorskip("cupy")
    slots = 1 << int(get_backend().device_info()["max_log2n"])
    n_real, epoch = 1000, 77 + seed
    batch, tape = make_batch(n_real, seed), tape_for(n_real, seed)
    got = engine(cp, slots, tape).write_epoch(epoch, batch)
    hi, lo = chacha_ref.tags_for_epoch(REF_KEYS.k_tag, epoch, slots)
    perm = np.lexsort((np.arange(slots), lo, hi))
    order = perm[perm < n_real].tolist()
    bkt = chacha_ref.bucket_prf(REF_KEYS.k_bkt, np.array([s.conv_id for s in batch], dtype=np.uint64), config.BUCKETS)
    ent = Tape(tape)
    want = []
    for i in order:
        row_id = uuid.UUID(bytes=ent(16), version=4)
        seq_enc = crypto_hooks.seal_seq(REF_KEYS.k_seq, batch[i].conv_id, batch[i].seq, ent(12))
        want.append((row_id, int(bkt[i]), ref.window_of(epoch), seq_enc, batch[i].payload))
    assert rows_of(got) == want, f"write_epoch at slots=2^{slots.bit_length() - 1} seed={seed}"
