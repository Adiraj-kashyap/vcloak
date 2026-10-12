#!/usr/bin/env python3
"""Start `vcloak serve` as a real process and do one encrypted round trip over HTTP.

    python scripts/smoke_service.py [--mode vcloak|baseline] [--store sqlite|pg] [--port 8011] [--log FILE]
                                    [--sessions]

Two clients share a content key, one sends N messages through POST /v1/messages, the other reads the
conversation back with POST /v1/read and decrypts it. The server runs with `--dev` (the public
development key) on the wall clock. A correctness check only: nothing is timed.

With `--sessions` the server runs its session layer (M11): the client registers an account, logs in with
a device key, signs every request with a DPoP proof (tests/dpop_client.py), opens `/v1/ws` with a ticket
and counts the frames pushed, and logs out. The password is random and lives in this process only.
With `--log` too, the server's output is then searched for every token, ticket, proof id and conversation
token the client handled, and for per-connection lines.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(1, str(ROOT / "tests"))

from dpop_client import Device, decode_segment  # noqa: E402
from vcloak.crypto.client import decrypt_content, encrypt_content  # noqa: E402
from vcloak.service.models import decode_payload, encode_payload  # noqa: E402

WS_TICKS = 3  # frames to wait for on the socket


class Session:
    """The client side of `--sessions`: one device key, one login, a proof per request."""

    def __init__(self, client: httpx.Client, base: str) -> None:
        self.client, self.base, self.dev, self.access = client, base, Device(), ""
        self.handled: list[str] = [self.dev.jkt]  # what the server's log must not hold

    def proof(self, method: str, path: str, token: str | None = None) -> str:
        p = self.dev.proof(method, self.base + path, token)
        self.handled += [p.split(".")[2], decode_segment(p.split(".")[1])["jti"]]
        return p

    def sign_in(self) -> list[int]:
        name, password = "smoke_" + os.urandom(4).hex(), os.urandom(16).hex()
        body = {"username": name, "password": password}
        r1 = self.client.post("/v1/auth/register", json=body)
        path = "/v1/auth/login"
        r2 = self.client.post(path, json=body, headers={"DPoP": self.proof("POST", path)})
        self.access = r2.json().get("access_token", "")
        self.handled += [name, password, self.access, *self.access.split("."), r2.json().get("refresh_token", "")]
        return [r1.status_code, r2.status_code]

    def post(self, path: str, body: Any = None) -> httpx.Response:
        headers = {"DPoP": self.proof("POST", path, self.access), "Authorization": f"DPoP {self.access}"}
        return self.client.post(path, json=body, headers=headers)

    def ticket(self) -> str:
        ticket = self.post("/v1/auth/ws-ticket").json()["ticket"]
        self.handled.append(ticket)
        return ticket

    def leaks(self, log_text: str) -> list[str]:
        """What the server's output holds that it must not: handled values, and per-connection lines."""
        found = [f"handled value {i}" for i, v in enumerate(self.handled) if v and v in log_text]
        return found + [marker for marker in ("WebSocket", "connection open", "connection closed")
                        if marker in log_text]

    def socket_frames(self, n: int) -> list[dict[str, Any]]:
        """Open /v1/ws with a fresh ticket and return the first frame and the `n` pushed after it."""
        from websockets.sync.client import connect

        ticket = self.ticket()
        with connect(self.base.replace("http", "ws", 1) + "/v1/ws", open_timeout=10) as ws:
            ws.send(json.dumps({"ticket": ticket, "dpop": self.proof("GET", "/v1/ws")}))
            return [json.loads(ws.recv(timeout=10)) for _ in range(n + 1)]

    def socket_close_on_logout(self) -> tuple[int, int | None]:
        """Open a socket, log out, and return (the status of the logout, the close code the socket got)."""
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect

        ticket = self.ticket()
        with connect(self.base.replace("http", "ws", 1) + "/v1/ws", open_timeout=10) as ws:
            ws.send(json.dumps({"ticket": ticket, "dpop": self.proof("GET", "/v1/ws")}))
            ws.recv(timeout=10)
            status = self.post("/v1/auth/logout").status_code
            try:
                for _ in range(50):
                    ws.recv(timeout=10)
            except ConnectionClosed as e:
                return status, e.rcvd.code if e.rcvd else None
        return status, None


def wait_ready(client: httpx.Client, proc: subprocess.Popen[bytes], timeout_s: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"the server exited with code {proc.returncode}")
        try:
            r = client.get("/healthz")
            if r.status_code == 200 and r.json()["ready"]:
                return r.json()
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise RuntimeError("the server did not become ready")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("vcloak", "baseline"), default="vcloak")
    ap.add_argument("--store", choices=("sqlite", "pg"), default="sqlite")
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--messages", type=int, default=12)
    ap.add_argument("--log", default=None, help="write the server's output to this file")
    ap.add_argument("--sessions", action="store_true", help="run the server with its session layer and use it")
    a = ap.parse_args(argv)

    cmd = [sys.executable, "-m", "vcloak.cli", "serve", "--mode", a.mode, "--clock", "wall", "--dev",
           "--store", a.store, "--port", str(a.port), *(["--sessions"] if a.sessions else [])]
    base = f"http://127.0.0.1:{a.port}"
    checks: dict[str, bool] = {}
    session: Session | None = None
    conv = ""
    print("server:", " ".join(cmd[1:]))
    log = open(a.log, "wb") if a.log else subprocess.DEVNULL  # noqa: SIM115 - handed to the child process
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    try:
        with httpx.Client(base_url=base, timeout=10.0) as client:
            health = wait_ready(client, proc)
            print("healthz:", {k: health[k] for k in ("status", "mode", "ready")})
            session = Session(client, base) if a.sessions else None

            def post(path: str, body: Any) -> httpx.Response:
                return session.post(path, body) if session else client.post(path, json=body)

            if session:
                codes = session.sign_in()
                print("register, login:", codes)
                checks["register 201 and login 200"] = codes == [201, 200]
            k_content = os.urandom(32)  # the two clients' shared key; it never reaches the server
            conv = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
            texts = [f"message {i}".encode() for i in range(a.messages)]
            first = client.get("/v1/windows").json()
            for t in texts:
                r = post("/v1/messages", {"conv_token": conv,
                                          "payload_b64": encode_payload(encrypt_content(k_content, t))})
                assert r.status_code == 202, r.text
            print(f"sent: {len(texts)} messages, accepted")
            got: list[bytes] = []
            for _ in range(50):
                time.sleep(0.1)
                last = client.get("/v1/windows").json()["win"]
                got = []
                for win in range(first["win"], last + 1):
                    r = post("/v1/read", {"conv_token": conv, "win": win})
                    assert r.status_code == 200, r.text
                    got += [decrypt_content(k_content, decode_payload(p)) for p in r.json()["payloads_b64"]]
                if len(got) == len(texts):
                    break
            ok = got == texts
            print(f"read: {len(got)} messages, decrypted, in order: {ok}")
            bad = post("/v1/messages", {"conv_token": conv, "payload_b64": encode_payload(b"short")})
            print("wrong payload size:", bad.status_code, bad.json()["error"])
            stats = client.get("/healthz").json()
            print("counters present:", sorted(k for k in stats if k not in ("status", "mode", "ready")))
            ok = ok and bad.status_code == 422
            if session:
                r = client.post("/v1/read", json={"conv_token": conv, "win": first["win"]})
                print("read without a session:", r.status_code, r.json().get("failed_check"))
                checks["a request without a proof is refused 401"] = r.status_code == 401
                frames = session.socket_frames(WS_TICKS)
                kinds = [f.get("type") for f in frames]
                print(f"socket: {kinds[0]} and {kinds.count('tick')} pushed frames, keys {sorted(frames[-1])}")
                checks["the socket opens with a ticket and is pushed to"] = (
                    kinds == ["ready"] + ["tick"] * WS_TICKS and all(set(f) == {"type", "win"} for f in frames))
                status, code = session.socket_close_on_logout()
                print("logout:", status, "socket closed with", code)
                checks["logout answers 204 and closes the socket with 4001"] = (status, code) == (204, 4001)
                r = session.post("/v1/read", {"conv_token": conv, "win": first["win"]})
                print("read after logout:", r.status_code, r.json().get("failed_check"))
                checks["the token is refused after logout"] = (
                    r.status_code == 401 and r.json().get("failed_check") == "token_revoked")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        if a.log:
            log.close()  # type: ignore[union-attr]
    if session:
        if a.log:
            text = Path(a.log).read_text(encoding="utf-8", errors="replace")
            leaks = session.leaks(text) + (["the conversation token"] if conv in text else [])
            print(f"server log: {len(text.splitlines())} lines searched for {len(session.handled) + 1} handled "
                  f"values, found {leaks or 'none'}")
            checks["the server log holds no handled value and no connection line"] = (
                not leaks and "event=serve" in text)
        for name, held in checks.items():
            print("PASS" if held else "FAIL", name)
        ok = ok and len(checks) == (6 if a.log else 5) and all(checks.values())
    print("SMOKE", "PASS" if ok else "FAIL", f"mode={a.mode} store={a.store} sessions={a.sessions}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
