"""A test client for the session layer (M11): an ES256 device key and the DPoP proofs it signs.

Written against RFC 9449 and RFC 7638 with `cryptography` only, and sharing no code with
`vcloak.service.session`, so that the tests check the server against a second implementation.
Every argument of `proof` can be bent to build a proof the server must refuse.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from collections.abc import Callable
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def segment(obj: Any) -> str:
    return b64u(json.dumps(obj).encode())


def decode_segment(text: str) -> Any:
    return json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))


class Device:
    """One client device: a fresh P-256 key that never leaves the test process."""

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())
        self._now = now
        n = self._key.public_key().public_numbers()
        self.jwk: dict[str, str] = {"kty": "EC", "crv": "P-256", "x": b64u(n.x.to_bytes(32, "big")),
                                    "y": b64u(n.y.to_bytes(32, "big"))}
        canonical = '{"crv":"P-256","kty":"EC","x":"' + self.jwk["x"] + '","y":"' + self.jwk["y"] + '"}'
        self.jkt = b64u(hashlib.sha256(canonical.encode()).digest())

    def sign(self, signing_input: str) -> str:
        r, s = decode_dss_signature(self._key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
        return b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

    def proof(self, method: str, url: str, token: str | None = None, *, iat: float | None = None,
              jti: str | None = None, header: dict[str, Any] | None = None,
              claims: dict[str, Any] | None = None, drop: tuple[str, ...] = (),
              signer: Device | None = None) -> str:
        """A DPoP proof for one request. `header` and `claims` override members, `drop` removes them,
        `signer` signs with another device's key while the header keeps this one's JWK."""
        hdr: dict[str, Any] = {"typ": "dpop+jwt", "alg": "ES256", "jwk": dict(self.jwk)}
        hdr.update(header or {})
        body: dict[str, Any] = {"htm": method, "htu": url, "iat": int(self._now() if iat is None else iat),
                                "jti": jti or b64u(os.urandom(16))}
        if token is not None:
            body["ath"] = b64u(hashlib.sha256(token.encode()).digest())
        body.update(claims or {})
        for name in drop:
            hdr.pop(name, None)
            body.pop(name, None)
        signing_input = f"{segment(hdr)}.{segment(body)}"
        return f"{signing_input}.{(signer or self).sign(signing_input)}"

    def headers(self, method: str, url: str, token: str | None = None, **kw: Any) -> dict[str, str]:
        """The request headers of an authenticated call (or of a token request when `token` is None)."""
        out = {"DPoP": self.proof(method, url, token, **kw)}
        if token is not None:
            out["Authorization"] = f"DPoP {token}"
        return out


class FakeTime:
    """A wall clock the test moves."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds
