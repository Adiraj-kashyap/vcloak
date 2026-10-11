"""Permutation-uniformity statistics (ported from the E2 block of seed/vcloak_oracle.py).

`counts[s, p]` is how often input slot s landed at output position p over `reps` permutations.
"""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from scipy import stats


def position_counts(perms: Iterable[np.ndarray], n: int) -> np.ndarray:
    """Accumulate the (n, n) slot-by-position table; each perm has perm[p] = input slot at position p."""
    counts = np.zeros((n, n), dtype=np.int64)
    pos = np.arange(n)
    for perm in perms:
        counts[np.asarray(perm, dtype=np.int64), pos] += 1
    return counts


def ideal_sampler_counts(n: int, reps: int, rng: np.random.Generator) -> np.ndarray:
    """Calibration: the same table from NumPy's uniform permutation sampler."""
    return position_counts((rng.permutation(n) for _ in range(reps)), n)


def chi2_uniformity(counts: np.ndarray) -> dict[str, float]:
    """Corrected chi-square test of uniformity, plus the mean total-variation distance per slot.

    Rows and columns of a permutation-count table each sum to `reps`, so the Pearson statistic has
    expectation n(n-1), not n^2 - 1. Scaling by (n-1)/n gives an approximately chi2((n-1)^2) statistic.
    """
    n = counts.shape[0]
    reps = int(counts[0].sum())
    if counts.shape != (n, n) or not (counts.sum(axis=0) == reps).all() or not (counts.sum(axis=1) == reps).all():
        raise ValueError("counts is not a permutation-count table")
    exp = reps / n
    dof = (n - 1) ** 2
    chi2 = float((n - 1) / n * ((counts - exp) ** 2 / exp).sum())
    return {"n": n, "reps": reps, "chi2": chi2, "dof": dof, "p_value": float(stats.chi2.sf(chi2, dof)),
            "mean_tvd": float(0.5 * np.abs(counts / reps - 1 / n).sum(axis=1).mean())}


def kendall_sigma(n: int) -> float:
    """Standard deviation of Kendall's tau between a uniform random permutation of n items and identity."""
    return float(np.sqrt(2 * (2 * n + 5) / (9 * n * (n - 1))))


def kendall_tau(perm: np.ndarray) -> float:
    """Kendall's tau between the permutation and the identity order."""
    return float(stats.kendalltau(np.arange(len(perm)), perm).statistic)


def kendall_band(taus: Iterable[float], n: int) -> dict[str, float]:
    """Summary of observed taus against the theoretical 3-sigma band for permutations of n items."""
    taus = np.asarray(list(taus), dtype=np.float64)
    sigma = kendall_sigma(n)
    return {"n": n, "epochs": int(taus.size), "sigma_theory": sigma, "band_3sigma": 3 * sigma,
            "mean_tau": float(taus.mean()), "std_tau": float(taus.std(ddof=1)) if taus.size > 1 else float("nan"),
            "max_abs_tau": float(np.abs(taus).max()), "frac_in_band": float((np.abs(taus) < 3 * sigma).mean())}
