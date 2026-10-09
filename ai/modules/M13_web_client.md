# M13 — Minimal web client (WebCrypto, non-extractable keys)
owner: Abhishek · depends_on: M12 · est_sessions: 1 · human_gates: none · priority: optional for Review 3 (do after M14 if time is short)

## Goal
A single static page served by FastAPI that demonstrates the browser side of session security:
non-extractable ES256 keys in IndexedDB, DPoP headers, AES-GCM in the browser.

## Required reading
- `docs/API.md` · `src/vcloak/client/sdk.py` (to mirror the flows)

## Deliverables
`web/index.html`, `web/app.js`, `web/style.css`, a route serving `/web`, `tests/integration/test_web_static.py` (served + CSP headers),
`docs/DEMO.md` (web section).

## Steps
- **S1 Keys.** `crypto.subtle.generateKey({name:"ECDSA", namedCurve:"P-256"}, false, ["sign","verify"])`; store the CryptoKey in IndexedDB;
  check `exportKey` fails (displayed in the UI as proof).
- **S2 DPoP in JS.** Build the JWS (header typ/alg/jwk, claims htm/htu/iat/jti/ath) and convert the ECDSA signature to the raw 64-byte form.
- **S3 Chat UI.** Login, start a conversation (X25519 via WebCrypto if supported, otherwise the documented fallback: ECDH P-256 with an ADR),
  send/read, and a "server view" panel showing shuffled rows from a dev-only endpoint.
- **S4 Security headers.** CSP `default-src 'self'`, no inline scripts, HSTS in production mode.

## Audit checklist
- A1 A Python-SDK user and a web user can talk (manual demo recorded in docs/DEMO.md with screenshots in runs/).
- A2 Key export from the browser fails (screenshot/log). A3 The dev-only endpoint is disabled unless `--dev`. G1–G10.

## Next: M14
