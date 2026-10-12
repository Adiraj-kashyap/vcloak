#!/usr/bin/env python3
"""A private development PostgreSQL cluster from an installed PostgreSQL, for machines without Docker.

    python scripts/pgdev.py up        initdb once (.pgdev/data), write the settings, start, create the database
    python scripts/pgdev.py down      stop the cluster
    python scripts/pgdev.py status    is it running, and which server version answers
    python scripts/pgdev.py show --out runs/<dir>/pg_settings.json    SHOW every setting of pgconf.HYGIENE
    python scripts/pgdev.py doc runs/<dir>/pg_settings.json           write the storage section of docs/ENV.md

The cluster belongs to the current user, listens on 127.0.0.1 only and uses `trust` authentication:
it holds development and test data, never a key. It does not touch a PostgreSQL service installed on
the machine. The binaries come from VCLOAK_PG_BIN, PATH, or `C:\\Program Files\\PostgreSQL\\<n>\\bin`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import config  # noqa: E402
from vcloak.storage import pgconf  # noqa: E402

DATA = ROOT / ".pgdev" / "data"
LOG = ROOT / ".pgdev" / "server.log"
CONF = "vcloak.conf"
BEGIN, END = "<!-- BEGIN M09 STORAGE -->", "<!-- END M09 STORAGE -->"


def pg_bin() -> Path:
    exe = "pg_ctl.exe" if os.name == "nt" else "pg_ctl"
    cands = [Path(os.environ["VCLOAK_PG_BIN"])] if os.environ.get("VCLOAK_PG_BIN") else []
    found = shutil.which("pg_ctl")
    if found:
        cands.append(Path(found).parent)
    base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PostgreSQL"
    if base.is_dir():
        cands += sorted((d / "bin" for d in base.iterdir()), reverse=True)
    for c in cands:
        if (c / exe).is_file():
            return c
    raise SystemExit("no PostgreSQL binaries found: set VCLOAK_PG_BIN to the directory that holds pg_ctl")


def _run(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _admin_dsn() -> str:
    return (f"host={pgconf.DEV_HOST} port={pgconf.DEV_PORT} dbname=postgres user={pgconf.DEV_USER} "
            "connect_timeout=5")


def write_conf() -> None:
    lines = [f"listen_addresses = '{pgconf.DEV_HOST}'", f"port = {pgconf.DEV_PORT}", "logging_collector = off"]
    lines += [f"{k} = '{v}'" for k, v in pgconf.HYGIENE.items()]
    (DATA / CONF).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    main_conf = DATA / "postgresql.conf"
    include = f"include_if_exists = '{CONF}'"
    if include not in main_conf.read_text(encoding="utf-8"):
        with main_conf.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"\n{include}\n")


def running(bin_dir: Path) -> bool:
    return DATA.is_dir() and _run(str(bin_dir / "pg_ctl"), "-D", str(DATA), "status").returncode == 0


def up() -> int:
    import psycopg

    bin_dir = pg_bin()
    if not (DATA / "PG_VERSION").is_file():
        DATA.parent.mkdir(parents=True, exist_ok=True)
        r = _run(str(bin_dir / "initdb"), "-D", str(DATA), "-U", pgconf.DEV_USER, "-A", "trust", "-E", "UTF8",
                 "--locale=C")
        if r.returncode != 0:
            print(r.stdout[-2000:], r.stderr[-2000:])
            return r.returncode
    write_conf()
    if not running(bin_dir):
        # no captured pipes: the server inherits them on Windows and pg_ctl would never return
        rc = subprocess.run([str(bin_dir / "pg_ctl"), "-D", str(DATA), "-l", str(LOG), "-w", "start"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL).returncode
        if rc != 0:
            print(f"pg_ctl start failed ({rc}); see {LOG}")
            return rc
    with psycopg.connect(_admin_dsn(), autocommit=True) as c:
        if c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (pgconf.DEV_DB,)).fetchone() is None:
            c.execute(f'CREATE DATABASE "{pgconf.DEV_DB}"')
    return status()


def down() -> int:
    bin_dir = pg_bin()
    if not running(bin_dir):
        print("pgdev: not running")
        return 0
    return subprocess.run([str(bin_dir / "pg_ctl"), "-D", str(DATA), "-m", "fast", "-w", "stop"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def status() -> int:
    import psycopg

    try:
        with psycopg.connect(pgconf.default_dsn()) as c:
            one = c.execute("SELECT 1").fetchone()[0]
            print(f"pgdev: SELECT 1 -> {one}; server_version {c.execute('SHOW server_version').fetchone()[0]}; "
                  f"{pgconf.DEV_HOST}:{pgconf.DEV_PORT}/{pgconf.DEV_DB}")
        return 0
    except psycopg.OperationalError as e:
        print("pgdev: no connection:", str(e).strip().splitlines()[-1])
        return 1


def show(out: str | None) -> int:
    import psycopg

    with psycopg.connect(pgconf.default_dsn()) as c:
        got = {k: c.execute(f"SHOW {k}").fetchone()[0] for k in pgconf.HYGIENE}
        version = c.execute("SHOW server_version").fetchone()[0]
    rows = [{"setting": k, "required": v, "show": got[k], "ok": got[k] == v} for k, v in pgconf.HYGIENE.items()]
    doc = {"server_version": version, "dsn_host": pgconf.DEV_HOST, "dsn_port": pgconf.DEV_PORT,
           "window_s": config.WINDOW_S, "settings": rows, "all_ok": all(r["ok"] for r in rows)}
    if out:
        Path(out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    for r in rows:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['setting']} = {r['show']} (required {r['required']})")
    return 0 if doc["all_ok"] else 1


def section(doc: dict, source: str) -> str:
    rows = [f"| {r['setting']} | {r['required']} | {r['show']} | {'PASS' if r['ok'] else 'FAIL'} |"
            for r in doc["settings"]]
    return "\n".join([
        BEGIN,
        "## Storage: PostgreSQL WAL and logging (M09 S5)",
        "",
        f"Generated by `python scripts/pgdev.py doc {source}` from the `SHOW` output saved in that file "
        f"(server {doc['server_version']}) — do not edit by hand.",
        "",
        "| Setting | Required | SHOW | Check |", "|---|---|---|---|",
        *rows,
        "",
        "**Requirement (ADR-004): WAL retention must be shorter than the window W (`WINDOW_S` in "
        "`src/vcloak/config.py`).**",
        "A closed window is rewritten into a new partition under a fresh permutation and the old partition is",
        "dropped. The WAL still holds the inserts of that window in their epoch order, so a copy of the WAL that",
        "outlives the window undoes the re-shuffle. Therefore: no WAL archive, no replication slot or standby,",
        "`wal_keep_size` 0, and a checkpoint cycle (`checkpoint_timeout`, `max_wal_size`) shorter than W.",
        "The server log carries no statements, durations or connection events, and commit timestamps are off.",
        "",
        "Not established here: these settings bound which WAL files the server keeps. They do not overwrite the",
        "disk blocks of a removed WAL segment or of a dropped partition, so the requirement holds against a",
        "copy of the database files, not against forensic recovery of freed blocks. How long a WAL record",
        "actually survives has not been measured. A base backup or `pg_dump` taken while a window is open",
        "contains that window in its pre-shuffle order.",
        "",
        "Development database: `python scripts/pgdev.py up` (a private cluster from an installed PostgreSQL) or",
        "`docker compose up -d db`; both listen on the loopback port `DEV_PORT` of `src/vcloak/storage/pgconf.py`.",
        "Override with `VCLOAK_PG_DSN`.",
        END,
    ])


def write_doc(src: str, env_md: Path | None = None) -> int:
    env_md = env_md or ROOT / "docs" / "ENV.md"
    doc = json.loads(Path(src).read_text(encoding="utf-8"))
    text = env_md.read_text(encoding="utf-8") if env_md.is_file() else "# Environment\n"
    sec = section(doc, Path(src).as_posix())
    if BEGIN in text and END in text:
        text = text[:text.index(BEGIN)] + sec + text[text.index(END) + len(END):]
    else:
        text = text.rstrip("\n") + "\n\n" + sec + "\n"
    env_md.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote the storage section of {env_md}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("up", "down", "status"):
        sub.add_parser(name)
    sub.add_parser("show").add_argument("--out", default=None)
    sub.add_parser("doc").add_argument("settings_json")
    a = ap.parse_args(argv)
    if a.cmd == "show":
        return show(a.out)
    if a.cmd == "doc":
        return write_doc(a.settings_json)
    return {"up": up, "down": down, "status": status}[a.cmd]()


if __name__ == "__main__":
    sys.exit(main())
