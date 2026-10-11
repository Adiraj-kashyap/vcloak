"""Derived metrics (ai/GPU_GUIDE.md §5). Pure functions of measured medians and public parameters:
nothing here measures, and nothing here invents a value when an input is missing."""
from __future__ import annotations

from typing import Any

RECORD_BYTES = 24  # hi (8) + lo (8) + slot (4) + pay (4)
UNSTABLE = "UNSTABLE"
NM = "NOT_MEASURED"


def rounds(n: int) -> int:
    """Stages of the bitonic network: log2(n) (log2(n) + 1) / 2."""
    if n < 1 or n & (n - 1):
        raise ValueError(f"n must be a power of two, got {n}")
    lg = n.bit_length() - 1
    return lg * (lg + 1) // 2


def compare_exchanges(n: int) -> int:
    return rounds(n) * (n // 2)


def bitonic_bytes(n: int) -> int:
    """Bytes a global-memory network moves: every stage reads and writes all n records once."""
    return rounds(n) * n * RECORD_BYTES * 2


def per_second(count: int, median_ms: float) -> float:
    return count / (median_ms / 1e3)


def gbs(nbytes: int, median_ms: float) -> float:
    return nbytes / 1e9 / (median_ms / 1e3)


def bandwidth_pct(n: int, median_ms: float, peak_gbs: float | None) -> float | None:
    """Effective bitonic bandwidth as a percentage of the theoretical peak; None without a peak."""
    return None if not peak_gbs else 100.0 * gbs(bitonic_bytes(n), median_ms) / peak_gbs


def best_cpu(cpu: dict[str, dict[int, dict[str, Any]]], n: int, names: tuple[str, ...]) -> tuple[str, dict] | None:
    """(baseline name, point) of the fastest of `names` that has a median at n, or None."""
    have = [(cpu[b][n]["median_ms"], b) for b in names if n in cpu.get(b, {}) and cpu[b][n].get("median_ms")]
    if not have:
        return None
    _, b = min(have)
    return b, cpu[b][n]


def compare(gpu: dict[int, dict[str, Any]], cpu: dict[str, dict[int, dict[str, Any]]],
            names: tuple[str, ...]) -> list[dict[str, Any]]:
    """Per n present on both sides: the GPU median (kernels + transfers), the best of the `names` CPU
    baselines, the speed-up cpu / gpu, and whether either input was flagged unstable."""
    rows = []
    for n in sorted(gpu):
        best = best_cpu(cpu, n, names)
        g = gpu[n]
        if best is None or not g.get("median_ms"):
            continue
        b, c = best
        rows.append({"n": n, "log2n": n.bit_length() - 1, "gpu_ms": g["median_ms"], "cpu_ms": c["median_ms"],
                     "cpu_baseline": b, "speedup": c["median_ms"] / g["median_ms"],
                     "gpu_faster": g["median_ms"] < c["median_ms"],
                     "unstable": bool(g.get("unstable")) or bool(c.get("unstable"))})
    return rows


def crossover(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """n*: the smallest compared n at which the GPU is faster there and at every larger compared n.

    kind is `at` (the GPU loses below n*), `at_or_below` (it is faster at every compared n, so n* is at
    most the smallest one), `none` (it is not faster at the largest compared n) or `no_data`.
    `unstable` is set when the comparison at n* or at the size just below it used an unstable input."""
    if not rows:
        return {"kind": "no_data", "n": None, "unstable": False}
    rows = sorted(rows, key=lambda r: r["n"])
    first = len(rows)
    while first > 0 and rows[first - 1]["gpu_faster"]:
        first -= 1
    if first == len(rows):
        return {"kind": "none", "n": None, "unstable": rows[-1]["unstable"], "largest_n": rows[-1]["n"]}
    edge = rows[max(first - 1, 0):first + 1]
    return {"kind": "at" if first > 0 else "at_or_below", "n": rows[first]["n"],
            "unstable": any(r["unstable"] for r in edge), "smallest_n": rows[0]["n"], "largest_n": rows[-1]["n"]}


def value_or_flag(value: float | None, unstable: bool, digits: int = 4) -> Any:
    """What goes into a metric row: the rounded value, UNSTABLE when an input was, NOT_MEASURED when absent."""
    if value is None:
        return NM
    return UNSTABLE if unstable else round(value, digits)
