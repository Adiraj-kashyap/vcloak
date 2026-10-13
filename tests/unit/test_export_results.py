"""M16: the exporter writes only values it can trace, and holds back what is not a value."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INPUTS = (ROOT / "state" / "METRICS_INDEX.md", ROOT / "results" / "perf" / "perf_summary.json")
pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in INPUTS),
    reason="the exporter reads state/ and results/, which a job bundle does not ship")


def _module():
    spec = importlib.util.spec_from_file_location("export_results", ROOT / "scripts" / "export_results.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look the module up by name
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def built():
    mod = _module()
    ex = mod.Exporter()
    ex.build()
    return mod, ex


def test_every_contract_macro_is_exported_once(built) -> None:
    _, ex = built
    names = re.findall(r"^\\newcommand\{\\(\w+)\}", ex.files["results/paper/macros.tex"], flags=re.M)
    assert len(names) == len(set(names)) and set(ex.interim()) <= set(names)


def test_a_metric_value_is_the_index_row_and_never_quick_unstable_or_withdrawn(built) -> None:
    _, ex = built
    metric = [e for e in ex.entries if e["kind"] == "metric"]
    assert len(metric) > 100
    for e in metric:
        row = ex.index[(e["metric_ids"][0], e["run_dir"])]
        assert row["quick"].lower() == "no" and row["value"] not in ("UNSTABLE", "NOT_MEASURED"), e
        assert "\\" not in e["value"]
    assert all(e["kind"] != "pending" or e["value"].startswith("\\") for e in ex.entries)


def test_every_entry_names_its_source(built) -> None:
    _, ex = built
    for e in ex.entries:
        if e["kind"] in ("field", "param"):
            assert (ROOT / e["run_dir"] / e["file"]).is_file() and e["path"], e
        elif e["kind"] == "derived":
            assert e["from"] and e["how"], e
        elif e["kind"] == "pending":
            assert e["reason"], e


def test_withdrawn_and_stale_measurements_do_not_reach_the_paper(built) -> None:
    _, ex = built
    dudect = ex.files["results/paper/dudect_table.tex"]
    kernel_rows = [ln for ln in dudect.splitlines() if "kernel only" in ln]
    assert kernel_rows and all(ln.count("\\notmeasured") == 2 and "PASS" not in ln for ln in kernel_rows)
    assert "FAIL" in dudect  # a FAIL of the measured series is exported as it is
    pipeline = ex.files["results/paper/pipeline_breakdown.dat"]
    assert [ln for ln in pipeline.splitlines() if not ln.startswith("#")] == ["slots h2d tags sort compact d2h host"]
    held = {h["figure"] for h in json.loads(ex.files["results/figures/figures_index.json"])["held_back"]}
    assert {"fig_write_epoch_host_device", "fig_write_epoch_device_stages"} <= held
    assert "\\resAESus}{\\pending}" in ex.files["results/paper/macros.tex"]
    assert ex.files["results/paper/e2e_table.tex"].count("\\pending") >= 4


def test_tex_check_catches_a_broken_snippet(built) -> None:
    mod, ex = built
    assert ex.check_tex() == []
    broken = mod.Exporter()
    broken.files = {"results/paper/x.tex": "\\newcommand{\\rows}{%\n  a & b \\\\\n  c \\\\\n",
                    "results/paper/y.dat": "{"}
    errs = broken.check_tex()
    assert any("unbalanced" in e for e in errs) and any("number of columns" in e for e in errs)


def test_files_on_disk_are_what_the_exporter_writes(built) -> None:
    _, ex = built
    assert ex.write(check=True) == []
