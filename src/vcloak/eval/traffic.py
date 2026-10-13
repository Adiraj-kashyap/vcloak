"""Bursty conversation traffic, replayed through the service on a simulated clock (M14 S1).

`burst_events` is the traffic model of the seed oracle (`seed/vcloak_oracle.py`, `simulate_traffic`),
with the same draws in the same order: per conversation a first message after Exp(1/rate), then 70% of
the gaps are replies after Exp(2 s) and the others pauses of Exp(1/rate). The same generator state gives
the same events as the oracle.

`replay` posts every event to `POST /v1/messages` at its simulated arrival time and lets the scheduler
close one epoch after the other, so an arrival falls into the epoch its time belongs to. The backend must
have been built with `autorun=False`: with the free-running sim clock of `serve --clock sim` the arrival
time of a request would be whatever the loop had reached.

Ground truth (the arrival rank and the conversation of a row) stays in the `Replay` the evaluation holds.
A stored row is found again by the SHA-256 of its ciphertext; the server never sees the truth.

The conversation keys are derived from the public seed of the run. They are evaluation inputs, not
secrets, and they are never written anywhere.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from vcloak.crypto.client import derive_conv_token, encrypt_content
from vcloak.service.models import encode_payload

REPLY_PROB = 0.7  # share of gaps that are quick replies
REPLY_MEAN_S = 2.0
_KEY_LABEL = b"vcloak-eval-conversation:"


@dataclass(frozen=True)
class Event:
    t_ms: int  # simulated arrival time
    conv: int  # conversation index (evaluation only)
    seq: int  # position inside the conversation
    truth: int  # global arrival rank (evaluation only)


def burst_events(rng: np.random.Generator, n_conv: int, duration_s: float, rate: float) -> list[Event]:
    """The events of `n_conv` conversations over `duration_s` seconds, in arrival order."""
    if n_conv < 1 or duration_s <= 0 or rate <= 0:
        raise ValueError("n_conv, duration_s and rate must be positive")
    times: list[tuple[float, int]] = []
    for c in range(n_conv):
        t = rng.exponential(1 / rate)
        while t < duration_s:
            times.append((t, c))
            t += rng.exponential(REPLY_MEAN_S) if rng.random() < REPLY_PROB else rng.exponential(1 / rate)
    times.sort()
    seqs = [0] * n_conv
    events = []
    for rank, (t, c) in enumerate(times):
        events.append(Event(int(t * 1000), c, seqs[c], rank))
        seqs[c] += 1
    return events


def conversation_key(seed: int, conv: int) -> bytes:
    """K_content of evaluation conversation `conv`: a function of the public seed, not a secret."""
    return hashlib.sha256(_KEY_LABEL + f"{seed}:{conv}".encode()).digest()


def message_text(event: Event) -> bytes:
    return f"m{event.seq} conv{event.conv}".encode()


def digest(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()


@dataclass
class Replay:
    """What was sent, and what the evaluation needs to find it again."""
    seed: int
    events: list[Event]
    tokens: list[str]  # per conversation
    digests: list[bytes] = field(default_factory=list)  # per event: SHA-256 of the ciphertext
    refused: list[tuple[int, int]] = field(default_factory=list)  # (truth, HTTP status) of posts not accepted
    epochs: int = 0  # epoch boundaries passed

    @property
    def accepted(self) -> int:
        return len(self.digests) - len(self.refused)

    def by_digest(self) -> dict[bytes, Event]:
        return dict(zip(self.digests, self.events, strict=True))


async def replay(backend: Any, clock: Any, client: Any, events: Sequence[Event], *, seed: int,
                 duration_ms: int, epoch_ms: int) -> Replay:
    """Post `events` at their simulated times, epoch by epoch, then pass one more epoch so that the
    last window is closed. `client` is an httpx.AsyncClient of the app that serves `backend`."""
    if clock.now_ms() != 0:
        raise ValueError("the replay starts at simulated time 0")
    if duration_ms % epoch_ms:
        raise ValueError("the duration must be a whole number of epochs")
    n_conv = 1 + max((e.conv for e in events), default=0)
    keys = [conversation_key(seed, c) for c in range(n_conv)]
    out = Replay(seed, list(events), [derive_conv_token(k) for k in keys])
    scheduler = getattr(backend, "scheduler", None)  # the baseline has none: it stores at once
    i = 0
    for epoch in range(duration_ms // epoch_ms + 1):
        boundary = (epoch + 1) * epoch_ms
        while i < len(events) and events[i].t_ms < boundary:
            ev = events[i]
            clock.advance(ev.t_ms - clock.now_ms())
            payload = encrypt_content(keys[ev.conv], message_text(ev))
            r = await client.post("/v1/messages", json={"conv_token": out.tokens[ev.conv],
                                                        "payload_b64": encode_payload(payload)})
            out.digests.append(digest(payload))
            if r.status_code != 202:
                out.refused.append((ev.truth, r.status_code))
            i += 1
        if scheduler is not None:
            if await scheduler.run(1) != 1:
                raise RuntimeError("the scheduler did not close the epoch")
        else:
            clock.advance(boundary - clock.now_ms())
        out.epochs += 1
    if i != len(events):
        raise ValueError("an event lies outside the duration")
    return out
