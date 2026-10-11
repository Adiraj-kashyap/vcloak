"""Fixed TEST keys (CONVENTIONS §3). Never used outside tests and golden-vector generation."""
from __future__ import annotations

from typing import Any

TEST_K_MASTER = bytes(range(32))


def dev_keystore(backend: Any = None) -> Any:
    """A DeviceKeyStore loaded with the fixed TEST master (ai/modules/M06 S1). Tests only.
    The import is deferred so that the key constants stay free of imports."""
    from vcloak.gpu.keystore import DeviceKeyStore

    store = DeviceKeyStore(backend)
    store.load_master(bytearray(TEST_K_MASTER))
    return store
