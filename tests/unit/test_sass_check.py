"""M08 S3: scripts/sass_check.py on a HAND-WRITTEN listing in the layout of `cuobjdump -sass` (tests/data/
sass_synthetic.txt). It checks the parser and the predicate trace, not any real machine code: the real
listings exist only on the runner."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sass_check as sc  # noqa: E402

LISTING = (ROOT / "tests" / "data" / "sass_synthetic.txt").read_text(encoding="utf-8")


def by_name() -> dict[str, dict]:
    return {f["function"]: f for f in sc.analyse_listing(LISTING)}


def test_functions_and_instruction_counts() -> None:
    funcs = by_name()
    assert list(funcs) == ["clean_kernel", "leaky_kernel"]
    assert funcs["clean_kernel"]["instructions"] == 15 and funcs["leaky_kernel"]["instructions"] == 10


def test_public_branches_are_traced_to_ids_and_parameters() -> None:
    f = by_name()["clean_kernel"]
    rows = {r["addr"]: r for r in f["rows"]}
    assert rows["0050"]["class"] == "public" and set(rows["0050"]["leaves"]) == {"id", "param"}
    assert rows["00b0"]["class"] == "public" and set(rows["00b0"]["leaves"]) == {"imm", "param"}
    assert rows["00d0"]["class"] == "unconditional" and rows["00e0"]["class"] == "unconditional"
    assert (f["conditional"], f["public"], f["data"], f["unknown"], f["sync"]) == (2, 2, 0, 0, 0)
    assert f["branches"] == 3  # two conditional and the jump at 00e0; the final EXIT is not a branch


def test_a_branch_on_loaded_data_is_DATA_and_an_unwritten_register_is_unknown() -> None:  # noqa: N802
    f = by_name()["leaky_kernel"]
    rows = {r["addr"]: r for r in f["rows"]}
    assert rows["0040"]["class"] == "DATA" and "global" in rows["0040"]["leaves"]
    assert rows["0040"]["predicate"] == ["!P0"]
    assert rows["0080"]["class"] == "unknown"
    assert rows["0030"]["class"] == "sync" and rows["0060"]["class"] == "sync"
    assert (f["data"], f["unknown"], f["sync"]) == (1, 1, 2)


def test_stores_and_memory_operands_write_no_register() -> None:
    assert sc.parse_instr(0, "STG.E.64.SYS [R2], R6").dests == []
    ins = sc.parse_instr(0, "ISETP.GE.U32.AND P0, PT, R0, c[0x0][0x180], PT")
    assert ins.dests == ["P0"] and ins.srcs == ["R0"] and ins.leaves == {"param"}
    ins = sc.parse_instr(0, "@P1 LDS.U.64 R8, [R5+0x10]")
    assert ins.guard == "P1" and ins.dests == ["R8"] and ins.srcs == [] and "shared" in ins.leaves


def test_old_function_header_and_empty_listing() -> None:
    old = ("Function : k\n        /*0000*/     MOV R1, c[0x0][0x28];  /* 0x4000500000a04de4 */\n"
           "        /*0008*/   EXIT;\n")
    (f,) = sc.analyse_listing(old)
    assert f["function"] == "k" and f["instructions"] == 2 and f["branches"] == 0
    assert sc.analyse_listing("nothing here") == []
    assert "no function found" in sc.render("x", [])


def test_render_and_metrics() -> None:
    funcs = sc.analyse_listing(LISTING)
    text = sc.render("synthetic", funcs)
    assert "leaky_kernel: 10 instructions" in text and "DATA" in text and "<- !P0: global, imm" in text
    got = {m["id"]: m["value"] for m in sc.metrics_of({"x.cu": funcs}, None)}
    assert got == {"T-SASS-BRA-CLEAN-KERNEL": 3, "T-SASS-BRA-LEAKY-KERNEL": 2}
    nm = sc.metrics_of({}, "nvcc is not installed on this machine")
    assert [m["value"] for m in nm] == ["NOT_MEASURED"] * 3 and nm[0]["id"] == "T-SASS-BRA-BITONIC"


def test_listing_mode_prints_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert sc.main(["--listing", str(ROOT / "tests" / "data" / "sass_synthetic.txt")]) == 0
    assert "clean_kernel: 15 instructions, 3 branches" in capsys.readouterr().out


def test_compile_without_nvcc_is_not_measured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from vcloak import runs
    from vcloak.gpu.runtime import get_backend

    monkeypatch.setattr(sc.shutil, "which", lambda name: None)
    monkeypatch.setenv("VCLOAK_BACKEND", "numpy")
    assert get_backend().name == "numpy"
    assert sc.main(["--compile", "--arch", "sm_75", "--out", str(tmp_path)]) == 0
    (d,) = tmp_path.glob("*_M08_sass")
    assert runs.read_manifest(d)["status"] == "NOT_MEASURED"
    s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    assert s["reason"] == "nvcc is not installed on this machine"
    assert all(m["value"] == "NOT_MEASURED" for m in s["metrics"]) and not list(d.glob("sass_*.txt"))
