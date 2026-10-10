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
