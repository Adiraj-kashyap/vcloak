"""M06: the device key store and the GPU engine (ai/modules/M06 S1-S4, audit A2-A4; ai/TESTING.md §2b, §3).

Every test with the `xp` fixture runs twice: under the simulator twins (numpy) and on the CUDA kernels
(cupy, marked `gpu`, on the runner only). The references are the M02 crypto and the M01 oracle; equality
is exact. The engine-against-oracle sweeps are in tests/integration/test_engine_vs_oracle.py.
"""
from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from test_chacha import (
    to_host,
    xp,  # noqa: F401 - the numpy / cupy fixture
)

from testkeys import TEST_K_MASTER, dev_keystore
from vcloak.crypto import chacha_ref
from vcloak.gpu import engine as engine_mod
from vcloak.gpu import keystore as keystore_mod
from vcloak.gpu.engine import ROW_ENTROPY, STAGES, TIMER_GPU, TIMER_SIM, GpuEngine, StoredRow, Submission
from vcloak.gpu.keystore import DeviceKeyStore, KeyStoreError
from vcloak.gpu.runtime import Backend, get_backend

WRITE_STAGES = ("h2d", "tags", "sort", "compact", "d2h", "seal", "bucket", "total")  # ai/modules/M06 S4


def backend_of(xp: Any) -> Backend:  # noqa: F811
    return get_backend("numpy" if xp is np else "cupy")


def key_words(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype="<u4").astype(np.uint32)


def batch_of(n: int, seed: int = 1) -> list[Submission]:
    rng = np.random.default_rng([seed, n])
    conv = rng.integers(0, 2**64, n, dtype=np.uint64).tolist()
    seq = rng.integers(0, 2**64, n, dtype=np.uint64).tolist()
    return [Submission(c, s, bytes([i % 251]) * 8) for i, (c, s) in enumerate(zip(conv, seq, strict=True))]


# ── S1: DeviceKeyStore (A2) ──────────────────────────────────────────────────


def test_load_master_zeroizes_the_host_buffer_and_derives_the_m02_subkeys(xp: Any) -> None:  # noqa: F811
    master = bytearray(TEST_K_MASTER)
    store = DeviceKeyStore(backend_of(xp))
    assert not store.ready
    store.load_master(master)
    assert master == bytearray(32), "the host master buffer must be all zeros after load_master"
    assert store.ready
    # reading a key buffer back is something only a test does (audit A3 forbids it in the engine)
    want = chacha_ref.derive_subkeys(TEST_K_MASTER)
    for name, got, ref in zip(("K_tag", "K_seq", "K_bkt"), (store.k_tag, store.k_seq, store.k_bkt), want, strict=True):
        assert to_host(got).tobytes() == key_words(ref).tobytes(), f"{name} differs from chacha_ref.derive_subkeys"
        assert isinstance(got, xp.ndarray), f"{name} must live on the device of the backend"


def test_zeroize_clears_the_device_buffer_and_empties_the_store(xp: Any) -> None:  # noqa: F811
    store = dev_keystore(backend_of(xp))
    held = store._subkeys  # the device buffer itself, to observe the memset
    assert int(xp.count_nonzero(held)) > 0
    store.zeroize()
    assert int(xp.count_nonzero(held)) == 0, "zeroize must overwrite the device key buffer"
    assert not store.ready
    with pytest.raises(KeyStoreError):
        _ = store.k_tag
    store.zeroize()  # idempotent


def test_reload_replaces_the_keys_and_clears_the_old_buffer(xp: Any) -> None:  # noqa: F811
    store = dev_keystore(backend_of(xp))
    old = store._subkeys
    other = bytes(range(32, 64))
    store.load_master(bytearray(other))
    assert int(xp.count_nonzero(old)) == 0
    assert to_host(store.k_seq).tobytes() == key_words(chacha_ref.derive_subkeys(other)[1]).tobytes()


@pytest.mark.parametrize("bad", [TEST_K_MASTER, memoryview(bytearray(32)), "x" * 32, None])
def test_load_master_refuses_anything_but_a_bytearray(bad: Any) -> None:
    with pytest.raises(TypeError):
        DeviceKeyStore(get_backend("numpy")).load_master(bad)


@pytest.mark.parametrize("n", [0, 16, 31, 33])
def test_load_master_refuses_a_wrong_length_and_leaves_the_store_empty(n: int) -> None:
    store = DeviceKeyStore(get_backend("numpy"))
    with pytest.raises(ValueError):
        store.load_master(bytearray(n))
    assert not store.ready


def test_the_host_buffer_is_zeroized_even_when_derivation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_: Any) -> Any:
        raise RuntimeError("derivation failed")

    monkeypatch.setattr(keystore_mod, "gpu_derive_subkeys", boom)
    master = bytearray(TEST_K_MASTER)
    store = DeviceKeyStore(get_backend("numpy"))
    with pytest.raises(RuntimeError):
        store.load_master(master)
    assert master == bytearray(32)
    assert not store.ready


def test_the_store_does_not_leak_through_repr_or_pickle() -> None:
    store = dev_keystore(get_backend("numpy"))
    text = repr(store) + str(store)
    for key in chacha_ref.derive_subkeys(TEST_K_MASTER):
        assert key.hex() not in text and str(key_words(key)[0]) not in text
    with pytest.raises(TypeError):
        pickle.dumps(store)


# ── A3: no key buffer is copied to the host by the engine or the key store ───


def _code(module: Any) -> str:
    """The module source without comments, docstrings and string literals."""
    src = Path(module.__file__).read_text(encoding="utf-8")
    src = re.sub(r'"""[\s\S]*?"""', '""', src)
    src = re.sub(r'"[^"\n]*"', '""', src)
    return re.sub(r"#[^\n]*", "", src)


HOST_COPIES = re.compile(r"\.get\(|asnumpy|\.tolist\(|\.tobytes\(|\.item\(|\.copy_to_host|pickle|print\(|logging")
KEY_NAMES = re.compile(r"k_tag|k_seq|k_bkt|_keys|_subkeys|master")


def test_a3_the_key_store_has_no_device_to_host_path() -> None:
    found = HOST_COPIES.findall(_code(keystore_mod))
    assert found == [], f"keystore.py must not copy anything back to the host, found {found}"


def test_a3_the_engine_downloads_only_through_d2h_and_never_a_key_buffer() -> None:
    code = _code(engine_mod)
    assert code.count(".get(") == 2, "one dict lookup in _pinned and one device download in _d2h"
    assert code.count("dev.get(stream=") == 1 and "asnumpy" not in code and "copy_to_host" not in code
    calls = re.findall(r"self\._d2h\(([^\n]*)", code)
    assert len(calls) >= 5
    for args in calls:
        assert not KEY_NAMES.search(args), f"_d2h is given a key buffer: {args}"
    uses = [line for line in code.splitlines() if "self._keys.k_" in line]
    assert len(uses) >= 5
    for line in uses:  # a key is only ever the first argument of a kernel wrapper
        assert re.search(r"= gpu_\w+\(self\._keys\.k_(tag|seq|bkt), ", line), line


# ── the engine: construction, limits, timings (S4, A4) ───────────────────────


@pytest.mark.parametrize("kwargs", [{"slots": 0}, {"slots": 2}, {"slots": 48}, {"buckets": 0}, {"buckets": 1 << 32},
                                    {"window_s": 0}, {"epoch_ms": 0}])
def test_the_constructor_checks_the_public_parameters(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        GpuEngine(dev_keystore(get_backend("numpy")), **kwargs)


def test_an_engine_without_keys_cannot_run() -> None:
    eng = GpuEngine(DeviceKeyStore(get_backend("numpy")), slots=64)
    with pytest.raises(KeyStoreError):
        eng.write_epoch(1, batch_of(3))


def test_a_batch_larger_than_slots_is_refused() -> None:
    eng = GpuEngine(dev_keystore(get_backend("numpy")), slots=8)
    with pytest.raises(ValueError):
        eng.write_epoch(1, batch_of(9))


def test_a_short_entropy_source_is_refused() -> None:
    eng = GpuEngine(dev_keystore(get_backend("numpy")), slots=8, entropy=lambda n: bytes(n - 1))
    with pytest.raises(ValueError):
        eng.write_epoch(1, batch_of(3))


def check_timings(t: dict[str, float], used: tuple[str, ...]) -> None:
    assert set(t) == {*STAGES, "total"} and set(WRITE_STAGES) <= set(t)
    assert all(isinstance(v, float) and v >= 0.0 for v in t.values())
    for stage in used:
        assert t[stage] > 0.0, f"stage {stage} was not timed"
    for stage in set(STAGES) - set(used) - {"host"}:
        assert t[stage] == 0.0, f"stage {stage} is not part of this call"
    parts = sum(v for k, v in t.items() if k != "total")
    assert parts == pytest.approx(t["total"], rel=1e-3, abs=1e-6), "the stages must add up to the total"


def test_last_timings_of_every_call(xp: Any) -> None:  # noqa: F811
    eng = GpuEngine(dev_keystore(backend_of(xp)), slots=1 << 10)
    assert eng.timer == (TIMER_SIM if xp is np else TIMER_GPU)
    assert eng.last_timings() == {**dict.fromkeys(STAGES, 0.0), "total": 0.0}
    batch = batch_of(300)
    rows = eng.write_epoch(7, batch)
    check_timings(eng.last_timings(), ("tags", "sort", "compact", "d2h", "h2d", "seal", "bucket"))
    eng.reshuffle_window(rows[0].win, rows)
    check_timings(eng.last_timings(), ("tags", "sort", "compact", "d2h"))
    assert eng.read_window(batch[5].conv_id, rows, 512) == [batch[5].payload]
    check_timings(eng.last_timings(), ("h2d", "open", "sort", "d2h"))
    eng.bucket_of(np.arange(10, dtype=np.uint64))
    check_timings(eng.last_timings(), ("h2d", "bucket", "d2h"))
    snapshot = eng.last_timings()
    snapshot["total"] = -1.0
    assert eng.last_timings()["total"] >= 0.0, "last_timings returns a copy"


def test_an_empty_epoch_runs_the_permutation_and_returns_no_row(xp: Any) -> None:  # noqa: F811
    eng = GpuEngine(dev_keystore(backend_of(xp)), slots=64)
    assert eng.write_epoch(3, []) == []
    check_timings(eng.last_timings(), ("tags", "sort", "compact"))


def test_bucket_of_checks_its_input_and_handles_no_ids() -> None:
    eng = GpuEngine(dev_keystore(get_backend("numpy")))
    assert eng.bucket_of(np.empty(0, dtype=np.uint64)).tolist() == []
    with pytest.raises(TypeError):
        eng.bucket_of(np.arange(4))
    with pytest.raises(TypeError):
        eng.bucket_of(np.zeros((2, 2), dtype=np.uint64))


def test_read_window_refuses_too_many_candidates_and_malformed_rows() -> None:
    eng = GpuEngine(dev_keystore(get_backend("numpy")))
    rows = eng.write_epoch(1, batch_of(5))
    with pytest.raises(ValueError):
        eng.read_window(1, rows, 4)
    with pytest.raises(ValueError):
        eng.read_window(1, rows, 0)
    bad = StoredRow(rows[0].row_id, 0, 0, b"short", b"")
    with pytest.raises(ValueError):
        eng.read_window(1, [bad], 4)


def test_reshuffle_refuses_rows_of_another_window() -> None:
    eng = GpuEngine(dev_keystore(get_backend("numpy")))
    rows = eng.write_epoch(1, batch_of(5))
    with pytest.raises(ValueError):
        eng.reshuffle_window(rows[0].win + 1, rows)


def test_the_entropy_contract_is_one_call_of_28_bytes_per_row() -> None:
    calls: list[int] = []

    def ent(n: int) -> bytes:
        calls.append(n)
        return bytes(i % 256 for i in range(n))

    eng = GpuEngine(dev_keystore(get_backend("numpy")), slots=16, entropy=ent)
    rows = eng.write_epoch(1, batch_of(5))
    assert calls == [ROW_ENTROPY * 5]
    for p, row in enumerate(rows):
        assert row.seq_enc[:12] == bytes(range(28 * p + 16, 28 * p + 28)), "the nonce is bytes 16..27 of the row"
        assert row.row_id.version == 4 and len(row.seq_enc) == 44
