# M15 — End-to-end performance vs an unprotected baseline (E6)
owner: Divyansh · depends_on: M10, M11 (M07 recommended) · est_sessions: 2 · human_gates: AC power; close heavy apps

## Goal
The cost of privacy at the system level: latency and throughput of V-cloak vs the baseline backend on the same
hardware, with GPU utilisation sampled throughout.

## Required reading
- `ai/GPU_GUIDE.md §6` · `.claude/skills/gpu-bench/SKILL.md` · `docs/API.md`

## Deliverables
`bench/run_e2e.py` (async load generator using httpx; per-user DPoP clients), `results/e2e/*.csv|png|json`,
`docs/REPORT_CH4_NOTES.md` (end-to-end section).

## Steps
- **S1 Load generator.** U virtual users in conversation pairs; Poisson send rate per user; records submit→ack latency,
  and submit→readable latency (poll the read endpoint until the message appears). Warm-up of 20 s is excluded.
- **S2 Runs.** Modes {baseline, vcloak} × users {10, 100, 1000} × 120 s each (quick: 30 s, users {10, 100}),
  wall clock. NVML telemetry at 10 Hz, CPU utilisation (psutil), DB size. Two repetitions per cell.
- **S3 Metrics.** p50/p95/p99 latency, achieved msgs/s, epoch overflow count, GPU utilisation median/p95, power.
  The added latency of V-cloak = its p50/p99 minus the baseline's; the expected floor ≈ EPOCH_MS/2 on average (report measured).
- **S4 Plots.** Latency CDFs per mode and user count; a throughput bar chart; a GPU utilisation timeline.

## Metrics to record
`E2E-P50-U<u>-<mode>`, `E2E-P99-U<u>-<mode>`, `E2E-TPUT-U<u>-<mode>`, `E2E-OVERFLOW-U<u>`, `E2E-GPUUTIL-U<u>`.

## Audit checklist
- A1 Both modes ran under identical conditions (the manifests show the same power state, versions and duration).
- A2 The warm-up is excluded consistently. A3 Two repetitions are within 15% of each other, or UNSTABLE is recorded. G1–G10.

## Presenter notes
1. What latency does V-cloak add over the baseline, and where does it come from?
2. How loaded is the GPU at 1000 users?
3. Does anything overflow an epoch?

## Next: M16

## Amendments
- 2026-10-14 (session 50): the owner's decisions on ISSUE-49 (ADR-027).
  - Scope: two-party conversations only. Every cell pairs its users (users 2i and 2i+1, conversations = users / 2);
    every summary carries `users_per_conversation: 2`, and every E6 table and figure states the pairing beside
    the user count. Group conversations are future work (`docs/REFINEMENTS.md`).
  - S2 runs users {10, 50, 200}, not {10, 100, 1000} (quick: {10, 50}, not {10, 100}). The presenter note "How
    loaded is the GPU at 1000 users?" is answered for 200 users; 1000 users is not measured end to end.
    Metric ids: `E2E-*-U10`, `E2E-*-U50`, `E2E-*-U200`.
  - A cell is not reduced, dropped or retried without the owner: a cell that cannot complete is reported first.
  - S2 as built: `bench/run_e2e_cells.py` runs the cells (the two modes of a user count back to back, baseline
    first; one seed, so every cell replays the same schedule; one PostgreSQL schema per cell, dropped first).
    Each cell is a run of `bench/run_e2e.py` with `telemetry.csv` (NVML, 10 Hz), `cpu.csv` (psutil, 2 Hz: the
    machine, the service process, the generator) and the size of the cell's tables. The samplers cover setup,
    warm-up and drain too; `measured_unix` in the summary gives the measured interval for S3.
  - The module fixes neither the send rate nor SLOTS. As run: 0.15 messages per user per second (the owner,
    ADR-027 (3): at 0.2 the 200-user schedule can exceed CAND_K in two buckets), SLOTS 256 for every cell and
    both modes, readers poll every 500 ms, `ack: stored`, sessions on (ISSUE-49). All of it is in every summary.
  - The human gate "AC power; close heavy apps" is about a local GPU. The cells run on the cloud runner
    (ADR-024: Kaggle, 4 vCPU); each summary records what the machine reports about its power source (`power`).
