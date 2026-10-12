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
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

WEB_DIR = Path(__file__).resolve().parents[3] / "web"  # the repository's web/ (an editable install)
MOUNT = "/app"

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
            "gpu": None,  # provenance of the compute backend: S6
        }
