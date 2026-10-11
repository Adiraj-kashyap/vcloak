# SESSION LOG (append-only; newest at the bottom; format: ai/LOGGING_AND_AUDIT.md §1)

## Session 1 — 2026-10-11 01:48 — M00 Bootstrap & GPU probe — owner:Aditya
- Steps: S1→S6 gate (status after: BLOCKED_HUMAN — GPU JOB READY)
- Did: ran setup/bootstrap.ps1 (venv, packages, git init, identity Aditya); .gitignore; kit committed.
- Did: pyproject.toml, requirements.lock, requirements-gpu.txt, tasks.py, src/vcloak/{config,runs}.py,
  src/vcloak/gpu/{runtime,sim,telemetry}.py, scripts/{gpujob,new_run,check_metrics}.py, tests/unit (5 files).
- Did: kernels/vector_add.cu + bench/probe_gpu.py + bench/jobs/M00.json; packed job 20261011-014756_M00.
- Evidence: runs/20261011-014812_M00_local_checks (pytest 33/33; gpujob round trip + tamper 12/12;
  check_metrics self-test 6/6; real bundle unpacked, dry-run and bundled tests 32 passed/2 skipped).
- Metrics added: none (nothing measurable without the GPU; no numpy number recorded)
- Decisions: none
- Issues: opened ISSUE-2 (GPU JOB READY); opened and closed ISSUE-1 (bootstrap.ps1 BOM)
- Deviations from spec: (a) manifest/run code lives in src/vcloak/runs.py with scripts/new_run.py as its CLI,
  because the runner bundle ships src/ but must write manifests; (b) scripts/ is added to the bundle so the
  bundled tests import; (c) bundle_sha256 is a content hash excluding job.json (a file cannot hold its own hash);
  (d) manifest status gains FAIL; (e) docs/ENV.md and STATE env are deferred to S7 (need the ingested probe).
- Commit: 092fd4a
- Next: M00 S6 ingest → S7 → audit ; human action: ISSUE-2

- GPU-JOB 20261011-014756_M00 ingested 2026-10-11 16:34: runner kaggle, gpu Tesla T4, session 20261011-110131, overall exit 0, runs 20261011-110031_M00_gpu_probe, 20261011-110133_M00_gpu_probe, 8 metrics indexed.

## Session 2 — 2026-10-11 16:40 — M00 Bootstrap & GPU probe — owner:Aditya
- Steps: S6 ingest→S7 (status after: DONE)
- Did: verified and ingested results_20261011-014756_M00.zip (Kaggle, Tesla T4, 2 probe runs, vector-add 0 mismatches).
- Did: scripts/record_env.py (new) fills STATE local/runner and writes docs/ENV.md from the ingested probe.
- Did: fixed two tests that assumed runner == local (scripts/check_metrics.py self-test, tests/unit/test_runs_manifest.py).
- Did: evidence/gpu + evidence/terminal captures (5 rows in evidence/INDEX.md).
- Evidence: runs/20261011-163648_M00_ingest_checks (pytest 33/33 local, 33/33 as runner; check_metrics 8 rows PASS; self-test 6/6; probe gates PASS),
  runs/20261011-110031_M00_gpu_probe, runs/20261011-110133_M00_gpu_probe
- Metrics added: ENV-PEAK-BW, ENV-D2D-BW, ENV-MAX-LOG2N, ENV-VRAM-FREE (one row per probe run; backend cupy, runner kaggle)
- Decisions: none
- Issues: closed ISSUE-2; opened ISSUE-3 (runner package set differs from requirements-gpu.txt)
- Deviations from spec: (a) the runner was Kaggle, not Colab; (b) scripts/record_env.py is not in the M00 deliverables
  list, added so STATE.runner is generated, not typed (A3); (c) the runner's optional unit_tests command exited 1
  (2 test bugs, fixed here); (d) ncu_counters_permitted left unknown — not probed in M00.
- Commit: PENDINGHASH
- Next: M01 S1 ; human action: none
