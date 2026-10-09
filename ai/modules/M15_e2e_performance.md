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
