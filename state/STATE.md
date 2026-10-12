# STATE — single source of progress (agent-maintained)

```yaml
project: v-cloak
kit_version: 1.0
last_session: 20
last_session_date: 2026-10-12
current_module: M11
current_step: S1
status: BLOCKED_HUMAN        # NOT_STARTED | IN_PROGRESS | AUDIT_PENDING | AUDIT_FAILED | DONE | BLOCKED_HUMAN | BLOCKED_TECH
next_unit: M11
last_checkpoint: 2026-10-12 fix ISSUE-17 prep done, job 20261012-113437_M08_issue17 packed (ISSUE-24); M11 not started
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
  last_session_id: "20261012-031230"
gpu_job:                    # set by the gpu-job skill
  pending: 20261012-113437_M08_issue17   # job id awaiting the upload of the human, or null
  last_ingested: 20261012-041010_M08
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
| M08 | GPU obliviousness audit (E3) | Aditya | M06 | no | DONE | S5 | 2 |
| M09 | Storage (PostgreSQL) | Divyansh | M06 | no | DONE | S5 | 1 |
| M10 | Service & scheduler | Divyansh | M09 | no | DONE | S5 | 2 |
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
- G4 runs `python scripts/check_secrets.py`. `gpujob.py pack` allow-lists the new `bundle_sha256` itself (ISSUE-5, closed):
  commit `scripts/secrets_allowlist.json` with the session; it is not bundled, so that commit does not make a job stale.
- The M05 and M06 jobs ran on a newer Kaggle image (driver 580.178.04, CUDA 12.8 / runtime 12090) than the `runner` block
  above (M00 probe). Do not mix timings across the two images (ISSUE-3).
- **M19 is calendar-bound.** Once M16 has real results, treat M19 as the highest-priority unmet unit
  even if other modules look more urgent — criterion 9 awards nothing without a dated submission proof.
- The five quick-tagged `P-*` rows from M06 are smoke values, superseded by the M07 rows of session 20261011-213139.
- Kaggle unpacks an uploaded job.zip into a folder. Cell 2 of the notebook finds either form; in a GPU JOB READY
  issue never tell the human to set a path to job.zip on Kaggle.
- M07 results are one runner session (20261011-213139, T4 / Xeon 2.00GHz x4). 65 of its 213 rows are UNSTABLE
  (ISSUE-15); never quote K-BITONIC-BW-PCT below 2^18 as bandwidth (ISSUE-14). Figures and notes are regenerated
  with `python -m vcloak.bench.report`, never edited by hand.
- write_epoch misses EPOCH_MS at 2^16 slots because of host Python (one uuid object per row), not the GPU
  (ISSUE-12, BLOCKS M15): vectorise the row building in its own unit, then re-measure with a new GPU job.
- M08 is DONE with a negative result: dudect FAILS for aead_conv, aead_tag and the whole write_epoch call (ISSUE-17,
  high, BLOCKS M14; cause unknown). Never write that AEAD open or the whole write path is timing-independent before
  it is closed. Its diagnostic job 20261012-113437_M08_issue17 is pending (ISSUE-24): when its results zip is in
  gpujobs/inbox, `continue` ingests it and judges ISSUE-17 by the reading rules written in that issue (owner Aditya,
  module M08; M11 is NOT started by that session). The status BLOCKED_HUMAN belongs to this job, not to M11. ncu is NOT_MEASURED (ISSUE-18); the SASS
  claim rests on bench/sass_explained.json, a manual reading of the nvcc listing (ISSUE-19).
- The obliviousness section of docs/REPORT_CH4_NOTES.md is generated by `python -m vcloak.bench.report_oblivious`
  (markers BEGIN/END M08 OBLIVIOUS); report.py keeps it. Never edit either part by hand.
- Database: `docker compose up -d --wait db` (postgres:16, 127.0.0.1:54329; Docker Desktop must be running, and in a
  shell opened before the install docker.exe is under %LOCALAPPDATA%/Programs/DockerDesktop/resources/bin). Fallback
  without Docker: `python scripts/pgdev.py up` (17rc1, same port, never both). The integration tests SKIP when no
  database answers, so read the skip count before calling G1 a pass. M09 passed on both servers.
- Repo contract (ADR-014): `fetch_candidates` raises `CandidateOverflow` above K; `rewrite_window` needs the stored row
  count; re-shuffle through `storage.reshuffle.reshuffle_window(repo, engine, win)`. M10 must handle the overflow.
- Service (ADR-015): `python -m vcloak.cli serve --dev --store sqlite` runs it without a database; `scripts/smoke_service.py`
  is the live round trip. The server assigns conv_id (hash of conv_token) and seq (arrival position). One thread owns
  the engine. Log only through `service.logsafe` (new fields go on its allow-list in M11, never around it).
- Restart (ADR-016, ISSUE-22 closed): the store lists the windows still to be re-shuffled (`pending_windows`); new
  Repo implementations need `mark_pending` / `pending_windows`. A kill loses the in-memory queue by design: only
  `ack: "stored"` (201) means durable. M12 must use it and drop repeats, M15 must name the ack it measures (ISSUE-23).
  `scripts/smoke_restart.py` is the live kill-and-restart check. The service has never run on a CUDA device.
