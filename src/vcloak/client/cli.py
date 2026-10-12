"""`vcloak-chat`: a terminal chat with one peer over a V-cloak service that runs with `--sessions`.

    vcloak-chat --server http://127.0.0.1:8000 --user alice --peer bob [--register] [--keyfile PATH]

Type a line to send it; `/quit` (or end of input) leaves. Messages of the peer are printed as they
are read. The client reads on a fixed schedule (`--poll`), whether or not anything arrived.

The account password is asked at a prompt (or taken from VCLOAK_CHAT_PASSWORD, which is removed from
the environment once read). It is sent to the server once, at login, and not kept.

**Where the device key is kept.** In memory, by default: a new ES256 key and a new prekey per run, so
a restarted client starts a new conversation key. With `--keyfile` both private keys are kept in a
file sealed with Argon2id + AES-256-GCM under a local passphrase (prompt, or VCLOAK_CHAT_PASSPHRASE);
the passphrase and the plaintext keys are never written anywhere.

Before trusting a conversation, compare the fingerprint this command prints with the one your peer
sees, over another channel: the server hands out the prekeys and could replace one (ADR-019).
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TextIO

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from vcloak.client.device import DeviceKey, load_keyfile, save_keyfile
from vcloak.client.sdk import ApiError, ClientError, SendUnconfirmed, SequenceError, TamperError, VcloakClient
from vcloak.crypto.keys import UnsealError

PASSWORD_ENV = "VCLOAK_CHAT_PASSWORD"
PASSPHRASE_ENV = "VCLOAK_CHAT_PASSPHRASE"
EXIT_INTEGRITY = 3  # the server returned a conversation that does not verify


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vcloak-chat", description="chat with one peer through V-cloak")
    ap.add_argument("--server", default="http://127.0.0.1:8000", help="the service URL (run it with --sessions)")
    ap.add_argument("--user", required=True, help="your account name")
    ap.add_argument("--peer", required=True, help="the account you talk to")
    ap.add_argument("--register", action="store_true", help="create the account first")
    ap.add_argument("--keyfile", default=None, help="keep the device key and the prekey in this sealed file")
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between two reads")
    ap.add_argument("--lookback", type=int, default=2, help="windows before the open one to read at the start")
    ap.add_argument("--wait", type=float, default=120.0, help="seconds to wait for the peer's prekey")
    return ap


def _secret(env: str, prompt: str, ask: Callable[[str], str]) -> str:
    value = os.environ.pop(env, None)
    return ask(prompt) if value is None else value


def device_keys(keyfile: str | None, ask: Callable[[str], str] = getpass.getpass
                ) -> tuple[DeviceKey, X25519PrivateKey]:
    """The keys of this device: fresh in memory, or from (and, when new, to) the sealed key file."""
    if keyfile is None:
        return DeviceKey(), X25519PrivateKey.generate()
    passphrase = _secret(PASSPHRASE_ENV, "Device key passphrase: ", ask)
    if Path(keyfile).exists():
        return load_keyfile(keyfile, passphrase)
    device, prekey = DeviceKey(), X25519PrivateKey.generate()
    save_keyfile(keyfile, passphrase, device, prekey)
    return device, prekey


def run_chat(client: VcloakClient, peer: str, lines: Iterable[str], out: TextIO, *, poll_s: float = 1.0,
             lookback: int = 2, wait_s: float = 120.0) -> int:
    """The chat loop of a logged-in client: publish the prekey, agree with `peer`, send `lines`, print
    what the peer says. Returns the exit code."""
    def say(text: str) -> None:
        print(text, file=out, flush=True)

    client.publish_prekey()
    say(f"waiting for the prekey of {peer} ...")
    peer_public = client.wait_for_prekey(peer, timeout_s=wait_s)
    first = max(0, int(client.windows()["win"]) - lookback)
    # a client that joins late has not seen the start of the peer's session: the first number it sees
    # is taken as given, every later one must follow
    conv = client.start_conversation(peer, first_win=first, strict_start=False, peer_prekey=peer_public)
    say(f"conversation with {peer} ready. Fingerprint (compare it with your peer): {conv.fingerprint}")

    lock, stop = threading.Lock(), threading.Event()
    failure: list[str] = []

    def show() -> None:
        with lock:
            for m in conv.sync():
                if not m.mine:
                    say(f"<{m.sender}> {m.text}")

    def reader() -> None:
        while not stop.is_set():
            try:
                show()
            except (SequenceError, TamperError) as e:
                failure.append(str(e))
                say(f"!! the server returned a conversation that does not verify: {e}")
                stop.set()
                return
            except (ClientError, OSError) as e:
                say(f"!! read failed ({type(e).__name__}); trying again")
            stop.wait(poll_s)

    thread = threading.Thread(target=reader, name="vcloak-chat-reader", daemon=True)
    thread.start()
    try:
        for line in lines:
            text = line.rstrip("\r\n")
            if stop.is_set() or text == "/quit":
                break
            if not text.strip():
                continue
            try:
                with lock:
                    conv.send(text)
            except SendUnconfirmed:
                say("!! not confirmed as stored; it will be sent again with your next message")
            except ValueError as e:
                say(f"!! {e}")
    finally:
        stop.set()
        thread.join(timeout=30)
    if failure:
        return EXIT_INTEGRITY
    try:
        show()
        conv.verify_delivered()
    except (SequenceError, TamperError) as e:
        say(f"!! the server returned a conversation that does not verify: {e}")
        return EXIT_INTEGRITY
    return 0


def main(argv: Sequence[str] | None = None, *, stdin: TextIO | None = None, stdout: TextIO | None = None,
         ask: Callable[[str], str] = getpass.getpass) -> int:
    a = build_parser().parse_args(argv)
    out = stdout or sys.stdout
    try:
        device, prekey = device_keys(a.keyfile, ask)
    except UnsealError as e:
        print(f"vcloak-chat: {e}", file=sys.stderr)
        return 2
    with VcloakClient(a.server, device=device, prekey=prekey) as client:
        password = _secret(PASSWORD_ENV, f"Password of {a.user}: ", ask)
        try:
            if a.register and not client.register(a.user, password):
                print(f"vcloak-chat: the name {a.user} is taken; logging in", file=out)
            client.login(a.user, password)
            del password
            code = run_chat(client, a.peer, stdin or sys.stdin, out, poll_s=a.poll, lookback=a.lookback,
                            wait_s=a.wait)
            client.logout()
            return code
        except ApiError as e:
            print(f"vcloak-chat: {e}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
