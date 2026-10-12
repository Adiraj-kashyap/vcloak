"""M08 S5: the report generator copies verdicts, checks branch explanations against the listing, and never
writes from a run that is not an ingested cupy run. All inputs are synthetic; nothing here is a measurement."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from vcloak.bench import report_oblivious as ro
from vcloak.bench.report import M08_BEGIN, M08_END, ReportError

LISTING = """\
\t\tFunction : k_one
        /*0040*/                   ISETP.GE.U32.AND P0, PT, R0, c[0x0][0x188], PT ;   /* 0x0 */
        /*0050*/               @P0 EXIT ;                                             /* 0x0 */
        /*0060*/                   EXIT ;                                             /* 0x0 */
"""
EXPLAINED = {"branches": [{"file": "k.cu", "function": "k_one", "addr": "0050", "instr": "@P0 EXIT",
                           "setter": "0040 ISETP.GE.U32.AND P0, PT, R0, c[0x0][0x188], PT",
                           "source": "if (t >= n) return;", "depends_on": "thread id and n", "public": True}]}


def _series(t: float, verdict: str) -> dict[str, Any]:
    return {"n_class0": 50, "n_class1": 50, "max_abs_t": t, "max_at": "raw", "verdict": verdict}


def _target(name: str, series: dict[str, Any], expected: str = "PASS") -> dict[str, Any]:
    return {"target": name, "title": name, "series": series, "expected_verdict": expected, "r": 1, "mismatches": 0,
            "clock": {"status": "OK", "before_mhz": 1000, "after_mhz": 1000}}


def _run(root: Path, name: str, summary: dict[str, Any], backend: str = "cupy", quick: bool = False,
         session: str = "s1") -> Path:
    d = root / "runs" / name
    d.mkdir(parents=True)
    man: dict[str, Any] = {"run_id": name, "git_sha": "abcdef0123", "quick": quick, "status": "OK",
                           "params": {"percentile_crops": 100},
                           "env": {"backend": backend, "runner": "kaggle", "gpu": "Tesla T4", "session_id": session}}
    if backend == "cupy":
        man["gpu_job"] = {"job_id": "job1"}
    (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return d


def _metrics(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in targets:
        for s, st in t["series"].items():
            mid = ro.metric_id("T-DUDECT-MAXT", t["target"]) + ("-CALL" if s == "call_ms" else "")
            out.append({"id": mid, "value": st["max_abs_t"]})
        out.append({"id": ro.metric_id("T-DUDECT-N", t["target"]), "value": 50})
    return out


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    common = {"timer": "cupy.cuda.Event", "executed_by": "nvrtc", "t_threshold": 4.5, "caveat": "shared GPU"}
    st = [_target("control_leak", {"ms": _series(300.0, "FAIL")}, "FAIL"),
          _target("control_null", {"ms": _series(1.0, "PASS")})]
    full = [_target("control_null", {"ms": _series(2.0, "PASS")}),
            _target("bitonic_equal", {"ms": _series(1.5, "PASS")}),
            _target("bitonic_sorted", {"ms": _series(2.5, "PASS")}),
            _target("write_epoch", {"device_ms": _series(2.0, "PASS"), "call_ms": _series(9.0, "FAIL")}),
            _target("aead_tag", {"ms": _series(1.0, "PASS")}),
            _target("aead_conv", {"ms": _series(12.0, "FAIL")})]
    dirs = {
        "selftest": _run(tmp_path, "st", {**common, "metrics": _metrics(st), "targets": st}, quick=True),
        "dudect": _run(tmp_path, "dd", {**common, "metrics": _metrics(full), "targets": full}),
        "sass": _run(tmp_path, "sass", {
            "metrics": [{"id": "T-SASS-BRA-K-ONE", "value": 2}], "analysis": "static; x",
            "control": {"detected": True},
            "log": {"files": {"bitonic.cu": {"command": "nvcc -cubin -I x", "disassembler": "cuobjdump -sass"}},
                    "nvrtc": {}},
            "functions": {"k.cu": [{"function": "k_one", "instructions": 3, "conditional": 1, "sync": 0}]},
            "to_explain": {"k.cu": [{"function": "k_one", "addr": "0050", "instr": "@P0 EXIT", "class": "DATA"}]}}),
        "ncu": _run(tmp_path, "ncu", {
            "metrics": [{"id": "T-NCU-DIVERGENT-AEAD-OPEN-SEQ", "value": "NOT_MEASURED", "unit": "branches",
                         "stat": "sum", "note": "denied"}],
            "reason": "denied", "branch_metrics_queried": []}),
    }
    (dirs["sass"] / "sass_k.txt").write_text(LISTING, encoding="utf-8")
    (dirs["dudect"] / "dudect_aead_conv.json").write_text("{}", encoding="utf-8")
    (tmp_path / "explained.json").write_text(json.dumps(EXPLAINED), encoding="utf-8")
    return {**dirs, "root": tmp_path}


def _generate(tree: dict[str, Path], **kw: Any) -> dict[str, Any]:
    root = tree["root"]
    return ro.generate(tree["selftest"], tree["dudect"], tree["sass"], tree["ncu"], root / "out",
                       kw.pop("explained", root / "explained.json"),
                       {"fail": "ISSUE-A", "ncu": "ISSUE-B", "sass": "ISSUE-C"}, root=root, **kw)


def test_listing_instructions_reads_addresses(tree: dict[str, Path]) -> None:
    ins = ro.listing_instructions(tree["sass"] / "sass_k.txt")
    assert ins == {"k_one": {"0040": "ISETP.GE.U32.AND P0, PT, R0, c[0x0][0x188], PT", "0050": "@P0 EXIT",
                             "0060": "EXIT"}}


def test_fail_is_copied_never_softened(tree: dict[str, Path]) -> None:
    notes = tree["root"] / "notes.md"
    s = _generate(tree, notes=notes)
    assert s["fails"] == ["write_epoch:call_ms", "aead_conv:ms"]
    assert s["controls_ok"] is True
    assert s["sass_explained_public"] == 1
    text = notes.read_text(encoding="utf-8")
    assert "| write_epoch (whole call) | full |" in text and "**FAIL**" in text
    assert "12.0<!--M:T-DUDECT-MAXT-AEAD-CONV-->" in text
    assert "ISSUE-A" in text
    table = (tree["root"] / "out" / "summary_table.csv").read_text(encoding="utf-8")
    assert "aead_conv,ms,dudect,50,12.0,raw,FAIL,PASS" in table
    assert (tree["root"] / "out" / "dudect_aead_conv.json").exists()


def test_notes_section_is_replaced_and_the_rest_kept(tree: dict[str, Path]) -> None:
    notes = tree["root"] / "notes.md"
    notes.write_text("# perf\nkeep me\n", encoding="utf-8")
    _generate(tree, notes=notes)
    _generate(tree, notes=notes)
    text = notes.read_text(encoding="utf-8")
    assert text.startswith("# perf\nkeep me\n")
    assert text.count(M08_BEGIN) == 1 and text.count(M08_END) == 1


def test_missing_explanation_refuses(tree: dict[str, Path]) -> None:
    empty = tree["root"] / "empty.json"
    empty.write_text(json.dumps({"branches": []}), encoding="utf-8")
    with pytest.raises(ReportError, match="without an explanation"):
        _generate(tree, explained=empty)
    assert not (tree["root"] / "out").exists()


def test_stale_explanation_refuses(tree: dict[str, Path]) -> None:
    (tree["sass"] / "sass_k.txt").write_text(LISTING.replace("R0, c[0x0][0x188]", "R7, c[0x0][0x188]"),
                                             encoding="utf-8")
    with pytest.raises(ReportError, match="wrong setter"):
        _generate(tree)


def test_numpy_run_is_never_reported(tree: dict[str, Path]) -> None:
    man = json.loads((tree["ncu"] / "manifest.json").read_text(encoding="utf-8"))
    man["env"]["backend"] = "numpy"
    (tree["ncu"] / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(ReportError, match="backend numpy"):
        _generate(tree)


def test_two_sessions_are_never_merged(tree: dict[str, Path]) -> None:
    man = json.loads((tree["sass"] / "manifest.json").read_text(encoding="utf-8"))
    man["env"]["session_id"] = "s2"
    (tree["sass"] / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(ReportError, match="session_id differs"):
        _generate(tree)


def test_a_missing_target_refuses(tree: dict[str, Path]) -> None:
    summ = json.loads((tree["dudect"] / "summary.json").read_text(encoding="utf-8"))
    summ["targets"] = [t for t in summ["targets"] if t["target"] != "aead_tag"]
    (tree["dudect"] / "summary.json").write_text(json.dumps(summ), encoding="utf-8")
    with pytest.raises(ReportError, match="aead_tag"):
        _generate(tree)
