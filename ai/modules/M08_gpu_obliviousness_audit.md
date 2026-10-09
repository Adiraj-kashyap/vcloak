# M08 — GPU obliviousness audit: dudect timing, divergence, SASS (E3 physical)
owner: Aditya · depends_on: M06 (M07 recommended) · est_sessions: 2 · human_gates: GPU performance-counter permission for ncu; nvcc present

## Goal
Measure whether GPU execution time or control flow depends on secret data, for the comparator kernels,
the full write_epoch, and AEAD-open.

## Required reading
- `ai/GPU_GUIDE.md §7` · `ai/CONVENTIONS.md §2` · `.claude/skills/gpu-bench/SKILL.md`

## Deliverables
`bench/run_dudect.py`, `bench/run_ncu.sh` and `bench/run_ncu.ps1`, `scripts/sass_check.py`,
`results/oblivious/dudect_*.json|png`, `results/oblivious/sass_*.txt`, `results/oblivious/ncu_*.csv`,
`docs/REPORT_CH4_NOTES.md` (obliviousness section).

## Steps
- **S1 dudect harness.** Classes A (fixed input) and B (fresh random), randomly interleaved; per-measurement CUDA
  events (batch r launches so one measurement ≥ 50 µs, r public and constant); Welch t on the raw data plus the
  dudect percentile crops (the 100 thresholds from the paper). Online t updates; save the raw data (npz, gitignored)
  and the t-curve vs N (png). Check: a planted leaky kernel (`if (x) spin(1000)`) is detected (|t| ≫ 4.5) in quick mode.
- **S2 dudect targets.** (a) bitonic n = 2^16, classes all-equal vs random; (b) sorted vs random;
  (c) write_epoch at SLOTS = 2^12 with n_real fixed, contents fixed vs random; (d) AEAD-open with all-valid vs all-invalid
  tags; (e) AEAD-open with conv matching q vs not. N = 10^5 per class (quick 10^4). Check: t-curves and verdicts saved.
- **S3 SASS.** If nvcc exists: `nvcc -cubin -arch=sm_<cc> -std=c++17 kernels/bitonic.cu` (and aead_open.cu, chacha_tags.cu);
  `cuobjdump -sass`; `sass_check.py` lists every branch instruction with its predicate source; explain each one (loop over j,
  bounds on public n, exit). If nvcc is missing: HUMAN ACTION (install the CUDA Toolkit) or NOT_MEASURED.
- **S4 ncu divergence.** Confirm metric names (`ncu --query-metrics`); profile the bitonic global/shared kernels and aead_open
  at n = 2^16, collecting branch efficiency and divergent-branch counts. If counters are denied (ERR_NVGPUCTRPERM): HUMAN
  ACTION issue with OS-specific steps, and record NOT_MEASURED meanwhile.
- **S5 Report.** Summary table: target | N/class | max |t| | verdict | SASS branches explained | ncu divergent branches.

## Metrics to record
`T-DUDECT-MAXT-<target>`, `T-DUDECT-N-<target>`, `T-NCU-BRANCHEFF-<kernel>`, `T-NCU-DIVERGENT-<kernel>`, `T-SASS-BRA-<kernel>`.

## Audit checklist
- A1 The planted-leak self-test is detected (proves the harness has power).
- A2 All 5 targets have verdicts at full N (or quick-tagged with an issue to rerun).
- A3 SASS branches are all explained (or NOT_MEASURED with an issue). A4 ncu metrics are collected or NOT_MEASURED with the reason.
- A5 A FAIL on any target opens a high-severity issue that BLOCKS M14 (never softened).
- G1–G10.

## Presenter notes
1. What is dudect, what are your two classes, and what threshold means "no evidence of leakage"?
2. How do you know your harness could detect a leak? (planted kernel)
3. Which SASS branches remain in the comparator kernel and why are they safe?

## Next: M09
