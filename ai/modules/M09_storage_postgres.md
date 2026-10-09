# M09 — Storage: PostgreSQL schema, repository, window re-shuffle
owner: Divyansh · depends_on: M06 · est_sessions: 1–2 · human_gates: Docker Desktop or a native PostgreSQL 16 install

## Goal
A store that carries no arrival information, partitions by window, and rewrites closed windows atomically.

## Required reading
- `ai/ARCHITECTURE.md §4 (Repo)` · `ai/DECISIONS.md ADR-004, ADR-008` · `ai/PROJECT_BRIEF.md §5`

## Deliverables
`docker-compose.yml` (postgres:16, a named volume, `wal_keep_size` small, log settings), `src/vcloak/storage/schema.sql`,
`src/vcloak/storage/repo.py` (`PgRepo`, `SqliteRepo`), `src/vcloak/storage/reshuffle.py`,
`tests/integration/test_repo_pg.py`, `tests/unit/test_repo_sqlite.py`.

## Steps
- **S1 Database up.** Try `docker compose up -d db`; else detect a native install via `psql --version`. If neither exists:
  HUMAN ACTION with the Docker Desktop / native install steps. Check: `SELECT 1` via psycopg.
- **S2 Schema.** `messages(row_id uuid primary key default gen_random_uuid(), bucket int not null, win int not null,
  seq_enc bytea not null, payload bytea not null) PARTITION BY RANGE (win)`; index `(bucket, win)`; a helper that
  creates the partition for a window. No serial, no timestamp columns (a test asserts this from information_schema).
- **S3 Repo.** `insert_rows` (COPY or executemany within one transaction per epoch); `fetch_candidates(bucket, win, K)`
  returns exactly K rows, padded with dummy rows (random uuid, random 44-byte seq_enc, random payload of the same size) in
  random order; `dump()` returns rows in physical order (`ORDER BY ctid`) for the attack harness.
- **S4 Window rewrite.** `rewrite_window(win, rows)`: create `messages_w<win>_new`, insert in the given order,
  then in one transaction detach and drop the old partition and attach the new one. Check: row count is preserved and
  `dump()` order equals the given order.
- **S5 WAL and logging hygiene.** Configure `log_statement=none`, and in dev set `wal_keep_size`/`max_wal_size` small;
  document the retention < W requirement in `docs/ENV.md`. Check: the settings are verified via `SHOW`.

## Audit checklist
- A1 The schema has no serial/timestamp columns (test). A2 fetch_candidates always returns exactly K rows.
- A3 After a rewrite, physical order = the new permutation (test uses `ctid`). A4 SQLite and Pg pass the same repo tests.
- G1–G10.

## Presenter notes
1. Why is in-place UPDATE not enough to hide order in PostgreSQL? (MVCC)
2. What exactly does a pg_dump of your table reveal?
3. How is K chosen and what happens when a bucket-window exceeds it?

## Next: M10
