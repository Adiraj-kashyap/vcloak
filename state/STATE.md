# STATE — single source of progress (agent-maintained)

```yaml
project: v-cloak
kit_version: 1.0
last_session: 38
last_session_date: 2026-10-13
current_module: M14
current_step: S6
status: IN_PROGRESS          # NOT_STARTED | IN_PROGRESS | AUDIT_PENDING | AUDIT_FAILED | DONE | BLOCKED_HUMAN | BLOCKED_TECH
next_unit: M14
last_checkpoint: 2026-10-13 session 38: job 20261013-105517_M14 ingested, S2-S5 complete on the real stack (61 of 61 gates PASS), results/security and notes 4.S generated; next: S7 (no device needed), S6 after the decision of ISSUE-40
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
  last_session_id: "20261012-135251"
gpu_job:                    # set by the gpu-job skill
  pending: null   # job id awaiting the upload of the human, or null
  last_ingested: 20261013-105517_M14
```

## Modules

| ID | Title | Owner | Depends on | Optional | Status | Step | Sessions |
|---|---|---|---|---|---|---|---|
| M00 | Bootstrap & GPU probe | Aditya | — | no | DONE | S7 | 2 |
| M01 | Oracle port & golden vectors | Abhishek | M00 | no | DONE | S5 | 1 |
| M02 | CPU crypto & key lifecycle | Abhishek | M01 | no | DONE | S7 | 1 |
| M03 | GPU bitonic kernel | Aditya | M01 | no | DONE | S6 | 2 |
| M04 | GPU ChaCha20 tags/PRF | Aditya | M02, M03 | no | DONE | S4 | 2 |
| M05 | GPU AEAD-open, restore, compaction | Aditya | M04 | no | DONE | S4 | 2 |
| M06 | GPU engine | Aditya | M05 | no | DONE | S5 | 2 |
| M07 | GPU performance metrics (E4) | Aditya | M06 | no | DONE | S6 | 2 |
| M08 | GPU obliviousness audit (E3) | Aditya | M06 | no | DONE | S5 | 9 |
| M09 | Storage (PostgreSQL) | Divyansh | M06 | no | DONE | S5 | 1 |
| M10 | Service & scheduler | Divyansh | M09 | no | DONE | S5 | 2 |
| M11 | Session security (E5) | Divyansh | M10 | no | DONE | S7 | 2 |
| M12 | Client SDK & CLI | Abhishek | M11 | no | DONE | S4 | 1 |
| M13 | Frontend: chat + server view | Abhishek | M12 | no | DONE | S6 | 5 |
| M14 | Security evaluation (E0–E2, anon set) | Abhishek | M08, M10 | no | IN_PROGRESS | S6 | 3 |
| M15 | End-to-end performance (E6) | Divyansh | M10, M11 | no | NOT_STARTED | S1 | 0 |
| M16 | Results export | Abhishek | M07, M08, M14 | no | NOT_STARTED | S1 | 0 |
| M18 | Frontend: dashboard, experiments, logs | Abhishek | M13, M14 | no | NOT_STARTED | S1 | 0 |
| M17 | Final audit & demo (Review 3 close-out) | Team | all required | no | NOT_STARTED | S1 | 0 |
| M22 | Draft report (prelim pages, Ch.1–4, similarity) | Team | M16 | no | NOT_STARTED | S1 | 0 |
| M19 | Publication / IP submission (crit. 9) | Abhishek + team | M16 | no | NOT_STARTED | S1 | 0 |
| M20 | Final report, analysis, limitations | Team | M16 | no | NOT_STARTED | S1 | 0 |
| M21 | Integration, validation, Review-4 readiness | Team | M17, M19, M20 | no | NOT_STARTED | S1 | 0 |

## Notes for the agent
Keep this file under 120 lines: one or two lines per note, the detail lives in the issue or ADR it names.
- Update the yaml block and the module row together; `sessions` includes audit-only sessions.
- GPU modules need a prep and an ingest session; never mark one DONE while `gpu_job.pending` is set. In a GPU JOB
  READY issue never give a path to job.zip on Kaggle (it unpacks uploads into a folder).
- Gates: Review 3 = M00–M08 + M13; Draft Review = M22; Review 4 = everything + M19–M21 (`ai/REVIEW_RUBRICS.md`).
- **M19 is calendar-bound.** Once M16 has real results it is the highest-priority unmet unit (criterion 9 needs a
  dated submission proof).
- G4 = `python scripts/check_secrets.py`. `gpujob.py pack` allow-lists the new bundle sha itself: commit
  `scripts/secrets_allowlist.json` with the session (it is not bundled, so that does not make a job stale).
- Runner images differ: M05/M06 ran on driver 580.178.04 / CUDA 12.8, the `runner` block is the M00 probe. Never mix
  timings across images (ISSUE-3).
- M07: one runner session (20261011-213139). 65 of 213 rows are UNSTABLE (ISSUE-15); never quote K-BITONIC-BW-PCT
  below 2^18 as bandwidth (ISSUE-14). Figures and notes only through `python -m vcloak.bench.report`.
- write_epoch misses EPOCH_MS at 2^16 slots because of host Python, not the GPU (ISSUE-12, BLOCKS M15): vectorise
  the row building in its own unit, then re-measure with a new GPU job.
- M08 is DONE with a negative result: dudect FAILS for aead_conv, aead_tag and the whole write_epoch call (ISSUE-17,
  closed). Diagnostics trace the AEAD FAILs to the harness staging and the whole-call FAIL to host Python state.
  ADR-023: P3 is claimed for the KERNELS only; host timing is a limitation. Never write "constant time".
- How M14/M20/M22 quote M08: AEAD only as "no dependence on the contents detected with symmetric staging, N 100000,
  two seeds, one T4; staging and SM clock change together", naming ISSUE-37 (S2 never re-measured that way); tags
  and compact only with the limits of ISSUE-36 and ANN-1 / ANN-2. ncu is NOT_MEASURED (ISSUE-18); the SASS claim
  rests on a manual reading (ISSUE-19). The dudect timebox of session 32 stands: no further dudect job.
- The obliviousness section of docs/REPORT_CH4_NOTES.md is generated (`python -m vcloak.bench.report_oblivious`,
  command in runs/20261013-091541_M08_issue17_table/report_command.txt). Never edit it by hand.
- Database: `docker compose up -d --wait db` (postgres:16, 127.0.0.1:54329; docker.exe is under
  %LOCALAPPDATA%/Programs/DockerDesktop/resources/bin). Fallback: `python scripts/pgdev.py up` (never both).
  Integration tests SKIP when no database answers: read the skip count before calling G1 a pass.
- Repo contract (ADR-014): `fetch_candidates` raises `CandidateOverflow` above K; `rewrite_window` needs the stored
  row count; re-shuffle through `storage.reshuffle.reshuffle_window(repo, engine, win)`.
- Service (ADR-015): `python -m vcloak.cli serve --dev --store sqlite`; `scripts/smoke_service.py` is the live round
  trip. One thread owns the engine. Log only through `service.logsafe`; its allow-list is final and pinned by
  tests/security/test_log_redaction.py.
- Restart (ADR-016): only `ack: "stored"` (201) means durable; a kill loses the in-memory queue by design. M15 must
  name the ack it measures (ISSUE-23). `scripts/smoke_restart.py` is the live check.
- Sessions (ADR-017, ADR-018): `vcloak serve --sessions` (off by default). State is in memory (ISSUE-26). E5 matrix:
  `python bench/run_session_matrix.py`. SEC-DPOP-VERIFY-US is a laptop-CPU time: M15 must say whether `--sessions`
  was on and how many sockets were open (ISSUE-27).
- Client (ADR-019): `vcloak.client` never imports `vcloak.service`. Never claim forward secrecy or a verified
  cross-sender order (ISSUE-28).
- M13 (ADR-020..022): browser tests need Chrome (read the skip count). `serve --dev --compare` stores every message
  twice: never measure on it. `/v1/stats/live` `last_write_ms` is never a metric (ISSUE-33).
- M14: `python bench/run_security_eval.py --stage s1|attack|uniformity|trace` (schemas m14_eval*, dropped at each
  run; `eval.traffic.replay` needs `autorun=False`). Local runs are the numpy simulator: correctness only, never a
  GPU result. S1-S5 are measured on the real stack (job 20261013-105517_M14, Colab session 20261013-054610: T4 +
  PostgreSQL in the runner). results/security and section 4.S of the notes are generated: never edit them by hand,
  re-run runs/20261013-115636_M14_security_ingest_report/report_command.txt (`vcloak.bench.report_security`).
  Left: S7 (oracle run locally against the ingested numbers) and S6 (decision of ISSUE-40 first). W300 is dumped
  only: its peak occupancy is above CAND_K. The runner stack job shape is `bench/jobs/M14.json`.
