#!/usr/bin/env python3
"""Secrets hygiene (global audit check G4, CLAUDE.md hard rule 4).

    python scripts/check_secrets.py                 scan the repository
    python scripts/check_secrets.py PATH [PATH...]  scan only these files or directories
    python scripts/check_secrets.py --allow ID --reason "why this is not a key"
    python scripts/check_secrets.py --allow-file PATH --reason "why this file holds no key"

A finding is any run that could be a 32-byte key: at least 64 hex characters, or at least 43 base64 or
base64url characters that mix digits, upper and lower case (so long identifiers and paths do not match).
The repository scan covers every tracked and untracked-but-not-ignored file, plus everything under
runs/, state/, logs/, gpujobs/ and evidence/ even when git ignores it. Binary files are not searched.

A run is accepted only when one of these holds:
  1. it is the SHA-256 of a scanned file (a digest the scanner can verify itself);
  2. the SHA-256 of the run is listed under "tokens" in scripts/secrets_allowlist.json;
  3. the file it sits in is listed under "files" there, with the file's current SHA-256.
The allow-list holds digests only, never the runs themselves. A finding is printed as path:line, kind,
length and ID (the SHA-256 of the run); the run itself is never printed, so this output is safe to log.
`secrets/` must not be tracked by git. Exit status: 0 clean, 1 findings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "scripts" / "secrets_allowlist.json"
ALWAYS_SCAN = ("runs", "state", "logs", "gpujobs", "evidence")  # scanned even when git ignores them
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
MIN_HEX = 64
MIN_B64 = 43

_PATTERNS = (
    ("hex", re.compile(rb"(?<![0-9A-Fa-f])[0-9A-Fa-f]{%d,}(?![0-9A-Fa-f])" % MIN_HEX), False),
    ("base64", re.compile(rb"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{%d,}" % MIN_B64), True),
    ("base64url", re.compile(rb"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{%d,}" % MIN_B64), True),
)
_CLASSES = (re.compile(rb"[0-9]"), re.compile(rb"[A-Z]"), re.compile(rb"[a-z]"))


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    length: int
    token_id: str  # SHA-256 of the run; the run itself is never kept

    def __str__(self) -> str:
        # the ID is printed in dashed groups so that a logged finding is not itself a key-like run
        dashed = "-".join(self.token_id[i:i + 8] for i in range(0, len(self.token_id), 8))
        return f"{self.path}:{self.line}  {self.kind}  len={self.length}  id={dashed}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _walk(top: Path) -> list[Path]:
    if top.is_file():
        return [top]
    return [p for p in top.rglob("*") if p.is_file() and not SKIP_DIRS.intersection(p.parts)]


def repo_files(root: Path = ROOT) -> list[Path]:
    """Tracked and untracked-but-not-ignored files, plus everything under ALWAYS_SCAN."""
    out = subprocess.run(["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"], cwd=root,
                         capture_output=True, check=True).stdout
    files = {root / name.decode("utf-8") for name in out.split(b"\0") if name}
    for d in ALWAYS_SCAN:
        files.update(_walk(root / d))
    return sorted(p for p in files if p.is_file())


def tracked_secrets(root: Path = ROOT) -> list[str]:
    """Paths under secrets/ that git tracks (there must be none)."""
    out = subprocess.run(["git", "ls-files", "-z", "--", "secrets"], cwd=root, capture_output=True, check=True)
    return [name.decode("utf-8") for name in out.stdout.split(b"\0") if name]


def load_allowlist(path: Path = ALLOWLIST) -> tuple[dict[str, str], set[str]]:
    """({relative file path: sha256}, {token ids}) from the allow-list file."""
    if not path.exists():
        return {}, set()
    doc = json.loads(path.read_text(encoding="utf-8"))
    return ({e["path"]: e["sha256"] for e in doc.get("files", [])},
            {e["sha256"] for e in doc.get("tokens", [])})


def scan(files: list[Path], *, root: Path = ROOT, allow_files: dict[str, str] | None = None,
         allow_tokens: set[str] | None = None) -> list[Finding]:
    """Every key-like run in `files` that no rule of the module docstring accepts."""
    allow_files, allow_tokens = allow_files or {}, allow_tokens or set()
    blobs = {p: p.read_bytes() for p in files}
    digests = {p: _sha256(data) for p, data in blobs.items()}
    verified = {d.encode("ascii") for d in digests.values()}
    findings: list[Finding] = []
    for p, data in blobs.items():
        rel = p.relative_to(root).as_posix() if p.is_relative_to(root) else p.as_posix()
        if b"\0" in data[:8192] or allow_files.get(rel) == digests[p]:
            continue
        seen: set[tuple[int, int]] = set()
        for kind, rx, mixed in _PATTERNS:
            for m in rx.finditer(data):
                tok = m.group()
                if m.span() in seen or (mixed and not all(c.search(tok) for c in _CLASSES)):
                    continue
                seen.add(m.span())
                if tok.lower() in verified or _sha256(tok) in allow_tokens:
                    continue
                findings.append(Finding(rel, data.count(b"\n", 0, m.start()) + 1, kind, len(tok), _sha256(tok)))
    return findings


def _add_entry(section: str, entry: dict[str, str]) -> None:
    doc = json.loads(ALLOWLIST.read_text(encoding="utf-8")) if ALLOWLIST.exists() else {}
    rows = [e for e in doc.get(section, []) if e.get("path", e["sha256"]) != entry.get("path", entry["sha256"])]
    doc[section] = sorted(rows + [entry], key=lambda e: (e.get("path", ""), e["sha256"]))
    doc.setdefault("files", [])
    doc.setdefault("tokens", [])
    ALLOWLIST.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="files or directories to scan instead of the repository")
    ap.add_argument("--allow", metavar="ID", help="accept the run with this finding ID everywhere")
    ap.add_argument("--allow-file", metavar="PATH", help="accept this file at its current content")
    ap.add_argument("--reason", default="", help="required with --allow and --allow-file")
    a = ap.parse_args(argv)

    if a.allow or a.allow_file:
        if not a.reason.strip():
            ap.error("--reason is required: say why this is not key material")
        if a.allow:
            token_id = a.allow.replace("-", "")
            if not re.fullmatch(r"[0-9a-f]{64}", token_id):
                ap.error("--allow takes the id= value of a finding")
            _add_entry("tokens", {"sha256": token_id, "reason": a.reason})
        if a.allow_file:
            target = Path(a.allow_file).resolve()
            _add_entry("files", {"path": target.relative_to(ROOT).as_posix(), "sha256": _sha256(target.read_bytes()),
                                 "reason": a.reason})
        print(f"updated {ALLOWLIST.relative_to(ROOT).as_posix()}")
        return 0

    allow_files, allow_tokens = load_allowlist()
    if a.paths:
        files, tracked = sorted({f for p in a.paths for f in _walk(Path(p).resolve())}), []
    else:
        files, tracked = repo_files(), tracked_secrets()
    # the allow-list is nothing but digests, and it is the one file that may list them
    files = [f for f in files if f != ALLOWLIST]
    findings = scan(files, allow_files=allow_files, allow_tokens=allow_tokens)
    for f in findings:
        print(f"KEY-LIKE: {f}")
    for t in tracked:
        print(f"TRACKED SECRET FILE: {t}")
    bad = len(findings) + len(tracked)
    print(f"check_secrets: {len(files)} files scanned, {len(findings)} key-like runs, "
          f"{len(tracked)} tracked files under secrets/ -> {'FAIL' if bad else 'PASS'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
