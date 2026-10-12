"""M09: SqliteRepo against the repository contract (A4), the compose file and the ENV.md section."""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

import pgdev
import record_env
from repo_contract import PAYLOAD, RepoContract, make_rows
from vcloak.storage import pgconf
from vcloak.storage.repo import PgRepo, SqliteRepo

ROOT = Path(__file__).resolve().parents[2]
ARRIVAL_TYPES = ("serial", "timestamp", "date", "time", "interval", "identity", "autoincrement", "sequence")


class TestSqliteRepo(RepoContract):
    @pytest.fixture
    def repo(self) -> Iterator[SqliteRepo]:
        r = SqliteRepo(dummy_payload_len=PAYLOAD)
        r.init_schema()
        yield r
        r.close()


def test_sqlite_schema_has_the_five_columns_and_no_arrival_column() -> None:
    r = SqliteRepo()
    r.init_schema()
    r.init_schema()  # idempotent
    cols = [(c[1], c[2].upper()) for c in r.execute("PRAGMA table_info(messages)")]
    assert cols == [("row_id", "BLOB"), ("bucket", "INTEGER"), ("win", "INTEGER"), ("seq_enc", "BLOB"),
                    ("payload", "BLOB")]
    ddl = " ".join(row[0].lower() for row in r.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
    assert not any(t in ddl for t in ARRIVAL_TYPES)


def test_sqlite_repo_persists_to_a_file(tmp_path: Path) -> None:
    path = str(tmp_path / "store.db")
    r = SqliteRepo(path)
    r.init_schema()
    r.insert_rows(make_rows(5, 1, 1))
    r.close()
    again = SqliteRepo(path)
    assert again.dump() == make_rows(5, 1, 1)
    again.close()


def test_schema_sql_declares_no_arrival_column() -> None:
    ddl = (ROOT / "src/vcloak/storage/schema.sql").read_text(encoding="utf-8")
    code = " ".join(line.split("--")[0] for line in ddl.splitlines()).lower()
    assert "partition by range (win)" in code
    assert not any(re.search(rf"\b{t}", code) for t in ARRIVAL_TYPES + ("now()", "nextval"))


def test_partition_names_and_schema_names_are_validated() -> None:
    assert PgRepo.partition_name(0) == "messages_w0" and PgRepo.partition_name(41) == "messages_w41"
    for bad in (-1, 2**31 - 1, True, "1", 1.0):
        with pytest.raises(ValueError):
            PgRepo.partition_name(bad)  # type: ignore[arg-type]
    for bad in ("Public", "a;b", "", 'x"y', "1abc"):
        with pytest.raises(ValueError):  # raised before any connection is opened
            PgRepo("host=invalid.invalid connect_timeout=1", schema=bad)


def test_default_dsn_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(pgconf.DSN_ENV, raising=False)
    assert f"port={pgconf.DEV_PORT}" in pgconf.default_dsn() and f"host={pgconf.DEV_HOST}" in pgconf.default_dsn()
    monkeypatch.setenv(pgconf.DSN_ENV, "host=db.example dbname=x")
    assert pgconf.default_dsn() == "host=db.example dbname=x"


def test_docker_compose_passes_the_same_settings_as_pgconf() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "image: postgres:16" in text
    passed = dict(re.findall(r'^\s*- "-c"\s*\n\s*- "([a-z_]+)=([^"]+)"', text, flags=re.M))
    assert passed == pgconf.HYGIENE
    assert f'"{pgconf.DEV_HOST}:{pgconf.DEV_PORT}:5432"' in text, "the port is published on the loopback only"
    assert f"POSTGRES_USER: {pgconf.DEV_USER}" in text and f"POSTGRES_DB: {pgconf.DEV_DB}" in text
    assert re.search(r"^volumes:\s*\n\s+vcloak_pgdata:", text, flags=re.M), "a named volume"


SETTINGS = {"server_version": "0-test", "dsn_host": "h", "dsn_port": 1, "window_s": 60, "all_ok": False,
            "settings": [{"setting": "log_statement", "required": "none", "show": "none", "ok": True},
                         {"setting": "wal_keep_size", "required": "0", "show": "1GB", "ok": False}]}


def test_the_storage_section_of_env_md_is_written_from_the_show_output(tmp_path: Path) -> None:
    import json

    src = tmp_path / "pg_settings.json"
    src.write_text(json.dumps(SETTINGS), encoding="utf-8")
    env = tmp_path / "ENV.md"
    env.write_text("# Environment\n\nkept\n", encoding="utf-8")
    assert pgdev.write_doc(str(src), env) == 0
    first = env.read_text(encoding="utf-8")
    assert first.startswith("# Environment\n\nkept\n\n" + pgdev.BEGIN)
    assert "| log_statement | none | none | PASS |" in first and "| wal_keep_size | 0 | 1GB | FAIL |" in first
    assert "retention must be shorter than the window" in first and "0-test" in first
    assert pgdev.write_doc(str(src), env) == 0
    assert env.read_text(encoding="utf-8") == first, "writing it again replaces the section"


def test_record_env_keeps_the_storage_section(tmp_path: Path) -> None:
    env = tmp_path / "ENV.md"
    sec = pgdev.section(SETTINGS, "runs/x/pg_settings.json")
    env.write_text("# Environment\n\nold\n\n" + sec + "\n", encoding="utf-8")
    assert record_env.keep_sections(env, "# Environment\n\nnew\n") == "# Environment\n\nnew\n\n" + sec + "\n"
    assert record_env.keep_sections(tmp_path / "missing.md", "# Environment\n") == "# Environment\n"
