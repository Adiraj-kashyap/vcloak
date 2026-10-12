"""The HTTP service (docs/API.md): four routes over one of two backends, and the session routes.

    POST /v1/messages   queue one client ciphertext for the open epoch (`ack: stored` waits for the write)
    POST /v1/read       the payloads of one conversation in one visible round, in order
    GET  /v1/windows    the visible round being written now
    GET  /healthz       liveness and the scheduler's public counters
    POST /v1/auth/register | login | refresh | logout | ws-ticket   (only with `sessions`, M11)
    PUT  /v1/prekeys    publish the public X25519 prekey of the account (only with `sessions`, M12)
    GET  /v1/prekeys/{username}   the prekey an account published; open, so a fetch names no account
    WS   /v1/ws         one frame per epoch boundary, the same for every socket (only with `sessions`)

With a `SessionService` the two message routes take a DPoP-bound access token and a proof per request
(session.py); without one the API is open, which `vcloak serve` allows on a loopback address only.

`VcloakBackend` is the protected path: the epoch scheduler writes, and the read handler maps the
conversation to its bucket on the engine, fetches exactly CAND_K candidates and lets the engine open
and order them (R1-R4). `BaselineBackend` (baseline.py) is the unprotected comparison. Both sit behind
`create_app`, so the API contract is one.

Key lifecycle (ADR-007): at startup the master key goes from the key provider straight into the device
key store, which zeroizes the host copy; at shutdown the device subkeys are zeroized. The engine and the
key store are used from one thread only.

Restart (ADR-016): at startup the backend reads the windows the store still lists as pending and hands
them to the scheduler, which re-shuffles those that have closed with its first epoch.
"""
from __future__ import annotations

import asyncio
import getpass
import json
import os
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Protocol, TypeVar

import numpy as np
from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from vcloak import config
from vcloak.crypto import keys as keyfile
from vcloak.crypto.client import PAYLOAD_LEN
from vcloak.gpu.engine import GpuEngine
from vcloak.gpu.keystore import DeviceKeyStore
from vcloak.gpu.runtime import Backend
from vcloak.service.logsafe import SafeLogger, get_logger
from vcloak.service.models import (
    Health,
    LoginIn,
    MessageAccepted,
    MessageIn,
    PayloadError,
    PrekeyIn,
    PrekeyOut,
    ReadIn,
    ReadOut,
    RefreshIn,
    Registered,
    RegisterIn,
    TicketOut,
    TokenOut,
    WindowsOut,
    conv_id_of,
    decode_payload,
    encode_payload,
)
from vcloak.service.scheduler import QUEUE_EPOCHS, Clock, EpochScheduler, NotStored, QueueFull
from vcloak.service.session import SessionService, TokenSet, Verdict
from vcloak.service.web import add_live_routes, mount_web
from vcloak.storage.repo import CandidateOverflow, Repo

T = TypeVar("T")

PASSPHRASE_ENV = "VCLOAK_PASSPHRASE"
KEY_FILE_ENV = "VCLOAK_KEY_FILE"
DEFAULT_KEY_FILE = Path("secrets") / "k_master.sealed"
STOP_TIMEOUT_S = 10.0
ACK_TIMEOUT_MIN_S = 5.0
WS_AUTH_TIMEOUT_S = 5.0  # a socket that has not sent its ticket by then is closed
WS_SEND_TIMEOUT_S = 5.0
WS_AUTH_MAX_LEN = 8192
WS_MAX_SOCKETS = 1024
WS_MAX_PER_SESSION = 4
# close codes of /v1/ws (docs/API.md)
WS_SESSION_ENDED = 4001
WS_REFUSED = 4401
WS_AUTH_TIMEOUT = 4408
WS_TOO_MANY = 4429
WS_POLICY = 1008
WS_GOING_AWAY = 1001

KeyProvider = Callable[[], bytearray]  # a fresh 32-byte master the caller hands to the key store


class AuthRefused(Exception):
    """A request whose proof or access token did not verify; answered with 401 and a DPoP challenge."""

    def __init__(self, verdict: Verdict) -> None:
        super().__init__(verdict.failed_check or "refused")
        self.verdict = verdict


class AckTimeout(RuntimeError):
    """A submission that waits for its write is still queued after every epoch it could have gone into."""


class ServiceBackend(Protocol):
    mode: str
    visible_round: str
    window_s: int
    epoch_ms: int

    @property
    def ready(self) -> bool: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def current_window(self) -> int: ...

    def on_epoch(self, listener: Callable[[], None]) -> None: ...

    async def submit(self, conv_token: str, payload: bytes, *, stored: bool = False) -> None: ...

    async def read(self, conv_token: str, win: int) -> list[bytes]: ...

    def stats(self) -> dict[str, int]: ...


# ── key providers (S5) ───────────────────────────────────────────────────────

def dev_master() -> bytearray:
    """The fixed, public development key of `--dev` (the same bytes as the test key). Not a secret:
    a store written under it has no protection."""
    return bytearray(range(keyfile.KEY_LEN))


def sealed_master(path: str | Path | None = None, *, prompt: Callable[[str], str] = getpass.getpass) -> KeyProvider:
    """A provider that unseals the master key file with the passphrase from VCLOAK_PASSPHRASE, or from a
    prompt when the variable is not set. The variable is removed from the environment once it is read."""
    key_path = Path(path or os.environ.get(KEY_FILE_ENV) or DEFAULT_KEY_FILE)

    def provide() -> bytearray:
        passphrase = os.environ.pop(PASSPHRASE_ENV, None)
        if passphrase is None:
            passphrase = prompt("V-cloak master key passphrase: ")
        return keyfile.unseal_master(key_path, passphrase)

    return provide


# ── the protected backend ────────────────────────────────────────────────────

class VcloakBackend:
    mode = "vcloak"

    def __init__(self, repo: Repo, clock: Clock, key_provider: KeyProvider, *, gpu: Backend | None = None,
                 slots: int = config.SLOTS, buckets: int = config.BUCKETS, window_s: int = config.WINDOW_S,
                 epoch_ms: int = config.EPOCH_MS, cand_k: int = config.CAND_K, visible_round: str = "window",
                 epoch_origin: int = 0, max_queue: int | None = None, autorun: bool = True,
                 ack_timeout_s: float | None = None,
                 engine_factory: Callable[[DeviceKeyStore], Any] | None = None,
                 log: SafeLogger | None = None) -> None:
        self.repo, self._clock, self._key_provider, self._gpu = repo, clock, key_provider, gpu
        self.slots, self.buckets, self.window_s, self.epoch_ms = slots, buckets, window_s, epoch_ms
        self.cand_k, self.visible_round = cand_k, visible_round
        self._origin, self._max_queue, self._autorun = epoch_origin, max_queue, autorun
        # a queued submission is written within the epochs the queue can hold, unless epochs fail
        queue_epochs = QUEUE_EPOCHS if max_queue is None else -(-max_queue // slots)
        self.ack_timeout_s = (max(ACK_TIMEOUT_MIN_S, (queue_epochs + 2) * epoch_ms / 1000)
                              if ack_timeout_s is None else ack_timeout_s)
        self._pending: list[int] = []
        self._epoch_listeners: list[Callable[[], None]] = []
        self._engine_factory = engine_factory or (
            lambda keys: GpuEngine(keys, slots=slots, buckets=buckets, window_s=window_s, epoch_ms=epoch_ms))
        self._log = log or get_logger("service")
        self._executor: ThreadPoolExecutor | None = None
        self._task: asyncio.Task[int] | None = None
        self.keys: DeviceKeyStore | None = None
        self.engine: Any = None
        self.scheduler: EpochScheduler | None = None

    @property
    def ready(self) -> bool:
        return self.scheduler is not None and self.keys is not None and self.keys.ready

    async def _blocking(self, fn: Callable[[], T]) -> T:
        if self._executor is None:
            raise RuntimeError("the backend is not started")
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn)

    def _boot(self) -> None:
        """In the engine thread: master key to the device, then the engine and the schema."""
        self.keys = DeviceKeyStore(self._gpu)
        master = self._key_provider()
        try:
            self.keys.load_master(master)  # zeroizes `master`
        finally:
            if isinstance(master, bytearray):
                keyfile.zeroize(master)
        self.engine = self._engine_factory(self.keys)
        self.repo.init_schema()
        # what a stopped or killed service left in its arrival-time layout (ISSUE-22)
        self._pending = self.repo.pending_windows() if self.visible_round == "window" else []

    async def start(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vcloak-engine")
        try:
            await self._blocking(self._boot)
        except BaseException:
            await self._shutdown_keys()
            raise
        self.scheduler = EpochScheduler(self.engine, self.repo, self._clock, visible_round=self.visible_round,
                                        epoch_origin=self._origin, max_queue=self._max_queue,
                                        executor=self._executor, pending=self._pending)
        for listener in self._epoch_listeners:
            self.scheduler.on_epoch(listener)
        if self._autorun:
            self._task = asyncio.create_task(self.scheduler.run(), name="vcloak-scheduler")
        self._log.event("started", mode=self.mode, visible_round=self.visible_round, slots=self.slots,
                        buckets=self.buckets, window_s=self.window_s, epoch_ms=self.epoch_ms, cand_k=self.cand_k,
                        windows=len(self._pending), backend=self.keys.backend.name if self.keys else "none")

    async def _shutdown_keys(self) -> None:
        keys, executor = self.keys, self._executor
        if keys is not None and executor is not None:
            await asyncio.get_running_loop().run_in_executor(executor, keys.zeroize)
        if executor is not None:
            executor.shutdown(wait=True)
        self._executor = None

    async def stop(self) -> None:
        """Write what is queued, stop the scheduler, zeroize the device keys."""
        sched = self.scheduler
        try:
            if sched is not None:
                budget = sched.finish()
                if self._task is not None:
                    try:
                        await asyncio.wait_for(self._task, STOP_TIMEOUT_S)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        self._log.warning("stop_timeout", queued=sched.queued)
                    except Exception as e:  # noqa: BLE001 - the keys are zeroized whatever the scheduler did
                        self._log.failure("scheduler_failed", e)
                elif budget:
                    await sched.run(budget)
                sched.stop()
                if sched.queued:
                    self._log.warning("stopped_with_queue", queued=sched.queued)
        finally:
            if sched is not None:
                sched.drop_waiters()
            if self._task is not None and not self._task.done():
                self._task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await self._task
            self._task = None
            await self._shutdown_keys()
            self._log.event("stopped", mode=self.mode, ready=self.ready)

    def current_window(self) -> int:
        if self.scheduler is None:
            raise RuntimeError("the backend is not started")
        return self.scheduler.current_round()

    def on_epoch(self, listener: Callable[[], None]) -> None:
        """`listener()` runs on the event loop after every epoch boundary the scheduler handles."""
        self._epoch_listeners.append(listener)
        if self.scheduler is not None:
            self.scheduler.on_epoch(listener)

    async def submit(self, conv_token: str, payload: bytes, *, stored: bool = False) -> None:
        """Queue one message; with `stored`, return only when its epoch is in the store."""
        if self.scheduler is None:
            raise QueueFull("the backend is not started")
        written = self.scheduler.submit(conv_id_of(conv_token), payload, wait=stored)
        if written is not None:
            try:
                await asyncio.wait_for(written, self.ack_timeout_s)
            except asyncio.TimeoutError:
                raise AckTimeout("the submission is still queued") from None

    def _read(self, conv_id: int, win: int) -> list[bytes]:
        bucket = int(self.engine.bucket_of(np.array([conv_id], dtype=np.uint64))[0])
        candidates = self.repo.fetch_candidates(bucket, win, self.cand_k)  # exactly CAND_K rows, or CandidateOverflow
        return self.engine.read_window(conv_id, candidates, self.cand_k)

    async def read(self, conv_token: str, win: int) -> list[bytes]:
        conv_id = conv_id_of(conv_token)
        return await self._blocking(lambda: self._read(conv_id, win))

    def stats(self) -> dict[str, int]:
        if self.scheduler is None:
            return {"epochs": 0, "overflow": 0, "missed": 0, "queued": 0}
        return self.scheduler.stats()


# ── the sockets (M11 S5, ADR-018) ────────────────────────────────────────────

class _Socket:
    def __init__(self, family: str) -> None:
        self.family = family
        self.wake = asyncio.Event()
        self.close: tuple[int, str] | None = None  # set: close with this code instead of sending


class SocketHub:
    """The open sockets of `/v1/ws`. Every socket gets the same frame at every epoch boundary: the push
    says that a boundary passed and names the visible round, never whose messages arrived. A socket that
    is slower than the cadence misses frames (only the newest matters); it is never queued for."""

    def __init__(self, backend: ServiceBackend, sessions: SessionService) -> None:
        self._backend, self._sessions = backend, sessions
        self._sockets: set[_Socket] = set()
        self.frame = ""

    def __len__(self) -> int:
        return len(self._sockets)

    def tick_frame(self, kind: str = "tick") -> str:
        return json.dumps({"type": kind, "win": self._backend.current_window()}, separators=(",", ":"))

    def add(self, family: str) -> _Socket | None:
        """A place for one more socket of this login, or None when the service or the login has too many."""
        if len(self._sockets) >= WS_MAX_SOCKETS:
            return None
        if sum(1 for s in self._sockets if s.family == family) >= WS_MAX_PER_SESSION:
            return None
        sock = _Socket(family)
        self._sockets.add(sock)
        return sock

    def remove(self, sock: _Socket) -> None:
        self._sockets.discard(sock)

    def _end(self, sock: _Socket, code: int, reason: str) -> None:
        if sock.close is None:
            sock.close = (code, reason)
        sock.wake.set()

    def on_epoch(self) -> None:
        """An epoch boundary passed: the same frame for every socket, and the end of those whose login is
        over (logged out, revoked or expired)."""
        self.frame = self.tick_frame()
        for sock in self._sockets:
            if self._sessions.family_live(sock.family):
                sock.wake.set()
            else:
                self._end(sock, WS_SESSION_ENDED, "session_ended")

    def revoke(self, family: str) -> None:
        for sock in self._sockets:
            if sock.family == family:
                self._end(sock, WS_SESSION_ENDED, "session_ended")

    def close_all(self) -> None:
        for sock in self._sockets:
            self._end(sock, WS_GOING_AWAY, "shutdown")


# ── the API ──────────────────────────────────────────────────────────────────

NO_STORE = {"Cache-Control": "no-store"}


def create_app(backend: ServiceBackend, *, payload_len: int = PAYLOAD_LEN,
               sessions: SessionService | None = None, dev: bool = False,
               web_dir: Path | None | bool = None) -> FastAPI:
    """`dev` is what `--dev` means to the page (M13). `web_dir`: the directory served at /app (default: the
    repository's web/), or False for no page."""
    log = get_logger("api")
    hub = SocketHub(backend, sessions) if sessions is not None else None
    if hub is not None and sessions is not None:
        backend.on_epoch(hub.on_epoch)
        sessions.on_family_revoked(hub.revoke)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await backend.start()
        try:
            yield
        finally:
            if hub is not None:
                hub.close_all()
            try:
                await backend.stop()
            finally:
                if sessions is not None:
                    sessions.close()

    app = FastAPI(title="V-cloak", version="1", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.backend = backend
    app.state.sessions = sessions
    app.state.sockets = hub

    def error(status: int, code: str, **headers: str) -> JSONResponse:
        return JSONResponse({"error": code}, status_code=status, headers=headers or None)

    def verify(request: Request, s: SessionService, *, token_required: bool = True) -> Verdict:
        """Check the proof (and the access token) of a request against the method and URL it was sent to."""
        url = s.request_url(str(request.url), request.url.path)
        return s.verify(request.method, url, request.headers.getlist("dpop"),
                        request.headers.get("authorization"), token_required=token_required)

    async def require_session(request: Request) -> Verdict | None:
        """The session of a request; None when the app runs without sessions (open API)."""
        if sessions is None:
            return None
        verdict = verify(request, sessions)
        if not verdict.ok:
            raise AuthRefused(verdict)
        return verdict

    @app.exception_handler(AuthRefused)
    async def refused(_: Request, exc: AuthRefused) -> JSONResponse:
        v = exc.verdict
        return JSONResponse({"error": v.error, "failed_check": v.failed_check}, status_code=401,
                            headers={"WWW-Authenticate": v.challenge(), **NO_STORE})

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        # the field and the reason, never the rejected value
        fields = [{"field": ".".join(str(p) for p in e.get("loc", ())[1:]), "reason": e.get("type", "invalid")}
                  for e in exc.errors()]
        return JSONResponse({"error": "invalid_request", "fields": fields}, status_code=422)

    @app.post("/v1/messages", status_code=202, response_model=MessageAccepted,
              dependencies=[Depends(require_session)])
    async def post_message(body: MessageIn) -> Any:
        try:
            payload = decode_payload(body.payload_b64, payload_len)
        except PayloadError:
            return JSONResponse({"error": "invalid_request",
                                 "fields": [{"field": "payload_b64", "reason": "payload_size"}]}, status_code=422)
        stored = body.ack == "stored"
        try:
            await backend.submit(body.conv_token, payload, stored=stored)
        except QueueFull:
            return error(503, "queue_full", **{"Retry-After": "1"})
        except NotStored:
            return error(503, "not_stored", **{"Retry-After": "1"})
        except AckTimeout:
            # still queued: it may be written later, so the sender cannot tell (docs/API.md)
            return error(504, "ack_timeout")
        if stored:
            return JSONResponse(MessageAccepted(stored=True).model_dump(), status_code=201)
        return MessageAccepted()

    @app.post("/v1/read", response_model=ReadOut, dependencies=[Depends(require_session)])
    async def post_read(body: ReadIn) -> Any:
        try:
            payloads = await backend.read(body.conv_token, body.win)
        except CandidateOverflow as e:
            # CAND_K is below the occupancy of a bucket-window: a capacity fault, never a truncated answer
            log.failure("candidate_overflow", e, win=body.win)
            return error(503, "candidate_overflow")
        return ReadOut(win=body.win, payloads_b64=[encode_payload(p) for p in payloads])

    @app.get("/v1/windows", response_model=WindowsOut)
    async def get_windows() -> Any:
        return WindowsOut(win=backend.current_window(), window_s=backend.window_s, epoch_ms=backend.epoch_ms,
                          visible_round=backend.visible_round, mode=backend.mode)

    @app.get("/healthz", response_model=Health)
    async def healthz() -> Any:
        return Health(mode=backend.mode, ready=backend.ready, **backend.stats())

    if sessions is not None and hub is not None:
        _add_session_routes(app, sessions, verify)
        _add_socket_routes(app, sessions, hub, verify)
    add_live_routes(app, backend, dev=dev, sessions=sessions is not None, payload_len=payload_len)
    if web_dir is not False:
        mount_web(app, None if web_dir is None or web_dir is True else web_dir, dev=dev)
    return app


def _add_session_routes(app: FastAPI, sessions: SessionService, verify: Callable[..., Verdict]) -> None:
    def client_ip(request: Request) -> str:
        # the peer address: a forwarding header is the client's word and is not read
        return request.client.host if request.client else "unknown"

    def tokens(t: TokenSet) -> JSONResponse:
        body = TokenOut(access_token=t.access_token, refresh_token=t.refresh_token, expires_in=t.expires_in)
        return JSONResponse(body.model_dump(), headers=NO_STORE)

    def limited(retry_after: int) -> JSONResponse:
        return JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": str(retry_after)})

    @app.post("/v1/auth/register", status_code=201, response_model=Registered)
    async def register(body: RegisterIn, request: Request) -> Any:
        result = await sessions.register(body.username, body.password, ip=client_ip(request))
        if result.status == "rate_limited":
            return limited(result.retry_after)
        if result.status == "taken":
            return JSONResponse({"error": "username_taken"}, status_code=409)
        if result.status != "ok":
            return JSONResponse({"error": "invalid_request", "fields": []}, status_code=422)
        return Registered()

    @app.post("/v1/auth/login", response_model=TokenOut)
    async def login(body: LoginIn, request: Request) -> Any:
        url = sessions.request_url(str(request.url), request.url.path)
        result = await sessions.login(body.username, body.password, ip=client_ip(request), method=request.method,
                                      url=url, proofs=request.headers.getlist("dpop"))
        if result.status == "rate_limited":
            return limited(result.retry_after)
        if result.status == "invalid_proof" and result.verdict is not None:
            raise AuthRefused(result.verdict)
        if result.tokens is None:
            # one answer for an unknown name and a wrong password
            return JSONResponse({"error": "invalid_credentials"}, status_code=401, headers=NO_STORE)
        return tokens(result.tokens)

    @app.post("/v1/auth/refresh", response_model=TokenOut)
    async def refresh(body: RefreshIn, request: Request) -> Any:
        verdict = verify(request, sessions, token_required=False)
        if not verdict.ok:
            raise AuthRefused(verdict)
        issued, reason = sessions.refresh(body.refresh_token, verdict.jkt)
        if issued is None:
            return JSONResponse({"error": "invalid_grant", "reason": reason}, status_code=401, headers=NO_STORE)
        return tokens(issued)

    @app.post("/v1/auth/logout", status_code=204)
    async def logout(request: Request) -> Response:
        verdict = verify(request, sessions)
        if not verdict.ok:
            raise AuthRefused(verdict)
        sessions.revoke_family(verdict.family)
        return Response(status_code=204)

    async def session_of(request: Request) -> Verdict:
        # a dependency: the session is checked before the body, as for the message routes
        verdict = verify(request, sessions)
        if not verdict.ok:
            raise AuthRefused(verdict)
        return verdict

    @app.put("/v1/prekeys", status_code=204)
    async def put_prekey(body: PrekeyIn, verdict: Verdict = Depends(session_of)) -> Response:  # noqa: B008
        sessions.publish_prekey(verdict, body.prekey_b64)
        return Response(status_code=204)

    @app.get("/v1/prekeys/{username}", response_model=PrekeyOut)
    async def get_prekey(username: str) -> Any:
        # no session on purpose: the server never learns which account asked for whose key (ADR-019)
        prekey = sessions.prekey_of(username)
        if prekey is None:
            return JSONResponse({"error": "no_prekey"}, status_code=404, headers=NO_STORE)
        return JSONResponse(PrekeyOut(username=username, prekey_b64=prekey).model_dump(), headers=NO_STORE)


def _add_socket_routes(app: FastAPI, sessions: SessionService, hub: SocketHub,
                       verify: Callable[..., Verdict]) -> None:
    @app.post("/v1/auth/ws-ticket", response_model=TicketOut)
    async def ws_ticket(request: Request) -> Any:
        verdict = verify(request, sessions)
        if not verdict.ok:
            raise AuthRefused(verdict)
        t = sessions.issue_ws_ticket(verdict)
        return JSONResponse(TicketOut(ticket=t.ticket, expires_in=t.expires_in).model_dump(), headers=NO_STORE)

    async def first_frame(ws: WebSocket) -> tuple[object, object] | None:
        """The (ticket, proof) of the frame a client sends first; None when it is not such a frame."""
        text = await ws.receive_text()
        if len(text) > WS_AUTH_MAX_LEN:
            return None
        try:
            body = json.loads(text)
        except ValueError:
            return None
        if not isinstance(body, dict) or set(body) != {"ticket", "dpop"}:
            return None
        return body["ticket"], body["dpop"]

    async def watch(ws: WebSocket, sock: _Socket) -> None:
        """A client has nothing to say after its ticket: a frame ends the socket, and so does its leaving."""
        try:
            await ws.receive_text()
        except (WebSocketDisconnect, RuntimeError, KeyError):
            sock.close = sock.close or (0, "")  # gone: nothing to close
        else:
            sock.close = sock.close or (WS_POLICY, "unexpected_frame")
        sock.wake.set()

    @app.websocket("/v1/ws")
    async def ws_push(ws: WebSocket) -> None:
        await ws.accept()
        try:
            first = await asyncio.wait_for(first_frame(ws), WS_AUTH_TIMEOUT_S)
        except asyncio.TimeoutError:
            await ws.close(WS_AUTH_TIMEOUT, "auth_timeout")
            return
        except (WebSocketDisconnect, RuntimeError, KeyError):
            return  # left, or sent bytes, before the ticket
        if first is None:
            await ws.close(WS_POLICY, "auth_frame")
            return
        grant = sessions.open_socket(sessions.socket_url(str(ws.url), ws.url.path), *first)
        if not grant.ok:
            await ws.close(WS_REFUSED, grant.failed_check or "refused")
            return
        sock = hub.add(grant.family)
        if sock is None:
            await ws.close(WS_TOO_MANY, "too_many_sockets")
            return
        watcher = asyncio.create_task(watch(ws, sock))
        try:
            await ws.send_text(hub.tick_frame("ready"))
            while True:
                await sock.wake.wait()
                sock.wake.clear()
                if sock.close is not None:
                    if sock.close[0]:
                        await ws.close(*sock.close)
                    return
                await asyncio.wait_for(ws.send_text(hub.frame), WS_SEND_TIMEOUT_S)
        except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
            return  # the client left, or does not read
        finally:
            hub.remove(sock)
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
