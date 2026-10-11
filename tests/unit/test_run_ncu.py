"""M08 S4: bench/run_ncu.py against HAND-WRITTEN `ncu` output in the layout of `ncu --csv`. It checks the
parsing and the bookkeeping only; real counters exist only on a runner that permits them."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import fakecupy
from vcloak import runs
from vcloak.gpu.runtime import get_backend

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import run_ncu as rn  # noqa: E402

DIV, UNI = "smsp__sass_branch_targets_threads_divergent", "smsp__sass_branch_targets_threads_uniform"
QUERY = f"""Device 0 (Fake GPU)
---------------------------------------- --------------------------------------------
Metric Name                              Description
---------------------------------------- --------------------------------------------
smsp__inst_executed                      instructions
smsp__sass_branch_targets                Number of unique branch targets
{DIV}   Number of divergent branches
{UNI}     Number of uniform branches
sm__sass_branch_targets                  per SM
"""
HEADER = ('"ID","Process ID","Process Name","Host Name","Kernel Name","Context","Stream","Block Size","Grid Size",'
          '"Device","CC","Section Name","Metric Name","Metric Unit","Metric Value"')


def row(i: int, kernel: str, metric: str, value: str) -> str:
    return (f'"{i}","1","python","host","{kernel}","1","7","(256, 1, 1)","(128, 1, 1)","0","7.5","Command line '
            f'profiler metrics","{metric}","","{value}"')


def csv_text(leak_divergent: str = "32,768") -> str:
    sig = "(unsigned long long*, unsigned long long*, unsigned int*, unsigned int*, unsigned int, unsigned int)"
    body = [row(0, "bitonic_shared_full" + sig, DIV, "0"), row(0, "bitonic_shared_full" + sig, UNI, "1,000"),
            row(1, "bitonic_pairs_global" + sig, DIV, "0"), row(1, "bitonic_pairs_global" + sig, UNI, "256"),
            row(2, "bitonic_pairs_global" + sig, DIV, "0"), row(2, "bitonic_pairs_global" + sig, UNI, "256"),
            row(3, "bitonic_shared" + sig, DIV, "0"), row(3, "bitonic_shared" + sig, UNI, "300"),
            row(4, "aead_open_seq", DIV, "0"), row(4, "aead_open_seq", UNI, "512"),
            row(5, "planted_leak", DIV, leak_divergent), row(5, "planted_leak", UNI, "32,768"),
            row(5, "planted_leak", "smsp__sass_branch_targets", "n/a")]
    head = ["==PROF== Connected to process 1", "ncu_workload backend=cupy n=2^16 mismatches=0", HEADER]
    return "\n".join([*head, *body])


def test_branch_metric_names_come_from_the_query() -> None:
    assert rn.branch_metric_names(QUERY) == ["smsp__sass_branch_targets", DIV, UNI, "sm__sass_branch_targets"]
    assert rn.branch_metric_names("no such thing") == []


def test_parse_and_aggregate() -> None:
    rows = rn.parse_csv(csv_text())
    assert len(rows) == 13 and rn.parse_csv("no header") == []
    agg = rn.by_kernel(rows)
    assert agg["bitonic_pairs_global"][UNI] == {"sum": 512.0, "min": 256.0, "max": 256.0, "launches": 2}
    assert "smsp__sass_branch_targets" not in agg["planted_leak"]  # "n/a" is not a number
    d = rn.divergence(agg["bitonic_pairs_global"])
    assert d["divergent"] == 0.0 and d["efficiency_pct"] == 100.0 and d["launches"] == 2
    leak = rn.divergence(agg["planted_leak"])
    assert leak["divergent"] == 32768.0 and leak["efficiency_pct"] == 50.0


def test_a_percentage_is_never_taken_for_the_counter() -> None:
    m = {"smsp__branch_divergent_pct": {"sum": 3.0, "min": 3.0, "max": 3.0, "launches": 1}}
    assert rn.divergence(m)["divergent"] is None


def test_metrics() -> None:
    per = {k: rn.divergence(m) for k, m in rn.by_kernel(rn.parse_csv(csv_text())).items()}
    got = {m["id"]: m["value"] for m in rn.metrics_of(per, None)}
    assert got == {f"T-NCU-{kind}-{k}": v for k in ("BITONIC-PAIRS-GLOBAL", "BITONIC-SHARED", "BITONIC-SHARED-FULL",
                                                   "AEAD-OPEN-SEQ")
                   for kind, v in (("DIVERGENT", 0.0), ("BRANCHEFF", 100.0))}
    del per["aead_open_seq"]
    missing = {m["id"]: m for m in rn.metrics_of(per, None)}
    assert missing["T-NCU-DIVERGENT-AEAD-OPEN-SEQ"]["value"] == "NOT_MEASURED"
    assert "does not appear" in missing["T-NCU-DIVERGENT-AEAD-OPEN-SEQ"]["note"]
    assert all(m["value"] == "NOT_MEASURED" for m in rn.metrics_of(per, "denied"))


def only_run(out: Path) -> tuple[dict, dict, Path]:
    (d,) = out.glob("*_M08_ncu")
    return runs.read_manifest(d), json.loads((d / "summary.json").read_text(encoding="utf-8")), d


def test_numpy_backend_is_not_measured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rn, "get_backend", lambda: get_backend("numpy"))
    assert rn.main(["--out", str(tmp_path)]) == 0
    m, s, d = only_run(tmp_path)
    assert m["status"] == "NOT_MEASURED" and len(s["metrics"]) == 8
    assert all(x["value"] == "NOT_MEASURED" for x in s["metrics"]) and not list(d.glob("ncu_*"))


def fake_ncu(monkeypatch: pytest.MonkeyPatch, profile_output: str) -> None:
    def run(cmd: list[str], timeout: int) -> tuple[int, str]:  # noqa: ARG001
        if "--version" in cmd:
            return 0, "NVIDIA (R) Nsight Compute Command Line Profiler\nVersion fake\n"
        if "--query-metrics" in cmd:
            return 0, QUERY
        assert cmd[:3] == ["ncu", "--csv", "--metrics"] and DIV in cmd[3]
        return 0, profile_output

    monkeypatch.setattr(rn, "get_backend", fakecupy.backend)
    monkeypatch.setattr(rn.shutil, "which", lambda name: "/usr/bin/ncu")
    monkeypatch.setattr(rn, "_run", run)
    monkeypatch.setenv("VCLOAK_SESSION_ID", "20260101-000000")
    monkeypatch.setenv("VCLOAK_RUNNER", "kaggle")


def test_a_profile_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ncu(monkeypatch, csv_text())
    assert rn.main(["--out", str(tmp_path)]) == 0
    m, s, d = only_run(tmp_path)
    assert m["status"] == "OK" and s["control"]["divergent_seen"] is True and s["rows"] == 13
    assert {x["id"]: x["value"] for x in s["metrics"]}["T-NCU-DIVERGENT-BITONIC-SHARED"] == 0.0
    for name in ("ncu_query_metrics.txt", "ncu_profile_raw.txt", "ncu_branches.csv", "ncu_by_kernel.csv"):
        assert (d / name).exists()


def test_refused_counters_are_not_measured_and_not_a_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ncu(monkeypatch, "==ERROR== ERR_NVGPUCTRPERM - The user does not have permission to access NVIDIA GPU "
                          "Performance Counters on the target device 0.")
    assert rn.main(["--out", str(tmp_path)]) == 0
    m, s, _ = only_run(tmp_path)
    assert m["status"] == "NOT_MEASURED" and "ERR_NVGPUCTRPERM" in s["reason"]
    assert all(x["value"] == "NOT_MEASURED" for x in s["metrics"])


def test_a_blind_counter_fails_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ncu(monkeypatch, csv_text(leak_divergent="0"))
    assert rn.main(["--out", str(tmp_path)]) == 1
    m, _, _ = only_run(tmp_path)
    assert m["status"] == "FAIL" and "planted-leak" in m["notes"]
