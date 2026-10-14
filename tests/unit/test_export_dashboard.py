"""M18 S1: the dashboard exporter shows only indexed values; what is absent or not a value lands in `missing`."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "state" / "METRICS_INDEX.md"
pytestmark = pytest.mark.skipif(not INDEX.exists(), reason="the exporter reads state/, which a job bundle does not ship")


def _module():
    spec = importlib.util.spec_from_file_location("export_dashboard", ROOT / "scripts" / "export_dashboard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _doctored(tmp_path: Path, edit) -> Path:
    lines = [edit(ln) for ln in INDEX.read_text(encoding="utf-8").splitlines()]
    out = tmp_path / "METRICS_INDEX.md"
    out.write_text("\n".join(ln for ln in lines if ln is not None) + "\n", encoding="utf-8")
    return out


def _tile(data: dict, mid: str) -> dict:
    return next(t for t in data["tiles"] if t["metric_id"] == mid)


def test_every_shown_value_is_the_indexed_value():
    ed = _module()
    data = ed.build(INDEX, ROOT)
    rows, _ = ed.check_metrics.parse_index(INDEX)
    for t in data["tiles"]:
        if t["value"] is None:
            continue
        assert any(r["id"] == t["metric_id"] and r["value"] == t["raw"] and r["run_dir"] == t["run"] for r in rows)


def test_gpu_utilisation_group_comes_first_with_its_framing():
    data = _module().build(INDEX, ROOT)
    assert data["groups"][0]["id"] == "gpu" and data["tiles"][0]["group"] == "gpu"
    assert data["tiles"][0]["metric_id"].startswith("E2E-GPUUTIL-U")
    assert data["framing"][0]["id"] == "gpu_utilisation"
    assert any("not a capacity" in p for p in data["framing"][0]["points"])


def test_deleting_a_row_moves_its_tile_to_missing(tmp_path):
    ed = _module()
    mid = "K-BITONIC-FUSED-MS-2^16"
    idx = _doctored(tmp_path, lambda ln: None if ln.startswith(f"| {mid} |") else ln)
    data = ed.build(idx, ROOT)
    assert _tile(data, mid)["value"] is None
    assert mid in [m["metric_id"] for m in data["missing"]]
    assert mid not in [m["metric_id"] for m in ed.build(INDEX, ROOT)["missing"]]


def test_unstable_rows_are_not_values_and_their_user_counts_are_excluded():
    data = _module().build(INDEX, ROOT)
    assert _tile(data, "X-CROSSOVER-N")["value"] is None  # UNSTABLE in the index
    excluded = {e["users"] for e in data["excluded"]}
    assert not any(f"-U{u}" in t["metric_id"] for t in data["tiles"] for u in excluded)
    gpu_chart = next(c for c in data["charts"] if c["id"] == "e2e_gpu_util")
    assert not any(f"{u} users" in gpu_chart["categories"] for u in excluded)


def test_quick_metric_is_marked_and_never_a_headline(tmp_path):
    ed = _module()

    def make_quick(ln: str) -> str:
        if ln.startswith("| S-CHI2-P |"):
            cells = ln.split("|")
            cells[9] = " yes "
            return "|".join(cells)
        return ln
    t = _tile(ed.build(_doctored(tmp_path, make_quick), ROOT), "S-CHI2-P")
    assert t["quick"] is True and t["headline"] is False


def test_committed_json_is_current():
    ed = _module()
    assert ed.OUT.read_text(encoding="utf-8") == ed.render(ed.build(INDEX, ROOT))
    json.loads(ed.OUT.read_text(encoding="utf-8"))


# M18 S2: the headline tiles and how they are stated.
S2_HEADLINES = ("S-TURNACC-BASELINE", "S-TURNACC-EPOCH", "S-TURNACC-W300", "S-E0-RESTORE", "S-CHI2-P",
                "T-DUDECT-MAXT-BITONIC-EQUAL", "T-DUDECT-MAXT-BITONIC-SORTED", "K-BITONIC-FUSED-MS-2^16",
                "X-CROSSOVER-N", "SEC-E5-PASS")


def test_every_s2_headline_has_a_tile_with_its_provenance():
    data = _module().build(INDEX, ROOT)
    groups = {g["id"] for g in data["groups"]}
    for mid in S2_HEADLINES:
        t = _tile(data, mid)
        assert t["group"] in groups
        if t["value"] is not None:
            assert t["run"] and t["backend"] and t["runner"] and t["stat"]


def test_dudect_verdict_follows_the_threshold_and_host_timing_is_never_a_headline(tmp_path):
    ed = _module()
    data = ed.build(INDEX, ROOT)
    host = _tile(data, "T-DUDECT-MAXT-WRITE-EPOCH-CALL")
    assert host["headline"] is False and "outside the claim" in host["sub"]
    for t in data["tiles"]:
        assert "constant time" not in t.get("sub", "")
    mid = "T-DUDECT-MAXT-BITONIC-EQUAL"

    def raise_t(ln: str) -> str:
        if ln.startswith(f"| {mid} |"):
            cells = ln.split("|")
            cells[2] = f" {ed.dudect.T_THRESHOLD * 2} "
            return "|".join(cells)
        return ln
    assert _tile(data, mid)["state"] == ("good" if abs(float(_tile(data, mid)["raw"])) < ed.dudect.T_THRESHOLD
                                         else "crit")
    doctored = _tile(ed.build(_doctored(tmp_path, raise_t), ROOT), mid)
    assert doctored["state"] == "crit" and doctored["sub"].startswith("FAIL")


def test_groups_name_their_framing_and_the_leakage_is_stated():
    data = _module().build(INDEX, ROOT)
    framing = {f["id"] for f in data["framing"]}
    assert all(g["framing"] in framing for g in data["groups"] if "framing" in g)
    sec = next(g for g in data["groups"] if g["id"] == "security")
    assert "window ids" in sec["note"]
