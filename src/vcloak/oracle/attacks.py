"""Order-recovery attack on a database dump (ported from seed/vcloak_oracle.py).

The attacker sees the physical order of the rows and each row's visible round (`win`). Ground truth
(`truth`, and optionally `conv`) is supplied by the evaluation only and is never visible to the attacker.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy import stats


def _tau(a: np.ndarray, b: np.ndarray) -> float:
    return float(stats.kendalltau(a, b).statistic) if len(a) >= 2 else float("nan")


def order_recovery_attack(wins: Sequence[int] | np.ndarray, truth: Sequence[int] | np.ndarray,
                          conv: Sequence[int] | np.ndarray | None = None) -> dict[str, float]:
    """The attacker's best guess: sort by visible round, then by physical position.

    All arguments are in physical (dump) order: `wins[p]` is the visible round of the row at position p,
    `truth[p]` its true global arrival rank, `conv[p]` its conversation. Returns
      tau_global, tau_within_round (size-weighted over rounds with >= 3 rows), rounds_with_3plus,
      adjacent_pair_accuracy,
    and, when `conv` is given (worst case: the attacker knows every row's conversation),
      turn_order_accuracy       fraction of consecutive same-conversation messages ordered correctly,
      turns_same_round_frac     f, the fraction of those turns whose two messages share a visible round,
      turn_accuracy_same_round  the accuracy restricted to those turns (the granularity V-cloak protects).
    """
    wins = np.asarray(wins)
    truth = np.asarray(truth)
    guess = np.argsort(wins, kind="stable")
    t, w = truth[guess], wins[guess]
    res: dict[str, float] = {"tau_global": _tau(np.arange(len(t)), t)}

    taus, weights = [], []
    bounds = np.flatnonzero(np.diff(w)) + 1
    for g in np.split(np.arange(len(t)), bounds):
        if len(g) >= 3:
            tau = _tau(np.arange(len(g)), t[g])
            if not np.isnan(tau):
                taus.append(tau)
                weights.append(len(g))
    res["tau_within_round"] = float(np.average(taus, weights=weights)) if taus else float("nan")
    res["rounds_with_3plus"] = len(taus)
    res["adjacent_pair_accuracy"] = float((t[:-1] < t[1:]).sum() / max(1, len(t) - 1))

    if conv is not None:
        c = np.asarray(conv)[guess]
        by_conv = np.lexsort((t, c))  # guess positions, grouped by conversation in true order
        a, b = by_conv[:-1], by_conv[1:]
        turn = c[a] == c[b]
        hit = (a < b) & turn
        same = (w[a] == w[b]) & turn
        tot, n_same = int(turn.sum()), int(same.sum())
        res["turn_order_accuracy"] = float(hit.sum() / max(1, tot))
        res["turns_same_round_frac"] = float(n_same / max(1, tot))
        res["turn_accuracy_same_round"] = float((hit & same).sum() / n_same) if n_same else float("nan")
    return res
