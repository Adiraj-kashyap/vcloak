# M07 — GPU performance metrics, CPU baselines and crossover (E4)
owner: Aditya · depends_on: M06 · est_sessions: 3 · human_gates: upload the GPU job; prefer Kaggle for the full sweep (longer session)

## Goal
Publication-grade GPU measurements: kernel sweeps, pipeline stage breakdowns, bandwidth utilisation,
telemetry, CPU baselines and the GPU/CPU crossover.

## Required reading
- `ai/GPU_RUNNER.md` (§3–§5) and `.claude/skills/gpu-job/SKILL.md`
- `ai/GPU_GUIDE.md §4, §5, §6` · `.claude/skills/gpu-bench/SKILL.md` · `ai/LOGGING_AND_AUDIT.md §2, §5`

## GPU execution (this module runs on the free runner)
This module's CUDA work cannot run on the laptop. Follow `ai/GPU_RUNNER.md` and the `gpu-job` skill:
1. **Prep session (local):** write/modify the `.cu` kernels **and their NumPy twins in `src/vcloak/gpu/sim.py`**;
   pass every correctness test under `VCLOAK_BACKEND=numpy`; commit; `python scripts/gpujob.py pack M07`;
   open the `GPU JOB READY` issue; set `BLOCKED_HUMAN`; hand off.
2. **Human (~2 min):** open `colab/VCloak_GPU_Runner.ipynb` on Colab (or Kaggle for long jobs), select a GPU
   runtime, upload `gpujobs/out/<job>.zip`, run all cells, drop `results_<job>.zip` into `gpujobs/inbox/`, type `continue`.
3. **Ingest session:** `python scripts/gpujob.py ingest`, apply this module's gates, record metrics
   (`backend: cupy`, with the runner and session id), audit, close.
**Simulator parity is an acceptance gate here:** every kernel this module adds must produce byte-identical
output on the GPU and under the `numpy` twin, over the sizes and seeds in `ai/TESTING.md §3`. A mismatch is a
real bug in one of the two — never "close enough".

## Deliverables
`src/vcloak/bench/timing.py` (event timer, stats), `src/vcloak/bench/baselines.py`,
`src/vcloak/bench/report.py` (plots + tables), `bench/run_kernels.py`, `bench/run_pipeline.py` (full mode),
`results/perf/*.png|pdf|csv|json`, `docs/REPORT_CH4_NOTES.md` (performance section).

## Steps
- **S1 Timer library.** `time_gpu(fn, warmup, runs, stream)` → per-run ms list, plus `summarise()` → median/p5/p95/mean/std/CV.
  `time_cpu(fn, …)` with `perf_counter_ns`. Check: unit test with a known sleep kernel (`__nanosleep`) is within ±10%.
- **S2 Kernel sweeps (GPU).** For n = 2^10 … 2^max_log2n: (a) the bitonic global-only variant, (b) the fused shared variant,
  (c) ChaCha20 tags, (d) AEAD open (rows/s), (e) bucket PRF. 50 runs each, telemetry sampled.
  Derive keys/s, effective GB/s and % of peak (GPU_GUIDE §5). Check: run dirs are complete; CV < 10% or UNSTABLE is recorded.
- **S3 CPU baselines (on the runner, in the same session).** The laptop's CPU is not the runner's CPU, so
  both sides of the comparison must come from one runner session, and the write-up must say which GPU/CPU pair it was.
  Original text: (i) the oracle NumPy bitonic (single-thread vectorised), (ii) `np.lexsort` (non-oblivious,
  lower bound), (iii) optional `numba` parallel bitonic if numba installs (otherwise NOT_MEASURED with the reason). Same n sweep,
  ≥10 runs (CPU sweeps above 2^20 may use 5 runs; note it). Check: run dirs are complete.
- **S4 Crossover and speed-up.** Compute n* (GPU_GUIDE §5) against the best *oblivious* CPU baseline, plus speed-ups
  at 2^16 and 2^20. Include H2D/D2H in the GPU numbers for a fair comparison. Check: summary.json contains n* and the speed-ups.
- **S5 Pipeline breakdown.** write_epoch at SLOTS ∈ {2^6, 2^10, 2^12, 2^14, 2^16}: stacked stage breakdown; p99 vs the
  EPOCH_MS budget. read_window for K ∈ {64 … 4096}. Check: the real-time gate is evaluated and recorded (pass or issue).
- **S6 Plots and notes.** Log-log time vs n (GPU variants vs CPU), bandwidth % of peak vs n, stage breakdown,
  and telemetry during the longest run. Sidecar JSON per figure listing its run dirs. Update REPORT_CH4_NOTES
  with a table in which every number carries a `<!--M:ID-->` tag.

## Metrics to record
`K-BITONIC-GLOBAL-MS-2^n`, `K-BITONIC-FUSED-MS-2^n`, `K-BITONIC-BW-PCT-2^n`, `K-CHACHA-GBS`, `K-AEADOPEN-ROWS-S`,
`CPU-BITONIC-MS-2^n`, `CPU-LEXSORT-MS-2^n`, `X-CROSSOVER-N`, `X-SPEEDUP-2^16`, `X-SPEEDUP-2^20`,
`P-WRITE-EPOCH-P99-S<slots>`, `P-READ-WINDOW-P99-K<k>`, `TEL-SMCLK-MEDIAN`, `TEL-POWER-W-MEDIAN`.

## Quick parameters
n up to 2^18, runs 15, warm-up 5; tag every ID with quick=yes.

## Runner budget
One full sweep (S2+S3) should fit in roughly 20–40 min of GPU time. Cap n at 2^22 even if `max_log2n` is higher,
and split S5 (pipeline) into its own job if a session gets close to its limit. Record `runner` and `session_id`
in every manifest; never merge two sessions into one figure.

## Evidence to capture at ingest
Copy from the ingested bundle into `evidence/gpu/` and index it: `nvidia-smi` output, the device
properties, the sweep plots, the device identity and the telemetry summary. This is the proof that the GPU work really ran on a real GPU, and it is what the
paper's setup section and the panel will ask to see. Follow `ai/EVIDENCE.md`.

## Audit checklist
- A1 Every plotted point traces to a run dir (sidecar JSON); `check_metrics.py` passes.
- A2 GPU timings use CUDA events; CPU uses perf_counter_ns (grep).
- A3 The fair-comparison rule holds: the GPU crossover includes transfers, and the GPU and CPU numbers come
  from the **same runner session** (manifest `session_id` matches); cloud-shared-GPU caveat recorded.
- A4 Unstable runs are reported, not dropped. A5 The fused variant is bit-identical to global-only (spot test).
- G1–G10.

## Presenter notes
1. At what n does the GPU beat the best oblivious CPU sort, including transfers?
2. What fraction of peak memory bandwidth does the bitonic kernel reach, and why not 100%?
3. Does write_epoch fit the 200 ms epoch at 2^16 slots (p99)?

## Next: M08

## Amendments

### 2026-10-11 (session 13, prep) — how the steps were implemented, and where that differs from the text above
- **No new kernel.** S2 times kernels that M03–M06 already delivered with their NumPy twins (the global-only
  plan and the fused plan of `kernels/bitonic.cu`, `chacha_tags`, `aead_open_seq`, `bucket_prf`), so the
  "simulator parity for every kernel this module adds" gate has nothing new to cover. The sweep still checks
  every timed output (np.lexsort, `chacha_ref`, the sealed inputs) and that fused = global-only at every n (A5).
- **S1 sleep kernel.** `tests/gpu/test_timing.py` checks the event timer in two parts: the CUDA-event time of a
  `__nanosleep` launch against the host clock around the same synchronised launch (±10%, a hard assert), and
  against the nominal sleep (±10%; a miss is reported as XFAIL with the measured ratio). Reason: the nanosleep
  instruction promises only an approximate sleep, so a nominal miss would say nothing about the timer.
- **S2 warm-up and clock (ISSUE-7, ISSUE-11).** The warm-up of each configuration lasts until the SM clock has
  stopped rising (at least 10 launches and 0.5 s, at most 4 s); the clock is read after the warm-up and after the
  last timed run without a subprocess. CV > 10% or a clock change > 15% on two attempts → the metric value is
  `UNSTABLE` (both attempts stay in raw.csv and summary.json). A steady clock below 85% of the device maximum is
  repeated once after a ramp load; if it is still low the number is kept and its note says `LOW clock`.
  ISSUE-7 had proposed to call a low-clock run UNSTABLE; that would discard the small-n points, which is where a
  short kernel cannot keep a GPU busy and where the crossover is expected.
- **S2 metric names.** Besides the listed IDs: `K-BITONIC-E2E-MS-2^n` (pinned H2D + fused sort + pinned D2H, the
  series S4 uses), per-n `K-CHACHA-MS-2^n`, `K-AEADOPEN-MS-2^n`, `K-BUCKETPRF-MS-2^n`, and `K-BUCKETPRF-ROWS-S`.
  `K-CHACHA-GBS`, `K-AEADOPEN-ROWS-S` and `K-BUCKETPRF-ROWS-S` are taken at the largest swept n.
  `K-BITONIC-BW-PCT-2^n` is the global-only variant, for which the bytes-moved model of GPU_GUIDE §5 holds.
- **S3 baselines.** The oracle network is timed through `vcloak.bench.baselines.oracle_bitonic`: the same
  per-stage arithmetic as `oracle.reference.bitonic_sort` (tested equal), with the schedule built one stage at a
  time, because the oracle's precomputed schedule needs about 8 GB of index arrays at 2^22. Added
  `CPU-BITONIC-VIEWS-MS-2^n`, the same network on reshaped views, so that the "best oblivious CPU baseline" of S4
  is not just the slowest way to write it. numba is `CPU-BITONIC-NUMBA-MS-2^n` (NOT_MEASURED when absent). A
  configuration that would exceed 20 min has its run count cut (noted in the metric).
- **S3–S4 session rule.** `run_kernels.py --part crossover` only accepts a GPU sweep and a CPU sweep whose
  manifest `session_id` equals its own; otherwise every X metric is NOT_MEASURED.
  n* is the smallest compared n from which the GPU is faster at every larger compared n.
  Added `X-SPEEDUP-VS-LEXSORT-2^16` / `-2^20` (np.lexsort is not oblivious: a lower bound, not the comparison).
- **S5.** 200 timed calls per configuration (30 with quick) instead of 50, so that a p99 is not the maximum.
  Besides `P-…-P99-…`: `-MS-` (median), `-DEVICE-MS-`, `-DEVICE-P99-` (the device stages only) and `-HOST-MS-`
  (ISSUE-12). The gate is evaluated for the whole call and for the device part. The SM clock is recorded and not
  forced up. `host_profile.txt` is a cProfile of three write_epoch calls at SLOTS 65536.
- **S6 is not prepared in this session**: `src/vcloak/bench/report.py`, the figures and `docs/REPORT_CH4_NOTES.md`
  are written in the ingest session from the ingested run dirs.
