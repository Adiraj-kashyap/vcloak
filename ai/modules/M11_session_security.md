# M11 — Session security: DPoP, refresh rotation, WS tickets, log redaction (E5)
owner: Divyansh · depends_on: M10 · est_sessions: 2 · human_gates: none

## Goal
The Review-2 answer implemented in the real service and verified with an attack matrix.

## Required reading
- `ai/PROJECT_BRIEF.md §3` · `ai/CONVENTIONS.md §4` · `seed/vcloak_oracle.py` session section
  (grep `class SessionServer` and `def session_tests`) · RFC 9449 §4.2–4.3 and RFC 7638 §3 (summaries in your own words)

## Deliverables
`src/vcloak/service/session.py` (users, Argon2id login, token issue, DPoP verify, jti cache, refresh families,
WS tickets), routes `/v1/auth/register|login|refresh|logout|ws-ticket`, a WebSocket `/v1/ws`,
`logsafe.py` (final allow-list), `tests/security/test_session_matrix.py`, `tests/security/test_logsafe.py`,
`results/session/e5_matrix.json`, `docs/API.md` (auth section).

## Steps
- **S1 Accounts.** Register/login with Argon2id (argon2-cffi; per-user salt; parameters stored), per-IP and per-account rate limits.
- **S2 Tokens.** Access token (JWS HS256 over the server secret, or opaque + a server-side table; choose and write an ADR), 10 min,
  `cnf.jkt` = the RFC 7638 thumbprint of the client's ES256 JWK. Refresh tokens: single-use, with a family id.
- **S3 DPoP verification middleware.** Verify the ES256 signature, `typ=dpop+jwt`, jwk in the header, `htm`, `htu` (normalised),
  `iat` within ±60 s, `jti` unseen in a 300 s cache, `ath` = SHA-256(access token), and `jkt` binding. Evaluate all checks,
  then decide (no early exit before the signature check). Return 401 with a `WWW-Authenticate: DPoP error=...` header.
- **S4 Refresh rotation + reuse detection.** Reusing a spent token revokes the whole family. Logout revokes the family and closes WebSockets.
- **S5 WebSocket tickets.** A one-time ticket valid for 30 s, bound to jkt, and required for `/v1/ws`; the server pushes at epoch cadence.
- **S6 Attack matrix (E5).** At least the 12 scenarios from the seed, plus: a ticket reused, a ticket from a different key,
  and a login brute force hitting the rate limit. Save `results/session/e5_matrix.json` (scenario, expected, observed, failed_check).
- **S7 Log redaction.** Allow-list enforcement plus a test that drives traffic and greps the captured logs for conv tokens,
  bucket ids, jti values and tokens.

## Metrics to record
`SEC-E5-PASS` (x/y scenarios behaving as expected), `SEC-DPOP-VERIFY-US` (median verify time, CPU perf_counter).

## Audit checklist
- A1 E5 matrix: every scenario is as expected; each rejected case names the correct failed check.
- A2 The RFC 7638 thumbprint vector passes. A3 Logs contain no forbidden fields (test).
- A4 The session code never sees K_content or any GPU key (grep). G1–G10.

## Presenter notes
1. What does DPoP add over a bearer JWT? Demonstrate the stolen-token case.
2. How is refresh-token theft detected?
3. Why must logs never contain conversation ids or bucket numbers?

## Amendments
- 2026-10-12 (session 22, S1-S4): what was built differs from the text above in these points (ADR-017).
  - S2: the access token is the JWS HS256 option. It carries one claim more, `fam` (the refresh family of the login),
    and verification has one check more, `token_revoked`, so that a logout or a detected reuse ends the access
    tokens of that login at once.
  - S3: 16 named checks (`proof_format`, `typ`, `alg`, `jwk`, `signature`, `htm`, `htu`, `iat`, `jti`, `authorization`,
    `token_format`, `token_mac`, `token_exp`, `token_revoked`, `key_binding`, `ath`). The verification is a function the
    routes call through a FastAPI dependency, not an ASGI middleware. The server nonce of RFC 9449 section 8 is not
    used; the replay defence is `iat` plus the jti cache. The 401 names the first failed check in the body too.
  - S4: logout revokes the family; closing WebSockets is S5 (the hook `on_family_revoked` exists, nothing listens yet).
  - `create_app(backend, sessions=...)` switches the session routes and the check on. `vcloak serve` does not pass a
    `SessionService` yet: the CLI switch, the two smoke scripts and the loopback rule are S5 work.
  - Accounts, refresh families, the jti cache and the rate limits are in memory (ISSUE-26).
  - Extra files: `tests/dpop_client.py` (an independent ES256/DPoP client for the tests and the S6 matrix),
    `tests/security/test_session.py`, `tests/security/test_session_api.py`, `tests/golden/rfc7638_thumbprint.json`.
  - Required reading: RFC 7638 section 3 and RFC 9449 section 4.3 were read from rfc-editor.org this session; the
    thumbprint vector is copied from the RFC text by a script, not typed.

## Next: M12
