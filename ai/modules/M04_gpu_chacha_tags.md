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

## Amendments
2026-10-11 (session 7, prep). Where the build differs from the text above, and why:
- **Types and nonce split.** The kernels use the `u32`/`u64` typedefs of `common.cuh`. `chacha_tags` takes
  `u64 nonce_lo` (the epoch or the window, nonce words 0-1) and `u32 nonce_hi` (the domain word, nonce word 2:
  0 for epoch tags, 0x80000000 for re-shuffle tags, i.e. LE32 of the suffixes in ARCHITECTURE §5).
- **S1 kernel.** The RFC vector needs counter 1 and a free nonce, so the one-thread kernel is a general
  `chacha_blocks(key, nonce, out, counter0, nblocks)` in `chacha_tags.cu` (wrapper `gpu_chacha_blocks`).
- **Guards.** Every kernel keeps `if (t >= nblocks | n | 3) return;` on the thread id and a public bound, so a
  launch rounded up to whole blocks cannot write out of bounds.
- **Bucket reduction.** `bucket_prf` does not use `%` on the PRF output. `mod_public(w, B)` in `common.cuh` is a
  Barrett reduction whose only division has public operands (2^64 - 1 and B), followed by one masked subtraction.
  It equals `w % B` for every 32-bit w (tested at the edge values, in the twin and in the C source).
- **Ranges.** `B` is a `u32`, so the wrapper accepts n_buckets in [1, 2^32 - 1]; M02's reference also accepts
  2^32. Tag columns must hold a multiple of 4 slots (one block is 4 tags); M02's reference accepts any n.
- **Wrappers.** `gpu_tags(key_dev, nonce64, domain, hi, lo)` fills existing columns in place;
  `gpu_tags_for_epoch` / `gpu_reshuffle_tags` allocate them. `gpu_derive_subkeys` returns one 24-word device buffer
  and `subkey(keys_dev, SUBKEY_TAG | SUBKEY_SEQ | SUBKEY_BKT)` is a view of it. A4 is enforced, not only followed:
  a key given as `bytes`, `bytearray` or `memoryview` raises `TypeError`.
- **Twins.** As in M03 they take `grid=` and `block=`. They are written from the kernel source and do not call
  `chacha_ref`, so the local tests compare two implementations.
- **CPU stand-in.** `tests/cuda_shim/chacha_host.cpp` compiles the real `chacha_tags.cu` and `prf.cu` with g++
  (`tests/gpu/test_chacha_cpu_shim.py`). It checks the C++ logic, not what nvcc emits; the GPU job is the gate.
- **Largest size.** At n = 2^max_log2n the tags are compared with the reference for seeds 1-3 and with the twin
  once (seed 1); buckets are compared with the reference in chunks of 2^20 ids to bound host memory.
- **S4.** `bench/chacha_smoke.py` takes its clock-stability snapshots after the warm-up and after the last timed
  run (the fix proposed in ISSUE-7), because 30 runs at 2^20 are shorter than one telemetry sampling period.
