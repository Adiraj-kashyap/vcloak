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

## Amendments
- 2026-10-11 (session 4). **S4 file format.** The spec fixes the field sizes but not the cipher or the params
  encoding. Implemented: `magic = b"VCLKSMK1"`, params = LE32 t | LE32 m_kib | LE32 p (12 B), AES-256-GCM over the
  32-byte key with `magic|params|salt` as associated data; 96 bytes in total. AES-GCM was chosen over
  ChaCha20-Poly1305 because `cryptography` can decrypt it straight into a `bytearray` (`update_into`), so the
  unsealed key never exists as an immutable `bytes` object. The KEK from Argon2 and the fresh key from `os.urandom`
  are still immutable `bytes` for a moment; this is part of the ADR-007 exposure window.
- 2026-10-11 (session 4). **`vcloak_keys.py rotate`** re-seals the same K_master under a new passphrase (fresh salt
  and nonce). It does not draw a new K_master: nothing in the system can re-key stored rows, so a new master would
  orphan them. `init` refuses to overwrite an existing sealed file for the same reason.
- 2026-10-11 (session 4). **S6 scanner rules.** "Any 32-byte hex/base64 run" is implemented as ≥64 hex characters,
  or ≥43 base64/base64url characters that contain a digit, an upper-case and a lower-case letter (without that
  condition long identifiers and paths match). Beyond the by-hash allow-list of the spec, a hex run is also accepted
  when it equals the SHA-256 of a scanned file, and whole files can be allow-listed by file hash (ISSUE-4). A
  digest the scanner cannot verify (a GPU job's `bundle_sha256`) needs `check_secrets.py --allow <id>` (ISSUE-5).
- 2026-10-11 (session 4). **S7.** The byte formats did not change, so the golden files were checked
  (`make_golden.py --check`: identical) and not regenerated. `aead_ref` sets IMPLEMENTED from whether
  `cryptography` imports, so the oracle still imports without it and then uses its NumPy stand-in.
