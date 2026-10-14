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


# M18 S3: the charts. Each draws only indexed rows or the run files those rows name.
S3_CHARTS = ("e2e_latency_u10", "kernel_sweep", "pipeline_device", "attack_ablation", "tau_hist", "session_matrix")


def _chart(data: dict, cid: str) -> dict:
    return next(c for c in data["charts"] if c["id"] == cid)


def test_every_chart_names_indexed_ids_and_existing_runs():
    data = _module().build(INDEX, ROOT)
    rows, _ = _module().check_metrics.parse_index(INDEX)
    ids = {r["id"] for r in rows}
    for cid in S3_CHARTS:
        assert _chart(data, cid)
    for c in data["charts"]:
        assert c["metric_ids"] and set(c["metric_ids"]) <= ids, c["id"]
        assert all((ROOT / r).is_dir() for r in c["runs"]), c["id"]


def test_the_leakage_sentence_is_stated_and_grouping_is_never_a_word():
    sec = next(g for g in _module().build(INDEX, ROOT)["groups"] if g["id"] == "security")
    assert "does not conceal which rows belong to the same conversation" in sec["note"]
    assert "grouping" not in ROOT.joinpath("web", "data", "dashboard.json").read_text(encoding="utf-8").lower()


def test_kernel_points_are_the_indexed_values_and_unstable_sizes_are_gaps(tmp_path):
    ed = _module()
    data = ed.build(INDEX, ROOT)
    best = ed.pick(ed.check_metrics.parse_index(INDEX)[0])
    k = _chart(data, "kernel_sweep")
    for s, (_, pattern, _) in zip(k["series"], ed.KERNEL_SERIES, strict=True):
        for n, v in s["points"]:
            row = best.get(pattern.format(e=n.bit_length() - 1))
            assert v == (None if row is None else ed._num(row["value"]))
    assert k["crossover"] is None and "NOT MEASURED" in k["note"]  # X-CROSSOVER-N is UNSTABLE in the index

    mid = "K-BITONIC-FUSED-MS-2^16"

    def unstable(ln: str) -> str:
        if ln.startswith(f"| {mid} |"):
            cells = ln.split("|")
            cells[2] = " UNSTABLE "
            return "|".join(cells)
        return ln
    gpu = _chart(ed.build(_doctored(tmp_path, unstable), ROOT), "kernel_sweep")["series"][0]["points"]
    assert [v for n, v in gpu if n == 2 ** 16] == [None]


def test_pipeline_bars_come_from_one_run_and_never_show_host_or_whole_call():
    ed = _module()
    rows, _ = ed.check_metrics.parse_index(INDEX)
    p = _chart(ed.build(INDEX, ROOT), "pipeline_device")
    assert len(p["runs"]) == 1 and all(m.startswith("P-WRITE-EPOCH-DEVICE-MS-S") for m in p["metric_ids"])
    for mid, v in zip(p["metric_ids"], p["series"][0]["values"], strict=True):
        assert any(r["id"] == mid and r["run_dir"] == p["runs"][0] and round(float(r["value"]), 3) == v for r in rows)
    assert "ISSUE-12" in p["note"] and p["refLine"]["value"] == ed.config.EPOCH_MS


def test_latency_cdfs_draw_the_repetitions_apart_from_valid_cells_only():
    data = _module().build(INDEX, ROOT)
    excluded = {e["users"] for e in data["excluded"]}
    cdfs = [c for c in data["charts"] if c["kind"] == "cdf"]
    assert cdfs and not any(c["id"] == f"e2e_latency_u{u}" for c in cdfs for u in excluded)
    for c in cdfs:
        assert sorted((s["slot"], s["dash"]) for s in c["series"]) == [(1, False), (1, True), (2, False), (2, True)]
        for s in c["series"]:
            xs = [x for x, _ in s["points"]]
            assert xs == sorted(xs) and s["points"][-1][1] == 1.0 and s["n"] > 0


def test_attack_prediction_is_the_runs_own_and_absent_for_arrival_order():
    a = _chart(_module().build(INDEX, ROOT), "attack_ablation")
    pred = next(s for s in a["series"] if s["name"].startswith("Predicted"))
    assert pred["values"][0] is None and all(v is not None for v in pred["values"][1:])
    run = json.loads((ROOT / a["runs"][0] / "e1_attack.json").read_text(encoding="utf-8"))
    w300 = next(x for x in run["layouts"] if x["layout"] == "W300")
    assert pred["values"][-1] == round(w300["attack"]["predicted_turn_accuracy"] * 100, 1)


def test_experiment_layouts_carry_the_indexed_value_at_full_precision_and_the_replay(tmp_path):
    """M18 S4: the live run is compared with these, so the value is the index's own, unrounded, with the seed
    and sizes of the run that produced it; a deleted row leaves nothing to compare with."""
    ed = _module()
    exp = ed.build(INDEX, ROOT)["experiments"]["attack"]
    assert exp["endpoint"] == "/v1/eval/attack"
    rows, _ = ed.check_metrics.parse_index(INDEX)
    for x in exp["layouts"]:
        assert any(r["id"] == x["metric_id"] and float(r["value"]) == x["value"] and r["run_dir"] == x["run"]
                   for r in rows)
        man = json.loads((ROOT / x["run"] / "manifest.json").read_text(encoding="utf-8"))
        assert x["seed"] == man["seed"] and x["params"]["n_conv"] == man["params"]["n_conv"]
        assert (x["predicted"] is None) == (x["layout"] == "BASELINE")
    mid = "S-TURNACC-W60"
    idx = _doctored(tmp_path, lambda ln: None if ln.startswith(f"| {mid} |") else ln)
    gone = next(x for x in ed.build(idx, ROOT)["experiments"]["attack"]["layouts"] if x["metric_id"] == mid)
    assert gone["value"] is None and "run" not in gone


def _arch_evidence(data: dict, mid: str) -> dict:
    return next(e for r in data["architecture"]["leak"] for e in r["evidence"] if e["metric_id"] == mid)


def test_architecture_flow_is_the_spec_with_parameters_from_config():
    ed = _module()
    a = ed.build(INDEX, ROOT)["architecture"]
    spec = ROOT.joinpath("ai", "ARCHITECTURE.md").read_text(encoding="utf-8")
    flow = spec[spec.index("## 2. Data-state flow"):spec.index("## 3.")]
    ids = [s["id"] for s in a["write"] + a["read"]]
    assert ids == [f"S{i}" for i in range(11)] + [f"R{i}" for i in range(1, 6)]
    assert all(f"{i} " in flow for i in ids)
    assert [s["id"] for s in a["write"] + a["read"] if s["durable"]] == ["S9", "S10"]  # "Only S9 and S10 are durable"
    assert all(s["where"] == "db" for s in a["write"] if s["durable"])
    assert a["params"] == {p: getattr(ed.config, p) for p in ed.ARCH_PARAMS}
    text = json.dumps(a, ensure_ascii=False)
    assert "{" not in "".join(s["d"] for s in a["write"] + a["read"])  # every placeholder was filled
    assert f"BLOCK = {ed.config.BLOCK} bytes" in text and f"EPOCH_MS = {ed.config.EPOCH_MS} ms" in text


def test_architecture_leak_table_states_adr031_and_the_brief_leakage():
    ed = _module()
    a = ed.build(INDEX, ROOT)["architecture"]
    adr = ROOT.joinpath("ai", "DECISIONS.md").read_text(encoding="utf-8")
    assert " ".join(a["leak_sentence"].split()) in " ".join(adr.split())  # ADR-031 item 2, as written
    status = {r["observable"]: r["status"] for r in a["leak"]}
    assert status["Order of storage within a window"] == "concealed"
    for obs in ("Full read/write access pattern", "Order across windows", "Real messages per window",
                "Order of the newest data", "Anything a compromised live server sees"):
        assert status[obs] == "visible", obs
    assert status["Which rows belong to one conversation"] == "partly visible"
    assert "grouping" not in json.dumps(a).lower()


def test_architecture_evidence_is_the_indexed_value_or_not_measured(tmp_path):
    ed = _module()
    rows, _ = ed.check_metrics.parse_index(INDEX)
    e = _arch_evidence(ed.build(INDEX, ROOT), "S-TAU-WITHIN-W60")
    assert any(r["id"] == e["metric_id"] and r["value"] == e["raw"] and r["run_dir"] == e["run"] for r in rows)
    mid = "S-TURNACC-W60"
    data = ed.build(_doctored(tmp_path, lambda ln: None if ln.startswith(f"| {mid} |") else ln), ROOT)
    assert _arch_evidence(data, mid)["value"] is None
    assert [m["metric_id"] for m in data["missing"]].count(mid) == 1


def _figure_setup(tmp_path: Path, ed) -> tuple[Path, Path, list[str]]:
    out = tmp_path / "dashboard.json"
    out.write_text(ed.render(ed.build(INDEX, ROOT)), encoding="utf-8")
    charts = [c["id"] for c in json.loads(out.read_text(encoding="utf-8"))["charts"] if not c.get("pending")]
    figs = tmp_path / "figures"
    figs.mkdir()
    sha = ed.hashlib.sha256(out.read_bytes()).hexdigest()
    for cid in charts:
        (figs / f"M18_dash_{cid}.json").write_text(json.dumps({"drawn_from": {"sha256": sha}}), encoding="utf-8")
    return out, figs, charts


def test_check_fails_on_a_stale_dashboard_and_on_stale_figures(tmp_path):
    """M18 S7: `tasks.py dashboard --check` (M17 S1) refuses a dashboard.json or a paper figure that is not current."""
    ed = _module()
    out, figs, charts = _figure_setup(tmp_path, ed)
    args = ["--check", "--out", str(out), "--figures", str(figs)]
    assert ed.main(args) == 0
    assert ed.stale_figures(out, figs) == []
    out.write_bytes(out.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))  # other checkout, same content
    assert ed.stale_figures(out, figs) == []
    (figs / f"M18_dash_{charts[0]}.json").write_text(json.dumps({"drawn_from": {"sha256": "0" * 64}}), encoding="utf-8")
    (figs / f"M18_dash_{charts[1]}.json").unlink()
    assert ed.stale_figures(out, figs) == [charts[0], f"{charts[1]} (no figure)"]
    assert ed.main(args) == 1
    out.write_text(out.read_text(encoding="utf-8").replace('"charts"', '"charts_old"', 1), encoding="utf-8")
    assert ed.main(args) == 1


def test_tasks_py_runs_the_exporter():
    spec = importlib.util.spec_from_file_location("tasks", ROOT / "tasks.py")
    tasks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tasks)
    assert tasks.TASKS["dashboard"] == [[tasks.PY, "scripts/export_dashboard.py"]]
