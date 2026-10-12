"""M10: the service on PostgreSQL, in both modes (A3): the same contract as tests/unit/test_service_sqlite.py,
plus what only PostgreSQL shows (partitions after the window close, the baseline schema, the physical order).

Needs a PostgreSQL: `docker compose up -d --wait db` (or `python scripts/pgdev.py up`, or VCLOAK_PG_DSN).
Each test works in a schema of its own, dropped afterwards.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator

import httpx
import pytest

from service_contract import (
    BaselineService,
    Harness,
    VcloakService,
    baseline_harness,
    index_of,
    send_across_windows,
    vcloak_harness,
)
from vcloak.service import baseline
from vcloak.service.baseline import PgBaselineStore
from vcloak.storage import pgconf
from vcloak.storage.repo import PgRepo

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def dsn() -> str:
    try:
        with psycopg.connect(pgconf.default_dsn()) as c:
            assert c.execute("SELECT 1").fetchone() == (1,)
    except psycopg.OperationalError as e:
        pytest.skip(f"no PostgreSQL at the configured DSN ({str(e).strip().splitlines()[-1]}): "
                    "run `docker compose up -d --wait db`")
    return pgconf.default_dsn()


class TestVcloakPg(VcloakService):
    @pytest.fixture
    def harness(self, dsn: str) -> Iterator[Harness]:
        schema = "s_" + uuid.uuid4().hex[:16]
        repo = PgRepo(dsn, schema=schema)
        yield vcloak_harness(repo)
        repo.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        repo.close()

    def test_closed_windows_are_fresh_partitions_without_arrival_columns(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            await send_across_windows(harness, client)

        harness.serve(scenario)
        repo: PgRepo = harness.store
        schema = repo.execute("SELECT current_schema()")[0][0]
        tables = sorted(t for (t,) in repo.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (schema,)))
        assert tables == ["messages", "messages_w0", "messages_w1", "messages_w2", "pending_windows"]
        assert repo.pending_windows() == []  # every window that holds rows has been re-shuffled
        columns = {c for (c,) in repo.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s", (schema,))}
        assert columns == {"row_id", "bucket", "win", "seq_enc", "payload"}
        assert repo.execute("SELECT count(*) FROM information_schema.sequences WHERE sequence_schema = %s",
                            (schema,)) == [(0,)]
        for win in range(3):  # each closed partition was written by one transaction: the rewrite
            xmins = repo.execute(f"SELECT count(DISTINCT xmin::text) FROM {PgRepo.partition_name(win)}")
            assert xmins == [(1,)]


class TestBaselinePg(BaselineService):
    @pytest.fixture
    def harness(self, dsn: str) -> Iterator[Harness]:
        schema = "b_" + uuid.uuid4().hex[:16]
        store = PgBaselineStore(dsn, schema=schema)
        yield baseline_harness(store)
        store.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        store.close()

    def test_baseline_table_has_a_serial_id_and_a_timestamp(self, harness: Harness) -> None:
        async def scenario(client: httpx.AsyncClient) -> None:
            await send_across_windows(harness, client, n=30)

        harness.serve(scenario)
        store: PgBaselineStore = harness.store
        schema = store.execute("SELECT current_schema()")[0][0]
        cols = dict(store.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = %s", (schema,)))
        assert cols == {"id": "bigint", "ts": "timestamp with time zone", "conv": "bytea", "win": "integer",
                        "payload": "bytea"}
        rows = store.execute("SELECT id, ts, payload FROM messages ORDER BY ctid")
        assert [i for i, _, _ in rows] == list(range(1, 31))
        assert [index_of(bytes(p)) for _, _, p in rows] == list(range(30))  # physical order = arrival order
        assert [t for _, t, _ in rows] == sorted(t for _, t, _ in rows)


def test_default_baseline_schema_is_separate() -> None:
    assert baseline.SCHEMA == "baseline" != "public"


def test_issue21_a_second_connection_reads_whole_windows_while_they_are_reshuffled(dsn: str) -> None:
    """The service serialises reads and re-shuffles on one connection. This is the case it does not
    create itself: another connection reading a closed window while the partition is swapped."""
    import threading

    from repo_contract import PAYLOAD, SeededEngine, make_rows
    from vcloak.storage.reshuffle import reshuffle_window

    schema = "c_" + uuid.uuid4().hex[:16]
    writer = PgRepo(dsn, schema=schema, dummy_payload_len=PAYLOAD)
    writer.init_schema()
    reader = PgRepo(dsn, schema=schema, dummy_payload_len=PAYLOAD)
    try:
        rows = make_rows(240, win=0, seed=5, buckets=4)
        writer.insert_rows(rows)
        ids = {r.row_id for r in rows}
        seen: list[int] = []
        errors: list[str] = []
        stop = threading.Event()

        def read_loop() -> None:
            while not stop.is_set():
                try:
                    got = [r for b in range(4) for r in reader.fetch_candidates(b, 0, 128) if r.row_id in ids]
                    seen.append(len(got))
                except Exception as e:  # noqa: BLE001 - recorded and asserted below
                    errors.append(type(e).__name__)

        t = threading.Thread(target=read_loop)
        t.start()
        try:
            for seed in range(25):
                assert reshuffle_window(writer, SeededEngine(seed), 0) == 240
        finally:
            stop.set()
            t.join(timeout=30)
        assert not t.is_alive() and len(seen) + len(errors) > 0
        assert errors == [], sorted(set(errors))  # a reader never fails on a partition that is being replaced
        assert set(seen) == {240}  # and never sees a partial window
    finally:
        reader.close()
        writer.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        writer.close()
