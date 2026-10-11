"""M02 S6: the secrets scanner (G4) flags planted keys and accepts only what its allow rules cover."""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

import pytest

import check_secrets

REPO = Path(__file__).resolve().parents[2]


def _scan(tmp_path: Path, **allow) -> list[check_secrets.Finding]:
    return check_secrets.scan(sorted(p for p in tmp_path.rglob("*") if p.is_file()), root=tmp_path, **allow)


def _mixed_key() -> bytes:
    """A fresh random key whose base64 forms mix digits, upper and lower case. Generated here, never committed."""
    while True:
        key = os.urandom(32)
        text = base64.urlsafe_b64encode(key).decode()
        if any(c.isdigit() for c in text) and any(c.isupper() for c in text) and any(c.islower() for c in text):
            return key


def test_planted_keys_are_flagged_and_never_printed(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    key = _mixed_key()
    forms = {"hex": key.hex(), "hex_upper": key.hex().upper(), "base64": base64.b64encode(key).decode(),
             "base64url": base64.urlsafe_b64encode(key).decode().rstrip("=")}
    for name, text in forms.items():
        (tmp_path / f"{name}.log").write_text(f"line one\nK_tag = {text}\n", encoding="ascii")
    findings = _scan(tmp_path)
    assert {f.path for f in findings} == {f"{name}.log" for name in forms}
    assert all(f.line == 2 for f in findings)
    assert check_secrets.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and out.count("KEY-LIKE") >= len(forms)
    assert not any(text.rstrip("=") in out for text in forms.values())
    logged = tmp_path / "scanner_output.txt"  # a logged FAIL report must not itself be a finding
    logged.write_text(out, encoding="utf-8")
    assert check_secrets.scan([logged], root=tmp_path) == []


def test_ordinary_text_is_not_flagged(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    (tmp_path / "notes.md").write_text(
        "commit 70c07edc0ffee70c07edc0ffee70c07edc0ffee1\n"  # 40 hex: a git sha, shorter than a key
        "def test_wrong_passphrase_fails_cleanly_and_leaks_nothing_at_all(): ...\n"
        "see src/vcloak/oracle/reference/and/some/very/long/path/without/any/digit\n"
        "runs/20261011-164329_M01_oracle_checks/pytest.txt\n", encoding="ascii")
    (tmp_path / "blob.bin").write_bytes(b"\0\1\2" + os.urandom(32).hex().encode())  # binary: not searched
    assert _scan(tmp_path) == [] and check_secrets.main([str(tmp_path)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_a_digest_of_a_scanned_file_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_text("some artefact\n", encoding="ascii")
    digest = hashlib.sha256((tmp_path / "data.txt").read_bytes()).hexdigest()
    (tmp_path / "sums.sha256").write_text(f"{digest} *data.txt\n", encoding="ascii")
    assert _scan(tmp_path) == []
    (tmp_path / "data.txt").write_text("changed\n", encoding="ascii")  # the digest no longer verifies
    assert [f.path for f in _scan(tmp_path)] == ["sums.sha256"]


def test_allow_list_by_token_and_by_file_hash(tmp_path: Path) -> None:
    path = tmp_path / "vectors.json"
    path.write_text(f'{{"block": "{os.urandom(32).hex()}"}}\n', encoding="ascii")
    (finding,) = _scan(tmp_path)
    assert finding.kind == "hex" and finding.length == 64
    assert _scan(tmp_path, allow_tokens={finding.token_id}) == []
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    assert _scan(tmp_path, allow_files={"vectors.json": file_hash}) == []
    path.write_text(f'{{"block": "{os.urandom(32).hex()}"}}\n', encoding="ascii")  # stale file hash: flagged again
    assert len(_scan(tmp_path, allow_files={"vectors.json": file_hash})) == 1


def test_repository_is_clean_and_secrets_dir_is_ignored() -> None:
    if not (REPO / ".git").exists():
        pytest.skip("not a git checkout (runner bundle)")
    assert "secrets/" in (REPO / ".gitignore").read_text(encoding="utf-8").split()
    assert check_secrets.tracked_secrets() == []
    assert check_secrets.main([]) == 0
