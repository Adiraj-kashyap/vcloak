"""The keys of one client device, and the optional sealed key file (M12 S1).

A device holds two private keys: an ES256 (P-256) key that signs its DPoP proofs, and the X25519
prekey its conversations are agreed with. Both are drawn in memory and stay there. `save_keyfile`
writes them only sealed, with the construction of the master key file (crypto/keys.py):

    magic(8) | argon2 params: LE32 t, LE32 m_kib, LE32 p (12) | salt(16) | nonce(12) | ct+tag

AES-256-GCM under an Argon2id key of a local passphrase, with `magic | params | salt` as associated
data. The plaintext is the 32-byte P-256 scalar followed by the 32-byte X25519 private key.

Limit of a Python host (as in ADR-007): the private scalars pass through immutable `bytes` while a
file is sealed or opened; they cannot be overwritten and live until the interpreter frees them.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from vcloak.crypto.keys import DEFAULT_PARAMS, Argon2Params, UnsealError

MAGIC = b"VCLKDEV1"
SCALAR_LEN = 32
SALT_LEN = 16
NONCE_LEN = 12
_PARAMS = struct.Struct("<III")
_HEADER_LEN = len(MAGIC) + _PARAMS.size + SALT_LEN
_SEALED_LEN = _HEADER_LEN + NONCE_LEN + 2 * SCALAR_LEN + 16


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _segment(obj: Any) -> str:
    return b64u(json.dumps(obj, separators=(",", ":")).encode())


class DeviceKey:
    """The ES256 key of one device. The private key never leaves this object except sealed."""

    def __init__(self, key: ec.EllipticCurvePrivateKey | None = None, *,
                 now: Callable[[], float] = time.time) -> None:
        self._key = key or ec.generate_private_key(ec.SECP256R1())
        self._now = now
        n = self._key.public_key().public_numbers()
        self.jwk: dict[str, str] = {"kty": "EC", "crv": "P-256", "x": b64u(n.x.to_bytes(32, "big")),
                                    "y": b64u(n.y.to_bytes(32, "big"))}
        # RFC 7638: the required members in lexicographic order, no whitespace
        canonical = json.dumps({k: self.jwk[k] for k in ("crv", "kty", "x", "y")}, separators=(",", ":"))
        self.thumbprint = b64u(hashlib.sha256(canonical.encode()).digest())

    def _sign(self, signing_input: str) -> str:
        r, s = decode_dss_signature(self._key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
        return b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

    def proof(self, method: str, url: str, token: str | None = None) -> str:
        """A fresh DPoP proof (RFC 9449) for one request to `url`; with `token`, bound to it by `ath`."""
        header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": self.jwk}
        claims: dict[str, Any] = {"htm": method, "htu": url, "iat": int(self._now()), "jti": b64u(os.urandom(16))}
        if token is not None:
            claims["ath"] = b64u(hashlib.sha256(token.encode()).digest())
        signing_input = f"{_segment(header)}.{_segment(claims)}"
        return f"{signing_input}.{self._sign(signing_input)}"

    def _scalar(self) -> bytes:
        return self._key.private_numbers().private_value.to_bytes(SCALAR_LEN, "big")


def _kek(passphrase: str, salt: bytes, params: Argon2Params) -> bytes:
    raw = passphrase.encode("utf-8")
    if not raw:
        raise ValueError("the passphrase must not be empty")
    return hash_secret_raw(secret=raw, salt=salt, time_cost=params.t, memory_cost=params.m_kib,
                           parallelism=params.p, hash_len=32, type=Type.ID)


def save_keyfile(path: str | Path, passphrase: str, device: DeviceKey, prekey: X25519PrivateKey, *,
                 params: Argon2Params = DEFAULT_PARAMS) -> Path:
    """Write the two private keys of a device to `path`, sealed under `passphrase` (atomic, mode 0600)."""
    params.check()
    salt, nonce = os.urandom(SALT_LEN), os.urandom(NONCE_LEN)
    header = MAGIC + _PARAMS.pack(params.t, params.m_kib, params.p) + salt
    secret = device._scalar() + prekey.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    blob = header + nonce + AESGCM(_kek(passphrase, salt, params)).encrypt(nonce, secret, header)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(blob)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def load_keyfile(path: str | Path, passphrase: str, *,
                 now: Callable[[], float] = time.time) -> tuple[DeviceKey, X25519PrivateKey]:
    """The device key and the prekey of a sealed key file; `UnsealError` for a wrong passphrase or file."""
    blob = Path(path).read_bytes()
    if len(blob) != _SEALED_LEN or blob[:len(MAGIC)] != MAGIC:
        raise UnsealError("not a V-cloak device key file")
    header, nonce, body = blob[:_HEADER_LEN], blob[_HEADER_LEN:_HEADER_LEN + NONCE_LEN], blob[_HEADER_LEN + NONCE_LEN:]
    params = Argon2Params(*_PARAMS.unpack_from(header, len(MAGIC)))
    params.check()
    try:
        secret = AESGCM(_kek(passphrase, header[-SALT_LEN:], params)).decrypt(nonce, body, header)
    except InvalidTag:
        raise UnsealError("wrong passphrase, or the device key file is corrupted") from None
    key = ec.derive_private_key(int.from_bytes(secret[:SCALAR_LEN], "big"), ec.SECP256R1())
    return DeviceKey(key, now=now), X25519PrivateKey.from_private_bytes(secret[SCALAR_LEN:])


def public_bytes(prekey: X25519PrivateKey) -> bytes:
    return prekey.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
