# M07 — GPU performance metrics, CPU baselines and crossover (E4)
owner: Aditya · depends_on: M06 · est_sessions: 2 · human_gates: plug in AC power; optional clock lock (admin)

## Goal
Publication-grade GPU measurements: kernel sweeps, pipeline stage breakdowns, bandwidth utilisation,
telemetry, CPU baselines and the GPU/CPU crossover.

## Required reading
- `ai/GPU_GUIDE.md §4, §5, §6` · `.claude/skills/gpu-bench/SKILL.md` · `ai/LOGGING_AND_AUDIT.md §2, §5`

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
- **S3 CPU baselines.** (i) the oracle NumPy bitonic (single-thread vectorised), (ii) `np.lexsort` (non-oblivious,
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

## Audit checklist
- A1 Every plotted point traces to a run dir (sidecar JSON); `check_metrics.py` passes.
- A2 GPU timings use CUDA events; CPU uses perf_counter_ns (grep).
- A3 The fair-comparison rule holds: the GPU crossover includes transfers; the power state is recorded for all runs.
- A4 Unstable runs are reported, not dropped. A5 The fused variant is bit-identical to global-only (spot test).
- G1–G10.

## Presenter notes
1. At what n does the GPU beat the best oblivious CPU sort, including transfers?
2. What fraction of peak memory bandwidth does the bitonic kernel reach, and why not 100%?
3. Does write_epoch fit the 200 ms epoch at 2^16 slots (p99)?

## Next: M08
