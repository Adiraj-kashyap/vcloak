"""M14: the security report generator copies gates and values from ingested cupy runs of the real stack and refuses
anything else. All inputs are synthetic; nothing here is a measurement."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from vcloak.bench import report_security as rs
from vcloak.bench.report import M08_BEGIN, M08_END, M14_BEGIN, M14_END, ReportError

STACK = {"mode": "vcloak", "db": "postgres", "engine": "gpu"}


def _run(root: Path, name: str, files: dict[str, Any], metrics: list[dict[str, Any]], backend: str = "cupy",
         session: str = "s1", params: dict[str, Any] | None = None, quick: bool = False) -> Path:
    d = root / "runs" / name
    d.mkdir(parents=True)
    man: dict[str, Any] = {"run_id": name, "git_sha": "abcdef0123", "quick": quick, "status": "OK", "seed": 7,
                           "params": STACK if params is None else params,
                           "env": {"backend": backend, "runner": "colab", "gpu": "Tesla T4", "session_id": session}}
    if backend == "cupy":
        man["gpu_job"] = {"job_id": "job1"}
    (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    (d / "summary.json").write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
    for f, body in files.items():
        (d / f).write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return d


def _layout(key: str, window_s: int, acc: float, f: float, peak: int | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "layout": key, "window_s": window_s, "checks": {"row_count_equals_message_count": True},
        "attack": {"turn_order_accuracy": acc, "predicted_turn_accuracy": 1 - f / 2, "visible_rounds": 3,
                   "rows": 40, "turns_same_round_frac": f}}
    if peak is not None:
        out["occupancy"] = {"peak": peak, "mean": 1.0}
    return out


LAYOUTS = [_layout("BASELINE", 60, 1.0, 0.9, None), _layout("EPOCH", 60, 0.98, 0.04, 2),
           _layout("W1", 1, 0.92, 0.16, 3), _layout("W10", 10, 0.69, 0.62, 5), _layout("W60", 60, 0.56, 0.88, 9),
           _layout("W300", 300, 0.51, 0.98, 30)]
E0 = {"conversations_checked": 4, "exact_order": 4, "messages_checked": 40, "reads": 8, "reads_failed": [],
      "cand_k": 16, "checks": {"every_conversation_in_exact_order": True}}
E2 = {"key": "development key (public)",
      "chi2": {"n": 8, "reps": 100, "dof": 49, "gates": {"p_above_0_01": True},
               "ideal_sampler": {"tables": 5, "chi2_min": 30.0, "chi2_max": 70.0}},
      "tau_band": {"n": 64, "epochs": 10, "inside_band": 10, "binomial_99_bounds": [9, 10], "sigma_theory": 0.08,
                   "histogram": {"z_edges": [-4.0, -2.0, 0.0, 2.0, 4.0], "counts": [0, 6, 4, 0]},
                   "gates": {"coverage_inside_binomial_99_bounds": True}}}
E3 = {"sort": {"n": 16, "digest": "sha256, first 128 bits", "rows": [{}, {}],
               "gates": {"device_trace_identical_for_every_input": True}},
      "write_epoch": {"slots": 8, "rows": [{}, {}], "gates": {"launch_list_identical_for_every_batch": True}}}


def _metrics() -> list[dict[str, Any]]:
    out = [{"id": "S-E0-RESTORE", "value": 4}, {"id": "S-CANDK", "value": 16}]
    for lay in LAYOUTS:
        out.append({"id": f"S-TURNACC-{lay['layout']}", "value": lay["attack"]["turn_order_accuracy"]})
    return out


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Any]:
    s1 = {"params": {"n_conv": 4, "duration_s": 9}, "checks": {"row_count_equals_message_count": True}}
    return {
        "s1": _run(tmp_path, "s1", {"s1_traffic.json": s1}, [{"id": "S-TRAFFIC-MSGS", "value": 40}]),
        "attack": _run(tmp_path, "atk", {"e1_attack.json": {"layouts": LAYOUTS, "db_server_version": "16"},
                                         "e0_restoration.json": E0, "attack_table.csv": "layout\n"}, _metrics()),
        "uniformity": _run(tmp_path, "uni", {"e2_uniformity.json": E2}, [{"id": "S-CHI2-P", "value": 0.5}]),
        "trace": _run(tmp_path, "trc", {"e3_trace.json": E3}, [{"id": "S-TRACE-DISTINCT-DEVICE", "value": 1}]),
        "root": tmp_path, "out": tmp_path / "results" / "security",
    }


def _generate(tree: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return rs.generate(tree["s1"], tree["attack"], tree["uniformity"], tree["trace"], tree["out"],
                       root=tree["root"], **kw)


def test_files_gates_and_sidecars(tree: dict[str, Any]) -> None:
    s = _generate(tree)
    for f in ("attack_table.csv", "e0_restoration.json", "gates.csv", "fig_window_ablation.png",
              "fig_window_ablation.pdf", "fig_tau_histogram.png", "security_summary.json"):
        assert (tree["out"] / f).is_file(), f
    with (tree["out"] / "gates.csv").open(encoding="utf-8", newline="") as fh:
        gates = list(csv.DictReader(fh))
    assert len(gates) == s["gates"] == 1 + len(LAYOUTS) + 1 + 2 + 2
    assert {g["result"] for g in gates} == {"PASS"} and s["gates_failed"] == []
    side = json.loads((tree["out"] / "fig_window_ablation.json").read_text(encoding="utf-8"))
    assert side["run_dirs"] == ["runs/atk"] and "S-TURNACC-W60" in side["metric_ids"]
    assert s["not_measured"] == ["S6 anonymity set", "S7 comparison with the CPU oracle"]


def test_a_failed_gate_is_reported_not_dropped(tree: dict[str, Any]) -> None:
    bad = json.loads(json.dumps(E2))
    bad["chi2"]["gates"]["p_above_0_01"] = False
    (tree["uniformity"] / "e2_uniformity.json").write_text(json.dumps(bad), encoding="utf-8")
    notes = tree["root"] / "notes.md"
    s = _generate(tree, notes=notes)
    assert [g["gate"] for g in s["gates_failed"]] == ["p_above_0_01"]
    assert "- FAIL: E2 / chi2 / p_above_0_01" in notes.read_text(encoding="utf-8")


def test_notes_are_tagged_and_the_rest_is_kept(tree: dict[str, Any]) -> None:
    notes = tree["root"] / "notes.md"
    notes.write_text(f"# perf\n\n{M08_BEGIN}\nobl\n{M08_END}\n", encoding="utf-8")
    _generate(tree, notes=notes, issues={"overflow": "ISSUE-9", "pending": "ISSUE-9"})
    _generate(tree, notes=notes, issues={"overflow": "ISSUE-9", "pending": "ISSUE-9"})  # replaced, not appended
    text = notes.read_text(encoding="utf-8")
    assert text.startswith(f"# perf\n\n{M08_BEGIN}\nobl\n{M08_END}\n")
    assert text.count(M14_BEGIN) == 1 and text.count(M14_END) == 1
    assert "4<!--M:S-E0-RESTORE-->" in text and "0.56<!--M:S-TURNACC-W60-->" in text
    assert "NOT_MEASURED<!--M:S-OCC-PEAK-->" in text  # a metric no run lists is never guessed
    assert "layout W300 the peak bucket-window occupancy is 30, above CAND_K 16" in text and "ISSUE-9" in text
    assert "W60 the peak" not in text


def test_m08_verdicts_come_from_the_oblivious_summary(tree: dict[str, Any]) -> None:
    obl = tree["root"] / "oblivious_summary.json"
    obl.write_text(json.dumps({"provenance": {"job_id": "jobM08"}, "fails": ["aead_conv:ms"], "ncu_reason": "refused",
                               "issues": {"fail": "ISSUE-1", "ncu": "ISSUE-2"}}), encoding="utf-8")
    notes = tree["root"] / "notes.md"
    _generate(tree, notes=notes, oblivious=obl)
    text = notes.read_text(encoding="utf-8")
    assert "verdict FAIL for these series: `aead_conv:ms` (ISSUE-1)" in text and "(refused; ISSUE-2)" in text
    assert "constant time" not in text.lower()
    _generate(tree, notes=notes)
    assert "no oblivious summary was given" in notes.read_text(encoding="utf-8")


@pytest.mark.parametrize("change", [
    {"backend": "numpy"}, {"session": "s2"}, {"quick": True}, {"params": {**STACK, "db": "sqlite"}},
    {"params": {**STACK, "engine": "numpy"}}, {"params": {**STACK, "mode": "baseline"}}])
def test_refuses_runs_that_are_not_the_real_stack(tree: dict[str, Any], change: dict[str, Any]) -> None:
    s1 = {"params": {"n_conv": 4, "duration_s": 9}, "checks": {}}
    tree["s1"] = _run(tree["root"], "s1_other", {"s1_traffic.json": s1}, [], **change)
    with pytest.raises(ReportError):
        _generate(tree)
    assert not tree["out"].exists()


def test_cli_prints_not_measured_on_refusal(tree: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    (tree["trace"] / "e3_trace.json").unlink()
    rc = rs.main(["--s1", str(tree["s1"]), "--attack", str(tree["attack"]), "--uniformity", str(tree["uniformity"]),
                  "--trace", str(tree["trace"]), "--out", str(tree["out"])])
    assert rc == 1 and "NOT_MEASURED" in capsys.readouterr().out


def _oracle_run(tree: dict[str, Any], device_runs: dict[str, str] | None = None, quick: bool = False) -> Path:
    cmp = {"seed": 7, "oracle_reps": 5, "family_alpha": 0.01, "spread_rows": 1,
           "counts": {"EQUAL": 1, "WITHIN_NOISE": 0, "DIFFERS": 1, "NOT_COMPARABLE": 1},
           "rows": [
               {"experiment": "S1", "quantity": "messages", "device_metric": "S-TRAFFIC-MSGS",
                "oracle_metric": "S-ORACLE-TRAFFIC-MSGS", "lo": None, "hi": None, "verdict": "EQUAL", "criterion": "c"},
               {"experiment": "E1", "quantity": "turn-order accuracy, W60", "device_metric": "S-TURNACC-W60",
                "oracle_metric": "S-ORACLE-TURNACC-W60", "lo": 0.6, "hi": 0.7, "verdict": "DIFFERS", "criterion": "c",
                "device": 0.56, "oracle": 0.65},
               {"experiment": "E0", "quantity": "candidate set size K", "device_metric": "S-CANDK",
                "oracle_metric": "S-ORACLE-CANDK", "lo": None, "hi": None, "verdict": "NOT_COMPARABLE",
                "criterion": "defined differently"}]}
    params = {"oracle": "seed/vcloak_oracle.py",
              "device_runs": device_runs or {"s1": "s1", "attack": "atk", "uniformity": "uni", "trace": "trc"}}
    metrics = [{"id": "S-ORACLE-TRAFFIC-MSGS", "value": 40}, {"id": "S-ORACLE-TURNACC-W60", "value": 0.65},
               {"id": "S-ORACLE-CANDK", "value": 8}, {"id": "S-ORACLE-CMP-DIFFERS", "value": 1}]
    return _run(tree["root"], "ora", {"oracle_comparison.json": cmp, "oracle_comparison.csv": "experiment\n"},
                metrics, backend="numpy", params=params, quick=quick)


def test_oracle_comparison_is_copied_and_both_sides_are_tagged(tree: dict[str, Any]) -> None:
    notes = tree["root"] / "notes.md"
    s = _generate(tree, notes=notes, oracle=_oracle_run(tree), issues={"oracle": "ISSUE-8", "pending": "ISSUE-9"})
    text = notes.read_text(encoding="utf-8")
    assert (tree["out"] / "oracle_comparison.csv").exists() and "oracle_comparison.json" in s["files"]
    assert s["not_measured"] == ["S6 anonymity set"] and s["oracle_comparison"]["counts"]["DIFFERS"] == 1
    assert "| S1 | messages | 40<!--M:S-TRAFFIC-MSGS--> | 40<!--M:S-ORACLE-TRAFFIC-MSGS--> | - | EQUAL |" in text
    assert "0.56<!--M:S-TURNACC-W60--> | 0.65<!--M:S-ORACLE-TURNACC-W60--> | 0.6 to 0.7 | DIFFERS |" in text
    # a difference is named with the side that is outside and with its issue
    assert "- DIFFERS: E1 / turn-order accuracy, W60; outside the interval: the device value (ISSUE-8)." in text
    assert "No row differs" not in text
    assert "## 4.S.10 Not in this section\n- The anonymity-set study (S6): NOT_MEASURED (ISSUE-9)." in text


@pytest.mark.parametrize("kw", [{"device_runs": {"s1": "s1", "attack": "other", "uniformity": "uni", "trace": "trc"}},
                                {"quick": True}])
def test_refuses_an_oracle_run_over_other_device_runs_or_quick(tree: dict[str, Any], kw: dict[str, Any]) -> None:
    with pytest.raises(ReportError):
        _generate(tree, oracle=_oracle_run(tree, **kw))
    assert not tree["out"].exists()


def _pop(users: int, peak: int, cand_k: int = 16) -> dict[str, Any]:
    cells = {"cells": 6, "empty": 2, "median": 3.0, "p5": 0.5, "msg_median": 5.0, "msg_p5": 2.0}
    return {"users": users, "conversations": users // 2, "cand_k": cand_k, "occupancy": {"peak": peak},
            "peak_bucket_window_above_cand_k": peak > cand_k,
            "checks": {"row_count_equals_message_count": True, "no_epoch_failed": True},
            "attack": {"predicted_turn_accuracy": 0.56}, "anonymity": {"per_window": cells, "per_bucket_window": cells}}


def _anon_run(tree: dict[str, Any], name: str = "anon", pops: list[dict[str, Any]] | None = None,
              **kw: Any) -> Path:
    s6 = {"mapping": "two users per conversation", "db_server_version": "16",
          "params": {"duration_s": 9, "buckets": 2, "window_s": 60}, "populations": pops or [_pop(4, 9), _pop(8, 30)]}
    metrics = [{"id": "S-ANON-MED-U4", "value": 3.0}, {"id": "S-ANON-BW-PEAK-U8", "value": 30}]
    return _run(tree["root"], name, {"s6_anonymity.json": s6, "anonymity_table.csv": "users\n"}, metrics,
                **{"session": "s9", **kw})


def test_anonymity_run_of_another_session_gets_its_own_provenance(tree: dict[str, Any]) -> None:
    notes = tree["root"] / "notes.md"
    s = _generate(tree, notes=notes, anonymity=_anon_run(tree), issues={"overflow": "ISSUE-9"})
    assert s["not_measured"] == ["S7 comparison with the CPU oracle"]
    assert s["provenance"]["session_id"] == "s1" and s["anonymity_provenance"]["session_id"] == "s9"
    assert s["run_dirs"]["anonymity"] == "runs/anon" and (tree["out"] / "anonymity_table.csv").is_file()
    assert s["gates"] == 1 + len(LAYOUTS) + 1 + 2 + 2 + 2 * 2
    text = notes.read_text(encoding="utf-8")
    assert "## 4.S.9 S6: anonymity set" in text and "## 4.S.10 Not in this section" in text
    assert "runner session s9 (a runner session of its own, not the one of the sections above)" in text
    assert "3.0<!--M:S-ANON-MED-U4-->" in text and "30<!--M:S-ANON-BW-PEAK-U8-->" in text
    assert "NOT_MEASURED<!--M:S-ANON-P5-U4-->" in text  # a metric the run does not list is never guessed
    assert "at 8 users the fullest bucket-window holds 30 real rows, above CAND_K 16" in text and "ISSUE-9" in text
    assert "at 4 users the fullest" not in text and "anonymity-set study (S6)" not in text


def test_a_failed_anonymity_check_is_a_failed_gate(tree: dict[str, Any]) -> None:
    bad = _pop(4, 9)
    bad["checks"]["no_epoch_failed"] = False
    s = _generate(tree, anonymity=_anon_run(tree, pops=[bad]))
    failed = [(g["experiment"], g["scope"], g["gate"]) for g in s["gates_failed"]]
    assert failed == [("S6", "4 users", "no_epoch_failed")]


def test_nothing_is_left_unmeasured_with_oracle_and_anonymity(tree: dict[str, Any]) -> None:
    notes = tree["root"] / "notes.md"
    s = _generate(tree, notes=notes, oracle=_oracle_run(tree), anonymity=_anon_run(tree))
    text = notes.read_text(encoding="utf-8")
    assert s["not_measured"] == [] and "## 4.S.10 S6: anonymity set" in text and "Not in this section" not in text


@pytest.mark.parametrize("change", [{"backend": "numpy"}, {"quick": True}, {"params": {**STACK, "db": "sqlite"}},
                                    {"params": {**STACK, "engine": "numpy"}}])
def test_refuses_an_anonymity_run_that_is_not_the_real_stack(tree: dict[str, Any], change: dict[str, Any]) -> None:
    with pytest.raises(ReportError):
        _generate(tree, anonymity=_anon_run(tree, **change))
    assert not tree["out"].exists()
