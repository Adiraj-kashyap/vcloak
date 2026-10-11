"""dudect statistics for the timing side-channel test (ai/GPU_GUIDE.md §7, ai/modules/M08 S1).

Two classes of inputs are measured in a random interleaving: class 0 (A, a fixed input) and class 1
(B, a fresh random input). `OnlineTTest` keeps, for the raw measurements and for each of the
N_PERCENTILES crops of dudect, the count, mean and sum of squared deviations of both classes, and
updates them batch by batch (the merge of two batches is exact, so the result does not depend on the
batch size). Crop i keeps the measurements below the threshold at the percentile
100 * (1 - 0.5 ** (10 (i + 1) / N_PERCENTILES)) of a calibration batch, as in dudect (Reparaz, Balasch
and Verbauwhede, "dude, is my code constant time?", DATE 2017); the calibration batch only sets the
thresholds and is not part of any test.

The verdict is on max |t| over the raw test and the crops. dudect's second-order (centred product)
test is not implemented.

Nothing here knows where a time came from: a time taken under the numpy backend is never a result.
"""
from __future__ import annotations

from typing import Any

import numpy as np

T_THRESHOLD = 4.5  # ai/GPU_GUIDE.md §7: PASS if |t| < 4.5
N_PERCENTILES = 100
MIN_PER_CLASS = 2  # a variance needs two measurements
PASS, FAIL = "PASS", "FAIL"


def percentile_points(count: int = N_PERCENTILES) -> np.ndarray:
    """The percentiles (0..100) of dudect's crops: 100 * (1 - 0.5 ** (10 (i + 1) / count))."""
    i = np.arange(count, dtype=np.float64)
    return 100.0 * (1.0 - 0.5 ** (10.0 * (i + 1.0) / count))


def crop_thresholds(calibration: Any, count: int = N_PERCENTILES) -> np.ndarray:
    """Thresholds of the crops from a calibration batch of measurements (both classes pooled)."""
    a = np.asarray(calibration, dtype=np.float64)
    if a.ndim != 1 or a.size < 2:
        raise ValueError("the calibration batch needs at least two measurements")
    return np.percentile(a, percentile_points(count))


def welch_t(n0: Any, mean0: Any, m2_0: Any, n1: Any, mean1: Any, m2_1: Any) -> np.ndarray:
    """Welch's t = (mean0 - mean1) / sqrt(var0 / n0 + var1 / n1), with var = m2 / (n - 1).

    Elementwise over arrays of tests. A test with fewer than MIN_PER_CLASS measurements in a class,
    or with no variance at all, has t = 0 when the means are equal and is otherwise infinite."""
    n0, n1 = np.asarray(n0, dtype=np.float64), np.asarray(n1, dtype=np.float64)
    mean0, mean1 = np.asarray(mean0, dtype=np.float64), np.asarray(mean1, dtype=np.float64)
    ok = (n0 >= MIN_PER_CLASS) & (n1 >= MIN_PER_CLASS)
    with np.errstate(divide="ignore", invalid="ignore"):
        var = np.asarray(m2_0, dtype=np.float64) / (n0 - 1) / n0 + np.asarray(m2_1, dtype=np.float64) / (n1 - 1) / n1
        diff = mean0 - mean1
        t = np.where(var > 0, diff / np.sqrt(var), np.where(diff == 0, 0.0, np.sign(diff) * np.inf))
    return np.where(ok, t, 0.0)


class OnlineTTest:
    """Welch t statistics of the raw measurements (test 0) and of each crop (tests 1..), updated online."""

    def __init__(self, thresholds: Any) -> None:
        self.thresholds = np.asarray(thresholds, dtype=np.float64)
        if self.thresholds.ndim != 1:
            raise ValueError("thresholds must be one-dimensional")
        tests = self.thresholds.size + 1
        self.n = np.zeros((2, tests), dtype=np.float64)
        self.mean = np.zeros((2, tests), dtype=np.float64)
        self.m2 = np.zeros((2, tests), dtype=np.float64)
        self.curve: list[dict[str, float]] = []

    def update(self, times: Any, classes: Any) -> None:
        """Add one batch: `times[i]` was measured for class `classes[i]` (0 or 1)."""
        x = np.asarray(times, dtype=np.float64)
        c = np.asarray(classes)
        if x.ndim != 1 or c.shape != x.shape:
            raise ValueError("times and classes must be one-dimensional and of the same length")
        if not np.isin(c, (0, 1)).all():
            raise ValueError("classes must be 0 or 1")
        if not np.isfinite(x).all():
            raise ValueError("a measurement is not finite")
        for cls in (0, 1):
            xc = x[c == cls]
            if xc.size == 0:
                continue
            # column 0 keeps everything, column i + 1 the measurements below thresholds[i]
            keep = np.concatenate([np.ones((xc.size, 1), dtype=bool), xc[:, None] < self.thresholds[None, :]], axis=1)
            nb = keep.sum(axis=0).astype(np.float64)
            sb = np.where(keep, xc[:, None], 0.0).sum(axis=0)
            with np.errstate(divide="ignore", invalid="ignore"):
                mb = np.where(nb > 0, sb / nb, 0.0)
            m2b = (np.where(keep, (xc[:, None] - mb[None, :]) ** 2, 0.0)).sum(axis=0)
            na, ma = self.n[cls], self.mean[cls]
            tot = na + nb
            with np.errstate(divide="ignore", invalid="ignore"):
                delta = mb - ma
                self.m2[cls] = self.m2[cls] + m2b + np.where(tot > 0, delta * delta * na * nb / tot, 0.0)
                self.mean[cls] = np.where(tot > 0, (na * ma + nb * mb) / tot, 0.0)
            self.n[cls] = tot

    def t(self) -> np.ndarray:
        """t of every test: index 0 is the raw test, index i + 1 the crop at thresholds[i]."""
        return welch_t(self.n[0], self.mean[0], self.m2[0], self.n[1], self.mean[1], self.m2[1])

    def max_abs_t(self) -> tuple[float, int]:
        """(max |t|, index of the test that has it)."""
        t = np.abs(self.t())
        i = int(np.argmax(t))
        return float(t[i]), i

    def checkpoint(self) -> dict[str, float]:
        """Append the current point of the t-curve (measurements per class so far, raw t, max |t|)."""
        mx, at = self.max_abs_t()
        point = {"n0": float(self.n[0, 0]), "n1": float(self.n[1, 0]), "t_raw": float(self.t()[0]),
                 "max_abs_t": mx, "max_at_test": float(at)}
        self.curve.append(point)
        return point

    def result(self, threshold: float = T_THRESHOLD) -> dict[str, Any]:
        """The verdict and what it rests on. A non-finite t (no variance, different means) is a FAIL."""
        t = self.t()
        mx, at = self.max_abs_t()
        return {
            "n_class0": int(self.n[0, 0]), "n_class1": int(self.n[1, 0]),
            "mean_class0": float(self.mean[0, 0]), "mean_class1": float(self.mean[1, 0]),
            "std_class0": _std(self.n[0, 0], self.m2[0, 0]), "std_class1": _std(self.n[1, 0], self.m2[1, 0]),
            "t_raw": float(t[0]), "max_abs_t": mx, "max_at_test": at,
            "max_at": "raw" if at == 0 else f"crop {at - 1} (below {self.thresholds[at - 1]:.9g})",
            "threshold": threshold, "verdict": PASS if mx < threshold else FAIL,
            "tests": int(t.size), "t_all": [float(v) for v in t],
        }


def _std(n: float, m2: float) -> float:
    return float(np.sqrt(m2 / (n - 1))) if n >= MIN_PER_CLASS else 0.0


def balanced_classes(n_per_class: int, rng: np.random.Generator) -> np.ndarray:
    """A random interleaving of exactly `n_per_class` zeros and as many ones (uint8)."""
    if n_per_class < 1:
        raise ValueError("n_per_class must be positive")
    c = np.zeros(2 * n_per_class, dtype=np.uint8)
    c[n_per_class:] = 1
    rng.shuffle(c)
    return c


def analyse(times: Any, classes: Any, calibration: Any, *, batch: int = 1000,
            threshold: float = T_THRESHOLD) -> dict[str, Any]:
    """Run the whole test over saved measurements (the same code path as the live harness): the
    thresholds from `calibration`, then online updates in batches with one t-curve point per batch."""
    x, c = np.asarray(times, dtype=np.float64), np.asarray(classes)
    test = OnlineTTest(crop_thresholds(calibration))
    for i in range(0, x.size, batch):
        test.update(x[i:i + batch], c[i:i + batch])
        test.checkpoint()
    return {**test.result(threshold), "curve": test.curve}


def plot_curve(path: Any, curve: list[dict[str, float]], title: str, threshold: float = T_THRESHOLD) -> None:
    """The t-curve: |t| of the raw test and max |t| over all tests against the measurements per class."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = [0.5 * (p["n0"] + p["n1"]) for p in curve]
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ax.plot(n, [abs(p["t_raw"]) for p in curve], label="|t|, raw measurements", linewidth=1.2)
    ax.plot(n, [p["max_abs_t"] for p in curve], label="max |t| over raw + percentile crops", linewidth=1.2)
    ax.axhline(threshold, color="tab:red", linestyle="--", linewidth=1.0, label=f"threshold {threshold}")
    ax.set_xlabel("measurements per class")
    ax.set_ylabel("|t| (Welch)")
    ax.set_xscale("log")
    ax.set_yscale("symlog", linthresh=10.0)
    ax.set_title(title, fontsize=9)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
