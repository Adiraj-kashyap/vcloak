#!/usr/bin/env python3
"""The full stack on the GPU runner (Colab/Kaggle): the Python packages of the service, and a PostgreSQL
server with the settings of `pgconf.HYGIENE` on the development endpoint (127.0.0.1:54329, user and
database `vcloak`, `trust` authentication on loopback).

    python scripts/runner_stack.py up        install what is missing, initdb, start, create the database
    python scripts/runner_stack.py status    the server version and every setting of pgconf.HYGIENE
    python scripts/runner_stack.py down      stop the server

It installs system packages with apt-get, so it runs only where VCLOAK_RUNNER is `colab` or `kaggle`
(`gpu_entry.py` sets it), or with `--force`. Never on the laptop: use `docker compose` or `scripts/pgdev.py`.
apt-get and pip need the internet (on by default in Colab; in Kaggle: Settings > Internet).

The cluster is a private one under /tmp: the `main` cluster the Debian package creates is left alone.
It holds evaluation data under the public development key, never a secret. The runner is root, and
PostgreSQL refuses to run as root, so initdb and pg_ctl run as the `postgres` user of the package.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak.storage import pgconf  # noqa: E402

BASE = Path("/tmp/vcloak_pg")
DATA, LOG = BASE / "data", BASE / "server.log"
PG_USER = "postgres"
RUNNERS = ("colab", "kaggle")
# pip name -> import name: what the service, the evaluation and the test suite import beyond the runner's defaults
PACKAGES = {"psycopg[binary]": "psycopg", "fastapi": "fastapi", "uvicorn": "uvicorn", "httpx": "httpx",
            "websockets": "websockets", "argon2-cffi": "argon2", "cryptography": "cryptography", "scipy": "scipy",
            "pytest": "pytest"}
# one partition per visible round: the epoch layout of M14 holds thousands, each locked by a dump
EXTRA_CONF = {"max_locks_per_transaction": "1024"}


def _run(cmd: list[str], *, as_pg: bool = False, timeout: int = 900) -> subprocess.CompletedProcess:
    kw: dict = {"capture_output": True, "text": True, "timeout": timeout}
    if as_pg and os.geteuid() == 0:
        kw.update({"user": PG_USER, "group": PG_USER, "cwd": "/tmp",
                   "env": {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/tmp", "LC_ALL": "C"}})
    return subprocess.run(cmd, **kw)


def _must(what: str, r: subprocess.CompletedProcess) -> None:
    if r.returncode != 0:
        print(f"runner_stack: {what} failed ({r.returncode})\n{(r.stdout or '')[-1500:]}\n{(r.stderr or '')[-1500:]}")
        raise SystemExit(1)


def install_python() -> None:
    for pip_name, module in PACKAGES.items():
        if importlib.util.find_spec(module) is not None:
            print(f"python: {pip_name} present")
            continue
        _must(f"pip install {pip_name}", _run([sys.executable, "-m", "pip", "install", "-q", pip_name], timeout=1800))
        print(f"python: {pip_name} installed")


def pg_bin() -> Path | None:
    found = shutil.which("pg_ctl")
    if found:
        return Path(found).parent
    versions = sorted((p for p in Path("/usr/lib/postgresql").glob("*/bin") if (p / "pg_ctl").is_file()),
                      key=lambda p: float(p.parent.name) if p.parent.name.replace(".", "").isdigit() else 0.0)
    return versions[-1] if versions else None


def install_postgres() -> Path:
    bin_dir = pg_bin()
    if bin_dir is None:
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        subprocess.run(["apt-get", "update", "-qq"], capture_output=True, text=True, timeout=900, env=env)
        r = subprocess.run(["apt-get", "install", "-y", "-qq", "postgresql"], capture_output=True, text=True,
                           timeout=1800, env=env)
        _must("apt-get install postgresql (is the internet on?)", r)
        bin_dir = pg_bin()
    if bin_dir is None:
        print("runner_stack: PostgreSQL was installed but pg_ctl was not found under /usr/lib/postgresql")
        raise SystemExit(1)
    print(f"postgres: binaries in {bin_dir}")
    return bin_dir


def write_conf() -> None:
    lines = [f"listen_addresses = '{pgconf.DEV_HOST}'", f"port = {pgconf.DEV_PORT}", "logging_collector = off",
             f"unix_socket_directories = '{BASE}'"]
    lines += [f"{k} = '{v}'" for k, v in {**pgconf.HYGIENE, **EXTRA_CONF}.items()]
    with (DATA / "postgresql.conf").open("a", encoding="utf-8") as f:
        f.write("\n# V-cloak runner settings (scripts/runner_stack.py)\n" + "\n".join(lines) + "\n")


def running(bin_dir: Path) -> bool:
    return DATA.is_dir() and _run([str(bin_dir / "pg_ctl"), "-D", str(DATA), "status"], as_pg=True).returncode == 0


def start_postgres(bin_dir: Path) -> None:
    import psycopg

    root = os.geteuid() == 0
    if not (DATA / "PG_VERSION").exists():
        BASE.mkdir(parents=True, exist_ok=True)
        if root:
            shutil.chown(BASE, PG_USER, PG_USER)
        _must("initdb", _run([str(bin_dir / "initdb"), "-D", str(DATA), "-U", pgconf.DEV_USER, "-A", "trust",
                              "-E", "UTF8", "--locale=C"], as_pg=True))
        write_conf()  # root may write it: the file stays owned by postgres
    if not running(bin_dir):
        r = _run([str(bin_dir / "pg_ctl"), "-D", str(DATA), "-l", str(LOG), "-w", "start"], as_pg=True)
        if r.returncode != 0 and LOG.exists():
            print(LOG.read_text(errors="replace")[-2000:])
        _must("pg_ctl start", r)
    admin = f"host={pgconf.DEV_HOST} port={pgconf.DEV_PORT} dbname=postgres user={pgconf.DEV_USER} connect_timeout=5"
    with psycopg.connect(admin, autocommit=True) as c:
        if c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (pgconf.DEV_DB,)).fetchone() is None:
            c.execute(f'CREATE DATABASE "{pgconf.DEV_DB}"')


def status() -> int:
    import psycopg

    try:
        with psycopg.connect(pgconf.default_dsn(), autocommit=True) as c:
            doc = {"server_version": c.execute("SHOW server_version").fetchone()[0],
                   "endpoint": f"{pgconf.DEV_HOST}:{pgconf.DEV_PORT}/{pgconf.DEV_DB}",
                   "settings": {k: c.execute(f"SHOW {k}").fetchone()[0] for k in (*pgconf.HYGIENE, *EXTRA_CONF)}}
    except psycopg.Error as e:
        print(f"runner_stack: no database answers on {pgconf.DEV_HOST}:{pgconf.DEV_PORT}: {type(e).__name__}")
        return 1
    doc["hygiene_as_required"] = all(doc["settings"][k] == v for k, v in pgconf.HYGIENE.items())
    print(json.dumps(doc, indent=1))
    return 0 if doc["hygiene_as_required"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("up", "status", "down"))
    ap.add_argument("--force", action="store_true", help="run although VCLOAK_RUNNER is not colab or kaggle")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        return status()
    if os.name != "posix" or not (a.force or os.environ.get("VCLOAK_RUNNER") in RUNNERS):
        print("runner_stack: this installs system packages and is meant for the Colab/Kaggle runner only "
              "(VCLOAK_RUNNER=colab|kaggle). On the laptop use `docker compose up -d --wait db` or scripts/pgdev.py.")
        return 2
    if a.cmd == "down":
        bin_dir = pg_bin()
        if bin_dir is None or not running(bin_dir):
            print("runner_stack: not running")
            return 0
        return _run([str(bin_dir / "pg_ctl"), "-D", str(DATA), "-m", "fast", "-w", "stop"], as_pg=True).returncode
    install_python()
    start_postgres(install_postgres())
    return status()


if __name__ == "__main__":
    sys.exit(main())
