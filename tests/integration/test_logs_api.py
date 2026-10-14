"""M18 S5: `/v1/logs`, the Logs view's tail of state/ through the redaction of `vcloak.service.logsapi` (audit A4).

The redaction test drives traffic through the service, takes every value that traffic produced (conversation
tokens in both client forms, the conversation id and its hex, buckets, row ids, sealed sequence numbers,
payloads) and writes them into a copy of state/ the way a careless log line would. Then it reads every kind
through the endpoint and greps the answers for each value. The real state/ files are served too: no absolute
path and no address may come out of them.
"""
from __future__ import annotations

import base64
import json
import random
import re
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vcloak.cli import build_backend, build_parser
from vcloak.crypto.client import PAYLOAD_LEN
from vcloak.service.app import create_app
from vcloak.service.logsapi import KINDS, STATE_DIR, TAIL_MAX, redact_line
from vcloak.service.models import conv_id_of

HEX_TOKEN = "3f9a1c0be47d52a86c1e0f9d7b2a4c61"  # the form of tests/service_contract.token()
B64_TOKEN = base64.urlsafe_b64encode(bytes(range(7, 31))).decode()  # the browser's form: 24 bytes, base64url
ABS_PATH = re.compile(r"(?<![\w.])(?:[A-Za-z]:[\\/]|\\\\)|(?<![\w.~])/(?:home|Users|kaggle|content|tmp|[a-z])/")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def app_client(*, dev: bool, state_dir: Path | None = None) -> TestClient:
    a = build_parser().parse_args(["serve", "--store", "sqlite", "--dev", "--epoch-ms", "50", "--window-s", "1"])
    return TestClient(create_app(build_backend(a), dev=dev, web_dir=False, state_dir=state_dir))


def served(c: TestClient, kind: str) -> dict[str, Any]:
    r = c.get(f"/v1/logs?kind={kind}&tail={TAIL_MAX}")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store", kind
    return r.json()


def drive_traffic(c: TestClient) -> list[dict[str, Any]]:
    """Messages of two conversations, stored; the rows as the store holds them."""
    for token in (HEX_TOKEN, B64_TOKEN):
        for i in range(6):
            body = {"conv_token": token, "payload_b64": base64.b64encode(bytes([i + 40]) * PAYLOAD_LEN).decode(),
                    "ack": "stored"}
            assert c.post("/v1/messages", json=body).status_code == 201
    deadline = time.monotonic() + 20
    while True:
        d = c.get("/v1/dump?limit=500&windows=16").json()
        if d["total"] == 12:
            return d["rows"]
        assert time.monotonic() < deadline, d["total"]
        time.sleep(0.1)


def test_refused_without_dev(tmp_path: Path) -> None:
    with app_client(dev=False, state_dir=tmp_path) as c:
        for kind in KINDS:
            r = c.get(f"/v1/logs?kind={kind}")
            assert r.status_code == 403 and r.json() == {"error": "dev_only"}, kind


def test_kind_is_one_of_four_names_never_a_path() -> None:
    with app_client(dev=True) as c:
        for bad in ("kind=../README", "kind=SESSION_LOG.md", "kind=state/ISSUES.md", "kind=",
                    "kind=session&tail=0", f"kind=session&tail={TAIL_MAX + 1}", "kind=session&tail=x", ""):
            assert c.get("/v1/logs?" + bad).status_code == 422, bad
        body = json.dumps(served(c, "issues"))
        assert str(STATE_DIR) not in body and "ISSUES.md\"" not in body and "state/" not in json.dumps(
            {k: v for k, v in served(c, "issues").items() if k != "lines"})


def test_traffic_values_written_into_the_logs_are_never_served(tmp_path: Path) -> None:
    state = tmp_path / "state"
    shutil.copytree(STATE_DIR, state, ignore=shutil.ignore_patterns("*.tmp"))
    with app_client(dev=True, state_dir=state) as c:
        rows = drive_traffic(c)
        secrets: set[str] = {HEX_TOKEN, B64_TOKEN, str(tmp_path)}
        for tok in (HEX_TOKEN, B64_TOKEN):
            cid = conv_id_of(tok)
            secrets |= {str(cid), cid.to_bytes(8, "little").hex()}
        for r in rows:
            secrets |= {r["payload_b64"], r["seq_enc_b64"], r["payload_b64"].rstrip("="), r["seq_enc_b64"].rstrip("=")}
        leaky = []
        for r in rows:
            cid = conv_id_of(HEX_TOKEN)
            leaky += [
                f"event=stored conv_token={HEX_TOKEN} bucket={r['bucket']} row_id={r['row_id']} seq=5",
                json.dumps({"conv_token": B64_TOKEN, "bucket": str(r["bucket"]), "row_id": r["row_id"]}),
                f"stored {r['payload_b64']} with {r['seq_enc_b64']}",
                f"- the client sent {B64_TOKEN} and {HEX_TOKEN} for conversation {cid} ({cid.to_bytes(8, 'little').hex()})",
                f"- Evidence: {tmp_path}\\runs\\x and /home/someone/vcloak/runs/x, mail someone@example.org",
            ]
        for name in KINDS.values():
            with (state / name).open("a", encoding="utf-8") as f:
                f.write("\n".join(leaky) + "\n")

        for kind in KINDS:
            got = served(c, kind)
            text = "\n".join(got["lines"])
            assert got["missing"] is False and got["redacted"] >= len(leaky), kind
            for s in secrets:
                assert s not in text, (kind, "a traffic value was served")
            assert not re.search(r"\b(bucket|row_id|seq)(=|\": \")\d", text), kind  # the planted forms
            assert not ABS_PATH.search(text) and not EMAIL.search(text), kind
            assert "- Evidence: <path> and <path>, mail <email>" in text  # the rest of the line is still served


def test_the_real_state_files_are_served_redacted() -> None:
    with app_client(dev=True) as c:
        for kind, name in KINDS.items():
            raw = (STATE_DIR / name).read_text(encoding="utf-8", errors="replace").splitlines()
            got = served(c, kind)
            assert got["total"] == len(raw) and got["lines"] == [redact_line(x)[0] for x in raw[-TAIL_MAX:]]
            text = "\n".join(got["lines"])
            assert not ABS_PATH.search(text) and not EMAIL.search(text), kind
        few = c.get("/v1/logs?kind=session&tail=5").json()
        assert len(few["lines"]) == 5 and few["tail"] == 5


def test_a_missing_file_is_said_not_invented(tmp_path: Path) -> None:
    with app_client(dev=True, state_dir=tmp_path) as c:
        assert served(c, "audit") == {"kind": "audit", "lines": [], "total": 0, "redacted": 0, "missing": True}


@pytest.mark.parametrize("line", [
    "- Evidence: runs/20261014-102648_M18_s4_live_attack, evidence/screens/M18_experiments_light_20261014.png",
    "| S-F-BASELINE | 0.8894142583459015 | fraction | seed 2026 | M14 | runs/20261013-103235_M14_security_e0e1 |",
    "| K-BITONIC-E2E-MS-2^12 | 0.21541 | ms | median | M07 | python bench/run_kernels.py --part gpu --seed 7 |",
    "  aead_ref.py (seal_seq/open_seq through `cryptography` ChaCha20Poly1305); Submission/StoredRow/RefKeys",
    "  the driver option NVreg_RestrictProfilingToAdminUsers=0; colab/VCloak_GPU_Runner.ipynb; M14_S2S5_*",
    "- Commit: cdd7560",
])
def test_names_numbers_and_run_dirs_are_kept(line: str) -> None:
    assert redact_line(line) == (line, False)


def test_random_client_tokens_are_caught() -> None:
    """The base64 rule is a heuristic: a bound on its misses for the browser's token form is pinned here (the
    counts are in runs/<...>_M18_s5_checks/redaction_rate.txt); hex tokens and conversation ids are always caught."""
    rng = random.Random(2026)
    n = 20000
    miss = sum(t in redact_line(f"x {t} y")[0]
               for t in (base64.urlsafe_b64encode(rng.randbytes(24)).decode() for _ in range(n)))
    assert miss <= n // 1000
    for _ in range(2000):
        h = rng.randbytes(16).hex()
        assert h not in redact_line(f"x {h} y")[0]
        cid = str(rng.getrandbits(64) | 1 << 60)
        assert cid not in redact_line(f"conversation {cid}")[0]
