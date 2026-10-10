# M04 — GPU ChaCha20: tags, subkeys and bucket PRF
owner: Aditya · depends_on: M02, M03 · est_sessions: 2 · human_gates: upload the GPU job (~2 min)

## Goal
All ChaCha20-based server functions on the GPU, reading keys from device buffers only, bit-exact with M02.

## Required reading
- `ai/GPU_RUNNER.md` (§3–§5) and `.claude/skills/gpu-job/SKILL.md`
- `ai/ARCHITECTURE.md §5` · `ai/GPU_GUIDE.md §3 (ChaCha20)` · `src/vcloak/crypto/chacha_ref.py` (function signatures via grep)

## GPU execution (this module runs on the free runner)
This module's CUDA work cannot run on the laptop. Follow `ai/GPU_RUNNER.md` and the `gpu-job` skill:
1. **Prep session (local):** write/modify the `.cu` kernels **and their NumPy twins in `src/vcloak/gpu/sim.py`**;
   pass every correctness test under `VCLOAK_BACKEND=numpy`; commit; `python scripts/gpujob.py pack M04`;
   open the `GPU JOB READY` issue; set `BLOCKED_HUMAN`; hand off.
2. **Human (~2 min):** open `colab/VCloak_GPU_Runner.ipynb` on Colab (or Kaggle for long jobs), select a GPU
   runtime, upload `gpujobs/out/<job>.zip`, run all cells, drop `results_<job>.zip` into `gpujobs/inbox/`, type `continue`.
3. **Ingest session:** `python scripts/gpujob.py ingest`, apply this module's gates, record metrics
   (`backend: cupy`, with the runner and session id), audit, close.
**Simulator parity is an acceptance gate here:** every kernel this module adds must produce byte-identical
output on the GPU and under the `numpy` twin, over the sizes and seeds in `ai/TESTING.md §3`. A mismatch is a
real bug in one of the two — never "close enough".

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
