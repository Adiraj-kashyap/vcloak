"""M14 S2 to S5 on the numpy simulator: the attack on a dump, the read-back, uniformity, the trace."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

import testkeys
from vcloak import runs
from vcloak.eval import attack, trace, traffic, uniformity
from vcloak.gpu import kernels
from vcloak.gpu.engine import GpuEngine, StoredRow
from vcloak.gpu.runtime import get_backend
from vcloak.oracle import reference
from vcloak.service.baseline import SqliteBaselineStore
from vcloak.storage.repo import SqliteRepo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_gpu_tests  # noqa: E402
import run_security_eval as rse  # noqa: E402
import runner_stack  # noqa: E402

SMALL = dict(seed=7, n_conv=12, duration_s=40, buckets=4)
W5 = {"id": "W5", "mode": "vcloak", "visible_round": "window", "window_s": 5}
EPOCH = {"id": "EPOCH", "mode": "vcloak", "visible_round": "epoch", "window_s": 5}
BASELINE = {"id": "BASELINE", "mode": "baseline", "visible_round": "window", "window_s": 5}


def _dump(order: list[int], wins: list[int]) -> tuple[list[tuple[int, int, bytes]], dict[bytes, traffic.Event]]:
    """Baseline-style rows holding the events `order` (by arrival rank), two conversations in turn."""
    events = [traffic.Event(t_ms=1000 * i, conv=i % 2, seq=i // 2, truth=i) for i in range(len(order))]
    payloads = [f"payload {i}".encode() for i in range(len(order))]
    by_digest = {traffic.digest(p): e for p, e in zip(payloads, events, strict=True)}
    return [(p, wins[i], payloads[i]) for p, i in enumerate(order)], by_digest


class TestAttack:
    def test_a_dump_in_arrival_order_is_fully_recovered(self) -> None:
        rows, by_digest = _dump(list(range(12)), [i // 4 for i in range(12)])
        res = attack.attack_dump(rows, by_digest)
        assert res["tau_global"] == pytest.approx(1.0) and res["turn_order_accuracy"] == 1.0
        assert res["rows"] == 12 and res["visible_rounds"] == 3
        assert res["predicted_turn_accuracy"] == 1 - res["turns_same_round_frac"] / 2

    def test_a_reversed_round_is_not(self) -> None:
        rows, by_digest = _dump(list(range(11, -1, -1)), [0] * 12)
        res = attack.attack_dump(rows, by_digest)
        assert res["tau_global"] == pytest.approx(-1.0) and res["turn_order_accuracy"] == 0.0
        assert res["turns_same_round_frac"] == 1.0 and res["predicted_turn_accuracy"] == 0.5

    def test_a_row_that_was_never_sent_is_an_error(self) -> None:
        rows, by_digest = _dump([0, 1, 2], [0, 0, 0])
        with pytest.raises(KeyError):
            attack.dump_columns([*rows, (9, 0, b"not sent")], by_digest)

    def test_occupancy_counts_rows_per_bucket_window(self) -> None:
        import uuid
        rows = [StoredRow(uuid.uuid4(), b, w, b"s", b"p") for b, w in [(0, 0), (0, 0), (0, 0), (1, 0), (0, 1)]]
        assert attack.occupancy(rows) == {"bucket_windows": 3, "peak": 3, "mean": 5 / 3}
        assert attack.occupancy([])["peak"] == 0


class TestLayouts:
    def test_the_full_and_the_quick_layout_lists(self) -> None:
        assert [x["id"] for x in rse.layouts(False)] == ["BASELINE", "EPOCH", "W1", "W10", "W60", "W300"]
        assert [x["id"] for x in rse.layouts(True)] == ["BASELINE", "EPOCH", "W10", "W60"]
        assert rse.E0_LAYOUT in {x["id"] for x in rse.layouts(True)}

    def test_window_layout_is_attacked_and_read_back_in_exact_order(self) -> None:
        res = rse.run_layout(SqliteRepo(), get_backend("numpy"), W5, read_convs=6, **SMALL)
        assert res["ok"], res["checks"]
        e0 = res["e0"]
        assert e0["exact_order"] == e0["conversations_checked"] == 6 and not e0["reads_failed"]
        assert e0["reads"] == 6 * (40 // 5 + 1) and e0["messages_checked"] > 6
        assert res["occupancy"]["peak"] <= e0["cand_k"]
        assert res["attack"]["rows"] == res["messages"] == res["rows_stored"]
        assert 0 < res["attack"]["turns_same_round_frac"] < 1
        assert res["attack"]["turn_order_accuracy"] < 1

    def test_baseline_dump_gives_the_order_away_and_the_epoch_round_nearly(self) -> None:
        base = rse.run_layout(SqliteBaselineStore(), get_backend("numpy"), BASELINE, **SMALL)
        assert base["ok"], base["checks"]
        assert base["attack"]["turn_order_accuracy"] == 1.0 and base["attack"]["tau_global"] == pytest.approx(1.0)
        assert "occupancy" not in base and "e0" not in base
        epoch = rse.run_layout(SqliteRepo(), get_backend("numpy"), EPOCH, **SMALL)
        assert epoch["ok"], epoch["checks"]
        w5 = rse.run_layout(SqliteRepo(), get_backend("numpy"), W5, **SMALL)
        assert epoch["attack"]["turn_order_accuracy"] > w5["attack"]["turn_order_accuracy"]
        assert epoch["attack"]["visible_rounds"] > w5["attack"]["visible_rounds"]

    def test_a_lost_row_fails_the_checks_and_is_not_attacked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = SqliteRepo()
        dump = repo.dump
        monkeypatch.setattr(repo, "dump", lambda: dump()[1:])
        res = rse.run_layout(repo, get_backend("numpy"), W5, **SMALL)
        assert not res["ok"] and res["attack"] is None
        assert not res["checks"]["stored_ciphertexts_are_the_sent_ones"]

    def test_a_wrong_read_fails_e0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        read = GpuEngine.read_window
        monkeypatch.setattr(GpuEngine, "read_window", lambda self, c, cand, K: read(self, c, cand, K)[::-1])  # noqa: N803
        res = rse.run_layout(SqliteRepo(), get_backend("numpy"), W5, read_convs=6, **SMALL)
        assert not res["ok"] and not res["checks"]["e0_every_conversation_in_exact_order"]
        assert res["e0"]["conversations_wrong"]

    def test_metrics_of_a_layout_carry_its_id(self) -> None:
        res = rse.run_layout(SqliteRepo(), get_backend("numpy"), W5, read_convs=3, **SMALL)
        ids = [m["id"] for m in rse.attack_metrics([res], 7)]
        assert ids == ["S-TAU-GLOBAL-W5", "S-TAU-WITHIN-W5", "S-TURNACC-W5", "S-F-W5", "S-E0-RESTORE", "S-CANDK",
                       "S-OCC-PEAK", "S-OCC-MEAN"]


class TestUniformity:
    def test_device_permutation_equals_the_reference(self) -> None:
        keys = testkeys.dev_keystore(get_backend("numpy"))
        k_tag = reference.RefKeys.from_master(testkeys.TEST_K_MASTER).k_tag
        for epoch in (0, 1, 10**6):
            got = uniformity.epoch_permutation(keys, epoch, 64)
            assert np.array_equal(got, reference.epoch_permutation_ref(k_tag, epoch, 64))
            assert sorted(got.tolist()) == list(range(64))

    def test_ideal_counts_is_a_permutation_count_table(self) -> None:
        counts = uniformity.ideal_counts(8, 500, np.random.default_rng(3))
        assert counts.shape == (8, 8) and (counts.sum(axis=0) == 500).all() and (counts.sum(axis=1) == 500).all()

    def test_chi2_study_passes_for_the_device_and_fails_for_a_biased_sampler(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        keys = testkeys.dev_keystore(get_backend("numpy"))
        res = uniformity.chi2_study(keys, 8, 400, calibration=40, seed=5)
        assert res["n"] == 8 and res["reps"] == 400 and res["ideal_sampler"]["tables"] == 40
        ideal = res["ideal_sampler"]
        assert ideal["chi2_min"] <= ideal["chi2_first"] <= ideal["chi2_max"]
        assert res["gates"]["p_above_0_01"]
        biased = np.diag(np.full(8, 400)).astype(np.int64)  # the identity every time
        monkeypatch.setattr(uniformity, "device_counts", lambda *a, **k: biased)
        bad = uniformity.chi2_study(keys, 8, 400, calibration=40, seed=5)
        assert not bad["gates"]["p_above_0_01"] and not bad["gates"]["chi2_inside_ideal_range"]

    def test_tau_band_counts_epochs_inside_the_band(self, monkeypatch: pytest.MonkeyPatch) -> None:
        keys = testkeys.dev_keystore(get_backend("numpy"))
        res = uniformity.tau_band_study(keys, 64, 30)
        assert res["epochs"] == 30 and len(res["taus"]) == 30 and 0 <= res["inside_band"] <= 30
        assert sum(res["histogram"]["counts"]) <= 30 and len(res["histogram"]["z_edges"]) == 25
        lo, hi = res["binomial_99_bounds"]
        assert res["gates"]["coverage_inside_binomial_99_bounds"] == (lo <= res["inside_band"] <= hi)
        monkeypatch.setattr(uniformity, "epoch_permutation", lambda keys, epoch, n: np.arange(n))
        assert not uniformity.tau_band_study(keys, 64, 30)["gates"]["coverage_inside_binomial_99_bounds"]


class TestTrace:
    def test_recorder_collects_the_launches_and_restores_the_hook(self) -> None:
        seen: list[int] = []
        kernels.set_launch_hook(lambda n, launch: seen.append(n))
        try:
            cols = (np.zeros(64, np.uint64), np.zeros(64, np.uint64), np.arange(64, dtype=np.uint32),
                    np.arange(64, dtype=np.uint32))
            with trace.LaunchRecorder() as rec:
                kernels.gpu_bitonic_sort(*cols)
            assert rec.launches and not seen
            assert [(k, j) for _, k, j in rec.stages()] == list(reference.bitonic_stages(64))
            kernels.gpu_bitonic_sort(*cols)
            assert seen
        finally:
            assert kernels.set_launch_hook(None) is not None
        assert kernels.set_launch_hook(None) is None

    def test_device_trace_is_the_oracle_trace_whatever_the_keys(self) -> None:
        res = trace.sort_traces(get_backend("numpy"), 64, 3)
        assert all(res["gates"].values()), res["gates"]
        assert [r["input"] for r in res["rows"]] == list(trace.INPUTS)
        assert res["device_distinct_traces"] == 1 < res["merge_sort_distinct_traces"]

    def test_merge_sort_trace_depends_on_the_data(self) -> None:
        assert trace.merge_sort_trace(list(range(16))) != trace.merge_sort_trace(list(range(16))[::-1])
        assert trace.merge_sort_trace([3, 1, 2]) == trace.merge_sort_trace([3, 1, 2])

    def test_write_epoch_issues_the_same_launches_for_every_batch(self) -> None:
        engine = GpuEngine(testkeys.dev_keystore(get_backend("numpy")), slots=16, buckets=4)
        res = trace.engine_traces(engine, 32, 4)
        assert all(res["gates"].values()), res["gates"]
        assert [r["rows_out"] for r in res["rows"]] == [16, 16, 8, 1, 0]
        assert all(r["launches"] > 0 for r in res["rows"])


class TestCli:
    @pytest.mark.parametrize(("stage", "step", "output"), [("trace", "S5", "e3_trace.json"),
                                                         ("attack", "S3", "e1_attack.json")])
    def test_a_stage_writes_a_valid_run_with_the_true_engine(self, tmp_path: Path, stage: str, step: str,
                                                             output: str) -> None:
        assert rse.main(["--stage", stage, "--quick", "--store", "sqlite", "--backend", "numpy", "--seed", "11",
                         "--out", str(tmp_path)]) == 0
        (run_dir,) = tmp_path.iterdir()
        assert runs.validate_manifest(run_dir) == []
        m = runs.read_manifest(run_dir)
        assert m["status"] == "OK" and m["step"] == step and m["seed"] == 11 and m["quick"] is True
        assert m["params"]["engine"] == "numpy-simulator" and m["env"]["backend"] == "numpy"
        assert "not evidence about a GPU" in m["notes"]
        assert output in m["outputs"] and "summary.json" in m["outputs"]
        metrics = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["metrics"]
        assert metrics and all(x["id"].startswith("S-") for x in metrics)
        if stage == "attack":
            assert m["params"]["db"] == "sqlite" and m["params"]["layouts"] == ["BASELINE", "EPOCH", "W10", "W60"]
            table = (run_dir / "attack_table.csv").read_text(encoding="utf-8").splitlines()
            assert table[0].split(",") == list(rse.ATTACK_COLUMNS) and len(table) == 5
            assert json.loads((run_dir / "e0_restoration.json").read_text(encoding="utf-8"))["exact_order"] == 15


JUNIT = """<testsuites><testsuite>
<testcase classname="tests.gpu.test_a" name="test_ok"/>
<testcase classname="tests.gpu.test_a" name="test_bad"><failure message="boom">trace</failure></testcase>
<testcase classname="tests.gpu.test_a" name="test_err"><error message="setup">trace</error></testcase>
<testcase classname="tests.gpu.test_a" name="test_skip"><skipped message="needs a CUDA device"/></testcase>
</testsuite></testsuites>"""


class TestGpuTestRecord:
    def test_junit_counts_and_reasons(self, tmp_path: Path) -> None:
        path = tmp_path / "junit.xml"
        path.write_text(JUNIT, encoding="utf-8")
        counts = run_gpu_tests.parse_junit(path)
        assert {k: counts[k] for k in ("selected", "passed", "failed", "errors", "skipped")} == {
            "selected": 4, "passed": 1, "failed": 1, "errors": 1, "skipped": 1}
        assert [t["outcome"] for t in counts["not_passed"]] == ["failure", "error", "skipped"]
        assert counts["not_passed"][2]["message"] == "needs a CUDA device"

    def test_all_skipped_is_never_a_pass(self) -> None:
        skipped = {"selected": 3, "passed": 0, "failed": 0, "errors": 0, "skipped": 3}
        assert not all(run_gpu_tests.verdict(skipped).values())
        assert all(run_gpu_tests.verdict({**skipped, "passed": 3, "skipped": 0}).values())
        assert not all(run_gpu_tests.verdict({**skipped, "passed": 2, "errors": 1}).values())


class TestRunnerStack:
    def test_it_refuses_to_install_outside_the_runner(self, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.delenv("VCLOAK_RUNNER", raising=False)
        assert runner_stack.main(["up"]) == 2
        monkeypatch.setenv("VCLOAK_RUNNER", "local")
        assert runner_stack.main(["down"]) == 2
        assert "runner only" in capsys.readouterr().out

    def test_the_extra_settings_never_replace_a_hygiene_setting(self) -> None:
        from vcloak.storage import pgconf
        assert not set(runner_stack.EXTRA_CONF) & set(pgconf.HYGIENE)
        assert runner_stack.PACKAGES["psycopg[binary]"] == "psycopg"

    def test_the_job_runs_the_stack_before_the_stages_and_every_stage_on_the_device(self) -> None:
        spec = json.loads((ROOT / "bench" / "jobs" / "M14.json").read_text(encoding="utf-8"))
        names = [c["name"] for c in spec["commands"]]
        assert names.index("stack_up") < names.index("security_s1") < names.index("cuda_tests")
        stages = [c["cmd"] for c in spec["commands"] if "run_security_eval.py" in c["cmd"]]
        assert len(stages) == 4 and all("--backend cupy" in c and "{quick}" in c for c in stages)
        assert all("--store" not in c for c in stages)  # the default: PostgreSQL
