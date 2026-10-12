# M08 — GPU obliviousness audit: dudect timing, divergence, SASS (E3 physical)
owner: Aditya · depends_on: M06 (M07 recommended) · est_sessions: 3 · human_gates: upload the GPU job; dudect at full N needs a long Kaggle session

## Goal
Measure whether GPU execution time or control flow depends on secret data, for the comparator kernels,
the full write_epoch, and AEAD-open.

## Required reading
- `ai/GPU_RUNNER.md` (§3–§5) and `.claude/skills/gpu-job/SKILL.md`
- `ai/GPU_GUIDE.md §7` · `ai/CONVENTIONS.md §2` · `.claude/skills/gpu-bench/SKILL.md`

## GPU execution (this module runs on the free runner)
This module's CUDA work cannot run on the laptop. Follow `ai/GPU_RUNNER.md` and the `gpu-job` skill:
1. **Prep session (local):** write/modify the `.cu` kernels **and their NumPy twins in `src/vcloak/gpu/sim.py`**;
   pass every correctness test under `VCLOAK_BACKEND=numpy`; commit; `python scripts/gpujob.py pack M08`;
   open the `GPU JOB READY` issue; set `BLOCKED_HUMAN`; hand off.
2. **Human (~2 min):** open `colab/VCloak_GPU_Runner.ipynb` on Colab (or Kaggle for long jobs), select a GPU
   runtime, upload `gpujobs/out/<job>.zip`, run all cells, drop `results_<job>.zip` into `gpujobs/inbox/`, type `continue`.
3. **Ingest session:** `python scripts/gpujob.py ingest`, apply this module's gates, record metrics
   (`backend: cupy`, with the runner and session id), audit, close.
**Simulator parity is an acceptance gate here:** every kernel this module adds must produce byte-identical
output on the GPU and under the `numpy` twin, over the sizes and seeds in `ai/TESTING.md §3`. A mismatch is a
real bug in one of the two — never "close enough".

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

## Evidence to capture at ingest
Copy from the ingested bundle into `evidence/gpu/` and index it: `nvidia-smi` output, the device
properties, the dudect t-curves, the Nsight metric output and the SASS extract. This is the proof that the GPU work really ran on a real GPU, and it is what the
paper's setup section and the panel will ask to see. Follow `ai/EVIDENCE.md`.

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

## Amendments
- 2026-10-12 (session 15, prep). What was built differs from the step text in these points:
  - S1: the planted-leak kernel is `bench/planted/planted_leak.cu`, outside `kernels/`, because it breaks
    CONVENTIONS §2.1 on purpose and G3 scans `kernels/`. Its twin is `vcloak.gpu.sim.planted_leak`.
  - S1: a second control was added, `control_null` (the same fixed input in both classes). A FAIL there means the
    harness itself separates the classes, so it is run at full N beside the five targets.
  - S1: the statistics are in `src/vcloak/bench/dudect.py`. A calibration batch (500 per class) sets the batch size r
    and the 100 crop thresholds and is not part of any test, as in dudect. dudect's second-order test is not implemented.
  - S2 (c): write_epoch has two series, the device stages (the engine's CUDA events without its `host` stage) and the
    whole call. Extra metric id: `T-DUDECT-MAXT-WRITE-EPOCH-CALL`. A FAIL on either is a finding.
  - S2 (e): class B of `aead_conv` is drawn from a pool of 64 inputs sealed before the run (16 in quick mode), because
    sealing a fresh input on the device before only one class would be a difference between the classes.
  - S2: every class-B input is drawn on the host for both classes and then used or not, so the host does the same
    work before every measurement.
  - S3: `sass_check.py` also lists the code that CuPy's nvrtc path builds, when CuPy exposes it, and compiles the
    planted-leak kernel as a positive control. Its trace is static and flow-insensitive.
  - S4: the logic is in `bench/run_ncu.py` (with `bench/ncu_workload.py`); `run_ncu.sh` and `run_ncu.ps1` call it.
    The planted-leak kernel is profiled as a positive control.
- 2026-10-12 (session 16, ingest). Job 20261012-041010_M08 on a Kaggle T4:
  - S5: the table, `results/oblivious/*` and the notes section are generated by `python -m vcloak.bench.report_oblivious`
    (verdicts copied, never recomputed). The section sits in `docs/REPORT_CH4_NOTES.md` between two markers, and
    `vcloak.bench.report` keeps it when it rewrites the performance notes.
  - S3: `sass_check.py` reports every conditional branch as DATA (ISSUE-19); the per-branch explanations are in
    `bench/sass_explained.json`. The nvrtc listing was not obtained.
  - S4: counters denied (ERR_NVGPUCTRPERM). The issue is an optional human action, not a gate: a Kaggle container
    cannot change the setting (ISSUE-18). `results/oblivious/ncu_divergence.csv` lists the eight NOT_MEASURED rows.
  - A5: three target series FAIL; ISSUE-17 (high) blocks M14. The module is closed with that issue open, as A5 asks.
  - `scripts/gpujob.py` wrote `max |t|` into the metrics table and broke its columns; cells are now sanitised
    (`abs(t)`) and the nine rows of this ingest were rewritten with the same rule.
- 2026-10-12 (session 20, fix ISSUE-17 prep): `bench/run_dudect.py` has 11 more targets, outside S2's list and
  outside `all` / `targets`: the diagnostics of the three failing series (groups `issue17`, `issue17_rep`; job spec
  `bench/jobs/M08_issue17.json`). `gpu_open_and_key` takes optional preallocated outputs (`out=`), used only by the
  kernel-only targets. Their metric ids are `T-DUDECT-MAXT-<TARGET>-NULL|SWAP|SYM|KERNEL|AGE|FRESH`. They do not
  replace any S2 target, and `report_oblivious` does not read them.
