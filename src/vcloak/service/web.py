"""The web app (M13): the static files of `web/` at `/app`, and what the page asks the service about itself.

The page is plain files (ADR-012): classic scripts, one stylesheet, nothing from another origin. Every
answer under `/app` carries a Content-Security-Policy that allows exactly that:

- scripts, stylesheets, fetches and sockets only from this origin, so an injected `<script>` or an
  inline handler does not run and nothing can be sent to another host;
- no plugins, no `<base>`, no framing, no form posts.

`style-src-attr 'unsafe-inline'` is the one relaxation: the charts of the prototype position marks with
`style=` attributes (ISSUE-29). It allows no script and no stylesheet. `img-src data:` is the icon in the
shell.

`GET /v1/stats/live` is open like `/v1/windows`: public parameters and the public counters of `/healthz`,
plus what the page needs to decide how to run (`dev`, `sessions`, the payload size).

`GET /v1/dump` is the "what the server stores" panel: the rows of the newest windows exactly as the store
holds them, in physical order. It exists with `--dev` only and answers 403 otherwise. It hands out what
a copy of the database holds and nothing else: no key is used to build it, so it cannot say which row is
which message. The page finds that out from its own clients.

`GET /v1/mode` says which backend answers and whether it can be changed; `POST /v1/mode` changes it. Only
`serve --dev --compare` can (service/switch.py, ADR-022): 403 without `--dev`, 409 with `--dev` alone.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

WEB_DIR = Path(__file__).resolve().parents[3] / "web"  # the repository's web/ (an editable install)
MOUNT = "/app"
DUMP_LIMIT, DUMP_LIMIT_MAX = 50, 500  # rows of one answer
DUMP_WINDOWS, DUMP_WINDOWS_MAX = 4, 64  # windows looked at, the open one included

CSP = "; ".join((
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "style-src-attr 'unsafe-inline'",
    "img-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'none'",
))


class ModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["vcloak", "baseline"]


def page_headers(dev: bool) -> dict[str, str]:
    """The headers of every answer under /app. In dev nothing is cached: the page on screen is the page on disk."""
    return {
        "Content-Security-Policy": CSP,
        "Cache-Control": "no-store" if dev else "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Opener-Policy": "same-origin",
    }


class PageHeaders:
    """ASGI middleware: the headers of `page_headers` on every answer under /app, whoever produced it
    (a file, the redirect of `/app` to `/app/`, a 404)."""

    def __init__(self, app: ASGIApp, *, dev: bool) -> None:
        self._app = app
        self._headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in page_headers(dev).items()]
        self._names = {k for k, _ in self._headers}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == MOUNT or path.startswith(MOUNT + "/")):
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in self._names]
                message = {**message, "headers": kept + self._headers}
            await send(message)

        await self._app(scope, receive, send_with_headers)


def mount_web(app: FastAPI, web_dir: Path | None = None, *, dev: bool = False) -> bool:
    """Serve `web_dir` at /app. False (and no mount) when the directory holds no shell."""
    root = WEB_DIR if web_dir is None else Path(web_dir)
    if not (root / "index.html").is_file():
        return False
    app.mount(MOUNT, StaticFiles(directory=str(root), html=True), name="web")
    app.add_middleware(PageHeaders, dev=dev)
    return True


def add_live_routes(app: FastAPI, backend: Any, *, dev: bool, sessions: bool, payload_len: int) -> None:
    # the mode can change only on the comparison backend, and that one is offered in dev only
    switchable = dev and bool(getattr(backend, "switchable", False))
    no_store = {"Cache-Control": "no-store"}

    @app.get("/v1/mode")
    async def get_mode() -> JSONResponse:
        return JSONResponse({"mode": backend.mode, "switchable": switchable}, headers=no_store)

    @app.post("/v1/mode")
    async def post_mode(body: ModeIn) -> JSONResponse:
        if not dev:
            return JSONResponse({"error": "dev_only"}, status_code=403, headers=no_store)
        if not switchable:
            return JSONResponse({"error": "not_switchable"}, status_code=409, headers=no_store)
        backend.set_mode(body.mode)
        return JSONResponse({"mode": backend.mode, "switchable": True}, headers=no_store)

    @app.get("/v1/stats/live")
    async def stats_live() -> dict[str, Any]:
        stats = backend.stats()
        return {
            "mode": backend.mode,
            "dev": dev,
            "sessions": sessions,
            "win": backend.current_window(),
            "window_s": backend.window_s,
            "epoch_ms": backend.epoch_ms,
            "slots": getattr(backend, "slots", None),  # the baseline has no epochs to fill
            "queued": stats["queued"],
            "epochs": stats["epochs"],
            "payload_len": payload_len,
            "switchable": switchable,
            "gpu": None,  # provenance of the compute backend: S6
        }

    if not dev:
        @app.get("/v1/dump")
        async def dump_refused() -> JSONResponse:
            return JSONResponse({"error": "dev_only"}, status_code=403, headers={"Cache-Control": "no-store"})
        return

    def b64(raw: bytes | None) -> str | None:
        return None if raw is None else base64.b64encode(raw).decode("ascii")

    @app.get("/v1/dump")
    async def dump(limit: int = Query(DUMP_LIMIT, ge=1, le=DUMP_LIMIT_MAX),
                   windows: int = Query(DUMP_WINDOWS, ge=1, le=DUMP_WINDOWS_MAX)) -> JSONResponse:
        stored = await backend.stored(windows)
        # the newest rows win the limit; a window that does not fit whole loses its tail
        kept: list[dict[str, Any]] = []
        room = limit
        for w in reversed(stored):
            kept.append({**w, "rows": w["rows"][:room]})
            room -= len(kept[-1]["rows"])
        kept.reverse()
        # `ts` and `conv_hex` are columns of the baseline table only: V-cloak rows have neither
        rows = [{"pos": pos, "win": w["win"], "row_id": r["row_id"], "bucket": r["bucket"],
                 "seq_enc_b64": b64(r["seq_enc"]), "payload_b64": b64(r["payload"]),
                 "ts": r.get("ts"), "conv_hex": r["conv"].hex() if r.get("conv") is not None else None}
                for pos, (w, r) in enumerate((w, r) for w in kept for r in w["rows"])]
        total = sum(len(w["rows"]) for w in stored)
        body = {"mode": backend.mode, "visible_round": backend.visible_round, "win": backend.current_window(),
                "windows": [{"win": w["win"], "state": w["state"], "rows": len(w["rows"])} for w in stored],
                "total": total, "truncated": total > len(rows), "rows": rows}
        return JSONResponse(body, headers={"Cache-Control": "no-store"})
