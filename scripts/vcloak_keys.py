#!/usr/bin/env python3
"""Create or re-seal the sealed master key (ADR-007).

    python scripts/vcloak_keys.py init   [--path secrets/k_master.sealed]   new K_master under a new passphrase
    python scripts/vcloak_keys.py rotate [--path secrets/k_master.sealed]   same K_master under a new passphrase

The passphrase is read with getpass and is never an argument, an environment variable or an output.
K_master is never printed or written in plaintext. `rotate` changes the passphrase, salt and nonce only:
replacing K_master itself would orphan every stored row, so `init` refuses to overwrite an existing file.
If the passphrase is lost, the sealed file cannot be opened and the stored order is unrecoverable.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak.crypto import keys  # noqa: E402

DEFAULT_PATH = ROOT / "secrets" / "k_master.sealed"


def _new_passphrase(ask: Callable[[str], str]) -> str:
    first = ask("New passphrase: ")
    if not first:
        raise SystemExit("error: the passphrase must not be empty")
    if ask("Repeat passphrase: ") != first:
        raise SystemExit("error: the passphrases do not match")
    return first


def main(argv: list[str] | None = None, ask: Callable[[str], str] = getpass.getpass) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("init", "rotate"))
    ap.add_argument("--path", type=Path, default=DEFAULT_PATH, help="the sealed key file")
    a = ap.parse_args(argv)

    if a.command == "init":
        if a.path.exists():
            print(f"error: {a.path} already exists; use `rotate` to change its passphrase", file=sys.stderr)
            return 1
        keys.create_sealed_master(a.path, _new_passphrase(ask))
        print(f"sealed master key written to {a.path} ({keys.SEALED_LEN} bytes)")
        return 0

    if not a.path.exists():
        print(f"error: {a.path} does not exist; run `init` first", file=sys.stderr)
        return 1
    current = ask("Current passphrase: ")
    try:
        keys.zeroize(keys.unseal_master(a.path, current))  # fail before asking for the new one
    except keys.UnsealError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    keys.reseal_master(a.path, current, _new_passphrase(ask))
    print(f"sealed master key at {a.path} re-sealed under the new passphrase")
    return 0


if __name__ == "__main__":
    sys.exit(main())
