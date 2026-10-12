"""Session security (M11, ADR-017, ADR-018): accounts, sender-constrained tokens, DPoP verification, refresh
rotation, WebSocket tickets.

    register / login     an account is a name and an Argon2id hash (per-user salt, parameters in the hash string)
    access token         JWS HS256 over a secret that lives in this process only, 10 minutes, bound to the
                         client's key by `cnf.jkt` (the RFC 7638 thumbprint of its ES256 public JWK)
    DPoP proof           every request is signed by that key (RFC 9449): a stolen token is useless without it
    refresh token        opaque, single use, one family per login; a spent token that comes back revokes the family
    WebSocket ticket     opaque, single use, 30 seconds, bound to the key of the request that asked for it; the
                         socket is opened with the ticket and a proof of that key (`open_socket`)

`SessionService.verify` evaluates every check and decides afterwards, so a refused request takes one path
whatever failed, and the signature is always computed. The verdict names the checks that failed, in a fixed
order; the first one goes into the `WWW-Authenticate` challenge.

Nothing here touches message content or the keys of the engine: a session says who may call the API, and the
server still does not learn who talks to whom. State is in memory (accounts included): see ADR-017.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from vcloak.service.logsafe import SafeLogger, get_logger

T = TypeVar("T")

USERNAME_PATTERN = r"^[a-z0-9_]{3,32}$"
PASSWORD_MIN, PASSWORD_MAX = 8, 128
REFRESH_PATTERN = r"^[A-Za-z0-9_-]{43}$"  # 32 random bytes, base64url
PROOF_MAX_LEN = 4096
HTU_MAX_LEN = 2048
DPOP_ALG = "ES256"
DPOP_TYP = "dpop+jwt"
HASH_WORKERS = 2  # Argon2id runs off the event loop; this bounds its memory (workers x m_kib)

# the order in which a refused request is reported: the proof first, then the token it presents
PROOF_CHECKS: tuple[str, ...] = ("proof_format", "typ", "alg", "jwk", "signature", "htm", "htu", "iat", "jti")
TOKEN_CHECKS: tuple[str, ...] = ("authorization", "token_format", "token_mac", "token_exp", "token_revoked",
                                 "key_binding", "ath")
_TOKEN_ERRORS = frozenset(TOKEN_CHECKS) - {"ath"}  # `ath` is a claim of the proof
# opening a socket: the proof again, then the ticket it redeems
TICKET_CHECKS: tuple[str, ...] = ("ticket_format", "ticket_known", "ticket_unused", "ticket_exp", "ticket_session",
                                  "ticket_key")
TICKET_PATTERN = r"^[A-Za-z0-9_-]{43}$"  # 32 random bytes, base64url
PREKEY_PATTERN = r"^[A-Za-z0-9+/]{43}=$"  # a 32-byte X25519 public key, standard base64
WS_METHOD = "GET"  # the method of the handshake a socket proof names
TICKETS_PER_FAMILY = 8  # unspent tickets one login may hold; the oldest goes first

_B64U_RE = re.compile(r"[A-Za-z0-9_-]*")
_JTI_RE = re.compile(r"[\x21-\x7e]{16,128}")  # at least 96 bits when random
_USERNAME_RE = re.compile(USERNAME_PATTERN)
_REFRESH_RE = re.compile(REFRESH_PATTERN)
_TICKET_RE = re.compile(TICKET_PATTERN)
_PREKEY_RE = re.compile(PREKEY_PATTERN)
_WS_SCHEMES = {"ws": "http", "wss": "https"}
_DEFAULT_PORTS = {"http": 80, "https": 443}
# RFC 7638 §3.2: the required members of each key type, in lexicographic order
_THUMBPRINT_MEMBERS: dict[str, tuple[str, ...]] = {
    "EC": ("crv", "kty", "x", "y"),
    "OKP": ("crv", "kty", "x"),
    "RSA": ("e", "kty", "n"),
}

Clock = Callable[[], float]


# ── encodings ────────────────────────────────────────────────────────────────

def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def ub64(text: object) -> bytes:
    """Strict unpadded base64url: any other character, or padding, is a ValueError."""
    if not isinstance(text, str) or not _B64U_RE.fullmatch(text) or len(text) % 4 == 1:
        raise ValueError("not unpadded base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _json_object(segment: object) -> dict[str, Any] | None:
    try:
        obj = json.loads(ub64(segment))
    except (ValueError, RecursionError):  # bad base64url, bad UTF-8, bad JSON, absurd nesting
        return None
    return obj if isinstance(obj, dict) else None


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def jwk_thumbprint(jwk: dict[str, Any]) -> str:
    """RFC 7638: SHA-256 over the JSON object of the required members only, keys sorted, no whitespace."""
    kty = jwk.get("kty")
    members = _THUMBPRINT_MEMBERS.get(kty) if isinstance(kty, str) else None
    if members is None:
        raise ValueError("unsupported key type")
    required = {m: jwk.get(m) for m in members}
    if not all(isinstance(v, str) for v in required.values()):
        raise ValueError("a required member of the JWK is missing")
    canonical = json.dumps(required, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return b64u(hashlib.sha256(canonical.encode("utf-8")).digest())


def normalise_htu(url: object) -> str | None:
    """The form in which `htu` and the request URL are compared (RFC 9449 §4.3, RFC 3986 §6.2): scheme and
    host in lower case, the default port dropped, an empty path as `/`, query and fragment ignored."""
    if not isinstance(url, str) or len(url) > HTU_MAX_LEN:
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host or parts.username is not None or parts.password is not None:
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        host = f"{host}:{port}"
    return f"{scheme}://{host}{parts.path or '/'}"


# ── the proof ────────────────────────────────────────────────────────────────

_NO_KEY = ec.generate_private_key(ec.SECP256R1()).public_key()  # verified against when a proof carries no usable key
_NO_SIGNATURE = (bytes(31) + b"\x01") * 2


@dataclass(frozen=True)
class _Proof:
    well_formed: bool
    header: dict[str, Any]
    claims: dict[str, Any]
    signing_input: bytes
    signature: bytes


def _parse_proof(proofs: Sequence[str]) -> _Proof:
    """Never raises: a request without exactly one parsable proof gives empty parts and `well_formed` False."""
    proof = proofs[0] if len(proofs) == 1 and len(proofs[0]) <= PROOF_MAX_LEN else ""
    parts = proof.split(".")
    h, b, s = parts if len(parts) == 3 else ("", "", "")
    header, claims = _json_object(h), _json_object(b)
    try:
        signature = ub64(s)
    except ValueError:
        signature = b""
    ok = len(parts) == 3 and header is not None and claims is not None and len(signature) == 64
    return _Proof(ok, header or {}, claims or {}, f"{h}.{b}".encode("utf-8", "replace"), signature)


def _ec_public_key(jwk: object) -> ec.EllipticCurvePublicKey | None:
    """The P-256 public key of a JWK, or None. A JWK with a private member is refused (RFC 9449 §4.3)."""
    if not isinstance(jwk, dict) or jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or "d" in jwk:
        return None
    try:
        x, y = ub64(jwk.get("x")), ub64(jwk.get("y"))
        if len(x) != 32 or len(y) != 32:
            return None
        numbers = ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1())
        return numbers.public_key()  # ValueError when the point is not on the curve
    except ValueError:
        return None


def _es256_ok(key: ec.EllipticCurvePublicKey, signing_input: bytes, signature: bytes) -> bool:
    """One ECDSA verification whatever the input: a signature of the wrong size is replaced by a fixed bad one."""
    sized = len(signature) == 64
    raw = signature if sized else _NO_SIGNATURE
    der = encode_dss_signature(int.from_bytes(raw[:32], "big") or 1, int.from_bytes(raw[32:], "big") or 1)
    try:
        key.verify(der, signing_input, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        return False
    return sized


# ── results ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Verdict:
    """What `verify` decided. `failed` lists every check that did not hold, in the order of PROOF_CHECKS +
    TOKEN_CHECKS; `sub`, `jkt` and `family` are set only when nothing failed."""
    failed: tuple[str, ...] = ()
    sub: str = ""
    jkt: str = ""
    family: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def failed_check(self) -> str | None:
        return self.failed[0] if self.failed else None

    @property
    def error(self) -> str | None:
        """The RFC 9449 §7.1 error code of the first failed check."""
        if not self.failed:
            return None
        return "invalid_token" if self.failed[0] in _TOKEN_ERRORS else "invalid_dpop_proof"

    def challenge(self) -> str:
        """The value of `WWW-Authenticate` for a 401."""
        if not self.failed:
            return f'DPoP algs="{DPOP_ALG}"'
        return f'DPoP error="{self.error}", error_description="{self.failed[0]}", algs="{DPOP_ALG}"'


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "DPoP"


@dataclass(frozen=True)
class Ticket:
    ticket: str
    expires_in: int


@dataclass(frozen=True)
class SocketGrant:
    """What `open_socket` decided. `failed` lists every check that did not hold, in the order of PROOF_CHECKS +
    TICKET_CHECKS; `sub` and `family` are set only when nothing failed."""
    failed: tuple[str, ...] = ()
    sub: str = ""
    family: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def failed_check(self) -> str | None:
        return self.failed[0] if self.failed else None


RefreshReason = Literal["rotated", "unknown", "family_revoked", "reuse", "expired", "key_binding"]
LoginStatus = Literal["ok", "rate_limited", "invalid_proof", "invalid_credentials"]
RegisterStatus = Literal["ok", "rate_limited", "invalid", "taken"]


@dataclass(frozen=True)
class LoginResult:
    status: LoginStatus
    tokens: TokenSet | None = None
    retry_after: int = 0
    verdict: Verdict | None = None


@dataclass(frozen=True)
class RegisterResult:
    status: RegisterStatus
    retry_after: int = 0


# ── configuration ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PasswordParams:
    """Argon2id cost (the second recommended option of RFC 9106 §4). Stored in every hash string."""
    t: int = 3
    m_kib: int = 64 * 1024
    p: int = 4


@dataclass(frozen=True)
class SessionConfig:
    access_ttl_s: int = 600
    refresh_ttl_s: int = 7 * 24 * 3600
    proof_skew_s: int = 60  # |now - iat| a proof may have
    jti_ttl_s: int = 300  # how long a seen jti is remembered (longer than any accepted proof lives)
    login_ip_max: int = 20  # login attempts of one address ...
    login_ip_window_s: int = 60
    login_account_max: int = 5  # ... and attempts on one name without a success in between
    login_account_window_s: int = 300
    register_ip_max: int = 5
    register_ip_window_s: int = 3600
    ws_ticket_ttl_s: int = 30
    password: PasswordParams = field(default_factory=PasswordParams)
    public_origin: str | None = None  # e.g. "https://chat.example" behind a proxy; None: the URL as received


# ── rate limits ──────────────────────────────────────────────────────────────

class RateLimiter:
    """At most `limit` hits of one key in any `window_s` seconds (a sliding log, in memory)."""

    SWEEP_AT = 4096  # keys held before the idle ones are dropped

    def __init__(self, limit: int, window_s: float, now: Clock = time.time) -> None:
        if limit < 1 or window_s <= 0:
            raise ValueError("a rate limit needs limit >= 1 and window_s > 0")
        self.limit, self.window_s, self._now = limit, window_s, now
        self._hits: dict[str, deque[float]] = {}

    def _live(self, key: str, now: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def retry_after(self, key: str) -> int:
        """0 when a hit is allowed now, otherwise the whole seconds until one is."""
        now = self._now()
        hits = self._live(key, now)
        if hits is None or len(hits) < self.limit:
            return 0
        return max(1, int(hits[-self.limit] + self.window_s - now + 0.999))

    def hit(self, key: str) -> None:
        now = self._now()
        if len(self._hits) >= self.SWEEP_AT:
            for k in list(self._hits):
                self._live(k, now)
        self._hits.setdefault(key, deque(maxlen=self.limit)).append(now)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def __len__(self) -> int:
        return len(self._hits)


# ── accounts ─────────────────────────────────────────────────────────────────

class Accounts:
    """Names and Argon2id hashes. The hash string carries its salt and its parameters, so a later change
    of the cost re-hashes an account at its next login. Passwords are never kept, logged or compared here
    other than through Argon2id."""

    def __init__(self, params: PasswordParams | None = None) -> None:
        params = params or PasswordParams()
        self._hasher = PasswordHasher(time_cost=params.t, memory_cost=params.m_kib, parallelism=params.p,
                                      hash_len=32, salt_len=16)
        self._hashes: dict[str, str] = {}
        # verified against for a name that does not exist, so that both refusals cost one Argon2id run
        self._decoy = self._hasher.hash(b64u(os.urandom(18)))

    def __contains__(self, name: object) -> bool:
        return name in self._hashes

    def __len__(self) -> int:
        return len(self._hashes)

    def hash_of(self, name: str) -> str | None:
        return self._hashes.get(name)

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def add(self, name: str, pw_hash: str) -> bool:
        """False when the name is taken (the first registration wins)."""
        if name in self._hashes:
            return False
        self._hashes[name] = pw_hash
        return True

    def check(self, name: str, password: str) -> bool:
        stored = self._hashes.get(name)
        try:
            self._hasher.verify(stored or self._decoy, password)
        except (VerificationError, InvalidHashError):
            return False
        if stored is None:
            return False
        if self._hasher.check_needs_rehash(stored) and self._hashes.get(name) == stored:
            self._hashes[name] = self._hasher.hash(password)
        return True


# ── the service ──────────────────────────────────────────────────────────────

_ACCESS_HEADER = b64u(b'{"alg":"HS256","typ":"at+jwt"}')


@dataclass
class _Refresh:
    user: str
    jkt: str
    family: str
    exp: float
    used: bool = False


@dataclass
class _Ticket:
    user: str
    jkt: str
    family: str
    exp: float
    used: bool = False


@dataclass
class _Family:
    exp: float  # the expiry of its newest refresh token
    revoked: bool = False


_NO_TICKET = _Ticket("", "", "", 0.0, used=True)  # read in place of a ticket the table does not hold


class SessionService:
    """Accounts, tokens and proof verification of one service process.

    The state changes on the event-loop thread only; Argon2id runs in a small pool. `now` is the wall
    clock in seconds (a test passes its own)."""

    def __init__(self, config: SessionConfig | None = None, *, now: Clock = time.time,
                 log: SafeLogger | None = None) -> None:
        self.config = config or SessionConfig()
        self._now = now
        self._log = log or get_logger("session")
        self._mac_key = os.urandom(32)  # signs access tokens; never leaves this process
        self.accounts = Accounts(self.config.password)
        self._jti: OrderedDict[bytes, float] = OrderedDict()  # SHA-256(jti) -> when it may be forgotten
        self._refresh: dict[bytes, _Refresh] = {}  # SHA-256(token) -> record: the table holds no usable token
        self._families: dict[str, _Family] = {}
        self._tickets: OrderedDict[bytes, _Ticket] = OrderedDict()  # SHA-256(ticket) -> record, oldest first
        self._revocation_listeners: list[Callable[[str], None]] = []
        self._prekeys: dict[str, str] = {}  # account name -> its public X25519 prekey (M12, ADR-019)
        c = self.config
        self.login_ip = RateLimiter(c.login_ip_max, c.login_ip_window_s, now)
        self.login_account = RateLimiter(c.login_account_max, c.login_account_window_s, now)
        self.register_ip = RateLimiter(c.register_ip_max, c.register_ip_window_s, now)
        self._pool: ThreadPoolExecutor | None = None

    # -- lifecycle --

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None

    async def _hashing(self, fn: Callable[[], T]) -> T:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=HASH_WORKERS, thread_name_prefix="vcloak-argon2")
        return await asyncio.get_running_loop().run_in_executor(self._pool, fn)

    def on_family_revoked(self, listener: Callable[[str], None]) -> None:
        """`listener(family)` runs when a family is revoked (logout, refresh reuse)."""
        self._revocation_listeners.append(listener)

    # -- accounts (S1) --

    async def register(self, name: str, password: str, *, ip: str) -> RegisterResult:
        retry = self.register_ip.retry_after(ip)
        if retry:
            return RegisterResult("rate_limited", retry)
        self.register_ip.hit(ip)
        if not _USERNAME_RE.fullmatch(name) or not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
            return RegisterResult("invalid")
        if name in self.accounts:
            return RegisterResult("taken")
        pw_hash = await self._hashing(lambda: self.accounts.hash_password(password))
        return RegisterResult("ok" if self.accounts.add(name, pw_hash) else "taken")

    async def login(self, name: str, password: str, *, ip: str, method: str, url: str,
                    proofs: Sequence[str]) -> LoginResult:
        """Password login that binds the new tokens to the key of the DPoP proof sent with it."""
        retry = max(self.login_ip.retry_after(ip), self.login_account.retry_after(name))
        if retry:
            return LoginResult("rate_limited", retry_after=retry)
        self.login_ip.hit(ip)
        verdict = self.verify(method, url, proofs, token_required=False)
        if not verdict.ok:
            return LoginResult("invalid_proof", verdict=verdict)
        # counted before the hash is computed: attempts made in parallel cannot outrun the limit
        self.login_account.hit(name)
        if not await self._hashing(lambda: self.accounts.check(name, password)):
            return LoginResult("invalid_credentials")
        self.login_account.reset(name)
        return LoginResult("ok", tokens=self._issue(name, verdict.jkt))

    # -- tokens (S2) --

    def _mac(self, signing_input: str) -> bytes:
        return hmac.new(self._mac_key, signing_input.encode("utf-8", "replace"), hashlib.sha256).digest()

    def _sign_access(self, claims: dict[str, Any]) -> str:
        body = b64u(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{_ACCESS_HEADER}.{body}"
        return f"{signing_input}.{b64u(self._mac(signing_input))}"

    def _read_access(self, token: str) -> tuple[bool, bool, dict[str, Any]]:
        """(well formed, MAC holds, claims). The claims are untrusted unless both flags hold."""
        parts = token.split(".")
        h, p, t = parts if len(parts) == 3 else ("", "", "")
        try:
            tag = ub64(t)
        except ValueError:
            tag = b""
        mac_ok = hmac.compare_digest(tag, self._mac(f"{h}.{p}"))
        claims = _json_object(p) or {}
        cnf = claims.get("cnf")
        well_formed = (len(parts) == 3 and h == _ACCESS_HEADER and isinstance(claims.get("sub"), str)
                       and _is_number(claims.get("exp")) and isinstance(claims.get("fam"), str)
                       and isinstance(cnf, dict) and isinstance(cnf.get("jkt"), str))
        return well_formed, mac_ok, claims

    def _issue(self, user: str, jkt: str, family: str | None = None) -> TokenSet:
        now = self._now()
        self._expire(now)
        family = family or b64u(os.urandom(12))
        access = self._sign_access({"sub": user, "cnf": {"jkt": jkt}, "fam": family, "iat": int(now),
                                    "exp": int(now) + self.config.access_ttl_s})
        refresh = b64u(os.urandom(32))
        exp = now + self.config.refresh_ttl_s
        self._refresh[hashlib.sha256(refresh.encode("ascii")).digest()] = _Refresh(user, jkt, family, exp)
        self._families[family] = _Family(exp)
        return TokenSet(access, refresh, self.config.access_ttl_s)

    def _expire(self, now: float) -> None:
        """Forget refresh tokens and families past their lifetime (a spent token is kept until then: it is
        what reuse detection looks up)."""
        for key in [k for k, r in self._refresh.items() if r.exp <= now]:
            del self._refresh[key]
        for fam in [f for f, rec in self._families.items() if rec.exp <= now]:
            del self._families[fam]
        while self._tickets and next(iter(self._tickets.values())).exp <= now:
            self._tickets.popitem(last=False)

    def family_live(self, family: object) -> bool:
        rec = self._families.get(family) if isinstance(family, str) else None
        return rec is not None and not rec.revoked and rec.exp > self._now()

    # -- DPoP verification (S3) --

    def request_url(self, url: str, path: str) -> str:
        """The URL a proof must name: the configured public origin plus the path, or the URL as received."""
        origin = self.config.public_origin
        return f"{origin.rstrip('/')}{path}" if origin else url

    def verify(self, method: str, url: str, proofs: Sequence[str], authorization: str | None = None, *,
               token_required: bool = True) -> Verdict:
        """Check one request: the DPoP proof (`proofs` holds every `DPoP` header of the request) and, unless
        `token_required` is False (login, refresh), the access token of `Authorization: DPoP <token>`.

        Every check is evaluated, the ES256 verification included, and only then is the request decided.
        A jti is remembered only for an accepted request."""
        now = self._now()
        proof = _parse_proof(proofs)
        jwk = proof.header.get("jwk")
        key = _ec_public_key(jwk)
        signature_ok = _es256_ok(key or _NO_KEY, proof.signing_input, proof.signature)
        jkt = jwk_thumbprint(jwk) if key is not None else ""

        while self._jti and next(iter(self._jti.values())) <= now:
            self._jti.popitem(last=False)
        jti, iat = proof.claims.get("jti"), proof.claims.get("iat")
        jti_key = hashlib.sha256(jti.encode("utf-8", "replace")).digest() if isinstance(jti, str) else b""
        want_htu = normalise_htu(url)

        checks: dict[str, bool] = {
            "proof_format": proof.well_formed,
            "typ": proof.header.get("typ") == DPOP_TYP,
            "alg": proof.header.get("alg") == DPOP_ALG,
            "jwk": key is not None,
            "signature": signature_ok and key is not None,
            "htm": proof.claims.get("htm") == method,
            "htu": want_htu is not None and normalise_htu(proof.claims.get("htu")) == want_htu,
            "iat": _is_number(iat) and abs(now - iat) <= self.config.proof_skew_s,
            "jti": isinstance(jti, str) and _JTI_RE.fullmatch(jti) is not None and jti_key not in self._jti,
        }
        claims: dict[str, Any] = {}
        if token_required:
            scheme, _, token = (authorization or "").partition(" ")
            well_formed, mac_ok, claims = self._read_access(token)
            cnf, exp, ath = claims.get("cnf"), claims.get("exp"), proof.claims.get("ath")
            bound = cnf.get("jkt") if isinstance(cnf, dict) else None
            want_ath = b64u(hashlib.sha256(token.encode("utf-8", "replace")).digest())
            checks.update({
                "authorization": scheme.lower() == "dpop" and bool(token) and " " not in token,
                "token_format": well_formed,
                "token_mac": mac_ok,
                "token_exp": _is_number(exp) and exp > now,
                "token_revoked": self.family_live(claims.get("fam")),
                "key_binding": bool(jkt) and isinstance(bound, str) and hmac.compare_digest(
                    jkt.encode("ascii"), bound.encode("utf-8", "replace")),
                "ath": isinstance(ath, str) and hmac.compare_digest(
                    ath.encode("utf-8", "replace"), want_ath.encode("ascii")),
            })
        failed = tuple(name for name, held in checks.items() if not held)
        if failed:
            return Verdict(failed)
        self._jti[jti_key] = now + self.config.jti_ttl_s
        if token_required:
            return Verdict((), sub=claims["sub"], jkt=jkt, family=claims["fam"])
        return Verdict((), jkt=jkt)

    # -- refresh rotation and revocation (S4) --

    def refresh(self, refresh_token: str, jkt: str) -> tuple[TokenSet | None, RefreshReason]:
        """Spend a refresh token for a new pair in the same family. `jkt` is the key of the verified proof.

        A token that was already spent means two parties hold it: the whole family is revoked, so the
        thief and the owner both have to log in again, and only the owner can."""
        now = self._now()
        rec = self._refresh.get(hashlib.sha256(refresh_token.encode("utf-8", "replace")).digest())
        if rec is None or not _REFRESH_RE.fullmatch(refresh_token):
            return None, "unknown"
        family = self._families.get(rec.family)
        if family is None or family.revoked:
            return None, "family_revoked"
        if rec.used:
            self.revoke_family(rec.family, "refresh_reuse")
            return None, "reuse"
        if rec.exp <= now:
            return None, "expired"
        if not hmac.compare_digest(rec.jkt.encode("ascii"), jkt.encode("utf-8", "replace")):
            return None, "key_binding"  # not spent: the owner's next refresh still works
        rec.used = True
        return self._issue(rec.user, rec.jkt, rec.family), "rotated"

    def revoke_family(self, family: str, reason: str = "logout") -> bool:
        """Revoke every token of a login: its refresh tokens and, through `token_revoked`, its access
        tokens. True when the family was live."""
        rec = self._families.get(family)
        if rec is None or rec.revoked:
            return False
        rec.revoked = True
        if reason != "logout":
            self._log.warning("family_revoked", error=reason)
        for listener in list(self._revocation_listeners):
            listener(family)
        return True

    # -- prekeys (M12, ADR-019) --

    def publish_prekey(self, session: Verdict, prekey_b64: str) -> bool:
        """Set the public prekey of the account of this session (the newest replaces the one before).
        False when it is not the base64 of 32 bytes."""
        if not session.ok or not session.sub or not _PREKEY_RE.fullmatch(prekey_b64):
            return False
        self._prekeys[session.sub] = prekey_b64
        return True

    def prekey_of(self, name: object) -> str | None:
        """The public prekey an account published; None for an unknown name and for an account without one."""
        return self._prekeys.get(name) if isinstance(name, str) else None

    # -- WebSocket tickets (S5) --

    def issue_ws_ticket(self, session: Verdict) -> Ticket:
        """A ticket for one socket, for the session of a verified request. It is bound to the key of that
        request and to its login: a logout ends it."""
        if not session.ok or not session.family:
            raise ValueError("a ticket is issued to a verified session only")
        now = self._now()
        self._expire(now)
        held = [k for k, t in self._tickets.items() if t.family == session.family and not t.used]
        for key in held[:max(0, len(held) - TICKETS_PER_FAMILY + 1)]:
            del self._tickets[key]
        ticket = b64u(os.urandom(32))
        self._tickets[hashlib.sha256(ticket.encode("ascii")).digest()] = _Ticket(
            session.sub, session.jkt, session.family, now + self.config.ws_ticket_ttl_s)
        return Ticket(ticket, self.config.ws_ticket_ttl_s)

    def socket_url(self, url: str, path: str) -> str:
        """The URL a socket proof must name: that of the handshake, as `http` or `https` (a DPoP `htu` has no
        `ws` form), under the configured public origin when there is one."""
        scheme, sep, rest = url.partition("://")
        mapped = _WS_SCHEMES.get(scheme.lower())
        return self.request_url(f"{mapped}{sep}{rest}" if mapped else url, path)

    def open_socket(self, url: str, ticket: object, proof: object) -> SocketGrant:
        """Redeem a ticket for one socket. `proof` is a DPoP proof for `GET` on `url` (see `socket_url`), signed
        by the key the ticket was issued to. Every check is evaluated, then the request is decided; a ticket
        is spent only by the request that is accepted."""
        proofs = [proof] if isinstance(proof, str) else []
        verdict = self.verify(WS_METHOD, url, proofs, token_required=False)
        now = self._now()
        text = ticket if isinstance(ticket, str) else ""
        rec = self._tickets.get(hashlib.sha256(text.encode("utf-8", "replace")).digest())
        known = rec is not None
        rec = rec or _NO_TICKET
        checks: dict[str, bool] = {
            "ticket_format": _TICKET_RE.fullmatch(text) is not None,
            "ticket_known": known,
            "ticket_unused": known and not rec.used,
            "ticket_exp": known and rec.exp > now,
            "ticket_session": known and self.family_live(rec.family),
            "ticket_key": known and bool(verdict.jkt) and hmac.compare_digest(
                rec.jkt.encode("ascii"), verdict.jkt.encode("utf-8", "replace")),
        }
        failed = verdict.failed + tuple(name for name, held in checks.items() if not held)
        if failed:
            return SocketGrant(failed)
        rec.used = True
        return SocketGrant((), sub=rec.user, family=rec.family)
