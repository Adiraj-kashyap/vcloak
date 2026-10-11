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

## Audit M03 — 2026-10-11 — session 5 — result: PARTIAL (prep: local checks PASS; A1, A2, G5 and S1/S6 wait for GPU job 20261011-173759_M03; module not DONE)
Evidence dir: runs/20261011-173514_M03_bitonic_prep (numpy backend, correctness only)

| Check | Result | Evidence / note |
|---|---|---|
| A1 | PENDING (GPU) | Local half PASS: NumPy twins byte-equal to the oracle for n in {2^6, 2^10, 2^16} x {random seeds 1-3, all-equal, sorted, reverse, two-value}, 21/21, plus 24 small (n, T) cases x 3 seeds, the global kernel alone at 2^10, and every launch against the oracle's intermediate state (pytest.txt). The real bitonic.cu source, compiled by g++ and run on the CPU, is byte-equal to the twins, 37/37 (same file, test_bitonic_cpu_shim). No CUDA device has run the kernels yet: the 84 `gpu` tests are skipped locally and are the job's `pytest_bitonic` and `pytest_bitonic_max_log2n` commands |
| A2 | PENDING (GPU) | By construction: test_no_element_is_written_by_two_threads passes 4/4 (each global launch, and each stage and the load/store of the shared kernels, partitions its elements into one pair per thread); barriers listed in audit_a2_a4.txt. `compute-sanitizer --tool racecheck` runs inside bench/bitonic_smoke.py on the runner and is recorded as a count or NOT_MEASURED with the reason |
| A3 | PASS | check_oblivious.txt: 3 files, 0 findings, exit 0. check_oblivious_planted.txt: a planted `if (hi[i] > hi[l])` gives 1 BRANCH finding, exit 1. check_oblivious_selftest.txt: 10/10 planted leaks flagged on their own lines, clean copy clean |
| A4 | PASS | audit_a2_a4.txt: launch_plan, clamp_tile and _global take n, T, k, j only; the driver reads `.shape`, `.dtype`, `.ndim`, `.flags` of the columns and never their contents; test_plan_covers_every_stage_once_in_order 72/72 |
| G1 | PASS | pytest.txt: 192 passed, 84 skipped (all 84 are `gpu`-marked); pytest_all.txt: 432 passed, 86 skipped |
| G2 | PASS | check_metrics.txt: 8 rows, 0 problems. This session adds no metric; the launch-plan counts in audit_a2_a4.txt are derived from n and T, not measured |
| G2b | N/A (prep) | nothing was timed; the smoke script wrote NOT_MEASURED under numpy (not kept as a run) |
| G3 | PASS | same evidence as A3. First run of this check in the project: vector_add.cu, common.cuh and bitonic.cu are clean |
| G4 | PASS | check_secrets.txt before the pack; after the pack `check_secrets.py` still exits 0 (237 files), because pack now allow-lists its bundle digest |
| G5 | PENDING (GPU) | see A1; local half over 3 sizes x 3 seeds x 4 adversarial inputs passes |
| G6 | PASS | deliverables_ls.txt: common.cuh, bitonic.cu, kernels.py, check_oblivious.py, tests/gpu/test_bitonic.py, plus sim.py, bitonic_smoke.py, jobs/M03.json |
| G7 | PASS | d91bfd6 carries [owner:Aditya]; checked again after the closing commit |
| G8 | PASS | STATE: M03 BLOCKED_HUMAN at S6, sessions 1, next_unit M03, gpu_job.pending 20261011-173759_M03 |
| G9 | PASS | SESSION_LOG session 5, this entry, ISSUE-5 closed, ISSUE-6 opened |
| G10 | PASS | manifest validates; the module tests ran three times this session with the same outcome (pytest.txt, pytest_repeat.txt, and once more after the last edit) |
Notes: what is and is not verified. Verified locally: the index arithmetic and mask logic of the kernels (twins vs
oracle) and the C++ source itself (g++ at -std=c++14, fibers for threads, a real barrier for __syncthreads). Not
verified: that nvrtc compiles the source with -std=c++17 and the `-I` include, that the generated code behaves the
same, and anything about speed. The CPU stand-in runs a block's threads in a fixed round-robin order, so it cannot
expose a race that depends on thread interleaving; the racecheck on the runner is the test for that.
check_oblivious.py reads source text: it cannot see a branch the compiler introduces (M08 covers SASS and Nsight)
and does not check data-dependent division latency. At n = 2^max_log2n the job compares the GPU with np.lexsort
for all seven inputs and with the twin for one (see the Amendments note in the module file). `ruff` reports only
the pre-existing E501 in scripts/record_env.py (ruff.txt). The run manifest's git_sha is the HEAD at run creation,
before commit d91bfd6.

## Audit M03 — 2026-10-11 — session 6 — result: PASS
Evidence dirs: runs/20261011-122303_M03_bitonic_smoke (cupy, Kaggle Tesla T4, GPU job 20261011-173759_M03, git d91bfd6),
runs/20261011-181052_M03_ingest_audit (local checks, numpy), gpujobs/out/20261011-173759_M03/{result.json,logs/}

| Item | Result | Evidence |
|---|---|---|
| A1 Bit-exact vs the oracle | PASS | logs/03_pytest_bitonic.txt: 219 passed, 0 failed on the T4 (the 37 skips are the Windows-only g++ stand-in); logs/05_pytest_bitonic_max_log2n.txt: 7 passed at n = 2^max_log2n; smoke summary.json: mismatches 0 at 2^16. Local half unchanged: runs/20261011-181052_M03_ingest_audit/pytest.txt (192 passed, 84 gpu-skipped) |
| A2 No element written twice per launch | PASS | racecheck.txt: `RACECHECK SUMMARY: 0 hazards displayed (0 errors, 0 warnings)` at n = 2^12, compute-sanitizer exit 0, the child sort reported CHILD_SORT_OK; by-construction test passes on both backends (pytest logs above) |
| A3 check_oblivious clean, planted branch flagged | PASS | check_oblivious.txt (3 files, 0 findings, exit 0; also exit 0 on the runner, logs/02_check_oblivious.txt); check_oblivious_planted.txt (1 BRANCH finding, exit 1); check_oblivious_selftest.txt (11/11) |
| A4 Launch configuration depends only on n and T | PASS | runs/20261011-173514_M03_bitonic_prep/audit_a2_a4.txt; the driver is unchanged since d91bfd6 (the job would be stale otherwise, and ingest verified the sha) |
| G1 | PASS | pytest.txt (192 passed, 84 skipped), pytest_all.txt (432 passed, 86 skipped); every skip is `gpu`-marked and ran on the runner |
| G2 | PASS | check_metrics.txt: 11 rows, 0 problems |
| G2b | PASS | the 3 new rows come from a manifest with backend cupy and a gpu_job block (gates.txt: backend_cupy_gpu_job_block) |
| G3 | PASS | same as A3 |
| G4 | PASS | check_secrets.txt: 256 files, 0 key-like runs; run again after the evidence copies and logs, before the commit |
| G5 | PASS | GPU vs oracle and GPU vs NumPy twin, byte equality, n in {2^6, 2^10, 2^16} x seeds {1, 2, 3} x 4 adversarial inputs, plus 2^24 (logs/03, logs/05) |
| G6 | PASS | deliverables_ls.txt |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M03 DONE at S6, sessions 2, next_unit M04, gpu_job.pending null, last_ingested 20261011-173759_M03 |
| G9 | PASS | SESSION_LOG session 6 and its GPU-JOB line, this entry, ISSUE-6 closed, ISSUE-7 opened |
| G10 | PASS | both run manifests validate (new_run.py --validate); the local module tests gave the same outcome as in session 5 |
Notes: S6 gates are in runs/20261011-181052_M03_ingest_audit/gates.txt, computed from the ingested files.
- The runner's pytest logs are `-q` summaries: they give counts, not test names. That all 84 `gpu` tests ran is
  inferred from the counts (no `needs a CUDA device` skip appears on the runner; 77 + 7 = the 84 skipped locally).
- At n = 2^max_log2n the reference is np.lexsort for seven inputs and the twin for one (module Amendments).
- Racecheck covers one size (2^12) and one input; it is a dynamic check of that run, not a proof.
- SM clock: 900 MHz in the start snapshot (idle, util 6%) and 1590 MHz in the end snapshot; no throttle reason,
  CV 0.0118 over the 30 timed runs. The gate is a drop of more than 15%; this is a rise from idle, so the run is
  kept as OK. But the sampler caught 1 sample, taken before the ramp, so clock stability *during* the timed
  section is not shown by telemetry, only suggested by the CV (ISSUE-7, to fix before M07).
- The smoke time is a sanity value for one n on a shared T4. It is not an M07 result and is not to be quoted as one.

## Audit M04 — 2026-10-11 — session 7 — result: PARTIAL (prep: local checks PASS; A1, A2, G5 on the GPU and S4 wait for GPU job 20261011-183051_M04; module not DONE)
| Item | Result | Evidence |
|---|---|---|
| A1 RFC vectors pass on the GPU | PENDING | ISSUE-8. Local half PASS: RFC 8439 §2.3.2 and §2.4.2 through the NumPy twin (test_rfc8439_2_3_2_block_from_a_one_thread_kernel[numpy], test_rfc8439_2_4_2_keystream[numpy]) and §2.3.2 through the real chacha_tags.cu compiled with g++ (test_cu_block_is_rfc8439_2_3_2): runs/20261011-182840_M04_chacha_prep/pytest.txt |
| A2 bit-exact tags/subkeys/buckets vs M02 across sizes and seeds | PENDING | ISSUE-8. Local half PASS: twins = chacha_ref for tags (epoch and re-shuffle) at 2^6, 2^10, 2^16 x seeds 1-3 x 4 epochs, subkeys for 6 master keys, buckets at 2^6, 2^10, 2^16 x seeds 1-3 x 5 input kinds and 9 moduli; the C source = chacha_ref = twin (65 shim tests): runs/20261011-182840_M04_chacha_prep/pytest.txt (221 passed, 146 gpu-skipped) |
| A3 check_oblivious.py is clean | PASS | runs/20261011-182840_M04_chacha_prep/check_oblivious.txt (6 files, 0 findings, exit 0); a leak planted in each of chacha_tags.cu, prf.cu, chacha20.cuh and common.cuh is flagged at its line (test_check_oblivious_flags_a_leak_planted_in_the_chacha_kernels, runs/20261011-182840_M04_chacha_prep/pytest.txt); self-test 11/11 (runs/20261011-182840_M04_chacha_prep/check_oblivious_selftest.txt) |
| A4 no key passed by value from the host in production wrappers | PASS | runs/20261011-182840_M04_chacha_prep/audit_a4.txt: every kernel takes its key as `const u32*`; every wrapper checks a uint32[8] buffer and raises TypeError on bytes/bytearray/memoryview (test_wrappers_reject_key_bytes); the tests upload TEST keys only |
| G1 | PASS (local) | runs/20261011-182840_M04_chacha_prep/pytest.txt (221 passed, 146 skipped: gpu); full suite runs/20261011-182840_M04_chacha_prep/pytest_all.txt (653 passed, 232 skipped) |
| G2 | PASS | runs/20261011-182840_M04_chacha_prep/check_metrics.txt (11 rows, 0 problems); no number recorded this session |
| G2b | PASS | no metric added; bench/chacha_smoke.py under numpy reports NOT_MEASURED for all three metrics (runs/20261011-182840_M04_chacha_prep/chacha_smoke_numpy.txt) |
| G3 | PASS | as A3 |
| G4 | PASS | runs/20261011-182840_M04_chacha_prep/check_secrets.txt (0 key-like runs); re-run after the pack: 287 files, PASS (the bundle digest is allow-listed by pack) |
| G5 | PENDING | ISSUE-8: the GPU side of test_chacha.py (146 tests, incl. test_gpu_equals_simulator at 3 sizes x 3 seeds and test_max_log2n) runs in the job |
| G6 | PASS | runs/20261011-182840_M04_chacha_prep/deliverables_ls.txt (chacha20.cuh, chacha_tags.cu, prf.cu, gpu/kernels.py, tests/gpu/test_chacha.py) |
| G7 | PASS | checked after commit (clean tree, [owner:Aditya]) |
| G8 | PASS | STATE: M04 BLOCKED_HUMAN at S4, gpu_job.pending 20261011-183051_M04, sessions 1 |
| G9 | PASS | SESSION_LOG session 7, this entry, ISSUE-8 opened, ISSUE-7 updated |
| G10 | PASS | manifest validates (new_run.py --validate); the module tests re-run in a fresh process give the same result (runs/20261011-182840_M04_chacha_prep/pytest_repeat.txt: 221 passed, 146 skipped) |
Notes: nothing on this page ran on a GPU. The twins and the g++ build show that the kernel logic is right; they do
not show that nvrtc compiles the files, that the device produces the same bytes, or any speed. mod_public replaces
`%` on the PRF output with a Barrett reduction on a public modulus; whether nvcc emits branch-free code for it and
for the rotates is an M08 (SASS) question, not answered here. ruff reports 1 E501 in scripts/record_env.py, which
predates this session (runs/20261011-182840_M04_chacha_prep/ruff.txt); the files of this session are clean. The run manifest has dirty:true because
the run was taken before the commit; the code it tested is commit 680c28d.

## Audit M04 — 2026-10-11 — session 8 — result: PASS
Evidence dirs: runs/20261011-134013_M04_chacha_smoke (cupy, Kaggle Tesla T4, GPU job 20261011-183051_M04, git 680c28d),
runs/20261011-191448_M04_ingest_audit (local checks, numpy), gpujobs/out/20261011-183051_M04/{result.json,logs/}

| Item | Result | Evidence |
|---|---|---|
| A1 RFC vectors pass on the GPU | PASS | gpujobs/out/20261011-183051_M04/logs/03_pytest_chacha.txt: test_rfc8439_2_3_2_block_from_a_one_thread_kernel[cupy] and test_rfc8439_2_4_2_keystream[cupy] PASSED on the T4 (gates.txt: A1_rfc8439_2_3_2_on_gpu, A1_rfc8439_2_4_2_on_gpu) |
| A2 bit-exact tags/subkeys/buckets vs M02 across sizes and seeds | PASS | logs/03: 299 passed, 0 failed, 0 skipped (tags, subkeys, buckets, blocks vs chacha_ref on numpy and cupy; test_gpu_equals_simulator at 3 sizes x seeds 1-3); logs/06: test_max_log2n[1..3] passed at n = 2^24; smoke: 0 mismatches at 2^20 (gates.txt) |
| A3 check_oblivious.py is clean | PASS | runs/20261011-191448_M04_ingest_audit/check_oblivious.txt (6 files, 0 findings); the same on the runner (logs/02); self-test 11/11 (check_oblivious_selftest.txt); planted leaks flagged (test_check_oblivious_flags_a_leak_planted_in_the_chacha_kernels, logs/03 and pytest.txt) |
| A4 no key passed by value from the host in production wrappers | PASS | runs/20261011-191448_M04_ingest_audit/audit_a4.txt: every kernel takes its key as `const u32*`; the wrappers raise TypeError on host bytes; test_wrappers_reject_key_bytes and test_chain_from_master_on_the_device[cupy] PASSED on the runner; code unchanged since 680c28d |
| G1 | PASS | runs/20261011-191448_M04_ingest_audit/pytest.txt (413 passed, 230 gpu-skipped locally); full suite pytest_all.txt (653 passed, 232 skipped); on the T4: logs/03 (299 passed), logs/06 (3 passed), logs/04 (bitonic regression, 212 passed) |
| G2 | PASS | check_metrics.txt: 14 metric rows, 0 problems |
| G2b | PASS | the 3 new rows come from a manifest with backend cupy and a gpu_job block (gates.txt: backend_cupy_gpu_job_block); indexed by `gpujob.py ingest`, not by hand |
| G3 | PASS | same as A3 |
| G4 | PASS | check_secrets.txt: 314 files, 0 key-like runs; this is the run taken after the evidence copies and logs, before the commit |
| G5 | PASS | GPU vs chacha_ref and GPU vs NumPy twin, byte equality, 3 sizes x seeds 1-3, plus 2^24 x seeds 1-3 (logs/03, logs/06) |
| G6 | PASS | deliverables_ls.txt |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M04 DONE at S4, sessions 2, next_unit M05, gpu_job.pending null, last_ingested 20261011-183051_M04 |
| G9 | PASS | SESSION_LOG session 8 and its GPU-JOB line, this entry, ISSUE-8 closed, ISSUE-7 updated |
| G10 | PASS | both run manifests validate (new_run.py --validate); the local module tests gave the same outcome as in session 7 |
Notes: the S4 gates are in runs/20261011-191448_M04_ingest_audit/gates.txt, computed from the ingested files.
- The smoke ran with the SM clock at 810-840 MHz (util 3-6%); the M03 job saw the same T4 model reach 1590 MHz under
  load. The 30 timed runs total about 6 ms of kernel time, so the GPU never left its low-clock state. The 15% gate
  compares the snapshot after the warm-up with the one after the runs (+3.7%), so the run is OK by the rule, but the
  value describes a T4 at roughly half clock. It is a sanity value, not an M07 result, and is not to be quoted as one.
- CV 0.083 passes the 0.10 limit with little margin; the first timed run (0.2796 ms) is the largest sample.
- GB/s here is generated tag bytes (16 n) over the median kernel time, not memory traffic.
- At n = 2^max_log2n the tags are compared with the reference for seeds 1-3 and with the twin once (Amendments).
- Whether nvcc emits branch-free code for mod_public and the rotates is an M08 (SASS) question, not answered here.
- The runner's Python is 3.13.15 and the laptop's 3.14.0 (ISSUE-3 covers the package-set difference).
