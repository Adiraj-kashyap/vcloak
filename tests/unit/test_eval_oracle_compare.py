"""M14 S7: the device-against-oracle table. All inputs are synthetic; nothing here is a measurement."""
from __future__ import annotations

import copy
from typing import Any

import pytest

from vcloak.eval import oracle_compare as oc


def _attack(tau_g: float, tau_w: float, acc: float, f: float) -> dict[str, float]:
    return {"tau_global": tau_g, "tau_within_round": tau_w, "turn_order_accuracy": acc, "turns_same_round_frac": f}


def _device() -> dict[str, Any]:
    lay = {
        "BASELINE": {"layout": "BASELINE", "attack": _attack(1.0, 1.0, 1.0, 0.9)},
        "EPOCH": {"layout": "EPOCH", "attack": _attack(0.999, 0.001, 0.98, 0.04),
                  "occupancy": {"peak": 3, "mean": 1.1}},
        "W60": {"layout": "W60", "attack": _attack(0.93, -0.002, 0.556, 0.88), "occupancy": {"peak": 90, "mean": 26.5},
                "e0": {}},
    }
    return {
        "s1": {"seed": 7, "messages": 500},
        "e1": {"seed": 7, "layouts": lay, "params": {"n_conv": 20, "duration_s": 90, "buckets": 8, "slots": 64}},
        "e0": {"conversations_checked": 6, "exact_order": 6, "cand_k": 128},
        "e2": {"chi2": {"n": 8, "reps": 100, "chi2": 50.0, "p_value": 0.4,
                        "ideal_sampler": {"tables": 5, "chi2_min": 30.0, "chi2_max": 70.0}},
               "tau_band": {"n": 64, "epochs": 1000, "sigma_theory": 0.08, "std_tau": 0.081, "frac_in_band": 0.997,
                            "binomial_99_bounds": [992, 1000]}},
        "e3": {"sort": {"n": 16, "device_distinct_traces": 1, "merge_sort_distinct_traces": 4}},
    }


def _oracle() -> dict[str, Any]:
    return {
        "seed": 7,
        "traffic": {"conversations": 20, "duration_s": 90, "buckets": 8, "slots_per_epoch": 64, "messages": 500},
        "E1_attack": {"conventional": _attack(1.0, 1.0, 1.0, 0.15), "epoch_200ms": _attack(0.9991, 0.0, 0.981, 0.04),
                      "window_60s": _attack(0.931, 0.001, 0.558, 0.88)},
        "E0_candidate_K": {"K": 128, "max_occupancy": 95, "mean_occupancy": 26.4},
        "E0_restoration": {"conversations_checked": 6, "exact_order": 6},
        "E2_uniformity": {"n": 8, "epochs": 100, "chi2": 45.0, "p_value": 0.6},
        "E2_tau_band": {"n": 64, "epochs": 1000, "std_tau": 0.079, "frac_in_band": 0.996},
        "E3_trace": {"n": 16, "bitonic_distinct_traces": 1, "mergesort_distinct_traces": 4},
    }


def _reps() -> list[dict[str, Any]]:
    out = []
    for d in (-0.002, -0.001, 0.0, 0.001, 0.002):
        out.append({"attack": {"epoch_200ms": _attack(0.999 + d / 10, d, 0.98 + d, 0.04),
                               "window_60s": _attack(0.93 + d, d, 0.556 + d, 0.88)},
                    "occupancy": {"peak": 92 + int(d * 2000), "mean": 26.5 + d}})
    return out


def _by(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["quantity"]: r for r in result["rows"]}


def test_verdicts_of_an_agreeing_pair() -> None:
    res = oc.compare(_device(), _oracle(), _reps())
    rows = _by(res)
    assert res["counts"][oc.DIFFERS] == 0 and sum(res["counts"].values()) == len(res["rows"])
    assert rows["messages"]["verdict"] == oc.EQUAL
    assert rows["turn-order accuracy, BASELINE"]["verdict"] == oc.EQUAL
    assert rows["f (turns inside one visible round), W60"]["verdict"] == oc.EQUAL
    assert rows["turn-order accuracy, W60"]["verdict"] == oc.WITHIN
    assert rows["peak bucket-window occupancy, W60"]["verdict"] == oc.WITHIN
    assert rows["chi-square statistic, n 8"]["verdict"] == oc.WITHIN
    # two quantities are defined differently on the two sides: shown, never judged
    assert rows["f (turns inside one visible round), BASELINE"]["verdict"] == oc.NOT_COMPARABLE
    assert rows["candidate set size K"]["verdict"] == oc.NOT_COMPARABLE
    # 3 attack numbers for each shuffled layout plus the two occupancies share the level
    assert res["spread_rows"] == 8 and res["per_row_alpha"] == pytest.approx(0.01 / 8)


def test_a_key_dependent_value_outside_the_interval_differs() -> None:
    dev = _device()
    dev["e1"]["layouts"]["W60"]["attack"]["turn_order_accuracy"] = 0.70
    res = oc.compare(dev, _oracle(), _reps())
    row = _by(res)["turn-order accuracy, W60"]
    assert row["verdict"] == oc.DIFFERS and row["lo"] < 0.556 < row["hi"] < 0.70
    assert res["counts"][oc.DIFFERS] == 1


def test_a_traffic_fixed_value_must_be_equal() -> None:
    dev = _device()
    dev["e1"]["layouts"]["W60"]["attack"]["turns_same_round_frac"] = 0.8801
    dev["s1"]["messages"] = 501
    rows = _by(oc.compare(dev, _oracle(), _reps()))
    assert rows["f (turns inside one visible round), W60"]["verdict"] == oc.DIFFERS
    assert rows["messages"]["verdict"] == oc.DIFFERS


def test_uniformity_rows_need_both_sides_inside() -> None:
    ora = _oracle()
    ora["E2_uniformity"]["chi2"] = 71.0  # outside the ideal-sampler range of the device run
    ora["E2_tau_band"]["frac_in_band"] = 0.990  # below the binomial bounds
    rows = _by(oc.compare(_device(), ora, _reps()))
    assert rows["chi-square statistic, n 8"]["verdict"] == oc.DIFFERS
    assert rows["tau inside 3 sigma (%), n 64"]["verdict"] == oc.DIFFERS
    assert rows["standard deviation of tau"]["verdict"] == oc.WITHIN


def test_no_spread_over_the_repetitions_means_exact() -> None:
    reps = _reps()
    for r in reps:
        r["occupancy"]["peak"] = 90
    row = _by(oc.compare(_device(), _oracle(), reps))["peak bucket-window occupancy, W60"]
    assert row["verdict"] == oc.EQUAL and row["oracle"] == 95


@pytest.mark.parametrize("change", [("seed", 8), ("traffic.conversations", 21), ("E2_tau_band.epochs", 10),
                                    ("E3_trace.n", 32)])
def test_other_seed_or_sizes_are_not_compared(change: tuple[str, int]) -> None:
    ora = copy.deepcopy(_oracle())
    *path, last = change[0].split(".")
    node = ora
    for p in path:
        node = node[p]
    node[last] = change[1]
    with pytest.raises(oc.CompareError):
        oc.compare(_device(), ora, _reps())


def test_one_repetition_gives_no_spread() -> None:
    with pytest.raises(oc.CompareError):
        oc.compare(_device(), _oracle(), _reps()[:1])


def test_metrics_carry_the_oracle_side_and_the_counts() -> None:
    res = oc.compare(_device(), _oracle(), _reps())
    ms = {m["id"]: m["value"] for m in oc.metrics(res, "seed 7")}
    assert ms["S-ORACLE-TURNACC-W60"] == 0.558 and ms["S-ORACLE-TRAFFIC-MSGS"] == 500
    assert ms["S-ORACLE-CMP-DIFFERS"] == 0 and ms["S-ORACLE-CMP-WITHIN-NOISE"] == res["counts"][oc.WITHIN]
    assert len(ms) == len(res["rows"]) + len(oc.VERDICTS)  # one id per row: no id is used twice


def test_layout_names() -> None:
    assert [oc.oracle_layout(k) for k in ("BASELINE", "EPOCH", "W300")] == ["conventional", "epoch_200ms",
                                                                            "window_300s"]
