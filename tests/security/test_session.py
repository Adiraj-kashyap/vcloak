"""M11 S1-S4: accounts and rate limits, tokens, DPoP verification, refresh rotation (the service object).

Time is a `FakeTime` the test moves; the client side is tests/dpop_client.py. Argon2id runs with a cheap
cost here: nothing in this file measures anything."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from dpop_client import Device, FakeTime, b64u, decode_segment, segment
from vcloak.service import session
from vcloak.service.session import (
    PROOF_CHECKS,
    TOKEN_CHECKS,
    PasswordParams,
    RateLimiter,
    SessionConfig,
    SessionService,
    TokenSet,
    Verdict,
    jwk_thumbprint,
    normalise_htu,
)

GOLDEN = Path(__file__).resolve().parent.parent / "golden" / "rfc7638_thumbprint.json"
CHEAP = PasswordParams(t=1, m_kib=64, p=1)  # tests only
URL = "https://vcloak.test/v1/read"
LOGIN_URL = "https://vcloak.test/v1/auth/login"
IP = "198.51.100.7"
PASSWORD = "correct horse battery"


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture
def clock() -> FakeTime:
    return FakeTime()


@pytest.fixture
def svc(clock: FakeTime) -> Any:
    service = SessionService(SessionConfig(password=CHEAP), now=clock)
    yield service
    service.close()


@pytest.fixture
def dev(clock: FakeTime) -> Device:
    return Device(clock)


def signed_in(svc: SessionService, dev: Device, name: str = "alice", ip: str = IP) -> TokenSet:
    """Register `name` (once) and log it in with the key of `dev`."""
    async def go() -> TokenSet:
        if name not in svc.accounts:
            assert (await svc.register(name, PASSWORD, ip=ip)).status == "ok"
        result = await svc.login(name, PASSWORD, ip=ip, method="POST", url=LOGIN_URL,
                                 proofs=[dev.proof("POST", LOGIN_URL)])
        assert result.status == "ok" and result.tokens is not None
        return result.tokens
    return run(go())


def check(svc: SessionService, dev: Device, token: str, **kw: Any) -> Verdict:
    method, url = kw.pop("method", "POST"), kw.pop("url", URL)
    authorization = kw.pop("authorization", f"DPoP {token}")
    return svc.verify(method, url, [dev.proof(kw.pop("proof_method", method), kw.pop("proof_url", url), token, **kw)],
                      authorization)


# ── S1: accounts ─────────────────────────────────────────────────────────────

def test_register_stores_an_argon2id_hash_with_its_parameters_and_a_salt_per_user(svc: SessionService) -> None:
    async def go() -> None:
        assert (await svc.register("alice", PASSWORD, ip=IP)).status == "ok"
        assert (await svc.register("bob", PASSWORD, ip=IP)).status == "ok"
        assert (await svc.register("alice", "another password", ip=IP)).status == "taken"
    run(go())
    a, b = svc.accounts.hash_of("alice"), svc.accounts.hash_of("bob")
    assert a is not None and b is not None
    assert a.startswith("$argon2id$v=19$m=64,t=1,p=1$") and b.startswith("$argon2id$v=19$m=64,t=1,p=1$")
    assert a != b  # the same password under two salts
    assert PASSWORD not in a and len(svc.accounts) == 2


def test_default_cost_is_the_rfc9106_second_option() -> None:
    assert PasswordParams() == PasswordParams(t=3, m_kib=65536, p=4)
    assert SessionConfig().access_ttl_s == 600 and SessionConfig().proof_skew_s == 60
    assert SessionConfig().jti_ttl_s == 300


@pytest.mark.parametrize("name, password", [("al", PASSWORD), ("Alice", PASSWORD), ("alice smith", PASSWORD),
                                            ("a" * 33, PASSWORD), ("alice", "short"), ("alice", "x" * 129)])
def test_register_refuses_names_and_passwords_outside_the_policy(svc: SessionService, name: str,
                                                                 password: str) -> None:
    assert run(svc.register(name, password, ip=IP)).status == "invalid"
    assert len(svc.accounts) == 0


def test_login_gives_one_answer_for_a_wrong_password_and_an_unknown_name(svc: SessionService, dev: Device) -> None:
    signed_in(svc, dev)

    async def go(name: str, password: str) -> str:
        return (await svc.login(name, password, ip=IP, method="POST", url=LOGIN_URL,
                                proofs=[dev.proof("POST", LOGIN_URL)])).status
    assert run(go("alice", "wrong password")) == "invalid_credentials"
    assert run(go("nobody", PASSWORD)) == "invalid_credentials"
    assert run(go("alice", PASSWORD)) == "ok"


def test_login_needs_a_valid_proof_and_a_bad_one_does_not_count_against_the_account(svc: SessionService,
                                                                                    dev: Device) -> None:
    signed_in(svc, dev)
    other = "https://vcloak.test/v1/auth/refresh"
    for _ in range(8):
        result = run(svc.login("alice", PASSWORD, ip=IP, method="POST", url=LOGIN_URL,
                               proofs=[dev.proof("POST", other)]))
        assert result.status == "invalid_proof" and result.verdict is not None
        assert result.verdict.failed == ("htu",)
    assert svc.login_account.retry_after("alice") == 0


def test_account_limit_stops_a_password_guessing_run_and_a_success_clears_it(svc: SessionService, dev: Device,
                                                                             clock: FakeTime) -> None:
    signed_in(svc, dev)
    signed_in(svc, dev, "bob")

    async def attempt(name: str, password: str, ip: str = IP) -> Any:
        return await svc.login(name, password, ip=ip, method="POST", url=LOGIN_URL,
                               proofs=[dev.proof("POST", LOGIN_URL)])
    limit = svc.config.login_account_max
    for _ in range(limit):
        assert run(attempt("alice", "guess guess")).status == "invalid_credentials"
    blocked = run(attempt("alice", PASSWORD))  # the right password is not tried any more
    assert blocked.status == "rate_limited" and 0 < blocked.retry_after <= svc.config.login_account_window_s
    assert run(attempt("alice", PASSWORD, ip="203.0.113.9")).status == "rate_limited"  # the limit is on the name
    assert run(attempt("bob", PASSWORD)).status == "ok"  # another account is not affected
    clock.advance(svc.config.login_account_window_s + 1)
    assert run(attempt("alice", PASSWORD)).status == "ok"
    for _ in range(limit - 1):
        assert run(attempt("alice", "guess guess")).status == "invalid_credentials"
    assert run(attempt("alice", PASSWORD)).status == "ok"  # a success in between clears the count
    assert svc.login_account.retry_after("alice") == 0


def test_parallel_guesses_cannot_outrun_the_account_limit(svc: SessionService, dev: Device) -> None:
    signed_in(svc, dev)

    async def go() -> list[str]:
        calls = [svc.login("alice", f"guess number {i}", ip=IP, method="POST", url=LOGIN_URL,
                           proofs=[dev.proof("POST", LOGIN_URL)]) for i in range(12)]
        return [r.status for r in await asyncio.gather(*calls)]
    statuses = run(go())
    assert statuses.count("invalid_credentials") == svc.config.login_account_max
    assert statuses.count("rate_limited") == 12 - svc.config.login_account_max


def test_address_limit_counts_every_attempt_whatever_the_name(svc: SessionService, dev: Device,
                                                              clock: FakeTime) -> None:
    async def attempt(i: int, ip: str = IP) -> Any:
        return await svc.login(f"user_{i}", PASSWORD, ip=ip, method="POST", url=LOGIN_URL,
                               proofs=[dev.proof("POST", LOGIN_URL)])
    for i in range(svc.config.login_ip_max):
        assert run(attempt(i)).status == "invalid_credentials"
    blocked = run(attempt(99))
    assert blocked.status == "rate_limited" and 0 < blocked.retry_after <= svc.config.login_ip_window_s
    assert run(attempt(99, ip="203.0.113.9")).status == "invalid_credentials"
    clock.advance(svc.config.login_ip_window_s + 1)
    assert run(attempt(100)).status == "invalid_credentials"


def test_register_is_limited_per_address(svc: SessionService) -> None:
    for i in range(svc.config.register_ip_max):
        assert run(svc.register(f"user_{i}", PASSWORD, ip=IP)).status == "ok"
    blocked = run(svc.register("one_more", PASSWORD, ip=IP))
    assert blocked.status == "rate_limited" and blocked.retry_after > 0
    assert run(svc.register("one_more", PASSWORD, ip="203.0.113.9")).status == "ok"


def test_rate_limiter_is_a_sliding_window() -> None:
    clock = FakeTime(1000.0)
    rl = RateLimiter(3, 10, clock)
    for dt in (0, 2, 2):
        clock.advance(dt)
        assert rl.retry_after("k") == 0
        rl.hit("k")
    assert rl.retry_after("k") == 6 and rl.retry_after("other") == 0  # the first hit leaves at t = 1010
    clock.advance(6)
    assert rl.retry_after("k") == 0
    rl.hit("k")
    assert rl.retry_after("k") == 2
    rl.reset("k")
    assert rl.retry_after("k") == 0 and len(rl) == 0
    with pytest.raises(ValueError):
        RateLimiter(0, 10)


def test_rate_limiter_drops_idle_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RateLimiter, "SWEEP_AT", 50)
    clock = FakeTime(0.0)
    rl = RateLimiter(2, 10, clock)
    for i in range(50):
        rl.hit(f"k{i}")
    clock.advance(11)
    rl.hit("late")
    assert len(rl) == 1


def test_a_changed_cost_rehashes_the_account_at_its_next_login() -> None:
    accounts = session.Accounts(CHEAP)
    accounts.add("alice", accounts.hash_password(PASSWORD))
    stronger = session.Accounts(PasswordParams(t=2, m_kib=128, p=1))
    stored = accounts.hash_of("alice")
    assert stored is not None
    stronger.add("alice", stored)
    assert not stronger.check("alice", "wrong password") and stronger.hash_of("alice") == stored
    assert stronger.check("alice", PASSWORD)
    assert (stronger.hash_of("alice") or "").startswith("$argon2id$v=19$m=128,t=2,p=1$")
    assert stronger.check("alice", PASSWORD)


# ── S2: tokens and the thumbprint ────────────────────────────────────────────

def test_rfc7638_thumbprint_vector() -> None:
    """A2: the example of RFC 7638 section 3.1 (the JWK and the expected value are copied from the RFC)."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert jwk_thumbprint(golden["jwk"]) == golden["thumbprint_sha256_b64url"]
    only_required = {k: golden["jwk"][k] for k in ("e", "kty", "n")}
    assert jwk_thumbprint(only_required) == golden["thumbprint_sha256_b64url"]


def test_ec_thumbprint_uses_the_required_members_only_in_lexicographic_order(dev: Device) -> None:
    assert jwk_thumbprint(dev.jwk) == dev.jkt
    shuffled = {"y": dev.jwk["y"], "kid": "phone", "x": dev.jwk["x"], "use": "sig", "crv": "P-256", "kty": "EC"}
    assert jwk_thumbprint(shuffled) == dev.jkt
    assert jwk_thumbprint(Device().jwk) != dev.jkt
    for bad in ({"kty": "EC", "crv": "P-256", "x": dev.jwk["x"]}, {"kty": "oct", "k": "AAAA"}, {},
                {"kty": ["EC"]}, {"kty": "EC", "crv": "P-256", "x": 1, "y": 2}):
        with pytest.raises(ValueError):
            jwk_thumbprint(bad)


def test_access_token_is_hs256_bound_to_the_key_and_lives_ten_minutes(svc: SessionService, dev: Device,
                                                                      clock: FakeTime) -> None:
    tokens = signed_in(svc, dev)
    h, p, tag = tokens.access_token.split(".")
    assert decode_segment(h) == {"alg": "HS256", "typ": "at+jwt"}
    claims = decode_segment(p)
    assert claims["sub"] == "alice" and claims["cnf"] == {"jkt": dev.jkt}
    assert claims["iat"] == int(clock()) and claims["exp"] - claims["iat"] == 600 == tokens.expires_in
    assert set(claims) == {"sub", "cnf", "fam", "iat", "exp"} and tokens.token_type == "DPoP"
    assert len(tag) == 43  # 32 bytes of HMAC-SHA256


def test_refresh_token_is_random_and_only_its_hash_is_kept(svc: SessionService, dev: Device) -> None:
    a, b = signed_in(svc, dev), signed_in(svc, dev)
    assert a.refresh_token != b.refresh_token and len(a.refresh_token) == 43
    keys = set(svc._refresh)
    assert hashlib.sha256(a.refresh_token.encode()).digest() in keys
    assert all(isinstance(k, bytes) and len(k) == 32 for k in keys)
    assert a.refresh_token.encode() not in keys
    families = {r.family for r in svc._refresh.values()}
    assert len(families) == 2  # one family per login


def test_a_token_of_another_server_secret_is_refused(dev: Device, clock: FakeTime) -> None:
    one, two = (SessionService(SessionConfig(password=CHEAP), now=clock) for _ in range(2))
    try:
        tokens = signed_in(one, dev)
        signed_in(two, dev)
        assert check(one, dev, tokens.access_token).ok
        refused = check(two, dev, tokens.access_token)
        assert "token_mac" in refused.failed and refused.error == "invalid_token"
    finally:
        one.close()
        two.close()


# ── S3: DPoP verification ────────────────────────────────────────────────────

def test_a_valid_request_is_accepted_and_names_its_session(svc: SessionService, dev: Device) -> None:
    tokens = signed_in(svc, dev)
    verdict = check(svc, dev, tokens.access_token)
    assert verdict.ok and verdict.failed_check is None and verdict.error is None
    assert verdict.sub == "alice" and verdict.jkt == dev.jkt and verdict.family
    assert verdict.challenge() == 'DPoP algs="ES256"'


def other_token(svc: SessionService, dev: Device) -> str:
    return signed_in(svc, dev, "carol").access_token


REFUSALS: dict[str, tuple[dict[str, Any], str, str]] = {
    # name: (how the request is bent, the first failed check, the RFC 9449 error)
    "htu_other_path": ({"proof_url": URL + "x"}, "htu", "invalid_dpop_proof"),
    "htu_other_host": ({"proof_url": "https://evil.test/v1/read"}, "htu", "invalid_dpop_proof"),
    "htu_other_scheme": ({"proof_url": "http://vcloak.test/v1/read"}, "htu", "invalid_dpop_proof"),
    "htu_not_a_string": ({"claims": {"htu": 7}}, "htu", "invalid_dpop_proof"),
    "htm_other_method": ({"proof_method": "GET"}, "htm", "invalid_dpop_proof"),
    "htm_lower_case": ({"proof_method": "post"}, "htm", "invalid_dpop_proof"),
    "iat_missing": ({"drop": ("iat",)}, "iat", "invalid_dpop_proof"),
    "iat_a_string": ({"claims": {"iat": "now"}}, "iat", "invalid_dpop_proof"),
    "iat_true": ({"claims": {"iat": True}}, "iat", "invalid_dpop_proof"),
    "jti_missing": ({"drop": ("jti",)}, "jti", "invalid_dpop_proof"),
    "jti_too_short": ({"jti": "abc"}, "jti", "invalid_dpop_proof"),
    "jti_not_a_string": ({"claims": {"jti": 12345678901234567890}}, "jti", "invalid_dpop_proof"),
    "typ_jwt": ({"header": {"typ": "JWT"}}, "typ", "invalid_dpop_proof"),
    "typ_missing": ({"drop": ("typ",)}, "typ", "invalid_dpop_proof"),
    "alg_hs256": ({"header": {"alg": "HS256"}}, "alg", "invalid_dpop_proof"),
    "alg_none": ({"header": {"alg": "none"}}, "alg", "invalid_dpop_proof"),
    "jwk_missing": ({"drop": ("jwk",)}, "jwk", "invalid_dpop_proof"),
    "jwk_other_curve": ({"header": {"jwk": {"kty": "EC", "crv": "P-384", "x": "AA", "y": "AA"}}}, "jwk",
                        "invalid_dpop_proof"),
    "jwk_point_off_the_curve": ({"header": {"jwk": {"kty": "EC", "crv": "P-256", "x": b64u(bytes(31) + b"\x01"),
                                                    "y": b64u(bytes(31) + b"\x01")}}}, "jwk", "invalid_dpop_proof"),
    "ath_missing": ({"drop": ("ath",)}, "ath", "invalid_dpop_proof"),
    "ath_of_nothing": ({"claims": {"ath": b64u(hashlib.sha256(b"").digest())}}, "ath", "invalid_dpop_proof"),
    "scheme_bearer": ({"authorization": "Bearer {token}"}, "authorization", "invalid_token"),
    "authorization_missing": ({"authorization": None}, "authorization", "invalid_token"),
    "authorization_two_tokens": ({"authorization": "DPoP {token} extra"}, "authorization", "invalid_token"),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_a_bent_request_is_refused_with_the_check_that_failed(svc: SessionService, dev: Device, case: str) -> None:
    how, failed_check, error = REFUSALS[case]
    how = dict(how)
    tokens = signed_in(svc, dev)
    if isinstance(how.get("authorization"), str):
        how["authorization"] = how["authorization"].format(token=tokens.access_token)
    verdict = check(svc, dev, tokens.access_token, **how)
    assert not verdict.ok and verdict.sub == "" and verdict.jkt == ""
    assert verdict.failed_check == failed_check and verdict.error == error
    assert verdict.challenge() == f'DPoP error="{error}", error_description="{failed_check}", algs="ES256"'
    assert set(verdict.failed) <= set(PROOF_CHECKS + TOKEN_CHECKS)
    assert check(svc, dev, tokens.access_token).ok  # the session itself is untouched


def test_jwk_with_a_private_member_is_refused(svc: SessionService, dev: Device) -> None:
    tokens = signed_in(svc, dev)
    verdict = check(svc, dev, tokens.access_token, header={"jwk": {**dev.jwk, "d": b64u(os.urandom(32))}})
    assert verdict.failed_check == "jwk"


def test_replayed_proof_is_refused(svc: SessionService, dev: Device) -> None:
    tokens = signed_in(svc, dev)
    proof = dev.proof("POST", URL, tokens.access_token)
    auth = f"DPoP {tokens.access_token}"
    assert svc.verify("POST", URL, [proof], auth).ok
    again = svc.verify("POST", URL, [proof], auth)
    assert again.failed == ("jti",) and again.error == "invalid_dpop_proof"


def test_stolen_token_with_the_attackers_own_key_is_refused(svc: SessionService, dev: Device,
                                                            clock: FakeTime) -> None:
    tokens = signed_in(svc, dev)
    attacker = Device(clock)
    verdict = check(svc, attacker, tokens.access_token)  # a correct proof, made with another key
    assert verdict.failed == ("key_binding",) and verdict.error == "invalid_token"


def test_proof_signed_by_another_key_than_its_jwk_is_refused(svc: SessionService, dev: Device,
                                                             clock: FakeTime) -> None:
    tokens = signed_in(svc, dev)
    verdict = check(svc, dev, tokens.access_token, signer=Device(clock))  # the owner's JWK, a forged signature
    assert verdict.failed == ("signature",)


def test_tampered_proof_is_refused(svc: SessionService, dev: Device) -> None:
    tokens = signed_in(svc, dev)
    h, b, s = dev.proof("POST", URL, tokens.access_token).split(".")
    body = decode_segment(b)
    body["htu"] = URL  # the same claims, encoded again: other bytes than the signed ones
    bent = f"{h}.{segment({**body, 'extra': 1})}.{s}"
    assert svc.verify("POST", URL, [bent], f"DPoP {tokens.access_token}").failed == ("signature",)
    flipped = f"{h}.{b}.{s[:-2]}{'AA' if not s.endswith('AA') else 'BB'}"
    assert svc.verify("POST", URL, [flipped], f"DPoP {tokens.access_token}").failed == ("signature",)


@pytest.mark.parametrize("offset, ok", [(0, True), (-60, True), (60, True), (-61, False), (61, False),
                                        (-300, False), (3600, False)])
def test_iat_window_is_sixty_seconds_either_way(svc: SessionService, dev: Device, clock: FakeTime, offset: int,
                                                ok: bool) -> None:
    tokens = signed_in(svc, dev)
    verdict = check(svc, dev, tokens.access_token, iat=clock() + offset)
    assert verdict.ok is ok
    if not ok:
        assert verdict.failed == ("iat",)


def test_expired_access_token_is_refused(svc: SessionService, dev: Device, clock: FakeTime) -> None:
    tokens = signed_in(svc, dev)
    clock.advance(svc.config.access_ttl_s - 1)
    assert check(svc, dev, tokens.access_token).ok
    clock.advance(1)
    verdict = check(svc, dev, tokens.access_token)  # a fresh proof for a token that has run out
    assert verdict.failed == ("token_exp",) and verdict.error == "invalid_token"


def test_tampered_access_token_is_refused(svc: SessionService, dev: Device) -> None:
    tokens = signed_in(svc, dev)
    h, p, tag = tokens.access_token.split(".")
    claims = decode_segment(p)
    claims["sub"] = "admin"
    forged = f"{h}.{b64u(json.dumps(claims, separators=(',', ':')).encode())}.{tag}"
    assert check(svc, dev, forged).failed == ("token_mac",)
    longer = {**claims, "sub": "alice", "exp": claims["exp"] + 86400}
    assert check(svc, dev, f"{h}.{b64u(json.dumps(longer, separators=(',', ':')).encode())}.{tag}").failed == (
        "token_mac",)
    none = f"{segment({'alg': 'none', 'typ': 'at+jwt'})}.{p}."
    assert check(svc, dev, none).failed[:2] == ("token_format", "token_mac")
    for junk in ("", "a.b", "a.b.c.d", "....", "not a token at all"):
        verdict = check(svc, dev, junk, authorization=f"DPoP {junk}")
        assert not verdict.ok and verdict.error == "invalid_token"


def test_proof_for_another_token_is_refused(svc: SessionService, dev: Device) -> None:
    tokens = signed_in(svc, dev)
    second = signed_in(svc, dev).access_token
    proof = dev.proof("POST", URL, second)  # the hash of another token of the same key
    assert svc.verify("POST", URL, [proof], f"DPoP {tokens.access_token}").failed == ("ath",)


def test_every_check_is_evaluated_before_the_decision(svc: SessionService, dev: Device, clock: FakeTime,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = signed_in(svc, dev)
    verified: list[int] = []
    real = session._es256_ok

    def counting(*a: Any) -> bool:
        verified.append(1)
        return real(*a)
    monkeypatch.setattr(session, "_es256_ok", counting)
    verdict = check(svc, dev, tokens.access_token, proof_method="GET", proof_url=URL + "x", iat=clock() - 900,
                    jti="short", header={"typ": "JWT"})
    assert verdict.failed == ("typ", "htm", "htu", "iat", "jti") and len(verified) == 1
    # nothing usable at all: every check is still computed, the signature included
    for proofs in ([], ["garbage"], ["a.b.c"], ["..."], ["x" * 5000], [dev.proof("POST", URL), dev.proof("POST", URL)]):
        before = len(verified)
        verdict = svc.verify("POST", URL, proofs, None)
        assert verdict.failed_check == "proof_format" and len(verified) == before + 1
        assert {"proof_format", "authorization", "token_format", "token_mac", "token_exp", "token_revoked",
                "key_binding", "ath"} <= set(verdict.failed)
    assert set(svc.verify("POST", URL, [], None).failed) == set(PROOF_CHECKS + TOKEN_CHECKS)


def test_a_refused_request_does_not_spend_its_jti(svc: SessionService, dev: Device) -> None:
    tokens = signed_in(svc, dev)
    jti = b64u(os.urandom(16))
    assert check(svc, dev, tokens.access_token, jti=jti, proof_method="GET").failed == ("htm",)
    assert check(svc, dev, tokens.access_token, jti=jti).ok
    assert check(svc, dev, tokens.access_token, jti=jti).failed == ("jti",)


def test_jti_cache_forgets_after_300_seconds(svc: SessionService, dev: Device, clock: FakeTime) -> None:
    tokens = signed_in(svc, dev)
    for _ in range(5):
        assert check(svc, dev, tokens.access_token).ok
    assert len(svc._jti) == 6  # five requests and the login
    assert all(isinstance(k, bytes) and len(k) == 32 for k in svc._jti)  # digests, not the jti values
    clock.advance(svc.config.jti_ttl_s - 1)
    assert check(svc, dev, tokens.access_token).ok and len(svc._jti) == 7
    clock.advance(1)
    assert check(svc, dev, tokens.access_token).ok and len(svc._jti) == 2


@pytest.mark.parametrize("claimed", ["https://vcloak.test/v1/read", "HTTPS://VCLOAK.TEST/v1/read",
                                     "https://vcloak.test:443/v1/read", "https://vcloak.test/v1/read?x=1#top"])
def test_htu_is_compared_in_normal_form(svc: SessionService, dev: Device, claimed: str) -> None:
    tokens = signed_in(svc, dev)
    assert check(svc, dev, tokens.access_token, proof_url=claimed, url=URL + "?page=2").ok


def test_normalise_htu() -> None:
    assert normalise_htu("HTTP://Example.COM:80") == "http://example.com/"
    assert normalise_htu("http://example.com:8000/a/b?q#f") == "http://example.com:8000/a/b"
    assert normalise_htu("https://[::1]:8443/x") == "https://[::1]:8443/x"
    assert normalise_htu("https://example.com/V1/Read") != normalise_htu("https://example.com/v1/read")
    for bad in (None, 7, "", "/v1/read", "ftp://example.com/x", "https://user:pw@example.com/x",
                "https://example.com:notaport/x", "https://" + "a" * 3000):
        assert normalise_htu(bad) is None


def test_public_origin_replaces_the_received_origin(dev: Device, clock: FakeTime) -> None:
    svc = SessionService(SessionConfig(password=CHEAP, public_origin="https://chat.example/"), now=clock)
    try:
        assert svc.request_url("http://127.0.0.1:8000/v1/read?x=1", "/v1/read") == "https://chat.example/v1/read"
    finally:
        svc.close()
    plain = SessionService(SessionConfig(password=CHEAP), now=clock)
    assert plain.request_url("http://127.0.0.1:8000/v1/read", "/v1/read") == "http://127.0.0.1:8000/v1/read"


def test_verify_never_raises_on_hostile_input(svc: SessionService, dev: Device) -> None:
    tokens = signed_in(svc, dev)
    deep = b64u(b"[" * 3000 + b"]" * 3000)
    proofs = ["..", "a..b", f"{deep}.{deep}.{deep}", f"{segment([1])}.{segment('x')}.{b64u(bytes(64))}",
              f"{segment({'jwk': 'x', 'typ': 1, 'alg': None})}.{segment({'iat': 1e400, 'jti': {}})}.{b64u(bytes(64))}",
              f"{segment({'jwk': {'kty': 'EC', 'crv': 'P-256', 'x': 5, 'y': []}})}.{segment({})}.AA",
              "é.ü.ß", "\x00.\x00.\x00", "=.=.="]
    for proof in proofs:
        for auth in (None, "", "DPoP", "DPoP ", f"DPoP {tokens.access_token}", "DPoP é.ü.ß", "Basic abc"):
            verdict = svc.verify("POST", URL, [proof], auth)
            assert not verdict.ok and verdict.failed
    assert not svc.verify("POST", "not a url", [dev.proof("POST", "not a url", tokens.access_token)],
                          f"DPoP {tokens.access_token}").ok


def test_token_request_proof_needs_no_token_but_every_proof_check(svc: SessionService, dev: Device) -> None:
    ok = svc.verify("POST", LOGIN_URL, [dev.proof("POST", LOGIN_URL)], token_required=False)
    assert ok.ok and ok.jkt == dev.jkt and ok.sub == "" and ok.family == ""
    bad = svc.verify("POST", LOGIN_URL, [dev.proof("GET", LOGIN_URL)], token_required=False)
    assert bad.failed == ("htm",)
    assert set(svc.verify("POST", LOGIN_URL, [], token_required=False).failed) == set(PROOF_CHECKS)


# ── S4: refresh rotation, reuse detection, logout ────────────────────────────

def test_rotation_gives_a_new_pair_in_the_same_family(svc: SessionService, dev: Device, clock: FakeTime) -> None:
    first = signed_in(svc, dev)
    family = check(svc, dev, first.access_token).family
    clock.advance(5)
    second, reason = svc.refresh(first.refresh_token, dev.jkt)
    assert reason == "rotated" and second is not None
    assert second.refresh_token != first.refresh_token and second.access_token != first.access_token
    verdict = check(svc, dev, second.access_token)
    assert verdict.ok and verdict.family == family and verdict.sub == "alice"
    third, reason = svc.refresh(second.refresh_token, dev.jkt)
    assert reason == "rotated" and third is not None


def test_reuse_of_a_spent_refresh_token_revokes_the_family(svc: SessionService, dev: Device,
                                                           caplog: pytest.LogCaptureFixture,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    first = signed_in(svc, dev)
    elsewhere = signed_in(svc, dev)  # a second login of the same account: another family
    second, _ = svc.refresh(first.refresh_token, dev.jkt)
    assert second is not None
    assert check(svc, dev, second.access_token).ok
    monkeypatch.setattr(logging.getLogger("vcloak"), "propagate", True)
    with caplog.at_level(logging.WARNING, logger="vcloak"):
        assert svc.refresh(first.refresh_token, dev.jkt) == (None, "reuse")
    # the newest token of the family is dead too, and so are the access tokens of the family
    assert svc.refresh(second.refresh_token, dev.jkt) == (None, "family_revoked")
    assert svc.refresh(first.refresh_token, dev.jkt) == (None, "family_revoked")
    for token in (first.access_token, second.access_token):
        refused = check(svc, dev, token)
        assert refused.failed == ("token_revoked",) and refused.error == "invalid_token"
    assert check(svc, dev, elsewhere.access_token).ok
    assert svc.refresh(elsewhere.refresh_token, dev.jkt)[1] == "rotated"
    assert [r.getMessage() for r in caplog.records] == ["event=family_revoked error=refresh_reuse"]


def test_refresh_with_another_key_is_refused_and_does_not_spend_the_token(svc: SessionService, dev: Device,
                                                                          clock: FakeTime) -> None:
    tokens = signed_in(svc, dev)
    thief = Device(clock)
    assert svc.refresh(tokens.refresh_token, thief.jkt) == (None, "key_binding")
    assert svc.refresh(tokens.refresh_token, "") == (None, "key_binding")
    assert svc.refresh(tokens.refresh_token, dev.jkt)[1] == "rotated"


def test_unknown_and_expired_refresh_tokens(svc: SessionService, dev: Device, clock: FakeTime) -> None:
    tokens = signed_in(svc, dev)
    for junk in ("", "x", b64u(os.urandom(32)), tokens.refresh_token + "A", "é" * 43):
        assert svc.refresh(junk, dev.jkt) == (None, "unknown")
    clock.advance(svc.config.refresh_ttl_s)
    assert svc.refresh(tokens.refresh_token, dev.jkt)[0] is None
    signed_in(svc, dev)  # issuing forgets what has run out
    assert svc.refresh(tokens.refresh_token, dev.jkt) == (None, "unknown")
    assert len(svc._refresh) == 1 and len(svc._families) == 1


def test_logout_revokes_the_family_and_tells_the_listeners_once(svc: SessionService, dev: Device,
                                                                caplog: pytest.LogCaptureFixture,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = signed_in(svc, dev)
    family = check(svc, dev, tokens.access_token).family
    heard: list[str] = []
    svc.on_family_revoked(heard.append)
    monkeypatch.setattr(logging.getLogger("vcloak"), "propagate", True)
    with caplog.at_level(logging.DEBUG, logger="vcloak"):
        assert svc.revoke_family(family) is True
        assert svc.revoke_family(family) is False
        assert svc.revoke_family("no-such-family") is False
    assert heard == [family] and caplog.records == []  # a logout is not a log line
    assert check(svc, dev, tokens.access_token).failed == ("token_revoked",)
    assert svc.refresh(tokens.refresh_token, dev.jkt) == (None, "family_revoked")


def test_session_module_knows_no_content_or_engine_key() -> None:
    """A4: the session code never names a message key or imports the engine or the crypto of the store."""
    source = Path(session.__file__).read_text(encoding="utf-8")
    for word in ("K_content", "K_master", "K_tag", "K_seq", "K_bkt", "vcloak.gpu", "vcloak.crypto", "keystore"):
        assert word not in source
