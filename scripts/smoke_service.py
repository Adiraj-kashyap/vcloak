#!/usr/bin/env python3
"""Start `vcloak serve` as a real process and do one encrypted round trip over HTTP.

    python scripts/smoke_service.py [--mode vcloak|baseline] [--store sqlite|pg] [--port 8011] [--log FILE]

Two clients share a content key, one sends N messages through POST /v1/messages, the other reads the
conversation back with POST /v1/read and decrypts it. The server runs with `--dev` (the public
development key) on the wall clock. A correctness check only: nothing is timed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak.crypto.client import decrypt_content, encrypt_content  # noqa: E402
from vcloak.service.models import decode_payload, encode_payload  # noqa: E402


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
    a = ap.parse_args(argv)

    cmd = [sys.executable, "-m", "vcloak.cli", "serve", "--mode", a.mode, "--clock", "wall", "--dev",
           "--store", a.store, "--port", str(a.port)]
    print("server:", " ".join(cmd[1:]))
    log = open(a.log, "wb") if a.log else subprocess.DEVNULL  # noqa: SIM115 - handed to the child process
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{a.port}", timeout=10.0) as client:
            health = wait_ready(client, proc)
            print("healthz:", {k: health[k] for k in ("status", "mode", "ready")})
            k_content = os.urandom(32)  # the two clients' shared key; it never reaches the server
            conv = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
            texts = [f"message {i}".encode() for i in range(a.messages)]
            first = client.get("/v1/windows").json()
            for t in texts:
                r = client.post("/v1/messages", json={"conv_token": conv,
                                                      "payload_b64": encode_payload(encrypt_content(k_content, t))})
                assert r.status_code == 202, r.text
            print(f"sent: {len(texts)} messages, accepted")
            got: list[bytes] = []
            for _ in range(50):
                time.sleep(0.1)
                last = client.get("/v1/windows").json()["win"]
                got = []
                for win in range(first["win"], last + 1):
                    r = client.post("/v1/read", json={"conv_token": conv, "win": win})
                    assert r.status_code == 200, r.text
                    got += [decrypt_content(k_content, decode_payload(p)) for p in r.json()["payloads_b64"]]
                if len(got) == len(texts):
                    break
            ok = got == texts
            print(f"read: {len(got)} messages, decrypted, in order: {ok}")
            bad = client.post("/v1/messages", json={"conv_token": conv, "payload_b64": encode_payload(b"short")})
            print("wrong payload size:", bad.status_code, bad.json()["error"])
            stats = client.get("/healthz").json()
            print("counters present:", sorted(k for k in stats if k not in ("status", "mode", "ready")))
            ok = ok and bad.status_code == 422
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        if a.log:
            log.close()  # type: ignore[union-attr]
    print("SMOKE", "PASS" if ok else "FAIL", f"mode={a.mode} store={a.store}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
