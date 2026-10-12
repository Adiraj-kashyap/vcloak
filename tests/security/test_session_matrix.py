"""M11 S6: the E5 attack matrix (bench/run_session_matrix.py) and the published copy of its result.

The matrix runs here with a cheap Argon2id cost; the published file comes from a run with the real one."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from vcloak import runs
from vcloak.service.session import PROOF_CHECKS, TICKET_CHECKS, TOKEN_CHECKS, PasswordParams

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import run_session_matrix as rsm  # noqa: E402

CHEAP = PasswordParams(t=1, m_kib=64, p=1)  # tests only
PUBLISHED = ROOT / "results" / "session" / "e5_matrix.json"
# the eleven session rows and the key-agreement row of seed/vcloak_oracle.py `session_tests`
SEED_SCENARIOS = (
    "Valid token + fresh DPoP proof", "Replayed proof (same jti)", "Stolen token, attacker's own key",
    "Proof for different URL (htu)", "Proof for different method (htm)", "Stale proof (iat -5 min)",
    "Expired access token", "Tampered access token", "Refresh-token rotation", "Old refresh token reused",
    "Rotated token after reuse detected", "X25519+HKDF content key agreement",
)
M11_SCENARIOS = ("Ticket reused", "Ticket presented with a different key",
                 "Login brute force: sixth guess on one account")
REASONS = {"reuse", "family_revoked", "key_binding", "rate_limited", "session_ended"}


@pytest.fixture(scope="module")
def rows() -> list[dict[str, Any]]:
    return rsm.run_matrix(CHEAP)


def test_a1_every_scenario_is_as_expected(rows: list[dict[str, Any]]) -> None:
    assert [r["id"] for r in rows] == list(range(1, len(rows) + 1))
    assert all(r["as_expected"] for r in rows), [r for r in rows if not r["as_expected"]]
    names = [r["scenario"] for r in rows]
    assert len(names) == len(set(names)) >= 15
    assert set(SEED_SCENARIOS) <= set(names) and set(M11_SCENARIOS) <= set(names)


def test_a1_each_refusal_names_a_check_and_each_acceptance_none(rows: list[dict[str, Any]]) -> None:
    known = set(PROOF_CHECKS) | set(TOKEN_CHECKS) | set(TICKET_CHECKS) | REASONS
    for r in rows:
        assert set(r) == {"id", "scenario", "channel", "expected", "observed", "expected_check", "failed_check",
                          "as_expected"}
        assert r["channel"] in ("http", "websocket", "client")
        refused = r["observed"].startswith(("401", "429", "close"))
        assert (r["failed_check"] in known) if refused else (r["failed_check"] is None), r
        assert r["failed_check"] == r["expected_check"]
    by_name = {r["scenario"]: r["failed_check"] for r in rows}
    assert by_name["Stolen token, attacker's own key"] == "key_binding"
    assert by_name["Ticket reused"] == "ticket_unused"
    assert by_name["Ticket presented with a different key"] == "ticket_key"
    assert by_name["Old refresh token reused"] == "reuse"


def test_the_matrix_holds_no_token(rows: list[dict[str, Any]]) -> None:
    text = json.dumps(rows)
    assert "eyJ" not in text  # no JWS segment: neither a proof nor an access token
    assert max(len(word) for word in text.replace('"', " ").split()) < 40


def test_a_mismatch_is_reported_not_hidden() -> None:
    m = rsm.Matrix(client=None, clock=rsm.ShiftedClock(), password="")
    m.record("accepted although it must not be", "http", (401, "jti"), (200, None))
    m.record("refused for another reason", "http", (401, "jti"), (401, "iat"))
    assert [r["as_expected"] for r in m.rows] == [False, False]
    assert m.rows[0]["observed"] == "200" and m.rows[1]["expected"] == "401 (jti)"
    assert m.rows[1]["failed_check"] == "iat" and m.rows[1]["expected_check"] == "jti"


def test_time_verify_times_accepted_requests_only() -> None:
    t = rsm.time_verify(40, 5)
    assert (t["n"], t["warmup"], t["clock"]) == (40, 5, "time.perf_counter_ns")
    assert 0 < t["min_us"] <= t["p05_us"] <= t["median_us"] <= t["p95_us"] <= t["max_us"]


def test_main_writes_a_run_and_the_result_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    run_matrix = rsm.run_matrix
    monkeypatch.setattr(rsm, "run_matrix", lambda: run_matrix(CHEAP))
    assert rsm.main(["--quick", "--runs", "30", "--warmup", "3", "--out", str(tmp_path / "runs"),
                     "--results", str(tmp_path / "results")]) == 0
    (run_dir,) = (tmp_path / "runs").iterdir()
    assert run_dir.name.endswith("_M11_session_matrix_quick") and runs.validate_manifest(run_dir) == []
    manifest = runs.read_manifest(run_dir)
    assert (manifest["module"], manifest["step"], manifest["owner"]) == ("M11", "S6", "Divyansh")
    assert manifest["quick"] is True
    assert manifest["env"]["backend"] == "numpy" and manifest["status"] == "OK"
    assert manifest["outputs"] == ["e5_matrix.json", "summary.json", "verify_timing.json"]
    matrix = json.loads((run_dir / "e5_matrix.json").read_text(encoding="utf-8"))
    assert matrix == json.loads((tmp_path / "results" / "e5_matrix.json").read_text(encoding="utf-8"))
    assert matrix["run_id"] == run_dir.name and matrix["as_expected"] == matrix["scenarios"] == len(matrix["rows"])
    metrics = {m["id"]: m["value"] for m in json.loads((run_dir / "summary.json").read_text())["metrics"]}
    timing = json.loads((run_dir / "verify_timing.json").read_text(encoding="utf-8"))
    assert metrics == {"SEC-E5-PASS": f"{matrix['scenarios']}/{matrix['scenarios']}",
                       "SEC-DPOP-VERIFY-US": timing["median_us"]}
    assert timing["n"] == 30
    assert f"SEC-E5-PASS {matrix['scenarios']}/{matrix['scenarios']}" in capsys.readouterr().out


def test_the_published_matrix_is_a_full_run_of_the_current_scenarios(rows: list[dict[str, Any]]) -> None:
    if not PUBLISHED.exists():
        pytest.skip("results/session/e5_matrix.json is written by bench/run_session_matrix.py (M11 S6)")
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    assert published["experiment"] == "E5" and (ROOT / "runs" / published["run_id"] / "e5_matrix.json").exists()
    assert not published["run_id"].endswith("_quick")
    assert ([(r["scenario"], r["expected"]) for r in published["rows"]]
            == [(r["scenario"], r["expected"]) for r in rows])
    assert all(r["as_expected"] for r in published["rows"])
    assert published["as_expected"] == published["scenarios"] == len(rows)
