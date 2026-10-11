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

## Audit M01 — 2026-10-11 — session 3 — result: PASS
| Item | Result | Evidence |
|---|---|---|
| A1 | PASS | `bitonic_pairs` equals `bitonic_schedule` for every n = 2..2^12: test_pairs_equal_schedule 12/12 (runs/20261011-164329_M01_oracle_checks/audit_a1_a2.txt) |
| A2 | PASS | test_sort_equals_lexsort 60/60 = 12 sizes x {random, sorted, reverse, all_equal, two_value}, 3 seeds each (runs/20261011-164329_M01_oracle_checks/audit_a1_a2.txt) |
| A3 | PASS | two generations in separate processes hash-identical, `make_golden.py --check` exit 0 (runs/20261011-164329_M01_oracle_checks/s5_golden.txt, golden_gen1.sha256, golden_gen2.sha256); also asserted by tests/unit/test_oracle_golden.py |
| A4 | PASS | `grep -rn "HKDF\|hmac\|AESGCM" src/vcloak/oracle` returns nothing (runs/20261011-164329_M01_oracle_checks/a4_grep.txt, empty); kept as a unit test |
| G1 | PASS | runs/20261011-164329_M01_oracle_checks/pytest.txt (148/148 oracle tests); full local suite pytest_all.txt (181 passed, 1 gpu test deselected); pytest_as_runner.txt (181 with VCLOAK_RUNNER=kaggle) |
| G2 | PASS | runs/20261011-164329_M01_oracle_checks/check_metrics.txt (8 rows, 0 problems); M01 records no metrics |
| G2b | N/A | no performance or side-channel metric in M01; nothing was timed |
| G3 | N/A | check_oblivious.py is created in M03; no kernel changed. The reference sort uses selects only (test_access_trace_is_data_independent) |
| G4 | N/A | check_secrets.py is created in M02. Manual: the only key is the test key in tests/testkeys.py; test_golden_files_do_not_contain_key_material passes; RefKeys hides its fields from repr |
| G5 | N/A | M01 creates the CPU references; their GPU twins arrive in M03-M05 |
| G6 | PASS | 13/13 deliverable paths exist (runs/20261011-164329_M01_oracle_checks/deliverables_ls.txt) |
| G7 | PASS | checked after commit (clean tree, [owner:Abhishek], tag M01-done) |
| G8 | PASS | STATE: M01 DONE at S5 (1 session), next_unit M02, gpu_job.pending null |
| G9 | PASS | SESSION_LOG session 3, this AUDIT_LOG entry, ISSUE-4 opened |
| G10 | PASS | manifest validates (`new_run.py --validate`); the suite was run three times this session (pytest.txt, pytest_all.txt, pytest_as_runner.txt) with the same PASS outcome |
Notes: correctness only, numpy backend, no number from this session is a result. The statistics tests assert on
p-values and tau bands computed from the fixed test key, so they are deterministic; none of those values is
recorded as a metric (the E0-E2 measurements belong to M14). `ruff` reports one pre-existing E501 in
scripts/record_env.py (M00), left untouched (runs/20261011-164329_M01_oracle_checks/ruff.txt). The run manifest's
git_sha is the HEAD at run creation, before this session's commits.

## Audit M02 — 2026-10-11 — session 4 — result: PASS
| Item | Result | Evidence |
|---|---|---|
| A1 | PASS | RFC 8439 §2.3.2 block, §2.4.2 keystream, §2.5.2 Poly1305, §2.8.2 AEAD: 4/4 vector tests pass, vectors read from tests/golden/rfc8439_*.json (runs/20261011-171553_M02_crypto_checks/audit_a1_a2.txt) |
| A2 | PASS | test_keystream_equals_cryptography_over_1_mib 9/9 = 3 keys x 3 nonces x 1 MiB, byte-equal to `cryptography` ChaCha20 (runs/20261011-171553_M02_crypto_checks/audit_a1_a2.txt) |
| A3 | PASS | every single-bit flip of the 44 bytes, a wrong key and wrong lengths give (False, 0, 0) with no exception (runs/20261011-171553_M02_crypto_checks/audit_a3.txt). Manual: the same file lists every branch in aead_ref.py — nonce length, blob length (public), `pt is None`, and the `except InvalidTag`; the tag comparison itself is inside OpenSSL and no line reads tag bytes |
| A4 | PASS | `python scripts/check_secrets.py` exit 0 on the repo (runs/20261011-171553_M02_crypto_checks/check_secrets.txt); a planted random key in a temp dir gives exit 1 (s6_planted.txt); `secrets/` is ignored and nothing under it is tracked (a4_gitignore.txt) |
| G1 | PASS | runs/20261011-171553_M02_crypto_checks/pytest.txt (72/72 module tests); pytest_all.txt (252 passed, 2 skipped); pytest_as_runner.txt (252 passed, 2 skipped with VCLOAK_RUNNER=kaggle); s7_m01_tests.txt (147 oracle tests passed, 1 skipped) |
| G2 | PASS | runs/20261011-171553_M02_crypto_checks/check_metrics.txt (8 rows, 0 problems); M02 records no metrics |
| G2b | N/A | no performance or side-channel metric in M02; nothing was timed |
| G3 | N/A | check_oblivious.py is created in M03; M02 adds no kernel. The CPU references are NumPy/OpenSSL correctness references, not server kernels |
| G4 | PASS | same evidence as A4. First run of the scanner: 7 golden files allow-listed by file hash, 4 runs by token hash (3 inline RFC 8439 vectors, 1 GPU bundle digest), each with a reason in scripts/secrets_allowlist.json |
| G5 | N/A | M02 creates the CPU references; their GPU twins arrive in M04-M05 |
| G6 | PASS | 14/14 deliverable paths exist (runs/20261011-171553_M02_crypto_checks/deliverables_ls.txt) |
| G7 | PASS | checked after commit (clean tree, [owner:Abhishek], tag M02-done) |
| G8 | PASS | STATE: M02 DONE at S7 (1 session), next_unit M03, gpu_job.pending null |
| G9 | PASS | SESSION_LOG session 4, this AUDIT_LOG entry, ISSUE-4 closed, ISSUE-5 opened |
| G10 | PASS | manifest validates (`new_run.py --validate`); the module tests and the full suite were each run more than once this session with the same PASS outcome |
Notes: correctness only, numpy backend, no number from this session is a result. The bucket χ² test asserts
p > 0.01 for B in {16, 256, 1000} on the fixed test key, so it is deterministic; its statistics are printed in
audit_a1_a2.txt and are not recorded as metrics. The first full-suite run of the session had 2 failures, both
fixed before the evidence runs: a test wrote hex.log and HEX.log (one file on Windows), and the M01 test
test_oracle_imports_without_cryptography failed once aead_ref imported `cryptography` unconditionally (aead_ref
now imports it under try/except and reports IMPLEMENTED False without it). Not verified here: that the Kaggle
runner has `cryptography` (ISSUE-3 covers its package set); without it the oracle silently uses its NumPy
stand-in, visible only through crypto_hooks.backend_name(). `ruff` still reports the one pre-existing E501 in
scripts/record_env.py (ruff.txt). The run manifest's git_sha is the HEAD at run creation, before this commit.
