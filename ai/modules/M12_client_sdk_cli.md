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
