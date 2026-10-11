# AUDIT LOG (append-only; format: ai/LOGGING_AND_AUDIT.md §4)

## Audit M00 — 2026-10-11 — session 1 — result: PARTIAL (S1–S5 PASS; A3, A4 wait for the GPU job; module not DONE)
| Item | Result | Evidence |
|---|---|---|
| A1 local tests pass with no GPU; sim.py importable | PASS | runs/20261011-014812_M00_local_checks/pytest.txt (33 passed, 1 gpu test deselected); step_checks.txt |
| A1b git identity set | PASS | step_checks.txt (Aditya / adiraj.kashyap.01@gmail.com) |
| A2 pack → ingest round trip; tampered bundle rejected | PASS (local half) | gpujob_roundtrip_tamper.txt (12/12: corrupt zip, wrong bundle sha, wrong git sha, unknown job id, stale code, path traversal all rejected); bundle_dry_run.txt. The round trip uses a simulated runner in a temp repo; the real round trip is ISSUE-2 |
| A3 ingested probe shows a real NVIDIA GPU | PENDING | ISSUE-2 (no result bundle yet) |
| A4 measured D2D ≤ theoretical peak | PENDING | ISSUE-2 |
| A5 check_metrics rejects a numpy-backed performance metric | PASS | check_metrics_selftest.txt (6/6 cases) |
| G1 | PASS | pytest.txt (33/33) |
| G2 | PASS | check_metrics.txt (0 metric rows, 0 problems); no number recorded this session |
| G2b | PASS | no performance metric exists; probe under numpy reports NOT_MEASURED (bundle_dry_run.txt) |
| G3 | N/A | check_oblivious.py arrives in M03; the only kernel (vector_add.cu) handles public data and branches on thread id and n |
| G4 | N/A | check_secrets.py arrives in M02; no key material exists yet |
| G5 | N/A | GPU twin comparison needs the runner (probe checks vector-add against NumPy there) |
| G6 | PARTIAL | all deliverables exist except docs/ENV.md (S7, written from the ingested probe) |
| G7 | PASS | see commit in SESSION_LOG |
| G8 | PASS | STATE: M00 BLOCKED_HUMAN at S6, gpu_job.pending set |
| G9 | PASS | SESSION_LOG session 1, this entry, ISSUE-1 closed, ISSUE-2 open |
| G10 | PASS | manifest validates (new_run.py --validate); commands listed in the manifest |
Notes: the local-checks manifest has dirty:true because the freshly packed job.json was untracked when the run
started; the code it tested is commit a45088b. check_metrics.py does not yet scan web/** for literals (added in M13/M18).

## Audit M00 — 2026-10-11 — session 2 — result: PASS
| Item | Result | Evidence |
|---|---|---|
| A1 | PASS | pytest -m "not gpu": 33 passed, no GPU present (runs/20261011-163648_M00_ingest_checks/pytest.txt); sim importable (runs/20261011-163648_M00_ingest_checks/deliverables.txt) |
| A1b | PASS | git user.name=Aditya, user.email set (runs/20261011-163648_M00_ingest_checks/deliverables.txt) |
| A2 | PASS | real bundle packed, run on Kaggle, verified and ingested (state/SESSION_LOG GPU-JOB line); re-ingest refused (runs/20261011-163648_M00_ingest_checks/gpujob_reverify_after_ingest.txt); tamper test in pytest.txt and runs/20261011-014812_M00_local_checks/gpujob_roundtrip_tamper.txt |
| A3 | PASS | Tesla T4, CC 7.5, NVML available, backend cupy (runs/20261011-110133_M00_gpu_probe/device.json, nvidia_smi.txt); STATE runner written by scripts/record_env.py |
| A4 | PASS | ENV-D2D-BW 238.25 <= ENV-PEAK-BW 320.064 GB/s in both probe runs (runs/20261011-163648_M00_ingest_checks/probe_gates.txt) |
| A5 | PASS | self-test 6 cases incl. numpy_performance_metric_rejected (runs/20261011-163648_M00_ingest_checks/check_metrics_selftest.txt) |
| G1 | PASS | runs/20261011-163648_M00_ingest_checks/pytest.txt (33/33); also 33/33 with VCLOAK_RUNNER=kaggle (runs/20261011-163648_M00_ingest_checks/pytest_as_runner.txt) |
| G2 | PASS | runs/20261011-163648_M00_ingest_checks/check_metrics.txt (8 rows, 0 problems) |
| G2b | PASS | all 8 ENV rows backend cupy, runner kaggle, gpu_job block present (runs/20261011-163648_M00_ingest_checks/probe_gates.txt) |
| G3 | N/A | check_oblivious.py is created in M03; kernels/ holds only the vector-add probe (no secrets) |
| G4 | N/A | check_secrets.py is created in M02; no keys exist yet |
| G5 | N/A | no GPU twin of a CPU reference in M00 (vector-add checked against host: 0 mismatches) |
| G6 | PASS | 24/24 deliverables (runs/20261011-163648_M00_ingest_checks/deliverables.txt) |
| G7 | PASS | checked after commit (clean tree, [owner:Aditya]) |
| G8 | PASS | STATE: M00 DONE at S7, next_unit M01, gpu_job.pending null |
| G9 | PASS | SESSION_LOG session 2, AUDIT_LOG entry, ISSUE-2 closed, ISSUE-3 opened |
| G10 | PASS | every run dir manifest validates (runs/20261011-163648_M00_ingest_checks/probe_gates.txt manifest_valid; new_run.py --validate) |
Notes: the bundle holds two probe runs because the runner cell was executed twice (sessions 20261011-110028 and
-110131); both are real and indexed, and STATE/ENV.md use the one matching result.json. The runner's optional
unit-test command exited 1: two tests assumed runner == local (test bugs, fixed this session, reproduced and
re-run locally with VCLOAK_RUNNER=kaggle). GPU clocks are unlocked on the free runner (SM clock moved during the
run, no throttle reasons); M07 must apply its clock-stability gate. ncu_counters_permitted stays unknown (not probed).
