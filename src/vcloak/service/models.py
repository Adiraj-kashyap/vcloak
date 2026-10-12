"""Request and response bodies of the API (docs/API.md), and the token-to-conversation mapping.

The server never learns who talks to whom from these bodies: `conv_token` is an opaque handle the
client derives for its conversation (M12), and `payload_b64` is a client ciphertext of one fixed size.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vcloak.crypto.client import PAYLOAD_LEN
from vcloak.storage.repo import WIN_MAX

TOKEN_PATTERN = r"^[A-Za-z0-9_-]{16,128}$"  # base64url or hex text; at least 96 bits when random
_CONV_DOMAIN = b"vcloak-conv-id-v1\x00"

Mode = Literal["vcloak", "baseline"]
VisibleRound = Literal["window", "epoch"]


class PayloadError(ValueError):
    """`payload_b64` is not valid base64 or does not decode to exactly the ciphertext size."""


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageIn(_Body):
    payload_b64: str = Field(max_length=4 * ((PAYLOAD_LEN + 2) // 3) + 8)
    conv_token: str = Field(pattern=TOKEN_PATTERN)


class MessageAccepted(_Body):
    accepted: bool = True


class ReadIn(_Body):
    conv_token: str = Field(pattern=TOKEN_PATTERN)
    win: int = Field(ge=0, le=WIN_MAX)


class ReadOut(_Body):
    win: int
    payloads_b64: list[str]  # in conversation order


class WindowsOut(_Body):
    win: int  # the visible round new messages are being written to
    window_s: int
    epoch_ms: int
    visible_round: VisibleRound
    mode: Mode


class Health(_Body):
    status: Literal["ok"] = "ok"
    mode: Mode
    ready: bool
    epochs: int  # public counters of the scheduler (0 in baseline mode)
    overflow: int
    missed: int
    queued: int


def decode_payload(payload_b64: str, size: int = PAYLOAD_LEN) -> bytes:
    """The ciphertext bytes; every submission has exactly `size` bytes (nonce + BLOCK + tag)."""
    try:
        raw = base64.b64decode(payload_b64, validate=True)
    except (binascii.Error, ValueError):
        raise PayloadError("payload_b64 is not valid base64") from None
    if len(raw) != size:
        raise PayloadError(f"the payload must be exactly {size} bytes")
    return raw


def encode_payload(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def conv_id_of(conv_token: str) -> int:
    """The 64-bit conversation id the engine works with: a hash of the token (ADR-015)."""
    digest = hashlib.sha256(_CONV_DOMAIN + conv_token.encode("ascii")).digest()
    return int.from_bytes(digest[:8], "little")
