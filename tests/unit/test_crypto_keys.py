"""M02 S4: the sealed master key file and the key CLI (ADR-007)."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

import vcloak_keys
from testkeys import TEST_K_MASTER
from vcloak.crypto import keys

FAST = keys.Argon2Params(t=1, m_kib=64, p=1)  # tests only; the default is checked below


def test_default_argon2id_parameters() -> None:
    assert keys.DEFAULT_PARAMS == keys.Argon2Params(t=3, m_kib=64 * 1024, p=4)


def test_file_format_and_default_round_trip(tmp_path: Path) -> None:
    path = keys.create_sealed_master(tmp_path / "secrets" / "k_master.sealed", "correct horse")
    blob = path.read_bytes()
    assert len(blob) == keys.SEALED_LEN == 96 and blob[:8] == keys.MAGIC
    assert struct.unpack_from("<III", blob, 8) == (3, 64 * 1024, 4)
    master = keys.unseal_master(path, "correct horse")
    assert isinstance(master, bytearray) and len(master) == 32 and any(master)
    for i in range(0, 32 - 7):  # no 8-byte window of the plaintext key is in the file
        assert bytes(master[i:i + 8]) not in blob
    keys.zeroize(master)
    assert master == bytearray(32)


def test_seal_is_randomised_and_hides_the_key() -> None:
    a, b = keys.seal_master(TEST_K_MASTER, "pw", FAST), keys.seal_master(TEST_K_MASTER, "pw", FAST)
    assert a != b and a[20:36] != b[20:36] and a[36:48] != b[36:48]  # fresh salt and nonce
    assert TEST_K_MASTER not in a and TEST_K_MASTER[:8] not in a
    assert keys.unseal_blob(a, "pw") == keys.unseal_blob(b, b"pw") == bytearray(TEST_K_MASTER)


def test_wrong_passphrase_fails_cleanly() -> None:
    blob = keys.seal_master(TEST_K_MASTER, "right", FAST)
    with pytest.raises(keys.UnsealError) as e:
        keys.unseal_blob(blob, "wrong")
    assert "wrong passphrase" in str(e.value) and e.value.__cause__ is None and e.value.__suppress_context__
    assert TEST_K_MASTER.hex() not in repr(e.value)


def test_every_byte_of_the_file_is_authenticated() -> None:
    blob = keys.seal_master(TEST_K_MASTER, "pw", FAST)
    for i in range(len(blob)):
        bad = bytearray(blob)
        bad[i] ^= 1
        with pytest.raises(keys.UnsealError):
            keys.unseal_blob(bytes(bad), "pw")


def test_malformed_files_and_inputs() -> None:
    blob = keys.seal_master(TEST_K_MASTER, "pw", FAST)
    for bad in (b"", blob[:-1], blob + b"\0", b"NOTMAGIC" + blob[8:]):
        with pytest.raises(keys.UnsealError):
            keys.unseal_blob(bad, "pw")
    huge = blob[:8] + struct.pack("<III", 1, 1 << 31, 1) + blob[20:]  # a file may not demand 2 TiB of memory
    with pytest.raises(keys.UnsealError):
        keys.unseal_blob(huge, "pw")
    with pytest.raises(ValueError):
        keys.seal_master(TEST_K_MASTER, "", FAST)
    with pytest.raises(ValueError):
        keys.seal_master(TEST_K_MASTER[:16], "pw", FAST)


def test_create_refuses_to_overwrite(tmp_path: Path) -> None:
    path = keys.create_sealed_master(tmp_path / "k.sealed", "pw", params=FAST)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        keys.create_sealed_master(path, "pw", params=FAST)
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]  # no temp file left behind


def test_reseal_keeps_the_key_and_changes_the_passphrase(tmp_path: Path) -> None:
    path = keys.create_sealed_master(tmp_path / "k.sealed", "old", params=FAST)
    before, master = path.read_bytes(), keys.unseal_master(path, "old")
    keys.reseal_master(path, "old", "new", params=FAST)
    assert path.read_bytes()[20:] != before[20:] and keys.unseal_master(path, "new") == master
    with pytest.raises(keys.UnsealError):
        keys.unseal_master(path, "old")
    with pytest.raises(keys.UnsealError):
        keys.reseal_master(path, "old", "newer", params=FAST)
    assert keys.unseal_master(path, "new") == master


def test_cli_init_and_rotate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(keys.create_sealed_master, "__kwdefaults__", {"params": FAST, "overwrite": False})
    monkeypatch.setattr(keys.reseal_master, "__kwdefaults__", {"params": FAST})
    path = tmp_path / "secrets" / "k_master.sealed"
    args = ["--path", str(path)]

    def asker(*answers: str):
        it = iter(answers)
        return lambda prompt: next(it)

    assert vcloak_keys.main(["init", *args], ask=asker("pw-alpha-1", "pw-alpha-1")) == 0
    master = keys.unseal_master(path, "pw-alpha-1")
    assert vcloak_keys.main(["init", *args], ask=asker("x", "x")) == 1  # never overwrites a master key
    with pytest.raises(SystemExit):
        vcloak_keys.main(["init", "--path", str(tmp_path / "other")], ask=asker("a", "b"))
    assert not (tmp_path / "other").exists()
    assert vcloak_keys.main(["rotate", *args], ask=asker("nope", "pw-beta-2", "pw-beta-2")) == 1
    assert keys.unseal_master(path, "pw-alpha-1") == master
    assert vcloak_keys.main(["rotate", *args], ask=asker("pw-alpha-1", "pw-beta-2", "pw-beta-2")) == 0
    assert keys.unseal_master(path, "pw-beta-2") == master
    assert vcloak_keys.main(["rotate", "--path", str(tmp_path / "missing")], ask=asker("a")) == 1
    out = capsys.readouterr()
    for text in (out.out, out.err):
        assert master.hex() not in text and "pw-alpha-1" not in text and "pw-beta-2" not in text
