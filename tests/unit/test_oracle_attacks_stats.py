"""M01 S4: the order-recovery attack and the uniformity statistics."""
from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats as sps
from testkeys import TEST_K_MASTER

from vcloak.oracle.attacks import order_recovery_attack
from vcloak.oracle.reference import RefKeys, epoch_permutation_ref, reshuffle_permutation_ref
from vcloak.oracle.stats import (
    chi2_uniformity,
    ideal_sampler_counts,
    kendall_band,
    kendall_sigma,
    kendall_tau,
    position_counts,
)

KEYS = RefKeys.from_master(TEST_K_MASTER)


def _traffic(n: int, n_conv: int, per_round: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(wins, truth, conv) in arrival order."""
    rng = np.random.default_rng(seed)
    truth = np.arange(n)
    return truth // per_round, truth, rng.integers(0, n_conv, n)


def _seed_attack(wins: list[int], truth: list[int], conv: list[int]) -> dict[str, float]:
    """The seed's loop-and-dict formulation, kept as an independent check of the vectorised port."""
    guess = sorted(range(len(wins)), key=lambda p: (wins[p], p))
    tr = np.array([truth[p] for p in guess])
    res = {"tau_global": float(sps.kendalltau(np.arange(len(guess)), tr).statistic)}
    groups: dict[int, list[int]] = {}
    for g, p in enumerate(guess):
        groups.setdefault(wins[p], []).append(g)
    taus, w = [], []
    for gs in groups.values():
        if len(gs) >= 3:
            taus.append(sps.kendalltau(np.arange(len(gs)), tr[gs]).statistic)
            w.append(len(gs))
    res["tau_within_round"] = float(np.average(taus, weights=w))
    res["rounds_with_3plus"] = len(taus)
    res["adjacent_pair_accuracy"] = sum(1 for a, b in zip(tr[:-1], tr[1:], strict=True) if a < b) / (len(tr) - 1)
    pos = {truth[p]: g for g, p in enumerate(guess)}
    rnd = {truth[p]: wins[p] for p in guess}
    conv_of = dict(zip(truth, conv, strict=True))
    by_conv: dict[int, list[int]] = {}
    for t in sorted(pos):
        by_conv.setdefault(conv_of[t], []).append(t)
    ok = tot = same = ok_same = 0
    for seq in by_conv.values():
        for a, b in zip(seq[:-1], seq[1:], strict=True):
            tot += 1
            hit = pos[a] < pos[b]
            ok += hit
            if rnd[a] == rnd[b]:
                same += 1
                ok_same += hit
    res["turn_order_accuracy"] = ok / tot
    res["turns_same_round_frac"] = same / tot
    res["turn_accuracy_same_round"] = ok_same / same
    return res


def test_conventional_layout_is_fully_recovered() -> None:
    """S4 check: rows stored in arrival order give tau = 1.0 and turn accuracy 1.0."""
    wins, truth, conv = _traffic(600, 20, 25, seed=1)
    res = order_recovery_attack(wins, truth, conv)
    assert res["tau_global"] == pytest.approx(1.0) and res["tau_within_round"] == pytest.approx(1.0)
    assert res["turn_order_accuracy"] == 1.0 and res["turn_accuracy_same_round"] == 1.0
    assert res["adjacent_pair_accuracy"] == 1.0 and res["rounds_with_3plus"] == 24
    assert 0.0 < res["turns_same_round_frac"] < 1.0


def test_reversed_layout_is_fully_wrong() -> None:
    truth = np.arange(200)[::-1]
    res = order_recovery_attack(np.zeros(200, dtype=int), truth, np.arange(200) % 7)
    assert res["tau_global"] == pytest.approx(-1.0) and res["turn_order_accuracy"] == 0.0
    assert res["turns_same_round_frac"] == 1.0


def test_without_conversations_only_order_metrics_are_returned() -> None:
    wins, truth, _ = _traffic(50, 5, 10, seed=2)
    assert set(order_recovery_attack(wins, truth)) == {
        "tau_global", "tau_within_round", "rounds_with_3plus", "adjacent_pair_accuracy"}


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_port_matches_the_seed_formulation(seed: int) -> None:
    rng = np.random.default_rng(seed)
    wins, truth, conv = _traffic(400, 12, 37, seed)
    order = np.concatenate([rng.permutation(np.flatnonzero(wins == w)) for w in np.unique(wins)])
    order = order[rng.permutation(len(order))] if seed == 3 else order  # seed 3: rounds interleaved on disk
    w, t, c = wins[order], truth[order], conv[order]
    got, want = order_recovery_attack(w, t, c), _seed_attack(w.tolist(), t.tolist(), c.tolist())
    assert set(got) == set(want)
    for key, value in want.items():
        assert got[key] == pytest.approx(value, abs=1e-12), key


def test_vcloak_window_layout_hides_order_within_the_round() -> None:
    """Rows of each window stored in the reference re-shuffle order: no better than a coin flip inside a round."""
    n_win, per_win = 6, 1024
    wins, truth, conv = _traffic(n_win * per_win, 40, per_win, seed=4)
    order = np.concatenate([w * per_win + reshuffle_permutation_ref(KEYS.k_tag, w, per_win).astype(np.int64)
                            for w in range(n_win)])
    res = order_recovery_attack(wins[order], truth[order], conv[order])
    assert abs(res["tau_within_round"]) < 3 * kendall_sigma(per_win)
    assert abs(res["turn_accuracy_same_round"] - 0.5) < 0.05
    assert res["tau_global"] > 0.5  # the coarse round is still visible, by design (ADR-004)


def test_chi2_accepts_oracle_and_ideal_sampler_and_rejects_bias() -> None:
    n, reps = 32, 1500
    oracle = chi2_uniformity(position_counts((epoch_permutation_ref(KEYS.k_tag, e, n) for e in range(reps)), n))
    ideal = chi2_uniformity(ideal_sampler_counts(n, reps, np.random.default_rng(11)))
    assert oracle["dof"] == ideal["dof"] == 31 * 31 and oracle["reps"] == reps
    for res in (oracle, ideal):
        assert res["p_value"] > 0.001 and 0.85 < res["chi2"] / res["dof"] < 1.15
        assert 0.0 < res["mean_tvd"] < 0.1
    rng = np.random.default_rng(12)
    biased = position_counts((np.arange(n) if r % 10 == 0 else rng.permutation(n) for r in range(reps)), n)
    assert chi2_uniformity(biased)["p_value"] < 1e-9


def test_chi2_correction_factor_and_table_validation() -> None:
    counts = ideal_sampler_counts(8, 500, np.random.default_rng(3))
    exp = 500 / 8
    pearson = float(((counts - exp) ** 2 / exp).sum())
    assert chi2_uniformity(counts)["chi2"] == pytest.approx(pearson * 7 / 8)
    with pytest.raises(ValueError):
        chi2_uniformity(np.ones((4, 5), dtype=np.int64))
    bad = counts.copy()
    bad[0, 0] += 1
    with pytest.raises(ValueError):
        chi2_uniformity(bad)


def test_kendall_sigma_and_band() -> None:
    assert kendall_sigma(2) == pytest.approx(1.0)
    assert kendall_sigma(65536) == pytest.approx(math.sqrt(2 * (2 * 65536 + 5) / (9 * 65536 * 65535)))
    assert kendall_tau(np.arange(100)) == pytest.approx(1.0) and kendall_tau(np.arange(100)[::-1]) == pytest.approx(-1.0)
    n, epochs = 1024, 60
    band = kendall_band((kendall_tau(epoch_permutation_ref(KEYS.k_tag, e, n)) for e in range(epochs)), n)
    assert band["epochs"] == epochs and band["band_3sigma"] == pytest.approx(3 * kendall_sigma(n))
    assert band["frac_in_band"] >= 0.95 and abs(band["mean_tau"]) < band["sigma_theory"]
    assert 0.6 * band["sigma_theory"] < band["std_tau"] < 1.4 * band["sigma_theory"]
    identity = kendall_band([1.0, 1.0], n)
    assert identity["frac_in_band"] == 0.0 and identity["max_abs_tau"] == 1.0
