# M06 — GPU engine: device key store, write_epoch, read_window, reshuffle
owner: Aditya · depends_on: M05 · est_sessions: 3 · human_gates: upload the GPU job (~2 min); passphrase for a dev sealed key (or use the `--dev` test key)

## Goal
The `GpuEngine` API from ARCHITECTURE §4: the only server component that touches keys, entirely on the GPU,
with per-stage CUDA-event timings.

## Required reading
- `ai/GPU_RUNNER.md` (§3–§5) and `.claude/skills/gpu-job/SKILL.md`
- `ai/ARCHITECTURE.md §2, §4, §5` · `ai/DECISIONS.md ADR-006, ADR-007` · `ai/GPU_GUIDE.md §4, §8`

## GPU execution (this module runs on the free runner)
This module's CUDA work cannot run on the laptop. Follow `ai/GPU_RUNNER.md` and the `gpu-job` skill:
1. **Prep session (local):** write/modify the `.cu` kernels **and their NumPy twins in `src/vcloak/gpu/sim.py`**;
   pass every correctness test under `VCLOAK_BACKEND=numpy`; commit; `python scripts/gpujob.py pack M06`;
   open the `GPU JOB READY` issue; set `BLOCKED_HUMAN`; hand off.
2. **Human (~2 min):** open `colab/VCloak_GPU_Runner.ipynb` on Colab (or Kaggle for long jobs), select a GPU
   runtime, upload `gpujobs/out/<job>.zip`, run all cells, drop `results_<job>.zip` into `gpujobs/inbox/`, type `continue`.
3. **Ingest session:** `python scripts/gpujob.py ingest`, apply this module's gates, record metrics
   (`backend: cupy`, with the runner and session id), audit, close.
**Simulator parity is an acceptance gate here:** every kernel this module adds must produce byte-identical
output on the GPU and under the `numpy` twin, over the sizes and seeds in `ai/TESTING.md §3`. A mismatch is a
real bug in one of the two — never "close enough".

## Deliverables
`src/vcloak/gpu/keystore.py`, `src/vcloak/gpu/engine.py`, `tests/gpu/test_engine.py`,
`tests/integration/test_engine_vs_oracle.py`, `bench/run_pipeline.py` (smoke mode only here).

## Steps
- **S1 DeviceKeyStore.** `load_master(bytearray)`: H2D into a device buffer, zero the host bytearray in place,
  run `derive_subkeys` on the GPU, keep only the device buffers, and `zeroize()` with memset. Provide a `dev_keystore()` for tests
  (fixed test master from `tests/`). Check: after load, the host bytearray is all zeros; subkeys match M02.
- **S2 write_epoch.** Pad to SLOTS (the pay index ≥ n_real marks dummies) → `chacha_tags` → bitonic → compact → D2H the first n_real
  `pay` indices → host gather of payloads (ADR-006) → `aead_seal_seq` on the GPU (host-supplied random nonces)
  → `bucket_prf` on the GPU → build StoredRows with uuid4 and `win = floor(epoch*EPOCH_MS/1000 / WINDOW_S)`.
  Check: bit-exact vs `write_epoch_ref` given the same nonces and uuids (inject them via a test hook).
- **S3 reshuffle_window and read_window.** reshuffle = window tags → bitonic → host gather. read_window = pad candidates to K
  → H2D the seq_enc blobs → `aead_open_seq` → restore sort → D2H the first j indices → payloads in order.
  Check: equals the oracle for 50 windows.
- **S4 Streams and pinned memory.** Use one CUDA stream per engine and pinned host buffers for H2D/D2H. Record
  per-stage events: `h2d`, `tags`, `sort`, `compact`, `d2h`, `seal`, `bucket`, `total`. Check: `last_timings()` has all keys and they sum to about total.
- **S5 Smoke benchmark.** `bench/run_pipeline.py --quick`: write_epoch at SLOTS ∈ {64, 4096, 65536} and read_window at
  K ∈ {128, 1024}. Save the run dir.

## Metrics to record (smoke, quick-tagged)
`P-WRITE-EPOCH-MS-S<slots>` (median, quick), `P-READ-WINDOW-MS-K<k>` (median, quick).

## Audit checklist
- A1 Engine outputs are bit-exact vs the oracle (with injected nonces/uuids). A2 The host master buffer is zeroized (test).
- A3 No subkey ever exists in host memory (grep engine/keystore code: no `.get()` or `asnumpy` on key buffers).
- A4 Stage timings exist and are consistent. G1–G10.

## Presenter notes
1. Where exactly do K_tag, K_seq and K_bkt live, and when does K_master exist on the host?
2. Why does the payload gather happen on the host? (ADR-006)
3. What is the per-stage cost breakdown of one epoch?

## Next: M07

## Amendments
2026-10-11 (session 11, prep). Where the build differs from the text above, and why:
- **No new kernel.** The engine is built from the M03-M05 wrappers only, so `kernels/` and `gpu/sim.py` are
  unchanged. The simulator-parity gate is applied to the engine as a whole: the cupy engine against the numpy
  engine (`test_gpu_engine_equals_the_simulator_engine`), besides both against the oracle.
- **K_master on the device.** After `derive_subkeys` the device copy of the master is cleared with memset; only
  the three subkeys stay in VRAM. H2D reads straight from the caller's bytearray (`copy_from_host`), so no pinned
  or pageable staging copy of the master exists on the host.
- **`dev_keystore()`** lives in `tests/testkeys.py`, because test keys may exist in `tests/` only (CONVENTIONS §3).
  `bench/run_pipeline.py --dev` derives its TEST master from the seed, as the other bench scripts do; it has no
  sealed-key path, so this module needs no passphrase (the service unseals the real key, M10).
- **Test hook.** Instead of separate nonce and uuid hooks the engine takes one `entropy` callable (default
  `os.urandom`), called once per epoch for 28 bytes per stored row: 16 for the uuid4, then 12 for the nonce. The
  oracle draws the same bytes in the same order (16, then 12, per row), so one byte tape drives both.
- **Order of S2.** The bucket PRF and the seal run after the host gather, on the rows in stored order; the first
  transfer of an epoch is therefore the D2H of the order, and `h2d` (conv ids, seqs, nonces) comes after it.
- **Re-shuffle** follows the oracle (`reshuffle_ref`): tags, bitonic sort, compaction of the padding, host gather.
- **read_window** accepts fewer than K candidates and pads them with random 44-byte seq_enc values (misses);
  more than K, or a seq_enc that is not 44 bytes, is a ValueError (the oracle treats a malformed row as a miss).
- **Stage keys.** `last_timings()` always has `h2d, tags, sort, compact, d2h, seal, bucket, open, host, total`.
  `open` is the AEAD-open of a read; `host` is the engine's host work between device stages (gather, random bytes,
  building rows). Stages are intervals between consecutive events on the engine's stream, so they add up to `total`.
  Under the numpy backend the clock is `time.perf_counter` and `engine.timer` says so; never a performance result.
- **Smoke sizes.** `bench/run_pipeline.py` times full epochs (n_real = SLOTS) and reads with K/8 hits, with 8-byte
  payload stand-ins (payload bytes never reach the device, ADR-006).
