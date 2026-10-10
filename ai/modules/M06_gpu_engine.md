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
