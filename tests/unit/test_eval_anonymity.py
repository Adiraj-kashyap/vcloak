"""M14 S6 on the numpy simulator: the anonymity-set counts of a dump, the stage, its run and its job."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import numpy as np
import pytest

from vcloak import runs
from vcloak.eval import anonymity
from vcloak.gpu.engine import StoredRow
from vcloak.gpu.runtime import get_backend
from vcloak.storage.repo import SqliteRepo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import run_security_eval as rse  # noqa: E402

SMALL = dict(seed=7, duration_s=40, buckets=4, window_s=5)


def _rows(cells: list[tuple[int, int]]) -> list[StoredRow]:
    """One stored row per (bucket, window) given."""
    return [StoredRow(uuid.uuid4(), b, w, b"s", b"p") for b, w in cells]


class TestCounts:
    def test_users_are_paired(self) -> None:
        assert [anonymity.conversations(u) for u in (2, 10, 100, 1000)] == [1, 5, 50, 500]
        for bad in (0, 1, 7, -2):
            with pytest.raises(ValueError):
                anonymity.conversations(bad)

    def test_empty_cells_are_counted_as_zero(self) -> None:
        per_window, per_cell = anonymity.cell_counts(_rows([(0, 0), (0, 0), (1, 0), (0, 2)]), 3, 2)
        assert per_window.tolist() == [3, 0, 1]
        assert per_cell.tolist() == [2, 1, 0, 0, 1, 0]  # (window, bucket), window by window

    def test_a_row_outside_the_run_is_an_error(self) -> None:
        for cell in [(0, 3), (2, 0), (-1, 0)]:
            with pytest.raises(ValueError):
                anonymity.cell_counts(_rows([cell]), 3, 2)
        with pytest.raises(ValueError):
            anonymity.cell_counts([], 0, 2)

    def test_distribution_over_cells_and_as_a_row_sees_it(self) -> None:
        d = anonymity.distribution(np.array([0, 0, 2, 6]))
        assert (d["cells"], d["empty"], d["rows"], d["min"], d["max"]) == (4, 2, 8, 0, 6)
        assert d["median"] == 1.0 and d["mean"] == 2.0
        assert d["p5"] == pytest.approx(np.percentile([0, 0, 2, 6], 5))
        assert d["msg_median"] == 6.0  # six of the eight rows sit in the cell of six
        assert d["msg_p5"] == 2.0

    def test_distribution_of_an_empty_store_has_no_row_view(self) -> None:
        d = anonymity.distribution(np.zeros(5, dtype=np.int64))
        assert d["empty"] == 5 and d["median"] == 0.0 and np.isnan(d["msg_median"]) and np.isnan(d["msg_p5"])
        with pytest.raises(ValueError):
            anonymity.distribution(np.array([], dtype=np.int64))

    def test_anonymity_holds_both_distributions(self) -> None:
        res = anonymity.anonymity(_rows([(0, 0), (1, 0), (1, 1)]), 2, 2)
        assert res["rows_per_window"] == [2, 1]
        assert res["per_window"]["cells"] == 2 and res["per_bucket_window"]["cells"] == 4
        assert res["per_window"]["rows"] == res["per_bucket_window"]["rows"] == 3


class TestStage:
    def test_a_population_is_replayed_counted_and_attacked(self) -> None:
        res = rse.run_users(SqliteRepo(), get_backend("numpy"), 24, **SMALL)
        assert res["ok"], res["checks"]
        assert (res["users"], res["conversations"], res["layout"]) == (24, 12, "W5")
        anon = res["anonymity"]
        assert anon["per_window"]["cells"] == 8 and anon["per_bucket_window"]["cells"] == 32
        assert sum(anon["rows_per_window"]) == res["messages"] == res["rows_stored"]
        assert anon["per_bucket_window"]["max"] == res["occupancy"]["peak"]
        filled = anon["per_bucket_window"]["cells"] - anon["per_bucket_window"]["empty"]
        assert filled == res["occupancy"]["bucket_windows"]
        assert 0 <= res["attack"]["turn_order_accuracy"] <= 1

    def test_more_users_fill_the_windows(self) -> None:
        few = rse.run_users(SqliteRepo(), get_backend("numpy"), 4, **SMALL)
        many = rse.run_users(SqliteRepo(), get_backend("numpy"), 40, **SMALL)
        assert many["messages"] > few["messages"]
        assert many["anonymity"]["per_window"]["median"] > few["anonymity"]["per_window"]["median"]

    def test_the_duration_must_be_whole_windows(self) -> None:
        with pytest.raises(ValueError):
            rse.run_users(SqliteRepo(), get_backend("numpy"), 4, seed=7, duration_s=40, buckets=4, window_s=7)

    def test_a_lost_row_is_neither_counted_nor_attacked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = SqliteRepo()
        dump = repo.dump
        monkeypatch.setattr(repo, "dump", lambda: dump()[1:])
        res = rse.run_users(repo, get_backend("numpy"), 24, **SMALL)
        assert not res["ok"] and res["attack"] is None and res["anonymity"] is None
        assert rse.anon_metrics([res], 7) == []

    def test_metrics_carry_the_population(self) -> None:
        res = rse.run_users(SqliteRepo(), get_backend("numpy"), 24, **SMALL)
        got = {m["id"]: m for m in rse.anon_metrics([res], 7)}
        assert set(got) == {"S-ANON-MSGS-U24", "S-ANON-MED-U24", "S-ANON-P5-U24", "S-ANON-BW-MED-U24",
                            "S-ANON-BW-P5-U24", "S-ANON-BW-PEAK-U24", "S-TURNACC-W5-U24", "S-F-W5-U24"}
        assert got["S-ANON-MED-U24"]["value"] == res["anonymity"]["per_window"]["median"]
        assert got["S-ANON-BW-P5-U24"]["value"] == res["anonymity"]["per_bucket_window"]["p5"]
        assert all("24 users in 12 conversations" in m["stat"] and "seed 7" in m["stat"] for m in got.values())


class TestCli:
    def test_the_stage_writes_a_valid_run_with_the_true_engine(self, tmp_path: Path) -> None:
        assert rse.main(["--stage", "anonymity", "--quick", "--store", "sqlite", "--backend", "numpy", "--seed", "11",
                         "--out", str(tmp_path)]) == 0
        (run_dir,) = tmp_path.iterdir()
        assert runs.validate_manifest(run_dir) == []
        m = runs.read_manifest(run_dir)
        assert m["status"] == "OK" and m["step"] == "S6" and m["seed"] == 11 and m["quick"] is True
        p = m["params"]
        assert p["engine"] == "numpy-simulator" and p["db"] == "sqlite" and p["mode"] == "vcloak"
        assert p["users"] == [10, 100] and p["users_per_conversation"] == 2 and "n_conv" not in p
        assert "not evidence about a GPU" in m["notes"]
        assert {"s6_anonymity.json", "anonymity_table.csv", "summary.json"} <= set(m["outputs"])
        doc = json.loads((run_dir / "s6_anonymity.json").read_text(encoding="utf-8"))
        assert [x["users"] for x in doc["populations"]] == [10, 100] and "users / 2" in doc["mapping"]
        assert all(isinstance(x["peak_bucket_window_above_cand_k"], bool) for x in doc["populations"])
        table = (run_dir / "anonymity_table.csv").read_text(encoding="utf-8").splitlines()
        assert table[0].split(",") == list(rse.ANON_COLUMNS) and len(table) == 3
        metrics = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["metrics"]
        assert len(metrics) == 16 and {x["id"] for x in metrics} >= {"S-ANON-MED-U10", "S-TURNACC-W60-U100"}

    def test_the_job_runs_the_stage_on_the_device_behind_the_stack(self) -> None:
        spec = json.loads((ROOT / "bench" / "jobs" / "M14_s6.json").read_text(encoding="utf-8"))
        names = [c["name"] for c in spec["commands"]]
        assert spec["step"] == "S6" and names.index("stack_up") < names.index("security_anon")
        (stage,) = [c["cmd"] for c in spec["commands"] if "run_security_eval.py" in c["cmd"]]
        assert "--stage anonymity" in stage and "--backend cupy" in stage and "{quick}" in stage
        assert "--store" not in stage  # the default: PostgreSQL
