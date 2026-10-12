"""M10: the service contract on SQLite stores, in both modes (A3), plus the CLI wiring and the key providers."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from service_contract import (
    BaselineService,
    Harness,
    VcloakService,
    baseline_harness,
    fixed_master,
    token,
    vcloak_harness,
)
from testkeys import TEST_K_MASTER
from vcloak import cli
from vcloak.crypto import keys as keyfile
from vcloak.crypto.client import PAYLOAD_LEN
from vcloak.service import app as service_app
from vcloak.service.baseline import BaselineBackend, SqliteBaselineStore
from vcloak.service.models import PayloadError, conv_id_of, decode_payload, encode_payload
from vcloak.service.scheduler import EPOCH_ROUND_ORIGIN_MS, SimClock, WallClock
from vcloak.storage.repo import SqliteRepo

CHEAP = keyfile.Argon2Params(t=1, m_kib=64, p=1)  # test files only: fast to unseal


class TestVcloakSqlite(VcloakService):
    @pytest.fixture
    def harness(self) -> Harness:
        return vcloak_harness(SqliteRepo())


class TestBaselineSqlite(BaselineService):
    @pytest.fixture
    def harness(self) -> Harness:
        return baseline_harness(SqliteBaselineStore())


# ── models ───────────────────────────────────────────────────────────────────

def test_conv_id_is_a_stable_64_bit_hash_of_the_token() -> None:
    a, b = conv_id_of(token("a")), conv_id_of(token("b"))
    assert a == conv_id_of(token("a")) and a != b
    assert 0 <= a < 2**64 and 0 <= b < 2**64


def test_decode_payload_is_strict() -> None:
    raw = os.urandom(PAYLOAD_LEN)
    assert decode_payload(encode_payload(raw)) == raw
    for bad in ("", "AAAA", encode_payload(raw)[:-4], encode_payload(raw) + "AAAA", encode_payload(raw)[:-1] + "\n"):
        with pytest.raises(PayloadError):
            decode_payload(bad)


# ── key providers (S5) ───────────────────────────────────────────────────────

def _sealed(tmp_path: Path, passphrase: str) -> Path:
    path = tmp_path / "k_master.sealed"
    path.write_bytes(keyfile.seal_master(bytearray(TEST_K_MASTER), passphrase, CHEAP))
    return path


def test_sealed_master_takes_the_passphrase_from_the_environment_once(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _sealed(tmp_path, "correct horse")
    monkeypatch.setenv(service_app.PASSPHRASE_ENV, "correct horse")

    def no_prompt(_: str) -> str:
        raise AssertionError("the prompt must not be used when the variable is set")

    master = service_app.sealed_master(path, prompt=no_prompt)()
    assert isinstance(master, bytearray) and bytes(master) == TEST_K_MASTER
    assert service_app.PASSPHRASE_ENV not in os.environ  # removed once read


def test_sealed_master_prompts_without_the_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _sealed(tmp_path, "typed")
    monkeypatch.delenv(service_app.PASSPHRASE_ENV, raising=False)
    monkeypatch.setenv(service_app.KEY_FILE_ENV, str(path))
    asked: list[str] = []

    def prompt(text: str) -> str:
        asked.append(text)
        return "typed"

    assert bytes(service_app.sealed_master(prompt=prompt)()) == TEST_K_MASTER
    assert len(asked) == 1


def test_service_starts_from_a_sealed_key_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(service_app.PASSPHRASE_ENV, "pw")
    h = vcloak_harness(SqliteRepo())
    h.backend._key_provider = service_app.sealed_master(_sealed(tmp_path, "pw"))

    async def scenario(client: object) -> None:
        assert h.backend.ready

    h.serve(scenario)
    assert h.backend.ready is False


def test_wrong_passphrase_stops_the_startup_without_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(service_app.PASSPHRASE_ENV, "tulip-9")
    h = vcloak_harness(SqliteRepo())
    h.backend._key_provider = service_app.sealed_master(_sealed(tmp_path, "orchid-4"))

    async def scenario(client: object) -> None:
        raise AssertionError("the service must not start")

    with pytest.raises(keyfile.UnsealError) as err:
        h.serve(scenario)
    assert "tulip-9" not in str(err.value) and "orchid-4" not in str(err.value)
    assert h.backend.ready is False and h.backend.keys is not None and not h.backend.keys.ready


def test_dev_master_is_the_public_test_key() -> None:
    assert bytes(service_app.dev_master()) == TEST_K_MASTER == bytes(fixed_master())
    assert service_app.dev_master() is not service_app.dev_master()


# ── CLI ──────────────────────────────────────────────────────────────────────

def _args(*argv: str):
    return cli.build_parser().parse_args(["serve", "--store", "sqlite", *argv])


def test_cli_defaults() -> None:
    a = _args()
    assert (a.mode, a.clock, a.visible_round, a.dev) == ("vcloak", "wall", "window", False)


@pytest.mark.parametrize("bad", [["--mode", "fast"], ["--clock", "utc"], ["--visible-round", "minute"]])
def test_cli_rejects_unknown_choices(bad: list[str]) -> None:
    with pytest.raises(SystemExit):
        _args(*bad)


def test_cli_builds_the_vcloak_backend() -> None:
    b = cli.build_backend(_args("--dev", "--clock", "sim", "--slots", "128", "--window-s", "10"))
    assert isinstance(b, service_app.VcloakBackend)
    assert (b.mode, b.visible_round, b.slots, b.window_s, b._origin) == ("vcloak", "window", 128, 10, 0)
    assert isinstance(b._clock, SimClock) and b._key_provider is service_app.dev_master
    assert b.ready is False  # nothing is loaded before startup


def test_cli_epoch_rounds_on_the_wall_clock_count_from_the_public_origin() -> None:
    b = cli.build_backend(_args("--dev", "--visible-round", "epoch"))
    assert isinstance(b._clock, WallClock) and b.visible_round == "epoch"
    assert b._origin == EPOCH_ROUND_ORIGIN_MS // 200
    h = Harness(b, SimClock(), b.repo)

    async def scenario(client: object) -> None:
        assert 0 < b.current_window() < 2**31 - 1  # epochs since the origin fit the store's int4

    h.serve(scenario)


def test_cli_builds_the_baseline_backend() -> None:
    b = cli.build_backend(_args("--mode", "baseline"))
    assert isinstance(b, BaselineBackend) and b.mode == "baseline"


def test_cli_without_dev_uses_the_sealed_key_file(tmp_path: Path) -> None:
    b = cli.build_backend(_args("--key-file", str(tmp_path / "missing.sealed")))
    assert b._key_provider is not service_app.dev_master


# ── ISSUE-22: no authentication yet, so loopback only ────────────────────────

@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.9"])
def test_loopback_hosts(host: str) -> None:
    assert cli.is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "example.org", ""])
def test_serve_refuses_a_host_that_is_not_loopback(host: str, monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    import uvicorn

    def never(*a: object, **kw: object) -> None:
        raise AssertionError("the server must not start")

    monkeypatch.setattr(uvicorn, "run", never)
    assert not cli.is_loopback(host)
    assert cli.main(["serve", "--dev", "--store", "sqlite", "--host", host]) == 2
    assert "--allow-remote" in capsys.readouterr().err


def test_serve_listens_remotely_only_when_told_to(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    started: list[str] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, host, **kw: started.append(host))
    assert cli.main(["serve", "--dev", "--store", "sqlite", "--host", "0.0.0.0", "--allow-remote"]) == 0
    assert cli.main(["serve", "--dev", "--store", "sqlite"]) == 0
    assert started == ["0.0.0.0", "127.0.0.1"]
