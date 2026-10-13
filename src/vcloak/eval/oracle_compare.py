"""The numbers of the real stack beside the numbers of the CPU oracle (M14 S7).

Nothing here measures. `compare` takes the stage files of the device runs, the `results.json` the seed oracle
(`seed/vcloak_oracle.py`) wrote for the same seed and sizes, and a list of repetitions of the oracle's attack
with fresh keys, and returns one row per quantity with a verdict:

EQUAL           the quantity does not depend on the keys (it is fixed by the traffic or by the schedule) and the
                two values agree to 1e-9.
WITHIN_NOISE    the quantity depends on the keys. Either the device value lies inside the prediction interval of
                the oracle repetitions (mean +- t * sd * sqrt(1 + 1/R), two-sided, level `family_alpha` shared
                over all such rows, Bonferroni), or - for the uniformity statistics, where theory gives the
                interval - both values lie inside it.
DIFFERS         anything else. A difference is a finding: the caller opens an issue, it is never dropped.
NOT_COMPARABLE  the two sides do not define the quantity the same way; both values are shown, with the reason.

The oracle and the device use different keys (the oracle draws its keys from the OS at every run), so a
key-dependent quantity is never expected to be equal, only to come from the same distribution. The prediction
interval treats the oracle repetitions as normal; for the peak occupancy (a maximum of counts) that is rough.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from typing import Any

from scipy import stats

EQUAL, WITHIN, DIFFERS, NOT_COMPARABLE = "EQUAL", "WITHIN_NOISE", "DIFFERS", "NOT_COMPARABLE"
VERDICTS = (EQUAL, WITHIN, DIFFERS, NOT_COMPARABLE)
TOL = 1e-9
ORACLE_PREFIX = "S-ORACLE-"
COLUMNS = ("experiment", "quantity", "device_metric", "device", "oracle_metric", "oracle", "kind", "lo", "hi",
           "verdict", "criterion")
ATTACK_FIELDS = (("TAU-GLOBAL", "tau_global", "global tau"), ("TAU-WITHIN", "tau_within_round", "tau within a round"),
                 ("TURNACC", "turn_order_accuracy", "turn-order accuracy"))


class CompareError(ValueError):
    """The two sides were not run with the same seed and sizes: nothing is compared."""


def oracle_layout(key: str) -> str:
    """The oracle's name of a device layout."""
    if key == "BASELINE":
        return "conventional"
    if key == "EPOCH":
        return "epoch_200ms"
    return f"window_{int(key[1:])}s"


def oracle_metric(device_metric: str) -> str:
    return ORACLE_PREFIX + device_metric.removeprefix("S-")


def prediction_interval(samples: Sequence[float], alpha: float) -> dict[str, float]:
    """Two-sided prediction interval for one further draw, from `samples` taken as normal."""
    r = len(samples)
    if r < 2:
        raise CompareError(f"{r} oracle repetitions: a spread needs at least 2")
    mean, sd = statistics.fmean(samples), statistics.stdev(samples)
    half = float(stats.t.ppf(1 - alpha / 2, r - 1)) * sd * math.sqrt(1 + 1 / r)
    return {"mean": mean, "sd": sd, "lo": mean - half, "hi": mean + half, "min": min(samples), "max": max(samples)}


def sd_interval(sigma: float, n: int, alpha: float = 0.01) -> tuple[float, float]:
    """Central interval of the sample standard deviation of `n` normal draws of standard deviation `sigma`."""
    lo, hi = stats.chi2.ppf([alpha / 2, 1 - alpha / 2], n - 1)
    return sigma * math.sqrt(lo / (n - 1)), sigma * math.sqrt(hi / (n - 1))


def check_params(device: dict[str, Any], oracle: dict[str, Any]) -> dict[str, bool]:
    """Seed and sizes of the two sides, one boolean per item."""
    dp, tr = device["e1"]["params"], oracle["traffic"]
    chi, band = device["e2"]["chi2"], device["e2"]["tau_band"]
    return {
        "same_seed": device["e1"]["seed"] == oracle["seed"] == device["s1"]["seed"],
        "same_conversations": dp["n_conv"] == tr["conversations"],
        "same_duration": dp["duration_s"] == tr["duration_s"],
        "same_buckets": dp["buckets"] == tr["buckets"],
        "same_slots": dp["slots"] == tr["slots_per_epoch"],
        "same_chi2_size": (chi["n"], chi["reps"]) == (oracle["E2_uniformity"]["n"], oracle["E2_uniformity"]["epochs"]),
        "same_tau_size": (band["n"], band["epochs"]) == (oracle["E2_tau_band"]["n"], oracle["E2_tau_band"]["epochs"]),
        "same_trace_size": device["e3"]["sort"]["n"] == oracle["E3_trace"]["n"],
    }


def _row(exp: str, quantity: str, metric: str | None, dev: float, ora: float, kind: str, verdict: str,
         criterion: str, lo: float | None = None, hi: float | None = None, **extra: Any) -> dict[str, Any]:
    return {"experiment": exp, "quantity": quantity, "device_metric": metric,
            "oracle_metric": oracle_metric(metric) if metric else None, "device": dev, "oracle": ora, "kind": kind,
            "lo": lo, "hi": hi, "verdict": verdict, "criterion": criterion, **extra}


def _exact(exp: str, quantity: str, metric: str | None, dev: float, ora: float, why: str) -> dict[str, Any]:
    same = math.isclose(dev, ora, rel_tol=0.0, abs_tol=TOL)
    return _row(exp, quantity, metric, dev, ora, "exact", EQUAL if same else DIFFERS, f"equal to 1e-9: {why}")


def _both_inside(exp: str, quantity: str, metric: str, dev: float, ora: float, lo: float, hi: float,
                 criterion: str) -> dict[str, Any]:
    ok = lo <= dev <= hi and lo <= ora <= hi
    return _row(exp, quantity, metric, dev, ora, "theory", WITHIN if ok else DIFFERS, criterion, lo, hi)


def compare(device: dict[str, Any], oracle: dict[str, Any], reps: Sequence[dict[str, Any]], *,
            family_alpha: float = 0.01) -> dict[str, Any]:
    """`device`: {"s1", "e1" (layouts keyed by id), "e0", "e2", "e3"}; `oracle`: the oracle's results.json;
    `reps`: [{"attack": {<oracle layout>: {...}}, "occupancy": {"peak", "mean"}}, ...] with fresh keys each."""
    checks = check_params(device, oracle)
    if not all(checks.values()):
        raise CompareError("seed or sizes differ: " + ", ".join(k for k, ok in checks.items() if not ok))
    lay, att = device["e1"]["layouts"], oracle["E1_attack"]
    e0, e2, e3 = device["e0"], device["e2"], device["e3"]
    keys = [k for k in lay if oracle_layout(k) in att]
    shuffled = [k for k in keys if k != "BASELINE"]
    occ_layout = next((k for k in shuffled if "e0" in lay[k]), None)

    # the key-dependent quantities first: their number is the size of the family the level is shared over
    spread: list[tuple[str, str, str, float, float, list[float]]] = []
    for k in shuffled:
        o = oracle_layout(k)
        for tag, field, label in ATTACK_FIELDS:
            spread.append(("E1", f"{label}, {k}", f"S-{tag}-{k}", lay[k]["attack"][field], att[o][field],
                           [r["attack"][o][field] for r in reps]))
    if occ_layout is not None:
        occ, ock = lay[occ_layout]["occupancy"], oracle["E0_candidate_K"]
        spread += [("E0", f"peak bucket-window occupancy, {occ_layout}", "S-OCC-PEAK", occ["peak"],
                    ock["max_occupancy"], [r["occupancy"]["peak"] for r in reps]),
                   ("E0", f"mean bucket-window occupancy, {occ_layout}", "S-OCC-MEAN", occ["mean"],
                    ock["mean_occupancy"], [r["occupancy"]["mean"] for r in reps])]
    alpha = family_alpha / max(1, len(spread))

    rows = [_exact("S1", "messages", "S-TRAFFIC-MSGS", device["s1"]["messages"], oracle["traffic"]["messages"],
                   "same generator state, same draws")]
    rows.append(_exact("E0", "conversations read back in exact order", "S-E0-RESTORE", e0["exact_order"],
                       oracle["E0_restoration"]["exact_order"],
                       f"all of {e0['conversations_checked']} on both sides (the conversations drawn differ)"))
    if occ_layout is not None:
        rows.append(_row("E0", "candidate set size K", "S-CANDK", e0["cand_k"], oracle["E0_candidate_K"]["K"],
                         "definition", NOT_COMPARABLE, "the device uses the public parameter CAND_K; the oracle "
                         "derives K from the peak occupancy of its own run (next power of two)"))
    if "BASELINE" in keys:
        a, o = lay["BASELINE"]["attack"], att["conventional"]
        for tag, field, label in ATTACK_FIELDS:
            rows.append(_exact("E1", f"{label}, BASELINE", f"S-{tag}-BASELINE", a[field], o[field],
                               "arrival order is stored, no key is involved"))
        rows.append(_row("E1", "f (turns inside one visible round), BASELINE", "S-F-BASELINE",
                         a["turns_same_round_frac"], o["turns_same_round_frac"], "definition", NOT_COMPARABLE,
                         "the baseline service stores the window as the visible round; the oracle's conventional "
                         "layout stores the second of arrival"))
    for k in shuffled:
        rows.append(_exact("E1", f"f (turns inside one visible round), {k}", f"S-F-{k}",
                           lay[k]["attack"]["turns_same_round_frac"], att[oracle_layout(k)]["turns_same_round_frac"],
                           "fixed by the arrival times and the round length"))
    for exp, quantity, metric, dev, ora, samples in spread:
        pi = prediction_interval(samples, alpha)
        if pi["sd"] == 0.0:
            row = _exact(exp, quantity, metric, dev, pi["mean"], "no spread over the oracle repetitions")
            row["oracle"] = ora
        else:
            row = _row(exp, quantity, metric, dev, ora, "spread", WITHIN if pi["lo"] <= dev <= pi["hi"] else DIFFERS,
                       f"device value inside the prediction interval of {len(samples)} oracle repetitions with "
                       f"fresh keys, per-row level {alpha:.3g}", pi["lo"], pi["hi"])
        row.update({"oracle_reps": {k: pi[k] for k in ("mean", "sd", "min", "max")},
                    "oracle_run_inside": pi["lo"] - TOL <= ora <= pi["hi"] + TOL})
        rows.append(row)

    chi, band, ou, ob = e2["chi2"], e2["tau_band"], oracle["E2_uniformity"], oracle["E2_tau_band"]
    ideal = chi["ideal_sampler"]
    rows.append(_both_inside("E2", f"chi-square statistic, n {chi['n']}", "S-CHI2", chi["chi2"], ou["chi2"],
                             ideal["chi2_min"], ideal["chi2_max"],
                             f"both inside the range of the {ideal['tables']} ideal-sampler tables of the device run"))
    rows.append(_both_inside("E2", "chi-square p-value", "S-CHI2-P", chi["p_value"], ou["p_value"], 0.01, 1.0,
                             "both above 0.01 (the acceptance gate)"))
    lo, hi = (100 * b / band["epochs"] for b in band["binomial_99_bounds"])
    rows.append(_both_inside("E2", f"tau inside 3 sigma (%), n {band['n']}", "S-TAUBAND-PCT",
                             100 * band["frac_in_band"], 100 * ob["frac_in_band"], lo, hi,
                             f"both inside the central 99% interval of Binomial({band['epochs']}, 0.9973)"))
    lo, hi = sd_interval(band["sigma_theory"], band["epochs"])
    rows.append(_both_inside("E2", "standard deviation of tau", "S-TAU-SIGMA-MEAS", band["std_tau"], ob["std_tau"],
                             lo, hi, f"both inside the central 99% interval of the sample standard deviation of "
                             f"{band['epochs']} normal draws at the theoretical sigma"))
    sort, ot = e3["sort"], oracle["E3_trace"]
    rows.append(_exact("E3", "distinct comparator traces, bitonic sort", "S-TRACE-DISTINCT-DEVICE",
                       sort["device_distinct_traces"], ot["bitonic_distinct_traces"],
                       "the schedule depends on n only (five input classes each)"))
    rows.append(_exact("E3", "distinct comparator traces, merge sort", "S-TRACE-DISTINCT-MERGESORT",
                       sort["merge_sort_distinct_traces"], ot["mergesort_distinct_traces"],
                       "data-dependent control; the random input of the two sides differs"))

    counts = {v: sum(r["verdict"] == v for r in rows) for v in VERDICTS}
    return {"rows": rows, "counts": counts, "checks": checks, "family_alpha": family_alpha,
            "spread_rows": len(spread), "per_row_alpha": alpha, "oracle_reps": len(reps)}


def metrics(result: dict[str, Any], stat: str) -> list[dict[str, Any]]:
    """The oracle side of every row and the verdict counts, as METRICS_INDEX rows."""
    out = [{"id": r["oracle_metric"], "value": r["oracle"], "unit": "-",
            "stat": f"CPU oracle, {r['quantity']}, {stat}"} for r in result["rows"] if r["oracle_metric"]]
    out += [{"id": f"{ORACLE_PREFIX}CMP-{v.replace('_', '-')}", "value": n, "unit": "rows",
             "stat": f"rows of the device against oracle table with this verdict, of {len(result['rows'])}"}
            for v, n in result["counts"].items()]
    return out
