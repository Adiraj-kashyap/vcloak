from pathlib import Path

import pytest

import check_metrics

REPO = Path(__file__).resolve().parents[2]


def test_self_test_passes(capsys):
    assert check_metrics.self_test() == 0
    out = capsys.readouterr().out
    assert "ok   numpy_performance_metric_rejected" in out and "never a performance result" in out


def test_gpu_metric_areas():
    for mid in ("K-BITONIC-MS-2^16", "P-WRITE-EPOCH-P99-S65536", "T-DUDECT-T-BITONIC", "E2E-P99-U100-VCLOAK",
                "ENV-D2D-BW"):
        assert check_metrics.is_gpu_metric(mid)
    for mid in ("S-TURNACC-W60", "S-CHI2-P"):
        assert not check_metrics.is_gpu_metric(mid)


def test_repo_index_parses():
    if not (REPO / "state" / "METRICS_INDEX.md").exists():
        pytest.skip("state/ is not shipped in a job bundle")
    rows, errs = check_metrics.parse_index(REPO / "state" / "METRICS_INDEX.md")
    assert errs == []
    assert all(r["id"] for r in rows)
