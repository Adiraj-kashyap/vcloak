#!/usr/bin/env python3
"""Two users chat through a live V-cloak service, then the stored rows are shown (M12 S4).

    python scripts/demo_two_users.py [--store pg|sqlite] [--messages 30] [--window-s 2] [--epoch-ms 200]
                                     [--seed 0] [--quick] [--out RUNS_DIR]

The service runs in this process (uvicorn on a loopback port, the session layer on, `--dev` key, wall
clock). Alice and Bob are two `VcloakClient`s (src/vcloak/client/sdk.py): each registers, logs in with
its own device key, publishes a prekey, derives the content key and the conversation token, and they
send alternately with `ack: "stored"`. Both then read the conversation back and verify its order.

After the last window has closed, the store is dumped in physical order. The server holds no key that
opens a payload; the column `message` is filled in *here*, by Alice's client, to show which message
sits where.

A correctness demonstration: nothing is timed. The engine behind the service is the backend this
machine has (numpy on the laptop), which says nothing about performance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import runs  # noqa: E402
from vcloak.cli import build_backend, build_parser  # noqa: E402
from vcloak.client.sdk import ClientError, Message, VcloakClient  # noqa: E402
from vcloak.service.app import create_app  # noqa: E402
from vcloak.service.session import SessionConfig, SessionService  # noqa: E402

PHRASES = ("are you there?", "yes, go on", "the build is green", "send me the figure", "which window was that?",
           "reading it now", "the epoch closed", "same here", "one more check", "agreed", "see the log",
           "that row moved", "try again", "it decrypts", "nothing leaked", "done on my side")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class LocalServer:
    """`vcloak serve <argv>` with sessions, inside this process: a real HTTP server on a loopback port,
    with the backend and the store reachable for inspection after it stopped."""

    def __init__(self, argv: list[str], *, config: SessionConfig | None = None) -> None:
        import uvicorn

        a = build_parser().parse_args(["serve", *argv])
        self.backend: Any = build_backend(a)
        self.sessions = SessionService(config or SessionConfig())
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        app = create_app(self.backend, sessions=self.sessions)
        self._server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, access_log=False,
                                                     log_config=None, log_level="warning"))
        self._thread = threading.Thread(target=self._server.run, name="vcloak-demo-server", daemon=True)

    def start(self, timeout_s: float = 30.0) -> LocalServer:
        self._thread.start()
        deadline = time.monotonic() + timeout_s
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the server did not start")
            time.sleep(0.02)
        return self

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=30)

    def __enter__(self) -> LocalServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def sign_in(base: str, name: str) -> VcloakClient:
    """A client with a fresh device key, registered and logged in under a random password that lives
    in this process only, with its prekey published."""
    client = VcloakClient(base)
    password = os.urandom(16).hex()
    client.register(name, password)
    client.login(name, password)
    client.publish_prekey()
    return client


def chat(base: str, n: int, seed: int) -> dict[str, Any]:
    """Alice and Bob exchange `n` messages; returns what was sent and what each read back."""
    rng = random.Random(seed)
    alice, bob = sign_in(base, "alice"), sign_in(base, "bob")
    conv_a = alice.start_conversation("bob")
    conv_b = bob.start_conversation("alice", first_win=conv_a.first_win)
    sent: list[tuple[str, str]] = []
    for i in range(n):
        who = alice if i % 2 == 0 else bob
        text = f"[{i:02d}] {rng.choice(PHRASES)}"
        who.send(text)
        sent.append((who.username, text))
    return {"alice": alice, "bob": bob, "sent": sent, "first_win": conv_a.first_win,
            "fingerprints": (conv_a.fingerprint, conv_b.fingerprint)}


def wait_closed(client: VcloakClient, win: int, epoch_ms: int, timeout_s: float = 60.0) -> None:
    """Wait until window `win` has closed and the epochs that re-shuffle it have passed."""
    deadline = time.monotonic() + timeout_s
    while int(client.windows()["win"]) <= win:
        if time.monotonic() > deadline:
            raise RuntimeError("the window did not close")
        time.sleep(0.1)
    time.sleep(5 * epoch_ms / 1000)


def describe_rows(rows: list[Any], reader: VcloakClient) -> list[dict[str, Any]]:
    """One line per stored row in physical order. `message` comes from the client's key, not the store."""
    conv = reader.conversation
    assert conv is not None
    out = []
    for pos, row in enumerate(rows):
        try:
            sender, _, number, text = conv.open(bytes(row.payload))
            who, label = ("alice", "bob")[sender != conv.role], text
        except ClientError:
            who, number, label = "?", -1, "(not of this conversation)"
        out.append({"pos": pos, "win": int(row.win), "bucket": int(row.bucket), "row_id": str(row.row_id)[:8],
                    "payload_len": len(row.payload), "payload_sha256": hashlib.sha256(row.payload).hexdigest()[:12],
                    "sender": who, "number": number, "message": label})
    return out


def run_demo(store: str = "sqlite", n: int = 30, window_s: int = 2, epoch_ms: int = 200, seed: int = 0, *,
             config: SessionConfig | None = None) -> dict[str, Any]:
    """The whole demonstration; returns the transcripts, the rows and the checks."""
    schema = "demo_" + uuid.uuid4().hex[:12]
    argv = ["--dev", "--sessions", "--store", store, "--window-s", str(window_s), "--epoch-ms", str(epoch_ms)]
    server = LocalServer(argv + (["--schema", schema] if store == "pg" else []), config=config)
    repo = server.backend.repo
    try:
        with server:
            c = chat(server.base, n, seed)
            alice, bob = c["alice"], c["bob"]
            last_win = int(alice.windows()["win"])
            wait_closed(alice, last_win, epoch_ms)
            views: dict[str, list[Message]] = {"alice": alice.sync(), "bob": bob.sync()}
            for who in (alice, bob):
                assert who.conversation is not None
                who.conversation.verify_delivered()
            engine = server.backend.keys.backend.name
        rows = repo.dump()  # the server has stopped: nothing else uses the store
        pending = repo.pending_windows()
        table = describe_rows(rows, alice)
    finally:
        if store == "pg":
            repo.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        repo.close()

    sent_texts = [t for _, t in c["sent"]]
    stored_order = [r["message"] for r in table]
    blob = b"".join(bytes(r.payload) for r in rows)
    checks = {
        "alice reads every message, in the order sent": [m.text for m in views["alice"]] == sent_texts,
        "bob reads every message, in the order sent": [m.text for m in views["bob"]] == sent_texts,
        "each message is attributed to its sender": all(
            [(m.sender, m.text) for m in v] == c["sent"] for v in views.values()),
        "both ends derived the same fingerprint": c["fingerprints"][0] == c["fingerprints"][1],
        "the conversation spans at least 2 windows": len({m.win for m in views["alice"]}) >= 2,
        "the store holds one row per message": len(rows) == n,
        "every stored payload has the one fixed size": len({len(r.payload) for r in rows}) == 1,
        "no stored payload contains a message text": not any(t.encode() in blob for t in sent_texts),
        "every closed window was re-shuffled": pending == [],
        "the physical order is not the order sent": stored_order != sent_texts,
    }
    return {"store": store, "engine": engine, "messages": n, "window_s": window_s, "epoch_ms": epoch_ms,
            "sent": c["sent"], "views": views, "rows": table, "checks": checks,
            "windows": sorted({m.win - c["first_win"] for m in views["alice"]}),
            "repeats": sum(v.conversation.repeats for v in (alice, bob) if v.conversation), "first_win": c["first_win"]}


def render(result: dict[str, Any]) -> tuple[str, str]:
    """(transcript, rows) as text."""
    t = [f"V-cloak two-user demo: {result['messages']} messages, store={result['store']}, "
         f"WINDOW_S={result['window_s']}, EPOCH_MS={result['epoch_ms']}, engine backend={result['engine']}",
         "service: in-process uvicorn on loopback, sessions on, public development key (--dev)", ""]
    for name, view in result["views"].items():
        t.append(f"--- what {name} reads back ({len(view)} messages, windows counted from the first) ---")
        for m in view:
            t.append(f"  w+{m.win - result['first_win']}  {m.sender:>5} #{m.number:<2} {m.text}")
        t.append("")
    r = ["Stored rows in physical order. The store holds row_id, bucket, win, seq_enc and payload only;",
         "`sender`, `#` and `message` are decrypted here by Alice's client and are unknown to the server.", "",
         f"{'pos':>3}  {'win':>4}  {'bucket':>6}  {'row_id':8}  {'payload':>7}  {'sha256':12}  {'sender':>6} {'#':>2}"
         "  message"]
    for row in result["rows"]:
        r.append(f"{row['pos']:>3}  w+{row['win'] - result['first_win']:<2}  {row['bucket']:>6}  {row['row_id']:8}  "
                 f"{row['payload_len']:>7}  {row['payload_sha256']:12}  {row['sender']:>6} {row['number']:>2}  "
                 f"{row['message']}")
    return "\n".join(t) + "\n", "\n".join(r) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", choices=("pg", "sqlite"), default="pg")
    ap.add_argument("--messages", type=int, default=30)
    ap.add_argument("--window-s", type=int, default=2, help="a short window, so that the chat crosses several")
    ap.add_argument("--epoch-ms", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0, help="selects the message texts")
    ap.add_argument("--quick", action="store_true", help="12 messages and 1 s windows")
    ap.add_argument("--out", default=None, help="parent directory of the run dir (default: runs/)")
    a = ap.parse_args(argv)
    n, window_s = (12, 1) if a.quick else (a.messages, a.window_s)

    params = {"store": a.store, "messages": n, "window_s": window_s, "epoch_ms": a.epoch_ms}
    run_dir = runs.new_run("M12", "demo_two_users", step="S4", owner="Abhishek", seed=a.seed, quick=a.quick,
                           command="python scripts/demo_two_users.py " + " ".join(argv or sys.argv[1:]),
                           params=params, root=ROOT, runs_dir=a.out)
    try:
        result = run_demo(a.store, n, window_s, a.epoch_ms, a.seed)
    except Exception as e:  # noqa: BLE001 - the run dir records the failure
        runs.finish_run(run_dir, status="FAIL", notes=f"the demo raised {type(e).__name__}")
        raise
    transcript, rows = render(result)
    (run_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    (run_dir / "rows.txt").write_text(rows, encoding="utf-8")
    ok = all(result["checks"].values())
    summary = {**params, "engine_backend": result["engine"], "windows_used": result["windows"],
               "repeats_dropped": result["repeats"], "checks": result["checks"], "result": "PASS" if ok else "FAIL"}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    runs.finish_run(run_dir, status="OK" if ok else "FAIL",
                    notes="two-user round trip, correctness only: nothing timed, engine backend "
                          f"{result['engine']} (not a performance result)")
    print(transcript)
    print(rows)
    for name, held in result["checks"].items():
        print("PASS" if held else "FAIL", name)
    print("DEMO", "PASS" if ok else "FAIL", f"store={a.store} messages={n} windows={len(result['windows'])}",
          "->", run_dir.relative_to(ROOT).as_posix() if run_dir.is_relative_to(ROOT) else run_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
