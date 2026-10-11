"""M08 S1: the dudect statistics (vcloak.bench.dudect) on synthetic numbers. Nothing here is a timing."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from vcloak.bench import dudect


def synthetic(n: int, shift: float, seed: int = 1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    classes = dudect.balanced_classes(n, rng)
    times = rng.normal(1.0, 0.05, classes.size) + shift * classes
    cal = rng.normal(1.0, 0.05, 1000) + shift * (rng.integers(0, 2, 1000))
    return times, classes, cal


def test_percentile_points_follow_the_dudect_formula() -> None:
    p = dudect.percentile_points()
    assert p.size == dudect.N_PERCENTILES == 100
    assert p[0] == pytest.approx(100 * (1 - 0.5 ** 0.1))
    assert p[-1] == pytest.approx(100 * (1 - 2.0 ** -10))
    assert np.all(np.diff(p) > 0)


def test_balanced_classes_are_exact_and_shuffled() -> None:
    c = dudect.balanced_classes(500, np.random.default_rng(3))
    assert c.size == 1000 and int(c.sum()) == 500
    assert 0 < int(c[:500].sum()) < 500  # not the unshuffled layout
    with pytest.raises(ValueError):
        dudect.balanced_classes(0, np.random.default_rng(3))


def test_raw_and_crop_t_match_scipy() -> None:
    times, classes, cal = synthetic(4000, 0.002)
    th = dudect.crop_thresholds(cal)
    test = dudect.OnlineTTest(th)
    test.update(times, classes)
    t = test.t()
    want = stats.ttest_ind(times[classes == 0], times[classes == 1], equal_var=False).statistic
    assert t[0] == pytest.approx(want, rel=1e-9)
    for i in (0, 37, 99):
        keep = times < th[i]
        want = stats.ttest_ind(times[keep & (classes == 0)], times[keep & (classes == 1)], equal_var=False).statistic
        assert t[i + 1] == pytest.approx(want, rel=1e-9)


@pytest.mark.parametrize("batch", [1, 7, 1000])
def test_online_updates_do_not_depend_on_the_batch_size(batch: int) -> None:
    times, classes, cal = synthetic(600, 0.01)
    th = dudect.crop_thresholds(cal)
    whole, parts = dudect.OnlineTTest(th), dudect.OnlineTTest(th)
    whole.update(times, classes)
    for i in range(0, times.size, batch):
        parts.update(times[i:i + batch], classes[i:i + batch])
    np.testing.assert_allclose(parts.t(), whole.t(), rtol=1e-8, atol=1e-10)
    np.testing.assert_array_equal(parts.n, whole.n)


def test_a_shift_of_a_fifth_of_sigma_is_detected_and_no_shift_is_not() -> None:
    times, classes, cal = synthetic(10_000, 0.01)
    leaky = dudect.analyse(times, classes, cal)
    assert leaky["verdict"] == dudect.FAIL and leaky["max_abs_t"] > 10
    assert leaky["n_class0"] == leaky["n_class1"] == 10_000
    assert len(leaky["curve"]) == 20 and leaky["curve"][-1]["max_abs_t"] == leaky["max_abs_t"]
    times, classes, cal = synthetic(10_000, 0.0)
    clean = dudect.analyse(times, classes, cal)
    assert clean["verdict"] == dudect.PASS and clean["max_abs_t"] < dudect.T_THRESHOLD
    assert clean["tests"] == 101


def test_no_variance() -> None:
    th = np.array([10.0])
    same = dudect.OnlineTTest(th)
    same.update(np.ones(8), np.array([0, 1] * 4))
    assert same.result()["verdict"] == dudect.PASS and same.result()["max_abs_t"] == 0.0
    apart = dudect.OnlineTTest(th)
    apart.update(np.array([1.0, 2.0] * 4), np.array([0, 1] * 4))
    assert apart.result()["verdict"] == dudect.FAIL and np.isinf(apart.result()["max_abs_t"])


def test_one_class_only_is_no_evidence() -> None:
    t = dudect.OnlineTTest(np.array([10.0]))
    t.update(np.array([1.0, 1.1, 1.2]), np.array([0, 0, 0]))
    assert t.result()["max_abs_t"] == 0.0


def test_bad_input_is_refused() -> None:
    t = dudect.OnlineTTest(np.array([1.0]))
    with pytest.raises(ValueError):
        t.update(np.array([1.0, 2.0]), np.array([0, 2]))
    with pytest.raises(ValueError):
        t.update(np.array([1.0, np.nan]), np.array([0, 1]))
    with pytest.raises(ValueError):
        t.update(np.array([1.0]), np.array([0, 1]))
    with pytest.raises(ValueError):
        dudect.crop_thresholds([1.0])


def test_plot_curve_writes_a_png(tmp_path: Path) -> None:
    times, classes, cal = synthetic(2000, 0.0)
    res = dudect.analyse(times, classes, cal, batch=500)
    dudect.plot_curve(tmp_path / "t.png", res["curve"], "synthetic")
    assert (tmp_path / "t.png").stat().st_size > 1000
