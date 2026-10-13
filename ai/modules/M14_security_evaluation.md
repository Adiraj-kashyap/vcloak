# M14 — Security evaluation on the real system (E0, E1, E2, E3-logical, anonymity set)
owner: Abhishek · depends_on: M08, M10 (M11 recommended) · est_sessions: 2 · human_gates: none

## Goal
Re-run every security experiment against the **actual** GPU engine + PostgreSQL (not the CPU oracle),
with GPU-generated tags, and extend them with the anonymity-set study.

## Required reading
- `ai/PROJECT_BRIEF.md §8, §9` · `ai/TESTING.md §4` · `src/vcloak/oracle/attacks.py` and `stats.py` (signatures)

## Deliverables
`src/vcloak/eval/traffic.py` (bursty generator; users/conversations/rates; seeds), `eval/attack.py`, `eval/uniformity.py`,
`eval/anonymity.py`, `bench/run_security_eval.py`, `results/security/*.json|png|csv`, `docs/REPORT_CH4_NOTES.md` (security section).

## Steps
- **S1 Traffic on the real stack.** Service in `--clock sim` mode with PostgreSQL; 200 conversations, 900 simulated seconds,
  the same burst model as the oracle (70% replies at Exp(2 s), otherwise Exp(1/rate)); record the message count.
  Check: row count = message count; the manifest records the seed.
- **S2 E0 restoration.** Read back ≥60 conversations through the service read path; exact-order count. Record `CAND_K`,
  the peak and the mean bucket-window occupancy.
- **S3 E1 attack.** Dump from PostgreSQL (`ORDER BY ctid`) for layouts: baseline service, V-cloak with the epoch-level visible round
  (Review-1 mode flag), and V-cloak with W ∈ {1, 10, 60, 300} s. Compute global τ, τ within the round, turn-order accuracy, f, and the
  predicted 1 − f/2. Check: the table and the ablation figure are saved.
- **S4 E2 uniformity on GPU tags.** χ² at n=64 over 20,000 epochs with the (n−1)/n correction plus the ideal-sampler calibration;
  the τ band at n=2^16 over 1,000 epochs (on the GPU this should take seconds). Check: acceptance gates of TESTING §4.
- **S5 E3 logical.** Comparator-trace invariance for the GPU schedule (hash of the pair schedule over the launches actually issued by
  the driver, recorded via a debug hook) vs merge sort. Link the M08 dudect verdicts in the summary.
- **S6 Anonymity set.** Users ∈ {10, 100, 1000}: the distribution of real messages per window and per bucket-window
  (median, p5), and the turn-order accuracy at W=60 for each.
- **S7 Compare with the CPU oracle.** A table comparing GPU-system vs oracle numbers; differences beyond sampling noise open an issue.

## Metrics to record
`S-E0-RESTORE`, `S-CANDK`, `S-OCC-PEAK`, `S-TAU-GLOBAL-<layout>`, `S-TAU-WITHIN-<layout>`, `S-TURNACC-<layout>`,
`S-F-<layout>`, `S-CHI2`, `S-CHI2-P`, `S-CHI2-P-IDEAL`, `S-TAUBAND-PCT`, `S-TAU-SIGMA-MEAS`, `S-ANON-MED-U<users>`.

## Evidence to capture
The attack table, the window-ablation figure, the τ histogram and the uniformity summary — exported as
paper-ready figures into `evidence/figures/`, plus the terminal output of the attack run into
`evidence/terminal/`. These carry the project's headline claim.

## Audit checklist
- A1 All numbers come from the real stack (the manifest shows mode=vcloak, db=postgres, engine=gpu).
- A2 Every acceptance gate is evaluated and recorded; failures are issues, not omissions.
- A3 The GPU-vs-oracle comparison table exists. A4 A dudect FAIL from M08 (if any) is reflected in the summary. G1–G10.

## Presenter notes
1. Walk through turn-order accuracy vs W and the 1 − f/2 law, with your own numbers.
2. How big is the anonymity set at 10 vs 1000 users?
3. Do the GPU results match the CPU oracle, and how do you know?

## Next: M15

## Amendments
- 2026-10-13 (session 36): S1 as built differs from the text above in these points.
  - The app runs in-process with the objects of `vcloak serve --dev --clock sim`, but the scheduler is stepped by the
    replay (`autorun=False`): with the free-running sim clock an arrival time could not be placed in its epoch.
  - The run of S1 used the numpy simulator behind the engine (no local GPU). A1 (engine=gpu) is open: ISSUE-38.
  - The message count is recorded as `S-TRAFFIC-MSGS`, a metric id the list above does not name.
- 2026-10-13 (session 37): S2 to S5 as built, and the GPU job the human allowed (ISSUE-38).
  - S2 and S3 are one stage (`run_security_eval.py --stage attack`): the traffic is replayed into every layout, and
    E0 reads 60 conversations back on the W = 60 layout of S3 (every window is asked for, the empty ones too).
  - The epoch layout is dumped a hundred rounds per statement (the same physical order as `ORDER BY win, ctid`): one
    statement over its ~4500 partitions needs more locks than a default PostgreSQL allows.
  - S4 gates as implemented: "the range of the ideal-sampler calibration" is the smallest to the largest statistic of
    200 ideal-sampler tables; the tau band passes when the count inside 3 sigma lies in the central 99% interval of
    Binomial(epochs, 0.9973). The permutations come from the development key (public), epochs 0.. and 10^6.. .
  - S5 records the launches through `kernels.set_launch_hook` (public arguments only). It is the logical trace; the
    link to the M08 dudect verdicts is written at the ingest, from results/oblivious (not in the bundle).
  - Figures (window ablation, tau histogram) are drawn at the ingest from the JSON of the run dirs, not in the job.
  - Metric ids the list above does not name: `S-OCC-MEAN`, `S-TRACE-DISTINCT-DEVICE`, `S-TRACE-DISTINCT-MERGESORT`,
    `S-CUDA-TESTS-PASSED|FAILED|ERRORS|SKIPPED`.
  - The job `bench/jobs/M14.json` installs and starts PostgreSQL in the runner (`scripts/runner_stack.py`) and, at the
    request of the human, also runs every test marked `gpu` (`bench/run_gpu_tests.py`).
  - S6 (anonymity set) and S7 (comparison with the oracle) are not written and are not in that job.
- 2026-10-13 (session 38): the ingest of job 20261013-105517_M14 (Colab, Tesla T4, PostgreSQL 16 in the runner).
  - `results/security/*` and section 4.S of `docs/REPORT_CH4_NOTES.md` are written by a generator the Deliverables do
    not name, `src/vcloak/bench/report_security.py`: it copies the stage files and the gates of the ingested runs, draws
    the window-ablation figure and the tau histogram, and refuses runs that are not cupy runs of one session with
    mode=vcloak, db=postgres, engine=gpu.
  - The "uniformity summary" of *Evidence to capture* is `e2_uniformity.json` with section 4.S.4; no separate figure.
  - In the ablation figure the predicted 1 - f/2 is drawn as rings around the measured points (they coincide).
  - S6 and S7 are still open (ISSUE-40); the notes say NOT_MEASURED for both.
- 2026-10-13 (session 39): S7 as built.
  - "The CPU oracle" is `seed/vcloak_oracle.py`, run unchanged and locally by `bench/run_oracle_compare.py` with the
    seed of the device runs; its output directory is redirected into the run dir, so it never writes into `results/`.
  - The module text does not define "sampling noise". As built (`src/vcloak/eval/oracle_compare.py`, fixed before the
    full oracle run was read): a quantity fixed by the traffic or the schedule must be equal to 1e-9; a key-dependent
    quantity of E0 or E1 must lie inside the prediction interval of 20 repetitions of the oracle's attack with fresh
    keys on the same traffic (level 0.01 shared over those rows); for E2 both values must lie inside the interval that
    theory or the ideal-sampler calibration gives. Two quantities are defined differently on the two sides (f of the
    baseline layout, the candidate set size K) and are shown as NOT_COMPARABLE.
  - Metric ids the list above does not name: `S-ORACLE-<the device id without S->`, `S-ORACLE-CMP-<verdict>`,
    `S-ORACLE-REPS`. They are backend numpy / runner local: reference values of the logic, never GPU results.
  - The table reaches `results/security` and section 4.S.9 of the notes through `report_security --oracle`.
