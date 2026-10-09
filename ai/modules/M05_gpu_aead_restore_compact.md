# M05 — GPU AEAD-open, restore sort, oblivious compaction
owner: Aditya · depends_on: M04 · est_sessions: 2 · human_gates: none

## Goal
The read-path cryptography on the GPU (open seq_enc with ChaCha20-Poly1305) and the two composite sorts:
restore by (miss, seq, slot), and compaction by (is_dummy, position, slot).

## Required reading
- `ai/ARCHITECTURE.md §2, §5` · `ai/GPU_GUIDE.md §3 (Poly1305)` · `ai/CONVENTIONS.md §2.5`
- `src/vcloak/crypto/aead_ref.py` (signatures) · `src/vcloak/gpu/kernels.py` (existing wrappers, grep)

## Deliverables
`kernels/poly1305.cuh`, `kernels/aead_open.cu` (`aead_open_seq(kseq_dev, blobs, n, q_conv, out_hi, out_lo, out_ok)`),
`kernels/aead_seal.cu` (`aead_seal_seq` for the write path, nonces supplied by the host), wrappers:
`gpu_open_and_key(...)`, `gpu_restore_sort(...)`, `gpu_compact(...)`, tests `tests/gpu/test_aead.py`, `tests/gpu/test_restore.py`.

## Steps
- **S1 Poly1305 device code.** 26-bit limbs, clamp r, process 16-byte blocks including AAD and length blocks per
  RFC 8439 §2.8; the final reduction is by mask. Check: RFC 8439 §2.5.2 vector.
- **S2 AEAD seal/open.** One thread per row: keystream block 0 → Poly1305 key; block 1 → XOR the 16-byte pt;
  tag compare in constant time → `ok` (0/1). Output sort keys without branches:
  `miss = (1 - ok) | (uint64)(conv != q)`; `hi = miss`; `lo = seq & ~mask64(miss)` (seq zeroed on a miss). Check: bit-exact vs `aead_ref` on valid, tampered and random-dummy blobs.
- **S3 Restore sort.** Sort by `(hi = miss, lo = seq, slot)` with the M03 kernels; the first j rows are the conversation in order.
  Check: equals `read_window_ref` for 50 random windows including dummies and shared buckets.
- **S4 Compaction.** Sort by `(is_dummy, current position, slot)`; this preserves the random order among real slots.
  Check: equals the oracle's compaction.

## Audit checklist
- A1 RFC vectors (Poly1305, AEAD) pass on the GPU. A2 Bit-exact seal/open vs the reference, including tamper cases.
- A3 No branch on `ok`, `conv` or tag bytes (check_oblivious + manual review of poly1305.cuh).
- A4 The restore result equals the oracle for all test windows.
- G1–G10.

## Presenter notes
1. How is an authentication failure handled without branching?
2. Why does sorting on (is_dummy, position) keep the permutation uniform?
3. What does the server learn when it reads a window? (count j: public at the DB level anyway)

## Next: M06
