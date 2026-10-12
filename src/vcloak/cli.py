"""The `vcloak` command.

    vcloak serve --mode vcloak|baseline --clock wall|sim [--visible-round window|epoch] [--dev] [--sessions]

`serve` starts the backend of docs/API.md. Without `--dev` the master key is unsealed from the key
file (`--key-file`, or VCLOAK_KEY_FILE, default secrets/k_master.sealed; create it with
`python scripts/vcloak_keys.py init`) with the passphrase in VCLOAK_PASSPHRASE or typed at a prompt.
`--dev` uses the fixed public development key: only for a throw-away database.

`--sessions` turns the session layer on (M11): accounts, DPoP-bound tokens, `/v1/ws`. Without it the API
takes a conversation token from any caller, so `serve` then refuses a `--host` that is not a loopback
address unless `--allow-remote` is given (ISSUE-22). The service speaks plain HTTP: on any other address
put TLS in front of it and name the public URL with `--public-origin`.
"""
from __future__ import annotations

import argparse
import ipaddress
import logging
import sys
from collections.abc import Sequence
from typing import Any

from vcloak import config
from vcloak.service import logsafe
from vcloak.service.app import ServiceBackend, VcloakBackend, create_app, dev_master, sealed_master
from vcloak.service.baseline import BaselineBackend, PgBaselineStore, SqliteBaselineStore
from vcloak.service.scheduler import EPOCH_ROUND_ORIGIN_MS, VISIBLE_ROUNDS, Clock, SimClock, WallClock
from vcloak.service.session import SessionConfig, SessionService, normalise_htu

MODES = ("vcloak", "baseline")
CLOCKS = ("wall", "sim")
STORES = ("pg", "sqlite")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vcloak", description="V-cloak service")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="run the backend service")
    s.add_argument("--mode", choices=MODES, default="vcloak", help="vcloak, or the unprotected baseline (M15)")
    s.add_argument("--clock", choices=CLOCKS, default="wall",
                   help="wall: epochs on wall-clock boundaries; sim: a virtual clock that runs as fast as possible")
    s.add_argument("--visible-round", choices=VISIBLE_ROUNDS, default="window",
                   help="epoch reproduces the Review-1 layout, for the M14 comparison only")
    s.add_argument("--dev", action="store_true", help="use the fixed public development key (no passphrase)")
    s.add_argument("--key-file", default=None, help="the sealed master key file")
    s.add_argument("--store", choices=STORES, default="pg", help="sqlite is an in-memory store for demos and tests")
    s.add_argument("--dsn", default=None, help="PostgreSQL DSN (default: VCLOAK_PG_DSN or the development database)")
    s.add_argument("--schema", default=None, help="PostgreSQL schema (default: public; baseline in baseline mode)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--allow-remote", action="store_true",
                   help="listen on a non-loopback --host although the API is open (no --sessions)")
    s.add_argument("--sessions", action="store_true",
                   help="require a session: accounts, DPoP-bound tokens, WebSocket tickets (state in memory)")
    s.add_argument("--public-origin", default=None,
                   help="with --sessions behind a proxy: the origin clients see, e.g. https://chat.example")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--slots", type=int, default=config.SLOTS)
    s.add_argument("--buckets", type=int, default=config.BUCKETS)
    s.add_argument("--window-s", type=int, default=config.WINDOW_S)
    s.add_argument("--epoch-ms", type=int, default=config.EPOCH_MS)
    s.add_argument("--cand-k", type=int, default=config.CAND_K)
    return ap


def build_backend(a: argparse.Namespace) -> ServiceBackend:
    """The backend `serve` runs, from parsed arguments. Nothing is opened on the device before startup."""
    clock: Clock = WallClock() if a.clock == "wall" else SimClock()
    if a.mode == "baseline":
        store: Any = (SqliteBaselineStore() if a.store == "sqlite"
                      else PgBaselineStore(a.dsn, **({"schema": a.schema} if a.schema else {})))
        return BaselineBackend(store, clock, window_s=a.window_s, epoch_ms=a.epoch_ms)
    from vcloak.storage.repo import PgRepo, SqliteRepo

    repo: Any = SqliteRepo() if a.store == "sqlite" else PgRepo(a.dsn, schema=a.schema or "public")
    origin = EPOCH_ROUND_ORIGIN_MS // a.epoch_ms if (a.clock, a.visible_round) == ("wall", "epoch") else 0
    return VcloakBackend(repo, clock, dev_master if a.dev else sealed_master(a.key_file), slots=a.slots,
                         buckets=a.buckets, window_s=a.window_s, epoch_ms=a.epoch_ms, cand_k=a.cand_k,
                         visible_round=a.visible_round, epoch_origin=origin)


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def build_sessions(a: argparse.Namespace) -> SessionService | None:
    """The session layer of `--sessions`, or None for the open API."""
    if not a.sessions:
        return None
    return SessionService(SessionConfig(public_origin=a.public_origin))


def serve(a: argparse.Namespace) -> int:
    logsafe.configure()
    log = logsafe.get_logger("cli")
    if a.public_origin is not None and (not a.sessions or normalise_htu(a.public_origin) is None):
        print("vcloak serve: --public-origin needs --sessions and an http(s) origin", file=sys.stderr)
        return 2
    if not a.sessions and not is_loopback(a.host):
        if not a.allow_remote:
            log.event("remote_host_refused", level=logging.ERROR, error="no_authentication")
            print("vcloak serve: without --sessions the API has no authentication; --host must be a loopback "
                  "address (or pass --allow-remote)", file=sys.stderr)
            return 2
        log.warning("remote_host_without_authentication")
    import uvicorn

    if a.dev and a.mode == "vcloak":
        log.warning("dev_key_in_use", dev_key=True)
    log.event("serve", mode=a.mode, clock=a.clock, visible_round=a.visible_round, store=a.store, port=a.port,
              sessions=bool(a.sessions))
    # no access log and no connection lines: a line per request or per socket is an arrival record
    uvicorn.run(create_app(build_backend(a), sessions=build_sessions(a)), host=a.host, port=a.port,
                access_log=False, log_config=logsafe.server_log_config(uvicorn.config.LOGGING_CONFIG))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.command == "serve":
        return serve(a)
    return 2


if __name__ == "__main__":
    sys.exit(main())
