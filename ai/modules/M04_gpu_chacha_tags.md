# M04 — GPU ChaCha20: tags, subkeys and bucket PRF
owner: Aditya · depends_on: M02, M03 · est_sessions: 1 · human_gates: none

## Goal
All ChaCha20-based server functions on the GPU, reading keys from device buffers only, bit-exact with M02.

## Required reading
- `ai/ARCHITECTURE.md §5` · `ai/GPU_GUIDE.md §3 (ChaCha20)` · `src/vcloak/crypto/chacha_ref.py` (function signatures via grep)

## Deliverables
`kernels/chacha20.cuh` (quarter-round, 20-round block → 16 words), `kernels/chacha_tags.cu`
(`chacha_tags(key_dev, nonce_lo, nonce_hi, out_hi, out_lo, nblocks)`), `kernels/prf.cu`
(`derive_subkeys(master_dev, out_keys_dev)`, `bucket_prf(kbkt_dev, conv_ids, out_bucket, n, B)`),
wrappers in `gpu/kernels.py`, `tests/gpu/test_chacha.py`.

## Steps
- **S1 Block function.** `__device__ void chacha_block(const uint32_t key[8], uint32_t ctr, const uint32_t nonce[3], uint32_t out[16])`,
  with rotates via `__funnelshift_l` or shifts. Check: an RFC 8439 §2.3.2 vector via a 1-thread kernel.
- **S2 Tags kernel.** One thread per 64-byte block → 4 tags; counter = block index; nonce from `(epoch or window, domain)`.
  Output directly into the SoA `hi[]`/`lo[]` columns (little-endian words → uint64). Check: bit-exact with `tags_for_epoch` and
  `reshuffle_tags` for n ∈ {64, 2^16, 2^max}.
- **S3 Subkeys and bucket.** The `derive_subkeys` kernel (3 threads, one per label); `bucket_prf` (one thread per conv id).
  Keys are read from device pointers. Check: bit-exact with M02.
- **S4 Throughput smoke.** Quick GB/s of tag generation at 2^20 (real numbers come in M07).

## Audit checklist
- A1 RFC vectors pass on the GPU. A2 Bit-exact tags/subkeys/buckets vs M02 across sizes and seeds.
- A3 `check_oblivious.py` is clean. A4 No key is passed by value from the host in production wrappers (tests may upload test keys).
- G1–G10.

## Presenter notes
1. Why can ChaCha20's block function serve as a PRF for buckets and subkeys?
2. How are the epoch tags and re-shuffle tags domain-separated?
3. Why is ChaCha20 safer than table-based AES on a GPU?

## Next: M05
