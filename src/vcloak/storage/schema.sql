-- V-cloak storage schema (M09 S2). Applied by PgRepo.init_schema() inside the repository's schema.
--
-- The table carries no arrival information: no serial or identity column, no sequence, no timestamp.
-- row_id is random (the engine draws it; the default is for manual inserts only).
-- PostgreSQL requires the partition key in every unique constraint of a partitioned table, so the
-- primary key is (row_id, win) rather than row_id alone (ADR-014).

CREATE TABLE IF NOT EXISTS messages (
    row_id  uuid  NOT NULL DEFAULT gen_random_uuid(),
    bucket  int   NOT NULL,
    win     int   NOT NULL,
    seq_enc bytea NOT NULL,
    payload bytea NOT NULL,
    PRIMARY KEY (row_id, win)
) PARTITION BY RANGE (win);

CREATE INDEX IF NOT EXISTS messages_bucket_win_idx ON messages (bucket, win);

-- The windows that hold rows in the layout they were written in and are still to be re-shuffled
-- (ISSUE-22, ADR-016). A window is listed before its first rows are stored, and taken off the list by
-- the transaction that swaps in its re-shuffled partition. The list is public: the same fact shows in
-- the physical layout of the partition. It carries a window id and nothing else.
CREATE TABLE IF NOT EXISTS pending_windows (
    win int PRIMARY KEY
);
