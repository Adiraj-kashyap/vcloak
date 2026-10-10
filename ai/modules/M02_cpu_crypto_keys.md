# M02 — CPU crypto references and key lifecycle
owner: Abhishek · depends_on: M01 · est_sessions: 1 · human_gates: none

## Goal
Byte-exact CPU references for every server-side construction (the ground truth for M04/M05), the
client content crypto, and the sealed-master-key lifecycle.

## Required reading
- `ai/ARCHITECTURE.md §5` · `ai/DECISIONS.md ADR-003, ADR-007` · `ai/CONVENTIONS.md §3` · `ai/TESTING.md §2`

## Deliverables
`src/vcloak/crypto/chacha_ref.py` (block, keystream, tags_for_epoch, reshuffle_tags, bucket_prf, derive_subkeys),
`src/vcloak/crypto/aead_ref.py` (seal_seq / open_seq via `cryptography` ChaCha20Poly1305),
`src/vcloak/crypto/keys.py` (create_sealed_master, unseal_master → bytearray; Argon2id t=3, m=64 MiB, p=4),
`src/vcloak/crypto/client.py` (X25519 prekeys, HKDF-SHA256 content key, pad/unpad BLOCK, AES-256-GCM),
`scripts/check_secrets.py` (G4), `scripts/vcloak_keys.py` (CLI: init/rotate a sealed master; passphrase via getpass),
`tests/golden/rfc8439_*.json`, `tests/unit/test_crypto_*.py`.

## Steps
- **S1 ChaCha20 reference.** A block function in NumPy (vectorised over blocks), plus a keystream. Validate against
  RFC 8439 §2.3.2 and §2.4.2 (vectors in golden JSON) AND against `cryptography`'s ChaCha20
  (OpenSSL 16-byte nonce = LE32 counter || 12-byte nonce). Check: all vectors pass.
- **S2 Derived constructions.** `derive_subkeys`, `tags_for_epoch`, `reshuffle_tags`, `bucket_prf` per ARCHITECTURE §5.
  Check: the tag for slot i equals bytes [16i:16i+16) of the keystream; bucket is uniform over B (χ² on 10^5 ids, p > 0.01).
- **S3 seq AEAD.** `seal_seq(k_seq, conv, seq)` → 44 B; `open_seq(k_seq, blob)` → (ok, conv, seq), never raising on a
  bad tag (it returns ok=False). Check: RFC 8439 §2.8.2 vector, round-trip, and tamper tests.
- **S4 Key lifecycle.** The sealed file format: `magic(8)|argon2 params|salt(16)|nonce(12)|ct+tag(48)`. `unseal_master`
  returns a `bytearray` that callers must zeroize. Check: wrong passphrase fails cleanly; the plaintext never appears in the file.
- **S5 Client crypto.** X25519 agreement + HKDF over the transcript → K_content; fixed BLOCK padding
  (`0x80` then zeros); AES-256-GCM with a random 96-bit nonce. Check: two-party agreement test; tamper → error.
- **S6 Secrets scanner.** `check_secrets.py` flags any 32-byte hex/base64 run in tracked files, logs and runs except
  allow-listed RFC test vectors (by hash). Check: it flags a planted key in a temp file and passes on the repo.
- **S7 Wire the oracle.** Point `vcloak.oracle` at these references and regenerate the golden files if the formats changed.
  Check: M01 tests still pass.

## Audit checklist
- A1 All RFC 8439 vectors pass (block, keystream, Poly1305, AEAD).
- A2 The NumPy ChaCha20 equals `cryptography` for 3 keys × 3 nonces × 1 MiB.
- A3 `open_seq` returns ok=False on a bad tag, with no exception and no early-exit branching on tag bytes in our code.
- A4 `check_secrets.py` is clean; `secrets/` is gitignored.
- G1–G10.

## Presenter notes
1. Why ChaCha20 as a PRF for the bucket instead of HMAC? (ADR-003)
2. What exactly is inside the 44-byte seq_enc?
3. What happens if the server restarts, and if the passphrase is lost?

## Next: M03
