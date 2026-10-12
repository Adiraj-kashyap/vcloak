# M12 — Client SDK, CLI and two-user demo
owner: Abhishek · depends_on: M11 · est_sessions: 1 · human_gates: none

## Goal
A Python client that performs the full client side: key agreement, padding, AES-GCM, DPoP proofs, send/read.
Plus a scripted two-user chat demo that works end to end.

## Required reading
- `ai/ARCHITECTURE.md §2 (S0–S3, R4–R5)` · `docs/API.md` · `src/vcloak/crypto/client.py` (signatures)

## Deliverables
`src/vcloak/client/sdk.py` (`VcloakClient`: register, login, dpop_headers, publish_prekey, start_conversation,
send(text), read(win) → list[str], refresh), `src/vcloak/client/cli.py` (`vcloak-chat`),
`scripts/demo_two_users.py`, `tests/integration/test_two_users.py`.

## Steps
- **S1 SDK auth.** ES256 key generated per device (kept in memory; `--keyfile` optional, encrypted with a local passphrase),
  DPoP proof construction, token refresh.
- **S2 Conversation setup.** Prekey upload/fetch endpoints (add them to the service if missing, owned by M11's code;
  log an Amendment), X25519 + HKDF → K_content, and a conv_token derived client-side.
- **S3 Send/read.** Pad to BLOCK, AES-256-GCM with the sequence number inside the plaintext header, send; read windows
  and verify seq continuity client-side.
- **S4 Demo.** `demo_two_users.py`: Alice and Bob exchange 30 messages across ≥2 windows (use a short WINDOW_S in dev),
  both read back in order, and it prints a transcript. It also prints the corresponding DB rows (to show they're shuffled). Save to a run dir.

## Audit checklist
- A1 The two-user round trip is exact in order (test). A2 The server never receives plaintext (a test inspects stored payloads).
- A3 Client-side seq verification detects a reordered or missing message (test with a tampered server response). G1–G10.

## Presenter notes
1. What does the server see when Alice sends "hi"?
2. How does the client detect that the server dropped or reordered a message?
3. Where is the device key kept?

## Next: M13

## Amendments
- 2026-10-12 (session 24, ADR-019). The service had no prekey endpoints: `PUT /v1/prekeys` and
  `GET /v1/prekeys/{username}` were added to M11's code (session.py, models.py, app.py). The fetch takes no session,
  so that the server does not learn who asks for whose key.
- The plaintext header holds `version | sender | session | number`, not a bare sequence number: a random session id
  lets a restarted client number from 0 again, and the retry rule of ISSUE-23 (drop repeats) needs the sender.
- `read(win)` returns one window on its own; the reader that verifies continuity from the start of the conversation
  is `sync()` (`read()` without a window). Extra to the deliverables: `src/vcloak/client/device.py` (the device key and
  the sealed key file), `tests/unit/test_client_sdk.py`, `tests/security/test_prekeys.py`.
- The demo runs the service inside its own process (uvicorn on a loopback port) so that it can dump the store of
  either backend after the chat; `scripts/smoke_service.py` remains the check of `vcloak serve` as a separate process.
- The key file is sealed with Argon2id + AES-256-GCM (the construction of ADR-007), and holds the prekey as well as
  the ES256 key, so that a restarted client keeps its conversations.

