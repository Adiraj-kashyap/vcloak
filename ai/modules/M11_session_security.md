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

## Next: M12
