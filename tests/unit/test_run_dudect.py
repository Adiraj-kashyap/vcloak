"""M08 S1-S2: bench/run_dudect.py. The numpy backend must measure nothing; the measuring loop is driven
with tests/fakecupy.py (a stand-in device whose events read the host clock) into tmp_path, to check
the flow and the bookkeeping only. No number produced here is a result."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

import fakecupy
from vcloak import runs
from vcloak.bench import dudect
from vcloak.gpu import sim, telemetry
from vcloak.gpu.runtime import get_backend

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "scripts"))

import check_oblivious  # noqa: E402
import run_dudect as rd  # noqa: E402


def only_run(out: Path) -> Path:
    (d,) = out.glob("*_M08_dudect*")
    return d


def summary(run_dir: Path) -> dict:
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))


@pytest.fixture
def numpy_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rd, "get_backend", lambda: get_backend("numpy"))


@pytest.fixture
def fake_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rd, "get_backend", fakecupy.backend)
    monkeypatch.setattr(telemetry, "sample", fakecupy.clock_sample)
    for name, value in (("LOG2N", 6), ("CAL_PER_CLASS", 40), ("CHUNK", 50), ("R_PROBE", 4), ("WARM_MIN_S", 0.0),
                        ("WARM_MAX_S", 0.1), ("POOL", 2), ("POOL_QUICK", 2)):
        monkeypatch.setattr(rd, name, value)
    monkeypatch.setenv("VCLOAK_SESSION_ID", "20260101-000000")
    monkeypatch.setenv("VCLOAK_RUNNER", "kaggle")


def test_numpy_backend_measures_nothing(tmp_path: Path, numpy_backend: None) -> None:
    assert rd.main(["--targets", "all", "--seed", "8", "--out", str(tmp_path)]) == 0
    d = only_run(tmp_path)
    m, s = runs.read_manifest(d), summary(d)
    assert m["status"] == "NOT_MEASURED" and m["env"]["backend"] == "numpy"
    assert [t["target"] for t in s["targets"]] == list(rd.ALL)
    assert all(t["mismatches"] == 0 and t["verdict"] == "NOT_MEASURED" for t in s["targets"])
    assert len(s["metrics"]) == 2 * len(rd.ALL) and all(x["value"] == "NOT_MEASURED" for x in s["metrics"])
    assert not list(d.glob("*.npz")) and not list(d.glob("*.png"))
    assert runs.validate_manifest(d) == []


def test_the_planted_leak_is_detected_on_the_fake_device(tmp_path: Path, fake_gpu: None) -> None:
    assert rd.main(["--targets", "control_leak", "--n-per-class", "200", "--out", str(tmp_path)]) == 0
    d = only_run(tmp_path)
    res = json.loads((d / "dudect_control_leak.json").read_text(encoding="utf-8"))
    assert res["verdict"] == dudect.FAIL == res["expected_verdict"] and res["max_abs_t"] > dudect.T_THRESHOLD
    assert res["mismatches"] == 0 and res["r"] >= 1 and res["n_per_class"] == 200
    assert len(res["series"]["ms"]["curve"]) == 8  # 400 measurements in chunks of 50
    raw = np.load(d / "dudect_control_leak_raw.npz")
    assert raw["times_ms"].shape == (400, 1) and int(raw["classes"].sum()) == 200
    assert raw["calibration_ms"].shape == (80, 1)
    again = dudect.analyse(raw["times_ms"][:, 0], raw["classes"], raw["calibration_ms"][:, 0], batch=50)
    assert again["max_abs_t"] == pytest.approx(res["max_abs_t"])  # the saved raw data reproduce the verdict
    assert (d / "dudect_control_leak.png").exists()
    ids = {x["id"]: x["value"] for x in summary(d)["metrics"]}
    assert ids["T-DUDECT-N-CONTROL-LEAK"] == 200 and ids["T-DUDECT-MAXT-CONTROL-LEAK"] != "NOT_MEASURED"
    assert runs.read_manifest(d)["status"] == "OK"


def test_a_control_with_the_wrong_verdict_fails_the_run(tmp_path: Path, fake_gpu: None,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rd.ControlLeak, "expect", dudect.PASS)  # pretend the leak should not have been seen
    assert rd.main(["--targets", "control_leak", "--n-per-class", "200", "--out", str(tmp_path)]) == 1
    m = runs.read_manifest(only_run(tmp_path))
    assert m["status"] == "FAIL" and "control" in m["notes"]


def test_a_target_that_raises_is_recorded_and_fails_the_run(tmp_path: Path, fake_gpu: None,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: object) -> None:
        raise RuntimeError("no such kernel")

    monkeypatch.setattr(rd.ControlLeak, "run", boom)
    assert rd.main(["--targets", "control_leak", "--n-per-class", "100", "--out", str(tmp_path)]) == 1
    d = only_run(tmp_path)
    assert "no such kernel" in summary(d)["errors"][0] and runs.read_manifest(d)["status"] == "FAIL"


@pytest.mark.parametrize("name", ["control_null", "bitonic_equal", "bitonic_sorted", "aead_tag", "aead_conv"])
def test_device_targets_run_through_the_measuring_loop(name: str, tmp_path: Path, fake_gpu: None) -> None:
    backend = fakecupy.backend()
    res = rd.run_target(rd.build_target(name, backend, 8, True), backend, 60, 8, tmp_path, log=lambda s: None)
    s = res["series"]["ms"]
    assert res["mismatches"] == 0 and s["n_class0"] == s["n_class1"] == 60 and s["tests"] == 101
    assert res["verdict"] in (dudect.PASS, dudect.FAIL)
    assert (tmp_path / f"dudect_{name}_raw.npz").exists()


def test_write_epoch_has_a_device_series_and_a_call_series() -> None:
    t = rd.build_target("write_epoch", get_backend("numpy"), 8, True)
    assert t.series == ("device_ms", "call_ms") and t.n_real == t.slots // rd.REAL_FRACTION
    t.prepare(1, np.random.default_rng(1))
    device, call = t.measure(None, None, None, None, 1)
    assert 0.0 <= device <= call and t.check(1) == 0


@pytest.mark.parametrize("name", rd.ALL)
def test_preparing_either_class_does_the_same_host_work(name: str) -> None:
    """Both classes consume the same random numbers, so the host does the same before every measurement."""
    backend = get_backend("numpy")
    a, b = np.random.default_rng(5), np.random.default_rng(5)
    rd.build_target(name, backend, 8, True).prepare(0, a)
    rd.build_target(name, backend, 8, True).prepare(1, b)
    assert a.integers(0, 2**63) == b.integers(0, 2**63)


def test_the_null_control_uploads_the_same_input_for_both_classes() -> None:
    t = rd.build_target("control_null", get_backend("numpy"), 8, True)
    rng = np.random.default_rng(1)
    t.prepare(0, rng)
    first = [c.copy() for c in t.cols]
    t.prepare(1, rng)
    assert all(np.array_equal(x, y) for x, y in zip(first, t.cols, strict=True))


def test_choose_r() -> None:
    assert rd.choose_r([0.2] * 5, False) == (1, "")
    assert rd.choose_r([0.01] * 5, False) == (5, "")
    r, note = rd.choose_r([0.01] * 5, True)
    assert r == 1 and "not batched" in note


def test_parse_targets() -> None:
    assert rd.parse_targets("all") == list(rd.ALL)
    assert rd.parse_targets("controls,aead_tag,control_leak") == ["control_leak", "control_null", "aead_tag"]
    with pytest.raises(SystemExit):
        rd.parse_targets("bitonic")


def test_metric_ids() -> None:
    res = {"target": "write_epoch", "n_per_class": 7, "r": 1, "series": {
        name: {"verdict": "PASS", "threshold": 4.5, "max_at": "raw", "tests": 101, "max_abs_t": v}
        for name, v in (("device_ms", 1.23456), ("call_ms", float("inf")))}}
    got = {m["id"]: m["value"] for m in rd.metrics_of([res], True, None)}
    assert got == {"T-DUDECT-MAXT-WRITE-EPOCH": 1.2346, "T-DUDECT-MAXT-WRITE-EPOCH-CALL": "inf",
                   "T-DUDECT-N-WRITE-EPOCH": 7}


def test_planted_leak_twin_values() -> None:
    x = np.array([0, 1, 5, 0xFFFFFFFF], dtype=np.uint32)
    out = np.zeros(4, dtype=np.uint32)
    sim.get("planted_leak")(x, out, 4, 3, grid=1, block=4)

    def lcg(v: int) -> int:
        for _ in range(3):
            v = (v * 1664525 + 1013904223) & 0xFFFFFFFF
        return v

    assert out.tolist() == [0, lcg(1), lcg(5), lcg(0xFFFFFFFF)]
    part = np.full(4, 9, dtype=np.uint32)
    sim.get("planted_leak")(x, part, 2, 3, grid=1, block=4)  # threads past n do nothing
    assert part.tolist() == [0, lcg(1), 9, 9]


def test_the_static_checker_flags_the_planted_leak_and_it_is_not_in_kernels() -> None:
    findings, files = check_oblivious.check_paths([rd.LEAK_SRC])
    assert files and any(f.rule == "BRANCH" and "x" in f.message for f in findings)
    assert not (ROOT / "kernels" / rd.LEAK_SRC.name).exists()


# --- ISSUE-17: the diagnostic targets -------------------------------------------------------------

def test_issue17_groups() -> None:
    assert set(rd.DIAG) <= {*rd.ISSUE17, *rd.ISSUE25, *rd.ISSUE25K, *rd.DIAG_CONTROLS}
    assert set(rd.ISSUE17_REP) < set(rd.ISSUE17)
    assert {"aead_conv", "aead_tag", "write_epoch"} <= set(rd.ISSUE17_REP)  # the three failing targets, again
    assert rd.parse_targets("control_null,issue17") == ["control_null", *rd.ISSUE17]
    assert not set(rd.DIAG) & set(rd.ALL)  # `all` and `targets` stay what the M08 job measured
    ids = [rd.METRIC_OF[n] for n in rd.KNOWN]
    assert len(set(ids)) == len(ids)


def test_issue17_plumbing_on_the_numpy_backend(tmp_path: Path, numpy_backend: None) -> None:
    assert rd.main(["--targets", "issue17", "--out", str(tmp_path)]) == 0
    s = summary(only_run(tmp_path))
    assert [t["target"] for t in s["targets"]] == list(rd.ISSUE17) and not s["errors"]
    assert all(t["mismatches"] == 0 for t in s["targets"])
    assert {m["value"] for m in s["metrics"]} == {"NOT_MEASURED"}


@pytest.mark.parametrize("name", [n for n in rd.DIAG if n.startswith("aead")])
def test_issue17_aead_targets_run_through_the_measuring_loop(name: str, tmp_path: Path, fake_gpu: None) -> None:
    backend = fakecupy.backend()
    t = rd.build_target(name, backend, 8, True)
    res = rd.run_target(t, backend, 60, 8, tmp_path, log=lambda s: None)
    s = res["series"]["ms"]
    assert res["mismatches"] == 0 and s["n_class0"] == s["n_class1"] == 60
    assert res["r"] == (rd.KERNEL_WINDOW_R if name.endswith("_kernel") else 1)
    assert ("by design" in res["r_note"]) == name.endswith("_kernel")


@pytest.mark.parametrize("name", rd.DIAG)
def test_issue17_preparing_either_class_does_the_same_host_work(name: str) -> None:
    backend = get_backend("numpy")
    a, b = np.random.default_rng(5), np.random.default_rng(5)
    rd.build_target(name, backend, 8, True).prepare(0, a)
    rd.build_target(name, backend, 8, True).prepare(1, b)
    assert a.integers(0, 2**63) == b.integers(0, 2**63)


def staged(name: str, cls: int, seed: int = 3) -> np.ndarray:
    t = rd.build_target(name, get_backend("numpy"), 8, True)
    t.prepare(cls, np.random.default_rng(seed))
    return t.blobs.copy()


def test_issue17_the_tag_null_stages_the_same_rows_in_both_classes() -> None:
    assert np.array_equal(staged("aead_tag_null", 0), staged("aead_tag_null", 1))
    assert np.array_equal(staged("aead_tag_null", 0), staged("aead_tag", 0))


def test_issue17_the_tag_swap_exchanges_the_roles() -> None:
    t = rd.build_target("aead_tag_swap", get_backend("numpy"), 8, True)
    assert np.array_equal(staged("aead_tag_swap", 1), t.valid)  # the freshly written array is the valid one
    assert np.array_equal(staged("aead_tag_swap", 0), t.invalid)
    assert not np.array_equal(t.tags(t.invalid), t.tags(t.valid))
    assert (t.is_valid(0), t.is_valid(1)) == (False, True)


@pytest.mark.parametrize(("name", "hit"), [
    ("aead_conv", (0, 1)), ("aead_conv_null", (0, 0)), ("aead_conv_swap", (1, 0)), ("aead_conv_sym", (0, 1)),
    ("aead_conv_kernel", (0, 1))])
def test_issue17_conv_classes_open_as_declared(name: str, hit: tuple[int, int]) -> None:
    """hi is 0 for a row of the conversation asked for: the class contents are what the target says."""
    t = rd.build_target(name, get_backend("numpy"), 8, True)
    for cls in (0, 1):
        t.prepare(cls, np.random.default_rng(2))
        t.run()
        assert set(np.unique(t.out[0])) == {hit[cls]} and t.check(cls) == 0


def test_issue17_symmetric_pools_have_the_same_size_and_differ_per_class() -> None:
    for name in ("aead_conv_sym", "aead_tag_sym", "aead_conv_kernel", "aead_tag_kernel"):
        t = rd.build_target(name, get_backend("numpy"), 8, True)
        assert len(t.pools[0]) == len(t.pools[1]) == 2
        assert not np.array_equal(t.pools[0][0], t.pools[1][0])
        assert t.params()["pool_per_class"] == 2 and "class1_pool" not in t.params()


def test_issue17_the_kernel_window_reuses_its_outputs() -> None:
    t = rd.build_target("aead_tag_kernel", get_backend("numpy"), 8, True)
    t.prepare(0, np.random.default_rng(1))
    t.run()
    first = t.out
    t.run()
    assert all(a is b for a, b in zip(first, t.out, strict=True)) and t.min_r == rd.KERNEL_WINDOW_R
    assert t.params()["outputs"] == "preallocated"


def contents_of(batch: list) -> list:
    return [(s.conv_id, s.seq, s.payload) for s in batch]


def test_issue17_write_epoch_variants() -> None:
    backend = get_backend("numpy")
    base = rd.build_target("write_epoch", backend, 8, True)
    fixed = contents_of(base.build(base.fixed))
    for name in ("write_epoch_null", "write_epoch_age"):  # the same contents whatever the class
        for cls in (0, 1):
            t = rd.build_target(name, backend, 8, True)
            t.prepare(cls, np.random.default_rng(4))
            assert contents_of(t.batch) == fixed, (name, cls)
    t = rd.build_target("write_epoch_age", backend, 8, True)
    t.prepare(0, np.random.default_rng(4))
    assert t.batch[0].conv_id is t.fixed[0][0]  # class A: the long-lived objects
    t.prepare(1, np.random.default_rng(4))
    assert t.batch[0].conv_id is not t.fixed[0][0]  # class B: equal value, new object
    t = rd.build_target("write_epoch_fresh", backend, 8, True)
    t.prepare(0, np.random.default_rng(4))
    assert contents_of(t.batch) == fixed and t.batch[0].conv_id is not t.fixed[0][0]
    t.prepare(1, np.random.default_rng(4))
    assert contents_of(t.batch) != fixed
    t.run()
    assert t.check(1) == 0 and t.series == ("device_ms", "call_ms")


# --- ISSUE-25: the write_epoch diagnostics with one series per engine stage ---------------------

def test_issue25_group() -> None:
    assert rd.parse_targets("issue25") == list(rd.ISSUE25) and rd.ISSUE25[0] == "write_epoch_null_st"
    assert not set(rd.ISSUE25) & {*rd.ALL, *rd.ISSUE17}  # the earlier jobs stay what they measured
    assert rd.WRITE_STAGES == ("h2d", "tags", "sort", "compact", "d2h", "seal", "bucket")
    assert rd.STAGE_SERIES[:3] == ("device_ms", "call_ms", "core_ms")  # the verdict series is the one that FAILED
    assert set(rd.STAGE_SERIES) <= set(rd.SERIES_SUFFIX)
    assert len(set(rd.SERIES_SUFFIX.values())) == len(rd.SERIES_SUFFIX) - 1  # only ms and device_ms share one


@pytest.mark.parametrize("name", rd.ISSUE25)
def test_issue25_series_add_up_and_the_staging_is_that_of_the_parent(name: str) -> None:
    backend = get_backend("numpy")
    t, parent = rd.build_target(name, backend, 8, True), rd.build_target(name.removesuffix("_st"), backend, 8, True)
    for cls in (0, 1):
        t.prepare(cls, np.random.default_rng(4))
        parent.prepare(cls, np.random.default_rng(4))
        assert contents_of(t.batch) == contents_of(parent.batch), (name, cls)
        got = dict(zip(t.series, t.measure(None, None, None, None, 1), strict=True))
        tm = t.eng.last_timings()
        assert t.check(cls) == 0
        assert got["call_ms"] == tm["total"] and got["device_ms"] == tm["total"] - tm["host"]
        assert got["core_ms"] == got["device_ms"] - tm["h2d"] - tm["d2h"]
        assert all(got[f"{s}_ms"] == tm[s] for s in rd.WRITE_STAGES)
        assert sum(got[f"{s}_ms"] for s in rd.WRITE_STAGES) == pytest.approx(got["device_ms"], abs=1e-6)
        assert tm["open"] == 0.0  # the read stage is never marked by write_epoch: no series for it
        assert all(got[f"{s}_ms"] > 0 for s in rd.WRITE_STAGES)  # every series is a stage that ran
    assert t.params()["series_of_one_call"] == len(rd.STAGE_SERIES) and "h2d, d2h" in t.params()["core_ms"]


def test_issue25_plumbing_on_the_numpy_backend(tmp_path: Path, numpy_backend: None) -> None:
    assert rd.main(["--targets", "control_null,issue25", "--out", str(tmp_path)]) == 0
    s = summary(only_run(tmp_path))
    assert [t["target"] for t in s["targets"]] == ["control_null", *rd.ISSUE25] and not s["errors"]
    assert all(t["mismatches"] == 0 for t in s["targets"])
    assert {m["value"] for m in s["metrics"]} == {"NOT_MEASURED"}


def test_issue25_a_target_runs_through_the_measuring_loop(tmp_path: Path, fake_gpu: None) -> None:
    # the stand-in device cannot hold the key store: the engine is the simulator, the loop is the real one
    t = rd.build_target("write_epoch_age_st", get_backend("numpy"), 8, True)
    res = rd.run_target(t, fakecupy.backend(), 60, 8, tmp_path, log=lambda s: None)
    assert tuple(res["series"]) == rd.STAGE_SERIES and res["mismatches"] == 0 and res["r"] == 1
    assert all(s["n_class0"] == s["n_class1"] == 60 for s in res["series"].values())
    assert res["verdict"] == res["series"]["device_ms"]["verdict"]
    raw = np.load(tmp_path / res["raw"])
    assert raw["times_ms"].shape == (120, len(rd.STAGE_SERIES)) and list(raw["series"]) == list(rd.STAGE_SERIES)
    stages = raw["times_ms"][:, 3:].sum(axis=1)
    assert np.allclose(stages, raw["times_ms"][:, 0], atol=1e-6)  # the stages add up to the device series
    assert len(rd.metrics_of([res], False, None)) == len(rd.STAGE_SERIES) + 1


def test_issue25_metric_ids_name_the_stage() -> None:
    series = {n: {"verdict": "PASS", "threshold": 4.5, "max_at": "raw", "tests": 101, "max_abs_t": 1.0}
              for n in rd.STAGE_SERIES}
    ms = rd.metrics_of([{"target": "write_epoch_age_st", "series": series, "r": 1, "n_per_class": 7}], False, None)
    ids = [m["id"] for m in ms]
    assert len(set(ids)) == len(ids) == len(rd.STAGE_SERIES) + 1
    assert {"T-DUDECT-MAXT-WRITE-EPOCH-AGE-ST", "T-DUDECT-MAXT-WRITE-EPOCH-AGE-ST-CORE",
            "T-DUDECT-MAXT-WRITE-EPOCH-AGE-ST-H2D", "T-DUDECT-MAXT-WRITE-EPOCH-AGE-ST-D2H"} <= set(ids)


def test_open_and_key_writes_into_given_outputs() -> None:
    t = rd.build_target("aead_conv", get_backend("numpy"), 8, True)
    t.prepare(0, np.random.default_rng(1))
    want = rd.gpu_open_and_key(t.kseq, t.blobs, t.q)
    out = (np.empty(t.n, dtype=np.uint64), np.empty(t.n, dtype=np.uint64), np.empty(t.n, dtype=np.uint32))
    got = rd.gpu_open_and_key(t.kseq, t.blobs, t.q, out=out)
    assert all(g is o for g, o in zip(got, out, strict=True))
    assert all(np.array_equal(g, w) for g, w in zip(got, want, strict=True))
    with pytest.raises(ValueError, match="out ok"):
        rd.gpu_open_and_key(t.kseq, t.blobs, t.q, out=(out[0], out[1], out[2][:-1].copy()))
    with pytest.raises(TypeError, match="out hi"):
        rd.gpu_open_and_key(t.kseq, t.blobs, t.q, out=(out[2], out[1], out[2]))


# --- ISSUE-25, kernel-only window: tags and compact behind a blocker ----------------------------

@pytest.fixture
def small_window(monkeypatch: pytest.MonkeyPatch, fake_gpu: None) -> None:
    for name, value in (("WRITE_SLOTS", 64), ("BLOCKER_MIN", 4), ("BLOCKER_MAX", 16), ("QUEUE_PROBE", 3),
                        ("WARM_Q_MIN_S", 0.0), ("WARM_Q_MAX_S", 0.1), ("WARM_Q_FLAT", 1)):
        monkeypatch.setattr(rd, name, value)
    monkeypatch.setattr(rd._QueuedWindow, "blocker_blocks", 4)


def test_issue25k_group() -> None:
    assert rd.parse_targets("issue25k") == list(rd.ISSUE25K)
    assert rd.ISSUE25K.index("tags_kernel_null") < rd.ISSUE25K.index("tags_kernel")  # the control first
    assert not set(rd.ISSUE25K) & {*rd.ALL, *rd.ISSUE17, *rd.ISSUE25}
    assert rd.build_target("control_leak_q", get_backend("numpy"), 8, True).expect == dudect.FAIL


def test_the_class_order_is_a_random_interleaving_not_two_blocks() -> None:
    c = dudect.balanced_classes(5000, np.random.default_rng([8, 2]))
    assert c.sum() == 5000 and c.size == 10000
    switches = int(np.count_nonzero(c[1:] != c[:-1]))
    assert 4700 < switches < 5300  # two blocks would switch once; a fair shuffle about n times
    edges = np.flatnonzero(np.diff(np.concatenate(([2], c, [2]))))
    assert int(np.diff(edges).max()) < 30  # the longest run of one class


@pytest.mark.parametrize("name", ["write_epoch_null_st", "write_epoch_age_st", "write_epoch_fresh_st"])
def test_issue25_tags_and_compact_get_the_same_device_input_in_both_classes(
        name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The stages tags, sort and compact of write_epoch never see the submissions: their inputs come from
    K_tag, the epoch and n_real. A difference of tags_ms or compact_ms between the classes of these targets
    is therefore not a dependence of those kernels on their data."""
    from vcloak.gpu import engine

    seen: list[tuple[bytes, ...]] = []
    tags, compact = engine.gpu_tags_for_epoch, engine.gpu_compact

    def spy_tags(key: np.ndarray, epoch: int, n: int) -> tuple[np.ndarray, np.ndarray]:
        hi, lo = tags(key, epoch, n)
        seen.append((b"tags", np.asarray(key).tobytes(), bytes([epoch]), hi.tobytes(), lo.tobytes()))
        return hi, lo

    def spy_compact(is_dummy: np.ndarray, order: np.ndarray) -> np.ndarray:
        seen.append((b"compact", is_dummy.tobytes(), order.tobytes()))
        return compact(is_dummy, order)

    monkeypatch.setattr(engine, "gpu_tags_for_epoch", spy_tags)
    monkeypatch.setattr(engine, "gpu_compact", spy_compact)
    t = rd.build_target(name, get_backend("numpy"), 8, True)
    rng = np.random.default_rng(6)
    per_class = []
    for cls in (0, 1, 0, 1):
        seen.clear()
        t.prepare(cls, rng)
        t.run()
        assert [s[0] for s in seen] == [b"tags", b"compact"]
        per_class.append(list(seen))
    assert all(p == per_class[0] for p in per_class)
    if name == "write_epoch_fresh_st":  # while the submissions themselves do differ
        t.prepare(0, rng)
        a = contents_of(t.batch)
        t.prepare(1, rng)
        assert contents_of(t.batch) != a


@pytest.mark.parametrize("name", rd.ISSUE25K)
def test_issue25k_classes_are_what_the_target_says(name: str) -> None:
    t = rd.build_target(name, get_backend("numpy"), 8, True)
    same = all(np.array_equal(a, b) for a, b in zip(t.host[0], t.host[1], strict=True))
    assert same == name.endswith("_null") and len(t.host[0]) == len(t.host[1])
    assert all(np.array_equal(a, t.host[0][0]) for a in t.host[0])  # class A is one fixed input
    for cls in (0, 1):
        t.prepare(cls, np.random.default_rng(2))
        t.run()
        assert t.check(cls) == 0
    if name.startswith("compact"):
        for p in (*t.host[0], *t.host[1]):  # a permutation: the same number of dummies in every input
            assert sorted(p.tolist()) == list(range(t.slots))
        eng_order = rd.gpu_compact((t.host[1][0] >= t.n_real).astype(np.uint32), t.host[1][0])
        assert eng_order[:t.n_real].tolist() == [v for v in t.host[1][0].tolist() if v < t.n_real]


def test_issue25k_the_window_enqueues_blocker_start_launches_end_and_reads_the_flag(
        monkeypatch: pytest.MonkeyPatch) -> None:
    t = rd.build_target("tags_kernel", get_backend("numpy"), 8, True)
    log: list[str] = []

    class Ev:
        def __init__(self, name: str, done: bool) -> None:
            self.name, self._done = name, done

        def record(self, stream: object) -> None:
            log.append(self.name)

        @property
        def done(self) -> bool:
            log.append(f"{self.name}.done?")
            return self._done

        def synchronize(self) -> None:
            log.append(f"{self.name}.sync")

    monkeypatch.setattr(t, "_block", lambda: log.append("blocker"))
    monkeypatch.setattr(t, "run", lambda: log.append("launch"))
    cp = type("cp", (), {"cuda": type("cuda", (), {"get_elapsed_time": staticmethod(lambda a, b: 0.25)})})
    stream = type("S", (), {"synchronize": lambda self: log.append("stream.sync")})()
    assert t.measure(cp, stream, Ev("start", False), Ev("end", False), 3) == (0.25,)
    assert log == ["stream.sync", "blocker", "start", "launch", "launch", "launch", "end", "start.done?", "end.sync"]
    assert t.queued is True
    t.measure(cp, stream, Ev("start", True), Ev("end", False), 1)
    assert t.queued is False  # the device was idle before the end event was enqueued: host time is inside


@pytest.mark.parametrize("name", [*rd.ISSUE25K, "control_leak_q"])
def test_issue25k_targets_run_through_the_measuring_loop(name: str, tmp_path: Path, small_window: None) -> None:
    backend = fakecupy.backend()
    t = rd.build_target(name, backend, 8, True)
    clock = iter([1590] * 100 + [585] * 5 + [1575] * 10_000)
    res = rd.run_target(t, backend, 60, 8, tmp_path, log=lambda s: None, sm_clock=lambda: next(clock))
    f, s = res["per_sample"], res["series"]["ms"]
    assert res["mismatches"] == 0 and s["n_class0"] == s["n_class1"] == 60
    assert f["measurements"] == 120 and f["unqueued"] == 0 and f["steady_clock_mhz"] == 1590
    assert f["off_clock"] == 5 and f["not_at_modal_clock"] == 20 and f["flagged"] == 5
    assert s["unflagged"]["n_class0"] + s["unflagged"]["n_class1"] == 115
    assert f["blocker_steps"][0] == {"blocks": 4, "r": 1, "unqueued": 0} and t.blocker_blocks >= 8
    raw = np.load(tmp_path / res["raw"])
    assert raw["clocks_mhz"].shape == raw["queued"].shape == (120,) and raw["queued"].all()
    ids = [m["id"] for m in rd.metrics_of([res], False, None)]
    base = rd.METRIC_OF[name]
    assert ids == [f"T-DUDECT-MAXT-{base}", f"T-DUDECT-MAXT-{base}-UNFLAGGED", f"T-DUDECT-FLAGGED-{base}",
                   f"T-DUDECT-CLOCK-{base}", f"T-DUDECT-N-{base}"]


def test_issue25k_unqueued_measurements_are_flagged_and_the_blocker_stops_at_its_limit(
        tmp_path: Path, small_window: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fakecupy._Event, "done", True)  # a device that is never busy: nothing is queued
    backend = fakecupy.backend()
    t = rd.build_target("tags_kernel_null", backend, 8, True)
    res = rd.run_target(t, backend, 40, 8, tmp_path, log=lambda s: None, sm_clock=lambda: None)
    f = res["per_sample"]
    assert t.blocker_blocks == rd.BLOCKER_MAX and f["blocker_steps"][-1]["unqueued"] == rd.QUEUE_PROBE
    assert f["unqueued"] == f["flagged"] == 80 and f["off_clock"] == "NOT_MEASURED"
    assert res["series"]["ms"]["n_class0"] == 40  # the verdict is still the test on every measurement
    assert res["series"]["ms"]["unflagged"]["n_class0"] == 0


def test_issue25k_plumbing_on_the_numpy_backend(tmp_path: Path, numpy_backend: None) -> None:
    assert rd.main(["--targets", "control_leak_q,issue25k", "--lock-clock", "--out", str(tmp_path)]) == 0
    s = summary(only_run(tmp_path))
    assert [t["target"] for t in s["targets"]] == ["control_leak_q", *rd.ISSUE25K] and not s["errors"]
    assert all(t["mismatches"] == 0 for t in s["targets"])
    assert {m["value"] for m in s["metrics"]} == {"NOT_MEASURED"}
    assert s["clock_lock"] == {"attempted": False, "accepted": False}  # never asked for without a device


def test_the_clock_lock_records_a_refusal_and_an_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    nv = types.SimpleNamespace(NVML_CLOCK_SM=1, nvmlDeviceGetHandleByIndex=lambda i: "h",
                               nvmlDeviceGetMaxClockInfo=lambda h, c: 1590, nvmlDeviceGetClockInfo=lambda h, c: 585)
    monkeypatch.setattr(telemetry, "_nvml", lambda: nv)
    monkeypatch.setattr(telemetry, "_clock_handle", None)
    calls: list[list[str]] = []

    def smi(code: int) -> object:
        def run(cmd: list[str], **kw: object) -> types.SimpleNamespace:
            calls.append(cmd)
            return types.SimpleNamespace(returncode=code, stdout="out", stderr="")
        return run

    monkeypatch.setattr(telemetry.subprocess, "run", smi(4))
    got = telemetry.lock_clock()
    assert got["attempted"] and not got["accepted"] and got["returncode"] == 4
    assert calls[-1] == ["nvidia-smi", "-i", "0", "-lgc", "1590,1590"] and telemetry._locked_mhz is None
    monkeypatch.setattr(telemetry.subprocess, "run", smi(0))
    assert telemetry.lock_clock()["accepted"] and telemetry._clock_lock() == "lock accepted at 1590 MHz"
    assert telemetry.unlock_clock()["command"].endswith("-rgc") and telemetry._locked_mhz is None
    assert telemetry.sm_clock() == 585
    monkeypatch.setattr(telemetry, "_clock_handle", None)
