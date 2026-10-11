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
- Commit: HASH_PENDING
- Next: M08 S1 ; human action: none required (optional: decide on the ISSUE-15 re-measurement before M16)
