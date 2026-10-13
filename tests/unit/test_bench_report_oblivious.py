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


def test_kernel_window_recorded_as_not_measured_prints_no_t_value_and_no_reading(tree: dict[str, Path]) -> None:
    notes = tree["root"] / "notes.md"
    s = _generate(tree, notes=notes, kernel_window={**_kw_tree(tree), "withdrawn": "ISSUE-W"})
    part = notes.read_text(encoding="utf-8").split("## 4.O.7")[1]
    assert "NOT_MEASURED<!--M:T-DUDECT-MAXT-TAGS-KERNEL-->" in part
    assert "2.0<!--M:T-DUDECT-MAXT-TAGS-KERNEL-->" not in part
    assert "Decision of the owner (ISSUE-W)" in part and "no dependence detected" not in part
    assert "(below 50 us)" in part and "960 of its 1000 measurements were not queued" in part
    assert s["kernel_window"]["not_measured"] == "ISSUE-W"
    csv_text = (tree["root"] / "out" / "kernel_window.csv").read_text(encoding="utf-8")
    assert "8,tags_kernel,50,NOT_MEASURED,NOT_MEASURED,PASS,NOT_MEASURED,30,30,0,1590,40.0,1,0," in csv_text


def test_kernel_window_fail_is_never_recorded_as_not_measured(tree: dict[str, Path]) -> None:
    kw = {**_kw_tree(tree, tags_verdicts=("FAIL", "PASS")), "withdrawn": "ISSUE-W"}
    with pytest.raises(ReportError, match="FAIL is never recorded"):
        _generate(tree, kernel_window=kw)


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


# ---------------------------------------------------------------- staging diagnostics (ISSUE-17), synthetic

def _dg(name: str, series: dict[str, tuple[float, str, float]], mhz: int = 585) -> dict[str, Any]:
    out = _target(name, {s: {**_series(t, v), "t_raw": raw} for s, (t, v, raw) in series.items()})
    out["clock"] = {"status": "LOW", "before_mhz": mhz, "after_mhz": mhz}
    return out


def _diag_tree(tree: dict[str, Path], sym: str = "PASS", original: tuple[str, str] = ("FAIL", "FAIL"),
               control: str = "PASS", swap_raw: float = -5.0, session: str = "d1") -> dict[str, Any]:
    seeds = []
    for seed, ov in zip((8, 9), original, strict=True):
        targets = [_dg("control_null", {"ms": (1.0, control, 0.5)}, 1000),
                   _dg("aead_conv", {"ms": (30.0 if ov == "FAIL" else 2.0, ov, -6.0)}),
                   _dg("aead_conv_null", {"ms": (40.0, "FAIL", -12.0)}),
                   _dg("aead_conv_swap", {"ms": (34.0, "FAIL", swap_raw)}),
                   _dg("aead_conv_sym", {"ms": (7.0 if sym == "FAIL" else 2.4, sym, -0.7)}, 1500),
                   _dg("aead_conv_kernel", {"ms": (2.9, "PASS", 1.1)}, 1200),
                   _dg("write_epoch", {"device_ms": (1.7, "PASS", -1.1), "call_ms": (29.0, "FAIL", -0.1)}),
                   _dg("write_epoch_fresh", {"device_ms": (6.1 if seed == 8 else 3.0, "FAIL" if seed == 8 else "PASS",
                                                           -2.0), "call_ms": (1.7, "PASS", -0.1)})]
        if seed == 8:
            targets.append(_dg("write_epoch_null", {"device_ms": (2.7, "PASS", -2.1), "call_ms": (12.7, "FAIL", -0.6)}))
        d = _run(tree["root"], f"d{seed}", {"metrics": _metrics(targets), "targets": targets}, session=session)
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        man["seed"] = seed
        (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
        seeds.append(d)
    return {"seeds": seeds, "issue": "ISSUE-D"}


def _diag_text(tree: dict[str, Path], **kw: Any) -> str:
    notes = tree["root"] / "notes.md"
    _generate(tree, notes=notes, diagnostics=_diag_tree(tree, **kw))
    return notes.read_text(encoding="utf-8").split("### Diagnostics of the failing series")[1].split("## 4.O.4")[0]


def test_diagnostics_stand_beside_the_s2_rows_and_no_fail_is_removed(tree: dict[str, Path]) -> None:
    notes = tree["root"] / "notes.md"
    s = _generate(tree, notes=notes, diagnostics=_diag_tree(tree))
    text = notes.read_text(encoding="utf-8")
    head = "### Diagnostics of the failing series (ISSUE-D)"
    assert text.index("## 4.O.3") < text.index(head) < text.index("## 4.O.4")
    assert "aead_conv | full | 50<!--M:T-DUDECT-N-AEAD-CONV--> | 12.0<!--M:T-DUDECT-MAXT-AEAD-CONV--> | **FAIL" in text
    assert "it blocks M14" not in text and "stay in every table as measured" in text
    diag = text.split("### Diagnostics of the failing series")[1].split("## 4.O.4")[0]
    assert "| S2 | None | `aead_conv` | aead_conv | 50 | 12.0<!--M:T-DUDECT-MAXT-AEAD-CONV--> | **FAIL** |" in diag
    assert "| `aead_conv_null` | aead_conv_null | 50 | 40.0<!--M:T-DUDECT-MAXT-AEAD-CONV-NULL--> | **FAIL** |" in diag
    assert "| 9 | `aead_conv_sym` | aead_conv_sym | 50 | 2.4<!--M:T-DUDECT-MAXT-AEAD-CONV-SYM--> | PASS |" in diag
    conv = next(x for x in diag.splitlines() if x.startswith("- `aead_conv`:"))
    assert "reproduced in 2 of 2 seeds" in conv and "FAIL in 2 of 2 series" in conv
    assert "keeps its sign in 2 of 2 seeds" in conv and "PASSES in 4 of 4 series" in conv
    assert "the difference follows the staging, not the contents" in conv
    assert "585 to 585 MHz with the S2 staging and 1200 to 1500 MHz without it: the staging and the clock" in conv
    call = next(x for x in diag.splitlines() if x.startswith("- `write_epoch` (whole call):"))
    assert "FAIL in 1 of 1 series" in call and "follows the staging" in call and "change together" not in call
    assert "although their S2 series PASSES: `write_epoch_fresh` (device stages) at seed 8." in diag
    assert "constant time" not in diag
    assert "staging_diagnostics.csv" in s["files"] and s["diagnostics"]["issue"] == "ISSUE-D"
    assert s["fails"] == ["write_epoch:call_ms", "aead_conv:ms"] and "aead_conv_null:ms:s9" in s["diagnostic_fails"]
    table = (tree["root"] / "out" / "summary_table.csv").read_text(encoding="utf-8").splitlines()
    assert any(x.startswith("aead_conv,ms,dudect,50,12.0,raw,FAIL,PASS") for x in table)
    assert any(x.startswith("aead_conv_sym,ms,diagnostic_s8,50,2.4,,PASS,PASS,1500-1500") for x in table)
    rows = (tree["root"] / "out" / "staging_diagnostics.csv").read_text(encoding="utf-8")
    assert "diagnostic,8,aead_conv_swap,ms,aead_conv,swap,aead_conv_swap,50,34.0,FAIL,PASS,-,585-585" in rows


def test_without_diagnostics_the_fails_stay_open(tree: dict[str, Path]) -> None:
    notes = tree["root"] / "notes.md"
    s = _generate(tree, notes=notes)
    text = notes.read_text(encoding="utf-8")
    assert "it blocks M14" in text and "### Diagnostics" not in text and "diagnostics" not in s
    assert "Three target series FAIL and are open (ISSUE-A)" in text


@pytest.mark.parametrize(("kw", "expect", "never"), [
    ({"sym": "FAIL"}, "**a FAIL remains without the S2 staging**", "follows the staging"),
    ({"original": ("FAIL", "PASS")}, "reproduced in 1 of 2 seeds, so the diagnostics do not explain it", "Reading:"),
    ({"control": "FAIL"}, "void, the full-N `control_null` of a seed does not PASS", "Reading:"),
])
def test_diagnostics_are_read_by_the_rules_never_softened(tree: dict[str, Path], kw: dict[str, Any], expect: str,
                                                          never: str) -> None:
    diag = _diag_text(tree, **kw)
    conv = next(x for x in diag.splitlines() if x.startswith("- `aead_conv`:"))
    assert expect in conv and never not in conv


def test_diagnostics_count_a_swap_that_changes_its_sign(tree: dict[str, Path]) -> None:
    conv = next(x for x in _diag_text(tree, swap_raw=5.0).splitlines() if x.startswith("- `aead_conv`:"))
    assert "keeps its sign in 0 of 2 seeds" in conv


def test_diagnostics_refuse_a_numpy_run_and_a_second_session(tree: dict[str, Path]) -> None:
    dg = _diag_tree(tree)
    man = json.loads((dg["seeds"][1] / "manifest.json").read_text(encoding="utf-8"))
    man["env"]["session_id"] = "elsewhere"
    (dg["seeds"][1] / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(ReportError, match="never merge two sessions"):
        _generate(tree, diagnostics=dg)
    man["env"]["backend"] = "numpy"
    (dg["seeds"][1] / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(ReportError, match="not an ingested cupy run"):
        _generate(tree, diagnostics=dg)
