#!/usr/bin/env python3
"""E5: the session attack matrix, and the time of one DPoP verification (M11 S6).

    python bench/run_session_matrix.py [--quick] [--runs 2000] [--warmup 200] [--out runs] [--results results/session]

The matrix drives the real app in-process (the numpy simulator behind it, a SQLite store, the session
layer with its default limits and Argon2id cost) with the independent client of tests/dpop_client.py. Each
scenario records what was expected and what the server answered, and for a refused request the check the
server named. The eleven session scenarios of the seed oracle are here (`seed/vcloak_oracle.py`,
`session_tests`), its twelfth (the clients' key agreement) too, and the cases M11 adds: tickets, logout,
the login rate limit.

The timing is `SessionService.verify` for an accepted request (proof and access token), per call, with
`time.perf_counter_ns` on this machine's CPU: proofs are signed before the clock starts. It is a host
measurement and says nothing about the GPU.

Outputs in the run dir: e5_matrix.json, verify_timing.json, summary.json. With `--results DIR` the matrix
is copied to DIR/e5_matrix.json (`--results ""` skips the copy).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(1, str(ROOT / "tests"))

from dpop_client import Device  # noqa: E402
from vcloak import runs  # noqa: E402
from vcloak.crypto import client as content  # noqa: E402
from vcloak.crypto.client import PAYLOAD_LEN  # noqa: E402
from vcloak.gpu.runtime import get_backend  # noqa: E402
from vcloak.service.app import VcloakBackend, create_app  # noqa: E402
from vcloak.service.models import encode_payload  # noqa: E402
from vcloak.service.scheduler import SimClock  # noqa: E402
from vcloak.service.session import PasswordParams, SessionConfig, SessionService  # noqa: E402
from vcloak.storage.repo import SqliteRepo  # noqa: E402

BASE = "http://vcloak.test"
WS = "ws://vcloak.test/v1/ws"
WS_URL = BASE + "/v1/ws"
CONV = "e5" * 16  # a conversation token of the matrix (not a secret: nothing real is stored under it)
RUNS, WARMUP = 2000, 200
QUICK_RUNS, QUICK_WARMUP = 200, 20
PASS_METRIC, VERIFY_METRIC = "SEC-E5-PASS", "SEC-DPOP-VERIFY-US"


class ShiftedClock:
    """The wall clock plus an offset the matrix moves (token and ticket expiry)."""

    def __init__(self) -> None:
        self.offset = 0.0

    def __call__(self) -> float:
        return time.time() + self.offset

    def advance(self, seconds: float) -> None:
        self.offset += seconds


def _dev_master() -> bytearray:
    return bytearray(range(32))  # the public development key of `vcloak serve --dev`


def _url(path: str) -> str:
    return BASE + path


class Matrix:
    """The scenarios, in order, against one running app. `rows` is the result."""

    def __init__(self, client: Any, clock: ShiftedClock, password: str) -> None:
        self.client, self.clock, self.password = client, clock, password
        self.rows: list[dict[str, Any]] = []

    # -- recording --

    def record(self, scenario: str, channel: str, expected: tuple[int | str, str | None],
               observed: tuple[int | str, str | None]) -> None:
        def text(pair: tuple[int | str, str | None]) -> str:
            return f"{pair[0]} ({pair[1]})" if pair[1] else str(pair[0])

        self.rows.append({"id": len(self.rows) + 1, "scenario": scenario, "channel": channel,
                          "expected": text(expected), "observed": text(observed),
                          "expected_check": expected[1], "failed_check": observed[1],
                          "as_expected": expected == observed})

    @staticmethod
    def answer(r: Any) -> tuple[int, str | None]:
        """The status of a response and, when it refuses, the check or reason the server named."""
        if r.status_code < 400:
            return r.status_code, None
        body = r.json()
        return r.status_code, body.get("failed_check") or body.get("reason") or body.get("error")

    def http(self, scenario: str, expected: tuple[int, str | None], r: Any) -> Any:
        self.record(scenario, "http", expected, self.answer(r))
        return r

    def socket(self, scenario: str, expected: tuple[str, str | None], frame: str) -> None:
        """Open /v1/ws, send `frame` first, and record how the server answers it."""
        from starlette.websockets import WebSocketDisconnect

        with self.client.websocket_connect(WS) as ws:
            ws.send_text(frame)
            try:
                first = json.loads(ws.receive_text())
                observed: tuple[str, str | None] = (f"open ({first.get('type')})", None)
            except WebSocketDisconnect as e:
                observed = (f"close {e.code}", e.reason)
        self.record(scenario, "websocket", expected, observed)

    # -- the client side --

    def register(self, name: str) -> None:
        r = self.client.post("/v1/auth/register", json={"username": name, "password": self.password})
        assert r.status_code == 201, r.text

    def login(self, dev: Device, name: str, password: str | None = None) -> Any:
        path = "/v1/auth/login"
        return self.client.post(path, json={"username": name, "password": password or self.password},
                                headers=dev.headers("POST", _url(path)))

    def read(self, headers: dict[str, str]) -> Any:
        return self.client.post("/v1/read", json={"conv_token": CONV, "win": 0}, headers=headers)

    def call(self, dev: Device, access: str, path: str, body: Any = None) -> Any:
        return self.client.post(path, json=body, headers=dev.headers("POST", _url(path), access))

    def refresh(self, dev: Device, refresh_token: str) -> Any:
        path = "/v1/auth/refresh"
        return self.client.post(path, json={"refresh_token": refresh_token}, headers=dev.headers("POST", _url(path)))

    def ticket(self, dev: Device, access: str) -> str:
        r = self.call(dev, access, "/v1/auth/ws-ticket")
        assert r.status_code == 200, r.text
        return r.json()["ticket"]

    @staticmethod
    def frame(dev: Device, ticket: str, **kw: Any) -> str:
        return json.dumps({"ticket": ticket, "dpop": dev.proof("GET", WS_URL, **kw)})

    # -- the scenarios --

    def run(self) -> list[dict[str, Any]]:
        clock = self.clock
        dev, atk = Device(clock), Device(clock)
        read_url = _url("/v1/read")
        self.register("alice")
        tokens = self.login(dev, "alice").json()
        access, refresh = tokens["access_token"], tokens["refresh_token"]
        r = self.call(dev, access, "/v1/messages",
                      {"conv_token": CONV, "payload_b64": encode_payload(bytes(PAYLOAD_LEN))})
        assert r.status_code == 202, r.text

        # the request layer: one proof per request, bound to the token and to the key
        self.http("Valid token + fresh DPoP proof", (200, None), self.read(dev.headers("POST", read_url, access)))
        fixed = dev.headers("POST", read_url, access)
        assert self.read(fixed).status_code == 200
        self.http("Replayed proof (same jti)", (401, "jti"), self.read(fixed))
        self.http("Stolen token, attacker's own key", (401, "key_binding"),
                  self.read(atk.headers("POST", read_url, access)))
        self.http("Proof for different URL (htu)", (401, "htu"),
                  self.read(dev.headers("POST", _url("/v1/messages"), access)))
        self.http("Proof for different method (htm)", (401, "htm"), self.read(dev.headers("GET", read_url, access)))
        self.http("Stale proof (iat -5 min)", (401, "iat"),
                  self.read(dev.headers("POST", read_url, access, iat=clock() - 300)))
        tampered = access[:-2] + ("AA" if access[-2:] != "AA" else "BB")
        self.http("Tampered access token", (401, "token_mac"), self.read(dev.headers("POST", read_url, tampered)))
        second = self.login(dev, "alice").json()["access_token"]
        self.http("Proof made for another access token (ath)", (401, "ath"),
                  self.read({"DPoP": dev.proof("POST", read_url, second), "Authorization": f"DPoP {access}"}))
        self.http("Stolen token sent as a bearer token, no proof", (401, "proof_format"),
                  self.read({"Authorization": f"Bearer {access}"}))
        self.http("Proof with the owner's public key, signed by the attacker", (401, "signature"),
                  self.read(dev.headers("POST", read_url, access, signer=atk)))
        self.http("Proof that declares another algorithm (HS256)", (401, "alg"),
                  self.read(dev.headers("POST", read_url, access, header={"alg": "HS256"})))

        # the socket: a ticket opens one socket, for the key it was issued to, within 30 s
        spent = self.ticket(dev, access)
        self.socket("Valid ticket + proof of the same key", ("open (ready)", None), self.frame(dev, spent))
        self.socket("Ticket reused", ("close 4401", "ticket_unused"), self.frame(dev, spent))
        stolen = self.ticket(dev, access)
        self.socket("Ticket presented with a different key", ("close 4401", "ticket_key"), self.frame(atk, stolen))
        clock.advance(31)
        self.socket("Ticket presented after 31 s", ("close 4401", "ticket_exp"), self.frame(dev, stolen))

        # expiry and the refresh family
        clock.advance(600)
        self.http("Expired access token", (401, "token_exp"), self.read(dev.headers("POST", read_url, access)))
        rotated = self.http("Refresh-token rotation", (200, None), self.refresh(dev, refresh)).json()
        self.http("Refresh token presented with the attacker's key", (401, "key_binding"),
                  self.refresh(atk, rotated["refresh_token"]))
        self.http("Old refresh token reused", (401, "reuse"), self.refresh(dev, refresh))
        self.http("Rotated token after reuse detected", (401, "family_revoked"),
                  self.refresh(dev, rotated["refresh_token"]))
        self.http("Access token of the revoked family", (401, "token_revoked"),
                  self.read(dev.headers("POST", read_url, rotated["access_token"])))

        # logout
        from starlette.websockets import WebSocketDisconnect

        fresh = self.login(dev, "alice").json()["access_token"]
        with self.client.websocket_connect(WS) as ws:
            ws.send_text(self.frame(dev, self.ticket(dev, fresh)))
            assert json.loads(ws.receive_text())["type"] == "ready"
            assert self.call(dev, fresh, "/v1/auth/logout").status_code == 204
            try:
                ws.receive_text()
                observed: tuple[str, str | None] = ("open", None)
            except WebSocketDisconnect as e:
                observed = (f"close {e.code}", e.reason)
        self.record("Logout while a socket is open", "websocket", ("close 4001", "session_ended"), observed)
        self.http("Access token after logout", (401, "token_revoked"), self.read(dev.headers("POST", read_url, fresh)))

        # guessing a password: five attempts on one name, then the name is closed for the window
        self.register("bob")
        guesses = [self.answer(self.login(atk, "bob", f"wrong password {i}")) for i in range(5)]
        assert guesses == [(401, "invalid_credentials")] * 5, guesses
        self.http("Login brute force: sixth guess on one account", (429, "rate_limited"),
                  self.login(atk, "bob", "wrong password 5"))
        self.http("Login brute force: the right password while the limit holds", (429, "rate_limited"),
                  self.login(atk, "bob"))

        # the seed's twelfth row: the two clients agree on the content key (client side; the server has no part)
        a_priv, a_pub = content.generate_prekey()
        b_priv, b_pub = content.generate_prekey()
        ka = content.derive_content_key(a_priv, b_pub, content.transcript(a_pub, b_pub))
        kb = content.derive_content_key(b_priv, a_pub, content.transcript(b_pub, a_pub))
        same = "keys equal" if ka == kb and len(ka) == 32 else "MISMATCH"
        self.record("X25519+HKDF content key agreement", "client", ("keys equal", None), (same, None))
        return self.rows


def run_matrix(password_params: PasswordParams | None = None) -> list[dict[str, Any]]:
    """Run every scenario against a fresh app. `password_params` lowers the Argon2id cost (tests only)."""
    import os

    from starlette.testclient import TestClient

    clock = ShiftedClock()
    config = SessionConfig(password=password_params) if password_params else SessionConfig()
    sessions = SessionService(config, now=clock)
    backend = VcloakBackend(SqliteRepo(), SimClock(), _dev_master, gpu=get_backend("numpy"), slots=64, buckets=4,
                            window_s=1, epoch_ms=200, cand_k=128, autorun=False)
    password = os.urandom(12).hex()  # lives in this process only
    with TestClient(create_app(backend, sessions=sessions), base_url=BASE) as client:
        return Matrix(client, clock, password).run()


def time_verify(n: int, warmup: int, *, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """Per-call time of `SessionService.verify` for an accepted request: `warmup` calls, then `n` timed."""
    import os

    svc = SessionService(SessionConfig(password=PasswordParams(t=1, m_kib=64, p=1)), now=clock)  # the hash is not timed
    dev = Device(clock)
    login_url, url = _url("/v1/auth/login"), _url("/v1/read")
    password = os.urandom(12).hex()

    async def sign_in() -> str:
        assert (await svc.register("timing", password, ip="local")).status == "ok"
        result = await svc.login("timing", password, ip="local", method="POST", url=login_url,
                                 proofs=[dev.proof("POST", login_url)])
        assert result.tokens is not None
        return result.tokens.access_token

    access = asyncio.run(sign_in())
    svc.close()
    authorization = f"DPoP {access}"
    samples_ns: list[int] = []
    done, batch = 0, 500  # proofs are signed in batches so that none is older than the 60 s the server accepts
    while done < warmup + n:
        proofs = [[dev.proof("POST", url, access)] for _ in range(min(batch, warmup + n - done))]
        for proof in proofs:
            t0 = time.perf_counter_ns()
            verdict = svc.verify("POST", url, proof, authorization)
            t1 = time.perf_counter_ns()
            if not verdict.ok:
                raise RuntimeError(f"a valid request was refused: {verdict.failed}")
            if done >= warmup:
                samples_ns.append(t1 - t0)
            done += 1
    us = sorted(s / 1000 for s in samples_ns)
    q = statistics.quantiles(us, n=20) if len(us) >= 20 else [us[0]] * 19
    return {"what": "SessionService.verify, accepted request (DPoP proof + access token)",
            "clock": "time.perf_counter_ns", "n": len(us), "warmup": warmup,
            "median_us": round(statistics.median(us), 2), "p05_us": round(q[0], 2),
            "p95_us": round(q[18], 2), "min_us": round(us[0], 2), "max_us": round(us[-1], 2)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help=f"{QUICK_RUNS} timed calls instead of {RUNS}")
    ap.add_argument("--runs", type=int, default=None)
    ap.add_argument("--warmup", type=int, default=None)
    ap.add_argument("--out", default="runs", help="parent directory of the run dir")
    ap.add_argument("--results", default="results/session", help='where e5_matrix.json is copied ("" for nowhere)')
    a = ap.parse_args(argv)
    n = a.runs if a.runs is not None else (QUICK_RUNS if a.quick else RUNS)
    warmup = a.warmup if a.warmup is not None else (QUICK_WARMUP if a.quick else WARMUP)
    command = "python bench/run_session_matrix.py " + " ".join(argv if argv is not None else sys.argv[1:])
    backend = get_backend("numpy")
    run_dir = runs.new_run("M11", "session_matrix", step="S6", owner="Divyansh", command=command.strip(),
                           quick=a.quick, params={"runs": n, "warmup": warmup}, root=ROOT, runs_dir=a.out,
                           backend=backend)
    rows = run_matrix()
    passed = sum(1 for r in rows if r["as_expected"])
    timing = time_verify(n, warmup)
    matrix = {"experiment": "E5", "run_id": run_dir.name, "scenarios": len(rows), "as_expected": passed,
              "rows": rows}
    (run_dir / "e5_matrix.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    (run_dir / "verify_timing.json").write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
    summary = {"metrics": [
        {"id": PASS_METRIC, "value": f"{passed}/{len(rows)}", "unit": "scenarios", "stat": "as expected"},
        {"id": VERIFY_METRIC, "value": timing["median_us"], "unit": "us",
         "stat": f"median of {timing['n']} calls, CPU perf_counter"},
    ]}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if a.results:
        out = Path(a.results)
        out = out if out.is_absolute() else ROOT / out
        out.mkdir(parents=True, exist_ok=True)
        (out / "e5_matrix.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    ok = passed == len(rows)
    runs.finish_run(run_dir, status="OK" if ok else "UNSTABLE",
                    notes=("E5 matrix in-process (numpy simulator behind the API: correctness only). The verify "
                           "time is a host CPU measurement of the session layer; no GPU is involved."))
    for r in rows:
        print(f"{'ok  ' if r['as_expected'] else 'FAIL'} {r['id']:>2} {r['scenario']}: {r['observed']}")
    print(f"{PASS_METRIC} {passed}/{len(rows)}")
    print(f"{VERIFY_METRIC} median {timing['median_us']} us (p05 {timing['p05_us']}, p95 {timing['p95_us']}, "
          f"n={timing['n']})")
    print("run dir:", run_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
