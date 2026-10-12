"""The development PostgreSQL endpoint and the WAL / logging settings M09 S5 requires.

`HYGIENE` is the one list of settings: `scripts/pgdev.py` writes it into the private cluster, the
integration test compares it with `SHOW`, and `docker-compose.yml` passes the same values (a unit test
keeps the two in step). Values are spelled the way `SHOW` prints them.
"""
from __future__ import annotations

import os

DEV_HOST = "127.0.0.1"
DEV_PORT = 54329
DEV_USER = "vcloak"
DEV_DB = "vcloak"
DSN_ENV = "VCLOAK_PG_DSN"

HYGIENE: dict[str, str] = {
    # nothing about a statement, its duration or its session reaches the server log
    "log_statement": "none",
    "log_min_duration_statement": "-1",
    "log_duration": "off",
    "log_connections": "off",
    "log_disconnections": "off",
    # commit timestamps would be an arrival time per transaction
    "track_commit_timestamp": "off",
    # WAL: no archive, no standby, nothing kept beyond the checkpoint cycle (ADR-004: retention < W)
    "wal_level": "minimal",
    "max_wal_senders": "0",
    "archive_mode": "off",
    "wal_keep_size": "0",
    "min_wal_size": "32MB",
    "max_wal_size": "32MB",
    "checkpoint_timeout": "30s",
    "wal_recycle": "off",
}


def default_dsn() -> str:
    """The DSN in VCLOAK_PG_DSN, or the private development cluster of scripts/pgdev.py."""
    return os.environ.get(DSN_ENV) or (
        f"host={DEV_HOST} port={DEV_PORT} dbname={DEV_DB} user={DEV_USER} connect_timeout=5")
