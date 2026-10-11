"""Device key store (ai/ARCHITECTURE.md §4, ADR-003, ADR-007).

`load_master` is the only place where K_master exists on the host, and only inside the caller's
`bytearray`: it is copied to VRAM directly from that buffer (no intermediate host copy), the buffer is
overwritten in place, the three subkeys are derived on the GPU, and the device copy of the master is
cleared. Afterwards K_tag, K_seq and K_bkt exist in device memory only; nothing in this module copies a
key buffer back to the host.

Under the `numpy` backend the "device" is host memory (the thread-model simulator, ADR-011): the same
steps run, for correctness tests only.
"""
from __future__ import annotations

import ctypes
from typing import Any

import numpy as np

from vcloak.gpu.kernels import (
    KEY_WORDS,
    SUBKEY_BKT,
    SUBKEY_SEQ,
    SUBKEY_TAG,
    gpu_derive_subkeys,
    subkey,
)
from vcloak.gpu.runtime import Backend, get_backend

MASTER_LEN = 4 * KEY_WORDS


class KeyStoreError(RuntimeError):
    """A key was requested from a store that is empty or has been zeroized."""


class DeviceKeyStore:
    """Holds the server subkeys in device memory. One store serves any number of engines."""

    def __init__(self, backend: Backend | None = None) -> None:
        self.backend = backend or get_backend()
        self._subkeys: Any | None = None

    def __repr__(self) -> str:  # never the key material
        return f"DeviceKeyStore(backend={self.backend.name!r}, ready={self.ready})"

    def __reduce__(self) -> Any:
        raise TypeError("a DeviceKeyStore cannot be pickled or copied")

    @property
    def ready(self) -> bool:
        return self._subkeys is not None

    def _clear(self, buf: Any) -> None:
        """Overwrite a device buffer with zeros (memset on the device, ai/GPU_GUIDE.md §8)."""
        if self.backend.is_gpu:
            cp = self.backend.xp
            # cudaMemset is ordered on the default stream only: finish the kernels that still read `buf`
            cp.cuda.get_current_stream().synchronize()
            cp.cuda.runtime.memset(buf.data.ptr, 0, buf.nbytes)
            cp.cuda.Stream.null.synchronize()
        else:
            buf.fill(0)

    def _upload(self, master: bytearray) -> Any:
        """H2D of the 32 master bytes as 8 little-endian words, read straight from the caller's buffer."""
        xp = self.backend.xp
        if not self.backend.is_gpu:
            return np.frombuffer(master, dtype="<u4").astype(np.uint32)
        d_master = xp.empty(KEY_WORDS, dtype=np.uint32)
        src = (ctypes.c_char * MASTER_LEN).from_buffer(master)
        try:
            d_master.data.copy_from_host(ctypes.c_void_p(ctypes.addressof(src)), MASTER_LEN)
        finally:
            del src  # release the buffer export
        return d_master

    def load_master(self, master: bytearray) -> None:
        """Copy `master` to the device, zero it in place, derive the subkeys on the device.

        `master` must be a 32-byte `bytearray`: immutable `bytes` cannot be overwritten, so they are
        refused. The host buffer is zeroed even when a later step fails.
        """
        if not isinstance(master, bytearray):
            raise TypeError("master must be a bytearray, so that it can be zeroized in place (ADR-007)")
        if len(master) != MASTER_LEN:
            raise ValueError(f"master must be {MASTER_LEN} bytes")
        if self.ready:
            self.zeroize()
        d_master = None
        try:
            d_master = self._upload(master)
        finally:
            master[:] = bytes(MASTER_LEN)
        try:
            self._subkeys = gpu_derive_subkeys(d_master)
        finally:
            self._clear(d_master)

    def zeroize(self) -> None:
        """Clear the subkeys in device memory and drop them. Safe to call more than once."""
        buf, self._subkeys = self._subkeys, None
        if buf is not None:
            self._clear(buf)

    def _key(self, index: int) -> Any:
        if self._subkeys is None:
            raise KeyStoreError("the key store is empty: call load_master first")
        return subkey(self._subkeys, index)

    @property
    def k_tag(self) -> Any:
        """Device view of K_tag (8 uint32 words). For kernel arguments only."""
        return self._key(SUBKEY_TAG)

    @property
    def k_seq(self) -> Any:
        return self._key(SUBKEY_SEQ)

    @property
    def k_bkt(self) -> Any:
        return self._key(SUBKEY_BKT)
