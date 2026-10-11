"""M07 S2/S4: the derived-metric formulas of ai/GPU_GUIDE.md §5. Inputs are made-up medians: the tests
check arithmetic and the crossover rule, not performance."""
from __future__ import annotations

import pytest

from vcloak.bench import derive
from vcloak.oracle.reference import bitonic_stages

OBL = ("oracle_bitonic", "views_bitonic")


@pytest.mark.parametrize("n", [2, 64, 1024, 65536])
def test_rounds_match_the_network(n: int) -> None:
    assert derive.rounds(n) == len(list(bitonic_stages(n)))
    assert derive.compare_exchanges(n) == derive.rounds(n) * n // 2
    assert derive.bitonic_bytes(n) == derive.rounds(n) * n * 48


def test_rounds_rejects_non_powers_of_two() -> None:
    with pytest.raises(ValueError):
        derive.rounds(48)


def test_rates() -> None:
    assert derive.per_second(1000, 2.0) == pytest.approx(500_000.0)
    assert derive.gbs(4_000_000_000, 500.0) == pytest.approx(8.0)
    n = 1024
    eff = derive.gbs(derive.bitonic_bytes(n), 1.0)
    assert derive.bandwidth_pct(n, 1.0, 320.0) == pytest.approx(100 * eff / 320.0)
    assert derive.bandwidth_pct(n, 1.0, None) is None


def pt(ms: float, unstable: bool = False) -> dict:
    return {"median_ms": ms, "unstable": unstable}


def table(gpu_ms: list[float], cpu_ms: list[float], unstable_at: int | None = None) -> list[dict]:
    ns = [1 << (10 + i) for i in range(len(gpu_ms))]
    gpu = {n: pt(g, n == unstable_at) for n, g in zip(ns, gpu_ms, strict=True)}
    cpu = {"oracle_bitonic": {n: pt(c * 3) for n, c in zip(ns, cpu_ms, strict=True)},
           "views_bitonic": {n: pt(c) for n, c in zip(ns, cpu_ms, strict=True)},
           "lexsort": {n: pt(c / 100) for n, c in zip(ns, cpu_ms, strict=True)}}
    return derive.compare(gpu, cpu, OBL)


def test_compare_uses_the_best_listed_baseline_only() -> None:
    rows = table([1.0, 1.0], [0.5, 4.0])
    assert [r["cpu_baseline"] for r in rows] == ["views_bitonic", "views_bitonic"]  # never lexsort
    assert rows[0]["speedup"] == pytest.approx(0.5) and not rows[0]["gpu_faster"]
    assert rows[1]["speedup"] == pytest.approx(4.0) and rows[1]["gpu_faster"]


def test_crossover_kinds() -> None:
    x = derive.crossover(table([1.0, 1.0, 1.0, 1.0], [0.5, 0.8, 2.0, 9.0]))
    assert (x["kind"], x["n"], x["unstable"]) == ("at", 4096, False)
    x = derive.crossover(table([1.0, 1.0], [2.0, 9.0]))
    assert (x["kind"], x["n"]) == ("at_or_below", 1024)
    x = derive.crossover(table([1.0, 1.0], [0.5, 0.9]))
    assert (x["kind"], x["n"]) == ("none", None)
    assert derive.crossover([])["kind"] == "no_data"


def test_crossover_needs_the_gpu_to_stay_ahead() -> None:
    # faster at 2^11, slower again at 2^12: n* is where it is faster for good
    x = derive.crossover(table([1.0, 1.0, 1.0, 1.0], [0.5, 2.0, 0.9, 9.0]))
    assert (x["kind"], x["n"]) == ("at", 8192)


def test_crossover_flags_unstable_inputs_at_the_edge() -> None:
    assert derive.crossover(table([1.0, 1.0, 1.0], [0.5, 2.0, 9.0], unstable_at=2048))["unstable"]
    assert derive.crossover(table([1.0, 1.0, 1.0], [0.5, 2.0, 9.0], unstable_at=1024))["unstable"]
    assert not derive.crossover(table([1.0, 1.0, 1.0], [0.5, 2.0, 9.0], unstable_at=4096))["unstable"]


def test_compare_skips_sizes_missing_on_one_side() -> None:
    rows = derive.compare({1024: pt(1.0), 2048: pt(1.0)}, {"views_bitonic": {2048: pt(3.0)}}, OBL)
    assert [r["n"] for r in rows] == [2048]


def test_value_or_flag() -> None:
    assert derive.value_or_flag(1.23456789, False, 4) == 1.2346
    assert derive.value_or_flag(1.2, True) == "UNSTABLE"
    assert derive.value_or_flag(None, False) == "NOT_MEASURED"
