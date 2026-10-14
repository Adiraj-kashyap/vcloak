# STATE — single source of progress (agent-maintained)

```yaml
project: v-cloak
kit_version: 1.0
last_session: 50
last_session_date: 2026-10-14
current_module: M15
current_step: S2
status: BLOCKED_HUMAN         # NOT_STARTED | IN_PROGRESS | AUDIT_PENDING | AUDIT_FAILED | DONE | BLOCKED_HUMAN | BLOCKED_TECH
next_unit: M15
last_checkpoint: 2026-10-14 session 50: M15 S2 prep done, job 20261014-065041_M15 packed (ISSUE-50); next: ingest it, then S3
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
  pending: 20261014-065041_M15
  last_ingested: 20261013-224820_M08_ncu
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
| M08 | GPU obliviousness audit (E3) | Aditya | M06 | no | DONE | S5 | 12 |
| M09 | Storage (PostgreSQL) | Divyansh | M06 | no | DONE | S5 | 1 |
| M10 | Service & scheduler | Divyansh | M09 | no | DONE | S5 | 2 |
| M11 | Session security (E5) | Divyansh | M10 | no | DONE | S7 | 2 |
| M12 | Client SDK & CLI | Abhishek | M11 | no | DONE | S4 | 1 |
| M13 | Frontend: chat + server view | Abhishek | M12 | no | DONE | S6 | 5 |
| M14 | Security evaluation (E0–E2, anon set) | Abhishek | M08, M10 | no | DONE | S7 | 6 |
| M15 | End-to-end performance (E6) | Divyansh | M10, M11 | no | BLOCKED_HUMAN | S2 | 2 |
| M16 | Results export | Abhishek | M07, M08, M14 | no | DONE | S4 | 2 |
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
- ISSUE-12 (CLOSED, accepted limitation): state the device part of write_epoch against EPOCH_MS first (valid rows
  only). The whole call at 65536 slots: old code a stable miss (runs/20261011-215653_M07_pipeline); current code UNMEASURED
  under valid conditions (Colab 2 vCPU and Kaggle 4 vCPU both UNSTABLE). Never write that it fits or misses, never
  quote an UNSTABLE attempt, never call the two runs a before/after. M15 gives no verdict for that size. No column
  arrays, no further job. Section 4.P.6 of the notes is marked STALE by hand (the only hand edit).
- ADR-025: a PC with an NVIDIA GPU is a third runner, `pc-<gpu>`, never `local`; kit in pc_runner/ (HANDOFF.md says
  how that PC was really set up). Both of its jobs are ingested (session 47, runner pc-rtx3050laptopgpu). PC numbers
  are never mixed with T4 numbers; the `runner` block above stays the Kaggle T4 (record_env.py was not run for the PC).
- ADR-024: comparisons only within one runner platform (provider + vCPU); a comparison job names it in its spec
  (`runner_required`, `cpu_count_required`) and the runner refuses another; provenance lines carry the vCPU count.
- M16 (DONE): `python scripts/export_results.py` (`--check` in audits) writes results/paper, results/figures,
  results/PAPER_UPDATES.md, results/deck_numbers.md and report/TRACEABILITY.md; never edit them by hand. Run it again
  after every ingest that changes the index. A1 is amended (ISSUE-46): a value without a METRIC-ID must come from an
  INGESTED run or the exporter refuses it. Opportunistic only: if an M14-type job runs for another reason, index the
  9 macros of TRACEABILITY section 1. scripts/ and tests/ are in the job bundle: pack after the last code commit.
- M08 is DONE with a negative result: dudect FAILS for aead_conv, aead_tag and the whole write_epoch call (ISSUE-17,
  closed). Diagnostics trace the AEAD FAILs to the harness staging and the whole-call FAIL to host Python state.
  ADR-023: P3 is claimed for the KERNELS only; host timing is a limitation. Never write "constant time".
- How M14/M20/M22 quote M08: AEAD only as "no dependence on the contents detected with symmetric staging, N 100000,
  two seeds, one T4; staging and SM clock change together", naming ISSUE-37 (S2 never re-measured that way). The
  kernel-only series of tags and compact are NOT_MEASURED (ISSUE-36 closed, ANN-4): never write "no dependence
  detected" for them. SASS is a manual reading (ISSUE-19). No further dudect job.
- ncu (ISSUE-48 closed): the T4 is NOT_MEASURED (Kaggle refuses the counters); divergence was measured on
  pc-rtx3050laptopgpu, in its own table (4.O.5, ncu_second_table.tex). Always lead with the positive control ("an
  instrument that read N divergent targets on a planted leak reported 0 on ..."), name the runner, state both
  platforms. bitonic_pairs_global is NOT_MEASURED there (empty counters, SASS has branches; ANN-5). Never a T4 value.
- The obliviousness section of docs/REPORT_CH4_NOTES.md and the block of docs/RESULTS_ANALYSIS.md are generated
  (`python -m vcloak.bench.report_oblivious`; both commands: runs/20261014-014529_M08_issue48_report/report_command.txt,
  which replaces the one of runs/20261013-171026_M16_prefixes). Never edit them by hand.
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
- M14: `python bench/run_security_eval.py --stage s1|attack|uniformity|trace` (`eval.traffic.replay` needs
  `autorun=False`). Local runs are the simulator: never a GPU result. S1-S5 and S6 are measured on the real stack
  (jobs 20261013-105517_M14 and 20261013-125843_M14_s6, two Colab sessions). results/security and section 4.S are
  generated (line 2 of runs/20261013-171026_M16_prefixes/report_command.txt). Never write "the GPU matches the oracle":
  31 of 35 rows agree, 2 differ on the oracle side (ISSUE-41). Occupancy above CAND_K at W300 and at 1000 users: ISSUE-43.
- M15 (ADR-026): `python bench/run_e2e.py --mode vcloak|baseline --users U` is one cell; it starts the service
  itself (never `--compare`), sessions on, `ack: stored`, no WebSocket. Samples count by their scheduled time. A
  numpy cell is a correctness run: no metric, never indexed.
- ADR-027 (the owner): two-party conversations only, declared scope; every population states "two users per
  conversation"; groups are future work (docs/REFINEMENTS.md, kept by M20). M15 cells: 10/50/200 users at 0.15
  messages per user per second (at 0.2 the 200-user cell can exceed CAND_K), SLOTS 256, two repetitions:
  `python bench/run_e2e_cells.py`. No statement about 1000 users end to end. Never shrink, drop or retry a cell:
  report which and why to the owner first. Cell run names stay under 43 characters (check_secrets).
