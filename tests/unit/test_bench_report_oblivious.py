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


# ---------------------------------------------------------------- kernel-only window (ISSUE-25), synthetic

def _kw_target(name: str, t: float, verdict: str, flagged: int | None = 30, median_ms: float = 0.04,
               expected: str = "PASS") -> dict[str, Any]:
    s = {**_series(t, verdict), "summary_class0": {"median_ms": median_ms}}
    out = {**_target(name, {"ms": s}, expected), "class0": "fixed", "class1": "random", "raw": f"dudect_{name}_raw.npz",
           "params": {"window": "queued behind a blocker", "kernel": "k_one", "slots": 64}, "n_per_class": 50}
    if flagged is not None:
        s["unflagged"] = {"max_abs_t": t / 2, "verdict": "PASS"}
        out["per_sample"] = {"measurements": 1000, "unqueued": flagged, "off_clock": 0, "flagged": flagged,
                             "steady_clock_mhz": 1590}
    return out


def _kw_tree(tree: dict[str, Path], tags_verdicts: tuple[str, str] = ("PASS", "PASS"), null_verdict: str = "PASS",
             queued: int = 40, session: str = "k1") -> dict[str, Any]:
    import numpy as np

    root = tree["root"]
    lock = {"attempted": True, "accepted": False, "command": "nvidia-smi -lgc", "returncode": 4,
            "output": "no permission\n"}
    leakq = _kw_target("control_leak_q", 300.0, "FAIL", flagged=1000 - queued, expected="FAIL")
    st = _run(root, "kst", {"metrics": _metrics([leakq]), "targets": [leakq], "clock_lock": lock}, quick=True,
              session=session)
    q = np.zeros(1000, dtype=bool)
    q[:queued] = True
    classes = np.arange(1000) % 2
    np.savez(st / "dudect_control_leak_q_raw.npz", times_ms=(1.0 + classes + 0.01 * (np.arange(1000) % 7))[:, None],
             classes=classes.astype(np.uint8), queued=q, clocks_mhz=np.full(1000, 585, dtype=np.int32))
    seeds = []
    for seed, tv in zip((8, 10), tags_verdicts, strict=True):
        targets = [_kw_target("control_null", 2.0, "PASS", flagged=None, median_ms=0.5),
                   _kw_target("tags_kernel_null", 1.0, null_verdict),
                   _kw_target("tags_kernel", 6.0 if tv == "FAIL" else 2.0, tv),
                   _kw_target("compact_kernel_null", 1.0, "PASS", median_ms=0.08),
                   _kw_target("compact_kernel", 1.5, "PASS", median_ms=0.08)]
        d = _run(root, f"k{seed}", {"metrics": _metrics(targets), "targets": targets, "clock_lock": lock},
                 session=session)
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        man["seed"] = seed
        (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
        seeds.append(d)
    stage_t = [_target("write_epoch_age_st", {"tags_ms": _series(9.0, "FAIL"), "core_ms": _series(1.0, "PASS")})]
    stage = _run(root, "stage", {"metrics": [], "targets": stage_t}, session="other")
    return {"selftest": st, "seeds": seeds, "stage_runs": [stage], "issue": "ISSUE-K"}


def test_kernel_window_section_copies_verdicts_and_names_the_weak_control(tree: dict[str, Path]) -> None:
    notes = tree["root"] / "notes.md"
    s = _generate(tree, notes=notes, kernel_window=_kw_tree(tree))
    text = notes.read_text(encoding="utf-8")
    assert text.count(M08_BEGIN) == 1 and text.rstrip().endswith(M08_END)
    assert "## 4.O.7" in text and "ISSUE-K" in text
    assert "- tags: no dependence detected at this N, on this device (rule g)" in text
    assert "2.0<!--M:T-DUDECT-MAXT-TAGS-KERNEL-->" in text
    assert "960 of its 1000 measurements were not queued" in text and "on 20 and 20 measurements per class" in text
    assert "`tags_kernel`, `tags_kernel_null`" in text
    assert "`compact_kernel`" not in text.split("Windows with a median")[1]
    assert "2 series, 1 FAIL and 1 PASS" in text and "ANN-1" in text
    assert "constant time" not in text.split("## 4.O.7")[1]
    assert "kernel_window.csv" in s["files"] and s["kernel_window"]["issue"] == "ISSUE-K"
    csv_text = (tree["root"] / "out" / "kernel_window.csv").read_text(encoding="utf-8")
    assert "8,tags_kernel,50,2.0,PASS,PASS,1.0,30,30,0,1590,40.0,1,0,T-DUDECT-MAXT-TAGS-KERNEL" in csv_text


@pytest.mark.parametrize(("tags", "null", "expect"), [
    (("FAIL", "FAIL"), "PASS", "rule i"), (("FAIL", "PASS"), "PASS", "rule j"), (("FAIL", "FAIL"), "FAIL", "rule h")])
def test_kernel_window_fail_is_read_by_the_rules_never_softened(tree: dict[str, Path], tags: tuple[str, str], null: str,
                                                                expect: str) -> None:
    notes = tree["root"] / "notes.md"
    _generate(tree, notes=notes, kernel_window=_kw_tree(tree, tags_verdicts=tags, null_verdict=null))
    text = notes.read_text(encoding="utf-8").split("## 4.O.7")[1]
    line = next(x for x in text.splitlines() if x.startswith("- tags:"))
    assert expect in line and "rule g" not in line
    assert "**FAIL**" in text


def test_kernel_window_refuses_a_numpy_run(tree: dict[str, Path]) -> None:
    kw = _kw_tree(tree)
    man = json.loads((kw["seeds"][1] / "manifest.json").read_text(encoding="utf-8"))
    man["env"]["backend"] = "numpy"
    (kw["seeds"][1] / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(ReportError, match="not an ingested cupy run"):
        _generate(tree, kernel_window=kw)
