"""The comparison backend of `serve --dev --compare` (M13 S5, ADR-022): V-cloak and the baseline side by side.

Every accepted message is written to both stores, the permuted one and the arrival-order table, and the
routes are answered from the one `POST /v1/mode` selected. So the same conversation can be dumped both
ways, and the only thing that differs between the two panels is how the server laid the rows out.

This is a demonstration device and nothing else: the baseline table holds the order, the time and the
conversation of every message, which is exactly what V-cloak exists to withhold. `serve` builds it only
with `--dev` (the public key, a throw-away store, a loopback host). No measurement runs on it: the
second write is on the path of every message.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from vcloak.service.logsafe import SafeLogger, get_logger

MODES = ("vcloak", "baseline")


class SwitchBackend:
    """A `ServiceBackend` (app.py) over two: `vcloak` and `baseline`, one of them active."""

    switchable = True

    def __init__(self, vcloak: Any, baseline: Any, *, mode: str = "vcloak", log: SafeLogger | None = None) -> None:
        if (vcloak.window_s, vcloak.epoch_ms) != (baseline.window_s, baseline.epoch_ms):
            raise ValueError("the two backends must share window_s and epoch_ms")
        if vcloak.visible_round != "window":
            raise ValueError("the comparison needs --visible-round window: the baseline has no epoch rounds")
        self.vcloak, self.baseline = vcloak, baseline
        self.window_s, self.epoch_ms = vcloak.window_s, vcloak.epoch_ms
        self._log = log or get_logger("switch")
        self._active: Any = None
        self.set_mode(mode, quiet=True)

    # ── which one answers ────────────────────────────────────────────────────
    @property
    def mode(self) -> str:
        return str(self._active.mode)

    def set_mode(self, mode: str, *, quiet: bool = False) -> str:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self._active = self.vcloak if mode == "vcloak" else self.baseline
        if not quiet:
            self._log.event("mode_switched", mode=mode)
        return mode

    @property
    def visible_round(self) -> str:
        return str(self._active.visible_round)

    @property
    def slots(self) -> int | None:
        return getattr(self._active, "slots", None)  # the baseline has no epochs to fill

    @property
    def ready(self) -> bool:
        return bool(self.vcloak.ready and self.baseline.ready)

    def current_window(self) -> int:
        return int(self.vcloak.current_window())  # one clock, one window_s: the same window in both

    def on_epoch(self, listener: Callable[[], None]) -> None:
        self.vcloak.on_epoch(listener)  # the scheduler runs in either mode: one cadence for the sockets

    # ── both ─────────────────────────────────────────────────────────────────
    async def start(self) -> None:
        await self.vcloak.start()
        try:
            await self.baseline.start()
        except BaseException:
            await self.vcloak.stop()
            raise
        self._log.event("started", mode=self.mode, window_s=self.window_s)

    async def stop(self) -> None:
        try:
            await self.baseline.stop()
        finally:
            await self.vcloak.stop()

    async def submit(self, conv_token: str, payload: bytes, *, stored: bool = False) -> None:
        """One message into both stores. The scheduler is asked first, because only it can refuse (a full
        queue): a refused message reaches neither. The baseline row is inserted as soon as the message is
        queued, so that table is in the order of arrival whatever acknowledgement the sender waits for."""
        queued = asyncio.ensure_future(self.vcloak.submit(conv_token, payload, stored=stored))
        await asyncio.sleep(0)  # the scheduler has taken it, or refused it
        if queued.done():
            queued.result()
        try:
            await self.baseline.submit(conv_token, payload, stored=stored)
        finally:
            await queued

    # ── the active one ───────────────────────────────────────────────────────
    async def read(self, conv_token: str, win: int) -> list[bytes]:
        return list(await self._active.read(conv_token, win))

    def stats(self) -> dict[str, int]:
        return dict(self._active.stats())

    def live(self) -> dict[str, Any]:
        return dict(self._active.live())

    async def stored(self, windows: int) -> list[dict[str, Any]]:
        return list(await self._active.stored(windows))
