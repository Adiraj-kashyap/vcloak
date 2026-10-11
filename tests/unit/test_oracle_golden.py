"""M01 S5: the committed golden permutation vectors are deterministic and self-consistent."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import make_golden
from testkeys import TEST_K_MASTER
from vcloak.oracle import crypto_hooks

GOLDEN = Path(__file__).resolve().parents[1] / "golden"


@pytest.mark.parametrize("n", make_golden.SIZES)
def test_golden_file_is_reproduced_byte_for_byte(n: int) -> None:
    assert (GOLDEN / make_golden.file_name(n)).read_bytes() == make_golden.build(n)


@pytest.mark.parametrize("n", make_golden.SIZES)
def test_golden_vectors_are_valid_permutations(n: int) -> None:
    doc = json.loads((GOLDEN / make_golden.file_name(n)).read_text(encoding="ascii"))
    assert doc["n"] == n and "vcloak.oracle.reference" in doc["source"]
    assert [v["number"] for v in doc["vectors"]] == list(make_golden.NUMBERS)
    seen = set()
    for v in doc["vectors"]:
        for kind in ("epoch", "reshuffle"):
            raw = base64.b64decode(v[kind]["perm_b64"])
            assert hashlib.sha256(raw).hexdigest() == v[kind]["perm_sha256"]
            perm = np.frombuffer(raw, dtype="<u4")
            assert np.array_equal(np.sort(perm), np.arange(n))
            seen.add(v[kind]["perm_sha256"])
    assert len(seen) == 2 * len(make_golden.NUMBERS)


def test_golden_files_do_not_contain_key_material() -> None:
    keys = (TEST_K_MASTER, *crypto_hooks.derive_subkeys(TEST_K_MASTER))
    for n in make_golden.SIZES:
        text = (GOLDEN / make_golden.file_name(n)).read_text(encoding="ascii")
        for key in keys:
            assert key.hex() not in text and base64.b64encode(key).decode() not in text


def test_check_mode_detects_a_difference(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert make_golden.main(["--quick", "--out", str(tmp_path)]) == 0
    assert make_golden.main(["--quick", "--check", "--out", str(tmp_path)]) == 0
    first = tmp_path / make_golden.file_name(64)
    first.write_bytes(first.read_bytes().replace(b'"n": 64', b'"n": 65'))
    assert make_golden.main(["--quick", "--check", "--out", str(tmp_path)]) == 1
    assert "DIFFERS" in capsys.readouterr().out
