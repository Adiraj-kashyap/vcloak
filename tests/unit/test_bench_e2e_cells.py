"""M15 S2: the order of the cells, the bucket bound of a schedule, and the host samplers around a cell.
All inputs are synthetic; nothing here is a measurement."""
from __future__ import annotations

import csv
import importlib.util
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from vcloak.bench import e2e, hostload

ROOT = Path(__file__).resolve().parents[2]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "bench" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_two_modes_of_a_cell_run_back_to_back_and_a_repetition_is_a_full_pass() -> None:
    order = e2e.cell_order([10, 50, 200], 2)
    assert len(order) == 12
    assert order[:4] == [(1, 10, "baseline"), (1, 10, "vcloak"), (1, 50, "baseline"), (1, 50, "vcloak")]
    assert [x[0] for x in order] == [1] * 6 + [2] * 6
    with pytest.raises(ValueError):
        e2e.cell_order([10], 0)


def test_the_declared_population_is_10_50_200_users_in_pairs() -> None:
    cells = _script("run_e2e_cells")
    assert cells.USERS == (10, 50, 200) and cells.USERS_QUICK == (10, 50)  # ADR-027
    assert all(len(pair) == 2 for u in cells.USERS for pair in e2e.pairs(u))


def test_conv_tokens_are_the_tokens_of_the_generator() -> None:
    a = e2e.conv_tokens(np.random.default_rng([15, 0xE2E]), 5)
    b = e2e.conv_tokens(np.random.default_rng([15, 0xE2E]), 5)
    assert a == b and len(set(a)) == 5 and all(len(t) == 32 for t in a)


def test_bucket_span_peak_is_the_fullest_span_of_one_window_for_every_alignment() -> None:
    # conversation 0 and 1 share bucket 7; conversation 2 is alone in bucket 9
    sends = [e2e.Send(0, 0, t) for t in (1.0, 2.0, 58.0)] + [e2e.Send(2, 1, t) for t in (59.0, 61.5, 130.0)]
    sends += [e2e.Send(4, 2, 5.0)]
    peaks = e2e.bucket_span_peaks(sends, [7, 7, 9], 60.0)
    # [2.0, 62.0) holds 2.0, 58.0, 59.0 and 61.5: no fixed 60 s grid sees more than a sliding span does
    assert peaks == {7: 4, 9: 1}
    assert e2e.bucket_span_peaks(sends, [7, 7, 9], 1.0) == {7: 1, 9: 1}


def test_the_bound_of_a_cell_names_cand_k_and_calls_itself_arithmetic() -> None:
    cells = _script("run_e2e_cells")
    a = cells.build_parser().parse_args(["--rate", "0.2"])
    b = cells.bucket_bound(10, a, 140.0)
    assert (b["users"], b["conversations"], b["cand_k"], b["buckets"], b["window_s"]) == (10, 5, 128, 64, 60)
    assert 0 < b["max_sends_in_one_window_span"] and "not a measurement" in b["kind"]
    tight = cells.build_parser().parse_args(["--rate", "0.2", "--cand-k", "4"])
    over = cells.bucket_bound(10, tight, 140.0)
    assert over["buckets_that_can_exceed_cand_k"] > 0 and over["conversations_in_those_buckets"] > 0


def test_the_decided_rate_keeps_every_cell_inside_cand_k_and_0_2_does_not() -> None:
    """ISSUE-49: the reason the cells run at 0.15 messages per user per second. Arithmetic on the schedule."""
    cells = _script("run_e2e_cells")
    decided = cells.build_parser().parse_args([])
    assert decided.rate == cells.RATE == 0.15
    for users in cells.USERS:
        assert cells.bucket_bound(users, decided, 140.0)["buckets_that_can_exceed_cand_k"] == 0
    proposal = cells.bucket_bound(200, cells.build_parser().parse_args(["--rate", "0.2"]), 140.0)
    assert proposal["max_sends_in_one_window_span"] > proposal["cand_k"]


def test_every_cell_gets_the_same_seed_and_a_schema_of_its_own() -> None:
    cells = _script("run_e2e_cells")
    a = cells.build_parser().parse_args(["--out", "runs"])
    cmds = [cells.cell_command(a, rep, u, mode) for rep, u, mode in e2e.cell_order([10, 50], 2)]
    schemas = [c[c.index("--schema") + 1] for c in cmds]
    assert len(set(schemas)) == len(cmds) and all(hostload.CELL_SCHEMA_RE.fullmatch(s) for s in schemas)
    assert {c[c.index("--seed") + 1] for c in cmds} == {"15"}
    assert {c[c.index("--slots") + 1] for c in cmds} == {"256"}
    assert all("--compare" not in c and "--url" not in c for c in cmds)
    lite = cells.cell_command(cells.build_parser().parse_args(["--store", "sqlite"]), 1, 10, "vcloak")
    assert "--schema" not in lite


def test_only_a_cell_schema_can_be_dropped() -> None:
    for bad in ("public", "baseline", "e2e_", "e2e_x; drop schema public", "E2E_A"):
        with pytest.raises(ValueError):
            hostload.drop_cell_schema("host=127.0.0.1 port=1 connect_timeout=1", bad)


def test_db_size_without_a_server_is_unavailable_with_a_reason_never_zero() -> None:
    got = hostload.db_size("host=127.0.0.1 port=1 dbname=x user=x connect_timeout=1", "e2e_x")
    assert got["available"] is False and got["reason"] and "schema_bytes" not in got


def test_cpu_sampler_writes_rows_or_says_why_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hostload, "_psutil", lambda: None)
    off = hostload.CpuSampler(tmp_path / "none.csv", None).start().stop()
    assert off["available"] is False and off["reason"] == "psutil is not installed" and off["file"] is None
    assert not (tmp_path / "none.csv").exists()
    assert hostload.power_state() == {"available": False, "reason": "psutil is not installed"}
    monkeypatch.undo()
    pytest.importorskip("psutil")
    s = hostload.CpuSampler(tmp_path / "cpu.csv", None, hz=20.0).start()
    time.sleep(0.5)
    on = s.stop()
    rows = list(csv.DictReader((tmp_path / "cpu.csv").open(encoding="utf-8")))
    assert on["available"] and on["samples"] == len(rows) >= 2 and on["service_process"] is False
    assert tuple(rows[0]) == hostload.CPU_FIELDS and rows[0]["service_cpu_pct"] == ""
    assert all(0.0 <= float(r["cpu_pct"]) <= 100.0 for r in rows)
