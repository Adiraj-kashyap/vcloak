"""M02 S5: client content crypto (X25519 + HKDF-SHA256 agreement, BLOCK padding, AES-256-GCM)."""
from __future__ import annotations

import pytest

from vcloak.config import BLOCK
from vcloak.crypto import client


def _pair(context: bytes = b"conv-1") -> tuple[bytes, bytes]:
    a_priv, a_pub = client.generate_prekey()
    b_priv, b_pub = client.generate_prekey()
    k_a = client.derive_content_key(a_priv, b_pub, client.transcript(a_pub, b_pub, context))
    k_b = client.derive_content_key(b_priv, a_pub, client.transcript(b_pub, a_pub, context))
    return k_a, k_b


def test_two_parties_agree() -> None:
    k_a, k_b = _pair()
    assert k_a == k_b and len(k_a) == 32
    assert _pair()[0] != k_a  # fresh prekeys, fresh key


def test_key_is_bound_to_the_transcript_and_to_the_parties() -> None:
    a_priv, a_pub = client.generate_prekey()
    b_priv, b_pub = client.generate_prekey()
    c_priv, c_pub = client.generate_prekey()
    k = client.derive_content_key(a_priv, b_pub, client.transcript(a_pub, b_pub, b"conv-1"))
    assert k != client.derive_content_key(a_priv, b_pub, client.transcript(a_pub, b_pub, b"conv-2"))
    assert k != client.derive_content_key(c_priv, b_pub, client.transcript(a_pub, b_pub, b"conv-1"))
    assert client.transcript(a_pub, b_pub, b"x") == client.transcript(b_pub, a_pub, b"x")
    assert client.transcript(a_pub, b_pub, b"x") != client.transcript(a_pub, c_pub, b"x")
    with pytest.raises(ValueError):
        client.transcript(a_pub, b_pub[:31])
    with pytest.raises(ValueError):
        client.derive_content_key(a_priv, bytes(32), b"")  # a low-order point gives an all-zero secret


@pytest.mark.parametrize("msg", [b"", b"a", b"hello\0\0", b"\x80", b"x\x80\0", bytes(BLOCK - 1), b"\xff" * (BLOCK - 1)])
def test_pad_round_trip(msg: bytes) -> None:
    padded = client.pad(msg)
    assert len(padded) == BLOCK and padded[len(msg)] == 0x80 and not any(padded[len(msg) + 1:])
    assert client.unpad(padded) == msg


def test_pad_rejects_what_does_not_fit_and_unpad_rejects_bad_padding() -> None:
    with pytest.raises(ValueError):
        client.pad(bytes(BLOCK))
    for bad in (bytes(BLOCK), b"abc" + bytes(BLOCK - 3), client.pad(b"a")[:-1], b""):
        with pytest.raises(client.ContentError):
            client.unpad(bad)
    assert client.unpad(client.pad(b"ab", block=16), block=16) == b"ab"


def test_every_payload_has_one_length_and_a_fresh_nonce() -> None:
    k, _ = _pair()
    payloads = [client.encrypt_content(k, msg) for msg in (b"", b"hi", bytes(BLOCK - 1), b"hi")]
    assert {len(p) for p in payloads} == {client.PAYLOAD_LEN} == {12 + BLOCK + 16}
    assert len({p[:12] for p in payloads}) == 4 and payloads[1] != payloads[3]


def test_encrypt_decrypt_between_the_two_parties() -> None:
    k_a, k_b = _pair()
    msg = "namaste — turn 7".encode()
    assert client.decrypt_content(k_b, client.encrypt_content(k_a, msg, aad=b"seq=7"), aad=b"seq=7") == msg


def test_tamper_is_an_error() -> None:
    k_a, k_b = _pair()
    payload = client.encrypt_content(k_a, b"secret", aad=b"hdr")
    for i in (0, 11, 12, 12 + BLOCK // 2, 12 + BLOCK - 1, 12 + BLOCK, len(payload) - 1):
        bad = bytearray(payload)
        bad[i] ^= 1
        with pytest.raises(client.ContentError):
            client.decrypt_content(k_b, bytes(bad), aad=b"hdr")
    for call in (lambda: client.decrypt_content(k_b, payload, aad=b"other"),
                 lambda: client.decrypt_content(_pair()[0], payload, aad=b"hdr"),
                 lambda: client.decrypt_content(k_b, payload[:-1], aad=b"hdr"),
                 lambda: client.decrypt_content(k_b, b"", aad=b"hdr")):
        with pytest.raises(client.ContentError):
            call()
