"""The Logs view (M18 S5): `/v1/logs?kind=session|audit|metrics|issues&tail=N`, dev only.

The view tails the project's own record: the session log, the audit log, the metrics index and the issues.
The route never reads a path it is given: `kind` is one of four names, each bound here to one file of
`state/`, and the answer carries the kind, never the file's path. Every line passes `redact_line` first:

- an absolute file path (a drive letter, a home, a runner mount) becomes `<path>`; an e-mail address `<email>`
- `name=value` and `"name": "value"` for the names of `REDACT_NAMES` (conversation ids and tokens, buckets,
  sequence and row ids, credentials) keep the name and lose the value
- a JWT-shaped string becomes `<token>`; a run of 16 or more hex digits (64-bit conversation ids, digests,
  hex tokens) becomes `<hex>`, unless it is the digits of a decimal fraction
- a base64 or base64url run of 16 or more characters (tokens, ciphertexts, proofs) becomes `<b64>` unless every
  piece of it between `_`, `-`, `/`, `+`, `=` and `.` is word-shaped: lower case and digits (`live`, `e0e1`),
  upper case and digits (`M18`), a capitalised or CamelCase word (`ChaCha20Poly1305`). Run directories and file
  names are kept; a random token almost never splits into such pieces (tests/integration/test_logs_api.py).

This is a second layer. The state files are written by the build agent and scanned by check_secrets (G4); the
service's own log goes through `logsafe`. The answer counts the lines it changed, so the page can say so.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

STATE_DIR = Path(__file__).resolve().parents[3] / "state"  # the repository's state/ (an editable install)
KINDS: dict[str, str] = {
    "session": "SESSION_LOG.md",
    "audit": "AUDIT_LOG.md",
    "metrics": "METRICS_INDEX.md",
    "issues": "ISSUES.md",
}
TAIL_DEFAULT = 400
TAIL_MAX = 5000
LINE_MAX = 2000  # characters served of one line
NO_STORE = {"Cache-Control": "no-store"}

REDACT_NAMES = ("conv_id", "conv_token", "conv_hex", "conv", "bucket", "seq", "seq_enc", "seq_enc_b64",
                "row_id", "payload", "payload_b64", "token", "refresh_token", "access_token", "jti", "jkt",
                "dpop", "ticket", "passphrase", "password", "secret", "prekey_b64", "k_master", "k_tag",
                "k_seq", "k_bkt", "k_content")
_NAMES = "|".join(sorted(REDACT_NAMES, key=len, reverse=True))

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # absolute paths: C:\..., D:/..., \\server\..., /home/..., /Users/..., runner mounts, git-bash drives (/d/...)
    (re.compile(r"(?<![\w.])(?:[A-Za-z]:[\\/]|\\\\)[^\s`'\"<>|),;\]]*"), "<path>"),
    (re.compile(r"(?<![\w.~])/(?:home|Users|root|tmp|mnt|var|opt|usr|etc|kaggle|content|private|[a-z])/"
                r"[^\s`'\"<>|),;\]]*"), "<path>"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
    (re.compile(r"(\"(?:%s)\"\s*:\s*)\"[^\"]*\"" % _NAMES, re.I), r'\1"<redacted>"'),
    (re.compile(r"(?<![\w.])((?:%s)\s*=\s*)[^\s,;)\]}]+" % _NAMES, re.I), r"\1<redacted>"),
    (re.compile(r"eyJ[\w-]{4,}\.[\w-]{4,}(?:\.[\w-]*)?"), "<token>"),
    (re.compile(r"(?<![0-9A-Za-z.])[0-9A-Fa-f]{16,}(?![0-9A-Za-z.])"), "<hex>"),  # not a decimal fraction
)
_B64_RUN = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{16,}")
_WORD_SPLIT = re.compile(r"[_\-/+=.]")
# the pieces of a name a person typed: run, 20261014, e0e1, M18, E2E, S2S5, S6prep, Tesla, VCloak, NVreg,
# ChaCha20Poly1305, RestrictProfilingToAdminUsers
_WORD = re.compile(r"[a-z0-9]+|(?:[A-Z]+[0-9]*)+|[A-Z]+[0-9]*[a-z]+[0-9]*|(?:[A-Z]+[a-z]+[0-9]*)+")


_CASE_CHANGE = re.compile(r"(?=[a-z][A-Z]|[A-Z][a-z])")


def _wordlike(piece: str) -> bool:
    # CamelCase changes case about once in four characters (ChaCha20Poly1305: 4 in 16, RefKeys: 3 in 7); random
    # base64 more often
    return bool(_WORD.fullmatch(piece)) and 3 * len(_CASE_CHANGE.findall(piece)) <= len(piece) + 3


def _looks_random(run: str) -> bool:
    """A run of 16 or more base64(url) characters is a token unless every piece of it is word-shaped."""
    return not all(_wordlike(w) for w in _WORD_SPLIT.split(run) if w)


def redact_line(line: str) -> tuple[str, bool]:
    """The line as served, and whether a rule changed it."""
    out = line[:LINE_MAX]
    for rx, repl in _RULES:
        out = rx.sub(repl, out)
    out = _B64_RUN.sub(lambda m: "<b64>" if _looks_random(m.group(0)) else m.group(0), out)
    return out, out != line[:LINE_MAX]


def read_tail(kind: str, tail: int, state_dir: Path) -> dict[str, object]:
    path = state_dir / KINDS[kind]
    if not path.is_file():
        return {"kind": kind, "lines": [], "total": 0, "redacted": 0, "missing": True}
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lines, redacted = [], 0
    for raw in text[-tail:]:
        safe, changed = redact_line(raw)
        lines.append(safe)
        redacted += changed
    return {"kind": kind, "lines": lines, "total": len(text), "tail": tail, "redacted": redacted,
            "missing": False}


def add_logs_routes(app: FastAPI, *, dev: bool, state_dir: Path | None = None) -> None:
    root = STATE_DIR if state_dir is None else Path(state_dir)

    @app.get("/v1/logs")
    async def logs(kind: Literal["session", "audit", "metrics", "issues"] = Query(...),
                   tail: int = Query(TAIL_DEFAULT, ge=1, le=TAIL_MAX)) -> JSONResponse:
        if not dev:
            return JSONResponse({"error": "dev_only"}, status_code=403, headers=NO_STORE)
        return JSONResponse(read_tail(kind, tail, root), headers=NO_STORE)
