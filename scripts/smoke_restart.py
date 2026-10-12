#!/usr/bin/env python3
"""Kill `vcloak serve` in the middle of a window, start it again, and check what the store holds (ISSUE-22).

    python scripts/smoke_restart.py [--port 8012] [--log-dir DIR]

Needs the development PostgreSQL (`docker compose up -d --wait db`); it works in a schema of its own,
dropped at the end. The server runs with `--dev` (the public development key) on the wall clock.

1. Server A. Messages are sent with `ack: stored` over several epochs of one window, each answered 201.
   A few more are sent with the default acknowledgement (202) and the process is killed at once.
2. The store, read directly: every message answered 201 is there; the window is on the pending list and
   was written by more than one transaction (one per epoch: the arrival-time layout).
3. Server B on the same store, once the window has closed: the window is off the pending list, its
   partition is a new file written by one transaction, with the same rows, and a client reads the
   conversation back and decrypts it.

A correctness check only: nothing is timed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_service import wait_ready  # noqa: E402
from vcloak.crypto.client import decrypt_content, encrypt_content  # noqa: E402
from vcloak.service.models import decode_payload, encode_payload  # noqa: E402
from vcloak.storage.repo import PgRepo  # noqa: E402

WINDOW_S = 2
EPOCH_MS = 100
GROUPS, PER_GROUP, UNACKED = 3, 10, 5


def layout(repo: PgRepo, win: int) -> tuple[int, int, int]:
    """(rows, transactions that wrote them, file node) of the partition of one window."""
    part = PgRepo.partition_name(win)
    rows, writers = repo.execute(f"SELECT count(*), count(DISTINCT xmin::text) FROM {part}")[0]
    return rows, writers, repo.execute("SELECT pg_relation_filenode(%s::regclass)", (part,))[0][0]


async def send(base: str, conv: str, payloads: list[bytes], ack: str) -> list[int]:
    async with httpx.AsyncClient(base_url=base, timeout=10.0) as client:
        answers = await asyncio.gather(*(client.post("/v1/messages", json={
            "conv_token": conv, "payload_b64": encode_payload(p), "ack": ack}) for p in payloads))
    return [r.status_code for r in answers]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8012)
    ap.add_argument("--log-dir", default=None, help="write the output of the two servers to this directory")
    a = ap.parse_args(argv)

    schema = "smoke_" + uuid.uuid4().hex[:12]
    base = f"http://127.0.0.1:{a.port}"
    cmd = [sys.executable, "-m", "vcloak.cli", "serve", "--dev", "--store", "pg", "--schema", schema,
           "--port", str(a.port), "--window-s", str(WINDOW_S), "--epoch-ms", str(EPOCH_MS), "--slots", "64"]
    print("server:", " ".join(cmd[1:]).replace(schema, "smoke_<random>"))

    def start(name: str) -> tuple[subprocess.Popen[bytes], object]:
        log = open(Path(a.log_dir) / f"serve_{name}.log", "wb") if a.log_dir else subprocess.DEVNULL  # noqa: SIM115
        return subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT), log

    checks: dict[str, bool] = {}
    k_content = os.urandom(32)  # the clients' shared key; it never reaches the server
    conv = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
    acked = [f"stored {i}".encode() for i in range(GROUPS * PER_GROUP)]
    unacked = [f"queued {i}".encode() for i in range(UNACKED)]
    repo = PgRepo(schema=schema)
    proc_a, log_a = start("a")
    proc_b = None
    log_b: object = subprocess.DEVNULL
    try:
        with httpx.Client(base_url=base, timeout=10.0) as client:
            wait_ready(client, proc_a)
            while time.time() % WINDOW_S > 0.2:  # start with a window, so that the epochs below share it
                time.sleep(0.02)
            win = client.get("/v1/windows").json()["win"]
            codes: list[int] = []
            for g in range(GROUPS):
                group = acked[g * PER_GROUP:(g + 1) * PER_GROUP]
                codes += asyncio.run(send(base, conv, [encrypt_content(k_content, t) for t in group], "stored"))
            checks["every ack=stored message was answered 201"] = codes == [201] * len(acked)
            codes = asyncio.run(send(base, conv, [encrypt_content(k_content, t) for t in unacked], "queued"))
            checks["the messages without ack were answered 202"] = codes == [202] * len(unacked)
        proc_a.kill()  # no shutdown: the queue is not written, nothing is closed
        proc_a.wait(timeout=10)
        print(f"server A killed in window +0 after {len(acked)} stored and {len(unacked)} queued messages")

        pending = repo.pending_windows()
        rows, writers, node = layout(repo, win)
        print(f"store after the kill: pending windows {len(pending)}, rows {rows}, "
              f"transactions that wrote the window {writers}")
        checks["the window is on the pending list"] = pending == [win]
        checks["every message answered 201 is in the store"] = rows >= len(acked)
        checks["the window is in its arrival-time layout (one transaction per epoch)"] = writers > 1
        lost = len(acked) + len(unacked) - rows
        print(f"messages answered 202 and lost with the queue: {lost} of {len(unacked)}")

        while time.time() < (win + 1) * WINDOW_S + 0.2:  # the window closes while nothing runs
            time.sleep(0.05)
        proc_b, log_b = start("b")
        with httpx.Client(base_url=base, timeout=10.0) as client:
            wait_ready(client, proc_b)
            deadline = time.monotonic() + 10
            while repo.pending_windows() and time.monotonic() < deadline:
                time.sleep(0.05)
            rows_b, writers_b, node_b = layout(repo, win)
            print(f"store after the restart: pending windows {len(repo.pending_windows())}, rows {rows_b}, "
                  f"transactions that wrote the window {writers_b}, new file {node_b != node}")
            checks["the window is off the pending list"] = repo.pending_windows() == []
            checks["the window was rewritten by one transaction into a new file"] = writers_b == 1 and node_b != node
            checks["the rewrite kept every row"] = rows_b == rows
            r = client.post("/v1/read", json={"conv_token": conv, "win": win})
            got = [decrypt_content(k_content, decode_payload(p)) for p in r.json()["payloads_b64"]]
            checks["a client reads and decrypts every stored message after the restart"] = (
                r.status_code == 200 and len(got) == rows and set(acked) <= set(got) and len(set(got)) == len(got))
            time.sleep(3 * EPOCH_MS / 1000)
            checks["nothing is rewritten a second time"] = layout(repo, win) == (rows_b, writers_b, node_b)
    finally:
        for proc in (proc_a, proc_b):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
        for log in (log_a, log_b):
            if hasattr(log, "close"):
                log.close()
        repo.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        repo.close()
    for name, ok in checks.items():
        print("PASS" if ok else "FAIL", name)
    ok = len(checks) == 10 and all(checks.values())
    print("SMOKE", "PASS" if ok else "FAIL", "restart store=pg")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
