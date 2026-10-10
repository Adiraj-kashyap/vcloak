# M01 — Reference oracle port and golden vectors
owner: Abhishek · depends_on: M00 · est_sessions: 1 · human_gates: none

## Goal
Turn `seed/vcloak_oracle.py` into a tested reference package (`vcloak.oracle`) with deterministic golden
vectors. This package is the ground truth for every GPU test.

## Required reading
- `ai/ARCHITECTURE.md §4, §5` · `ai/TESTING.md §2, §3` · `ai/DECISIONS.md ADR-002, ADR-003`
- `seed/vcloak_oracle.py`: use `grep -n "^def \|^class " seed/vcloak_oracle.py` first, then read only the needed functions.

## Deliverables
`src/vcloak/oracle/reference.py` (bitonic schedule/sort, write_epoch_ref, read_window_ref, reshuffle_ref),
`src/vcloak/oracle/attacks.py` (order_recovery_attack incl. turn-order accuracy), `src/vcloak/oracle/stats.py`
(corrected χ², ideal-sampler calibration, Kendall band), `tests/unit/test_oracle_*.py`,
`tests/golden/oracle_perm_n{64,1024,65536}.json`, `scripts/make_golden.py`.

## Steps
- **S1 Port the bitonic network.** Copy `bitonic_schedule` / `bitonic_sort` (the SoA lexicographic version).
  Add `bitonic_pairs(n)` that yields the (i, l, asc) arrays per (k, j) using the pair indexing from GPU_GUIDE §3,
  and assert it produces the same pairs as the schedule. Check: unit tests on n = 2..2^12, compared with `np.lexsort`.
- **S2 Crypto profile hooks.** The seed uses HKDF/HMAC/AES-GCM. Replace every server-side use with calls into
  `vcloak.crypto.*_ref` stubs (implemented in M02). Until M02 exists, tests use a pure-NumPy ChaCha20
  reference written here in `oracle/chacha_np.py` (vectorised quarter-rounds). Check: RFC 8439 §2.3.2 block vector passes.
- **S3 Write/read/reshuffle references.** `write_epoch_ref(keys, epoch, batch, slots)`, `reshuffle_ref`,
  `read_window_ref`, following the ARCHITECTURE §5 byte formats exactly. Check: round-trip restoration test over 20 random conversations.
- **S4 Attacks and statistics.** Port `order_recovery_attack` (with turn-order accuracy and f), and the χ²
  (with the (n−1)/n correction) plus the ideal sampler. Check: the attack on a conventional layout gives τ = 1.0 and turn accuracy 1.0.
- **S5 Golden vectors.** `scripts/make_golden.py` writes permutation outputs for fixed test keys
  (`bytes(range(32))`), epochs {0, 1, 7}, n ∈ {64, 1024, 65536}, as hex/base64 in JSON with a `source` field.
  Check: re-running the script reproduces identical files (hash compare).

## Metrics to record
None (correctness only). Record test counts in the SESSION_LOG.

## Audit checklist
- A1 The pair indexing produces exactly the schedule's pairs for all n ≤ 2^12.
- A2 Bitonic output equals `np.lexsort` for random, sorted, reverse, all-equal and two-value inputs.
- A3 Golden files are deterministic (two generations hash-identical).
- A4 No server-side HKDF/HMAC/AES remains in `vcloak.oracle` (`grep -rn "HKDF\|hmac\|AESGCM" src/vcloak/oracle`).
- G1–G10.

## Presenter notes
1. Why does a bitonic network with unique keys give the same result as any correct sort?
2. What is the turn-order accuracy metric and why is it better than global τ?
3. Why correct the χ² statistic by (n−1)/n?

## Next: M02
