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
