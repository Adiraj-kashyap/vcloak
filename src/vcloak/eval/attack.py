"""The order-recovery attack on a dump of the real store (M14 S3), and the occupancy of its buckets (S2).

The attacker holds a copy of the table: the rows in physical order, each with its visible round. The
evaluation finds the true arrival rank and the conversation of a row by the SHA-256 of its ciphertext
(`traffic.Replay.by_digest`); the server and the attacker never see either.

A dump row is a `StoredRow` of the V-cloak store or an `(id, win, payload)` tuple of the baseline.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from vcloak.eval import traffic
from vcloak.oracle.attacks import order_recovery_attack


def _win_payload(row: Any) -> tuple[int, bytes]:
    if isinstance(row, tuple):
        return int(row[1]), bytes(row[2])
    return int(row.win), bytes(row.payload)


def dump_columns(rows: Sequence[Any],
                 by_digest: Mapping[bytes, traffic.Event]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(wins, truth, conv) of a dump, in its physical order. A row that was never sent is a KeyError."""
    wins = np.empty(len(rows), dtype=np.int64)
    truth = np.empty(len(rows), dtype=np.int64)
    conv = np.empty(len(rows), dtype=np.int64)
    for p, row in enumerate(rows):
        win, payload = _win_payload(row)
        ev = by_digest[traffic.digest(payload)]
        wins[p], truth[p], conv[p] = win, ev.truth, ev.conv
    return wins, truth, conv


def attack_dump(rows: Sequence[Any], by_digest: Mapping[bytes, traffic.Event]) -> dict[str, float]:
    """The attack of the oracle on this dump, in the worst case for the defender (the attacker knows the
    conversation of every row), plus `predicted_turn_accuracy` = 1 - f/2: what the turn-order accuracy
    is if the turns inside one visible round are coin flips and every other turn is recovered."""
    wins, truth, conv = dump_columns(rows, by_digest)
    res = order_recovery_attack(wins, truth, conv)
    res["rows"] = len(rows)
    res["visible_rounds"] = int(len(np.unique(wins)))
    res["predicted_turn_accuracy"] = 1 - res["turns_same_round_frac"] / 2
    return res


def occupancy(rows: Sequence[Any]) -> dict[str, float]:
    """Real rows per (bucket, window) of a V-cloak dump: what CAND_K has to exceed."""
    occ = Counter((int(r.bucket), int(r.win)) for r in rows)
    if not occ:
        return {"bucket_windows": 0, "peak": 0, "mean": float("nan")}
    return {"bucket_windows": len(occ), "peak": max(occ.values()), "mean": float(np.mean(list(occ.values())))}
