"""M09: PgRepo against the repository contract (A4) and the PostgreSQL-only properties: the schema
(A1), the physical order after a rewrite (A3) and the WAL / logging settings (S5).

Needs a PostgreSQL: `python scripts/pgdev.py up` or `docker compose up -d db` (or VCLOAK_PG_DSN).
Each test works in a schema of its own, dropped afterwards.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from repo_contract import PAYLOAD, RepoContract, SeededEngine, make_rows
from vcloak.storage import pgconf
from vcloak.storage.repo import PgRepo, RewriteMismatch

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def dsn() -> str:
    try:
        with psycopg.connect(pgconf.default_dsn()) as c:
            assert c.execute("SELECT 1").fetchone() == (1,)  # the S1 check
    except psycopg.OperationalError as e:
        pytest.skip(f"no PostgreSQL at the configured DSN ({str(e).strip().splitlines()[-1]}): "
                    "run `python scripts/pgdev.py up`")
    return pgconf.default_dsn()


@pytest.fixture
def repo(dsn: str) -> Iterator[PgRepo]:
    schema = "t_" + uuid.uuid4().hex[:16]
    r = PgRepo(dsn, schema=schema, dummy_payload_len=PAYLOAD)
    r.init_schema()
    yield r
    r.execute(f"DROP SCHEMA {schema} CASCADE")
    r.close()


def schema_of(repo: PgRepo) -> str:
    return repo.execute("SELECT current_schema()")[0][0]


def tables(repo: PgRepo) -> list[str]:
    return sorted(t for (t,) in repo.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (schema_of(repo),)))


def physical(repo: PgRepo, win: int) -> list[tuple]:
    """(ctid block, ctid offset, xmin, row_id) of one partition, read from the partition itself."""
    return repo.execute(
        f"SELECT (t.ctid::text::point)[0]::int AS blk, (t.ctid::text::point)[1]::int AS off, t.xmin::text, t.row_id "
        f"FROM {PgRepo.partition_name(win)} t ORDER BY t.ctid")


class TestPgRepo(RepoContract):
    @pytest.fixture
    def repo(self, repo: PgRepo) -> PgRepo:  # the module fixture above
        return repo


# -- S2 / A1: the schema -----------------------------------------------------------------------------

def test_schema_has_the_five_columns_and_nothing_that_records_arrival(repo: PgRepo) -> None:
    repo.init_schema()  # idempotent
    repo.insert_rows(make_rows(5, 3, 1))
    s = schema_of(repo)
    cols = repo.execute(
        "SELECT table_name, column_name, data_type, is_nullable, column_default, is_identity, is_generated "
        "FROM information_schema.columns WHERE table_schema = %s ORDER BY table_name, ordinal_position", (s,))
    assert {c[0] for c in cols} == {"messages", "messages_w3", "pending_windows"}
    # the list of windows still to be re-shuffled (ADR-016): a window id and nothing else
    assert [c[:4] for c in cols if c[0] == "pending_windows"] == [("pending_windows", "win", "integer", "NO")]
    for table in ("messages", "messages_w3"):
        mine = [c[1:] for c in cols if c[0] == table]
        assert [(c[0], c[1], c[2]) for c in mine] == [
            ("row_id", "uuid", "NO"), ("bucket", "integer", "NO"), ("win", "integer", "NO"),
            ("seq_enc", "bytea", "NO"), ("payload", "bytea", "NO")]
        assert [c[3] for c in mine] == ["gen_random_uuid()", None, None, None, None]
        assert all(c[4] == "NO" and c[5] == "NEVER" for c in mine), "no identity or generated column"
    for c in cols:
        assert not any(t in c[2] for t in ("timestamp", "date", "time", "interval", "serial"))
        assert "nextval" not in (c[4] or "")
    assert repo.execute("SELECT count(*) FROM information_schema.sequences WHERE sequence_schema = %s", (s,)) == [(0,)]
    assert repo.execute("SELECT count(*) FROM information_schema.triggers WHERE trigger_schema = %s", (s,)) == [(0,)]


def test_messages_is_range_partitioned_by_win_with_the_bucket_index(repo: PgRepo) -> None:
    s = schema_of(repo)
    assert repo.execute(
        "SELECT pg_get_partkeydef(c.oid) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = 'messages'", (s,)) == [("RANGE (win)",)]
    idx = dict(repo.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = %s "
                            "AND tablename = 'messages'", (s,)))
    assert "(bucket, win)" in idx["messages_bucket_win_idx"]
    assert "UNIQUE" in idx["messages_pkey"] and "(row_id, win)" in idx["messages_pkey"]


def test_create_partition_makes_one_partition_per_window(repo: PgRepo) -> None:
    for win in (0, 5, 5, 6):
        repo.create_partition(win)
    PgRepo(pgconf.default_dsn(), schema=schema_of(repo)).create_partition(5)  # a second connection: still idempotent
    assert tables(repo) == ["messages", "messages_w0", "messages_w5", "messages_w6", "pending_windows"]
    bounds = repo.execute(
        "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) FROM pg_inherits i "
        "JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p ON p.oid = i.inhparent "
        "JOIN pg_namespace n ON n.oid = p.relnamespace WHERE n.nspname = %s AND p.relname = 'messages' "
        "ORDER BY 1", (schema_of(repo),))
    assert bounds == [("messages_w0", "FOR VALUES FROM (0) TO (1)"), ("messages_w5", "FOR VALUES FROM (5) TO (6)"),
                      ("messages_w6", "FOR VALUES FROM (6) TO (7)")]


def test_insert_rows_creates_the_partition_and_rolls_it_back_with_the_epoch(repo: PgRepo) -> None:
    repo.insert_rows(make_rows(4, 11, 1))
    assert tables(repo) == ["messages", "messages_w11", "pending_windows"]
    bad = make_rows(4, 12, 1)
    with pytest.raises(psycopg.errors.UniqueViolation):
        repo.insert_rows(bad + bad[:1])
    assert tables(repo) == ["messages", "messages_w11", "pending_windows"], (
        "the partition of a failed epoch is rolled back")
    repo.insert_rows(bad)
    assert tables(repo) == ["messages", "messages_w11", "messages_w12", "pending_windows"] and len(repo.dump()) == 8


# -- S4 / A3: the physical order -----------------------------------------------------------------------

def test_before_a_rewrite_the_heap_shows_the_epochs(repo: PgRepo) -> None:
    """Why the re-shuffle exists (ADR-004): the heap order and xmin of an open window give the epoch of a row."""
    epochs = [make_rows(30, 5, seed) for seed in range(3)]
    for rows in epochs:
        repo.insert_rows(rows)
    phys = physical(repo, 5)
    assert [p[3] for p in phys] == [r.row_id for rows in epochs for r in rows]
    xmins = [p[2] for p in phys]
    assert len(set(xmins)) == 3 and [xmins[0], xmins[30], xmins[60]] == sorted(set(xmins), key=int)


@pytest.mark.parametrize("n", [2, 90, 700])
def test_after_a_rewrite_the_physical_order_is_the_new_permutation(repo: PgRepo, n: int) -> None:
    rows = make_rows(n, 5, 1, payload=PAYLOAD if n < 700 else 3000)  # 3000 bytes: stored out of line (TOAST)
    for i in range(0, n, max(1, n // 3)):
        repo.insert_rows(rows[i:i + max(1, n // 3)])
    old_file = repo.execute("SELECT pg_relation_filenode(%s::regclass)", ("messages_w5",))
    new = rows[::-1] if n < 10 else SeededEngine(n).reshuffle_window(5, rows)
    assert new != rows
    repo.rewrite_window(5, new)

    phys = physical(repo, 5)
    assert [p[3] for p in phys] == [r.row_id for r in new], "ctid order = the order given (A3)"
    assert [(p[0], p[1]) for p in phys] == sorted((p[0], p[1]) for p in phys) and len(set(phys)) == n
    assert len({p[2] for p in phys}) == 1, "one transaction wrote the whole window: xmin no longer separates epochs"
    assert repo.dump() == new == repo.window_rows(5)
    assert repo.execute("SELECT pg_relation_filenode(%s::regclass)", ("messages_w5",)) != old_file
    assert tables(repo) == ["messages", "messages_w5", "pending_windows"], (
        "the old partition and the _new table are gone")


def test_a_rewritten_partition_is_attached_with_its_bound_and_indexes(repo: PgRepo) -> None:
    rows = make_rows(40, 5, 1)
    repo.insert_rows(rows)
    repo.rewrite_window(5, rows[::-1])
    s = schema_of(repo)
    assert repo.execute("SELECT pg_get_expr(c.relpartbound, c.oid) FROM pg_class c JOIN pg_namespace n "
                        "ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relname = 'messages_w5'",
                        (s,)) == [("FOR VALUES FROM (5) TO (6)",)]
    idx = sorted(d for (d,) in repo.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = 'messages_w5'", (s,)))
    assert len(idx) == 2 and "(bucket, win)" in idx[0] and "UNIQUE" in idx[1]
    assert repo.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'win_bound' AND connamespace = "
                        "%s::regnamespace", (s,)) == [(0,)]
    with pytest.raises(psycopg.errors.UniqueViolation):  # the primary key is back
        repo.insert_rows(rows[:1])
    repo.insert_rows(make_rows(3, 5, 2))  # a late insert lands in the new partition
    assert len(repo.window_rows(5)) == 43


def test_a_failed_or_interrupted_rewrite_leaves_the_window_as_it_was(repo: PgRepo) -> None:
    rows = make_rows(25, 5, 1)
    repo.insert_rows(rows)
    file_before = repo.execute("SELECT pg_relation_filenode(%s::regclass)", ("messages_w5",))
    with pytest.raises(RewriteMismatch):
        repo.rewrite_window(5, rows[:-1])
    assert tables(repo) == ["messages", "messages_w5", "pending_windows"] and repo.dump() == rows
    assert repo.execute("SELECT pg_relation_filenode(%s::regclass)", ("messages_w5",)) == file_before
    # a crash between the load and the swap leaves messages_w5_new behind: the next rewrite replaces it
    repo.execute("CREATE TABLE messages_w5_new (LIKE messages)")
    repo.execute("INSERT INTO messages_w5_new SELECT * FROM messages_w5 LIMIT 3")
    assert repo.dump() == rows, "a stray _new table is not part of the store"
    repo.rewrite_window(5, rows[::-1])
    assert tables(repo) == ["messages", "messages_w5", "pending_windows"] and repo.dump() == rows[::-1]


def test_another_connection_reads_the_complete_new_window_after_the_swap(repo: PgRepo, dsn: str) -> None:
    rows = make_rows(60, 5, 1)
    repo.insert_rows(rows)
    with psycopg.connect(dsn, autocommit=True) as reader:
        reader.execute(f"SET search_path TO {schema_of(repo)}")
        assert reader.execute("SELECT count(*) FROM messages WHERE win = 5").fetchone() == (60,)
        repo.rewrite_window(5, rows[::-1])
        got = [r[0] for r in reader.execute("SELECT row_id FROM messages WHERE win = 5 ORDER BY ctid").fetchall()]
    assert got == [r.row_id for r in rows[::-1]]


# -- S5: WAL and logging hygiene -----------------------------------------------------------------------

@pytest.mark.parametrize("setting", sorted(pgconf.HYGIENE))
def test_wal_and_logging_settings(repo: PgRepo, setting: str) -> None:
    assert repo.execute(f"SHOW {setting}") == [(pgconf.HYGIENE[setting],)]


def test_no_replication_slot_or_archive_keeps_wal(repo: PgRepo) -> None:
    assert repo.execute("SELECT count(*) FROM pg_replication_slots") == [(0,)]
    assert repo.execute("SHOW archive_command") in ([("(disabled)",)], [("",)])


# -- ISSUE-22: the pending mark and the swap are one transaction ----------------------------------------

def test_the_pending_mark_goes_with_the_swap_and_survives_a_new_connection(repo: PgRepo, dsn: str) -> None:
    rows = make_rows(30, 5, 1)
    repo.mark_pending(5)
    repo.insert_rows(rows)
    other = PgRepo(dsn, schema=schema_of(repo), dummy_payload_len=PAYLOAD)  # what a restarted service sees
    try:
        other.init_schema()
        assert other.pending_windows() == [5]
        with pytest.raises(RewriteMismatch):
            other.rewrite_window(5, rows[:-1])
        assert other.pending_windows() == [5], "a refused rewrite keeps the mark"
        other.rewrite_window(5, rows[::-1])
        assert other.pending_windows() == [] == repo.pending_windows()
        assert repo.dump() == rows[::-1]
    finally:
        other.close()
    assert physical(repo, 5) and len({x[2] for x in physical(repo, 5)}) == 1  # one transaction wrote the window
