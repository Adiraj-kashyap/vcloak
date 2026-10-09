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

## Audit checklist
- A1 All numbers come from the real stack (the manifest shows mode=vcloak, db=postgres, engine=gpu).
- A2 Every acceptance gate is evaluated and recorded; failures are issues, not omissions.
- A3 The GPU-vs-oracle comparison table exists. A4 A dudect FAIL from M08 (if any) is reflected in the summary. G1–G10.

## Presenter notes
1. Walk through turn-order accuracy vs W and the 1 − f/2 law, with your own numbers.
2. How big is the anonymity set at 10 vs 1000 users?
3. Do the GPU results match the CPU oracle, and how do you know?

## Next: M15
