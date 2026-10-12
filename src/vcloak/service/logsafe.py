"""Application logging behind an allow-list (ai/CONVENTIONS.md §4). Initial version (M10); M11 finalises it.

A log line is an event name plus `key=value` fields. Only the keys of `ALLOWED` pass, and only with
values that cannot carry a secret: an int, a bool, or (for the keys of `TEXT_FIELDS`) a short
identifier. Anything else raises `ForbiddenLogField`, so a leak is a test failure, not a log line.

Never in a log line: conv_id, conv_token, bucket, seq, row_id, epoch numbers and any other timestamp
finer than 1 s, key material, tokens, DPoP proofs, payload bytes. The line's own timestamp has a
resolution of one second. Per-epoch events are not logged at all: with the line's timestamp they would
be an arrival record. The scheduler reports once per closed window.
"""
from __future__ import annotations

import logging
import re

ROOT_LOGGER = "vcloak"

# public values only: counts, coarse rounds, public parameters, states
ALLOWED: frozenset[str] = frozenset({
    "mode", "clock", "visible_round", "backend", "store",          # how the service was started
    "slots", "buckets", "window_s", "epoch_ms", "cand_k", "port",  # public parameters
    "win",                                                          # the coarse visible round (>= 1 s)
    "rows", "epochs", "overflow", "missed", "queued", "windows",    # public counters
    "status", "error", "dev_key", "ready",
})
TEXT_FIELDS: frozenset[str] = frozenset({"mode", "clock", "visible_round", "backend", "store", "status", "error"})
FORBIDDEN_EXAMPLES: tuple[str, ...] = ("conv_id", "conv_token", "bucket", "seq", "row_id", "epoch", "t_ms",
                                       "payload", "token", "dpop", "jti", "key", "passphrase")
_TEXT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,39}")
_EVENT_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
DATEFMT = "%Y-%m-%dT%H:%M:%S"  # one-second resolution: no milliseconds
FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class ForbiddenLogField(ValueError):
    """A log call used a field outside the allow-list, or a value that could carry a secret.
    The message names the field only, never its value."""


def check_fields(fields: dict[str, object]) -> None:
    for k, v in fields.items():
        if k not in ALLOWED:
            raise ForbiddenLogField(f"log field {k!r} is not on the allow-list")
        if isinstance(v, bool) or (isinstance(v, int) and not isinstance(v, bool)):
            continue
        if k in TEXT_FIELDS and isinstance(v, str) and _TEXT_RE.fullmatch(v):
            continue
        raise ForbiddenLogField(f"log field {k!r} has a value of a type or shape that is not allowed")


def render(event: str, fields: dict[str, object]) -> str:
    if not _EVENT_RE.fullmatch(event):
        raise ForbiddenLogField("the event name must be a short lower-case identifier")
    check_fields(fields)
    return " ".join([f"event={event}", *(f"{k}={fields[k]}" for k in sorted(fields))])


class SafeLogger:
    """The only logging surface of the service: `log.event("window_closed", win=3, rows=120)`."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    @property
    def name(self) -> str:
        return self._logger.name

    def event(self, event: str, *, level: int = logging.INFO, **fields: object) -> None:
        self._logger.log(level, render(event, fields))

    def warning(self, event: str, **fields: object) -> None:
        self.event(event, level=logging.WARNING, **fields)

    def failure(self, event: str, exc: BaseException, **fields: object) -> None:
        """An error by the class name of the exception only: its message may quote request data."""
        self.event(event, level=logging.ERROR, error=type(exc).__name__, **fields)


def get_logger(name: str = "service") -> SafeLogger:
    return SafeLogger(logging.getLogger(f"{ROOT_LOGGER}.{name}"))


def configure(level: int = logging.INFO) -> None:
    """Attach one stderr handler with the one-second timestamp to the `vcloak` logger (idempotent)."""
    root = logging.getLogger(ROOT_LOGGER)
    if not any(getattr(h, "_vcloak", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
        handler._vcloak = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
