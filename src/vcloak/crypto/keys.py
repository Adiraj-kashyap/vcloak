"""Sealed master key lifecycle (ADR-007).

K_master exists in plaintext only in memory. On disk it is sealed under a key-encryption key derived from
a passphrase with Argon2id, in a 96-byte file:

    magic(8) | argon2 params: LE32 t, LE32 m_kib, LE32 p (12) | salt(16) | nonce(12) | ct+tag(48)

The seal is AES-256-GCM over the 32-byte key with `magic | params | salt` as associated data, so a
changed parameter or salt fails authentication. `unseal_master` decrypts straight into a `bytearray`,
which the caller must `zeroize` after copying the key to the GPU.

Limits of a Python host (the boot-time exposure window of ADR-007): `os.urandom` and Argon2 return
immutable `bytes` (the fresh key at creation, the KEK at every seal/unseal), which cannot be overwritten
and live until the interpreter frees them.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"VCLKSMK1"
KEY_LEN = 32
SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16
_PARAMS = struct.Struct("<III")
HEADER_LEN = len(MAGIC) + _PARAMS.size + SALT_LEN  # authenticated, not encrypted
SEALED_LEN = HEADER_LEN + NONCE_LEN + KEY_LEN + TAG_LEN  # 96
_GCM_SLACK = 15  # update_into needs len(data) + block_size - 1 bytes


class UnsealError(ValueError):
    """The sealed key file is malformed, or the passphrase is wrong. Carries no key material."""


@dataclass(frozen=True)
class Argon2Params:
    t: int = 3
    m_kib: int = 64 * 1024
    p: int = 4

    def check(self) -> None:
        """Bounds on what a sealed file may ask this host to compute."""
        if not (1 <= self.t <= 64 and 8 * self.p <= self.m_kib <= 4 * 1024 * 1024 and 1 <= self.p <= 64):
            raise UnsealError("Argon2id parameters out of range")


DEFAULT_PARAMS = Argon2Params()


def zeroize(buf: bytearray) -> None:
    """Overwrite a key buffer in place."""
    buf[:] = bytes(len(buf))


def _passphrase_bytes(passphrase: str | bytes) -> bytes:
    raw = passphrase.encode("utf-8") if isinstance(passphrase, str) else bytes(passphrase)
    if not raw:
        raise ValueError("the passphrase must not be empty")
    return raw


def _kek(passphrase: str | bytes, salt: bytes, params: Argon2Params) -> bytes:
    return hash_secret_raw(secret=_passphrase_bytes(passphrase), salt=salt, time_cost=params.t,
                           memory_cost=params.m_kib, parallelism=params.p, hash_len=KEY_LEN, type=Type.ID)


def seal_master(master: bytes | bytearray, passphrase: str | bytes,
                params: Argon2Params = DEFAULT_PARAMS) -> bytes:
    """The 96-byte sealed form of `master` under `passphrase`, with a fresh salt and nonce."""
    if len(master) != KEY_LEN:
        raise ValueError("K_master must be 32 bytes")
    params.check()
    salt, nonce = os.urandom(SALT_LEN), os.urandom(NONCE_LEN)
    header = MAGIC + _PARAMS.pack(params.t, params.m_kib, params.p) + salt
    enc = Cipher(algorithms.AES(_kek(passphrase, salt, params)), modes.GCM(nonce)).encryptor()
    enc.authenticate_additional_data(header)
    ct = enc.update(master) + enc.finalize()
    return header + nonce + ct + enc.tag


def unseal_blob(blob: bytes, passphrase: str | bytes) -> bytearray:
    """K_master from a sealed blob, as a `bytearray` the caller must zeroize."""
    if len(blob) != SEALED_LEN or blob[:len(MAGIC)] != MAGIC:
        raise UnsealError("not a V-cloak sealed master key file")
    header, body = blob[:HEADER_LEN], blob[HEADER_LEN:]
    params = Argon2Params(*_PARAMS.unpack_from(header, len(MAGIC)))
    params.check()
    nonce, ct, tag = body[:NONCE_LEN], body[NONCE_LEN:-TAG_LEN], body[-TAG_LEN:]
    kek = _kek(passphrase, header[-SALT_LEN:], params)
    dec = Cipher(algorithms.AES(kek), modes.GCM(nonce, tag)).decryptor()
    dec.authenticate_additional_data(header)
    buf = bytearray(KEY_LEN + _GCM_SLACK)
    dec.update_into(ct, buf)
    try:
        dec.finalize()
    except InvalidTag:
        zeroize(buf)
        raise UnsealError("wrong passphrase, or the sealed key file is corrupted") from None
    master = buf[:KEY_LEN]
    zeroize(buf)
    return master


def _write_atomic(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(blob)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def create_sealed_master(path: str | Path, passphrase: str | bytes, *, params: Argon2Params = DEFAULT_PARAMS,
                         overwrite: bool = False) -> Path:
    """Draw a fresh K_master, seal it under `passphrase` and write only the sealed form to `path`."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists; a new master key would orphan every stored row")
    master = bytearray(os.urandom(KEY_LEN))
    try:
        blob = seal_master(master, passphrase, params)
    finally:
        zeroize(master)
    _write_atomic(path, blob)
    return path


def unseal_master(path: str | Path, passphrase: str | bytes) -> bytearray:
    """K_master from the sealed file at `path`, as a `bytearray` the caller must zeroize."""
    return unseal_blob(Path(path).read_bytes(), passphrase)


def reseal_master(path: str | Path, old_passphrase: str | bytes, new_passphrase: str | bytes, *,
                  params: Argon2Params = DEFAULT_PARAMS) -> Path:
    """Passphrase rotation: the same K_master sealed under `new_passphrase` with a fresh salt and nonce."""
    path = Path(path)
    master = unseal_master(path, old_passphrase)
    try:
        blob = seal_master(master, new_passphrase, params)
    finally:
        zeroize(master)
    _write_atomic(path, blob)
    return path
