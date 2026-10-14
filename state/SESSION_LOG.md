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
- Commit: 5cff14d
- Next: M01 S1 ; human action: none

## Session 3 — 2026-10-11 16:55 — M01 Oracle port & golden vectors — owner:Abhishek
- Steps: S1→S5 (status after: DONE)
- Did: src/vcloak/oracle/reference.py — bitonic_stages/schedule/pairs/sort, epoch/reshuffle permutation refs,
  oblivious_compact_ref, write_epoch_ref, reshuffle_ref, read_window_ref, dummy_row_ref (ARCHITECTURE §5 formats).
- Did: oracle/chacha_np.py (NumPy ChaCha20 + Poly1305 + AEAD), oracle/crypto_hooks.py (the one door to server
  crypto), src/vcloak/crypto/{chacha_ref,aead_ref}.py stubs with IMPLEMENTED = False for M02 to fill.
- Did: oracle/attacks.py (order_recovery_attack with turn-order accuracy and f), oracle/stats.py (corrected χ²,
  ideal-sampler calibration, Kendall band), scripts/make_golden.py, tests/golden/oracle_perm_n{64,1024,65536}.json.
- Evidence: runs/20261011-164329_M01_oracle_checks (pytest 148/148 oracle: bitonic 90, chacha 18, paths 22,
  attacks_stats 10, golden 8; full suite 181 local and 181 as runner; golden two generations hash-identical).
- Checks: S1 lexsort n=2..2^12; S2 RFC 8439 §2.3.2 block, §2.5.2 Poly1305, §2.8.2 AEAD + equality with
  `cryptography`; S3 20-conversation round trip with and without re-shuffle; S4 conventional layout τ = 1.0 and
  turn accuracy 1.0; S5 hash compare.
- Metrics added: none (correctness only; numpy backend)
- Decisions: none
- Issues: opened ISSUE-4 (M02 secrets scanner must allow-list tests/golden)
- Deviations from spec: (a) extra files oracle/crypto_hooks.py, tests/testkeys.py (the fixed test key lives under
  tests/ and make_golden imports it from there), .gitattributes (golden JSON stored byte-exact despite autocrlf),
  and `tests` added to pytest pythonpath; (b) the crypto stubs are created now, inside M02's package, as S2 asks;
  (c) the stand-in also implements Poly1305/AEAD in pure Python so seq_enc follows §5 without HKDF/HMAC/AES and
  the oracle imports without `cryptography`; a single block takes an integer path (parity-tested) for speed;
  (d) golden files also hold the re-shuffle permutations and tag hashes, and the 65536 file is 2.1 MB;
  (e) Submission/StoredRow/RefKeys are defined in the oracle until M06 owns them; order_recovery_attack takes
  arrays (wins, truth, conv) instead of the seed's Row list, and is checked against the seed's formulation;
  (f) the seed's traffic simulator and build_database were not ported (they belong to eval/, M14).
- Commit: 6e6f57f
- Next: M02 S1 ; human action: none

## Session 4 — 2026-10-11 17:18 — M02 CPU crypto & key lifecycle — owner:Abhishek
- Steps: S1→S7 (status after: DONE)
- Did: src/vcloak/crypto/chacha_ref.py (NumPy block/keystream vectorised over blocks, derive_subkeys, tags_for_epoch,
  reshuffle_tags, bucket_prf) and aead_ref.py (seal_seq/open_seq through `cryptography` ChaCha20Poly1305).
- Did: crypto/keys.py (96-byte sealed master, Argon2id t=3 m=64 MiB p=4, unseal → bytearray, zeroize, reseal),
  crypto/client.py (X25519 prekeys, HKDF-SHA256 over the transcript, 0x80 padding to BLOCK, AES-256-GCM).
- Did: scripts/check_secrets.py + scripts/secrets_allowlist.json (G4), scripts/vcloak_keys.py (init/rotate via getpass),
  tests/golden/rfc8439_{block,keystream,poly1305,aead}.json, tests/unit/test_crypto_{chacha,aead,keys,client}.py,
  tests/unit/test_check_secrets.py.
- Evidence: runs/20261011-171553_M02_crypto_checks (pytest 72/72 module: chacha 34, aead 11, keys 9, client 13,
  check_secrets 5; full suite 252 passed 2 skipped, local and as runner; check_secrets PASS on the repo).
- Checks: S1 RFC 8439 §2.3.2/§2.4.2 + equality with `cryptography`; S2 tag i = keystream [16i,16i+16), bucket χ²
  p > 0.01; S3 §2.8.2 vector, round trip, all 352 single-bit flips rejected; S4 wrong passphrase → UnsealError, no
  8-byte window of the key in the file; S5 two-party agreement, tamper → ContentError; S6 planted key exit 1, repo
  exit 0; S7 `make_golden.py --check` identical, 147 oracle tests pass.
- Metrics added: none (correctness only; numpy backend)
- Decisions: none
- Issues: closed ISSUE-4; opened ISSUE-5 (each GPU job's bundle_sha256 must be allow-listed for G4)
- Deviations from spec: see the Amendments note in ai/modules/M02_cpu_crypto_keys.md — (a) the seal cipher is
  AES-256-GCM and the params field is 3×LE32 (the spec names neither); (b) `rotate` re-seals the same K_master under
  a new passphrase, it does not replace the key; (c) the scanner's base64 rule needs digit+upper+lower, it accepts a
  hex run that is the SHA-256 of a scanned file, and it allow-lists by file hash as well as by run hash; (d) aead_ref
  imports without `cryptography` (IMPLEMENTED False → oracle stand-in); (e) golden files unchanged, not regenerated;
  (f) chacha_ref is a second, independent NumPy implementation; oracle/chacha_np.py stays as the cross-check.
- Commit: 686954e
- Next: M03 S1 ; human action: none

## Session 5 — 2026-10-11 17:40 — M03 GPU bitonic kernel (prep) — owner:Aditya
- Steps: S1→S5 written and checked locally; S6 packed (status after: BLOCKED_HUMAN, waiting for the GPU job)
- Did: kernels/common.cuh (mask64, lex_gt3, xor_swap64/32, cmp_exchange), kernels/bitonic.cu (bitonic_pairs_global,
  bitonic_shared, bitonic_shared_full), their NumPy twins in src/vcloak/gpu/sim.py.
- Did: src/vcloak/gpu/kernels.py (launch_plan(n, T) as data, run_launch, gpu_bitonic_sort for CuPy or NumPy arrays),
  scripts/check_oblivious.py (G3: data/public/unknown classification, self-test with 10 planted leaks).
- Did: tests/gpu/test_bitonic.py (each test on NumPy and, marked `gpu`, on CuPy), tests/cuda_shim + 
  tests/gpu/test_bitonic_cpu_shim.py (g++ compiles the real bitonic.cu and runs it on the CPU),
  tests/unit/test_check_oblivious.py, bench/bitonic_smoke.py (CUDA-event timing, racecheck), bench/jobs/M03.json.
- Evidence: runs/20261011-173514_M03_bitonic_prep (pytest 192 passed / 84 gpu-skipped; full suite 432 passed /
  86 skipped; check_oblivious clean, planted branch exit 1, self-test 11/11; check_secrets and check_metrics PASS).
- Checks: S1 helpers compile under g++ only (RawModule check is in the job); S2 global kernel alone at 2^10 = oracle
  (twin and CPU stand-in); S3 every launch = the oracle's intermediate state; S4 twins = oracle at 2^6, 2^10, 2^16 x
  seeds 1-3 + 4 adversarial inputs; S5 clean on kernels/, planted `if (hi[i] > hi[l])` flagged; S6 not run.
- GPU job: 20261011-173759_M03 packed from d91bfd6 (1.30 MB, 66 files), full mode, 5 commands.
- Metrics added: none (numpy backend; nothing timed)
- Decisions: none
- Issues: closed ISSUE-5 (pack allow-lists its bundle digest; the allow-list is left out of the bundle and of the
  staleness check); opened ISSUE-6 (HUMAN ACTION: GPU JOB READY, M03)
- Deviations from spec: see the Amendments note in ai/modules/M03_gpu_bitonic_kernel.md — guards on t/npairs and
  base/n; twins take grid= and block=; np.lexsort is the reference at 2^max_log2n; racecheck lives in the bench
  script; a CPU stand-in for nvcc was added; tests/conftest.py skipped all of tests/gpu/ by directory name (fixed).
- Not verified: CUDA compilation, GPU execution, simulator parity on a device, racecheck, any timing.
- Commit: d91bfd6 (code), 32b46ae (job, logs, state)
- Next: M03 ingest (S6, audit A1/A2/G5) ; human action: ISSUE-6 — upload the job, drop the results zip in gpujobs/inbox/

- GPU-JOB 20261011-173759_M03 ingested 2026-10-11 18:10: runner kaggle, gpu Tesla T4, session 20261011-122243, overall exit 0, runs 20261011-122303_M03_bitonic_smoke, 3 metrics indexed.

## Session 6 — 2026-10-11 18:11 — M03 GPU bitonic kernel (ingest) — owner:Aditya
- Steps: S6 (ingest and gates); S1's RawModule check closed by the same job (status after: DONE)
- Did: verified and ingested results_20261011-173759_M03.zip (job id, bundle sha and git sha d91bfd6 match the pack);
  5/5 commands exit 0. No code changed this session.
- Did: applied the S6 gates from the ingested files (gates.txt), re-ran the local checks, captured evidence.
- Evidence: runs/20261011-122303_M03_bitonic_smoke (cupy, Kaggle Tesla T4, session 20261011-122243),
  runs/20261011-181052_M03_ingest_audit (local), gpujobs/out/20261011-173759_M03/{result.json,logs/},
  evidence/gpu/M03_*, evidence/terminal/M03_*.
- Checks: S1 the kernels compile through cupy.RawModule (nvrtc); A1 on the T4 219 passed / 0 failed (GPU = oracle =
  NumPy twin, byte equality, 2^6, 2^10, 2^16 x seeds 1-3 x adversarial inputs) and 7 passed at 2^24; A2 racecheck
  0 hazards at 2^12; S6 smoke at 2^16: 0 mismatches, CUDA events, warm-up 10, 30 runs, CV under the 10% limit,
  no throttle reason. Local: 192 passed / 84 gpu-skipped, full suite 432 / 86; check_oblivious clean, planted
  branch exit 1, self-test 11/11; check_metrics 11 rows PASS; check_secrets PASS.
- Metrics added: K-BITONIC-SMOKE-MS-2^16, K-BITONIC-SMOKE-CV-2^16, K-BITONIC-RACECHECK-HAZARDS (cupy, kaggle;
  indexed by `gpujob.py ingest`). The smoke time is a sanity value, not an M07 result.
- Decisions: none
- Issues: closed ISSUE-6 (job uploaded and ingested); opened ISSUE-7 (telemetry sampler caught 1 sample, taken
  at idle, so the SM-clock gate has no in-run baseline; fix before M07)
- Deviations from spec: none new. The SM clock rose 900 -> 1590 MHz between the idle start snapshot and the end
  snapshot; the gate is a drop of more than 15%, so the run stands as OK, with the caveat in the audit notes.
- Not verified: per-test names on the runner (the logs are -q summaries); race freedom beyond the one racecheck
  size; any performance claim (M07).
- Commit: 121dc0b
- Next: M04 S1 ; human action: none

## Session 7 — 2026-10-11 18:32 — M04 GPU ChaCha20 tags/PRF (prep) — owner:Aditya
- Steps: S1→S4, local half of each (status after: BLOCKED_HUMAN, GPU JOB READY)
- Did: kernels/chacha20.cuh (quarter round, 20-round block), kernels/chacha_tags.cu (chacha_blocks, chacha_tags),
  kernels/prf.cu (derive_subkeys, bucket_prf), mod_public in common.cuh; NumPy twins in gpu/sim.py; wrappers in
  gpu/kernels.py that take keys as device buffers only.
- Did: tests/gpu/test_chacha.py (numpy now, cupy on the runner), tests/cuda_shim/chacha_host.cpp +
  test_chacha_cpu_shim.py (the real .cu files compiled with g++), bench/chacha_smoke.py, bench/jobs/M04.json.
- Evidence: runs/20261011-182840_M04_chacha_prep (pytest 221 passed / 146 gpu-skipped; full suite 653 / 232;
  check_oblivious 0 findings; check_secrets PASS; check_metrics 11 rows PASS).
- Checks: S1 RFC 8439 §2.3.2 block (twin and C source); S2 tags = tags_for_epoch / reshuffle_tags at 64, 2^10, 2^16;
  S3 subkeys and buckets = M02; S4 not run (the bench reports NOT_MEASURED under numpy).
- GPU job: 20261011-183051_M04 packed from 680c28d (1.32 MB, 74 files), full mode, 6 commands.
- Metrics added: none (numpy backend; nothing timed)
- Decisions: none
- Issues: opened ISSUE-8 (HUMAN ACTION: GPU JOB READY, M04); ISSUE-7 updated (fix applied in the new bench only)
- Deviations from spec: see the Amendments note in ai/modules/M04_gpu_chacha_tags.md — nonce split u64 + u32;
  a general chacha_blocks kernel for S1; guards on the thread id; Barrett reduction instead of `%` in bucket_prf;
  n_buckets up to 2^32 - 1 and tag counts in multiples of 4; a CPU stand-in for nvcc.
- Not verified: CUDA compilation, GPU execution, simulator parity on a device, 2^max_log2n, any timing.
- Commit: 680c28d (code), ba4ab4c (job, logs, state)
- Next: M04 ingest (S4 gates, audit A1/A2/G5) ; human action: ISSUE-8 — upload the job, drop the results zip in gpujobs/inbox/

- GPU-JOB 20261011-183051_M04 ingested 2026-10-11 19:13: runner kaggle, gpu Tesla T4, session 20261011-133942, overall exit 0, runs 20261011-134013_M04_chacha_smoke, 3 metrics indexed.

## Session 8 — 2026-10-11 19:35 — M04 GPU ChaCha20 tags/PRF (ingest) — owner:Aditya
- Steps: S4, GPU half of S1-S4 (status after: DONE)
- Did: `gpujob.py verify` and `ingest` on results_20261011-183051_M04.zip (job id, bundle sha and git sha 680c28d
  match); applied the S4 gates and the audit to the ingested files; no source file changed.
- Evidence: runs/20261011-134013_M04_chacha_smoke (cupy, Kaggle Tesla T4, session 20261011-133942),
  runs/20261011-191448_M04_ingest_audit (local, gates.txt), gpujobs/out/20261011-183051_M04/{result.json,logs/},
  evidence/gpu/M04_*, evidence/terminal/M04_*.
- Checks: all 6 runner commands exit 0. A1 RFC 8439 §2.3.2 and §2.4.2 pass on the T4. A2 299 passed / 0 failed /
  0 skipped (tags, subkeys, buckets, blocks = M02; GPU = NumPy twin at 3 sizes x seeds 1-3) and 3 passed at 2^24.
  Bitonic regression 212 passed. S4 smoke at 2^20: 0 mismatches, CUDA events, warm-up 10, 30 runs, CV under the
  10% limit, no throttle reason. Local: 413 passed / 230 gpu-skipped, full suite 653 / 232; check_oblivious clean,
  self-test 11/11; check_metrics 14 rows PASS; check_secrets PASS.
- Metrics added: K-CHACHA-TAGS-SMOKE-GBS-2^20, K-CHACHA-TAGS-SMOKE-MS-2^20, K-CHACHA-TAGS-SMOKE-CV-2^20 (cupy,
  kaggle; indexed by `gpujob.py ingest`). Sanity values, not M07 results.
- Decisions: none
- Issues: closed ISSUE-8 (job uploaded and ingested); ISSUE-7 updated (the snapshot pair works, but the smoke ran
  at a low SM clock because the timed section is only a few ms; M07 must warm up to the working clock)
- Deviations from spec: none new.
- Not verified: the smoke at the GPU's working clock (the SM clock stayed near half of what the M03 job reached);
  branch-free machine code for mod_public and the rotates (M08, SASS); any performance claim (M07).
- Commit: c7a7ac5
- Next: M05 S1 ; human action: none

## Session 9 — 2026-10-11 19:40 — M05 GPU AEAD-open, restore, compaction (prep) — owner:Aditya
- Steps: S1-S4, local half (status after: BLOCKED_HUMAN, GPU JOB READY)
- Did: kernels/poly1305.cuh (26-bit limbs, masked final reduction), aead_seq.cuh (fixed 3-block seq_enc tag),
  aead_open.cu (aead_open_seq), aead_seal.cu (aead_seal_seq), poly1305.cu (general poly1305_mac and aead_tag for
  the RFC vectors); NumPy twins in gpu/sim.py; wrappers gpu_open_and_key, gpu_restore_sort, gpu_compact,
  gpu_seal_seq, gpu_poly1305, gpu_aead_tag, pack/unpack_seq_enc; tests test_aead.py, test_restore.py,
  test_aead_cpu_shim.py (the real .cu files compiled with g++), tests/cuda_shim/aead_host.cpp, bench/jobs/M05.json.
- Evidence: runs/20261011-193238_M05_aead_restore_prep (pytest 404 passed / 363 gpu-skipped; full suite
  1057 / 595; check_oblivious 11 files 0 findings; check_secrets PASS; check_metrics 14 rows PASS; audit_a3.txt).
- Checks: S1 RFC 8439 §2.5.2 (twin and C source); S2 seal/open = aead_ref on valid, tampered and dummy rows,
  RFC §2.8.2 tag; S3 50 windows = read_window_ref; S4 compaction = oblivious_compact_ref and the oracle write order.
- GPU job: 20261011-193547_M05 packed from 69a2cc3 (1.34 MB, 84 files), full mode, 6 commands, tests only.
- Metrics added: none (numpy backend; nothing timed)
- Decisions: none
- Issues: opened ISSUE-9 (HUMAN ACTION: GPU JOB READY, M05)
- Deviations from spec: see the Amendments note in ai/modules/M05_gpu_aead_restore_compact.md — blobs as 11 u32
  words per row; extra files aead_seq.cuh and poly1305.cu; wrapper shapes; three public names added to
  check_oblivious; `cryptography` added to requirements-gpu.txt; no bench.
- Not verified: CUDA compilation, GPU execution, simulator parity on a device, 2^max_log2n, that the runner has or
  can install `cryptography`, any timing.
- Commit: 69a2cc3 (code), 24b10da (job, logs, state)
- Next: M05 ingest (A1, A2, A4, G5) ; human action: ISSUE-9 — upload the job, drop the results zip in gpujobs/inbox/

- GPU-JOB 20261011-193547_M05 ingested 2026-10-11 21:31: runner kaggle, gpu Tesla T4, session 20261011-141833, overall exit 0, runs none, 0 metrics indexed.

## Session 10 — 2026-10-11 21:45 — M05 GPU AEAD-open, restore, compaction (ingest) — owner:Aditya
- Steps: S1-S4, GPU half (status after: DONE)
- Did: verified and ingested results_20261011-193547_M05.zip (job id, bundle sha, git sha 69a2cc3 all match);
  applied gates A1, A2, A4 and G5 to the runner logs; re-ran the local checks; audit; evidence copies.
- Evidence: gpujobs/out/20261011-193547_M05/{result.json,logs/} (cupy, Kaggle Tesla T4, session 20261011-141833),
  runs/20261011-213200_M05_ingest_audit (gates.txt, gates_m05.py, local checks), evidence/gpu/M05_nvidia_smi.txt,
  evidence/terminal/M05_{gpu_tests,gates,audit}.txt.
- Checks: all 6 runner commands exit 0, no failed or skipped test. A1 RFC 8439 §2.5.2 and §2.8.2 pass on the T4.
  A2 213 passed (seal/open = aead_ref incl. tampered and dummy rows, every single-bit flip a miss). A4 497 passed
  (50 windows = read_window_ref, compaction and write order = oracle). G5 GPU = twin at 3 sizes x seeds 1-3 in both
  files, 6 passed at 2^max_log2n. ChaCha/bitonic regression 511 passed. check_oblivious 11 files, 0 findings on the
  runner and locally. Local: 817 passed / 593 gpu-skipped, full suite 1057 / 595; check_metrics 14 rows PASS;
  check_secrets PASS.
- Metrics added: none (the job runs tests only; nothing was timed)
- Decisions: none
- Issues: closed ISSUE-9 (job uploaded and ingested); ISSUE-3 updated (the M05 job ran on a different runner image)
- Deviations from spec: none new. capture-evidence was not required (no change in web/, results/ or METRICS_INDEX);
  terminal and GPU proofs were copied anyway, as for M03 and M04.
- Not verified: any timing of the AEAD, restore or compaction path (M07); branch-free machine code for the tag
  compare, `conv != q_conv` and the Poly1305 select (M08, SASS); behaviour on the older runner image (CUDA 13.0).
- Commit: c2cefaa
- Next: M06 S1 ; human action: none


## Session 11 — 2026-10-11 21:55 — M06 GPU engine (prep) — owner:Aditya
- Steps: S1-S5, local half (status after: BLOCKED_HUMAN, GPU JOB READY)
- Did: src/vcloak/gpu/keystore.py (DeviceKeyStore: H2D from the bytearray, host wipe, subkeys on the device,
  memset zeroize), src/vcloak/gpu/engine.py (GpuEngine: write_epoch, reshuffle_window, read_window, bucket_of,
  one stream, pinned transfers, per-stage event clock, last_timings), dev_keystore() in tests/testkeys.py,
  tests/gpu/test_engine.py, tests/integration/test_engine_vs_oracle.py, bench/run_pipeline.py, bench/jobs/M06.json.
- Evidence: runs/20261011-214849_M06_engine_prep (pytest 82 passed / 68 gpu-skipped; full suite 1139 / 663;
  check_oblivious 11 files 0 findings; check_secrets PASS; check_metrics 14 rows PASS; audit_a3.txt),
  runs/20261011-215050_M06_pipeline_smoke_quick (numpy plumbing run, 0 oracle mismatches, NOT_MEASURED).
- Checks: S1 host bytearray all zero after load, subkeys = chacha_ref.derive_subkeys; S2 write_epoch =
  write_epoch_ref with one shared byte tape; S3 reshuffle = reshuffle_ref, read_window = read_window_ref for 50
  windows; S4 last_timings has all keys and the stages add up to total; S5 the bench runs end to end on the twins.
- GPU job: 20261011-215111_M06 packed from 67504cd (1.37 MB, 91 files), full mode, 7 commands; the smoke bench
  inside it runs with --quick.
- Metrics added: none (numpy backend; nothing timed)
- Decisions: none
- Issues: opened ISSUE-10 (HUMAN ACTION: GPU JOB READY, M06)
- Deviations from spec: see the Amendments note in ai/modules/M06_gpu_engine.md — no new kernel; the device copy of
  K_master is cleared after derivation; one `entropy` hook instead of nonce/uuid hooks; seal and bucket after the
  host gather; extra stage keys `open` and `host`; read_window pads to K; bench is --dev only (no passphrase).
- Not verified: anything on a GPU — the stream, pinned transfers, copy_from_host, memset, CUDA-event timings,
  engine parity with the simulator, SLOTS = 2^max_log2n, every timing.
- Commit: 67504cd (code), 2ecfd59 (job, logs, state)
- Next: M06 ingest (A1, A2, A4, G5, smoke metrics) ; human action: ISSUE-10 — upload the job, drop the results zip
  in gpujobs/inbox/

- GPU-JOB 20261011-215111_M06 ingested 2026-10-11 22:13: runner kaggle, gpu Tesla T4, session 20261011-162938, overall exit 0, runs 20261011-163049_M06_pipeline_smoke_quick, 5 metrics indexed.


## Session 12 — 2026-10-11 22:25 — M06 GPU engine (ingest) — owner:Aditya
- Steps: S5 ingest (status after: DONE)
- Did: verified and ingested GPU job 20261011-215111_M06 (job id, bundle sha and git sha 67504cd match; 7 commands,
  overall exit 0); applied the gates with runs/20261011-221434_M06_ingest_audit/gates_m06.py; re-ran the local
  checks; captured terminal and GPU evidence. No code change.
- Evidence: runs/20261011-163049_M06_pipeline_smoke_quick (T4, cupy, CUDA events, 105 timed calls, 146 telemetry
  rows, status UNSTABLE); runs/20261011-221434_M06_ingest_audit (gates.txt, pytest.txt, pytest_all.txt,
  check_*.txt); gpujobs/out/20261011-215111_M06/logs; evidence/terminal/M06_*.txt, evidence/gpu/M06_*.
- Checks: A1 on the T4: write_epoch, reshuffle_window, read_window (50 windows) and bucket_of = oracle, 111 passed,
  and 0 oracle mismatches in the 5 timed configs. A2 host master buffer zeroized, device buffer cleared by memset
  ([cupy] tests). A4 CUDA-event stages add up to total in all 105 calls. G5 GPU engine = simulator engine at 64,
  1024, 65536 x seeds 1-3, and 3 passed at SLOTS 2^24. Regression M03-M05 1221 passed. check_oblivious 11 files,
  0 findings. Local: 82 passed / 68 gpu-skipped, full suite 1139 / 663; check_metrics 19 rows PASS; check_secrets PASS.
- Metrics added (smoke, quick, cupy, kaggle T4): P-WRITE-EPOCH-MS-S64, -S4096, -S65536; P-READ-WINDOW-MS-K128, -K1024.
- Decisions: none
- Issues: closed ISSUE-10; opened ISSUE-11 (smoke run UNSTABLE: K128 CV 0.119, SM clock 585 MHz throughout) and
  ISSUE-12 (host stage is 96% of write_epoch at SLOTS 65536; median total 208 ms against EPOCH_MS 200); ISSUE-3 updated.
- Deviations from spec: none new (see the Amendments note of session 11). The UNSTABLE K128 median is indexed as
  ingested, because the module asks for smoke values and sets no CV gate; it is flagged in ISSUE-11.
- Not verified: any performance claim. The five values come from 15 runs at a non-ramped SM clock and are not M07
  results. Not profiled: what the host stage spends its time on. Not checked: branch-free machine code (M08).
- Commit: 325a545
- Next: M07 S1 ; human action: none


## Session 13 — 2026-10-11 22:45 — M07 GPU performance metrics (prep) — owner:Aditya
- Steps: S1-S5 prepared locally (status after: BLOCKED_HUMAN, GPU JOB READY); S6 not started
- Did: src/vcloak/bench/timing.py (time_gpu, time_cpu, summarise, warm_until_stable, clock_check), baselines.py
  (oracle network, NumPy views network, numba pairs loop, lexsort), derive.py (rounds, bandwidth, crossover);
  bench/run_kernels.py --part gpu|cpu|crossover; bench/run_pipeline.py --full; telemetry.sample; bench/jobs/M07.json.
- Evidence: runs/20261011-223709_M07_prep_audit (pytest.txt, pytest_not_gpu.txt, ruff.txt, check_*.txt, plumbing_runs.txt,
  audit_a2_grep.txt); plumbing runs 20261011-224043_M07_kernel_sweep, 20261011-224044_M07_cpu_baselines,
  20261011-224044_M07_crossover, 20261011-224045_M07_pipeline (numpy, all NOT_MEASURED).
- Checks: module tests 86 passed / 3 gpu-skipped; local suite 1225 passed, 1 skipped; all timed outputs of the
  plumbing runs equal their references (0 mismatches); check_oblivious 11 files 0 findings; check_metrics 19 rows
  PASS; check_secrets PASS.
- GPU job: 20261011-224124_M07 packed from c40696b (1.40 MB, 104 files), full mode, 9 commands.
- Metrics added: none (numpy backend; nothing timed)
- Decisions: none (no ADR). Implementation choices are in the Amendments note of ai/modules/M07.
- Issues: opened ISSUE-13 (HUMAN ACTION: GPU JOB READY, M07); updated ISSUE-7, ISSUE-11, ISSUE-12
- Deviations from spec: no new kernel; nominal-sleep miss is XFAIL while event-vs-host-clock is the hard check;
  low-clock points are labelled, not UNSTABLE; extra baseline (views) and extra metric IDs; 200 calls for p99.
- Not verified: everything on a GPU — `__nanosleep` under nvrtc, the event timing loop, pinned transfers in
  sort_e2e, numba, the run time of the job (the CPU baselines at 2^21 and 2^22 are the long part), every number.
- Commit: c40696b (code), 4673a5d (job, logs, state)
- Next: M07 ingest (gates, metrics, S6 plots and notes) ; human action: ISSUE-13 — upload the job, drop the
  results zip in gpujobs/inbox/

- Session 13 follow-up 2026-10-12 (human report, same unit, no new step): Kaggle unpacks an uploaded job.zip, so
  Cell 2's KAGGLE_INPUT path did not exist. colab/VCloak_GPU_Runner.ipynb Cell 2 now finds an unpacked bundle or a
  zip under /kaggle/input and verifies the bundle content hash; YOUR_CHECKLIST.md, the gpu-job skill, ISSUE-13 and
  STATE updated. Job 20261011-224124_M07 is unchanged and still pending (the notebook is not in the bundle).
  Not verified on Kaggle.

- GPU-JOB 20261011-224124_M07 ingested 2026-10-12 03:35: runner kaggle, gpu Tesla T4, session 20261011-213139, overall exit 0, runs 20261011-213207_M07_kernel_sweep, 20261011-213731_M07_cpu_baselines, 20261011-215652_M07_crossover, 20261011-215653_M07_pipeline, 213 metrics indexed.

## Session 14 — 2026-10-12 03:50 — M07 GPU performance metrics (ingest) — owner:Aditya
- Steps: S2-S5 ingested and gated, S6 done (status after: DONE)
- Did: ingested job 20261011-224124_M07 (overall exit 0, 9 commands); runs/20261012-033804_M07_ingest_audit/gates_m07.py recomputes the indexed
  values from raw.csv / summary.json / telemetry.csv; src/vcloak/bench/report.py + tests/unit/test_bench_report.py;
  results/perf (7 figures as png + pdf + sidecar json, 4 csv tables, perf_summary.json); docs/REPORT_CH4_NOTES.md
  (generated, 201 tagged values); evidence/gpu, evidence/terminal, evidence/figures (16 index rows).
- Evidence: runs/20261011-213207_M07_kernel_sweep, runs/20261011-213731_M07_cpu_baselines, runs/20261011-215652_M07_crossover, runs/20261011-215653_M07_pipeline (Tesla T4 / Xeon 2.00GHz x4, kaggle session
  20261011-213139); runs/20261012-033804_M07_ingest_audit (gates.txt 39 PASS, pytest.txt 94 passed / 3 gpu-skipped, pytest_all.txt 1233 passed).
- Results: GPU sort with transfers is faster than the best oblivious CPU baseline (numba) at every n from 2^10 to
  2^22; X-SPEEDUP-2^16 34.593, X-SPEEDUP-2^20 21.756. Bitonic global-only at 70.499 to 73.717 % of peak from 2^18.
  Real-time gate: whole write_epoch call FAILS at SLOTS 65536 (p99 279.5451 ms), device part passes (11.0996 ms).
- Metrics added: 213 rows (K-*, CPU-*, X-*, P-*, TEL-*), 65 of them UNSTABLE (see METRICS_INDEX)
- Decisions: none (no ADR)
- Issues: closed ISSUE-7, ISSUE-11, ISSUE-13; updated ISSUE-12 (now BLOCKS M15, high); opened ISSUE-14 (bandwidth
  model above 100% at 2^17) and ISSUE-15 (45 of 78 kernel configurations UNSTABLE; optional re-measurement job)
- Deviations from spec: S6 has seven figures instead of four, and the notes are generated by report.py (Amendments)
- Not verified: the cause of the 2^17 to 2^18 step (ISSUE-14); any number on a second session or a second GPU;
  whether batching launches would stabilise the short kernels; branch-free machine code (M08).
- Commit: 9ae9ba5
- Next: M08 S1 ; human action: none required (optional: decide on the ISSUE-15 re-measurement before M16)

## Session 15 — 2026-10-12 04:12 — M08 GPU obliviousness audit (prep) — owner:Aditya
- Steps: S1-S4 code written, checks pending on the GPU (status after: BLOCKED_HUMAN)
- Did: src/vcloak/bench/dudect.py (online Welch t on the raw data and on the 100 dudect crops, t-curve, plot);
  bench/run_dudect.py (random interleaving of exactly N per class, CUDA events around r launches, calibration batch,
  raw npz + json + png per target; controls control_leak and control_null; targets bitonic_equal, bitonic_sorted,
  write_epoch with device and whole-call series, aead_tag, aead_conv); bench/planted/planted_leak.cu with its twin
  in sim.py; scripts/sass_check.py (nvcc -cubin, cuobjdump -sass, branch table with predicate sources, nvrtc
  listing when available); bench/run_ncu.py + ncu_workload.py + run_ncu.sh/.ps1; bench/jobs/M08.json; 59 new tests;
  tests/fakecupy.py gained a stream; .gitignore (npz), .gitattributes (*.sh stays LF).
- Evidence: runs/20261012-040948_M08_prep_audit (pytest.txt 50 passed, 9 gpu-skipped; pytest_not_gpu.txt 1283 passed, 1 skipped, 674 deselected; check_oblivious, check_secrets,
  check_metrics PASS); local plumbing runs runs/20261012-040958_M08_dudect, runs/20261012-040959_M08_sass,
  runs/20261012-040959_M08_ncu (all NOT_MEASURED).
- GPU job: 20261012-041010_M08 packed from fe51656 (1.45 MB, 121 files), full mode, 8 commands.
- Metrics added: none (numpy backend; nothing timed)
- Decisions: none (no ADR). Implementation choices are in the Amendments note of ai/modules/M08.
- Issues: opened ISSUE-16 (HUMAN ACTION: GPU JOB READY, M08)
- Deviations from spec: planted kernel outside kernels/; extra null control; write_epoch has two series; class B of
  aead_conv comes from a pool sealed before the run; ncu logic in a Python driver behind the two scripts.
- Not verified: everything on a GPU — the planted leak being detected, every verdict, the event loop under CuPy,
  nvcc/cuobjdump on the runner and the format of their output, whether the runner permits the ncu counters, the
  names of its branch metrics, the nvrtc listing path, the run time of the job.
- Commit: fe51656 (code), 901c171 (job, logs, state)
- Next: M08 ingest (gates A1-A5, metrics, evidence, S5 report) ; human action: ISSUE-16 — upload the job, drop the
  results zip in gpujobs/inbox/

- GPU-JOB 20261012-041010_M08 ingested 2026-10-12 09:32: runner kaggle, gpu Tesla T4, session 20261012-031230, overall exit 0, runs 20261012-031245_M08_dudect_selftest_quick, 20261012-031331_M08_dudect, 20261012-040020_M08_sass, 20261012-040027_M08_ncu, 31 metrics indexed.

## Session 16 — 2026-10-12 09:58 — M08 GPU obliviousness audit (ingest) — owner:Aditya
- Steps: S1-S4 checks applied to the ingested job, S5 done (status after: DONE)
- Did: ingested job 20261012-041010_M08 (8 commands, all exit 0); runs/20261012-093714_M08_ingest_audit/gates_m08.py (40 PASS, 0 FAIL, 3 dudect
  findings; max abs(t) recomputed from the raw npz); read the 16 conditional SASS branches in the listings and
  recorded them in bench/sass_explained.json; src/vcloak/bench/report_oblivious.py (S5 table, results/oblivious/,
  notes section 4.O, 8 tests); report.py keeps that section; fixed the index writer of gpujob.py (pipe in a cell).
- Evidence: runs/20261012-031245_M08_dudect_selftest_quick, runs/20261012-031331_M08_dudect, runs/20261012-040020_M08_sass, runs/20261012-040027_M08_ncu (Tesla T4, kaggle session 20261012-031230);
  runs/20261012-093714_M08_ingest_audit (gates.txt, report.txt, pytest.txt 80 passed / 9 gpu-skipped, pytest_all.txt 1292 passed);
  results/oblivious (29 files); evidence/gpu, evidence/figures, evidence/terminal (11 index rows).
- Results: planted leak detected (376.9125, quick); null control 2.0786; bitonic_equal 1.2708 PASS, bitonic_sorted
  2.6965 PASS, write_epoch device 2.7559 PASS; FAIL: aead_conv 11.6369, write_epoch whole call 8.2776, aead_tag
  6.2415 (100000 per class). SASS: 16 of 16 conditional branches public, no divergence control. ncu: NOT_MEASURED.
- Metrics added: 31 rows (T-DUDECT-*, T-SASS-BRA-*, T-NCU-* of which 8 NOT_MEASURED)
- Decisions: none (no ADR). Whether whole-call host timing is in the threat model is left open in ISSUE-17.
- Issues: closed ISSUE-16; opened ISSUE-17 (dudect FAILs, high, BLOCKS M14), ISSUE-18 (ncu counters denied,
  optional human action), ISSUE-19 (SASS checker over-reports; no nvrtc listing)
- Deviations from spec: the S4 issue is optional, not a gate (Kaggle cannot change the setting); dudect figures are
  the runner's PNGs only (Amendments).
- Not verified: the cause of the three FAILs (nothing in ISSUE-17 has been tested); any result on a second session,
  seed or GPU; the machine code CuPy actually runs (nvrtc); divergence counters; the ncu parser on real output.
- Commit: 7c31c24
- Next: M09 S1 ; human action: none required (optional: ISSUE-18; `fix ISSUE-17` is needed before M14)

## Session 17 — 2026-10-12 10:25 — M09 Storage (PostgreSQL) — owner:Divyansh
- Steps: S1-S5 (status after: DONE)
- Did: scripts/pgdev.py (private cluster from the installed PostgreSQL binaries; show / doc commands) and
  storage/pgconf.py (endpoint, 14 WAL and logging settings); storage/schema.sql (messages partitioned by win, primary
  key (row_id, win), index (bucket, win)); storage/repo.py (PgRepo, SqliteRepo: COPY per epoch, exactly-K candidates
  with random dummies in random order, dump by ctid, rewrite_window as load + one-transaction partition swap);
  storage/reshuffle.py; docker-compose.yml (postgres:16, same settings); storage section of docs/ENV.md, kept by
  record_env.py; tests/repo_contract.py run by tests/unit/test_repo_sqlite.py and tests/integration/test_repo_pg.py.
- Evidence: runs/20261012-101327_M09_storage (pytest.txt 118 passed; pytest_pg_contract.txt and pytest_sqlite_contract.txt 42 passed each;
  pytest_all.txt 1410 passed, 1 skipped; show.txt 14 of 14 settings; s1_select1.txt; check_* PASS; ruff clean)
- Metrics added: none (nothing measured; no performance number exists for the store)
- Decisions: ADR-014 (primary key (row_id, win); Repo.window_rows; CandidateOverflow; RewriteMismatch; pgdev cluster)
- Issues: opened ISSUE-20 (PostgreSQL 17rc1 instead of 16, compose file never started; low, optional human action)
- Deviations from spec: native 17rc1 cluster instead of Docker postgres:16; composite primary key; extra settings
  and files (Amendments of ai/modules/M09)
- Not verified: docker-compose.yml on a Docker engine; anything on PostgreSQL 16; the swap under concurrent
  connections; how long WAL of a closed window survives; behaviour at bench sizes (the largest test window is 700 rows)
- Commit: db7b746
- Next: M10 S1 ; human action: none required (optional: ISSUE-20). `fix ISSUE-17` is still needed before M14

## Session 17 (addendum) — 2026-10-12 10:35 — M09 Storage on postgres:16 (ISSUE-20) — owner:Divyansh
- Steps: none new (M09 stays DONE); the human installed Docker Desktop and the compose service was verified
- Did: `docker compose up -d --wait db` (postgres:16, server 16.15); the storage tests and the SHOW checks re-run on
  it without a code change; docs/ENV.md storage section regenerated from the new SHOW output.
- Evidence: runs/20261012-103011_M09_storage_pg16_docker (pytest.txt 118 passed; pytest_pg_contract.txt 42 passed; show.txt 14 of 14; compose_ps.txt)
- Metrics added: none
- Decisions: none
- Issues: closed ISSUE-20; opened ISSUE-21 (concurrent swap untested, WAL lifetime not measured; low)
- Deviations from spec: none left for S1 (Docker postgres:16 is now the development database)
- Not verified: the points of ISSUE-21
- Commit: 28c3080
- Next: M10 S1 ; human action: none. Keep Docker Desktop running when you type continue

## Session 18 — 2026-10-12 10:58 — M10 Service & scheduler — owner:Divyansh
- Steps: S1-S5 (status after: DONE)
- Did: src/vcloak/service: models.py (bodies, exact payload size, token to conv id), logsafe.py (allow-list logger,
  one-second timestamps), scheduler.py (WallClock, SimClock, EpochScheduler: aligned epochs, carry-over with public
  overflow and missed counters, one re-shuffle per closed window, --visible-round), app.py (four routes, VcloakBackend
  with the read handler and the key lifecycle), baseline.py (schema baseline, BIGSERIAL + timestamptz, same API);
  src/vcloak/cli.py (vcloak serve) and the console script; docs/API.md; scripts/smoke_service.py.
- Also: PgRepo.rewrite_window now locks the parent table before the partition (deadlock against a second reader).
- Evidence: runs/20261012-104809_M10_service (pytest.txt 190 passed, 61 of them on postgres:16; pytest_all.txt 1600 passed, 675 skipped
  for CUDA; smoke_vcloak.txt and smoke_baseline.txt PASS; issue21_before_fix.txt / issue21_after_fix.txt; check_* PASS; ruff clean)
- Metrics added: none (nothing measured; the backend was numpy)
- Decisions: ADR-015 (conv id and seq assigned by the server, epoch cut rule, queue bound, shutdown, epoch rounds)
- Issues: opened ISSUE-22 (restart leaves windows un-shuffled; 202 before durability); ISSUE-21 point 1 tested and fixed, stays open for WAL lifetime
- Deviations from spec: server-derived conv_id and seq; 202 answer; missed counter; baseline inserts at once;
  logsafe test under tests/unit; extra files and CLI options (Amendments of ai/modules/M10)
- Not verified: the service on a CUDA device; whether an epoch fits EPOCH_MS (nothing timed); restart and crash
  behaviour (ISSUE-22); the passphrase prompt on a terminal; --clock sim and --store pg as a live process
- Commit: 3e7b118
- Next: M11 S1 ; human action: none. Keep Docker Desktop running when you type continue

## Session 19 — 2026-10-12 11:20 — fix ISSUE-22 (M10 Service & scheduler) — owner:Divyansh
- Steps: none new (M10 stays DONE); the restart and durability defects of ISSUE-22
- Did: storage: table `pending_windows`, `Repo.mark_pending` / `pending_windows`, the mark removed in the swap
  transaction of `rewrite_window` (PgRepo and SqliteRepo). Scheduler: marks a window before its first rows, starts
  from the marks of the store, answers waiting submissions after the epoch is committed. Backend and API: the marks
  are read at startup; `ack: "stored"` (201), 503 `not_stored`, 504 `ack_timeout`. CLI: loopback guard,
  `--allow-remote`, `--schema`. scripts/smoke_restart.py; docs/API.md.
- Evidence: runs/20261012-110434_M10_issue22_restart (issue22_before_fix.txt 4 failed / 2 passed; issue22_after_fix.txt 6 passed; pytest.txt 343 passed;
  pytest_all.txt 1677 passed, 675 skipped for CUDA; smoke_restart.txt PASS on postgres:16; smoke_vcloak.txt,
  smoke_baseline.txt PASS; check_* PASS; ruff clean)
- Metrics added: none (nothing measured; the backend was numpy)
- Decisions: ADR-016 (pending-window list; acknowledgement of the write instead of a durable queue; loopback guard)
- Issues: closed ISSUE-22; opened ISSUE-23 (M12 must use ack stored and drop repeats, M15 must name the ack; low)
- Deviations from spec: one more table in the schema; one more request field and two more error answers
  (Amendments of ai/modules/M10)
- Not verified: anything on a CUDA device; a kill inside the swap transaction on a live server; ack stored under load
- Commit: 75a8bb5
- Next: M11 S1 ; human action: none. Keep Docker Desktop running when you type continue

## Session 20 — 2026-10-12 11:40 — fix ISSUE-17, prep (M08 GPU obliviousness audit) — owner:Aditya
- Steps: none new (M08 stays DONE); the prep half of `fix ISSUE-17` (status after: BLOCKED_HUMAN, GPU job)
- Did: bench/run_dudect.py: 11 diagnostic targets for the three failing series. AEAD conv and tag: `_null` (the
  staging of the original, the same contents in both classes), `_swap` (roles exchanged), `_sym` (pools of the same
  size on the device, device-to-device copy), `_kernel` (`_sym`, preallocated outputs, r = 8). write_epoch: `_null`
  (build order), `_age` (long-lived vs new objects), `_fresh` (fixed vs random, one batch built). Groups `issue17`
  and `issue17_rep`. src/vcloak/gpu/kernels.py: `gpu_open_and_key(..., out=)`. bench/jobs/M08_issue17.json (seed 8,
  then seed 9, a full-N null control in each). 14 new tests in tests/unit/test_run_dudect.py.
- Evidence: runs/20261012-113007_M08_issue17_prep (pytest_all.txt 1709 passed; pytest_issue17.txt 163 passed, 108 skipped for
  CUDA; plumbing_s8.txt; check_* PASS; ruff clean); runs/20261012-113337_M08_dudect_issue17_local (numpy, NOT_MEASURED)
- Metrics added: none (nothing measured; the backend was numpy)
- Decisions: none. The ADR on whole-call host timing (ISSUE-17 step 5) is still open for the team
- Issues: ISSUE-17 updated (prep done, how to read the result); opened ISSUE-24 (GPU JOB READY, 20261012-113437_M08_issue17)
- Deviations from spec: targets outside M08 S2 and a new optional argument of gpu_open_and_key (Amendments of ai/modules/M08)
- Not verified: anything on a CUDA device; the runtime of the job; whether the originals FAIL again
- GPU job: 20261012-113437_M08_issue17 packed from 3671fac (bundle c8b5e6ab81d2...), pending
- Commit: 0dff9e0 (code and job: 3671fac)
- Next: ingest 20261012-113437_M08_issue17 (then M11 S1) ; human action: ISSUE-24, run the job on Kaggle and put the results zip in gpujobs/inbox

- GPU-JOB 20261012-113437_M08_issue17 ingested 2026-10-12 15:04: runner kaggle, gpu Tesla T4, session 20261012-061138, overall exit 0, runs 20261012-061335_M08_dudect_issue17_selftest_quick, 20261012-061420_M08_dudect_issue17_s8, 20261012-080629_M08_dudect_issue17_s9, 66 metrics indexed.

## Session 21 — 2026-10-12 15:05 — fix ISSUE-17, ingest (M08 GPU obliviousness audit) — owner:Aditya
- Steps: none new (M08 stays DONE); the ingest half of `fix ISSUE-17` (status after: NOT_STARTED for M11, no job pending)
- Did: ingested job 20261012-113437_M08_issue17 (7 commands exit 0, shas match). runs/20261012-150500_M08_issue17_ingest/gates_issue17.py
  recomputes every verdict from the raw npz and applies the reading rules of ISSUE-17; device_series_detail.txt counts
  the tests above the threshold. No file under src/, kernels/, bench/, tests/ or results/ changed.
- Result: the three M08 FAILs are reproduced in both seeds. aead_conv and aead_tag: same-contents controls FAIL,
  swapped roles keep the sign of t, symmetric staging and kernel-only window PASS (harness staging, H1/H2). write_epoch
  whole call: same-contents controls FAIL, write_epoch_fresh PASSES (H4). New: write_epoch_age and write_epoch_fresh
  FAIL in the device-stage series at seed 8 (6.3027, 6.1653); the second PASSES at seed 9.
- Evidence: runs/20261012-061335_M08_dudect_issue17_selftest_quick, runs/20261012-061420_M08_dudect_issue17_s8,
  runs/20261012-080629_M08_dudect_issue17_s9 (cupy, Tesla T4); runs/20261012-150500_M08_issue17_ingest (gates.txt 106 PASS / 0 FAIL;
  pytest_all.txt 1709 passed; check_* PASS); evidence/terminal/M08_issue17_*, evidence/figures/M08_issue17_*
- Metrics added: 66 rows, T-DUDECT-MAXT-* and T-DUDECT-N-* for the 14 targets and the controls (seed 8, seed 9, self-test).
  The ids of the S2 targets now have one row per run; the run dir tells them apart
- Decisions: none. The ADR on whole-call host timing is still open for the team (needed before M14)
- Issues: closed ISSUE-24; ISSUE-17 updated with the result, stays OPEN; opened ISSUE-25 (device-stage FAILs, high, BLOCKS M14)
- Deviations from spec: none new (Amendments of ai/modules/M08 record the result)
- Not verified: the cause of ISSUE-25; staging and clock state are not separated; one GPU model
- Commit: 1569d66
- Next: M11 S1 ; human action: none now (team decision on whole-call host timing before M14, see ISSUE-17). Keep Docker Desktop running when you type continue

## Session 22 — 2026-10-12 15:50 — M11 Session security (E5) — owner:Divyansh
- Steps: S1→S4 (status after: IN_PROGRESS, current_step S5)
- Did: src/vcloak/service/session.py (new): accounts with Argon2id and three rate limits (S1); JWS HS256 access token
  with `cnf.jkt` and `fam`, opaque single-use refresh tokens in families, RFC 7638 thumbprint (S2); `verify` with 16
  named checks, all evaluated before the decision, ES256 always computed (S3); rotation, reuse detection, family
  revocation with a listener hook (S4). app.py: `create_app(..., sessions=)`, the DPoP dependency on /v1/messages and
  /v1/read, routes /v1/auth/register, login, refresh, logout. models.py: the four bodies. docs/API.md: section
  "Sessions and DPoP". tests/dpop_client.py, tests/security/test_session.py (79), test_session_api.py (9).
- Evidence: runs/20261012-153506_M11_session_s1_s4 (pytest_all.txt 1797 passed; pytest_security.txt 88 passed; ruff clean;
  check_secrets, check_metrics, check_oblivious PASS; a4_grep.txt empty)
- Metrics added: none (nothing measured)
- Decisions: ADR-017 (token format, in-memory state, limits, no conversation binding)
- Issues: opened ISSUE-26 (in-memory accounts and sessions, medium); closed none
- Deviations from spec: `fam` claim and `token_revoked` check added; a dependency instead of a middleware; no server
  nonce; docs/API.md no longer says M11 binds conv_token to the session (Amendments of ai/modules/M11, ADR-017)
- Not verified: the routes behind `vcloak serve` (not wired yet); timing of `verify`; the default Argon2id cost over HTTP
- Commit: eff55f1
- Next: M11 S5 (WS tickets, /v1/ws, CLI switch), then S6, S7 ; human action: none. Keep Docker Desktop running when you type continue

## Session 23 — 2026-10-12 16:10 — M11 Session security (E5) — owner:Divyansh
- Steps: S5→S7 (status after: DONE; next module M12 NOT_STARTED)
- Did: S5 session.py: one-time WebSocket tickets (30 s, bound to the key and the login), `open_socket` with 9 proof
  and 6 ticket checks, all evaluated. app.py: POST /v1/auth/ws-ticket, WS /v1/ws (ticket and proof in the first frame,
  one identical `tick` frame per epoch boundary for every socket), SocketHub; logout, refresh reuse and expiry close
  the sockets. scheduler.py / baseline.py: `on_epoch`. cli.py: `--sessions`, `--public-origin`; the loopback rule holds
  only without sessions. S6 bench/run_session_matrix.py: 26 scenarios and the verify timing. S7 logsafe.py: final
  allow-list (+`sessions`), `ConnectionLineFilter` for uvicorn's per-connection lines; scripts/smoke_service.py
  `--sessions` with a search of the server log. docs/API.md; tests: test_session_ws.py (32), test_session_matrix.py (7),
  test_log_redaction.py (37).
- Evidence: runs/20261012-160139_M11_session_matrix (e5_matrix.json, verify_timing.json, summary.json); runs/20261012-160146_M11_session_s5_s7 (pytest_all.txt 1880 passed;
  pytest_security.txt 164 passed; ruff clean; check_* PASS; four smokes PASS; a4_grep.txt empty; g10_rerun.txt);
  results/session/e5_matrix.json; evidence/terminal/M11_*
- Metrics added: SEC-E5-PASS 26/26; SEC-DPOP-VERIFY-US 117.3 us (median of 2000, laptop CPU, perf_counter)
- Decisions: ADR-018 (in-band ticket with a proof, one push for everybody, cadence from the scheduler, CLI switch)
- Issues: opened ISSUE-27 (sockets: no bound before the ticket, never under load, TLS proxy untested; low); closed none
- Deviations from spec: ticket in the first frame, not in the handshake; `tests/security/test_logsafe.py` is
  `test_log_redaction.py`; 26 scenarios instead of 15; `--sessions` is off by default (Amendments of ai/modules/M11)
- Found on the way: uvicorn logged every WebSocket with its peer address although the access log was off; fixed (S7)
- Not verified: sockets under load; behind a TLS proxy; equal time of refused and accepted verifications; a CUDA engine
  behind the session layer
- Commit: 3b755c6
- Next: M12 S1 ; human action: none. Keep Docker Desktop running when you type continue

## Session 24 — 2026-10-12 16:36 — M12 Client SDK & CLI — owner:Abhishek
- Steps: S1→S4 (status after: DONE; next module M13 NOT_STARTED)
- Did: src/vcloak/client/ (new): device.py (ES256 device key, DPoP proofs, key file sealed with Argon2id + AES-GCM),
  sdk.py (`VcloakClient`: register, login, refresh, dpop_headers, publish_prekey, start_conversation, send, read, sync,
  ticks; `Conversation`, `SeqChecker`), cli.py (`vcloak-chat`). crypto/client.py: `derive_conv_token`. Service:
  `PUT /v1/prekeys`, open `GET /v1/prekeys/{username}` (session.py, models.py, app.py). scripts/demo_two_users.py
  (in-process service, two SDK clients, transcript, stored rows in physical order). docs/API.md: prekey routes and
  "The client". Tests: tests/unit/test_client_sdk.py (42), tests/security/test_prekeys.py (13),
  tests/integration/test_two_users.py (10).
- Evidence: runs/20261012-162947_M12_demo_two_users (transcript.txt, rows.txt, summary.json: PostgreSQL, 30 messages, 4 windows, 10/10 checks);
  runs/20261012-162455_M12_client_sdk (pytest_all.txt 1945 passed; pytest_m12.txt 65 passed; ruff clean; check_* PASS; two smokes PASS;
  g10_rerun.txt); evidence/terminal/M12_*
- Metrics added: none (nothing measured: correctness only, numpy engine)
- Decisions: ADR-019 (open prekey fetch, token from K_content, header with sender/session/number, retry rule)
- Issues: opened ISSUE-28 (static prekeys, limits of the order check; medium); ISSUE-23 point 1 done (stays open for M15)
- Deviations from spec: header is version/sender/session/number; `sync()` is the verifying reader, `read(win)` one
  window; the demo runs the service in-process; the key file also holds the prekey (Amendments of ai/modules/M12)
- Found on the way: the lenient reader dropped a message older than its start as a repeat; it now raises
- Not verified: SDK over TLS; token expiry and 503/504 against the real service; `vcloak-chat` by hand; concurrent
  senders; a CUDA engine behind the service
- Commit: 0d05cf0
- Next: M13 S1 ; human action: none. Keep Docker Desktop running when you type continue

## Session 25 — 2026-10-12 17:00 — M13 Frontend: chat + server view — owner:Abhishek
- Steps: S1→S3 (status after: IN_PROGRESS; checkpoint S4)
- Did: S1 src/vcloak/service/web.py (new): `web/` mounted at `/app`, an ASGI middleware that puts the CSP, nosniff and
  `no-store` (dev) on every answer under /app, `GET /v1/stats/live` in a first form; `create_app(dev=, web_dir=)`,
  `vcloak serve` passes `--dev`. S2 web/js/crypto.js (new: non-extractable ES256 device key and X25519 prekey as
  CryptoKey handles in IndexedDB, DPoP proofs, HKDF, AES-256-GCM) and web/js/client.js (new: register, login, refresh
  rotation, authenticated requests, one queue per client). S3 the conversation in client.js (seal, send with
  `ack: stored` and retries, verified sync) and web/js/chat.js: two live panes, pending bubbles, fingerprint line, a
  pane alert on a gap or a tampered payload; the demo path of the prototype kept for file://. web/js/api.js: `raw`,
  no demo rows on a live server. scripts/headless.py (new): the installed Chrome/Edge over the DevTools protocol.
  tests/integration/test_web_app.py (16). docs/API.md (`/app`, `/v1/stats/live`, the page as a client); docs/DEMO.md (new).
- Evidence: runs/20261012-165025_M13_web_chat_s1_s3 (pytest_all.txt 1961 passed; pytest_m13.txt 16 passed in Chrome 154; page_checks.json;
  chat_live_light.png, chat_live_dark.png, chat_file_demo.png; ruff clean; check_* PASS; serve_cli.txt; a5_grep.txt empty;
  g10_rerun.txt); evidence/terminal/M13_*
- Metrics added: none (nothing measured: correctness only, numpy engine)
- Decisions: ADR-020 (the SDK's protocol in WebCrypto with X25519, key handles in IndexedDB, page-made demo accounts,
  no strict start, reads on a fixed 1 s schedule, the CSP)
- Issues: opened ISSUE-29 (CSP allows style attributes; limits of the browser client; low); closed none
- Deviations from spec: X25519 instead of "ECDH P-256"; client.js beside crypto.js; `/v1/stats/live` started in S1;
  Chrome over DevTools instead of Playwright; reads on a timer, not on the socket ticks (Amendments of ai/modules/M13)
- Found on the way: Starlette answers `/app` (the redirect) and a 404 outside the mounted files, so headers set on the
  file responses missed them: moved to a middleware. Without a strict start a reader cannot see a gap before the first
  message it saw of a session; the gap test now lets B see one message first.
- Not verified: S4-S6 and S5b (not started); audit items A3 and A6; the page in Firefox or Safari; the CSP against an
  injected script; token expiry and 503/504 in the browser; the page behind TLS; a CUDA engine behind the service
- Commit: 3126fea
- Next: M13 S4 ; human action: none. Keep Docker Desktop running when you type continue

## Session 26 — 2026-10-12 17:27 — M13 Frontend: chat + server view — owner:Abhishek
- Steps: S4→S4 (status after: IN_PROGRESS; checkpoint S5)
- Did: src/vcloak/service/web.py: `GET /v1/dump?limit=&windows=` (403 `dev_only` without --dev), the rows of the newest
  windows in physical order with the state of each window; `stored()` on VcloakBackend (app.py) and BaselineBackend.
  web/js/chat.js: the panel on the live dump (truncated hex fields, window state, note on what still leaks), "Reveal
  true order" worked out in the page from the ciphertexts the panes read and verified (client.js keeps them), refresh
  on the panes' one-second schedule, no request at all without dev; api.js, app.css. tests/integration/test_web_app.py
  (+5: 21); tests/service_contract.py (404 → 403); scripts/demo_two_users.py (`LocalServer(dev=)`); docs/API.md,
  docs/DEMO.md ("What the server stores").
- Evidence: runs/20261012-170743_M13_web_server_view_s4 (pytest_all.txt 1966 passed, 675 skipped; pytest_m13.txt 21 passed in Chrome;
  page_checks.json; file_demo_check.json; server_view_reveal_light.png, server_view_reveal_dark.png, server_view_light.png; ruff clean;
  check_* PASS; a5_grep.txt empty; g10_rerun.txt); evidence/terminal/M13_S4_*
- Metrics added: none (nothing measured: correctness only, numpy engine)
- Decisions: ADR-021 (dump without a key, true order computed by the page, the panel spans closed windows)
- Issues: opened ISSUE-30 (dump open in dev, baseline dump lacks ts/conv, untested panel states; low); closed none
- Deviations from spec: the panel shows the newest windows, not only the current one, and the S4 check is made on
  closed windows; the overlay is client-side; the M10 contract test changed from 404 to 403 (Amendments of
  ai/modules/M13)
- Found on the way: the open window lies in epoch order until it closes, so a panel of the current window alone would
  have shown the order of sending and the check would have passed only by luck of two messages sharing an epoch.
- Not verified: S5, S5b, S6 (not started); audit item A6; the panel with --visible-round epoch, in the `closing` state, with more than
  200 rows or on PostgreSQL; the page in Firefox or Safari; a CUDA engine behind the service
- Commit: 535e109
- Next: M13 S5 ; human action: none. Keep Docker Desktop running when you type continue

## Session 27 — 2026-10-12 18:40 — M13 Frontend: chat + server view — owner:Abhishek
- Steps: S5→S5 (status after: IN_PROGRESS; checkpoint S5b)
- Did: src/vcloak/service/switch.py (new): `SwitchBackend`, V-cloak and the baseline on one clock, every message
  written to both, the active one answers. cli.py: `serve --compare` (needs --dev, window rounds); `--dev` refused on a
  non-loopback host. web.py: `GET/POST /v1/mode` (403 without --dev, 409 without --compare), `switchable` in
  `/v1/stats/live`, `ts` and `conv_hex` in `/v1/dump`. baseline.py: `dump_clear()`. web/: the switch is live
  (chat.js `setMode`: both panes held, mode changed, windows read again via client.js `reread`), the panel shows
  ts/conv in baseline mode and a caption on what each layout leaks; api.js no longer pretends a refused switch worked.
  tests: test_web_app.py (+4: 25), test_service_sqlite.py (+7), test_session_ws.py (1 changed). docs/API.md,
  docs/DEMO.md ("The same conversation both ways").
- Evidence: runs/20261012-175413_M13_web_mode_switch_s5 (pytest_all.txt 1977 passed, 675 skipped; pytest_m13.txt 165 passed, 25 of them
  the web app in Chrome; page_checks.json 13 checks; file_demo_check.json; server_view_{vcloak,baseline}_reveal_{light,dark}.png;
  ruff clean; check_* PASS; a5_grep.txt empty; g10_rerun.txt); evidence/terminal/M13_S5_*
- Metrics added: none (nothing measured: correctness only, numpy engine)
- Decisions: ADR-022 (comparison backend behind --compare, mirrored writes, dev refused off loopback)
- Issues: opened ISSUE-31 (intermittent browser test; limits of the switch; medium); ISSUE-30 points 1-2 done, stays open
- Deviations from spec: `/v1/mode` works only with `--dev --compare`, not with `--dev` alone; two existing tests that
  started `--dev` on 0.0.0.0 were changed (Amendments of ai/modules/M13)
- Found on the way: the two stores can file one message under neighbouring windows, and the client counts payloads
  per window, so a pane stopped with an order error after a switch until the page re-read its windows. `open_app` in
  the tests raced the page's start-up (fixed). test_a_withheld_message_is_flagged_in_the_pane fails now and then, also
  on the last commit (ISSUE-31). The footer of a live page still reads "data: seed" (ISSUE-31 point 4).
- Not verified: S5b, S6 (not started); audit item A6; the switch on PostgreSQL, with a second client connected, or
  with a full queue on a real server; the page in Firefox or Safari; a CUDA engine behind the service
- Commit: 5348044
- Next: M13 S5b ; human action: none. Keep Docker Desktop running when you type continue

## Session 28 — 2026-10-12 19:20 — M13 Frontend: chat + server view — owner:Abhishek
- Steps: S5b→S5b (status after: IN_PROGRESS; checkpoint S6)
- Did: scripts/capture_evidence.py (new): `--module <Mxx>` starts its own `serve --dev --compare`, has the two panes
  hold an 8-message conversation and photographs the page in headless Chrome at 1440x900, full page, both themes: the
  chat with the panel and the revealed order in V-cloak and in baseline mode, then dashboard, experiments, logs and
  architecture (12 PNGs in evidence/screens/, 12 rows in evidence/INDEX.md with run dir, commit and data state read
  from the page). Rows are replaced by ID; nothing is written unless every check passed; `--terminal` copies run
  output to evidence/terminal/. tests/unit/test_capture_evidence.py (8). docs/DEMO.md ("Taking the pictures").
  ISSUE-31 point 1: the intermittent browser test traced to its own hook and changed (test_web_app.py).
- Evidence: runs/20261012-181114_M13_evidence_capture_s5b (capture_run1.txt, capture_run2.txt, capture_evidence.json, overwrite_check.txt;
  pytest_all.txt 1985 passed, 675 skipped; pytest_m13.txt 33 passed, 25 of them the web app in Chrome; flake/,
  flake_fixed/, withheld_repro.json, withheld_summary.txt; file_demo_check.json; ruff clean; check_* PASS;
  a5_grep.txt empty); evidence/screens/M13_*_20261012.png; evidence/terminal/M13_S5b_*
- Metrics added: none (nothing measured: pictures and correctness only, numpy engine)
- Decisions: none (no ADR; the choices of the script are in the Amendments of ai/modules/M13)
- Issues: opened ISSUE-32 (what the pictures do not show, what the script does not do; low); ISSUE-31 point 1 traced
  and the test changed, the issue stays open for points 2-4
- Deviations from spec: twelve pictures instead of "at least eight"; eight of them are of prototype views that show
  bundled sample data and are labelled `seed`; figures are not exported by the script yet (Amendments)
- Found on the way: the old withheld-message test withheld "the first new payload B is handed"; panes fetch the newest
  window first, so across a window boundary it withheld the last message and no alert could come. Old test: 29 of 30
  repeats passed; reproduction across a boundary: 4 of 8 trials without alert; changed test: 30 of 30 passed.
  A SHA-256 list written into the run directory tripped check_secrets (removed; the hashes are in the JSON record).
- Not verified: S6 (not started); that every earlier failure of that test had this cause; the whole test file
  repeated; `--views` subsets, the script making its own run directory, the move to evidence/superseded/; the page in
  Firefox or Safari; a CUDA engine behind the service
- Commit: 424a870
- Next: M13 S6 ; human action: none. Keep Docker Desktop running when you type continue

## Session 29 — 2026-10-12 18:56 — M13 Frontend: chat + server view — owner:Abhishek
- Steps: S6→S6 (status after: DONE; audit PASS)
- Did: `/v1/stats/live` gains `now_ms`, `epoch`, `last_epoch`, `last_write_ms` and `gpu {backend, runner, device,
  util}` (scheduler.py, app.py `live()`, baseline.py, switch.py, web.py, runtime.py `runner_name`); `last_write_ms`,
  `device` and `util` only with --dev. web/js/main.js: the strip counts the server's clock on between two answers,
  shows no epoch after 3 s without an answer, and says that the baseline has no epochs; api.js no longer falls back
  to a demo clock on a live page. Footer "dashboard data: ..."; the "dev" mark is no longer drawn as a switch.
  scripts/strip_drift.py (new). capture_evidence.py checks and quotes the strip, and keeps the picture of another
  run in evidence/superseded/ instead of overwriting it. docs/API.md, docs/DEMO.md ("The strip at the top").
- Evidence: runs/20261012-184104_M13_live_strip_s6 (strip_drift.json; pytest_all.txt 1993 passed, 675 skipped; pytest_m13.txt 41 passed;
  capture_run3.txt, capture_run4.txt, capture_evidence.json, superseded_check.txt; file_demo_check.json; ruff clean
  on src tests scripts bench; check_* PASS; a5_grep.txt empty); evidence/screens/M13_*_20261012.png (12, re-captured);
  evidence/superseded/ (the 12 of session 28)
- Metrics added: none (nothing measured: pictures and correctness only, numpy engine)
- Decisions: none (no ADR; the choices are in the Amendments of ai/modules/M13)
- Issues: opened ISSUE-33 (limits of the strip; low); ISSUE-31 point 4 and ISSUE-32 point 2 done, both stay open
- Deviations from spec: three fields of the route are dev-only; `last_write_ms` is not on the strip; a capture by
  another run no longer overwrites (Amendments)
- Found on the way: the first two capture runs of this session overwrote the pictures of session 28, which broke that
  run's recorded hashes and one test of the full suite; restored from git and fixed in the script, nothing
  allow-listed. The index row first quoted an epoch two ticks older than the one in the picture; it now says when it
  was read. `ruff check .` reports old scripts under runs/ and the colab notebook: only the code directories are linted.
- Not verified: the strip on a CUDA backend; drift beyond two minutes, over a network or in a background tab; a
  server clock that steps back; Firefox or Safari; the browser test file repeated many times (5 green runs today)
- Commit: f62c403
- Next: M14 S1 ; human action: none yet. ISSUE-17 and ISSUE-25 (open, high) block M14: the next session starts with
  them. Keep Docker Desktop running when you type continue

## Session 30 — 2026-10-12 19:25 — fix ISSUE-25 (M08 GPU obliviousness audit), prep — owner:Aditya
- Steps: S2→S2 of M08 for the issue only (module stays DONE; status after: BLOCKED_HUMAN at the GPU JOB READY gate)
- Did: bench/run_dudect.py: `_StageSeries` and the targets write_epoch_null_st, write_epoch_age_st, write_epoch_fresh_st
  (the calls and staging of the three ISSUE-17 diagnostics; series device_ms, call_ms, core_ms and one per engine
  stage h2d, tags, sort, compact, d2h, seal, bucket), group `issue25`, metric ids with the stage as suffix.
  bench/jobs/M08_issue25.json: unit tests, quick self-test, then control_null + issue25 at seeds 8, 10, 11, 12.
  tests/unit/test_run_dudect.py: 9 new tests. Packed job 20261012-191630_M08_issue25 from commit 3838502.
- Evidence: runs/20261012-191159_M08_i25_prep (summary.json: 4 targets, 0 mismatches, NOT_MEASURED; pytest_run_dudect.txt 65 passed;
  pytest_all.txt 2003 passed, 1 skipped, 674 deselected; ruff.txt, check_oblivious.txt, check_metrics.txt,
  check_secrets.txt PASS); gpujobs/out/20261012-191630_M08_issue25/job.json
- Metrics added: none (numpy backend: nothing measured)
- Decisions: none (no ADR). The reading rules a-e for the results are written into ISSUE-25 before the job runs
- Issues: ISSUE-25 updated, stays open; opened ISSUE-34 (HUMAN ACTION REQUIRED, GPU JOB READY)
- Deviations from spec: the per-stage series are new targets (`*_st`) instead of new series of the old targets, so
  the earlier jobs stay comparable; seed 8 is run again beside the three new seeds; `open` has no series (Amendments)
- Found on the way: a run directory name of 43 or more characters fails check_secrets (the first local run did);
  run names in the job spec are short for that reason
- Not verified: the new targets on a CUDA device; whether a stage is long enough to be timed alone (medians come
  with the results); the runtime of the job; ISSUE-17 points 1 and 2 (untouched, still block M14)
- Commit: 3838502 (prep, the commit of the job), 4102240 (records)
- Next: ingest 20261012-191630_M08_issue25, then M14 S1 ; human action: ISSUE-34 (run the job on Kaggle, put the
  results zip into gpujobs/inbox/). Do not change the repo before that


- GPU-JOB 20261012-191630_M08_issue25 ingested 2026-10-13 00:05: runner kaggle, gpu Tesla T4, session 20261012-135251, overall exit 0, runs 20261012-135342_M08_i25_selftest_quick, 20261012-135427_M08_dudect_i25_s8, 20261012-145303_M08_dudect_i25_s10, 20261012-155223_M08_dudect_i25_s11, 20261012-165055_M08_dudect_i25_s12, 144 metrics indexed.

## Session 31 — 2026-10-13 00:06 — fix ISSUE-25 (M08 GPU obliviousness audit), ingest — owner:Aditya
- Steps: none new (M08 stays DONE); the ingest half of `fix ISSUE-25` (status after: NOT_STARTED for M14, no job pending)
- Did: ingested job 20261012-191630_M08_issue25 (9 commands exit 0, shas match). runs/20261013-000602_M08_i25_ingest/gates_issue25.py
  recomputes every verdict from the raw npz and applies the reading rules a to e of ISSUE-25. No file under src/,
  kernels/, bench/, tests/, results/ or web/ changed.
- Result (negative): 56 of 124 series FAIL, the same ones in all four seeds. With EQUAL contents: h2d_ms and d2h_ms
  (write_epoch_null_st) and tags_ms and compact_ms (write_epoch_age_st) FAIL in 4 of 4 seeds. Fixed vs random contents:
  compact_ms FAILS in 4 of 4 seeds, core_ms and device_ms at seed 12. core_ms PASSES in 11 of 12 runs; control_null
  PASSES in all four. Rule b: chance is not the reading. Rule c: not met, the contents are neither shown nor excluded.
- Evidence: runs/20261012-135342_M08_i25_selftest_quick, runs/20261012-135427_M08_dudect_i25_s8, runs/20261012-145303_M08_dudect_i25_s10,
  runs/20261012-155223_M08_dudect_i25_s11, runs/20261012-165055_M08_dudect_i25_s12 (cupy, Tesla T4); runs/20261013-000602_M08_i25_ingest
  (gates.txt 249 PASS / 0 FAIL; pytest_all_rerun.txt 2003 passed, 1 skipped (tests/unit/test_oracle_chacha.py:82), 674 deselected; check_* PASS);
  evidence/terminal/M08_issue25_*, evidence/figures/M08_issue25_* (56 t-curves)
- Metrics added: 144 rows by `gpujob.py ingest`: T-DUDECT-MAXT-* and T-DUDECT-N-* of control_null and of the three
  `*_st` targets with their 10 series, for seeds 8, 10, 11, 12 and the self-test (one row per run; the run dir tells them apart)
- Decisions: none. The ADR on whole-call host timing is still open for the team (ISSUE-17 point 2, needed before M14)
- Issues: closed ISSUE-34; ISSUE-25 updated with the result, stays OPEN (high, BLOCKS M14); ISSUE-17 point 3 cross-referenced
- Deviations from spec: none new (Amendments of ai/modules/M08 record the result)
- Found on the way: the first full test run failed on a 48-character figure file name in a new row of evidence/INDEX.md
  (check_secrets); reworded, nothing allow-listed. The control of each run (control_null, a sort) ran at 1065 to 1110 MHz, every write_epoch target
  at 585 MHz; bucket_ms is below the 50 us rule (about 33 us)
- Not verified: the cause of any stage FAIL (H7 host launch time inside a stage interval, H8 contents: both untested);
  a write_epoch series at another clock; a second GPU model; write_epoch itself per stage
- Commit: a9178f8
- Next: fix ISSUE-25, prep of the kernel-window target for tags and compact (then a GPU job), M14 S1 after it ;
  human action: none now. The team decision on whole-call host timing (ISSUE-17 point 2) is needed before M14

## Session 32 — 2026-10-13 01:10 — fix ISSUE-25 (M08 GPU obliviousness audit), prep of the last job — owner:Aditya
- Steps: none new (M08 stays DONE); the prep half of `fix ISSUE-25` (status after: BLOCKED_HUMAN, job 20261013-005946_M08_issue25k)
- Did: `bench/run_dudect.py`: group `issue25k` (tags_kernel, compact_kernel, a same-contents control of each,
  control_leak_q). The timed window is enqueued behind a blocker launch, so no host code runs between the two events;
  an event query flags a measurement that was not queued. The SM clock is read after every measurement, flags for
  off-clock ones, `--lock-clock` (nvidia-smi -lgc, answer recorded, reset at the end). `telemetry.sm_clock`,
  `lock_clock`, `unlock_clock`; `timing.warm_until_stable(flat_polls=)`. Job spec `bench/jobs/M08_issue25k.json`.
- Found by reading the code (pinned by a test): tags, sort and compact of write_epoch never receive the submissions,
  so their device inputs were byte-identical in both classes of every session-31 target. H8 is excluded for those
  series; they also never tested these kernels against their own data. The new classes do (key, permutation).
- Checked against the session request: (a) the class order IS a random interleaving per measurement; control_null is a
  separate target, not a class, so it does not explain the equal-contents FAILs. (b) All 120 write_epoch series ran
  at a steady 585 MHz: 56 FAIL, 64 PASS at the same clock (runs/20261013-005353_M08_i25k_prep/clock_facts.txt). No target had a clock drop.
- NOT done: the 56 rows were not re-labelled UNSTABLE. Rule 5 is not met by any of them, and the label would
  replace 56 measured values while the 64 PASS values at the same clock stay. Left to the human (ISSUE-25, ISSUE-35).
- Evidence: runs/20261013-005353_M08_i25k_prep (clock_facts.txt; pytest_all.txt 2026 passed, 1 skipped (tests/unit/test_oracle_chacha.py:82),
  674 deselected; pytest_changed_rerun.txt 127 passed after the last two edits; ruff, check_oblivious, check_secrets,
  check_metrics PASS); runs/20261013-005359_M08_i25k_plumb (numpy, NOT_MEASURED: plumbing and outputs, 0 mismatches)
- Metrics added: none (nothing measured; the backend was numpy)
- Decisions: ADR-023 (the human's decision: P3 is claimed for the kernels, host timing is outside the threat model)
- Issues: ISSUE-25 updated (findings, reading rules f to k, timebox), stays OPEN; ISSUE-17 point 2 decided, stays
  open for points 1 and 3; opened ISSUE-35 (HUMAN ACTION REQUIRED, GPU JOB READY)
- Deviations from spec: the window and the per-measurement clock are not in M08 S1 (Amendments). The limitation
  line was added to the generator of section 4.O.6, not to docs/REPORT_CH4_NOTES.md: it appears at the next
  regeneration. The message of commit c510682 says 21 unit tests; it is 9 test functions, 18 cases.
- Not verified: anything on a CUDA device. Whether Kaggle accepts the clock lock; whether a blocker of at most 2^20
  ChaCha blocks keeps the compaction queued; what one NVML read costs per measurement; the runtime of the job.
- Commit: c510682 (prep, the commit of the job), 57af640 (records)
- Next: ingest 20261013-005946_M08_issue25k, close ISSUE-25 by the rules, then M14 S1 ; human action: ISSUE-35 (run the job on Kaggle,
  put the results zip into gpujobs/inbox/, and say what to do with the session-31 rows). Do not change the repo before that

## Session 33 — 2026-10-13 01:11 — fix ISSUE-25 (M08 GPU obliviousness audit), the decision on the session-31 rows — owner:Aditya
- Steps: none new (M08 stays DONE). The ingest did NOT run: gpujobs/inbox/ was empty (status after: BLOCKED_HUMAN,
  job 20261013-005946_M08_issue25k still pending)
- Did: applied the human's decision. ANN-1 at the top of state/METRICS_INDEX.md annotates the 120 write_epoch
  series of job 20261012-191630_M08_issue25: every value kept, the 56 FAILs not replaced; the condition (585 MHz, the control
  at another clock) and, for tags and compact (and sort), the real limit: device inputs byte-identical in both
  classes, so these series could not show a dependence on the contents and the kernels were never tested against
  their own secrets, which is what the pending job does.
- Recorded for the ingest: reading rule l (ISSUE-25: prefer a steady unlocked clock to a locked one with more
  off-clock flags) with what the packed job can and cannot give for it; the ISSUE-18 question (ISSUE-18 update).
- Evidence: runs/20261013-010926_M08_i25_annotate (annotation_check.txt: 120 rows covered, 12 each of TAGS, COMPACT, SORT, 0 table lines
  changed, no bundled path changed since c510682; check_metrics.txt 475 rows, 0 problems; pytest_index.txt 17 passed;
  check_secrets.txt); evidence/terminal/M08_issue25_annotation_check.txt
- Metrics added: none (nothing measured)
- Decisions: none new (the human's decision is recorded in ISSUE-25; no ADR)
- Issues: ISSUE-25 updated, stays OPEN; ISSUE-35 updated, stays OPEN (the zip is still wanted); ISSUE-18 updated
- Deviations from spec: the index has no note column, so the annotation is a section above the table and not a
  mark on each row. The note is not yet in the generated section 4.O of docs/REPORT_CH4_NOTES.md: its generator is
  under src/ and bench/ data, frozen until the ingest so that the packed job stays valid.
- Found on the way: both seeds of the packed job ask for the clock lock. If Kaggle accepts it, the job holds no
  unlocked kernel-window run, so rule l cannot be applied inside this job (ISSUE-25).
- Not verified: anything on a CUDA device. Whether the human has already started the job on Kaggle. The full test
  suite was not run (no code changed); only the tests of the index and of gpujob.
- Commit: 1dea96e (records)
- Next: ingest 20261013-005946_M08_issue25k, close ISSUE-25 by rules f to l, add ANN-1 to report_oblivious, then M14 S1 ;
  human action: ISSUE-35 (run the job on Kaggle, put the results zip into gpujobs/inbox/). Do not change the repo before that

- GPU-JOB 20261013-005946_M08_issue25k ingested 2026-10-13 08:47: runner kaggle, gpu Tesla T4, session 20261013-021903, overall exit 1, runs 20261013-022000_M08_i25k_selftest_quick, 20261013-022124_M08_dudect_i25k_s8, 20261013-024742_M08_dudect_i25k_s10, 53 metrics indexed.

## Session 34 — 2026-10-13 09:40 — fix ISSUE-25 (M08 GPU obliviousness audit), ingest of the last job — owner:Aditya
- Steps: none new (M08 stays DONE). Ingested job 20261013-005946_M08_issue25k (status after: NOT_STARTED for M14, no job pending)
- Did: `gpujob.py ingest` (job id, bundle sha, git sha verified; 53 rows indexed); gates script recomputing every
  max abs(t) and flag count from the raw npz and applying rules f to l; `report_oblivious` extended with section
  4.O.7 (kernel-only window) and the ANN-1 note, 5 new test cases; results/oblivious and the notes regenerated.
- Result: tags (fixed key vs random keys) and compact (fixed vs random permutation): null and target PASS in both
  seeds (tags 1.1320, 1.4622 / 2.1075, 1.9069; compact 0.7532, 2.2966 / 0.9475, 1.9613). Rule g: no dependence
  detected at this N, on this device. Lock refused (rule k); modal clock 1590 MHz; flagged 3.09% to 4.12%.
- Limits found: control_leak_q was unqueued in 19749 of 20000 measurements (its 251 queued ones: t -24.4826); all
  eight windows are below 50 us (22 us, 41 us); clock_reset exit 4 made the job report exit 1.
- Evidence: runs/20261013-084838_M08_i25k_ingest (gates.txt 55 PASS 0 FAIL, ingest.txt, report.txt, pytest_all.txt 2031 passed
  1 skipped, check_metrics.txt, check_secrets.txt, check_oblivious.txt, ruff.txt, validate.txt);
  runs/20261013-022000_M08_i25k_selftest_quick, runs/20261013-022124_M08_dudect_i25k_s8, runs/20261013-024742_M08_dudect_i25k_s10;
  evidence/terminal/M08_issue25k_gates.txt, _gpu_run_output.txt, _kernel_window.csv; evidence/figures/M08_issue25k_*
- Metrics added: 53 by the ingest (cupy, kaggle), annotated by ANN-2. The queued-only t of control_leak_q is a
  derived quantity in gates.txt and section 4.O.7, not an index row (check_metrics accepts only what a summary lists)
- Decisions: none new
- Issues: ISSUE-25 CLOSED, ISSUE-35 CLOSED; ISSUE-17 updated (point 1 is the only open point, still BLOCKS M14);
  opened ISSUE-36 (medium, BLOCKS none: weak positive control, windows below 50 us; a decision for the human)
- Deviations from spec: rule f was read with the 5% bound on the kernel-window targets, not on the control. One
  number of section 4.O.7 (the queued-only t) is generated from a raw file and has no index row.
- Not verified: the kernel-window result on a second session, GPU or size; a full-N positive control of the queued
  window; anything about the AEAD kernels or the whole write path. The 1 skipped test was not looked into.
- Commit: 9a6936f
- Next: `fix ISSUE-17` point 1 (the report table shows the diagnostics; local, no GPU), then M14 S1 ; human action:
  none required. Optional: decide ISSUE-36 (keep the result with its limits, or NOT_MEASURED)

## Session 35 — 2026-10-13 — fix ISSUE-17 point 1 (M08 GPU obliviousness audit), the report table — owner:Aditya
- Steps: none new (M08 stays DONE). Local unit, no GPU job (status after: NOT_STARTED for M14, no job pending)
- Did: `report_oblivious` gains `--diagnostics` / `--issue-diagnostics`: a sub-section of 4.O.3 and
  results/oblivious/staging_diagnostics.csv put the ISSUE-17 runs (seeds 8 and 9) beside the three failing S2
  series; the same rows are appended to summary_table.csv. 7 new test cases. results/oblivious and the notes regenerated.
- Result: nothing measured. Table: 38 rows (4 of S2, 34 of the diagnostic job); the S2 rows unchanged; 3 S2 FAILs and 18 diagnostic FAILs kept.
  Readings by the rules of ISSUE-17: aead_conv, aead_tag and write_epoch (whole call) follow the staging, not the
  contents; no dependence on the contents detected at this N, on this device. Never "constant time".
- Evidence: runs/20261013-091541_M08_issue17_table (report.txt, report_command.txt, gates.txt 49 PASS 0 FAIL, pytest_all.txt 2038 passed
  1 skipped, check_metrics.txt, check_secrets.txt, check_oblivious.txt, ruff.txt, regen_identical.txt);
  evidence/terminal/M08_issue17_staging_diagnostics.csv, _summary_table.csv, _section_4O3.md, _pytest_all.txt
- Metrics added: none (every value was indexed by the ingests of sessions 16 and 21)
- Decisions: none new
- Issues: ISSUE-17 CLOSED (points 2 and 3 were closed in sessions 32 and 34). ISSUE-36 stays OPEN (optional decision)
- Deviations from spec: the S2 staging was kept and the diagnostics are shown beside it; the other way named in
  ISSUE-17 (symmetric staging as the S2 staging, measured again) was not taken. The text of the "not explained"
  bullet and of one limitation line in 4.O.3 / 4.O.6 changes when diagnostics are given.
- Not verified: nothing on a CUDA device this session. For the AEAD targets staging and SM clock change together;
  the generator says so and does not separate them. The gates script was inline and is not saved.
- Commit: 44d7ff5
- Next: M14 S1 (Security evaluation, owner Abhishek) ; human action: none required. Optional: decide ISSUE-36

## Session 36 — 2026-10-13 — M14 Security evaluation, S1 traffic on the real stack — owner:Abhishek
- Steps: S1 done (status after: IN_PROGRESS, current_step S2, no job pending)
- Before the unit, at the request of the human: ISSUE-37 opened (low) so that the residual of ISSUE-17 (S2 never
  measured again with symmetric staging; staging and SM clock not separated) stays traceable. Nothing measured for it.
- Did: src/vcloak/eval/traffic.py (the burst model of the oracle with the same draws; replay through POST /v1/messages
  on the sim clock, epoch by epoch), bench/run_security_eval.py (--stage s1), tests/unit/test_eval_traffic.py (12 cases).
- Result: seed 2026, 200 conversations, 900 s: 24733 messages sent, 24733 rows in PostgreSQL (SQL count and
  ciphertext digests agree), 4501 epochs, 0 errors, 0 overflow, 15 windows each re-shuffled once. Engine: numpy
  simulator, so this is correctness evidence only.
- Evidence: runs/20261013-094044_M14_security_s1 (s1_traffic.json, summary.json, pytest_all.txt 2050 passed 675
  skipped, check_metrics.txt, check_secrets.txt, check_oblivious.txt, ruff.txt, g10_quick_rerun.txt,
  g10_same_seed_sqlite.txt); evidence/terminal/M14_S1_s1_traffic.json
- Metrics added: S-TRAFFIC-MSGS (numpy, local; a count, not a performance number)
- Decisions: none new
- Issues: opened ISSUE-37 (low, BLOCKS none) and ISSUE-38 (medium, BLOCKS M14: A1 wants engine=gpu, the service and
  a database have never run on the runner). ISSUE-36 stays OPEN
- Deviations from spec: scheduler stepped by the replay (autorun off) instead of the free-running sim clock; metric
  id S-TRAFFIC-MSGS is not in the module list; both in the Amendments of the module file.
- Not verified: anything on a CUDA device; the read path (S2); the attack (S3); that the PostgreSQL dump order is
  the physical order the attack needs. The same events as the seed oracle are expected from the same draws (a unit
  test compares against a copy of its loop); the oracle itself was not run this session.
- Commit: 63a41b5
- Next: M14 S2 (E0 restoration) ; human action: none required. Optional: decide ISSUE-36; say whether an M14 GPU
  job is allowed (ISSUE-38)

## Session 37 — 2026-10-13 — M14 Security evaluation, S2 to S5 prep and the full-stack GPU job — owner:Abhishek
- Steps: S2, S3, S4, S5 written and run on the simulator; none complete (status after: BLOCKED_HUMAN, current_step S2,
  job 20261013-105517_M14 pending)
- Human decisions this session: a full-stack GPU job for M14 is allowed and wanted (ISSUE-38, way 1), on Colab; the
  674 tests marked gpu are to run in it; STATE.md back under 120 lines. ISSUE-36 was summarised; not decided yet.
- Did: src/vcloak/eval/attack.py, uniformity.py, trace.py; `kernels.set_launch_hook` (public arguments);
  bench/run_security_eval.py stages attack, uniformity, trace; scripts/runner_stack.py (PostgreSQL in the runner);
  bench/run_gpu_tests.py; bench/jobs/M14.json; tests/unit/test_eval_security.py (25 cases); STATE.md 124 -> 115 lines.
- Result (numpy simulator, seed 2026, PostgreSQL 16.15, correctness only): six layouts, 24733 rows each; turn-order
  accuracy BASELINE 1.0000, EPOCH 0.9820, W1 0.9202, W10 0.6867, W60 0.5560, W300 0.5068; E0 60 of 60 in exact order;
  quick uniformity 3 of 3 gates; trace 6 of 6 gates.
- Evidence: runs/20261013-103235_M14_security_e0e1 (e1_attack.json, attack_table.csv, e0_restoration.json, pytest_all.txt 2075 passed 675 skipped,
  check_*.txt, ruff.txt, g10_quick_rerun.txt, runner_stack_container_rehearsal.txt);
  runs/20261013-102418_M14_security_e2_quick; runs/20261013-102417_M14_security_e3; evidence/terminal/M14_S2S5_*
- Metrics added: 35 rows (S-TAU-*, S-TURNACC-*, S-F-*, S-E0-RESTORE, S-CANDK, S-OCC-*, S-CHI2*, S-TAUBAND-PCT,
  S-TAU-SIGMA-MEAS, S-TRACE-DISTINCT-*), all backend numpy / runner local; the job gives the cupy rows
- Decisions: none new (ADR); S4 gate definitions and the other choices are in the Amendments of the module file
- Issues: ISSUE-38 updated (decided, stays OPEN until the ingest); opened ISSUE-39 (GPU JOB READY, BLOCKS M14) and
  ISSUE-40 (S6, S7 not written and not in the job; W300 occupancy above CAND_K on the simulator)
- Deviations from spec: S2 and S3 are one stage; figures at the ingest, not in the job; trace digests are 128 bits;
  the uniformity run in the repo is quick sizes (the full sizes are too slow on the simulator)
- Not verified: anything on a CUDA device; scripts/runner_stack.py on Colab itself (rehearsed in an ubuntu:22.04
  container as root); the service's engine thread with CuPy; that `-m gpu` selects 674 tests on the runner; the
  job's runtime (about 1 hour is an estimate)
- Commit: e5a82fc (code; the job is packed from it), a74eea2 (records)
- Next: ingest job 20261013-105517_M14 ; human action: ISSUE-39 (run the job on Colab); decide ISSUE-36 and ISSUE-40


- GPU-JOB 20261013-105517_M14 ingested 2026-10-13 11:51: runner colab, gpu Tesla T4, session 20261013-054610, overall exit 0, runs 20261013-054644_M14_security_s1, 20261013-054727_M14_security_e0e1, 20261013-055417_M14_security_e2, 20261013-055444_M14_security_e3, 20261013-055445_M14_cuda_tests, 40 metrics indexed.

## Session 38 — 2026-10-13 — M14 Security evaluation, ingest of the full-stack job, S2 to S5 — owner:Abhishek
- Steps: S2, S3, S4, S5 complete on the device (status after: IN_PROGRESS, current_step S6)
- Did: ingested job 20261013-105517_M14 (Colab, Tesla T4, PostgreSQL 16 in the runner; 11 of 11 commands exit 0);
  wrote src/vcloak/bench/report_security.py and tests/unit/test_bench_report_security.py (11 cases); report.py keeps
  the M14 block of the notes; generated results/security (stage files, gates.csv, two figures with sidecars,
  security_summary.json) and section 4.S of docs/REPORT_CH4_NOTES.md.
- Result (cupy, real stack, seed 2026, one replay): 61 of 61 gates PASS. Turn-order accuracy BASELINE 1.0000,
  EPOCH 0.9820, W1 0.9202, W10 0.6867, W60 0.5560, W300 0.5068; E0 60 of 60; chi2 p 0.9013; tau band 99.7 %;
  device trace 1 distinct against 4 for merge sort; 674 of 674 tests marked gpu passed. The attack table, E0 and E3
  equal the simulator run of session 37 byte for byte.
- Evidence: runs/20261013-054644_M14_security_s1, runs/20261013-054727_M14_security_e0e1, runs/20261013-055417_M14_security_e2,
  runs/20261013-055444_M14_security_e3, runs/20261013-055445_M14_cuda_tests (ingested);
  runs/20261013-115636_M14_security_ingest_report (pytest_all.txt 2086 passed 1 skipped, check_*.txt, simulator_parity.txt,
  g10_quick_rerun.txt); evidence/figures/M14_fig_*, evidence/terminal/M14_ingest_*, evidence/gpu/M14_*
- Metrics added: 40 rows by the ingest (S-*, backend cupy, runner colab)
- Decisions: none new (ADR); the generator and the figure choices are in the Amendments of the module file
- Issues: closed ISSUE-38 and ISSUE-39; ISSUE-40 updated (W300 occupancy above CAND_K on the device too), stays OPEN
- Deviations from spec: results and notes come from a generator the Deliverables do not name; no separate
  uniformity figure
- Not verified: S6 (anonymity set) and S7 (comparison with the oracle), both not written; E2 parity with the simulator
  at full size; more than one seed or replay
- Commit: 6bc85b8
- Next: M14 S7, then S6 ; human action: decide ISSUE-40 (a second small GPU job for S6, or S6 on the simulator with A1
  recorded as not met for it); ISSUE-36 is still undecided

## Session 39 — 2026-10-13 — M14 Security evaluation, S7 comparison with the CPU oracle — owner:Abhishek
- Steps: S7 complete (status after: IN_PROGRESS, current_step S6)
- Did: wrote src/vcloak/eval/oracle_compare.py (verdict rules), bench/run_oracle_compare.py (runs seed/vcloak_oracle.py
  unchanged, output redirected into the run dir, plus 20 repetitions of its attack with fresh keys),
  bench/oracle_chi2_repeat.py (diagnostic), tests/unit/test_eval_oracle_compare.py (12 cases), 3 cases more in
  tests/unit/test_bench_report_security.py; report_security takes --oracle and writes section 4.S.9.
- Result: 35 rows device (T4 + PostgreSQL, job 20261013-105517_M14) against oracle (laptop CPU, seed 2026): 12 EQUAL,
  19 WITHIN_NOISE, 2 NOT_COMPARABLE, 2 DIFFERS. Same traffic on both sides (24733 messages; f equal in every shuffled
  layout). The 2 DIFFERS rows are the oracle's chi-square (4222.8, p 0.0026: the oracle fails the gate, the device
  passes). Diagnostic with 10 fresh keys: median 3952.9, none below p 0.01.
- Evidence: runs/20261013-121247_M14_oracle_compare (oracle/, oracle_reps.json, oracle_comparison.*),
  runs/20261013-122525_M14_oracle_chi2_repeat, runs/20261013-122548_M14_oracle_report (pytest_all.txt 2101 passed
  675 skipped, check_*.txt, g10_quick_rerun.txt, report_command.txt); results/security/oracle_comparison.*;
  evidence/terminal/M14_S7_*
- Metrics added: 45 rows S-ORACLE-* (backend numpy, runner local: CPU reference values, never GPU results)
- Decisions: none new (ADR); the noise criteria are in the Amendments of the module file
- Issues: opened ISSUE-41 (the two differing rows); ISSUE-40 updated (S7 done, S6 left), stays OPEN
- Deviations from spec: "sampling noise" defined by this build (Amendments); the diagnostic is not in the module text
- Not verified: S6; more than one seed, device replay or oracle main run; whether the oracle's chi-square has a small
  bias (10 tables cannot exclude it); the normal approximation behind the prediction intervals
- Commit: b299525 (code), e25a24c and 689f418 (run, diagnostic script), records 2a6d14a
- Next: M14 S6 (code first; GPU job or simulator per ISSUE-40) ; human action: decide ISSUE-40 and ISSUE-41; ISSUE-36
  is still undecided

## Session 40 — 2026-10-13 — M14 Security evaluation, S6 anonymity set (prep half) — owner:Abhishek
- Steps: S6 code and GPU job (status after: BLOCKED_HUMAN, current_step S6, pending 20261013-125843_M14_s6)
- Did: wrote src/vcloak/eval/anonymity.py (real rows per window and per bucket-window, empty cells counted as 0, the
  same count as a row sees it), the stage `--stage anonymity` of bench/run_security_eval.py (10, 100, 1000 users in
  pairs into the W = 60 layout, counted and attacked on the dump), bench/jobs/M14_s6.json,
  tests/unit/test_eval_anonymity.py (13 cases). ISSUE-40 had no decision recorded: the job was packed, as it says.
- Result: no device result yet. Local check on the numpy simulator with PostgreSQL, full size: 3 of 3 populations ok
  (555, 5855 and 61383 messages; every check of the stage passed). Simulator only: at 1000 users the fullest
  bucket-window is above CAND_K. pytest 2114 passed, 675 skipped (674 need a CUDA device, 1 deliberate).
- Evidence: runs/20261013-124943_M14_security_anon (s6_anonymity.json, anonymity_table.csv; backend numpy: correctness only);
  runs/20261013-125258_M14_s6_prep_checks (pytest_all.txt, check_*.txt, ruff.txt, g10_quick_rerun.txt, manifests_valid.txt);
  evidence/terminal/M14_S6prep_pytest_all.txt; gpujobs/out/20261013-125843_M14_s6/job.zip (packed from b042dc8)
- Metrics added: 24 rows S-ANON-*, S-TURNACC-W60-U*, S-F-W60-U* (backend numpy, runner local: simulator values,
  never GPU-stack results; the cupy rows come with the ingest)
- Decisions: none new (ADR); the users-to-conversations mapping and the cell counting are in the Amendments of the
  module file
- Issues: opened ISSUE-42 (GPU JOB READY); ISSUE-40 updated, stays OPEN until the ingest
- Deviations from spec: the mapping of users to conversations is this build's (pairs, as M15 S1); metric ids beyond
  S-ANON-MED-U<users>; an intermediate simulator run made on an uncommitted tree was removed and repeated on 9c0e7f6
  (same output)
- Not verified: S6 on the device; report_security does not yet take the S6 run (a second runner session), so the
  notes still say NOT_MEASURED for S6; one seed, one replay per population; the runner time of the job
- Commit: 9c0e7f6 (code), b042dc8 (simulator run, checks), records 966e0ab
- Next: M14 ingest of 20261013-125843_M14_s6, then the S6 section and the module audit ; human action: ISSUE-42 (run the
  job, or say "S6 on the simulator"); ISSUE-41 and ISSUE-36 are still undecided

- GPU-JOB 20261013-125843_M14_s6 ingested 2026-10-13 15:49: runner colab, gpu Tesla T4, session 20261013-101235, overall exit 0, runs 20261013-101309_M14_security_anon, 24 metrics indexed.

## Session 41 — 2026-10-13 — M14 Security evaluation, S6 anonymity set (ingest half) and module audit — owner:Abhishek
- Steps: S6 ingest, report, audit (status after: M14 DONE; next_unit M15)
- Did: ingested job 20261013-125843_M14_s6 (7 of 7 commands exit 0). `report_security` got `--anonymity`: a run of a
  second runner session, same real-stack checks, own provenance line, its stage checks in gates.csv (5 new test
  functions, 8 cases). Regenerated results/security and section 4.S of the notes; captured evidence; audited M14.
- Result (T4 + PostgreSQL, seed 2026, one replay each, W = 60): real rows per window, median / p5: 32 / 23.5 at 10
  users, 384 / 331 at 100, 4098 / 3960.8 at 1000. Per bucket-window median / p5: 0 / 0, 0 / 0, 62 / 26 (900, 520, 0 of
  960 cells empty). Turn-order accuracy 0.5691, 0.5583, 0.5559. Fullest bucket-window 26, 42, 172: above CAND_K 128
  at 1000 users (ISSUE-43). Every cell equals the simulator run of session 40. 82 of 82 gates PASS.
- Evidence: runs/20261013-101309_M14_security_anon (device run); runs/20261013-155229_M14_s6_ingest_report (report_command.txt,
  report_stdout.txt, pytest_all.txt 2121 passed 675 skipped, check_*.txt, ruff.txt, g10_quick_rerun.txt);
  results/security/s6_anonymity.json, anonymity_table.csv; evidence/terminal/M14_S6_*, evidence/gpu/M14_S6_nvidia_smi.txt
- Metrics added: 24 rows S-ANON-*, S-TURNACC-W60-U*, S-F-W60-U* (backend cupy, runner colab), indexed by the ingest
- Decisions: none new (ADR); how the second session is reported is in the Amendments of the module file
- Issues: closed ISSUE-42 and ISSUE-40; opened ISSUE-43 (occupancy above CAND_K at 1000 users and at W300)
- Deviations from spec: S6 from a runner session of its own; stage checks counted in the gate table; no S6 figure
- Not verified: more than one seed or replay; a read on a layout above CAND_K (only dumped); how many bucket-windows
  are above CAND_K at 1000 users; another mapping of users to conversations
- Commit: ce8de77 (ingest, generator), d08aa1a (results, notes, evidence), records 492c599
- Next: M15 (ISSUE-12 BLOCKS M15 and comes first) ; human action: none required; ISSUE-41, ISSUE-36 and ISSUE-43 are
  open for a decision of the owner

## Session 42 — 2026-10-13 — ISSUE-12 (BLOCKS M15): the host path of write_epoch, prep half — owner:Aditya
- Steps: ISSUE-12 fix and job (status after: M15 NOT_STARTED, BLOCKED_HUMAN on job 20261013-163732_M07_issue12; next_unit M15)
- Did: `row_ids` in src/vcloak/gpu/engine.py builds the row ids of an epoch in one pass (bits set on the entropy
  matrix, objects filled through their slots); `write_epoch` uses it and builds the rows with one `map`. 7 new test
  cases. Job spec bench/jobs/M07_issue12.json; job packed.
- Result: none measured. The ids and the stored rows are byte-identical to before (tests; engine equals the oracle at
  64 to 65536 slots on the simulator). Whether p99 < EPOCH_MS holds at 65536 slots is NOT_MEASURED until the ingest.
- Evidence: runs/20261013-163225_M07_issue12_prep_checks (pytest_all.txt 2128 passed 675 skipped, ruff.txt, check_*.txt,
  g10_quick_rerun.txt); gpujobs/out/20261013-163732_M07_issue12/job.zip (packed from 36c8b35)
- Metrics added: none
- Decisions: none new (ADR)
- Issues: ISSUE-12 updated (stays OPEN); opened ISSUE-44 (GPU JOB READY)
- Deviations from spec: the issue proposed column arrays; the rows stay `StoredRow` objects (interface of ARCHITECTURE §4,
  ADR-014), only the uuid construction and the comprehension changed
- Not verified: any timing; the engine against the oracle on the device (in the job); the runtime of the job
- Commit: 59d622f (code, job spec), 36c8b35 (checks), records 6de1c9f
- Next: ingest of 20261013-163732_M07_issue12, then M15 S1 ; human action: ISSUE-44 (run the job)

- GPU-JOB 20261013-163732_M07_issue12 ingested 2026-10-13 16:50: runner colab, gpu Tesla T4, session 20261013-111455, overall exit 0, runs 20261013-111612_M07_pipeline, 60 metrics indexed.

## Session 43 — 2026-10-13 — ISSUE-12: the host path of write_epoch, ingest half — owner:Aditya
- Steps: ISSUE-12 ingest and gate (status after: M15 NOT_STARTED, no pending job; next_unit M15)
- Did: ingested job 20261013-163732_M07_issue12 (Colab T4, 2 vCPU; 5 of 5 commands exit 0). Read the real-time gate from the
  summary.json of the new run and of the M07 run (gates.txt, generated). ANN-3 in METRICS_INDEX. No code changed.
- Result: the gate still FAILS for the whole call at 65536 slots and the measurement is UNSTABLE; the device part
  passes; the gate passes at 64 to 16384 slots on UNSTABLE measurements. 12 of 12 configurations UNSTABLE, so the 60
  indexed rows carry no value. On the device: 154 engine tests pass, 0 oracle mismatches, no `uuid.py` in the host
  profile. The attempt values are in ISSUE-12 and gates.txt; none is a reportable metric.
- Evidence: runs/20261013-111612_M07_pipeline (device run); runs/20261013-165216_M07_issue12_ingest_checks (gates.txt, pytest_all.txt
  2128 passed 675 skipped, check_*.txt, ruff.txt, g10_quick_rerun.txt, job_log_*.txt); evidence/terminal/M07_ISSUE12_*
- Metrics added: 60 rows P-WRITE-EPOCH-* and the read_window rows of the run, all UNSTABLE (backend cupy, runner colab)
- Decisions: none new (ADR)
- Issues: ISSUE-12 updated (OPEN, BLOCKS none: a measured limitation); ISSUE-15 updated; closed ISSUE-44
- Deviations from spec: the M07 notes were not regenerated (`vcloak.bench.report` takes four runs of one session)
- Not verified: a before/after speed-up (Kaggle 4 vCPU against Colab 2 vCPU); the cause of the tail; a stable
  measurement of any pipeline row on this runner
- Commit: 698dff2 (ingest), records c50fe95
- Next: M15 S1 ; human action: none required; ISSUE-12 has three options open for a decision of the owner

## Session 44 — 2026-10-13 — M16 Results export (with the decisions on ISSUE-12 and ISSUE-36) — owner:Abhishek
- Steps: S1→S4 (status after: M16 AUDIT_FAILED at S4, job 20261013-173239_M07_issue12k pending; next_unit M16)
- Did (owner decisions first): ISSUE-12 text corrected (the Colab run was UNSTABLE in 12 of 12 configurations, so 65536
  slots are UNMEASURED under valid conditions, not "measured and failing"; no attempt value is quoted any more in the
  issue, ANN-3 or STATE). ADR-024 and gpu-bench rules 8 to 10: comparisons within one runner platform, vCPU count in
  every provenance line (manifest `cpu_count`, `runs.runner_vcpu`), a platform guard in pack and in the runner entry.
  Section 4.P.6 of the notes marked STALE in place. ISSUE-36 decided: the eight kernel-only series are NOT_MEASURED
  (16 index rows, ANN-4; generator flag `--kernel-window-not-measured`; sections 4.O and 4.S regenerated).
  M16: scripts/export_results.py, results/paper (13 files and the source map), results/figures, PAPER_UPDATES.md,
  deck_numbers.md. Kaggle rerun packed as bench/jobs/M07_issue12k.json (runner_required kaggle, 4 vCPU).
- Result: 372 exported values: 163 index rows, 36 derived from index rows only, 64 public parameters, 75 run-file
  fields, 1 derived with a field, 33 without a value (UNSTABLE, NOT_MEASURED, M15 not run, ISSUE-12 held back, no AES).
  Kaggle internet is not needed for the rerun (no `stack_up`, no bundle ever installed a package).
- Evidence: runs/20261013-171026_M16_prefixes (kaggle_internet_check.txt, report_command.txt, pytest_all.txt 2132 passed);
  runs/20261013-172550_M16_export (export_stdout.txt, export_check.txt, a1_traceability.txt, pytest_all.txt 2138 passed 1 skipped,
  check_*.txt, ruff.txt); evidence/terminal/M16_*
- Metrics added: none. 16 rows changed to NOT_MEASURED (ANN-4); ANN-3 corrected
- Decisions: ADR-024 (decision of the owner, recorded by the agent)
- Issues: ISSUE-12 corrected (OPEN); ISSUE-36 closed; opened ISSUE-45 (GPU JOB READY, Kaggle) and ISSUE-46 (BLOCKS M16)
- Deviations from spec: audit A1 is not met for 9 macros (run-file fields without a METRIC-ID, ISSUE-46); the pipeline
  breakdown and the two write_epoch figures are held back (ISSUE-12); the e2e table is all pending (M15); no LaTeX on
  this machine, so A3 is a syntax check; the deck is not in the repository, so deck_numbers.md has no slide numbers;
  docs/REPORT_CH4_NOTES.md got no M16 section; the mapping of the `Conv` macros to the baseline layout is a choice
  of the exporter (stated in PAPER_UPDATES.md section 5); the job was packed three times (twice discarded as stale)
- Not verified: that the .tex files compile in the Overleaf project; any timing; that Kaggle gives 4 vCPU today
- Commit: 28c0c40 (decisions, ADR-024, ISSUE-36), 4a50288 and f3903bc (M16), records 2dec7aa
- Next: ingest 20261013-173239_M07_issue12k if it is in the inbox, then M16 A1 ; human action: ISSUE-45 (run the job on
  Kaggle), ISSUE-46 (decide A1), ISSUE-41 and ISSUE-43 (answers announced for this handoff)


- GPU-JOB 20261013-173239_M07_issue12k ingested 2026-10-13 17:49: runner kaggle, gpu Tesla T4, session 20261013-121357, overall exit 0, runs 20261013-121512_M07_pipeline, 60 metrics indexed.

## Session 45 — 2026-10-13 — M16 Results export: ingest of the ISSUE-12 rerun, A1 decided, M16 DONE — owner:Abhishek
- Steps: ingest (M07 S5, owner Aditya), then M16 audit (status after: M16 DONE at S4; next_unit M19)
- Did: ingested job 20261013-173239_M07_issue12k (Kaggle; 5 of 5 commands exit 0) and read its gates against the M07 run.
  Asked the owner the two open decisions. ISSUE-46: (a) with conditions; A1 amended in the module file, the exporter
  enforces "ingested run or index row", report/TRACEABILITY.md is generated. ISSUE-12: (c), limitation accepted.
  Exporter: hold-back reasons updated; session_table.tex no longer prints a failed check twice.
- Result: the run is on the platform and image of the M07 run (Kaggle, T4, 4 vCPU, CUDA 12090, driver 580.178.04).
  write_epoch is UNSTABLE at 1024, 4096, 16384 and 65536 slots, so there is no gate verdict at 65536 and the
  before/after of the row-id change is NOT_MEASURED. Stable: write_epoch at 64 slots, read_window at all seven K.
  Export: 39 files, 372 mapped values (163 index rows, 37 derived, 64 parameters, 75 run-file fields, 33 without a value).
- Evidence: runs/20261013-121512_M07_pipeline (device run); runs/20261013-174910_M07_issue12k_ingest_checks (gates.txt, a1_traceability.txt,
  pytest_all.txt 2142 passed 675 skipped, export_check.txt, check_*.txt, ruff.txt, g10_quick_rerun.txt, job_log_*.txt);
  evidence/terminal/M16_S45_*; report/TRACEABILITY.md
- Metrics added: 60 rows P-WRITE-EPOCH-* and P-READ-WINDOW-* of the run (backend cupy, runner kaggle): 40 values, 20 UNSTABLE
- Decisions: A1 amendment (module file, no ADR); ISSUE-12 accepted limitation. Both decisions of the owner
- Issues: closed ISSUE-12 (c3d4e26), ISSUE-45 (99987e6), ISSUE-46 (c3d4e26); opened none
- Deviations from spec: the module says "Next: M18"; next_unit is M19 by instruction of the owner (calendar-bound).
  A3 is the syntax check only. The M07 notes section was not regenerated (4.P.6 stays marked STALE).
  The 26 session-table outcomes are tied to SEC-E5-PASS instead of the amendment (their run is local).
  The first answer of the owner arrived in the field of the ISSUE-12 question; both questions were asked again.
- Not verified: Overleaf compilation; the cause of the instability; anything about 65536 slots on the current code
- Commit: 99987e6 (ingest), c3d4e26 (M16), records a90039b
- Next: M19 S1 ; human action: none to start M19 (it has human gates of its own: guide approval, the submission)

## Session 46 — 2026-10-13 — M08 follow-up: PC runner kit and two jobs for it (ISSUE-18) — owner:Aditya
- Steps: not a module step. Unit named by the owner in the session request (status after: M08 stays DONE; next_unit M15)
- Did: the request arrived as a pasted block, so the agent asked whether it was the instruction and how to scope the
  session; answers: yes, and "kit now, M15 next session". ADR-025 records the third runner. Kit pc_runner/: SETUP.txt,
  RUN.txt, check_setup.py, run_job.py (VCLOAK_RUNNER=pc-<gpu> from nvidia-smi, refuses any other name), verify_result.py.
  Code: vcloak.runs accepts pc-<gpu>; run_ncu.py and gpu_entry.py start ncu by its resolved path (a .bat on Windows);
  bench/jobs/M08_ncu.json (the ncu step alone). Packed 20261013-224820_M00 and 20261013-224820_M08_ncu from 072ee8c.
- Result: nothing measured. Local suite 2142 passed, 1 skipped, 674 deselected (numpy backend).
- Evidence: runs/20261013-224907_M08_pc_runner_kit (pytest_all.txt, ruff.txt, check_*.txt, export_check.txt, kit_*.txt, jobs_sha256.txt)
- Metrics added: none
- Decisions: ADR-025 (decision of the owner, recorded by the agent)
- Issues: opened ISSUE-47 (GPU JOBS READY, PC runner); ISSUE-18 updated (OPEN)
- Deviations from spec: hard rule 2 and ai/GPU_RUNNER.md name Colab and Kaggle only (ADR-025). status is not
  BLOCKED_HUMAN although two jobs are pending, because the owner asked for M15 meanwhile. next_unit is M15, not the
  calendar-bound M19, by the same instruction. review/publication/ was untracked before the session and is left so.
- Not verified: the kit on any machine with a GPU; the Windows and WSL2 instructions; the download addresses in
  SETUP.txt (not fetched); that ncu works under WSL2; that the unit tests of job 1 pass on Windows (optional command)
- Commit: 072ee8c (kit and code), records in the next commit
- Next: M15 S1 ; human action: ISSUE-47 (run the two jobs on the PC) and its staleness decision


- GPU-JOB 20261013-224820_M00 ingested 2026-10-14 01:25: runner pc-rtx3050laptopgpu, gpu NVIDIA GeForce RTX 3050 Laptop GPU, session 20261014-001649, overall exit 0, runs 20261014-001653_M00_gpu_probe, 4 metrics indexed.

- GPU-JOB 20261013-224820_M08_ncu ingested 2026-10-14 01:25: runner pc-rtx3050laptopgpu, gpu NVIDIA GeForce RTX 3050 Laptop GPU, session 20261014-003925, overall exit 0, runs 20261014-003929_M08_ncu, 8 metrics indexed.

## Session 47 — 2026-10-14 — M08 follow-up: ingest of the two PC runner jobs (ISSUE-47, ISSUE-18) — owner:Aditya
- Steps: not a module step. The owner reported that the PC runner output was in the repository folder (pc_runner/,
  nsight/, nsight_dl/); ISSUE-47 says results are ingested first (status after: M08 stays DONE; next_unit M15)
- Did: the inbox was empty; the two results zips were in pc_runner/results/ and matched the SHA-256 of
  pc_runner/HANDOFF.md, so the agent copied them to gpujobs/inbox/ and ingested them, the probe first, without
  `--allow-stale`. nsight/, nsight_dl/ (Nsight Compute installer and extraction, about 1.8 GB), pc_runner/.pipcache/
  and pc_runner/.piptmp/ are now in .gitignore; nothing was deleted. Gates read by runs/20261014-012623_M08_pc_ingest_checks/gates.py.
- Result: both jobs overall exit 0 on runner pc-rtx3050laptopgpu (RTX 3050 Laptop GPU, cc 8.6, driver 610.88,
  CUDA 12090, CuPy 14.2.0, Windows 11, 16 logical CPUs). ncu: counters permitted, 7 of 8 metrics carry values, the
  planted-leak control shows divergence, the four audited kernels report 0 divergent branch targets. The exporter
  changes no file: every generated table still pins the Kaggle ncu run (NOT_MEASURED on the T4). The optional
  unit_tests command of the probe job exited 2 at collection (missing httpx, matplotlib on the PC).
- Evidence: runs/20261014-001653_M00_gpu_probe, runs/20261014-003929_M08_ncu (device runs); runs/20261014-012623_M08_pc_ingest_checks
  (gates.txt, pytest_all.txt 2142 passed 675 skipped, check_*.txt, export_check.txt, ruff.txt, manifests_valid.txt,
  job_*.txt); evidence/terminal/M08_S47_*, evidence/gpu/M08_pc_ncu_*, evidence/gpu/M00_pc_*
- Metrics added: 12 rows with runner pc-rtx3050laptopgpu, backend cupy: ENV-PEAK-BW, ENV-D2D-BW, ENV-MAX-LOG2N,
  ENV-VRAM-FREE (probe) and the 8 T-NCU-* rows (7 values, 1 NOT_MEASURED)
- Decisions: none taken by the agent. Two are left to the owner in ISSUE-48 (how the PC ncu result is reported;
  record_env.py for the PC probe)
- Issues: closed ISSUE-47 (555b4f5), ISSUE-18 (555b4f5); opened ISSUE-48
- Deviations from spec: the agent, not the human, moved the zips into the inbox (they were already in the repository
  folder and their hashes matched). record_env.py not run for the PC probe. No dashboard screenshot: web/ and
  results/ did not change. review/publication/ is still untracked and untouched. The generated obliviousness
  outputs were not regenerated (ISSUE-48).
- Not verified: why bitonic_pairs_global counts no branch target at all; what the `.avg` aggregate averages over;
  any size other than log2n 16; anything about the T4; G10 rerun (needs the PC). pc_runner/HANDOFF.md was written on
  the PC and is committed as received: its setup claims were not checked here, only its two SHA-256 values
- Commit: 555b4f5 (ingest, evidence), records in the next commit
- Next: M15 S1 ; human action: none to start M15; ISSUE-48 when convenient

## Session 48 — 2026-10-14 — M08 follow-up: ISSUE-48, how the PC ncu result is reported — owner:Aditya
- Steps: not a module step (M08 stays DONE; status after: next_unit M15). The owner answered ISSUE-48 in the session
  request: both proposals accepted, plus three instructions (control first; resolve bitonic_pairs_global from the
  SASS evidence held; state both platforms wherever ncu is reported) and the SETUP.txt packages.
- Did: `report_oblivious --ncu-second/--analysis` (a second runner gets its own table and paragraph, led by its
  positive control; a divergent 0 is reported only when the kernel's own uniform count is not zero, or when the SASS
  listing has no branch instruction); `report_security` and `export_results` state both platforms; new
  results/paper/ncu_second_table.tex; docs/RESULTS_ANALYSIS.md created with the generated block; 7 unit tests;
  httpx and matplotlib in pc_runner/SETUP.txt.
- Result: bitonic_pairs_global on the PC is NOT_MEASURED: its uniform and divergent counters are both 0 over its
  launches and the saved SASS listing of the kernel has branch instructions (one conditional), so the counter
  collected nothing; in the same run the hardware branch counter of that kernel is not zero while the instrumented
  one is. The reported statement covers 3 of the 4 audited kernels, after the control. T4 rows unchanged.
- Evidence: runs/20261014-014529_M08_issue48_report (sass_crosscheck.py/.txt, report_command.txt,
  report_oblivious.txt, report_security.txt, export.txt, export_check.txt, pytest_all.txt 2149 passed 675 skipped,
  check_*.txt, ruff.txt); evidence/terminal/M08_S48_*, evidence/gpu/M08_pc_ncu_divergence_reported.csv
- Metrics added: none. One row withdrawn to NOT_MEASURED: T-NCU-DIVERGENT-BITONIC-PAIRS-GLOBAL of
  runs/20261014-003929_M08_ncu (ANN-5; the run's own 0.0 stays in its summary.json)
- Decisions: those of the owner (ISSUE-48). By the agent: the cross-check counts every branch instruction that
  scripts/sass_check.py indexed (T-SASS-BRA), the stricter reading of "no branch instructions"
- Issues: closed ISSUE-48 (0856c6e)
- Deviations from spec: no screenshot: no view of the app shows this result (the dashboard is wired in M18), so
  terminal and GPU evidence only. The two security figure PDFs that the regeneration rewrote byte-for-byte
  differently were restored from git (same data). review/publication/ is still untracked and untouched.
- Not verified: why the instrumented counters missed bitonic_pairs_global; what `.avg` averages over; that the PC
  build of that kernel has the same branches as the sm_75 listing (it is another build of the same source);
  SETUP.txt on the PC
- Commit: 0856c6e (code, results, evidence), records in the next commit
- Next: M15 S1 ; human action: none

## Session 49 — 2026-10-14 — M15 S1: end-to-end load generator — owner:Divyansh
- Steps: S1 (status after: IN_PROGRESS, current_step S2). Same conversation as session 48: the owner asked for
  M15 to be started after ISSUE-48.
- Did: `vcloak.bench.e2e` (pairs, per-user Poisson schedule fixed by the seed, warm-up rule, statistics) and
  `bench/run_e2e.py` (one cell: starts the service as a child process, registers and logs in every user with its
  own DPoP key, open-loop sends, one reader per user, samples.csv and summary.json); ADR-026; 7 unit tests and
  an integration test of both modes against the real service.
- Result: both modes run end to end on the laptop with sessions on: every counted send acknowledged with 201
  and read back by the peer, both modes get the same schedule, warm-up sends recorded and not counted. These are
  numpy runs with the in-memory store: correctness of the generator only, no latency of them is a result.
- Evidence: runs/20261014-015841_M15_e2e_baseline_u10, runs/20261014-015857_M15_e2e_vcloak_u10 (local cells);
  runs/20261014-015940_M15_s1_checks (read_cells.py/.txt, pytest_all.txt 2158 passed 675 skipped, ruff.txt,
  check_*.txt, export_check.txt)
- Metrics added: none (no GPU run; `summary.json` offers no metric on the numpy backend)
- Decisions: ADR-026 (the generator starts the service and raises only the account rate limits: 5 registrations
  per address per hour cannot set up even 10 users). Samples are counted by scheduled time. Defaults proposed,
  not decided: ISSUE-49.
- Issues: opened ISSUE-49 (S2 parameters; reads at 1000 users exceed CAND_K with the default layout, by arithmetic)
- Deviations from spec: hard rule 5 (one unit per session): two units in one conversation, at the owner's
  explicit request, each with its own records and commits. No capture-evidence run: web/, results/ and the
  metrics index did not change in this unit. The module's human gate (AC power) does not apply to S1.
- Not verified: 100 and 1000 users; PostgreSQL; a CUDA device; the generator's own capacity at 200 messages/s;
  telemetry, CPU utilisation and DB size (S2). The token refresh path ran once by hand (limit forced), not in a test.
- Commit: 4fc9008 (code, tests, evidence), records in the next commit
- Next: M15 S2 (prep: job spec, telemetry, cell driver, pack) ; human action: ISSUE-49 if the proposals should change

## Session 50 — 2026-10-14 — M15 S2 (prep): the cells, telemetry, job packed; scope and load decisions recorded — owner:Divyansh
- Steps: S2 prep (status after: BLOCKED_HUMAN, current_step S2, gpu_job.pending 20261014-065041_M15)
- Did: recorded the owner's two decisions (ADR-027: two-party conversations only as declared scope; cells at
  10, 50 and 200 users) in ai/DECISIONS.md, the Amendments of M15, M20 and M22 and docs/REFINEMENTS.md (group
  conversations as future work). Built S2: `bench/run_e2e_cells.py` (2 modes x users x 2 repetitions, modes back
  to back, one PostgreSQL schema per cell), `vcloak.bench.hostload` (CPU utilisation, DB size, power source),
  NVML at 10 Hz around every cell, `bench/jobs/M15.json` (Kaggle, 4 vCPU), psutil in requirements-gpu.txt.
- Result: no measurement. The driver and both modes run locally against PostgreSQL on the numpy backend at 10,
  50 and 200 users: every counted send acknowledged and read back. Correctness only, no number of it is a result.
- Finding before packing: at the proposed 0.2 messages per user per second the 200-user schedule can exceed
  CAND_K (136 rows in one bucket-window, two buckets of 5 conversations); the owner chose 0.15 (bound 106).
  Arithmetic on the schedule, not a measurement.
- Evidence: runs/20261014-062714_M15_s2_checks (pytest_all.txt 2169 passed 675 skipped, ruff.txt, check_*.txt, export_check.txt,
  bucket_bound.py/.txt); runs/20261014-063452_M15_e2e_cells_quick and runs/20261014-063858_M15_e2e_cells_quick
  with their 6 cells; gpujobs/out/20261014-065041_M15
- Metrics added: none (no GPU run)
- Decisions: ADR-027, all three parts by the owner. By the agent: one schema per cell, dropped first; modes
  back to back, baseline first; CPU sampled at 2 Hz (the module gives no rate); samplers cover setup, warm-up
  and drain, `measured_unix` marks the interval; `runner_required: kaggle`, 4 vCPU; `stack_up` stops the job if
  PostgreSQL cannot be installed; cell run names shortened.
- Issues: closed ISSUE-49 (c64ec32); opened ISSUE-50 (GPU JOB READY)
- Deviations from spec: users 10/50/200 instead of 10/100/1000 (ADR-027). No design chapter exists yet (M22 not
  started), so the scope is in ADR-027 and an M22 amendment that Ch.3 must carry, not in a chapter. No anonymity
  figure exists either: the pairing is stated by the S6 table, its JSON (`mapping`) and section 4.S of the notes,
  pinned by tests/unit/test_bench_report_security.py; nothing had to change. Five local run dirs of this session
  (numpy, rate 0.2, never committed) were deleted: their names read as key-like to check_secrets and the rate
  was superseded; the same cells were re-run. psutil was installed in the local venv. No capture-evidence run:
  web/, results/ and the metrics index did not change. Commit by named paths, not `git add -A`:
  review/publication/ stays untracked as before.
- Not verified: anything on a CUDA device; runner_stack.py on Kaggle; whether the service and one generator
  process keep up with 200 users (the laptop numpy run did not answer the reads at the asked rate); the runtime
  of the job; NVML sampling (no NVML here: the code path is the M07 sampler).
- Commit: c64ec32 (code, tests, evidence, ADR), records in the next commit
- Next: M15 S2 ingest ; human action: ISSUE-50 (run job 20261014-065041_M15 on Kaggle, put the results in gpujobs/inbox/)

- GPU-JOB 20261014-065041_M15 ingested 2026-10-14 07:43: runner kaggle, gpu Tesla T4, session 20261014-013736, overall exit 0, runs 20261014-013858_M15_e2e_cells, 20261014-013859_M15_baseline_u10_r1, 20261014-014128_M15_vcloak_u10_r1, 20261014-014359_M15_baseline_u50_r1, 20261014-014635_M15_vcloak_u50_r1, 20261014-014912_M15_baseline_u200_r1, 20261014-015212_M15_vcloak_u200_r1, 20261014-015528_M15_baseline_u10_r2, 20261014-015757_M15_vcloak_u10_r2, 20261014-020026_M15_baseline_u50_r2, 20261014-020302_M15_vcloak_u50_r2, 20261014-020539_M15_baseline_u200_r2, 20261014-020839_M15_vcloak_u200_r2, 0 metrics indexed.

## Session 51 — 2026-10-14 — M15 S2 (ingest): the 12 end-to-end cells are in; 200 users ran at the generator's limit — owner:Divyansh
- Steps: S2 ingest (status after: IN_PROGRESS, current_step S3, gpu_job.pending null)
- Did: `python scripts/gpujob.py ingest` verified and ingested job 20261014-065041_M15 (Kaggle, Tesla T4, 4 vCPU,
  driver 580.178.04, runner session 20261014-013736; packed from c64ec32, manifests not dirty): 7 commands exit 0,
  13 run dirs (the driver and 12 cells). Read the cells against A1, A2 and A3 with
  runs/20261014-074636_M15_s2_ingest_checks/cell_reading.py (reads summaries, samples.csv, cpu.csv; writes no metric).
- Result: A1 one set of conditions and one environment over all 12 cells. A2 the same counted window in every
  cell (scheduled 20.01 s onwards; 169, 943 and 3660 counted sends at 10, 50 and 200 users). 10 and 50 users are
  clean in both modes. 200 users is not: the generator process was above one core in both modes, V-cloak
  acknowledged in seconds and lost one send per repetition, and the repetitions are more than 15 % apart
  (ISSUE-51). No epoch overflow in any cell; missed epochs in the V-cloak cells: 15, 1, 0, 1, 23, 19.
- Evidence: runs/20261014-013858_M15_e2e_cells (driver, cells.csv), the 12 cell dirs runs/20261014-01*_M15_* and
  runs/20261014-02*_M15_*, gpujobs/out/20261014-065041_M15 (result.json, logs); runs/20261014-074636_M15_s2_ingest_checks
  (cell_reading.txt, pytest_all.txt 2169 passed 1 skipped 674 deselected, ruff.txt, check_*.txt, export_check.txt)
- Metrics added: none. The E2E-* rows are S3 (percentiles, the UNSTABLE marks, throughput); the ingest indexed 0.
- Decisions: none by the agent beyond the default of ISSUE-51 (a), which changes no data and can be reversed.
- Issues: closed ISSUE-50 (29a77d7); opened ISSUE-51 (decision of the owner on the 200-user cells)
- Deviations from spec: S3 was not started in this session although the cells are in: the 200-user reading goes
  to the owner first (ADR-027), and S3 needs new code (throughput from completion times, see ISSUE-51). No
  capture-evidence run: web/, results/ and the metrics index did not change.
- Not verified: why V-cloak acknowledges in seconds at 200 users (generator, engine thread or both); the cause
  of the lost sends and of the one invalid_dpop_proof; why the V-cloak schema has 5 tables in two cells and 4 in
  the other four; GPU utilisation and power (telemetry is ingested, not yet read: S3). This run's image (driver
  580.178.04, CUDA 12090) is not the image of the `runner` block or of M07: no timing is compared across them.
- Commit: 29a77d7 (ingested runs, evidence), records in the next commit
- Next: M15 S3 (metrics from the 12 cells) ; human action: none required; ISSUE-51 if the default (a) should change
