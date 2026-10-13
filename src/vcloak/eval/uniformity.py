"""Uniformity of the permutations the device produces (M14 S4, experiment E2).

A permutation is produced the way `GpuEngine.write_epoch` produces it: the tags of the epoch from the
device key (`gpu_tags_for_epoch`), then the bitonic network over (tag, slot) (`gpu_bitonic_sort`).
Under the numpy backend the same calls run the thread-model simulator.

The statistics are those of the oracle (`vcloak.oracle.stats`); the gates are those of ai/TESTING.md §4:
  - corrected chi-square p-value above 0.01 AND the statistic inside the range of the ideal-sampler
    calibration (the smallest and the largest statistic of `calibration` tables drawn from NumPy's
    uniform permutation sampler with the same n and the same number of permutations);
  - the number of epochs with |tau| < 3 sigma inside the central 99% interval of Binomial(epochs, 0.9973).
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats

from vcloak.gpu.kernels import gpu_bitonic_sort, gpu_tags_for_epoch
from vcloak.gpu.keystore import DeviceKeyStore
from vcloak.oracle.stats import chi2_uniformity, kendall_band, kendall_tau

P_MIN = 0.01
BAND_COVERAGE = 0.9973  # P(|z| < 3)
BAND_CONFIDENCE = 0.99
TAU_EPOCH0 = 10**6  # the first epoch of the tau study (the oracle's offset): disjoint from the chi-square epochs


def _host(a: Any) -> np.ndarray:
    return a.get() if hasattr(a, "get") else np.asarray(a)


def epoch_permutation(keys: DeviceKeyStore, epoch: int, n: int) -> np.ndarray:
    """perm[p] = the input slot stored at position p in `epoch`."""
    xp = keys.backend.xp
    hi, lo = gpu_tags_for_epoch(keys.k_tag, epoch, n)
    slot, perm = xp.arange(n, dtype=np.uint32), xp.arange(n, dtype=np.uint32)
    gpu_bitonic_sort(hi, lo, slot, perm)
    return _host(perm).astype(np.int64)


def device_counts(keys: DeviceKeyStore, n: int, reps: int, epoch0: int = 0) -> np.ndarray:
    """counts[s, p]: how often input slot s was stored at position p over epochs epoch0 .. epoch0 + reps - 1."""
    counts = np.zeros((n, n), dtype=np.int64)
    pos = np.arange(n)
    for r in range(reps):
        counts[epoch_permutation(keys, epoch0 + r, n), pos] += 1
    return counts


def ideal_counts(n: int, reps: int, rng: np.random.Generator) -> np.ndarray:
    """The same table from NumPy's uniform permutation sampler."""
    perms = rng.permuted(np.tile(np.arange(n, dtype=np.int64), (reps, 1)), axis=1)
    return np.bincount((perms * n + np.arange(n)).ravel(), minlength=n * n).reshape(n, n)


def chi2_study(keys: DeviceKeyStore, n: int, reps: int, *, calibration: int, seed: int) -> dict[str, Any]:
    """The chi-square test of the device permutations and its calibration against the ideal sampler."""
    res: dict[str, Any] = chi2_uniformity(device_counts(keys, n, reps))
    rng = np.random.default_rng(seed)
    ideal = [chi2_uniformity(ideal_counts(n, reps, rng)) for _ in range(calibration)]
    chi = [i["chi2"] for i in ideal]
    res["ideal_sampler"] = {
        "tables": calibration, "seed": seed,
        "chi2_first": chi[0], "p_first": ideal[0]["p_value"], "mean_tvd_first": ideal[0]["mean_tvd"],
        "chi2_min": min(chi), "chi2_max": max(chi), "chi2_median": float(np.median(chi)),
        "p_min": min(i["p_value"] for i in ideal), "p_max": max(i["p_value"] for i in ideal),
    }
    res["gates"] = {"p_above_0_01": res["p_value"] > P_MIN,
                    "chi2_inside_ideal_range": min(chi) <= res["chi2"] <= max(chi)}
    return res


def tau_band_study(keys: DeviceKeyStore, n: int, epochs: int, epoch0: int = TAU_EPOCH0) -> dict[str, Any]:
    """Kendall's tau of `epochs` device permutations of n slots against the 3-sigma band of a uniform one."""
    taus = np.array([kendall_tau(epoch_permutation(keys, epoch0 + e, n)) for e in range(epochs)])
    res: dict[str, Any] = kendall_band(taus, n)
    inside = int((np.abs(taus) < res["band_3sigma"]).sum())
    lo, hi = (int(b) for b in stats.binom.interval(BAND_CONFIDENCE, epochs, BAND_COVERAGE))
    counts, edges = np.histogram(taus / res["sigma_theory"], bins=24, range=(-4, 4))
    res.update({"epoch0": epoch0, "inside_band": inside, "binomial_99_bounds": [lo, hi],
                "histogram": {"z_edges": edges.tolist(), "counts": counts.tolist()},
                "taus": taus.tolist(),
                "gates": {"coverage_inside_binomial_99_bounds": lo <= inside <= hi}})
    return res
