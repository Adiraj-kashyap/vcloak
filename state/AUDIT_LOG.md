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

## Audit M05 — 2026-10-11 — session 9 — result: PARTIAL (prep: local checks PASS; A1, A2, A4, G5 on the GPU wait for GPU job 20261011-193547_M05; module not DONE)
| Item | Result | Evidence |
|---|---|---|
| A1 RFC vectors (Poly1305, AEAD) pass on the GPU | PENDING | ISSUE-9. Local half PASS: RFC 8439 §2.5.2 and §2.8.2 through the NumPy twins (test_rfc8439_2_5_2_poly1305[numpy], test_rfc8439_2_8_2_aead[numpy]) and through the real poly1305.cu compiled with g++ (test_cu_poly1305_is_rfc8439_2_5_2, test_cu_aead_tag_is_rfc8439_2_8_2): runs/20261011-193238_M05_aead_restore_prep/pytest.txt |
| A2 bit-exact seal/open vs the reference, including tamper cases | PENDING | ISSUE-9. Local half PASS: twin seal = aead_ref.seal_seq at 2^6, 2^10, 2^16 x seeds 1-3 and 5 adversarial column kinds; twin open = aead_ref.open_seq on mixed rows (hits, other conversation, one-bit flips in tag / ciphertext / nonce, random dummies) at the same sizes and seeds, for two query conversations; all 352 single-bit flips of a row are misses under 3 keys; Poly1305 = `cryptography` at 15 lengths x 3 seeds plus reduction edge inputs; the C source = reference = twin (51 shim tests): same pytest.txt |
| A3 no branch on `ok`, `conv` or tag bytes | PASS | runs/20261011-193238_M05_aead_restore_prep/check_oblivious.txt (11 files, 0 findings, exit 0); 8 leaks planted in aead_open.cu, aead_seal.cu, poly1305.cuh, poly1305.cu and aead_seq.cuh are each flagged at their line (test_check_oblivious_flags_a_leak_planted_in_the_aead_kernels); manual review: runs/20261011-193238_M05_aead_restore_prep/audit_a3.txt lists every control construct of the five files: the thread guards `t >= n`, literal-bound loops, and in poly1305_bytes the loops and the `rem > 0` test on the public byte count. The tag compare is an OR of XORs, `ok` and `miss` are used as values and masks only, the final Poly1305 subtraction is selected by `sel` |
| A4 restore result equals the oracle for all test windows | PENDING | ISSUE-9. Local half PASS: 50 windows (K from 1 to 257, no hit to all hits, shared-bucket rows, dummies, repeated seq) = read_window_ref, each also read for a second conversation; restore sort = lexicographic order for 8 sizes x 3 seeds x 5 key kinds; compaction = oblivious_compact_ref at 3 sizes x 3 seeds x 6 dummy patterns; tags -> permute -> compact = the oracle write order for 6 (slots, n_real) x 3 epochs: same pytest.txt |
| G1 | PASS (local) | runs/20261011-193238_M05_aead_restore_prep/pytest.txt (404 passed, 363 skipped: gpu); full suite pytest_all.txt in the same run (1057 passed, 595 skipped) |
| G2 | PASS | runs/20261011-193238_M05_aead_restore_prep/check_metrics.txt (14 rows, 0 problems); no number recorded this session |
| G2b | PASS | no metric added; nothing was timed |
| G3 | PASS | as A3; self-test 11/11 (check_oblivious_selftest.txt) |
| G4 | PASS | runs/20261011-193238_M05_aead_restore_prep/check_secrets.txt (0 key-like runs); re-run after the pack: PASS (the bundle digest is allow-listed by pack) |
| G5 | PENDING | ISSUE-9: the GPU side of test_aead.py and test_restore.py (363 tests, incl. test_gpu_equals_simulator at 3 sizes x 3 seeds and test_max_log2n in both files) runs in the job |
| G6 | PASS | runs/20261011-193238_M05_aead_restore_prep/deliverables_ls.txt (poly1305.cuh, aead_open.cu, aead_seal.cu, gpu/kernels.py wrappers, tests/gpu/test_aead.py, tests/gpu/test_restore.py; extra: aead_seq.cuh, poly1305.cu, see the Amendments note) |
| G7 | PASS | checked after commit (clean tree, [owner:Aditya]) |
| G8 | PASS | STATE: M05 BLOCKED_HUMAN at S4, gpu_job.pending 20261011-193547_M05, sessions 1 |
| G9 | PASS | SESSION_LOG session 9, this entry, ISSUE-9 opened |
| G10 | PASS | manifest validates (new_run.py --validate); the module tests re-run in a fresh process give the same result (pytest_repeat.txt in the same run: 404 passed, 363 skipped) |
Notes: nothing on this page ran on a GPU. The twins and the g++ build show that the kernel logic is right; they do
not show that nvrtc compiles the files, that the device produces the same bytes, or any speed. Whether nvcc emits
branch-free code for `diff == 0`, `conv != q_conv` and the Poly1305 select is an M08 (SASS) question, not answered
here. ruff reports 1 E501 in scripts/record_env.py, which predates this session (ruff.txt in the run); the files of
this session are clean. The run manifest has dirty:true because the run was taken before the commit; the code it
tested is commit 69a2cc3. scripts/check_oblivious.py changed this session (three public parameter names added),
so the checker that passed A3 is not the one that passed M04; its self-test and the M03/M04 planted-leak tests
still pass in the full suite.

## Audit M05 — 2026-10-11 — session 10 — result: PASS
Evidence dirs: gpujobs/out/20261011-193547_M05/{result.json,logs/} (cupy, Kaggle Tesla T4, session 20261011-141833,
git 69a2cc3), runs/20261011-213200_M05_ingest_audit (gates.txt from the ingested logs; local checks, numpy),
runs/20261011-193238_M05_aead_restore_prep (prep, session 9)

| Item | Result | Evidence |
|---|---|---|
| A1 RFC vectors (Poly1305, AEAD) pass on the GPU | PASS | gpujobs/out/20261011-193547_M05/logs/03_pytest_aead.txt: test_rfc8439_2_5_2_poly1305[cupy] and test_rfc8439_2_8_2_aead[cupy] PASSED (gates.txt, A1 lines) |
| A2 bit-exact seal/open vs the reference, including tamper cases | PASS | logs/03: 213 passed, 0 failed, 0 skipped. On cupy: seal = aead_ref (9 cases, 3 sizes x seeds 1-3) plus 5 adversarial column kinds; open = aead_ref on valid, tampered and dummy rows (9 cases); every single-bit flip is a miss (3); Poly1305 = reference at every alignment (45); aead_tag = reference (21); wrong key misses everything; reduction edges (gates.txt, A2 lines) |
| A3 no branch on `ok`, `conv` or tag bytes | PASS | check_oblivious on the runner (logs/02: 11 files, 0 findings) and locally (runs/20261011-213200_M05_ingest_audit/check_oblivious.txt, same); self-test 11/11 (check_oblivious_selftest.txt); the planted-leak test passed on the runner (logs/03, 8 cases); manual review runs/20261011-193238_M05_aead_restore_prep/audit_a3.txt still applies: `git diff 69a2cc3 HEAD -- kernels src tests bench scripts/check_oblivious.py` is empty |
| A4 the restore result equals the oracle for all test windows | PASS | logs/04_pytest_restore.txt: 497 passed, 0 failed, 0 skipped. On cupy: 50 windows = read_window_ref; restore sort = lexicographic order (120 cases); compaction = oblivious_compact_ref (54); write-path order = oracle (18) (gates.txt, A4 lines) |
| G1 | PASS | runs/20261011-213200_M05_ingest_audit/pytest.txt (817 passed, 593 gpu-skipped locally); pytest_all.txt (1057 passed, 595 skipped); on the T4: logs/03 (213 passed), logs/04 (497 passed), logs/05 (511 passed), logs/06 (6 passed), no skip in any |
| G2 | PASS | check_metrics.txt: 14 metric rows, 0 problems; no number added this module |
| G2b | PASS | no performance or side-channel metric exists for M05: the job runs tests only (Amendments, "No bench") |
| G3 | PASS | same as A3 |
| G4 | PASS | check_secrets.txt in the run dir, taken after the evidence copies and logs, before the commit |
| G5 | PASS | GPU vs aead_ref / the oracle and GPU vs NumPy twin, byte equality: test_gpu_equals_simulator at sizes 64, 1024, 65536 x seeds 1-3 in both test files (logs/03, logs/04), plus test_max_log2n x seeds 1-3 in both files (logs/06: 6 passed) |
| G6 | PASS | deliverables_ls.txt (poly1305.cuh, aead_open.cu, aead_seal.cu, the four wrappers in gpu/kernels.py, tests/gpu/test_aead.py, tests/gpu/test_restore.py; extra aead_seq.cuh, poly1305.cu per the Amendments) |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M05 DONE at S4, sessions 2, next_unit M06, gpu_job.pending null, last_ingested 20261011-193547_M05 |
| G9 | PASS | SESSION_LOG session 10 and its GPU-JOB line, this entry, ISSUE-9 closed, ISSUE-3 updated |
| G10 | PASS | the run manifest validates (new_run.py --validate); the local module and full-suite outcomes equal those of session 9 (1057 passed / 595 skipped); gates.txt is regenerated by gates_m05.py in the run dir |
Notes: the gates are in runs/20261011-213200_M05_ingest_audit/gates.txt, computed from the ingested files.
- The job produced no run dir and no metric (tests only), so M05 adds nothing to METRICS_INDEX. Any speed of the
  AEAD, restore or compaction path is NOT_MEASURED until M07.
- The runner image differs from the M03/M04 jobs: driver 580.178.04, nvcc CUDA 12.8, CUDA runtime 12090, kernel
  6.18.48 (before: 580.82.07, CUDA 13.0, runtime 13000, kernel 6.6.122). Same GPU model and CuPy 14.0.1. Correctness
  results are byte comparisons and do not depend on it; timings from the two images must not be mixed (ISSUE-3).
  STATE.md `runner` still shows the M00 probe values.
- All three requirements were already present on the runner (`cryptography` included); nothing was installed.
- Whether nvcc emits branch-free code for `diff == 0`, `conv != q_conv` and the Poly1305 select is an M08 (SASS)
  question, not answered here.
- The local run manifest has dirty:true (taken before the commit); the code tested on the GPU is commit 69a2cc3.

## Audit M06 — 2026-10-11 — session 11 — result: PARTIAL (prep: local checks PASS; A1, A2, A4, G5 on the GPU wait for GPU job 20261011-215111_M06; module not DONE)
Evidence dir: runs/20261011-214849_M06_engine_prep (numpy backend, laptop); code commit 67504cd

| Item | Result | Evidence |
|---|---|---|
| A1 engine outputs bit-exact vs the oracle (injected nonces/uuids) | PENDING | ISSUE-10. Local half PASS on the twins (pytest.txt): write_epoch = write_epoch_ref at SLOTS 2^6, 2^10, 2^16 x seeds 1-3 (full, half+1 and 1 real row), 5 adversarial batches, 6 epochs, 5 public-parameter sets; reshuffle_window = reshuffle_ref for 12 sizes x 3 windows; read_window = read_window_ref for 50 windows, plus padding to K; bucket_of = chacha_ref.bucket_prf |
| A2 the host master buffer is zeroized (test) | PENDING | ISSUE-10 for the device path (copy_from_host, memset). Local half PASS: test_load_master_zeroizes_the_host_buffer..., ...even_when_derivation_fails, test_zeroize_clears_the_device_buffer... [numpy] in pytest.txt |
| A3 no subkey in host memory (no `.get()` / `asnumpy` on key buffers) | PASS | audit_a3.txt: keystore.py has no match; engine.py has one device download (`_d2h`, line 176) whose 5 callers pass order, blobs, bkt and perm only. Enforced by test_a3_the_key_store_has_no_device_to_host_path and test_a3_the_engine_downloads_only_through_d2h_and_never_a_key_buffer (pytest.txt) |
| A4 stage timings exist and are consistent | PENDING | ISSUE-10 (CUDA events). Local half PASS on the host clock: test_last_timings_of_every_call[numpy], test_an_empty_epoch...[numpy]: all keys present, unused stages 0, stages add up to total |
| G1 | PASS (local) | pytest.txt (82 passed, 68 skipped: gpu); full suite pytest_all.txt (1139 passed, 663 skipped) |
| G2 | PASS | check_metrics.txt (14 rows, 0 problems); no number recorded this session |
| G2b | PASS | no metric added; runs/20261011-215050_M06_pipeline_smoke_quick is numpy and records every metric as NOT_MEASURED |
| G3 | PASS | check_oblivious.txt (11 files, 0 findings); kernels/ unchanged this session |
| G4 | PASS | check_secrets.txt, taken after the pack (380 files, 0 key-like runs) |
| G5 | PENDING | ISSUE-10: the cupy half of both test files (68 tests), incl. test_gpu_engine_equals_the_simulator_engine at 3 sizes x 3 seeds and test_max_log2n x 3 seeds |
| G6 | PASS | deliverables_ls.txt (keystore.py, engine.py, tests/gpu/test_engine.py, tests/integration/test_engine_vs_oracle.py, bench/run_pipeline.py) |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M06 BLOCKED_HUMAN at S5, gpu_job.pending 20261011-215111_M06, sessions 1 |
| G9 | PASS | SESSION_LOG session 11, this entry, ISSUE-10 opened |
| G10 | PASS | both manifests validate (new_run.py --validate); the module tests re-run in a fresh process give the same result (pytest_repeat.txt: 82 passed, 68 skipped) |
Notes: nothing on this page ran on a GPU.
- The engine adds no kernel; what is new and untested on a device is the CuPy plumbing: a non-blocking stream as the
  current stream, pinned buffers with `set(stream=)` / `get(stream=, out=)`, `MemoryPointer.copy_from_host` from the
  bytearray, `runtime.memset`, and stage timing with consecutive events. These lines have never executed.
- The timing test asserts a strictly positive time for every stage a call uses. That holds on the host clock; on
  CUDA events a very short transfer stage could read 0 and fail the test without the engine being wrong.
- The pipeline smoke times whole calls, host work included (Python builds one row object per message). Its numbers
  will be smoke values, quick-tagged; real-time behaviour (p99 < EPOCH_MS) is M07/M15, NOT_MEASURED here.
- ruff reports 1 E501 in scripts/record_env.py, which predates this session (ruff.txt); this session's files are clean.
- The prep run manifest has dirty:true (taken before the commit); the code it tested is commit 67504cd.

## Audit M06 — 2026-10-11 — session 12 — result: PASS (ingest of GPU job 20261011-215111_M06; module DONE)
Evidence dir: runs/20261011-221434_M06_ingest_audit (gates.txt, laptop) ; GPU logs gpujobs/out/20261011-215111_M06/logs ; GPU run runs/20261011-163049_M06_pipeline_smoke_quick ; code commit 67504cd

| Item | Result | Evidence |
|---|---|---|
| A1 engine outputs bit-exact vs the oracle (injected nonces/uuids) | PASS | gates.txt: on the T4, write_epoch = write_epoch_ref (9 cases at SLOTS 2^6, 2^10, 2^16 x seeds 1-3; 6 epochs; 5 public-parameter sets; 5 adversarial batches), reshuffle_window = reshuffle_ref (12), read_window = read_window_ref for 50 windows, padding to K, bucket_of = reference (9), round trip; 04_pytest_engine_vs_oracle.txt (111 passed, 0 skipped). The smoke bench compared every timed config with the oracle: 0 mismatches in 5 configs |
| A2 the host master buffer is zeroized (test) | PASS | 03_pytest_engine.txt [cupy]: test_load_master_zeroizes_the_host_buffer_and_derives_the_m02_subkeys, test_zeroize_clears_the_device_buffer_and_empties_the_store, test_reload_replaces_the_keys_and_clears_the_old_buffer; and test_the_host_buffer_is_zeroized_even_when_derivation_fails (36 passed, 0 skipped) |
| A3 no subkey in host memory (no `.get()` / `asnumpy` on key buffers) | PASS | unchanged code (67504cd); audit_a3.txt of session 11; both test_a3_* tests also passed on the runner |
| A4 stage timings exist and are consistent | PASS | test_last_timings_of_every_call[cupy] and test_an_empty_epoch...[cupy] passed; timer = cupy.cuda.Event; raw.csv: in all 105 timed calls the 9 stages add up to total (worst relative gap 7.06e-08), every stage a call uses is > 0 and the unused ones are 0 |
| G1 | PASS | pytest.txt (82 passed, 68 gpu-skipped, local numpy); pytest_all.txt (1139 passed, 663 skipped); on the runner 36 + 111 + 1221 + 3 passed, 0 failed, 0 skipped |
| G2 | PASS | check_metrics.txt (19 rows, 0 problems); the 5 new rows were written by gpujob.py ingest and each equals the median of its raw.csv rows (gates.txt) |
| G2b | PASS | manifest of the smoke run: backend cupy, quick true, gpu_job block with this job id and bundle sha (gates.txt); no numpy number recorded |
| G3 | PASS | check_oblivious.txt locally and 02_check_oblivious.txt on the runner: 11 files, 0 findings; kernels/ unchanged in M06 |
| G4 | PASS | check_secrets.txt (402 files, 0 key-like runs, nothing tracked under secrets/); re-run after the records were written |
| G5 | PASS | test_gpu_engine_equals_the_simulator_engine: 9 passed, sizes 64, 1024, 65536 x seeds 1-3; test_max_log2n x 3 seeds passed at SLOTS = 2^24 (07_pytest_max_log2n.txt) |
| G6 | PASS | deliverables_ls.txt (5 paths) |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M06 DONE at S5, sessions 2, next_unit M07, gpu_job.pending null, last_ingested 20261011-215111_M06 |
| G9 | PASS | SESSION_LOG session 12 and its GPU-JOB line, this entry, ISSUE-10 closed, ISSUE-11 and ISSUE-12 opened, ISSUE-3 updated |
| G10 | PASS | both manifests validate (new_run.py --validate); the local module and full-suite outcomes equal those of session 11; gates.txt is regenerated by gates_m06.py in the run dir |
Notes: the gates are in runs/20261011-221434_M06_ingest_audit/gates.txt, computed from the ingested files.
- The smoke run's own status is UNSTABLE: P-READ-WINDOW-MS-K128 had CV 0.106 and 0.119 on its two attempts (limit
  0.10). The module asks for smoke values only and sets no CV gate, so this does not fail M06; the value is in
  METRICS_INDEX as ingested (quick-tagged) and must not be quoted as a result (ISSUE-11).
- The SM clock was 585 MHz after the warm-up and after the runs in every config (1590 MHz was seen under load in the
  M03 job). All five values were therefore taken on a GPU that had not ramped up (ISSUE-7, ISSUE-11).
- The host stage is the largest part of write_epoch: 0.51 of 1.57 ms at SLOTS 64, 9.64 of 10.84 ms at 4096 and
  199.78 of 208.11 ms at 65536 (stage medians against the median total). The device stages together are about 8 ms
  at 65536, of which d2h is 5.7 ms. The median total at 65536 is above EPOCH_MS = 200 (ISSUE-12). This is one quick
  run of full epochs (n_real = SLOTS) on a 4-vCPU runner; whether an epoch meets its deadline is M07/M15.
- 15 runs per config (quick), not the 30 that a performance result needs. These are smoke values, not M07 results.
- Same runner image as the M05 job (driver 580.178.04, CUDA runtime 12090, nvcc 12.8), not the M00/M03/M04 one.
- The run dir of the GPU run carries the runner's UTC time (16:30); the job was packed at 21:51 local time (UTC+5:30).
- The local run manifest has dirty:true (taken before the commit); the code tested on the GPU is commit 67504cd.

## Audit M07 — 2026-10-11 — session 13 — result: PARTIAL (prep; GPU job 20261011-224124_M07 pending)
| Item | Result | Evidence |
|---|---|---|
| A1 every plotted point traces to a run dir; check_metrics passes | PENDING | no figure exists yet (S6 is the ingest session); runs/20261011-223709_M07_prep_audit/check_metrics.txt (19 rows, 0 problems) |
| A2 GPU timings use CUDA events; CPU uses perf_counter_ns (grep) | PASS (code) | runs/20261011-223709_M07_prep_audit/audit_a2_grep.txt: `time_gpu` records two `cp.cuda.Event`s on the stream, `time_cpu` uses `time.perf_counter_ns`; the engine's stage clock is unchanged (M06). To be confirmed on the runner by tests/gpu/test_timing.py |
| A3 fair comparison: transfers included, same runner session, caveat recorded | PASS (code) | the crossover uses the `sort_e2e` series (pinned H2D + sort + D2H) and refuses inputs of another `session_id`: test_cpu_and_crossover_flow_in_one_session, test_crossover_refuses_another_session (runs/20261011-223709_M07_prep_audit/pytest.txt); the caveat is written to summary.json and the manifest notes. PENDING for the numbers |
| A4 unstable runs are reported, not dropped | PASS (code) | both attempts stay in raw.csv and summary.json and the metric value becomes UNSTABLE: test_gpu_part_flow_with_stand_in_device, test_measure_full_repeats_once_and_keeps_both, test_realtime_gate_and_metrics. PENDING for the numbers |
| A5 fused variant bit-identical to global-only (spot test) | PENDING | the sweep compares the two variants on the device at every n (`identical_to_global`, a FAIL of the run if not); tests/gpu/test_bitonic.py is in the job as a regression |
| G1 | PASS (local) | runs/20261011-223709_M07_prep_audit/pytest.txt (86 passed, 3 gpu-skipped); pytest_not_gpu.txt (1225 passed, 1 skipped, 665 deselected) |
| G2 | PASS | runs/20261011-223709_M07_prep_audit/check_metrics.txt; no metric row was added this session |
| G2b | PASS | nothing recorded; the four numpy plumbing runs have every metric NOT_MEASURED (plumbing_runs.txt) |
| G3 | PASS | runs/20261011-223709_M07_prep_audit/check_oblivious.txt (11 files, 0 findings); kernels/ unchanged |
| G4 | PASS | runs/20261011-223709_M07_prep_audit/check_secrets.txt (437 files, 0 key-like runs); re-run after pack, see the session log |
| G5 | N/A | no new kernel in M07 (Amendments note); the sweep checks every timed output against its reference |
| G6 | PARTIAL | runs/20261011-223709_M07_prep_audit/deliverables_ls.txt: timing.py, baselines.py, run_kernels.py, run_pipeline.py exist; report.py, results/perf and docs/REPORT_CH4_NOTES.md belong to S6 |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M07 BLOCKED_HUMAN at S5, sessions 1, gpu_job.pending 20261011-224124_M07 |
| G9 | PASS | SESSION_LOG session 13, this entry, ISSUE-13 opened, ISSUE-7/11/12 updated |
| G10 | PARTIAL | the five local run dirs have valid manifests; the numbers are reproducible only on a runner |
Notes: a prep session cannot pass A1-A5 for numbers that do not exist; the module stays open until the ingest.
- The CuPy-only paths of bench/run_kernels.py were exercised against tests/fakecupy.py (NumPy arrays with `set`/`get`,
  host-clock events) into tmp_path. That checks the flow and the bookkeeping, not CUDA behaviour.
- `__nanosleep` has never been compiled here. If nvrtc rejects it the three timer tests are skipped with the reason
  and S1's check is then not met; that would be fixed in the next prep session.
- numba is not installed on the laptop: the numba baseline's source ran only under the interpreter (n <= 256).
- ruff reports one line-length finding in scripts/record_env.py:161; it is at HEAD~1 as well and not part of M07.
- The local run manifests have dirty:true (written before the commit); the code in the job is commit c40696b.

## Audit M07 — 2026-10-12 — session 14 — result: PASS
| Item | Result | Evidence |
|---|---|---|
| A1 every plotted point traces to a run dir (sidecar JSON); check_metrics passes | PASS | runs/20261012-033804_M07_ingest_audit/a1_sidecars_and_tags.txt (7 figures, each with a sidecar whose run dirs exist and whose metric ids are all indexed; 201 tagged values in docs/REPORT_CH4_NOTES.md equal their index rows); runs/20261012-033804_M07_ingest_audit/check_metrics.txt (232 rows, 0 problems) |
| A2 GPU timings use CUDA events; CPU uses perf_counter_ns (grep) | PASS | runs/20261012-033804_M07_ingest_audit/audit_a2_grep.txt; summary.json `timer` is cupy.cuda.Event for the kernel sweep and the pipeline and time.perf_counter_ns for the CPU baselines (runs/20261012-033804_M07_ingest_audit/gates.txt); on the T4 the event timer is within 10% of the host clock (ratio 0.9997) and of the nominal sleep (ratio 1.0481), gpujobs/out/20261011-224124_M07/logs/03_pytest_timing.txt |
| A3 fair comparison: transfers included, same runner session, caveat recorded | PASS | runs/20261012-033804_M07_ingest_audit/gates.txt: the crossover uses sort_e2e (H2D + fused sort + D2H); kernel sweep, CPU baselines and crossover all carry session 20261011-213139; the shared-runner caveat is in the crossover manifest, its summary and the notes |
| A4 unstable runs are reported, not dropped | PASS | runs/20261012-033804_M07_ingest_audit/gates.txt: 45 kernel configurations (49 metric rows), 3 pipeline configurations (15 rows) and X-CROSSOVER-N are indexed as UNSTABLE, 65 rows in all; both attempts are in raw.csv and summary.json; figures draw them hollow and the CSV tables flag them |
| A5 fused variant bit-identical to global-only (spot test) | PASS | runs/20261011-213207_M07_kernel_sweep/summary.json `fused_differs_from_global` is empty for the 13 sizes on the T4; 0 mismatches against np.lexsort (runs/20261012-033804_M07_ingest_audit/gates.txt) |
| G1 | PASS | runs/20261012-033804_M07_ingest_audit/pytest.txt (94 passed, 3 gpu-skipped); runs/20261012-033804_M07_ingest_audit/pytest_all.txt (1233 passed, 1 skipped, 665 deselected); on the runner 3 timer tests and 248 engine regression tests passed (logs 03, 04) |
| G2 | PASS | runs/20261012-033804_M07_ingest_audit/check_metrics.txt; runs/20261012-033804_M07_ingest_audit/a1_sidecars_and_tags.txt; the notes and the tables are generated by `python -m vcloak.bench.report` from the run dirs |
| G2b | PASS | runs/20261012-033804_M07_ingest_audit/gates.txt: the four manifests have backend cupy and the gpu_job block of job 20261011-224124_M07; report.py refuses numpy runs and mixed sessions (tests/unit/test_bench_report.py) |
| G3 | PASS | runs/20261012-033804_M07_ingest_audit/check_oblivious.txt (11 files, 0 findings); kernels/ unchanged in M07 |
| G4 | PASS | runs/20261012-033804_M07_ingest_audit/check_secrets.txt (0 key-like runs, 0 tracked files under secrets/); the job used fixed test keys |
| G5 | N/A | M07 adds no kernel (Amendments note); every timed output of the sweep and every pipeline call equals its reference (0 mismatches) |
| G6 | PASS | runs/20261012-033804_M07_ingest_audit/deliverables_ls.txt: timing.py, baselines.py, report.py, run_kernels.py, run_pipeline.py, results/perf (7 figures as png + pdf + json, 4 csv, perf_summary.json), docs/REPORT_CH4_NOTES.md |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M07 DONE at S6, sessions 2, gpu_job.pending null, last_ingested 20261011-224124_M07, next_unit M08 |
| G9 | PASS | SESSION_LOG session 14, this entry, ISSUE-7/11/13 closed, ISSUE-12 updated, ISSUE-14/15 opened |
| G10 | PASS | the four run dirs have valid manifests (git sha, seed, command, env); runs/20261012-033804_M07_ingest_audit/g10_report_rerun.txt: a second run of the report gives byte-identical tables, summary and notes. The measurements themselves can only be repeated on a runner |
Notes:
- PASS means the measurements are recorded honestly, not that the results are all good. Three results are unfavourable
  and are stated as such: the real-time gate FAILS for the whole write_epoch call at SLOTS 65536 (ISSUE-12); 65 of
  213 metric rows are UNSTABLE, including K-AEADOPEN-ROWS-S, K-BUCKETPRF-ROWS-S and X-CROSSOVER-N (ISSUE-15); the
  bandwidth model gives more than 100% at 2^17 (ISSUE-14).
- Most of the sweep ran under the board's power limit at a reduced SM clock; those points are labelled LOW clock.
- S6 has seven figures instead of the four of the module text (Amendments note, 2026-10-12).
- The numbers quoted in ISSUES.md and in the figure labels are indexed values or are derived in gates.txt from raw.csv.
- The CSV tables carry the last-attempt median of UNSTABLE points with a status column; those medians are in
  summary.json and raw.csv but not in the index, where the value is UNSTABLE.
- ruff: src/vcloak/bench and the new test pass; the old line-length finding in scripts/record_env.py:161 is unchanged.
- The local audit manifest has dirty:true (taken before the commit); the measured code is commit c40696b.

## Audit M08 — 2026-10-12 — session 15 — result: PARTIAL (prep session; nothing measured; GPU job 20261012-041010_M08 pending)
| Item | Result | Evidence |
|---|---|---|
| A1 the planted-leak self-test is detected | PENDING (GPU) | job command `dudect_selftest`. Locally only the flow is checked: against the NumPy stand-in device the planted kernel is reported FAIL as expected and a control with the wrong verdict fails the run (runs/20261012-040948_M08_prep_audit/pytest.txt, tests/unit/test_run_dudect.py). That is not a timing result |
| A2 all 5 targets have verdicts at full N | PENDING (GPU) | job command `dudect` (N = 100000 per class, plus the null control). Local plumbing: both classes of all 7 targets prepared and run on the simulator with 0 wrong outputs, every metric NOT_MEASURED (runs/20261012-040958_M08_dudect) |
| A3 SASS branches are all explained | PENDING (GPU) | job command `sass`. Locally NOT_MEASURED: nvcc is not installed (runs/20261012-040959_M08_sass). The parser is tested on a hand-written listing only (tests/data/sass_synthetic.txt) |
| A4 ncu metrics collected or NOT_MEASURED with the reason | PENDING (GPU) | job command `ncu`. Locally NOT_MEASURED: no GPU (runs/20261012-040959_M08_ncu). A refused counter (ERR_NVGPUCTRPERM) is recorded as NOT_MEASURED with exit 0 (tests/unit/test_run_ncu.py) |
| A5 a FAIL on any target opens a high-severity issue that BLOCKS M14 | PENDING (GPU) | no verdict exists yet; run_dudect.py names every FAIL in the manifest notes and never changes a verdict |
| G1 | PASS | runs/20261012-040948_M08_prep_audit/pytest.txt (50 passed, 9 gpu-skipped); runs/20261012-040948_M08_prep_audit/pytest_not_gpu.txt (1283 passed, 1 skipped, 674 deselected) |
| G2 | PASS | runs/20261012-040948_M08_prep_audit/check_metrics.txt (232 rows, 0 problems); no metric row added this session; the three local run dirs carry NOT_MEASURED only |
| G3 | PASS | runs/20261012-040948_M08_prep_audit/check_oblivious.txt (kernels/: 11 files, 0 findings). The planted leak is outside kernels/ and is flagged, as it must be: runs/20261012-040948_M08_prep_audit/check_oblivious_planted.txt (2 findings, exit 1) |
| G4 | PASS | runs/20261012-040948_M08_prep_audit/check_secrets.txt (0 key-like runs); the job uses fixed TEST keys derived from the seed |
| G5 | PENDING (GPU) | tests/gpu/test_planted_leak.py (3 sizes x 3 seeds x 6 inputs, byte equality with the twin) runs in the job; M08 adds no other kernel |
| G6 | PARTIAL | runs/20261012-040948_M08_prep_audit/deliverables_ls.txt: bench/run_dudect.py, bench/run_ncu.sh, bench/run_ncu.ps1, scripts/sass_check.py exist; results/oblivious/* and the obliviousness section of docs/REPORT_CH4_NOTES.md belong to the ingest session (S5) |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M08 BLOCKED_HUMAN at S5, sessions 1, gpu_job.pending 20261012-041010_M08 |
| G9 | PASS | SESSION_LOG session 15, this entry, ISSUE-16 opened |
| G10 | PARTIAL | the four local run dirs have valid manifests at commit fe51656; the measurements can only be reproduced on a runner |
Notes: a prep session cannot pass A1-A5 for results that do not exist; the module stays open until the ingest.
- Nothing in this session ran on a GPU. The CuPy paths of run_dudect.py (events, RawModule for the planted kernel,
  uploads with `set`) ran only against tests/fakecupy.py; write_epoch could not run against the stand-in at all
  (the key store needs real device memory calls) and ran on the numpy backend only.
- The SASS parser and the ncu CSV parser were written against the documented layout of the tools' output and tested
  on hand-written samples. If the real output differs, the raw listing and the raw ncu output are still saved by
  the job, the run is marked FAIL or NOT_MEASURED, and the parser is corrected at ingest. `sass_check.py --listing`
  re-analyses a saved listing.
- sass_check.py classifies statically and flow-insensitively; a `public` there is not a proof. A3 still needs every
  branch read in the listing.
- dudect's second-order test is not implemented; the verdict rests on the raw Welch t and the 100 crops.
- The runtime of the job is unknown: no timing exists for these loops.
- The local manifests say dirty:true because the new run dirs were untracked when they were written; the bundled
  paths were clean and the job is commit fe51656.
- ruff: the new files pass; the old line-length finding in scripts/record_env.py:161 is unchanged (runs/20261012-040948_M08_prep_audit/ruff.txt).

## Audit M08 — 2026-10-12 — session 16 — result: PASS (three dudect findings open as ISSUE-17, which blocks M14)
| Item | Result | Evidence |
|---|---|---|
| A1 the planted-leak self-test is detected | PASS | runs/20261012-031245_M08_dudect_selftest_quick/summary.json: control_leak FAIL as expected, T-DUDECT-MAXT-CONTROL-LEAK 376.9125 at 10000 per class (quick); null control PASS in the quick run (1.933) and at full N (2.0786); runs/20261012-093714_M08_ingest_audit/gates.txt |
| A2 all 5 targets have verdicts at full N | PASS | runs/20261012-031331_M08_dudect/summary.json: bitonic_equal PASS, bitonic_sorted PASS, write_epoch device PASS / whole call FAIL, aead_tag FAIL, aead_conv FAIL, 100000 per class, quick false; max abs(t) of every series recomputed from the raw npz equals the summary (runs/20261012-093714_M08_ingest_audit/gates.txt) |
| A3 SASS branches all explained | PASS | runs/20261012-040020_M08_sass (nvcc -cubin -arch=sm_75, cuobjdump -sass, 6 kernels); bench/sass_explained.json: 16 of 16 conditional branches traced to ids, public parameters or constant loop counters, each checked against the listing by report_oblivious (runs/20261012-093714_M08_ingest_audit/report.txt); no BSSY/BSYNC; limits in ISSUE-19 |
| A4 ncu metrics collected or NOT_MEASURED with the reason | PASS | runs/20261012-040027_M08_ncu: ERR_NVGPUCTRPERM in ncu_query_metrics.txt and ncu_profile_raw.txt; 8 rows NOT_MEASURED with that reason; ISSUE-18 |
| A5 a FAIL on any target opens a high-severity issue that BLOCKS M14 | PASS | state/ISSUES.md ISSUE-17 (high, BLOCKS: M14) for the 3 failing series; the FAILs are in METRICS_INDEX, results/oblivious/summary_table.csv and docs/REPORT_CH4_NOTES.md 4.O.3 unchanged |
| G1 | PASS | runs/20261012-093714_M08_ingest_audit/pytest.txt (80 passed, 9 gpu-skipped); runs/20261012-093714_M08_ingest_audit/pytest_all.txt (1292 passed, 1 skipped, 674 deselected) |
| G2 | PASS | runs/20261012-093714_M08_ingest_audit/check_metrics.txt (263 rows, 0 problems) after the table fix below; every value in the notes section carries its metric tag |
| G3 | PASS | runs/20261012-093714_M08_ingest_audit/check_oblivious.txt (kernels/: 11 files, 0 findings); the same check passed on the runner (gpujobs/out/20261012-041010_M08/logs/02_check_oblivious.txt) |
| G4 | PASS | runs/20261012-093714_M08_ingest_audit/check_secrets.txt (0 key-like runs); the job used fixed TEST keys |
| G5 | PASS | gpujobs/out/20261012-041010_M08/logs/03_pytest_planted_leak.txt: 9 passed on the T4 (3 sizes x 3 seeds, byte equality of the planted kernel with its NumPy twin; M08 adds no other kernel); 0 output mismatches in every dudect target |
| G6 | PASS | runs/20261012-093714_M08_ingest_audit/deliverables_ls.txt: bench/run_dudect.py, bench/run_ncu.sh, bench/run_ncu.ps1, scripts/sass_check.py, results/oblivious/dudect_*.json+png, sass_*.txt, ncu_divergence.csv, docs/REPORT_CH4_NOTES.md (section 4.O) |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M08 DONE at S5, sessions 2, gpu_job.pending null, last_ingested 20261012-041010_M08, next_unit M09 |
| G9 | PASS | SESSION_LOG session 16, this entry, ISSUE-16 closed, ISSUE-17/18/19 opened |
| G10 | PASS | the four ingested run dirs have valid manifests (git fe51656, seed 8, command, env); runs/20261012-093714_M08_ingest_audit/g10_report_rerun.txt: the report regenerates identically and the verdicts are recomputed from the raw data; the measurements themselves need a runner |
Notes:
- The module passes its checklist and still reports a negative result: 3 of 6 target series FAIL (aead_conv 11.6369,
  write_epoch whole call 8.2776, aead_tag 6.2415). The cause is not known. ISSUE-17 lists untested hypotheses
  (asymmetric staging of the classes by the harness, host work inside the timed window, a device effect) and the
  controls that would separate them. No claim of timing independence for AEAD open or the whole write path may be
  made until then.
- One runner session, one shared T4. Every full-N target ran at a LOW SM clock (585 to 1065 MHz of 1590).
- The SASS listing is the nvcc build; the nvrtc code that CuPy executes was not listed (ISSUE-19). The checker's
  own classification (16 DATA, 0 public) is wrong for the reason given there; A3 rests on the manual reading.
- No dynamic divergence evidence (ISSUE-18); the ncu CSV parser is still untested on real output.
- scripts/gpujob.py wrote the stat `max |t|` into METRICS_INDEX and broke 9 rows (check_metrics FAIL, caught here).
  The writer now sanitises cells and the 9 rows were rewritten by the same rule (`max abs(t)`); values untouched.
- The dudect PNGs are the runner's own plots (no PDF / 300 dpi export); a paper-ready export is left to M16.
- ruff: the old line-length finding in scripts/record_env.py:161 is unchanged (runs/20261012-093714_M08_ingest_audit/ruff.txt).

## Audit M09 — 2026-10-12 — session 17 — result: PASS
| Item | Result | Evidence |
|---|---|---|
| A1 the schema has no serial/timestamp columns (test) | PASS | runs/20261012-101327_M09_storage/pytest_verbose.txt: test_schema_has_the_five_columns_and_nothing_that_records_arrival (information_schema.columns of the parent and a partition, no identity or generated column, no sequence, no trigger), test_schema_sql_declares_no_arrival_column, test_sqlite_schema_has_the_five_columns_and_no_arrival_column |
| A2 fetch_candidates always returns exactly K rows | PASS | runs/20261012-101327_M09_storage/pytest_verbose.txt: the fetch tests of the contract on both repositories (K 1, 5, 16, 128 with 0, 1, 5 real rows; exactly K real rows; an empty bucket-window; after a rewrite). Above K the read raises CandidateOverflow instead of returning K rows (ADR-014) |
| A3 after a rewrite, physical order = the new permutation (ctid) | PASS | runs/20261012-101327_M09_storage/pytest_verbose.txt: test_after_a_rewrite_the_physical_order_is_the_new_permutation at three sizes, one of them with out-of-line (TOAST) payloads: row ids in ctid order equal the given order, one xmin, a new relfilenode, no table left over |
| A4 SQLite and Pg pass the same repo tests | PASS | runs/20261012-101327_M09_storage/pytest_sqlite_contract.txt and runs/20261012-101327_M09_storage/pytest_pg_contract.txt: the same class tests/repo_contract.py::RepoContract, 42 passed on each |
| G1 | PASS | runs/20261012-101327_M09_storage/pytest.txt (118 passed, 0 skipped: 50 unit, 68 on PostgreSQL); runs/20261012-101327_M09_storage/pytest_all.txt (1410 passed, 1 skipped, 674 gpu-deselected); runs/20261012-101327_M09_storage/pytest_tasks_test.txt (1342 passed without the integration tests) |
| G2 | PASS | runs/20261012-101327_M09_storage/check_metrics.txt (263 rows, 0 problems). No metric was added: nothing was measured. The table in docs/ENV.md is generated from runs/20261012-101327_M09_storage/pg_settings.json |
| G3 | PASS | runs/20261012-101327_M09_storage/check_oblivious.txt (kernels/: 11 files, 0 findings); M09 adds no kernel. The store holds only values that are public at the database level |
| G4 | PASS | runs/20261012-101327_M09_storage/check_secrets.txt (0 key-like runs). The repository takes no key; the round-trip test uses the fixed TEST master of tests/testkeys.py; the development database has no password (trust on 127.0.0.1) |
| G5 | N/A | no GPU twin in this module |
| G6 | PASS | runs/20261012-101327_M09_storage/deliverables_ls.txt: docker-compose.yml, schema.sql, repo.py (PgRepo, SqliteRepo), reshuffle.py, test_repo_pg.py, test_repo_sqlite.py, docs/ENV.md (storage section) |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M09 DONE at S5, sessions 1, next_unit M10, gpu_job.pending null |
| G9 | PASS | SESSION_LOG session 17, this entry, ISSUE-20 opened |
| G10 | PASS | runs/20261012-101327_M09_storage/manifest.json (git sha, seed, command, env); runs/20261012-101327_M09_storage/g10_rerun.txt: the module tests re-run to the same result (118 passed) |
Notes:
- S1 check: runs/20261012-101327_M09_storage/s1_select1.txt (SELECT 1 through psycopg). S5 check: runs/20261012-101327_M09_storage/show.txt and runs/20261012-101327_M09_storage/pg_settings.json, 14 of 14
  settings equal to the required value by SHOW, and the same 14 as tests.
- Everything ran on a private PostgreSQL 17rc1 cluster, not on postgres:16; docker-compose.yml was never started
  (ISSUE-20). The module header lists Docker or a native install as a human gate; the installed binaries were enough.
- Not tested: the swap under concurrent connections; the lifetime of WAL records. docs/ENV.md says so.
- The manifest of the run is `dirty: true`: the tests ran on the working tree that this session commits.
- ruff is clean (runs/20261012-101327_M09_storage/ruff.txt); the old line-length finding in scripts/record_env.py was fixed while that file was edited.

## Audit M09 (addendum: postgres:16) — 2026-10-12 — session 17 — result: PASS
| Item | Result | Evidence |
|---|---|---|
| A1-A4 on PostgreSQL 16 | PASS | runs/20261012-103011_M09_storage_pg16_docker/pytest.txt (118 passed, 0 skipped; server 16.15 in the compose service, runs/20261012-103011_M09_storage_pg16_docker/s1_select1.txt, runs/20261012-103011_M09_storage_pg16_docker/compose_ps.txt); runs/20261012-103011_M09_storage_pg16_docker/pytest_pg_contract.txt (42 passed) |
| S5 settings on the compose service | PASS | runs/20261012-103011_M09_storage_pg16_docker/show.txt and runs/20261012-103011_M09_storage_pg16_docker/pg_settings.json: 14 of 14 by SHOW; docs/ENV.md regenerated from that file |
| G1, G4, G6, G10 | PASS | runs/20261012-103011_M09_storage_pg16_docker/pytest.txt; runs/20261012-103011_M09_storage_pg16_docker/check_secrets.txt; docker-compose.yml now started for the first time; runs/20261012-103011_M09_storage_pg16_docker/manifest.json valid |
Notes:
- Same code and tests as the audit above (commit db7b746); only the server differs. Closes ISSUE-20, opens ISSUE-21
  for the two things still untested (concurrent swap, WAL lifetime).
- Docker 29.8.2 with Compose v5.5.1, Linux engine on WSL 2 (runs/20261012-103011_M09_storage_pg16_docker/docker_version.txt). The first pull timed out once.

## Audit M10 — 2026-10-12 — session 18 — result: PASS
| Item | Result | Evidence |
|---|---|---|
| A1 Epoch boundaries are wall-clock aligned and never extended (slow engine: overflow carries) | PASS | runs/20261012-104809_M10_service/pytest_checks_verbose.txt: test_a1_a_slow_engine_does_not_extend_the_epoch_and_the_overflow_carries (injected engine of 2.5 epochs per call: epochs 0, 3, 6 written, 4 boundaries counted as missed, 36 carried, arrival order kept), test_a1_an_arrival_after_the_boundary_is_never_taken_into_the_closed_epoch, test_a1_wall_clock_epochs_never_close_before_their_boundary (real clock, 100 ms epochs) |
| A2 Window rewrite happens exactly once per closed window | PASS | runs/20261012-104809_M10_service/pytest_checks_verbose.txt: test_a2_each_closed_window_is_rewritten_exactly_once on SQLite and on PostgreSQL (spy on rewrite_window: calls 0, 1, 2 once each; empty and open windows not rewritten), test_a2_window_close_reshuffles_once_and_only_closed_windows; on PostgreSQL each closed partition has one xmin (test_closed_windows_are_fresh_partitions_without_arrival_columns) |
| A3 Baseline and V-cloak share the API contract (same tests) | PASS | runs/20261012-104809_M10_service/pytest.txt (190 passed): class ServiceContract of tests/service_contract.py runs as TestVcloakSqlite, TestBaselineSqlite, TestVcloakPg, TestBaselinePg |
| A4 No forbidden fields in logs (logsafe unit test) | PASS | runs/20261012-104809_M10_service/pytest_checks_verbose.txt: test_a4_the_log_of_a_service_run_holds_no_forbidden_value plus the allow-list tests of tests/unit/test_logsafe.py; runs/20261012-104809_M10_service/serve_vcloak.log is the log of a real process |
| G1 | PASS | runs/20261012-104809_M10_service/pytest.txt (190 passed, 0 skipped: 129 unit, 61 on PostgreSQL 16); runs/20261012-104809_M10_service/pytest_all.txt (1600 passed, 675 skipped: 674 need a CUDA device, 1 old oracle skip; none for a missing database) |
| G2 | PASS | runs/20261012-104809_M10_service/check_metrics.txt (263 rows, 0 problems). No metric was added: nothing was measured |
| G2b | N/A | no performance or side-channel metric; the backend was numpy |
| G3 | PASS | runs/20261012-104809_M10_service/check_oblivious.txt (kernels/: 11 files, 0 findings); M10 adds no kernel. Host code sees the conversation id by design (S4 of the data flow); the read fetches exactly CAND_K rows |
| G4 | PASS | runs/20261012-104809_M10_service/check_secrets.txt (760 files, 0 key-like runs). --dev builds the public test key from range(32); the passphrase is read from the environment or a prompt and never logged; tests seal the TEST master under throw-away passphrases in tmp_path |
| G5 | N/A | no GPU twin in this module |
| G6 | PASS | runs/20261012-104809_M10_service/deliverables_ls.txt (8 of 8 paths); docs/API.md written; runs/20261012-104809_M10_service/cli_help.txt |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M10 DONE at S5, sessions 1, next_unit M11, gpu_job.pending null |
| G9 | PASS | SESSION_LOG session 18, this entry, ISSUE-21 updated, ISSUE-22 opened |
| G10 | PASS | runs/20261012-104809_M10_service/manifest.json (git sha, seed, command, env); runs/20261012-104809_M10_service/g10_rerun.txt: the module tests re-run to the same result (190 passed) |
Notes:
- Step checks: S2 test_s2_100_sim_epochs_complete_and_the_rows_are_stored (SQLite and PostgreSQL); S3 test_round_trip_200_messages_across_3_windows_in_order (both modes, both stores); S4 test_s4_attack_on_the_baseline_dump_recovers_the_order (tau = 1 as a test assertion, not a recorded metric); S5 test_s5_shutdown_writes_the_queue_and_zeroizes_the_keys.
- Live process: runs/20261012-104809_M10_service/smoke_vcloak.txt and runs/20261012-104809_M10_service/smoke_baseline.txt (vcloak serve --dev on the wall clock, SQLite store, 12 messages encrypted, sent, read and decrypted in order). The PostgreSQL store was exercised through the tests only, not through a live process.
- Defect found and fixed outside the deliverables: PgRepo.rewrite_window (M09) took the partition lock before the parent lock and deadlocked against a reader on a second connection (runs/20261012-104809_M10_service/issue21_before_fix.txt: 25 DeadlockDetected in the reader; runs/20261012-104809_M10_service/issue21_after_fix.txt: passes; runs/20261012-104809_M10_service/pytest_m09_storage_after_lock_fix.txt: 118 passed).
- Not verified: the service on a CUDA device (engine and key store in a worker thread under CuPy); whether an epoch finishes inside EPOCH_MS on any store (nothing was timed; ISSUE-12 still applies at 65536 slots); restart behaviour (ISSUE-22); the passphrase prompt on a real terminal; --clock sim and --store pg as a live process.
- The manifest is dirty: true: the tests ran on the working tree that this session commits. The smoke outputs predate the lock fix, which does not touch the SQLite path they use.

## Audit M10 (fix ISSUE-22) — 2026-10-12 — session 19 — result: PASS
| Item | Result | Evidence |
|---|---|---|
| A1 Epoch boundaries are wall-clock aligned and never extended | PASS | runs/20261012-110434_M10_issue22_restart/pytest_checks_verbose.txt: the a1 test still passes; the cut rule of the scheduler is unchanged |
| A2 Window rewrite happens exactly once per closed window | PASS | runs/20261012-110434_M10_issue22_restart/pytest_checks_verbose.txt: test_a2_each_closed_window_is_rewritten_exactly_once, and now across a restart: test_a_window_left_open_at_shutdown_is_re_shuffled_once_after_the_restart (3 cases, SQLite and PostgreSQL), test_a_new_scheduler_closes_the_windows_an_earlier_one_left_pending, test_a_failed_re_shuffle_keeps_the_mark_and_is_tried_again. Before the fix: runs/20261012-110434_M10_issue22_restart/issue22_before_fix.txt (4 failed, 2 passed) |
| A3 Baseline and V-cloak share the API contract | PASS | runs/20261012-110434_M10_issue22_restart/pytest.txt (343 passed): the two `ack` tests are in class ServiceContract and run in both modes on both stores |
| A4 No forbidden fields in logs | PASS | runs/20261012-110434_M10_issue22_restart/pytest_checks_verbose.txt (a4 test, logsafe tests); the new log fields are `windows` and `error`, both already on the allow-list; runs/20261012-110434_M10_issue22_restart/serve_a.log, runs/20261012-110434_M10_issue22_restart/serve_b.log |
| G1 | PASS | runs/20261012-110434_M10_issue22_restart/pytest.txt (343 passed, 0 skipped, PostgreSQL 16 answered); runs/20261012-110434_M10_issue22_restart/pytest_all.txt (1677 passed, 675 skipped: 674 need a CUDA device, 1 old oracle skip) |
| G2 | PASS | runs/20261012-110434_M10_issue22_restart/check_metrics.txt (263 rows, 0 problems). No metric added: nothing was measured |
| G2b | N/A | no performance or side-channel metric; the backend was numpy |
| G3 | PASS | runs/20261012-110434_M10_issue22_restart/check_oblivious.txt (11 files, 0 findings); no kernel changed. The pending mark depends on the window id only, which is public |
| G4 | PASS | runs/20261012-110434_M10_issue22_restart/check_secrets.txt (0 key-like runs); smoke_restart.py draws its content key at run time and prints none |
| G5 | N/A | no GPU twin |
| G6 | PASS | the M10 deliverables are unchanged in place; docs/API.md updated (restart, ack, errors); runs/20261012-110434_M10_issue22_restart/cli_help.txt |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M10 stays DONE (sessions 2), next_unit M11, gpu_job.pending null |
| G9 | PASS | SESSION_LOG session 19, this entry, ISSUE-22 closed, ISSUE-23 opened, ADR-016 |
| G10 | PASS | runs/20261012-110434_M10_issue22_restart/manifest.json; the module tests were run twice in this session with the same result (343 passed), the restart smoke twice (PASS both times) |
Notes:
- Live process: runs/20261012-110434_M10_issue22_restart/smoke_restart.txt. `vcloak serve --dev --store pg` killed (no shutdown) in the middle of a window after 30 messages answered 201 and 5 answered 202; the store then listed 1 pending window written by 3 transactions; after the restart the list was empty and the window was one transaction in a new file with the same 30 rows, read back and decrypted. The 5 messages answered 202 were lost with the queue, as documented.
- Not verified: the same on a CUDA device; a kill during the swap transaction itself on a live server (covered only by the transaction and by the failed-rewrite tests); `ack: stored` under load (nothing was timed); a store written before this session has no marks.
- ruff: runs/20261012-110434_M10_issue22_restart/ruff.txt clean for src, tests, scripts, bench. The manifest is dirty: true (the tests ran on the tree this session commits).

## Audit M08 (fix ISSUE-17, prep) — 2026-10-12 — session 20 — result: PASS (prep only; nothing measured)
| Item | Result | Evidence |
|---|---|---|
| A1-A5 (M08 checklist) | N/A | the M08 results are unchanged; the diagnostics are measured by job 20261012-113437_M08_issue17 and judged in the ingest session |
| G1 | PASS | runs/20261012-113007_M08_issue17_prep/pytest_all.txt (1709 passed, 1 skipped, 674 deselected: not gpu); runs/20261012-113007_M08_issue17_prep/pytest_issue17.txt (163 passed, 108 skipped for CUDA), run again after the last edit |
| G2 | PASS | runs/20261012-113007_M08_issue17_prep/check_metrics.txt (263 rows, 0 problems). No metric added |
| G2b | N/A | no performance or side-channel metric recorded; the backend was numpy |
| G3 | PASS | runs/20261012-113007_M08_issue17_prep/check_oblivious.txt (11 files, 0 findings); no kernel source changed. `out=` changes where the launcher allocates, not the kernel; r = 8 and the pool size are public constants |
| G4 | PASS | runs/20261012-113007_M08_issue17_prep/check_secrets.txt, and again after the pack (0 key-like runs); the new bundle digest is on the allow-list. The targets use the fixed test keys of the seed |
| G5 | N/A | no new GPU twin; the outputs of every new target are checked against the expected open result (runs/20261012-113007_M08_issue17_prep/plumbing_s8.txt, 0 mismatches) |
| G6 | PASS | bench/jobs/M08_issue17.json, gpujobs/out/20261012-113437_M08_issue17/job.zip and job.json exist |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: status BLOCKED_HUMAN, gpu_job.pending 20261012-113437_M08_issue17, current_module M11 untouched, M08 stays DONE |
| G9 | PASS | SESSION_LOG session 20, this entry, ISSUE-17 updated, ISSUE-24 opened, M08 Amendments |
| G10 | PASS | runs/20261012-113007_M08_issue17_prep/manifest.json; runs/20261012-113337_M08_dudect_issue17_local/manifest.json (the job's seed-8 command on the numpy backend: status NOT_MEASURED, 0 mismatches) |
Notes:
- The three M08 targets stage bit-identical inputs before and after the refactoring of AeadTag / AeadConv (same
  digest of the staged inputs on the tree with and without the change; checked by hand in this session, no file kept).
- A defect found by the new tests before the pack: on a host array `asarray` does not copy, so the valid pool of
  aead_tag_sym was overwritten with the invalid tags (288 mismatches in the first plumbing run). Fixed with a copy.
- Not verified: anything on a CUDA device. `xp.copyto` between device arrays and r = 8 with reused outputs have run
  only on the numpy twin and the fake device. The 4-hour plan is not a measurement.
- runs/20261012-113007_M08_issue17_prep/pytest_all.txt was produced before two lines were re-wrapped for ruff (no logic change); the two files
  touched were tested again afterwards (runs/20261012-113007_M08_issue17_prep/pytest_issue17.txt). ruff: runs/20261012-113007_M08_issue17_prep/ruff.txt clean for src, tests, scripts, bench.
- The manifests are dirty: true (the tests ran on the tree this session commits).

## Audit M08 (fix ISSUE-17, ingest) — 2026-10-12 — session 21 — result: PASS (ISSUE-17 stays open; ISSUE-25 opened)
| Item | Result | Evidence |
|---|---|---|
| A1 | PASS | runs/20261012-150500_M08_issue17_ingest/gates.txt: planted leak detected in this runner session (max abs(t) 401.9489, quick, runs/20261012-061335_M08_dudect_issue17_selftest_quick); control_null PASS at full N in both seeds (1.6126, 1.2530) |
| A2 | N/A | the five S2 verdicts of M08 are unchanged (runs/20261012-031331_M08_dudect). The 28 target runs of this job have verdicts at full N, recomputed from the raw npz (runs/20261012-150500_M08_issue17_ingest/gates.txt, 106 PASS, 0 FAIL) |
| A3, A4 | N/A | SASS and ncu were not part of this job (ISSUE-19, ISSUE-18 unchanged) |
| A5 | PASS | the three FAILs are reproduced and ISSUE-17 stays OPEN, high, BLOCKS M14 (not softened: the FAIL rows stay in the index and the table). The two new device-stage FAILs opened ISSUE-25, high, BLOCKS M14 |
| G1 | PASS | runs/20261012-150500_M08_issue17_ingest/pytest_all.txt (1709 passed, 1 skipped, 674 deselected: not gpu), run again after the allow-list entry. On the runner: gpujobs/out/20261012-113437_M08_issue17/logs/03_pytest_issue17.txt (271 passed) |
| G2 | PASS | runs/20261012-150500_M08_issue17_ingest/check_metrics.txt (329 rows, 0 problems); 66 rows written by gpujob.py ingest from the bundle |
| G2b | PASS | the 66 rows are backend cupy, runner kaggle; the three manifests carry the gpu_job block of this job and its session (runs/20261012-150500_M08_issue17_ingest/gates.txt). Nothing recorded from the numpy backend |
| G3 | PASS | runs/20261012-150500_M08_issue17_ingest/check_oblivious.txt (11 files, 0 findings), and on the runner (logs/02_check_oblivious.txt); no kernel source changed this session |
| G4 | PASS | runs/20261012-150500_M08_issue17_ingest/check_secrets.txt (0 key-like runs) after one allow-list entry: the run directory name 20261012-061335_M08_dudect_issue17_selftest_quick is 49 characters of the base64url alphabet (reason recorded in scripts/secrets_allowlist.json) |
| G5 | N/A | no new GPU twin; 0 output mismatches in every target of both seeds |
| G6 | PASS | the three run dirs, gpujobs/done/results_20261012-113437_M08_issue17.zip, evidence/terminal/M08_issue17_*.txt, 27 evidence/figures/M08_issue17_*.png exist |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: status NOT_STARTED (M11 untouched), gpu_job.pending null, last_ingested this job, M08 stays DONE with 4 sessions |
| G9 | PASS | SESSION_LOG session 21, this entry, ISSUE-17 updated, ISSUE-24 closed, ISSUE-25 opened, M08 Amendments, evidence/INDEX.md |
| G10 | PASS | manifests of the three ingested runs (git sha, seed, command, env) and runs/20261012-150500_M08_issue17_ingest/manifest.json; the gate script run twice gives the same file (runs/20261012-150500_M08_issue17_ingest/g10_gates_rerun.txt). The GPU commands cannot be re-run on this laptop |
Notes:
- The verdict on ISSUE-17 applies the reading rules written in the issue before the job ran. It is a reading, not a proof:
  the staging and the SM clock state change together in this job (failing series at 585 MHz, symmetric staging at 1425 to 1560 MHz).
- Not verified: the cause of the two device-stage FAILs (ISSUE-25); write_epoch_null and write_epoch_age at a second seed;
  anything on another GPU model. results/oblivious and docs/REPORT_CH4_NOTES.md were not regenerated and do not show the diagnostics.
- runs/20261012-150500_M08_issue17_ingest/gates_issue17.py is outside the ruff scope (runs/) and has 11 long lines and one unused loop variable; runs/20261012-150500_M08_issue17_ingest/ruff.txt is
  clean for src, tests, scripts, bench. The first pytest and check_secrets runs of this session failed on the run directory
  name above; the files kept are the runs after the allow-list entry. The manifest of runs/20261012-150500_M08_issue17_ingest is dirty: true.

## Audit M11 (S1-S4, interim) — 2026-10-12 — session 22 — result: PASS (module IN_PROGRESS, S5-S7 not built)
| Item | Result | Evidence |
|---|---|---|
| A1 | N/A | the E5 matrix is S6. What exists: 24 bent requests each refused with the expected first failed check, plus replay, stolen token, forged signature, expired and tampered token, refresh reuse (runs/20261012-153506_M11_session_s1_s4/pytest_security.txt, 88 passed) |
| A2 | PASS | tests/security/test_session.py::test_rfc7638_thumbprint_vector against tests/golden/rfc7638_thumbprint.json (JWK and expected value copied from RFC 7638 section 3.1) (runs/20261012-153506_M11_session_s1_s4/pytest_security.txt) |
| A3 | N/A | the final allow-list and the log test are S7. logsafe.py is unchanged; the one new event (`family_revoked error=refresh_reuse`) uses allowed fields, and test_refresh_rotates_and_a_reused_token_revokes_the_family searches the captured log for the tokens, the conversation token, the password, the name and the jkt |
| A4 | PASS | runs/20261012-153506_M11_session_s1_s4/a4_grep.txt (0 matches for the key names and the gpu/crypto packages in src/vcloak/service/session.py); test_session_module_knows_no_content_or_engine_key |
| G1 | PASS | runs/20261012-153506_M11_session_s1_s4/pytest_all.txt (1797 passed, 1 skipped, 674 deselected: not gpu; the skip is tests/unit/test_oracle_chacha.py:82, no integration skip, PostgreSQL answered) |
| G2 | PASS | runs/20261012-153506_M11_session_s1_s4/check_metrics.txt (329 rows, 0 problems); no metric added, no number written into a doc other than configured limits |
| G2b | N/A | nothing measured; no performance or side-channel metric |
| G3 | PASS | runs/20261012-153506_M11_session_s1_s4/check_oblivious.txt (11 files, 0 findings); no kernel source changed |
| G4 | PASS | runs/20261012-153506_M11_session_s1_s4/check_secrets.txt (0 key-like runs) after one allow-file entry: tests/golden/rfc7638_thumbprint.json holds the public RSA modulus and the thumbprint of the RFC example |
| G5 | N/A | no GPU twin |
| G6 | PASS (partial) | exist: src/vcloak/service/session.py, routes /v1/auth/register, login, refresh, logout (src/vcloak/service/app.py), docs/API.md section "Sessions and DPoP". Not yet due: /v1/auth/ws-ticket, /v1/ws, the final logsafe.py, tests/security/test_session_matrix.py, tests/security/test_logsafe.py, results/session/e5_matrix.json (S5-S7) |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M11 IN_PROGRESS, current_step S5, next_unit M11, sessions 1 |
| G9 | PASS | SESSION_LOG session 22, this entry, ISSUE-26 opened, ADR-017, M11 Amendments |
| G10 | PASS | runs/20261012-153506_M11_session_s1_s4/manifest.json (valid); the session and service tests run a second time give the same outcome (runs/20261012-153506_M11_session_s1_s4/g10_rerun.txt, 269 passed) |
Notes:
- Interim audit: M11 is not DONE and is not tagged. SEC-E5-PASS and SEC-DPOP-VERIFY-US are not recorded (S6).
- The first pytest and check_secrets runs of this session failed on the new golden file (4 key-like runs) and ruff on one
  line of tests/dpop_client.py; the files kept are the runs after the allow-file entry and the fix. The manifest is dirty: true.
- Not verified: the session routes behind `vcloak serve` (not wired), behind a reverse proxy, or under concurrent load;
  timing behaviour of `verify` (every check is evaluated, but no timing test exists); Argon2id at the default cost through
  the API (the tests use t=1, m=64 KiB).
- No evidence capture: web/**, results/** and METRICS_INDEX.md did not change.

## Audit M11 (S5-S7, final) — 2026-10-12 — session 23 — result: PASS (module DONE)
| Item | Result | Evidence |
|---|---|---|
| A1 | PASS | runs/20261012-160139_M11_session_matrix/e5_matrix.json: 26 of 26 scenarios as expected, each refusal names the expected check (stolen token `key_binding`, replay `jti`, ticket reused `ticket_unused`, ticket with another key `ticket_key`, refresh reuse `reuse`, sixth guess `rate_limited`); tests/security/test_session_matrix.py (7 tests) checks the rows, that a mismatch is reported, and that results/session/e5_matrix.json is a full run of the current scenarios |
| A2 | PASS | tests/security/test_session.py::test_rfc7638_thumbprint_vector (runs/20261012-160146_M11_session_s5_s7/pytest_security.txt, 164 passed) |
| A3 | PASS | tests/security/test_log_redaction.py: a session run (messages over two windows, refusals, socket, refresh reuse, logout, login limit) and more than 150 handled values searched in the captured log, none found; the allow-list is pinned. Live: runs/20261012-160146_M11_session_s5_s7/smoke_sessions.txt (the server log of a real `vcloak serve --sessions` searched for 55 handled values, none found, no connection line) |
| A4 | PASS | runs/20261012-160146_M11_session_s5_s7/a4_grep.txt (0 matches for the key names, the keystore and the gpu package in src/vcloak/service/session.py); test_session_module_knows_no_content_or_engine_key |
| G1 | PASS | runs/20261012-160146_M11_session_s5_s7/pytest_all.txt (1880 passed, 1 skipped, 674 deselected: not gpu; the skip is tests/unit/test_oracle_chacha.py:82, no integration skip, PostgreSQL answered) |
| G2 | PASS | runs/20261012-160146_M11_session_s5_s7/check_metrics.txt (331 rows, 0 problems); the two new rows are backed by runs/20261012-160139_M11_session_matrix/summary.json; docs carry configured limits only (30 s, 5 s, 4, 8, 1024), no measured value |
| G2b | PASS | SEC-E5-PASS and SEC-DPOP-VERIFY-US are not GPU metrics: a correctness count and a host CPU time of the session layer (perf_counter, as the module asks), indexed with backend numpy / runner local and described as such. No GPU metric was recorded |
| G3 | PASS | runs/20261012-160146_M11_session_s5_s7/check_oblivious.txt (11 files, 0 findings); no kernel source changed |
| G4 | PASS | runs/20261012-160146_M11_session_s5_s7/check_secrets.txt (989 files, 0 key-like runs), run after the evidence files and the server logs were written |
| G5 | N/A | no GPU twin |
| G6 | PASS | src/vcloak/service/session.py; routes /v1/auth/register, login, refresh, logout, ws-ticket and WS /v1/ws (src/vcloak/service/app.py); src/vcloak/service/logsafe.py (final list); tests/security/test_session_matrix.py; results/session/e5_matrix.json; docs/API.md. `tests/security/test_logsafe.py` exists as tests/security/test_log_redaction.py (basename clash, Amendment) |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M11 DONE, step S7, sessions 2; current_module M12, next_unit M12 |
| G9 | PASS | SESSION_LOG session 23, this entry, ISSUE-27 opened, ADR-018, M11 Amendments |
| G10 | PASS | both manifests valid; the matrix re-run in quick mode gives the same outcome, 26/26 (runs/20261012-160146_M11_session_s5_s7/g10_rerun.txt) |
Notes:
- The matrix runs in-process (Starlette test client), not over a network; the over-the-wire path is the smoke only
  (one client, loopback). The verify time is one laptop CPU, single thread, accepted requests only; p95 is 185.6 us
  against a median of 117.3 us, and the quick re-run gave a median of 126.95 us (n=200): quote it as an order of magnitude.
- A failed first attempt of this session is not kept as evidence: the uvicorn connection lines were found by reading the
  log of a trial smoke before the run dir existed; the filter and its tests came from that.
- Not verified: sockets under load or with many clients; behaviour behind a TLS proxy (`--public-origin` is tested
  in-process only); that refused and accepted verifications take the same time (all checks are evaluated, no timing test);
  the session layer in front of a CUDA engine (the service has never run on one).
- Evidence capture: terminal only (scripts/capture_evidence.py does not exist before M13): TERM-M11-E5-MATRIX,
  TERM-M11-DPOP-VERIFY, TERM-M11-SMOKE-SESSIONS.

## Audit M12 — 2026-10-12 — session 24 — result: PASS
| Item | Result | Evidence |
|---|---|---|
| A1 | PASS | tests/integration/test_two_users.py::test_a1_two_users_exchange_30_messages_across_windows_in_order (SQLite) and ::test_a1_two_users_on_postgresql: both ends read back exactly what was sent, in order, with the senders (runs/20261012-162455_M12_client_sdk/pytest_m12.txt, 65 passed). Live: runs/20261012-162947_M12_demo_two_users (PostgreSQL, 30 messages, 4 windows, 10 of 10 checks) |
| A2 | PASS | tests/integration/test_two_users.py::test_a2_the_server_never_receives_or_stores_plaintext: every request of the conversation (path, headers, body) and every stored row (payload, seq_enc, row_id) searched for each text, its hex and its first 8 bytes, and for K_content: none; every payload is 4124 bytes; the rows open under the clients' key only. runs/20261012-162455_M12_client_sdk/a2_grep_service.txt: 0 references to the content key or its functions in src/vcloak/service |
| A3 | PASS | tests/unit/test_client_sdk.py test_a3_* (12 tests: swapped, reversed, dropped in the middle, dropped first, replayed, forged, foreign, moved to another window, rows disappearing, own tail lost) and tests/integration/test_two_users.py::test_a3_a_tampered_answer_of_the_real_server_is_detected (reordered, missing, forged answers of the real service) |
| G1 | PASS | runs/20261012-162455_M12_client_sdk/pytest_all.txt (1945 passed, 1 skipped, 674 deselected: not gpu; the skip is tests/unit/test_oracle_chacha.py:82, no integration skip: PostgreSQL answered) |
| G2 | PASS | runs/20261012-162455_M12_client_sdk/check_metrics.txt (331 rows, 0 problems). No metric was added: the demo and the tests are correctness checks; the counts in docs (30 messages, 18-byte header, BLOCK - 19, 30 digits) are parameters, not results |
| G2b | PASS | nothing timed, no GPU metric recorded; both manifests say backend numpy, and the demo transcript says so in its first lines |
| G3 | PASS | runs/20261012-162455_M12_client_sdk/check_oblivious.txt (11 files, 0 findings); no kernel source changed |
| G4 | PASS | runs/20261012-162455_M12_client_sdk/check_secrets.txt (1019 files, 0 key-like runs), run after the evidence files and the smoke log were written. Passwords of the demo and the tests are random and stay in the process; the key file tests check that neither private key nor the passphrase is in the file |
| G5 | N/A | no GPU twin |
| G6 | PASS | src/vcloak/client/sdk.py, src/vcloak/client/cli.py (`vcloak-chat` in pyproject.toml), scripts/demo_two_users.py, tests/integration/test_two_users.py; docs/API.md (prekey routes, section "The client") |
| G7 | PASS | checked after the closing commit |
| G8 | PASS | STATE: M12 DONE, step S4, sessions 1; current_module M13, next_unit M13 |
| G9 | PASS | SESSION_LOG session 24, this entry, ISSUE-28 opened, ISSUE-23 updated, ADR-019, M12 Amendments |
| G10 | PASS | both manifests valid; the demo re-run in quick mode on PostgreSQL gives the same outcome, PASS (runs/20261012-162455_M12_client_sdk/g10_rerun.txt), and on SQLite (runs/20261012-162455_M12_client_sdk/demo_sqlite_quick.txt) |
Notes:
- The demo and the live tests run the service inside the client's process (uvicorn on a loopback port, plain HTTP, the
  public development key). `vcloak serve --sessions` as a separate process was run by the two smokes only
  (runs/20261012-162455_M12_client_sdk/smoke_sessions.txt, smoke_open.txt: PASS), with tests/dpop_client.py as the client, not the SDK.
- In the demo each message is alone in its epoch (the sender waits for `stored`), so the order inside an open window is
  the arrival order until the window closes; the dump is taken after every window was re-shuffled. Two senders that
  alternate make the order between them deterministic; with concurrent senders it is the server's and is not verified.
- "The physical order is not the order sent" holds for this run; it is a property of one random permutation per window,
  not a measure of how well the order is hidden (that is M14).
- Found by the tests while writing them: a reader without a strict start silently dropped a message older than the first
  one it saw (it took it for a repeat). It now raises; test_seq_checker_without_a_strict_start_takes_the_first_number_as_given.
- Not verified: the SDK over TLS or behind a proxy; `vcloak-chat` typed by hand in two terminals (its loop is tested
  with scripted input); token expiry against the real server (the refresh-before-expiry path is tested with a fake
  clock and a scripted server); 503/504 retries against the real server (scripted server only); concurrent senders;
  a CUDA engine behind the service.
- Evidence capture: terminal only (scripts/capture_evidence.py does not exist before M13): TERM-M12-DEMO,
  TERM-M12-DEMO-SUMMARY, TERM-M12-PYTEST.
