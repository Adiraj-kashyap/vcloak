# STATE — single source of progress (agent-maintained)

```yaml
project: v-cloak
kit_version: 1.0
last_session: 3
last_session_date: 2026-10-11
current_module: M02
current_step: S1
status: NOT_STARTED        # NOT_STARTED | IN_PROGRESS | AUDIT_PENDING | AUDIT_FAILED | DONE | BLOCKED_HUMAN | BLOCKED_TECH
next_unit: M02
last_checkpoint: 2026-10-11 M01 DONE (S1-S5, 148 oracle tests, golden vectors, audit PASS)
quick_mode_default: false
local:                      # the laptop (no GPU) — filled by M00 S7
  os: "Windows-11-10.0.26200-SP0"
  python: "3.14.0"
  cpu: "12th Gen Intel(R) Core(TM) i7-1255U (12 logical)"
  ram_gb: 15.6
  postgres: "service postgresql-x64-17 (Running); psql not on PATH"
  default_backend: "numpy"
runner:                     # the free remote GPU — filled from the ingested M00 probe, never typed by hand
  provider: "kaggle"         # colab | kaggle
  gpu: "Tesla T4"
  compute_capability: "7.5"
  vram_gb: 15.64
  driver: "580.82.07"
  cuda: "13000"
  cupy: "14.0.1"
  nvcc: "Build cuda_13.0.r13.0/compiler.36424714_0"
  ncu: "NVIDIA (R) Nsight Compute Command Line Profiler"
  ncu_counters_permitted: "unknown"
  max_log2n: 24
  peak_bw_gbs: 320.064
  last_session_id: "20261011-110131"
gpu_job:                    # set by the gpu-job skill
  pending: null   # job id awaiting the human's upload, or null
  last_ingested: 20261011-014756_M00
```

## Modules

| ID | Title | Owner | Depends on | Optional | Status | Step | Sessions |
|---|---|---|---|---|---|---|---|
| M00 | Bootstrap & GPU probe | Aditya | — | no | DONE | S7 | 2 |
| M01 | Oracle port & golden vectors | Abhishek | M00 | no | DONE | S5 | 1 |
| M02 | CPU crypto & key lifecycle | Abhishek | M01 | no | NOT_STARTED | S1 | 0 |
| M03 | GPU bitonic kernel | Aditya | M01 | no | NOT_STARTED | S1 | 0 |
| M04 | GPU ChaCha20 tags/PRF | Aditya | M02, M03 | no | NOT_STARTED | S1 | 0 |
| M05 | GPU AEAD-open, restore, compaction | Aditya | M04 | no | NOT_STARTED | S1 | 0 |
| M06 | GPU engine | Aditya | M05 | no | NOT_STARTED | S1 | 0 |
| M07 | GPU performance metrics (E4) | Aditya | M06 | no | NOT_STARTED | S1 | 0 |
| M08 | GPU obliviousness audit (E3) | Aditya | M06 | no | NOT_STARTED | S1 | 0 |
| M09 | Storage (PostgreSQL) | Divyansh | M06 | no | NOT_STARTED | S1 | 0 |
| M10 | Service & scheduler | Divyansh | M09 | no | NOT_STARTED | S1 | 0 |
| M11 | Session security (E5) | Divyansh | M10 | no | NOT_STARTED | S1 | 0 |
| M12 | Client SDK & CLI | Abhishek | M11 | no | NOT_STARTED | S1 | 0 |
| M13 | Frontend: chat + server view | Abhishek | M12 | no | NOT_STARTED | S1 | 0 |
| M14 | Security evaluation (E0–E2, anon set) | Abhishek | M08, M10 | no | NOT_STARTED | S1 | 0 |
| M15 | End-to-end performance (E6) | Divyansh | M10, M11 | no | NOT_STARTED | S1 | 0 |
| M16 | Results export | Abhishek | M07, M08, M14 | no | NOT_STARTED | S1 | 0 |
| M18 | Frontend: dashboard, experiments, logs | Abhishek | M13, M14 | no | NOT_STARTED | S1 | 0 |
| M17 | Final audit & demo (Review 3 close-out) | Team | all required | no | NOT_STARTED | S1 | 0 |
| M22 | Draft report (prelim pages, Ch.1–4, similarity) | Team | M16 | no | NOT_STARTED | S1 | 0 |
| M19 | Publication / IP submission (crit. 9) | Abhishek + team | M16 | no | NOT_STARTED | S1 | 0 |
| M20 | Final report, analysis, limitations | Team | M16 | no | NOT_STARTED | S1 | 0 |
| M21 | Integration, validation, Review-4 readiness | Team | M17, M19, M20 | no | NOT_STARTED | S1 | 0 |

## Notes for the agent
- Update the yaml block and the module row together. Keep this file under 120 lines.
- `sessions` counts sessions spent on the module (including audit-only sessions).
- GPU modules (M03–M08) need a prep session and an ingest session; `gpu_job.pending` says which job the
  human still has to upload. Never mark such a module DONE while `pending` is set.
- The build targets three gates: **Review 3** (interim, 20 marks) is satisfied by M00–M08 plus M13;
  the **Draft / Report Review** (5 marks) is M22; **Review 4** (final, 25 marks) needs everything and
  adds M19–M21. See `ai/REVIEW_RUBRICS.md`.
- **M19 is calendar-bound.** Once M16 has real results, treat M19 as the highest-priority unmet unit
  even if other modules look more urgent — criterion 9 awards nothing without a dated submission proof.
