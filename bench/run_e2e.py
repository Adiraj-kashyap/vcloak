#!/usr/bin/env python3
"""E6: one cell of the end-to-end comparison, V-cloak or the unprotected baseline, under a Poisson load (M15 S1, S2).

    python bench/run_e2e.py --mode vcloak|baseline --users 10 [--rate 0.2] [--duration 120] [--warmup 20]
                            [--ack stored|queued] [--sessions on|off] [--poll-ms 500] [--store pg|sqlite]
                            [--seed 15] [--quick] [--url http://127.0.0.1:8000] [--out runs]
                            [--slots N] [--buckets N] [--window-s N] [--epoch-ms N] [--cand-k N]
                            [--rep N] [--schema e2e_...] [--dsn DSN]

U virtual users talk in pairs (users 2i and 2i+1 share a conversation). Every user sends at the times of its own
Poisson process (`vcloak.bench.e2e.schedule`, fixed by the seed before anything is sent, the same for both modes)
and polls its conversation every `--poll-ms`. The load is open loop: a send leaves at its scheduled time whether
or not earlier ones were answered. For every scheduled send one row is written:

- submit -> ack: until `POST /v1/messages` answers. `--ack` is part of every number (ISSUE-23): with `stored`
  (default) the answer comes after the commit, so in V-cloak mode it waits for the epoch boundary by design;
- submit -> readable: until a poll of the *peer* (`POST /v1/read` of the conversation) returns the payload. It is
  quantised by the poll interval, which is recorded beside it.

Sends scheduled in the first `--warmup` seconds are sent and recorded, and are not counted (audit A2).
Latencies are wall-clock differences of `time.monotonic()` in this process: the one place where the project
allows wall-clock timing (CLAUDE.md hard rule 2). The client and the service share one machine and its CPU.

The service. Without `--url` this script starts it as a child process and stops it afterwards: the app of
`vcloak serve --dev` (the same `build_backend` and `create_app`), with `--sessions on` the session layer of M11
with its Argon2id cost unchanged and only the registration and login rate limits raised: all virtual users come
from one address, and those limits act on the account routes, not on the message path (ADR-026). `--compare` is
never used. With `--url` the caller's service is measured as it is; `--sessions on` then needs limits that let U
users register. This generator opens no WebSocket (ISSUE-27): `ws_sockets` is 0 in every summary.

Around the cell (S2). `telemetry.csv`: NVML at 10 Hz (`vcloak.gpu.telemetry.Sampler`). `cpu.csv`: CPU utilisation
of the machine, of the service process and of this generator (psutil, 2 Hz). Both start when the service is ready
and so cover the account setup, the warm-up and the drain as well: the summary gives the Unix times of the
measured interval (`measured_unix`), and S3 cuts the series there. `db`: the size of the cell's tables after the
run. With `--schema e2e_...` (PostgreSQL) the cell gets a schema of its own, dropped first, so every cell starts
on an empty store; without it the cell shares the default schema with whatever ran before. What cannot be read
(no NVML, no psutil, the in-memory store) is recorded as unavailable with the reason.

Outputs in the run dir: samples.csv (one row per scheduled send, the excluded ones marked), summary.json,
server_log.txt, telemetry.csv and cpu.csv when available. On the numpy backend the run is a correctness run of the
generator: its numbers are never a performance result and the summary lists no metric.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import csv
import json
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402
import numpy as np  # noqa: E402

from vcloak import runs  # noqa: E402
from vcloak.bench import e2e, hostload  # noqa: E402
from vcloak.bench.derive import NM  # noqa: E402
from vcloak.client.device import DeviceKey  # noqa: E402
from vcloak.crypto.client import PAYLOAD_LEN  # noqa: E402
from vcloak.gpu import telemetry  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402

QUICK = {"duration": 30.0}  # ai/modules/M15: quick runs last 30 s
SERVER_OPTS = ("slots", "buckets", "window_s", "epoch_ms", "cand_k")
ACK_STATUS = {"stored": 201, "queued": 202}
SETUP_PARALLEL = 8  # registrations and logins in flight: each one is an Argon2id hash on the service
TELEMETRY_HZ = 10.0  # ai/modules/M15 S2
LOGIN_REFRESH_AFTER_S = 60.0  # access tokens live 600 s: refresh them all when the logins took longer than this


# ---------------------------------------------------------------- the service (child process)

def serve_child(argv: list[str]) -> int:
    """`vcloak serve --dev` with the account rate limits raised for `--bench-users` (see the module docstring)."""
    import uvicorn

    from vcloak import cli
    from vcloak.service import logsafe
    from vcloak.service.app import create_app
    from vcloak.service.session import SessionConfig, SessionService

    ap = argparse.ArgumentParser()
    ap.add_argument("--bench-users", type=int, required=True)
    own, rest = ap.parse_known_args(argv)
    a = cli.build_parser().parse_args(["serve", "--dev", "--clock", "wall", *rest])
    if a.compare or not cli.is_loopback(a.host):
        print("run_e2e: the measured service never runs with --compare or on a non-loopback host", file=sys.stderr)
        return 2
    logsafe.configure()
    sessions = None
    if a.sessions:
        n = 4 * own.bench_users + 64
        sessions = SessionService(SessionConfig(register_ip_max=n, login_ip_max=n))
    uvicorn.run(create_app(cli.build_backend(a), sessions=sessions, dev=True), host=a.host, port=a.port,
                access_log=False, log_config=logsafe.server_log_config(uvicorn.config.LOGGING_CONFIG))
    return 0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def serve_args(a: argparse.Namespace, port: int) -> list[str]:
    out = ["--mode", a.mode, "--store", a.store, "--port", str(port), "--host", "127.0.0.1"]
    if a.sessions == "on":
        out.append("--sessions")
    for name in ("schema", "dsn"):
        if getattr(a, name) is not None:
            out += ["--" + name, getattr(a, name)]
    for name in SERVER_OPTS:
        if getattr(a, name) is not None:
            out += ["--" + name.replace("_", "-"), str(getattr(a, name))]
    return out


def wait_ready(base: str, proc: subprocess.Popen[bytes] | None, timeout_s: float) -> dict[str, Any]:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"the service stopped while starting (exit {proc.returncode})")
        try:
            r = httpx.get(base + "/healthz", timeout=2.0)
            if r.status_code == 200 and r.json().get("ready"):
                return dict(r.json())
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"the service was not ready after {timeout_s:.0f} s")


# ---------------------------------------------------------------- the load

class User:
    def __init__(self, idx: int, conv: int, token: str, device: DeviceKey | None) -> None:
        self.idx, self.conv, self.conv_token, self.device = idx, conv, token, device
        self.name, self.password = f"e2e_user_{idx}", f"e2e-password-{idx:06d}"  # test accounts of this run only
        self.access: str | None = None
        self.refresh: str | None = None


class Cell:
    """One run: the users, their sends, and the samples it fills."""

    def __init__(self, base: str, a: argparse.Namespace, client: httpx.AsyncClient, window_s: int) -> None:
        self.base, self.a, self.http, self.window_s = base, a, client, window_s
        rng = np.random.default_rng([a.seed, 0xE2E])
        self.payload_rng = np.random.default_rng([a.seed, 0xE2E, 1])
        self.poll_s = a.poll_ms / 1000.0
        self.users: list[User] = []
        tokens = e2e.conv_tokens(rng, a.users // 2)
        for conv, members in enumerate(e2e.pairs(a.users)):
            self.users += [User(u, conv, tokens[conv], DeviceKey() if a.sessions == "on" else None)
                           for u in members]
        self.phase = rng.uniform(0.0, self.poll_s, size=a.users)  # readers do not all poll at the same instant
        self.total_s = a.warmup + a.duration
        self.sends = e2e.schedule(a.users, a.rate, self.total_s, a.seed)
        self.samples = [e2e.Sample(s.user, s.conv, s.t) for s in self.sends]
        # conversation -> payload -> (sample, monotonic submit time, window at submit): what the peer must still see
        self.pending: list[dict[str, tuple[e2e.Sample, float, int]]] = [{} for _ in range(a.users // 2)]
        self.reads = 0
        self.read_errors: dict[str, int] = {}
        self.setup: dict[str, Any] = {}
        self.t0 = self.t0_unix = 0.0

    def headers(self, u: User, method: str, path: str, *, token: bool = True) -> dict[str, str]:
        if u.device is None:
            return {}
        if not token:
            return {"DPoP": u.device.proof(method, self.base + path)}
        return {"DPoP": u.device.proof(method, self.base + path, u.access), "Authorization": f"DPoP {u.access}"}

    # -- accounts (not part of any latency)

    async def _account(self, u: User, sem: asyncio.Semaphore, path: str, body: dict[str, str], want: int) -> None:
        async with sem:
            hdr = self.headers(u, "POST", path, token=False) if path != "/v1/auth/register" else {}
            r = await self.http.post(path, json=body, headers=hdr)
        if r.status_code != want:
            raise RuntimeError(f"{path} for user {u.idx}: HTTP {r.status_code} {r.text[:120]}")
        if path != "/v1/auth/register":
            u.access, u.refresh = r.json()["access_token"], r.json()["refresh_token"]

    async def accounts(self) -> None:
        if self.a.sessions != "on":
            self.setup = {"sessions": False}
            return
        sem = asyncio.Semaphore(SETUP_PARALLEL)
        t = time.monotonic()
        await asyncio.gather(*(self._account(u, sem, "/v1/auth/register",
                                             {"username": u.name, "password": u.password}, 201) for u in self.users))
        t_reg = time.monotonic()
        await asyncio.gather(*(self._account(u, sem, "/v1/auth/login",
                                             {"username": u.name, "password": u.password}, 200) for u in self.users))
        t_login = time.monotonic()
        refreshed = t_login - t_reg > LOGIN_REFRESH_AFTER_S
        if refreshed:  # no token is older than the refresh round when the run starts
            await asyncio.gather(*(self._account(u, sem, "/v1/auth/refresh", {"refresh_token": u.refresh or ""}, 200)
                                   for u in self.users))
        self.setup = {"sessions": True, "register_s": t_reg - t, "login_s": t_login - t_reg, "refreshed": refreshed,
                      "refresh_s": time.monotonic() - t_login if refreshed else 0.0}

    # -- sending

    async def send_one(self, send: e2e.Send, sample: e2e.Sample) -> None:
        u = self.users[send.user]
        payload = base64.b64encode(self.payload_rng.bytes(PAYLOAD_LEN)).decode()
        body = {"conv_token": u.conv_token, "payload_b64": payload, "ack": self.a.ack}
        hdr = self.headers(u, "POST", "/v1/messages")
        t = time.monotonic()
        sample.t_submit = t - self.t0
        # known to the reader before the request leaves: the peer may see the message before the answer arrives
        self.pending[u.conv][payload] = (sample, t, int(time.time() // self.window_s))
        try:
            r = await self.http.post("/v1/messages", json=body, headers=hdr)
        except httpx.HTTPError as e:
            sample.error = type(e).__name__
            self.pending[u.conv].pop(payload, None)
            return
        sample.status = r.status_code
        if r.status_code == ACK_STATUS[self.a.ack]:
            sample.ack_ms = (time.monotonic() - t) * 1000.0
            return
        sample.error = _error_name(r)
        self.pending[u.conv].pop(payload, None)

    async def sender(self) -> None:
        tasks = []
        for send, sample in zip(self.sends, self.samples, strict=True):
            delay = self.t0 + send.t - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(self.send_one(send, sample)))
        await asyncio.gather(*tasks)

    # -- reading

    async def read_once(self, u: User, win: int) -> None:
        hdr = self.headers(u, "POST", "/v1/read")
        self.reads += 1
        try:
            r = await self.http.post("/v1/read", json={"conv_token": u.conv_token, "win": win}, headers=hdr)
        except httpx.HTTPError as e:
            self.read_errors[type(e).__name__] = self.read_errors.get(type(e).__name__, 0) + 1
            return
        now = time.monotonic()
        if r.status_code != 200:
            self.read_errors[_error_name(r)] = self.read_errors.get(_error_name(r), 0) + 1
            return
        pending = self.pending[u.conv]
        for payload in r.json()["payloads_b64"]:
            hit = pending.get(payload)
            if hit is not None and hit[0].user != u.idx:  # a user resolves the messages of its peer, not its own
                hit[0].readable_ms = (now - hit[1]) * 1000.0
                del pending[payload]

    async def reader(self, u: User, stop: asyncio.Event) -> None:
        await asyncio.sleep(float(self.phase[u.idx]))
        while not stop.is_set():
            wins = {int(time.time() // self.window_s)}
            # a message is stored in the window of its epoch: the one open when it was sent, or the next
            wins |= {w for s, _, w in self.pending[u.conv].values() if s.user != u.idx}
            for win in sorted(wins):
                await self.read_once(u, win)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), self.poll_s)

    async def run(self) -> None:
        await self.accounts()
        stop = asyncio.Event()
        self.t0, self.t0_unix = time.monotonic(), time.time()
        readers = [asyncio.create_task(self.reader(u, stop)) for u in self.users]
        await self.sender()
        end = time.monotonic() + self.a.drain  # the last messages still have to be written and read
        while time.monotonic() < end and any(self.pending):
            await asyncio.sleep(self.poll_s / 2)
        stop.set()
        await asyncio.gather(*readers)


def _error_name(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error") or f"http_{r.status_code}")
    except ValueError:
        return f"http_{r.status_code}"


async def run_cell(base: str, a: argparse.Namespace) -> tuple[Cell, dict[str, Any], dict[str, Any], dict[str, Any]]:
    limits = httpx.Limits(max_connections=a.connections, max_keepalive_connections=a.connections)
    async with httpx.AsyncClient(base_url=base, timeout=a.timeout, limits=limits) as client:
        windows = (await client.get("/v1/windows")).json()
        cell = Cell(base, a, client, int(windows["window_s"]))
        before = (await client.get("/healthz")).json()
        await cell.run()
        after = (await client.get("/healthz")).json()
    return cell, windows, before, after


# ---------------------------------------------------------------- outputs

def write_samples(path: Path, cell: Cell, warmup_s: float, duration_s: float) -> None:
    counted = {id(s) for s in e2e.measured(cell.samples, warmup_s, duration_s)}
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["user", "conv", "t_sched_s", "t_submit_s", "ack_ms", "readable_ms", "status", "error", "counted"])
        for s in cell.samples:
            w.writerow([s.user, s.conv, f"{s.t_sched:.6f}", "" if s.t_submit is None else f"{s.t_submit:.6f}",
                        "" if s.ack_ms is None else f"{s.ack_ms:.3f}",
                        "" if s.readable_ms is None else f"{s.readable_ms:.3f}", s.status, s.error,
                        int(id(s) in counted)])


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--mode", choices=("vcloak", "baseline"), required=True)
    ap.add_argument("--users", type=int, required=True, help="virtual users, an even number")
    ap.add_argument("--rate", type=float, default=0.2, help="sends per second of one user (Poisson)")
    ap.add_argument("--duration", type=float, default=None, help="measured seconds (default 120; 30 with --quick)")
    ap.add_argument("--warmup", type=float, default=20.0, help="seconds before the measured interval, not counted")
    ap.add_argument("--drain", type=float, default=5.0, help="seconds to keep reading after the last send")
    ap.add_argument("--ack", choices=tuple(ACK_STATUS), default="stored")
    ap.add_argument("--sessions", choices=("on", "off"), default="on", help="per-user DPoP clients (M11)")
    ap.add_argument("--poll-ms", type=float, default=500.0, help="read interval of every user")
    ap.add_argument("--store", choices=("pg", "sqlite"), default="pg", help="evaluation numbers need pg (ADR-008)")
    ap.add_argument("--connections", type=int, default=256, help="HTTP connections of the generator")
    ap.add_argument("--timeout", type=float, default=30.0, help="seconds before a request counts as failed")
    ap.add_argument("--seed", type=int, default=15)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--url", default=None, help="measure a running service instead of starting one")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--rep", type=int, default=1, help="repetition number of this cell (S2 runs every cell twice)")
    ap.add_argument("--schema", default=None,
                    help="PostgreSQL schema of this cell, e2e_...: dropped first, measured afterwards")
    ap.add_argument("--dsn", default=None, help="PostgreSQL DSN (default: VCLOAK_PG_DSN or the development database)")
    for name in SERVER_OPTS:
        ap.add_argument("--" + name.replace("_", "-"), type=int, default=None, help="passed to the service")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--serve-child"]:
        return serve_child(argv[1:])
    a = build_parser().parse_args(argv)
    if a.duration is None:
        a.duration = QUICK["duration"] if a.quick else 120.0
    e2e.pairs(a.users)  # refuse an odd number before anything starts
    if a.schema is not None:
        if a.store != "pg" or a.url:
            build_parser().error("--schema needs --store pg and a service this script starts")
        hostload.check_cell_schema(a.schema)
    backend = get_backend()
    command = "python bench/run_e2e.py " + " ".join(shlex.quote(x) for x in argv)
    params = {k: getattr(a, k) for k in ("mode", "users", "rate", "duration", "warmup", "drain", "ack", "sessions",
                                         "poll_ms", "store", "connections", "timeout", "rep", "schema",
                                         *SERVER_OPTS)}
    # the name stays short: a run id of 43 characters or more reads as key-like to scripts/check_secrets.py
    run_dir = runs.new_run("M15", f"{a.mode}_u{a.users}_r{a.rep}", step="S2", owner="Divyansh", command=command,
                           seed=a.seed, quick=a.quick, root=Path.cwd(), runs_dir=a.out, backend=backend,
                           params={**params, "service": "caller's (--url)" if a.url else "child process"})
    proc: subprocess.Popen[bytes] | None = None
    log = (run_dir / "server_log.txt").open("wb")
    status, notes = "OK", []
    gpu_sampler = telemetry.Sampler(run_dir / "telemetry.csv", hz=TELEMETRY_HZ)
    cpu_sampler: hostload.CpuSampler | None = None
    sampled: dict[str, Any] = {}
    try:
        base = a.url.rstrip("/") if a.url else f"http://127.0.0.1:{(port := free_port())}"
        if a.schema is not None:
            hostload.drop_cell_schema(a.dsn, a.schema)
        if not a.url:
            child = [sys.executable, str(Path(__file__).resolve()), "--serve-child", "--bench-users", str(a.users),
                     *serve_args(a, port)]
            proc = subprocess.Popen(child, stdout=log, stderr=subprocess.STDOUT, cwd=Path.cwd())
        ready = wait_ready(base, proc, 180.0)
        cpu_sampler = hostload.CpuSampler(run_dir / "cpu.csv", proc.pid if proc is not None else None).start()
        gpu_sampler.start()
        cell, windows, before, after = asyncio.run(run_cell(base, a))
    except Exception as e:  # noqa: BLE001 - whatever stopped the cell is the result of the cell
        runs.finish_run(run_dir, status="FAIL", notes=f"{type(e).__name__}: {e}")
        print(f"run_e2e: FAIL - {type(e).__name__}: {e}")
        return 1
    finally:
        sampled["telemetry"] = {**gpu_sampler.stop(), "hz": TELEMETRY_HZ}
        if cpu_sampler is not None:
            sampled["cpu"] = cpu_sampler.stop()
        if proc is not None:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(20)
        log.close()

    if not sampled["telemetry"]["available"]:
        sampled["telemetry"]["reason"] = "NVML is not available on this machine"
    db = (hostload.db_size(a.dsn, a.schema) if a.store == "pg" and not a.url else
          {"available": False, "reason": "the caller's service (--url)" if a.url else "in-memory store (sqlite)"})
    stats = e2e.summarise(cell.samples, a.warmup, a.duration)
    write_samples(run_dir / "samples.csv", cell, a.warmup, a.duration)
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in ("epochs", "overflow", "missed")}
    reason = None if backend.is_gpu else "numpy backend: a correctness run of the generator, never a performance result"
    if windows.get("mode") != a.mode:
        status = "FAIL"
        notes.append(f"the service answers in mode {windows.get('mode')}, not {a.mode}")
    if stats["acked"] == 0:
        status = "FAIL"
        notes.append("no submission of the measured interval was acknowledged")
    if reason:
        notes.append(reason)
    (run_dir / "summary.json").write_text(json.dumps({
        "metrics": [],  # the E2E-* rows are derived in S3, from GPU runs only
        "reason": reason, "mode": a.mode, "users": a.users, "conversations": a.users // 2,
        "users_per_conversation": 2, "rep": a.rep, "ack": a.ack,
        "sessions": a.sessions == "on", "ws_sockets": 0, "poll_ms": a.poll_ms, "rate_per_user_s": a.rate,
        "warmup_s": a.warmup, "duration_s": a.duration, "drain_s": a.drain, "store": a.store,
        "service": {"started_by": "caller" if a.url else "this script (child process)", "windows": windows,
                    "healthz_ready": ready, "healthz_before": before, "healthz_after": after, "delta": delta},
        "setup": cell.setup, "stats": stats,
        "t0_unix": cell.t0_unix,
        "measured_unix": [cell.t0_unix + a.warmup, cell.t0_unix + a.warmup + a.duration],
        "telemetry": sampled["telemetry"], "cpu": sampled.get("cpu"), "db": db, "power": hostload.power_state(),
        "reads": {"requests": cell.reads, "errors": dict(sorted(cell.read_errors.items()))},
        "clock": "time.monotonic() in the generator process; client and service on one machine",
        "device": backend.device_info()}, indent=2) + "\n", encoding="utf-8")
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))

    ack, rd = stats["ack_ms"], stats["readable_ms"]
    print(f"run dir     {run_dir}")
    print(f"cell        {a.mode}  users {a.users}  ack {a.ack}  sessions {a.sessions}  store {a.store}  "
          f"backend {backend.name}")
    print(f"sends       scheduled {stats['scheduled']}  acked {stats['acked']}  errors {stats['errors'] or 'none'}  "
          f"(warm-up excluded: {stats['excluded_warmup']})")
    print(f"ack ms      p50 {_fmt(ack['p50'])}  p95 {_fmt(ack['p95'])}  p99 {_fmt(ack['p99'])}")
    print(f"readable ms p50 {_fmt(rd['p50'])}  p95 {_fmt(rd['p95'])}  p99 {_fmt(rd['p99'])}  "
          f"missing {stats['readable_missing']}  (poll {a.poll_ms:.0f} ms)")
    print(f"service     epochs {delta['epochs']}  overflow {delta['overflow']}  missed {delta['missed']}  "
          f"reads {cell.reads}  read errors {cell.read_errors or 'none'}")
    print(f"sampled     NVML {sampled['telemetry']['samples']}  cpu {(sampled.get('cpu') or {}).get('samples', 0)}  "
          f"db bytes {db.get('schema_bytes', db.get('database_bytes', NM))}")
    print(f"status      {status}   {'; '.join(notes)}")
    return 0 if status == "OK" else 1


def _fmt(x: Any) -> str:
    return NM if x == NM else f"{x:.1f}"


if __name__ == "__main__":
    raise SystemExit(main())
