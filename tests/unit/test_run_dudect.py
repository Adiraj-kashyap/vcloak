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
    assert set(rd.DIAG) <= set(rd.ISSUE17) and set(rd.ISSUE17_REP) < set(rd.ISSUE17)
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
