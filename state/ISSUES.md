# ISSUES (format: ai/LOGGING_AND_AUDIT.md §6; human actions use ai/PROTOCOL.md §7)

### ISSUE-1 [CLOSED a45088b] setup/bootstrap.ps1 failed to parse on Windows PowerShell 5.1
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-11 session 1
The kit script was UTF-8 without a BOM; PowerShell 5.1 read it as ANSI, turned the em-dashes into quote
characters and aborted before doing anything ("The term 'tick' is not recognized"). Fixed by adding a UTF-8 BOM
to the file (no other change). It then ran clean: .venv, packages, git init, identity. Teammates get the fix.

### ISSUE-2 [CLOSED 5cff14d] HUMAN ACTION REQUIRED — GPU JOB READY: M00 runner probe (job 20261011-014756_M00)
BLOCKS: M00   SEVERITY: high   OPENED: 2026-10-11 session 1
Why: the laptop has no GPU; M00 S6 needs one real run on a free Colab GPU to identify the runner (about 2 minutes).
File to upload: D:\PJT\vcloak\gpujobs\out\20261011-014756_M00\job.zip
Notebook:       D:\PJT\vcloak\colab\VCloak_GPU_Runner.ipynb
Do this (Google Colab; needs a Google account):
  1. Open https://colab.research.google.com -> File -> Upload notebook -> pick colab\VCloak_GPU_Runner.ipynb.
  2. Runtime -> Change runtime type -> Hardware accelerator: T4 GPU -> Save.   (the step everyone forgets)
  3. Run Cell 1. It must print a GPU name (e.g. Tesla T4). If it prints NO GPU, redo step 2.
  4. Run Cell 2. When the file picker appears, choose gpujobs\out\20261011-014756_M00\job.zip.
  5. Run Cell 3 and keep the tab open (about 2 minutes).
  6. Run Cell 4. results_20261011-014756_M00.zip downloads.
  7. Move that file into D:\PJT\vcloak\gpujobs\inbox\   (do not unzip or rename it).
If Colab refuses a GPU, use Kaggle: kaggle.com -> Create -> New Notebook -> File -> Import Notebook -> the same
  .ipynb; Settings -> Accelerator -> GPU T4 x2; + Add Input -> Upload -> job.zip as a dataset; in Cell 2 set
  KAGGLE_INPUT = "/kaggle/input/<your-dataset>/job.zip"; run all; download the results zip from the Output panel.
Bring back only the results zip. Do not commit or edit anything in the repo before the next session:
  a change to src/, kernels/, tests/, bench/ or scripts/ makes the result stale and it will be rejected.
Confirm by running: .venv\Scripts\python scripts\gpujob.py verify gpujobs\inbox\results_20261011-014756_M00.zip
Then type: continue
Resolved session 2: results zip delivered (Kaggle T4), verified and ingested; bundle in gpujobs/done/.

### ISSUE-3 [OPEN] Runner package set differs from requirements-gpu.txt
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-11 session 2
requirements-gpu.txt names cupy-cuda12x, but the Kaggle T4 runner already ships CuPy 14.0.1 on CUDA runtime 13.0
(driver 580.82.07, Python 3.13.15), so gpu_entry skipped both installs. The probe compiled and ran correctly on it.
Risk: a Colab session may ship a different CuPy/CUDA pair, and the file no longer describes what actually ran.
Proposed fix (M03 prep): make the requirement runtime-agnostic or record the installed wheel name in result.json;
keep comparing `cupy`/`cuda` in each manifest before mixing timings from different sessions.
Update session 10: the risk happened. The M05 job (session 20261011-141833) ran on a different Kaggle image:
driver 580.178.04, nvcc CUDA 12.8, CUDA runtime 12090, kernel 6.18.48, against 580.82.07 / CUDA 13.0 / 13000 /
6.6.122 for the M00, M03 and M04 jobs. Same Tesla T4 and CuPy 14.0.1. M05 has no timing, so nothing is affected yet;
M07 must take all timings it compares from one image (or re-run the M00 probe first) and state the image per metric.
Update session 12: the M06 job (20261011-215111_M06) ran on the same newer image as the M05 job (driver
580.178.04, CUDA runtime 12090, nvcc 12.8). Its smoke timings must not be compared with the M03/M04 ones. Still open.

### ISSUE-4 [CLOSED] M02 secrets scanner must allow-list the golden vectors
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-11 session 3
tests/golden/oracle_perm_n*.json hold base64 permutations and sha256 hex digests. They contain no key material
(tests/unit/test_oracle_golden.py asserts this), but `scripts/check_secrets.py` (M02 S6) is specified to flag any
32-byte hex/base64 run in tracked files, so it will flag every one of them.
Proposed fix (M02 S6): allow-list tests/golden/*.json by file hash, next to the RFC vectors. Also in M02 S7: set
IMPLEMENTED = True in vcloak.crypto.{chacha_ref,aead_ref} and run `python scripts/make_golden.py --check`; the
golden files must come out identical, since the byte formats do not change.
Resolved session 4: scripts/secrets_allowlist.json lists the golden files by file hash; IMPLEMENTED is True in both references and `make_golden.py --check` reports the three files identical.

### ISSUE-5 [CLOSED d91bfd6] Each GPU job's bundle_sha256 must be allow-listed for G4
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-11 session 4
`scripts/gpujob.py` writes a 64-hex `bundle_sha256` into job.json, result.json, pack logs and run manifests. It is
a content hash, not the SHA-256 of job.zip, so `scripts/check_secrets.py` cannot verify it and reports it as a
key-like run. The M00 job's digest was allow-listed by hand in session 4. Every later pack (M03 onwards) will make
G4 fail until its digest is allow-listed.
Workaround (any session that packs a job): run `python scripts/check_secrets.py`, copy the `id=` of the finding, then
`python scripts/check_secrets.py --allow <id> --reason "bundle_sha256 of GPU job <job id>"`.
Proposed fix (M03 prep session, owner of scripts/gpujob.py): have `gpujob.py pack` add that allow-list entry itself.
Resolved session 5: `gpujob.py pack` adds the digest to scripts/secrets_allowlist.json itself; that file is no longer bundled or part of the staleness check, so the write cannot invalidate the job (tests/unit/test_gpujob.py).

### ISSUE-6 [CLOSED 121dc0b] HUMAN ACTION REQUIRED — GPU JOB READY: M03 bitonic kernels (job 20261011-173759_M03)
BLOCKS: M03   SEVERITY: high   OPENED: 2026-10-11 session 5
Why: the laptop has no GPU and no nvcc. The bitonic kernels have only run as NumPy twins and through a g++ CPU
stand-in; M03 needs one real run to compile them with CUDA, compare them byte for byte with the oracle and the
simulator up to n = 2^24, run the race check and take the timing smoke (about 20 minutes on the runner).
File to upload: D:\PJT\vcloak\gpujobs\out\20261011-173759_M03\job.zip
Notebook:       D:\PJT\vcloak\colab\VCloak_GPU_Runner.ipynb
Do this (Google Colab; needs a Google account, nothing to install):
  1. Open https://colab.research.google.com -> File -> Upload notebook -> pick colab\VCloak_GPU_Runner.ipynb.
  2. Runtime -> Change runtime type -> Hardware accelerator: T4 GPU -> Save.   (the step everyone forgets)
  3. Run Cell 1. It must print a GPU name (e.g. Tesla T4). If it prints NO GPU, redo step 2.
  4. Run Cell 2. When the file picker appears, choose gpujobs\out\20261011-173759_M03\job.zip.
  5. Run Cell 3 and keep the tab open (about 20 minutes; the last command sorts 16 million records on the CPU too).
  6. Run Cell 4. results_20261011-173759_M03.zip downloads.
  7. Move that file into D:\PJT\vcloak\gpujobs\inbox\   (do not unzip or rename it).
Or use Kaggle, as for the M00 probe: kaggle.com -> Create -> New Notebook -> File -> Import Notebook -> the same
  .ipynb; Settings -> Accelerator -> GPU T4 x2; + Add Input -> Upload -> job.zip as a dataset; in Cell 2 set
  KAGGLE_INPUT = "/kaggle/input/<your-dataset>/job.zip"; run all; download the results zip from the Output panel.
Bring back only the results zip, even if a cell reports a failure: a failed run is still evidence and is fixed in
  the next session. Do not commit or edit anything in the repo before the next session: a change to src/,
  kernels/, tests/, bench/ or scripts/ makes the result stale and it will be rejected.
Confirm by running: .venv\Scripts\python scripts\gpujob.py verify gpujobs\inbox\results_20261011-173759_M03.zip
Then open a new session and type: continue
Resolved session 6: the human ran the job on Kaggle (Tesla T4, session 20261011-122243) and dropped the results zip
in gpujobs/inbox/; `gpujob.py ingest` verified it and all 5 commands exited 0 (runs/20261011-122303_M03_bitonic_smoke).

### ISSUE-7 [CLOSED 9ae9ba5] Telemetry during a timed section: 1 sample, taken at idle
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-11 session 6
Symptom: in runs/20261011-122303_M03_bitonic_smoke the manifest's start snapshot shows the SM clock at 900 MHz
(idle, util 6%) and the end snapshot 1590 MHz; telemetry.csv holds 1 sample, also from before the ramp. The gate
"SM clock dropped more than 15% during the run" therefore compares against an idle baseline and cannot detect a
throttle that happens inside the timed runs; only the CV speaks for stability. Harmless for the M03 smoke value,
not acceptable for M07 sweeps (ai/GPU_RUNNER.md §7).
Cause: `telemetry.Sampler` polls slower than the timed section lasts (30 sorts at 2^16 take about 20 ms), and the
start snapshot is taken before the warm-up.
Proposed fix (M07 prep, or the first module that reports timings): take a snapshot after the warm-up and one
after the last timed run, write both to summary.json, and apply the 15% gate to that pair in either direction.
Update session 7: the proposed fix is in bench/chacha_smoke.py (snapshots after the warm-up and after the last timed
run, 15% gate in either direction, both written to summary.json). Unverified until GPU job 20261011-183051_M04 is
ingested; bench/bitonic_smoke.py and the M07 sweeps still use the old scheme, so the issue stays open.
Update session 8: the new scheme worked in runs/20261011-134013_M04_chacha_smoke (after warm-up 810 MHz, after the
runs 840 MHz, +3.7%, 3 sampler rows). It also showed a second problem: the whole timed section is about 6 ms of
kernel time, so the T4 stayed at 810-840 MHz (util 3-6%) instead of the 1590 MHz seen under load in the M03 job. A
stable pair of snapshots therefore does not mean the GPU was at its working clock. For M07: besides porting the
snapshot pair to bench/bitonic_smoke.py and the sweeps, warm up until the SM clock stops rising (or for a fixed
wall time), record the clock with every metric, and treat a low-clock run as UNSTABLE. Still open.
Update session 13 (M07 prep, c40696b): `vcloak.bench.timing.warm_until_stable` warms a configuration up until the SM
clock has stopped rising (>= 10 launches and 0.5 s, at most 4 s), and `telemetry.sample` reads the clock after the
warm-up and after the last timed run without a subprocess; bench/run_kernels.py uses both, records the clock with
every metric, and repeats a low-clock configuration once after a ramp load. Changed from the proposal above: a clock
that is steady but still below 85% of the device maximum keeps its number and is labelled `LOW clock` instead of
UNSTABLE (see the Amendments note of M07). bench/bitonic_smoke.py keeps the old scheme: it is the M03 smoke and is
superseded by the M07 sweep. Unverified until GPU job 20261011-224124_M07 is ingested, so the issue stays open.
Closed session 14 (M07 ingest): the scheme worked on the T4. Every attempt of runs/20261011-213207_M07_kernel_sweep carries a snapshot
after the warm-up and one after the last timed run, the 15% rule fired in both directions (for example bitonic_global
at 2^21 and chacha_tags at 2^19 to 2^22), and telemetry.csv holds 2625 samples at 10 Hz. What the snapshots showed
(most of the sweep runs under the board's power limit, at a reduced clock) is ISSUE-15, not a telemetry problem.

### ISSUE-8 [CLOSED c7a7ac5] HUMAN ACTION REQUIRED — GPU JOB READY: M04 ChaCha20 kernels (job 20261011-183051_M04)
BLOCKS: M04   SEVERITY: high   OPENED: 2026-10-11 session 7
Why: the laptop has no GPU and no nvcc. The ChaCha20 kernels (tags, subkeys, bucket PRF) have only run as NumPy
twins and through a g++ CPU stand-in; M04 needs one real run to compile them with CUDA, check the RFC 8439 vector,
compare them byte for byte with the M02 reference and the simulator up to n = 2^24, and take the throughput smoke.
The time on the runner has not been measured; expect roughly as long as the M03 job (about 20 minutes).
File to upload: D:\PJT\vcloak\gpujobs\out\20261011-183051_M04\job.zip
Notebook:       D:\PJT\vcloak\colab\VCloak_GPU_Runner.ipynb
Do this (Kaggle, as for the M00 and M03 jobs):
  1. kaggle.com -> Create -> New Notebook -> File -> Import Notebook -> pick colab\VCloak_GPU_Runner.ipynb.
  2. Settings -> Accelerator -> GPU T4 x2.   (the step everyone forgets)
  3. + Add Input -> Upload -> gpujobs\out\20261011-183051_M04\job.zip as a dataset.
  4. In Cell 2 set KAGGLE_INPUT = "/kaggle/input/<your-dataset>/job.zip".
  5. Run Cell 1. It must print a GPU name (e.g. Tesla T4). If it prints NO GPU, redo step 2.
  6. Run the remaining cells and keep the tab open until the last one finishes.
  7. Download results_20261011-183051_M04.zip from the Output panel.
  8. Move that file into D:\PJT\vcloak\gpujobs\inbox\   (do not unzip or rename it).
Or use Google Colab: colab.research.google.com -> File -> Upload notebook -> the same .ipynb; Runtime -> Change
  runtime type -> T4 GPU -> Save; run Cell 1 (GPU name), Cell 2 (upload job.zip), Cell 3 (keep the tab open),
  Cell 4 (downloads the results zip).
Bring back only the results zip, even if a cell reports a failure: a failed run is still evidence and is fixed in
  the next session. Do not commit or edit anything in the repo before the next session: a change to src/,
  kernels/, tests/, bench/ or scripts/ makes the result stale and it will be rejected.
Confirm by running: .venv\Scripts\python scripts\gpujob.py verify gpujobs\inbox\results_20261011-183051_M04.zip
Then open a new session and type: continue
Resolved session 8: the human ran the job on Kaggle (Tesla T4, session 20261011-133942) and dropped the results zip
in gpujobs/inbox/; `gpujob.py ingest` verified it and all 6 commands exited 0 (runs/20261011-134013_M04_chacha_smoke).

### ISSUE-9 [CLOSED c2cefaa] HUMAN ACTION REQUIRED — GPU JOB READY: M05 AEAD, restore sort, compaction (job 20261011-193547_M05)
BLOCKS: M05   SEVERITY: high   OPENED: 2026-10-11 session 9
Why: the laptop has no GPU and no nvcc. The Poly1305 and seq_enc AEAD kernels (seal, open) and the restore and
compaction sorts have only run as NumPy twins and through a g++ CPU stand-in; M05 needs one real run to compile
them with CUDA, check the RFC 8439 Poly1305 and AEAD vectors on the device, and compare them byte for byte with the
reference, the oracle and the simulator up to n = 2^24. The job runs tests only (no timing).
The time on the runner has not been measured; the earlier jobs were planned at about 20 minutes and this one has
more tests at n = 2^24, so allow longer and keep the tab open.
File to upload: D:\PJT\vcloak\gpujobs\out\20261011-193547_M05\job.zip
Notebook:       D:\PJT\vcloak\colab\VCloak_GPU_Runner.ipynb
Do this (Kaggle, as for the M00, M03 and M04 jobs):
  1. kaggle.com -> Create -> New Notebook -> File -> Import Notebook -> pick colab\VCloak_GPU_Runner.ipynb.
  2. Settings -> Accelerator -> GPU T4 x2.   (the step everyone forgets)
  3. + Add Input -> Upload -> gpujobs\out\20261011-193547_M05\job.zip as a dataset.
  4. In Cell 2 set KAGGLE_INPUT = "/kaggle/input/<your-dataset>/job.zip".
  5. Run Cell 1. It must print a GPU name (e.g. Tesla T4). If it prints NO GPU, redo step 2.
  6. Run the remaining cells and keep the tab open until the last one finishes.
  7. Download results_20261011-193547_M05.zip from the Output panel.
  8. Move that file into D:\PJT\vcloak\gpujobs\inbox\   (do not unzip or rename it).
Or use Google Colab: colab.research.google.com -> File -> Upload notebook -> the same .ipynb; Runtime -> Change
  runtime type -> T4 GPU -> Save; run Cell 1 (GPU name), Cell 2 (upload job.zip), Cell 3 (keep the tab open),
  Cell 4 (downloads the results zip).
Bring back only the results zip, even if a cell reports a failure: a failed run is still evidence and is fixed in
  the next session. Do not commit or edit anything in the repo before the next session: a change to src/,
  kernels/, tests/, bench/ or scripts/ makes the result stale and it will be rejected.
Note: this job is the first whose tests import the `cryptography` package on the runner. gpu_entry installs it if
  the runner lacks it (it needs internet in the notebook: Kaggle Settings -> Internet -> On).
Confirm by running: .venv\Scripts\python scripts\gpujob.py verify gpujobs\inbox\results_20261011-193547_M05.zip
Then open a new session and type: continue
Resolved session 10: the human ran the job on Kaggle (Tesla T4, session 20261011-141833) and dropped the results zip
in gpujobs/inbox/; `gpujob.py ingest` verified it and all 6 commands exited 0 (gpujobs/out/20261011-193547_M05/logs,
gates in runs/20261011-213200_M05_ingest_audit/gates.txt). `cryptography` was already on the runner.

### ISSUE-10 [CLOSED 325a545] HUMAN ACTION REQUIRED — GPU JOB READY: M06 GPU engine (job 20261011-215111_M06)
BLOCKS: M06   SEVERITY: high   OPENED: 2026-10-11 session 11
Why: the laptop has no GPU. The engine (key store, write_epoch, reshuffle_window, read_window) has only run on the
NumPy twins. M06 needs one real run to execute it on CUDA, compare it byte for byte with the oracle and with the
simulator engine up to SLOTS = 2^24, and take the first pipeline timings (smoke, quick-tagged). The CuPy-only code
paths (the engine's stream, pinned transfers, CUDA events, the key upload and the memset) have never executed, so a
failing cell is possible; it is still evidence and is fixed in the next session.
The time on the runner has not been measured; allow about as long as the M05 job and keep the tab open.
File to upload: D:\PJT\vcloak\gpujobs\out\20261011-215111_M06\job.zip
Notebook:       D:\PJT\vcloak\colab\VCloak_GPU_Runner.ipynb
Do this (Kaggle, as for the M00, M03, M04 and M05 jobs):
  1. kaggle.com -> Create -> New Notebook -> File -> Import Notebook -> pick colab\VCloak_GPU_Runner.ipynb.
  2. Settings -> Accelerator -> GPU T4 x2.   (the step everyone forgets)
  3. + Add Input -> Upload -> gpujobs\out\20261011-215111_M06\job.zip as a dataset.
  4. In Cell 2 set KAGGLE_INPUT = "/kaggle/input/<your-dataset>/job.zip".
  5. Run Cell 1. It must print a GPU name (e.g. Tesla T4). If it prints NO GPU, redo step 2.
  6. Run the remaining cells and keep the tab open until the last one finishes.
  7. Download results_20261011-215111_M06.zip from the Output panel.
  8. Move that file into D:\PJT\vcloak\gpujobs\inbox\   (do not unzip or rename it).
Or use Google Colab: colab.research.google.com -> File -> Upload notebook -> the same .ipynb; Runtime -> Change
  runtime type -> T4 GPU -> Save; run Cell 1 (GPU name), Cell 2 (upload job.zip), Cell 3 (keep the tab open),
  Cell 4 (downloads the results zip).
Bring back only the results zip, even if a cell reports a failure. Do not commit or edit anything in the repo
  before the next session: a change to src/, kernels/, tests/, bench/ or scripts/ makes the result stale and it
  will be rejected.
No passphrase is needed: the job uses the fixed TEST key (`--dev`).
Confirm by running: .venv\Scripts\python scripts\gpujob.py verify gpujobs\inbox\results_20261011-215111_M06.zip
Then open a new session and type: continue
Closed session 12: the results zip was uploaded and ingested (overall exit 0, 7 commands); gates PASS in
runs/20261011-221434_M06_ingest_audit/gates.txt.

### ISSUE-11 [CLOSED 9ae9ba5] M06 smoke timings are UNSTABLE / taken at a low SM clock
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-11 session 12
Symptom: runs/20261011-163049_M06_pipeline_smoke_quick has status UNSTABLE. P-READ-WINDOW-MS-K128 had CV 0.106 and
0.119 on its two attempts (limit 0.10); P-WRITE-EPOCH-MS-S4096 needed its second attempt (CV 0.354, then 0.043).
In all five configs the SM clock was 585 MHz after the warm-up and after the runs (1590 MHz under load in the M03
job), so the clock gate says OK while the GPU never left its low clock. 15 runs per config (quick).
Cause (not verified): a read_window call is about 0.5 ms and a write at small SLOTS is mostly host work, so the
device is idle most of the time and the 2 s warm-up does not raise the clock. Same finding as ISSUE-7 (session 8).
Effect: the five P-* rows in METRICS_INDEX are smoke values (quick-tagged). Do not quote them as results or put
them in a figure; M07 replaces them.
Proposed fix (M07 prep): with the ISSUE-7 fix, warm up until the SM clock stops rising, record the clock with each
metric, >= 30 runs, and report a config that stays above the CV limit as UNSTABLE instead of indexing its median.
Update session 13 (M07 prep, c40696b): `bench/run_pipeline.py --full` takes 200 calls per configuration, repeats a
configuration whose CV of `total` is above 0.10 (or whose clock moved by more than 15%) once, and then records its
metrics as UNSTABLE instead of its median. The SM clock is recorded with every P-* metric but is not forced up: the
engine mostly waits for the host, so a low clock is its working condition. Unverified until job 20261011-224124_M07
is ingested.
Closed session 14 (M07 ingest): runs/20261011-215653_M07_pipeline replaces the smoke values (200 calls per configuration, quick: no).
read_window is stable at all seven K (largest CV of the indexed attempts 0.086). write_epoch at SLOTS 1024, 4096 and
16384 is UNSTABLE on both attempts and indexed as such (ISSUE-15). The SM clock stayed at 585 MHz through the whole
pipeline run, as in the smoke run; it is recorded with every P-* metric. The five quick-tagged smoke rows stay in
the index as history and are not results.

### ISSUE-12 [CLOSED c3d4e26] write_epoch is dominated by host work; at SLOTS 65536 the whole call is UNMEASURED under valid conditions since the row-id change (it missed EPOCH_MS before it)
BLOCKS: none (accepted limitation, decision of the owner in session 45: the whole call at 65536 slots is unmeasured under valid conditions for the current code; M15 gives no verdict for that size)   SEVERITY: high   OPENED: 2026-10-11 session 12
Symptom: in runs/20261011-163049_M06_pipeline_smoke_quick the `host` stage is 199.78 ms of a 208.11 ms median total
at SLOTS 65536 (9.64 of 10.84 ms at 4096; 0.51 of 1.57 ms at 64). The device stages together are about 8 ms at
65536 (d2h 5.7 ms, sort 0.88, compact 0.77, h2d 0.57). EPOCH_MS is 200.
Cause (not profiled): `host` is the engine's Python work between device stages: the payload gather (ADR-006), the
random bytes, and building one StoredRow object with a uuid per message. The runner CPU is a 4-vCPU Xeon at 2.0 GHz.
Caveats: one quick run, 15 calls, full epochs (n_real = SLOTS), 8-byte payload stand-ins, GPU at 585 MHz. It is
not a real-time verdict (p99 < EPOCH_MS is M07/M15).
Proposed fix: in M07, report the host stage separately from the device pipeline, so that GPU metrics are not
hidden by Python overhead, and profile it. If it stays the bottleneck, vectorise the row building (column arrays
instead of one object per row) before M10/M15; that changes engine.py, so it needs its own unit and a new GPU job.
Update session 13 (M07 prep, c40696b): the full pipeline mode reports `device` (sum of the device stages) and `host`
apart (P-WRITE-EPOCH-DEVICE-MS/-DEVICE-P99/-HOST-MS-S<slots>), evaluates the real-time gate for the whole call and
for the device part, and writes a cProfile of write_epoch at SLOTS 65536 to host_profile.txt. No engine change yet:
whether the row building must be vectorised is decided from the ingested numbers.
Update session 14 (M07 ingest, runs/20261011-215653_M07_pipeline, 200 calls, full epochs): confirmed on the T4 runner. At SLOTS 65536
P-WRITE-EPOCH-P99-S65536 is 279.5451 ms against EPOCH_MS 200, so the real-time gate FAILS for the whole call;
P-WRITE-EPOCH-DEVICE-P99-S65536 is 11.0996 ms, so the device part passes. P-WRITE-EPOCH-HOST-MS-S65536 is 233.7088 ms
of a median of 242.3974 ms. The gate passes at 64 to 16384 slots (the three middle sizes are UNSTABLE, ISSUE-15).
host_profile.txt (cProfile, three calls at 65536) puts most of the host time in `uuid.py __init__`, 196608 calls: one
uuid object per stored row. Largest device stage at 65536: d2h.
Fix (needs its own unit, before M15 gives the end-to-end verdict): build the stored rows as column arrays and
generate the row ids in one vectorised call instead of one `uuid` object per row; then re-measure write_epoch with a
new GPU job. That changes src/vcloak/gpu/engine.py, so every later job is packed from the new commit. Until then the
honest statement is: the GPU pipeline fits the epoch at 2^16 slots, the Python host path on this runner's CPU does not.
Update session 42 (prep, 59d622f): the fix is in. `vcloak.gpu.engine.row_ids` sets the version and variant bits of all
row ids on the entropy matrix at once and fills the `uuid.UUID` objects through their two slots, so `write_epoch` makes
no `uuid.UUID(...)` constructor call (pinned by tests/gpu/test_engine.py; the ids are equal to those of the constructor,
and the engine still equals the oracle at 64 to 65536 slots on the simulator: runs/20261013-163225_M07_issue12_prep_checks/g10_quick_rerun.txt).
What was NOT done: the rows are still one `StoredRow` object per message (the interface of ARCHITECTURE §4 and of the
repository, ADR-014, returns a list of them), so the host stage still grows with the batch. No timing exists yet: the
laptop has no GPU and a simulator time is not a result. Whether p99 < EPOCH_MS now holds at 65536 slots is what job
20261013-163732_M07_issue12 measures (ISSUE-44). Stays OPEN, and keeps blocking M15, until that job is ingested.
Update session 43 (ingest, 698dff2; runs/20261013-111612_M07_pipeline, job 20261013-163732_M07_issue12, 5 of 5 commands exit 0).
Text corrected in session 44 at the request of the owner: the first version of this update quoted the attempt
values of an UNSTABLE run and called the result "measured and failing". That was wrong by gpu-bench rule 5.
- All 12 configurations of this run are UNSTABLE (CV of the whole call above the limit 0.1 on both attempts), so
  its 60 indexed rows are not values (ANN-3 in METRICS_INDEX) and the run gives NO gate verdict at any size. State
  of the question: whether the whole call meets EPOCH_MS at 65536 slots after the row-id change is UNMEASURED under
  valid conditions. The raw attempts stay in the run dir and in runs/20261013-165216_M07_issue12_ingest_checks/gates.txt;
  no number from them is quoted here, in the notes or in the report. They point in the direction of a miss; a
  direction is not a result.
- What the run does establish (not timings): `uuid.py __init__` is no longer in host_profile.txt (196608 calls in
  the M07 profile), the engine tests pass on the device (154 passed) and write_epoch equals the oracle at every size
  (0 mismatches).
- What it cannot establish: a before/after of the fix. The M07 numbers came from Kaggle with 4 vCPU and CUDA 12090;
  this job ran on Colab with 2 vCPU and CUDA 13000 (ISSUE-3). The host stage is Python on the CPU of the runner, so
  the two runs differ in the thing being measured. Packing a job on another platform than its before-measurement
  was the defect; ADR-024 now forbids it.
- Cause of the instability: not profiled (the host stage and the telemetry thread of the bench share 2 vCPU).
- The generated M07 section of docs/REPORT_CH4_NOTES.md was not regenerated (`vcloak.bench.report` takes four runs
  of one runner session); its paragraph on the uuid constructor is marked STALE in place (session 44).
Update session 44 (decision of the owner, Aditya): option (a). The same measurement is packed again for Kaggle
(4 vCPU), job in ISSUE-45. It settles two things at once: whether 65536 slots miss EPOCH_MS on 4 vCPU or the Colab
result was a runner artifact, and a before/after for the row-id change on the platform of the M07 before-measurement.
Column arrays (b) are NOT started and the limitation (c) is NOT accepted yet. Internet is not needed for this job:
it has no `stack_up` step (that step belongs to the M14 jobs), and the Kaggle M07 run installed no package
(result.json of gpujobs/done/results_20261011-224124_M07.zip: requirements installed [], skipped all three); the check is
runs/20261013-171026_M16_prefixes/kaggle_internet_check.txt. Comparability still depends on the runner image: the
ingest must compare vCPU count, CUDA runtime and driver of the new run with those of session 20261011-213139 and say
so if they differ (ADR-024). A valid before/after exists only if the new run is not UNSTABLE.
Framing for docs/RESULTS_ANALYSIS.md once valid numbers exist (owner, session 44): the device part of write_epoch
against EPOCH_MS is the result of the contribution (the oblivious shuffle runs there) and is stated first; the
whole-call figure at 65536 slots is host-side row marshalling in Python on a free-tier cloud VM. State both, and
state which part is the oblivious shuffle. Numbers only from valid (not UNSTABLE) rows.
Update session 45 (ingest of job 20261013-173239_M07_issue12k; runs/20261013-121512_M07_pipeline, 5 of 5 commands exit 0;
reading in runs/20261013-174910_M07_issue12k_ingest_checks/gates.txt).
- Platform: the job ran on the platform AND the image of the M07 before-measurement (session 20261011-213139):
  Kaggle, Tesla T4, 4 vCPU, the same CPU model, CUDA 12090, driver 580.178.04, CuPy 14.0.1, the same Python and OS.
  ADR-024 is satisfied; nothing differs that would have to be stated beside the numbers.
- Result at 65536 slots: write_epoch is UNSTABLE on both attempts (CV of the whole call above the limit 0.1), so by
  gpu-bench rule 10 there is NO gate verdict and no value. The question "does the whole call meet EPOCH_MS at 65536
  slots after the row-id change" is still UNMEASURED under valid conditions, now on the right platform as well.
  The before/after of the row-id change is NOT_MEASURED: the before side is a valid row (P-WRITE-EPOCH-P99-S65536
  279.5451 ms, old code, FAIL of the whole call), the after side is not a value. No attempt of the new run is quoted.
- The Colab result was not only a runner artifact in this sense: on 4 vCPU the configuration is unstable too. What
  the instability comes from is not profiled.
- Also UNSTABLE in this run: write_epoch at 1024, 4096 and 16384 slots (the same three sizes as in the M07 run,
  ISSUE-15 item 3). Stable: write_epoch at 64 slots and read_window at all seven K (8 of 12 configurations; 40 of the
  60 indexed rows carry a value, 20 are UNSTABLE).
- What the run does establish (not timings): `uuid.py` does not appear in host_profile.txt, the engine tests pass on
  the device (154 passed) and write_epoch equals the oracle at every size (0 mismatches).
- Exports: nothing new is handed to the paper. pipeline_breakdown.dat and the two write_epoch figures stay held
  back; their reason text now says that the rerun is UNSTABLE (scripts/export_results.py, `--check` clean).
Decision for the owner (the agent did not choose): (b) column arrays in the engine and a new job; (c) accept the
limitation: the report states the device part against EPOCH_MS from valid rows and the whole call at 65536 slots as
unmeasured under valid conditions on a free-tier runner (old code: a stable miss); (d) one more run of the same job
on Kaggle, which may be UNSTABLE again. Until decided, M15 gives no verdict for 65536 slots.
Decision of the owner (session 45, the same day): (c), the limitation is ACCEPTED. No further job, no column arrays.
How it is stated from now on (M15, M20, M22, the paper): the device part of write_epoch against EPOCH_MS, from valid
rows only, is the result of the contribution and comes first. The whole call at 65536 slots is host-side row
marshalling in Python on a free-tier cloud VM: for the code before the row-id change it is a stable miss
(P-WRITE-EPOCH-P99-S65536 of runs/20261011-215653_M07_pipeline); for the current code it is unmeasured under valid
conditions (two runs, Colab 2 vCPU and Kaggle 4 vCPU, both UNSTABLE at that size). Never write that the current
code fits or misses the epoch at 65536 slots, never quote an attempt of an UNSTABLE run, and never present the two
runs as a before/after. M15 gives no verdict for that size and says why. Closed as an accepted limitation.

### ISSUE-13 [CLOSED 9ae9ba5] HUMAN ACTION REQUIRED — GPU JOB READY: M07 performance sweeps (job 20261011-224124_M07)
BLOCKS: M07   SEVERITY: high   OPENED: 2026-10-11 session 13
Why: the laptop has no GPU. M07 is the measurement module: kernel sweeps from 2^10 to 2^22, the CPU baselines taken
beside the GPU in the same runner session, the GPU/CPU crossover, and the pipeline breakdown with the real-time
gate. None of these numbers can be produced here. The CuPy-only paths of the two benchmark scripts have only run
against a NumPy stand-in for the device, so a failing cell is possible; it is still evidence and is fixed in the next
session.
GPU JOB READY — 20261011-224124_M07              (runtime not measured; plan for 40-90 min, most of it CPU baselines)
Use Kaggle for this one (the job is long, and Kaggle sessions do not disconnect when the tab is idle).
File to upload: D:\PJT\vcloak\gpujobs\out\20261011-224124_M07\job.zip
Notebook:       D:\PJT\vcloak\colab\VCloak_GPU_Runner.ipynb
Do this (Kaggle, as for the earlier jobs):
  1. kaggle.com -> Create -> New Notebook -> File -> Import Notebook -> pick colab\VCloak_GPU_Runner.ipynb.
  2. Settings -> Accelerator -> GPU T4 x2.   (the step everyone forgets)
  3. + Add Input -> Upload -> gpujobs\out\20261011-224124_M07\job.zip as a dataset. Kaggle unpacks it into a
     folder: that is fine.
  4. Nothing to type in Cell 2: leave KAGGLE_INPUT = "" . The cell finds the job under /kaggle/input and must
     print "Bundle verified". (Import the notebook again from the repo: Cell 2 changed on 2026-10-12.)
  5. Run Cell 1. It must print a GPU name (e.g. Tesla T4). If it prints NO GPU, redo step 2.
  6. Run the remaining cells and keep the tab open until the last one finishes. Do not start anything else in
     that notebook while it runs: the CPU baselines are timed on the same machine.
  7. Download results_20261011-224124_M07.zip from the Output panel.
  8. Move that file into D:\PJT\vcloak\gpujobs\inbox\   (do not unzip or rename it).
Or use Google Colab: colab.research.google.com -> File -> Upload notebook -> the same .ipynb; Runtime -> Change
  runtime type -> T4 GPU -> Save; run Cell 1 (GPU name), Cell 2 (upload job.zip), Cell 3 (keep the tab open and
  active: a free Colab session can disconnect during a long job), Cell 4 (downloads the results zip).
Bring back only the results zip, even if a cell reports a failure. Do not commit or edit anything in the repo
  before the next session: a change to src/, kernels/, tests/, bench/ or scripts/ makes the result stale and it
  will be rejected.
No passphrase is needed: the job uses fixed TEST keys.
Confirm by running: .venv\Scripts\python scripts\gpujob.py verify gpujobs\inbox\results_20261011-224124_M07.zip
Then open a new session and type: continue
Update 2026-10-12 (reported by the human): Kaggle unpacks an uploaded job.zip, so the path
/kaggle/input/<dataset>/job.zip that steps 3-4 used to name does not exist and Cell 2 failed. Fixed in
colab/VCloak_GPU_Runner.ipynb: Cell 2 searches /kaggle/input for an unpacked bundle (the folder with job.json and
gpu_entry.py) or a zip, copies it to /kaggle/working, and recomputes the bundle content hash against job.json.
Checked on the laptop against this job.zip in the three layouts (unpacked, unpacked one level deeper next to an
older job, kept as a zip) and with a damaged file (refused). The job itself is unchanged: the notebook is not part
of the bundle, so job 20261011-224124_M07 and its job.zip stay valid. Not checked on Kaggle itself.
Closed session 14: results_20261011-224124_M07.zip was in gpujobs/inbox/, verified (job id, bundle sha, git sha
c40696b) and ingested: overall exit 0, 9 commands, 4 run dirs, 213 metric rows. Gates PASS in
runs/20261012-033804_M07_ingest_audit/gates.txt. Cell 2 of the notebook found the job on Kaggle (the human's run
completed), which is the first check of the 2026-10-12 notebook change on Kaggle itself.

### ISSUE-14 [OPEN] K-BITONIC-BW-PCT is above 100% of the theoretical peak at 2^17: the bytes-moved model breaks below 2^18
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-12 session 14
Symptom: in runs/20261011-213207_M07_kernel_sweep K-BITONIC-BW-PCT-2^17 is 167.539 % (global-only variant, CV 0.036), which memory traffic cannot
reach. The time per launch (median / rounds, runs/20261012-033804_M07_ingest_audit/gates.txt) is flat at about 12 microseconds from 2^10 to 2^17 and
then jumps to 55.8 at 2^18, after which it doubles with n. From 2^18 to 2^22 the metric is between 70.499 and 73.717 %.
Cause: NOT MEASURED. Two candidates, not told apart by this job: (a) up to 2^17 the 24-byte records (about 3 MB)
are served from the GPU's on-chip cache, so the "every stage moves all n records through device memory" assumption
of ai/GPU_GUIDE.md section 5 is false there; (b) up to 2^17 the sort is bound by the launch rate, so the time
measures launch overhead and not memory traffic. Both make the percentage meaningless below 2^18.
Effect: the values for 2^10 to 2^17 are indexed as measured (they are what the formula gives) but must not be
quoted as bandwidth utilisation. docs/REPORT_CH4_NOTES.md says so, and fig_bandwidth_pct draws the 100% line.
Proposed fix: answer "what fraction of peak" with the 2^18 to 2^22 range only. If M08 gets Nsight counters on the
runner (`ncu_counters_permitted` is still unknown), read the L2 hit rate of one global launch at 2^17 and at 2^18.

### ISSUE-15 [OPEN] M07: 45 of 78 kernel configurations and 3 of 5 write_epoch sizes are UNSTABLE on the shared T4
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-12 session 14
Symptom: 65 of the 213 M07 metric rows are UNSTABLE, among them three IDs the module lists as headline metrics:
K-AEADOPEN-ROWS-S, K-BUCKETPRF-ROWS-S (in addition) and X-CROSSOVER-N. bucket_prf is unstable at every n, aead_open at
12 of 13, chacha_tags at 11 of 13; the bitonic variants at 2 to 4 of 13 (runs/20261012-033804_M07_ingest_audit/gates.txt lists every point).
Cause, read from the attempts in summary.json (not a separate experiment):
  1. Kernels below about 0.1 ms (ChaCha, AEAD open and the PRF up to about 2^17; fused bitonic at 2^10 and 2^12):
     CV 0.25 to 0.55 on both attempts. One launch is as short as the jitter of a launch.
  2. Large n: the SM clock moved by more than 15% inside the timed runs. telemetry.csv has a non-zero
     throttle-reasons mask (value 4) in 2049 of 2625 samples, power at the 70 W limit and the temperature rising
     from 50 to 77 C over the sweep, which lasted about five minutes.
  3. write_epoch at 1024 to 16384 slots: CV of the whole call 0.18 to 0.57, and the host stage is most of the call
     (ISSUE-12).
Effect: the unstable cells are UNSTABLE in the index, hollow in the figures and flagged in the CSV tables; nothing
was dropped. The speed-ups at 2^16 and 2^20 and the bitonic series from 2^13 to 2^19 are stable. M16 would export
the table with these holes. The crossover statement itself is not in doubt (the GPU is faster at every compared n,
smallest ratio 8.93 at 2^10), only its 2^10 input is noisy.
Proposed fix (an optional re-measurement job, one prep session and one runner session; the human decides whether
it is worth a GPU session before M16): time batches of launches for any kernel whose single launch is under 0.1 ms
and divide; run the large-n configurations after a load that has brought the clock to its power-limited steady
state, so that the clock no longer moves inside the timed runs; label that state in the metric note as now. Keep
this session's numbers; index the new session separately and never merge the two in one figure.
Update session 43: the pipeline run of job 20261013-163732_M07_issue12 (Colab, 2 vCPU, runs/20261013-111612_M07_pipeline) is UNSTABLE in
12 of 12 configurations (write_epoch at all five sizes, read_window at all seven K), CV of the whole call 0.137 to
1.793 after two attempts, SM clock steady at 585 MHz (LOW), throttle-reasons mask 0 at 65536 slots. Its 60 rows
are UNSTABLE in the index (ANN-3). A free 2-vCPU runner did not give one stable pipeline row.

### ISSUE-16 [CLOSED 7c31c24] HUMAN ACTION REQUIRED — GPU JOB READY: M08 obliviousness audit (job 20261012-041010_M08)
BLOCKS: M08   SEVERITY: high   OPENED: 2026-10-12 session 15
Why: the laptop has no GPU. M08 asks whether GPU execution time or control flow depends on secret data: dudect
timing tests, the SASS branch listing (nvcc, cuobjdump) and the Nsight Compute divergence counters. None of it can
run here. The CuPy-only paths of the three new scripts have only run against a NumPy stand-in for the device, and
the SASS and ncu parsers only against hand-written samples of the tools' output, so a failing cell is possible; it
is still evidence and is fixed in the next session.
GPU JOB READY — 20261012-041010_M08              (runtime not measured; plan for 1 to 2 hours, most of it the write_epoch dudect)
Use Kaggle for this one (the job is long, and Kaggle sessions do not disconnect when the tab is idle).
File to upload: D:\PJT\vcloak\gpujobs\out\20261012-041010_M08\job.zip
Notebook:       D:\PJT\vcloak\colab\VCloak_GPU_Runner.ipynb
Do this (Kaggle, as for the earlier jobs):
  1. kaggle.com -> Create -> New Notebook -> File -> Import Notebook -> pick colab\VCloak_GPU_Runner.ipynb.
  2. Settings -> Accelerator -> GPU T4 x2.   (the step everyone forgets)
  3. + Add Input -> Upload -> gpujobs\out\20261012-041010_M08\job.zip as a dataset. Kaggle unpacks it into a
     folder: that is fine.
  4. Nothing to type in Cell 2: leave KAGGLE_INPUT = "" . The cell finds the job under /kaggle/input and must
     print "Bundle verified".
  5. Run Cell 1. It must print a GPU name (e.g. Tesla T4). If it prints NO GPU, redo step 2.
  6. Run the remaining cells and keep the tab open until the last one finishes. The long cell prints nothing
     while a command runs (the output of each command appears when it ends): that is normal. Do not start anything
     else in that notebook while it runs: the job measures small timing differences.
  7. Download results_20261012-041010_M08.zip from the Output panel.
  8. Move that file into D:\PJT\vcloak\gpujobs\inbox\   (do not unzip or rename it).
Or use Google Colab: colab.research.google.com -> File -> Upload notebook -> the same .ipynb; Runtime -> Change
  runtime type -> T4 GPU -> Save; run Cell 1 (GPU name), Cell 2 (upload job.zip), Cell 3 (keep the tab open and
  active: a free Colab session can disconnect during a long job), Cell 4 (downloads the results zip).
Bring back only the results zip, even if a cell reports a failure. Do not commit or edit anything in the repo
  before the next session: a change to src/, kernels/, tests/, bench/ or scripts/ makes the result stale and it
  will be rejected.
No passphrase is needed: the job uses fixed TEST keys.
Things that may come back as NOT_MEASURED and are not your fault: the Nsight counters (shared containers usually
  refuse them, ERR_NVGPUCTRPERM) and the SASS listing if the runner has no cuobjdump. Both are recorded as such.
Confirm by running: .venv\Scripts\python scripts\gpujob.py verify gpujobs\inbox\results_20261012-041010_M08.zip
Then open a new session and type: continue
Closed 2026-10-12 session 16: the human ran the job on Kaggle (session 20261012-031230, Tesla T4) and the results
zip was ingested; all 8 commands exit 0, git sha and bundle sha match (runs/20261012-093714_M08_ingest_audit/gates.txt).

### ISSUE-17 [CLOSED 44d7ff5] M08 dudect: three target series FAIL at N = 100000 (aead_conv, write_epoch whole call, aead_tag)
BLOCKS: M14   SEVERITY: high   OPENED: 2026-10-12 session 16
Finding (job 20261012-041010_M08, runner session 20261012-031230, Tesla T4, threshold 4.5; all values from
runs/20261012-031331_M08_dudect/summary.json and dudect_<target>.json, recomputed from the raw npz in runs/20261012-093714_M08_ingest_audit/gates.txt):
- aead_conv (AEAD open, every row matches q vs no row matches q): max abs(t) 11.6369 (T-DUDECT-MAXT-AEAD-CONV), raw
  t -8.684; class means 0.164110 ms and 0.164602 ms; the t of every crop has the same sign and the t-curve grows
  steadily with N (results/oblivious/dudect_aead_conv.png): a small shift of the whole distribution.
- write_epoch, whole call (fixed vs random contents): max abs(t) 8.2776 (T-DUDECT-MAXT-WRITE-EPOCH-CALL), raw t
  -2.215; class means 4.193689 ms and 4.228817 ms. The device-stage series of the same calls PASSES (2.7559).
- aead_tag (all tags valid vs all invalid): max abs(t) 6.2415 (T-DUDECT-MAXT-AEAD-TAG) at crop 8; raw t -2.412; class
  means 0.173499 ms and 0.173728 ms. Only the lower crops exceed the threshold: the weakest of the three.
What is established: the harness detects the planted leak (376.9125, quick) and does not separate identical classes
(null control 2.0786 at full N); outputs were correct in every run (0 mismatches); the nvcc listing of
aead_open_seq has 3 conditional branches, all on the thread id, n and the ChaCha round counter (ISSUE-19 for the
limits of that listing). So a timing difference between the classes was measured, and the kernel has no branch
on the data.
What is NOT established: the cause. Nothing below has been tested; these are hypotheses.
- H1 (harness staging, aead_conv): class 0 always uploads the same host array, class 1 one of a pool of 64 arrays.
  The host cache and TLB state after the upload differ between the classes, and the timed window (start event,
  Python launch path of gpu_open_and_key, kernel, end event) contains host work.
- H2 (harness staging, aead_tag): class 1 uploads an array the host has just written, class 0 one it has only read.
- H3 (device): the time of the kernel or of its memory traffic depends on the data (operand values, the values
  stored to out_hi/out_lo) without any branch.
- H4 (write_epoch whole call): the host stage of the engine is Python working on the submissions; it is not
  constant time, and class 0 rebuilds its batch from long-lived Python ints while class 1 uses freshly created ones.
- All three failing series ran with the SM clock at 585 MHz of 1590 (LOW); so did the passing write_epoch device series.
Proposed fix (one prep session and one runner session; `fix ISSUE-17`):
1. Symmetric staging: both classes drawn from pools of the same size, staged on the device before the run and
   selected by a device-to-device copy, so that the host does the same work on the same kind of memory for both.
2. An AEAD null control with the old asymmetric staging (one fixed buffer vs a pool of 64 inputs of the SAME class):
   a FAIL there convicts the harness (H1/H2), a PASS leaves H3.
3. Kernel-only window: r > 1 launches with the outputs preallocated, to shrink the share of host launch code.
4. Replication: a second seed and the two class roles swapped, for every failing target.
5. write_epoch whole call: a null control with identical contents rebuilt from fresh objects in both classes (H4);
   re-measure after ISSUE-12 has vectorised the host row building. Whether whole-call host timing is inside the
   threat model is a decision for the team (an ADR), not something this job can settle.
Until then: M14 must not claim that AEAD open or the whole write path is timing-independent. The FAILs stay in
the index, in results/oblivious/summary_table.csv and in docs/REPORT_CH4_NOTES.md section 4.O.3.
Prep done, session 20 (commit 3671fac; nothing measured, the backend was numpy): job 20261012-113437_M08_issue17 is packed (ISSUE-24).
`bench/run_dudect.py --targets issue17` runs the three failing targets again plus 11 diagnostics; seed 9 repeats 12
of the 14 (`issue17_rep`). How to read the result in the ingest session (threshold 4.5; a reading, not a proof):
- aead_conv_null / aead_tag_null / write_epoch_null / write_epoch_age FAIL: the staging alone separates two classes
  with the same contents, so the M08 FAIL of that target does not show a data dependence (H1 / H2 / H4).
- aead_conv_swap, aead_tag_swap: compare the sign of the raw t with the original. Same sign = the difference
  follows the staging role (fixed array vs pool / fresh array); opposite sign = it follows the contents.
- *_sym and *_kernel PASS while the original FAILS again: harness staging. *_sym or *_kernel FAIL: H3 stays open
  (the device time depends on the data without a branch) and the issue stays open with that finding.
- write_epoch_fresh is the fixed-vs-random comparison without the staging; its call_ms series decides H4.
- The originals must FAIL again (seed 8 and seed 9) for any of this to explain them; if they PASS now, the M08
  FAIL was not reproduced and that is the finding. The full-N control_null of each run must PASS, or the run is void.
Proposed step 3 was built as r = 8 with preallocated outputs (`gpu_open_and_key(..., out=)`); step 5's re-measure
after ISSUE-12 and the ADR on whole-call host timing are not part of this job.
Result, session 21 (job 20261012-113437_M08_issue17, runner session 20261012-061138, Tesla T4, N = 100000 per class,
threshold 4.5; all values from runs/20261012-061420_M08_dudect_issue17_s8 (seed 8) and runs/20261012-080629_M08_dudect_issue17_s9
(seed 9), every max abs(t) recomputed from the raw npz in runs/20261012-150500_M08_issue17_ingest/gates.txt, 106 gates PASS):
- The runs are valid: control_null PASS at full N (1.6126, 1.2530), planted leak detected (401.9489, quick), 0 mismatches.
- The M08 finding is reproduced in a second runner session: aead_conv FAIL 30.8131 / 28.2772, aead_tag FAIL 51.4940 /
  35.6716, write_epoch whole call FAIL 29.6309 / 8.5822 (seed 8 / seed 9).
- aead_conv and aead_tag: the same-contents controls FAIL as strongly as the originals (aead_conv_null 43.1742 / 30.1696,
  aead_tag_null 63.0436 / 50.8492); with the contents exchanged the raw t keeps its sign (aead_conv_swap -5.446 / -9.828
  against -6.177 / -7.364; aead_tag_swap -13.015 / -10.323 against -14.983 / -9.918), so the slower class is the staging
  role (pool, or freshly written array), not the contents; with symmetric staging the content comparison PASSES
  (aead_conv_sym 2.4044 / 1.3480, aead_conv_kernel 2.9037 / 1.8673, aead_tag_sym 1.5629 / 3.8937, aead_tag_kernel
  1.5075 / 2.3929). Reading: H1 and H2 are supported, the two AEAD FAILs are made by the harness staging, and no
  dependence of the AEAD-open time on the contents was detected. H3 is not excluded below the resolution of the
  test: the raw test of the *_sym and *_kernel series would reach 4.5 at a mean shift of about 0.19 to 0.29
  microseconds (column raw_shift_at_4.5_ns of gates.txt); the shift between the classes in the failing series is 0.27 to 0.72.
- write_epoch whole call: the same-contents controls FAIL (write_epoch_null 12.7431, write_epoch_age 12.1795, seed 8
  only) and the fixed-vs-random comparison without the staging PASSES (write_epoch_fresh call_ms 1.7015 / 1.3865).
  Reading: H4 is supported, the whole-call FAIL follows the build order and the age of the Python objects.
- New, not covered by the reading rules: two device-stage series FAIL at seed 8 (ISSUE-25).
- Limits: the staging and the SM clock change together (every failing series ran at 585 MHz, *_sym at 1425 to 1560 MHz,
  *_kernel at 1140 to 1245 MHz), so this job does not separate the two; one GPU model, two runner sessions; the
  readings are the rules written above, not a proof.
Still open, so the issue is not closed:
1. results/oblivious/summary_table.csv and docs/REPORT_CH4_NOTES.md 4.O.3 still show only the S2 targets, whose AEAD
   staging separates identical contents. A unit must make `report_oblivious` show the diagnostics beside them (or make
   the symmetric staging the S2 staging and measure again). The FAILs are never removed from the table.
2. The ADR on whole-call host timing (is the host Python of write_epoch inside the threat model?) is a decision of the
   team. It is needed before M14, not before M11 to M13.
3. ISSUE-25 (measured per stage in session 31: still open, see its result).
What M14 may write until then: with symmetric staging no timing difference between the classes was detected for AEAD
open at N = 100000 per class in two seeds, and the FAILs of the S2 staging are reproduced with identical contents. It
must not write that AEAD open is constant time, and nothing about the write path beyond the measured series.
Update 2026-10-13 session 32: point 2 is decided by the human and recorded as ADR-023. The timing of the host
orchestration is outside the threat model (a dump carries no timing; a live compromised server is excluded by
PROJECT_BRIEF §3) and P3 is claimed for the kernels only. The whole-call FAIL stays in every table as measured and is
listed as a limitation; it does not block M14 by itself any more. Points 1 and 3 are still open, so the issue is.
Update 2026-10-13 session 34: point 3 is closed (ISSUE-25 closed by the kernel-only job, see its result). Point 1
is the only open point: the summary table and section 4.O.3 must show the ISSUE-17 diagnostics beside the S2
targets. It is a local unit (no GPU job) and it still BLOCKS M14: `fix ISSUE-17` comes before M14 S1.
Closed 2026-10-13 session 35 (point 1; nothing measured, the tables were regenerated from the ingested runs):
`python -m vcloak.bench.report_oblivious --diagnostics <seed runs> --issue-diagnostics ISSUE-17` now writes
- section 4.O.3 of docs/REPORT_CH4_NOTES.md with the sub-section "Diagnostics of the failing series": the three
  failing S2 series, the same targets measured again and every diagnostic of seeds 8 and 9, one row per series
  (38 rows), with the reading of the rules above applied to the copied verdicts;
- results/oblivious/staging_diagnostics.csv (the same 38 rows) and 34 diagnostic rows appended to
  results/oblivious/summary_table.csv. The 9 rows of S2 are byte-identical to before; the three S2 FAILs and the
  18 FAILs of the diagnostic job are in the tables (runs/20261013-091541_M08_issue17_table/gates.txt, 49 PASS 0 FAIL).
The second way of point 1 (make the symmetric staging the S2 staging and measure again) was NOT taken: no GPU job.
What M14 may write is unchanged from the result of session 21 above: with symmetric staging no dependence of the
AEAD-open time on the contents was detected at N 100000 per class in two seeds, on one T4; the S2 FAILs are
reproduced with identical contents. Never "constant time". Limits that stay: for aead_conv and aead_tag the
staging and the SM clock change together (585 MHz against 1140 to 1560 MHz), one GPU model, readings are rules,
not proofs; the whole-call FAIL is host timing (ADR-023, a limitation); ISSUE-36 for the kernel-only window.

### ISSUE-18 [CLOSED 555b4f5] M08 ncu: the runner refuses the GPU performance counters (ERR_NVGPUCTRPERM); divergence is NOT_MEASURED
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-12 session 16
`ncu --query-metrics` and `ncu --csv --section SourceCounters` both stop with ERR_NVGPUCTRPERM on the Kaggle T4
(runs/20261012-040027_M08_ncu/ncu_query_metrics.txt, ncu_profile_raw.txt; ncu 2025.1.1.0). The eight
T-NCU-BRANCHEFF-* / T-NCU-DIVERGENT-* rows are NOT_MEASURED with that reason. The ncu CSV parser has therefore
still only seen hand-written samples.
Optional human action (nothing is blocked; A4 accepts NOT_MEASURED with the reason). The counters are a setting of
the machine that owns the GPU, and a Kaggle container cannot change it. They could be measured on:
- a Linux machine with an NVIDIA GPU where you are administrator: run the job as root, or let the administrator set
  the driver option NVreg_RestrictProfilingToAdminUsers=0 (file under /etc/modprobe.d, then reload the driver);
- a Windows machine with an NVIDIA GPU: NVIDIA Control Panel -> Desktop -> Enable Developer Settings, then
  Developer -> Manage GPU Performance Counters -> allow access to all users;
- Google Colab: not tried; it may refuse in the same way.
These steps are the ones NVIDIA documents (https://developer.nvidia.com/ERR_NVGPUCTRPERM) and have not been tried
in this project. If no such machine exists, the rows stay NOT_MEASURED and the static SASS reading (16 of 16
conditional branches public, no BSSY/BSYNC) is the only divergence evidence; say so in the report.
Update 2026-10-13 session 33 (the human asked whether this is cheap, so that the ISSUE-25 fallback has a second
independent leg beside the SASS reading and E3; nothing tried, nothing measured):
- Not cheap from this repository alone. Kaggle refused the counters and the container cannot change that setting.
- The one cheap attempt is Colab: a job of a few minutes that runs `ncu --query-metrics` and one profiled launch.
  Whether Colab permits the counters is unknown (never tried here). It needs a new job spec under bench/, so it
  can only be packed AFTER job 20261013-005946_M08_issue25k is ingested (a change there makes that result stale).
- Otherwise it needs a machine with an NVIDIA GPU and administrator rights (the steps above).
- Proposed order: ingest the ISSUE-25 job first; if its result is unusable (rule f or h), try the Colab ncu job
  before M14; if it is usable, this stays optional. The human decides at that handoff.
Update 2026-10-13 session 46 (decision of the owner, ADR-025): a PC with a discrete NVIDIA GPU is the third runner.
The ncu step alone is packed for it as job 20261013-224820_M08_ncu (ISSUE-47). Nothing is measured yet. A result
from the PC describes the nvrtc code on THAT GPU model, not on the T4 of the SASS listing: it is reported with its
own provenance and never as a T4 value (ADR-024). This issue closes when that job is ingested with counters that
carry values and a planted-leak control that shows divergence; a refusal on the PC leaves it NOT_MEASURED.
Closed 2026-10-14 session 47: job 20261013-224820_M08_ncu ran on the PC runner pc-rtx3050laptopgpu (RTX 3050 Laptop
GPU, cc 8.6, driver 610.88, Windows 11, Nsight Compute 2026.3.1.0) and is ingested as runs/20261014-003929_M08_ncu.
The closing condition is met (runs/20261014-012623_M08_pc_ingest_checks/gates.txt): the counters carry values (7 of 8 metrics; reason none) and the
planted-leak control shows divergence. The four audited kernels report 0 divergent branch targets. On the Kaggle T4
the rows of runs/20261012-040027_M08_ncu stay NOT_MEASURED: the PC result describes the nvrtc code for cc 8.6 on
that GPU, not the T4. How it is reported, and its caveats: ISSUE-48.

### ISSUE-19 [OPEN] M08 SASS: sass_check.py labels every conditional branch DATA; no listing of the nvrtc code that runs
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-12 session 16
1. The trace of the checker is static and flow-insensitive, so a register that once held a loaded value and is later
   reused as a loop counter (R25 in bitonic_shared, R29 in bitonic_shared_full) taints the predicate: 16 of 16
   conditional branches are reported DATA, 0 public (runs/20261012-040020_M08_sass/sass_*_branches.txt). A3 is met by
   the manual reading in bench/sass_explained.json, which report_oblivious checks against the listing instruction
   by instruction; the checker is not usable as an automatic gate. Fix: follow the last definition before the
   branch in address order (reaching definitions per basic block) and re-run `sass_check.py --listing` on the saved
   listings, which needs no GPU.
2. The listing is the nvcc build (nvcc 12.8, -arch=sm_75). CuPy runs an nvrtc build of the same source, and the job
   could not list it ("neither cuobjdump nor nvdisasm produced a listing"). The two compilers may emit different
   code. Fix in a later GPU job: save the cubin that CuPy caches, or build with the nvcc backend of CuPy for the audit.

### ISSUE-20 [CLOSED 28c3080] M09: the development database is a native PostgreSQL 17rc1 cluster; docker-compose.yml (postgres:16) was never started
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-12 session 17
1. The laptop has no Docker and the installed PostgreSQL 17 service asks for a password the agent does not have, so
   M09 runs on a private cluster started by `python scripts/pgdev.py up` (server 17rc1, a release candidate). ADR-008
   names PostgreSQL 16. Every M09 test passed on 17rc1 only. `docker-compose.yml` is checked for content by a unit
   test and has never been run.
2. The integration tests SKIP when no database answers. After a reboot run `python scripts/pgdev.py up` first, and
   read the skip count of a pytest run before using it as G1 evidence for a module that needs PostgreSQL.
3. Not tested in M09: the swap of `rewrite_window` under concurrent readers and writers (only one connection after
   the other), and how long WAL records of a closed window survive on disk (the settings are verified, the retention
   is not measured).
Optional human action (not a gate): install Docker Desktop from https://www.docker.com/products/docker-desktop/, open
it once so the engine starts, stop the private cluster (`python scripts/pgdev.py down`, it uses the same port), run
`docker compose up -d db`, then `python -m pytest -q tests/integration/test_repo_pg.py`. Before M14/M15 decide which
server the evaluation numbers come from and record its version in the run manifests.

Resolution of ISSUE-20 (2026-10-12, session 17, after the human installed Docker Desktop): `docker compose up -d --wait db`
started postgres:16 (server 16.15) from docker-compose.yml; the storage tests pass on it unchanged (118 passed, the 42
contract tests among them) and SHOW returns the 14 required settings (runs/20261012-103011_M09_storage_pg16_docker). Point 1 is settled; point 2 stays as a
note in STATE.md; point 3 moves to ISSUE-21.

### ISSUE-21 [OPEN] M09: rewrite_window is untested under concurrent connections; WAL lifetime of a closed window is not measured
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-12 session 17
1. Every rewrite test uses one connection after the other. Nothing shows what a reader or a late writer sees while
   the swap transaction runs (blocking, an error on the detached partition, a retry). M10 owns the scheduler that
   calls the re-shuffle: add a test with a second connection reading and inserting during `rewrite_window` there.
2. The WAL and logging settings are verified by SHOW on both servers, but how long the WAL records of a closed
   window stay on disk was not measured, and removed segments are not overwritten (docs/ENV.md says so). The
   requirement "retention < W" is configured, not demonstrated. M14 is the place to test it (copy `pg_wal` after a
   window has been rewritten and look for its rows).

Update of ISSUE-21 (2026-10-12, session 18, M10): point 1 is tested and one defect is fixed. With a second connection
reading a closed window in a loop while it is re-shuffled 25 times, `rewrite_window` deadlocked: it locked the
partition before the parent table, the opposite of a reader (runs/20261012-104809_M10_service/issue21_before_fix.txt, 25 DeadlockDetected). It now
locks `messages` first; the reader never fails and always sees the whole window
(runs/20261012-104809_M10_service/issue21_after_fix.txt, tests/integration/test_service.py). Inside the service the case cannot arise: one thread and one
connection serialise epochs, re-shuffles and reads. Still open: a writer on a second connection during the swap (the
scheduler never inserts into a closed window, so this is untested by design), and point 2 (WAL lifetime, for M14).

### ISSUE-22 [CLOSED 75a8bb5] M10: a restart leaves windows un-shuffled, and a crash loses messages that were accepted but not yet written
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-12 session 18
1. The scheduler keeps the set of windows it wrote and has not yet re-shuffled in memory only. After a restart the
   window that was open at shutdown, and any window that closed while the service was down, stays in its
   arrival-time layout for ever: nothing durable says which windows were re-shuffled. P1 does not hold for those
   windows. Fix in its own unit: a small durable marker per window (a public fact: "window w was rewritten"), or
   re-shuffle every window older than the current one at startup; then a test that restarts the backend mid-window.
2. `POST /v1/messages` answers 202 when the message is queued, before the epoch is written. A clean shutdown writes
   the queue first (tested); a crash or a kill loses up to one epoch of accepted messages, more if epochs are
   overflowing. The client has no acknowledgement of durability. M12 (client SDK) must read back or retry; M15 must
   say which of the two it measures.
3. Until M11 the API has no authentication and takes the conversation token in the clear from any caller: listen on
   127.0.0.1 only (the default of `vcloak serve`).
Not a human action. Must be closed, or stated as a limitation, before the security evaluation of M14 is written up.

Closing note of ISSUE-22 (2026-10-12, session 19, ADR-016):
1. Fixed. The store lists the windows still to be re-shuffled (`pending_windows`); the mark is written before the
   first rows of a window and removed in the swap transaction; a restarted service re-shuffles the listed windows
   that have closed. Before the fix the restart test failed in 4 of 6 cases (runs/20261012-110434_M10_issue22_restart/issue22_before_fix.txt), after it
   6 of 6 pass on SQLite and PostgreSQL 16 (runs/20261012-110434_M10_issue22_restart/issue22_after_fix.txt). A live `vcloak serve` on PostgreSQL was
   killed in the middle of a window and restarted: the window went from three writing transactions to one, in a new
   file, with every row (runs/20261012-110434_M10_issue22_restart/smoke_restart.txt).
2. Fixed by an acknowledgement, not by a durable queue (a journal of the queue would store the arrival order):
   `ack: "stored"` answers 201 after the epoch is committed. In the same live run the 30 messages answered 201
   survived the kill and the 5 answered 202 were lost. The default is still 202; what is left is ISSUE-23.
3. `vcloak serve` now refuses a non-loopback `--host` unless `--allow-remote` is given. Authentication is M11.

### ISSUE-23 [OPEN] The default acknowledgement is still `queued`: M12 must ask for `stored` and drop repeats, M15 must name what it measures
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-12 session 19
1. M12 (client SDK): send with `ack: "stored"`, retry on 503 `not_stored`, and on 504 `ack_timeout` or a broken
   connection treat the outcome as unknown. The server keeps no message identity, so a retry can store a message
   twice: carry a message number inside the plaintext and drop repeats on read.
2. M15: say for every latency number whether the submission used `ack: queued` or `ack: stored` (with `stored` the
   answer waits for the epoch boundary, up to EPOCH_MS, by design).
3. Windows written before session 19 carry no pending mark; a store older than that (only the development
   database) is not repaired. The marks and the acknowledgement have never run on a CUDA device.
Not a human action.
Update of ISSUE-23 (2026-10-12, session 24, M12, ADR-019): point 1 is done. The SDK sends with `ack: "stored"`, sends a
503 again after `Retry-After`, and after a 504 or a broken connection sends the same ciphertext again and holds the
next number back until it is confirmed; the reader drops repeats by (sender, session, number). Tested against a
scripted server (503, 504, lost answer, broken connection, five failed attempts) and, for the repeat, against the real
service. Points 2 and 3 remain (M15).

### ISSUE-24 [CLOSED 1569d66] HUMAN ACTION REQUIRED — GPU JOB READY: ISSUE-17 dudect diagnostics (job 20261012-113437_M08_issue17)
BLOCKS: M14   SEVERITY: high   OPENED: 2026-10-12 session 20
Why: three dudect series FAILED in the M08 job (ISSUE-17) and the cause is unknown. This job measures them again
together with controls that separate "the kernel time depends on the data" from "the test harness treats the two
classes differently". It needs the real GPU; the laptop cannot measure it.

GPU JOB READY — 20261012-113437_M08_issue17              (runtime not measured; plan for about 4 hours, see the note below)
Use Kaggle for this one (the job is long, and Kaggle sessions do not disconnect when the tab is idle).
File to upload: D:\PJT\vcloak\gpujobs\out\20261012-113437_M08_issue17\job.zip
Notebook:       D:\PJT\vcloak\colab\VCloak_GPU_Runner.ipynb
Do this (Kaggle, as for the earlier jobs):
  1. kaggle.com -> Create -> New Notebook -> File -> Import Notebook -> pick colab\VCloak_GPU_Runner.ipynb.
  2. Settings -> Accelerator -> GPU T4 x2.   (the step everyone forgets)
  3. + Add Input -> Upload -> gpujobs\out\20261012-113437_M08_issue17\job.zip as a dataset. Kaggle unpacks it into a
     folder: that is fine.
  4. Nothing to type in Cell 2: leave KAGGLE_INPUT = "" . The cell finds the job under /kaggle/input and must
     print "Bundle verified".
  5. Run Cell 1. It must print a GPU name (e.g. Tesla T4). If it prints NO GPU, redo step 2.
  6. Run the remaining cells and keep the tab open until the last one finishes. The long cell prints nothing
     while a command runs (the output of each command appears when it ends): that is normal. Do not start anything
     else in that notebook while it runs: the job measures small timing differences.
  7. Download results_20261012-113437_M08_issue17.zip from the Output panel.
  8. Move that file into D:\PJT\vcloak\gpujobs\inbox\   (do not unzip or rename it).
Or use Google Colab: colab.research.google.com -> File -> Upload notebook -> the same .ipynb; Runtime -> Change
  runtime type -> T4 GPU -> Save; run Cell 1 (GPU name), Cell 2 (upload job.zip), Cell 3 (keep the tab open and
  active: a free Colab session can disconnect during a job this long), Cell 4 (downloads the results zip).
Bring back only the results zip, even if a cell reports a failure. Do not commit or edit anything in the repo
  before the next session: a change to src/, kernels/, tests/, bench/ or scripts/ makes the result stale and it
  will be rejected.
No passphrase is needed: the job uses fixed TEST keys.
A dudect FAIL in the output is not an error of yours: FAIL or PASS of each series is the measurement.
Runtime note: 28 dudect targets (15 at seed 8, 13 at seed 9) of 100000 measurements per class. The plan of 4 hours is the sum of what the same
  kinds of target took in the M08 job (runs/20261012-031331_M08_dudect/summary.json, measure_seconds); the new
  targets have never run on a GPU, so it can be longer. Each of the two long commands may take up to 6 hours
  before it is stopped; what was measured until then is kept.
Confirm by running: .venv\Scripts\python scripts\gpujob.py verify gpujobs\inbox\results_20261012-113437_M08_issue17.zip
Then open a new session and type: continue
Closed 2026-10-12 session 21: the human ran the job on Kaggle (session 20261012-061138, Tesla T4) and the results zip
was ingested; all 7 commands exit 0, git sha and bundle sha match (runs/20261012-150500_M08_issue17_ingest/gates.txt).

### ISSUE-25 [CLOSED 9a6936f] M08 dudect: two device-stage series of the write_epoch diagnostics FAIL at seed 8 (write_epoch_age, write_epoch_fresh)
BLOCKS: M14   SEVERITY: high   OPENED: 2026-10-12 session 21
Finding (job 20261012-113437_M08_issue17, seed 8, Tesla T4, N = 100000 per class, threshold 4.5; values from
runs/20261012-061420_M08_dudect_issue17_s8, recomputed in runs/20261012-150500_M08_issue17_ingest/gates.txt and device_series_detail.txt).
The device-stage series is the CUDA-event total of the engine minus its `host` stage.
- write_epoch_age/device_ms (the SAME contents in both classes; long-lived Python ints vs new ones): max abs(t) 6.3027
  at crop 1, raw t 0.542; 8 of the 101 tests are above 4.5, all positive; 6.2202 in the first half of the run, 4.5639 in the second.
- write_epoch_fresh/device_ms (fixed vs random contents, both built from new objects): max abs(t) 6.1653 at crop 6, raw
  t -2.013; 5 of the 101 tests above 4.5, all negative; 3.7850 in the first half, 5.3228 in the second.
  The same target PASSES at seed 9 (3.0940, runs/20261012-080629_M08_dudect_issue17_s9): not reproduced.
- The device-stage series of write_epoch itself PASSES in all three runs (2.7559 in M08, 1.7742, 1.9675), and that of
  write_epoch_null PASSES (2.7782).
What is established: a device-stage series can FAIL when both classes hold the same contents (write_epoch_age), so
this series is not free of host effects. What is NOT established: the cause of either FAIL, and whether the
write_epoch_fresh FAIL is a dependence on the contents; it was seen in one of two seeds. Nothing below is tested.
- H5: the stages h2d and d2h are inside the device series and copy host memory that the classes prepared differently.
- H6: a chance exceedance or a drift of the shared runner (the SM clock was 585 MHz, LOW, in all of these runs).
Proposed fix (one prep session and one runner session):
1. Record every stage of the engine as its own series (h2d, tags, sort, compact, d2h, seal, bucket, open), so a FAIL
   is located in a stage.
2. Repeat write_epoch_age and write_epoch_fresh with three more seeds, and write_epoch_null as the control of each.
3. A device-only series that leaves out h2d and d2h.
Until then: M14 must not write that the device stages of the write path are timing-independent of the contents. It
may quote the series that were measured, with their verdicts.
Update 2026-10-12 session 30 (prep; nothing measured, the issue stays open):
- Points 1 and 3 are built: `bench/run_dudect.py --targets issue25` runs write_epoch_null_st, write_epoch_age_st and
  write_epoch_fresh_st, the same calls and staging as the three diagnostics, with the series device_ms, call_ms, core_ms
  (device_ms without h2d and d2h) and one series per engine stage (h2d, tags, sort, compact, d2h, seal, bucket; `open`
  is a read stage and has no series). Point 2 is job 20261012-191630_M08_issue25 (ISSUE-34): seed 8 again and seeds 10, 11, 12,
  with write_epoch_null_st and a full-N control_null in each run. Local evidence: runs/20261012-191159_M08_i25_prep (numpy,
  NOT_MEASURED: plumbing and outputs only).
- Reading rules, written before the results exist:
  a. H5 (transfers) is supported if a FAIL of device_ms comes with a FAIL of h2d_ms or d2h_ms and core_ms PASSES in
     the same run; it is not supported if core_ms FAILS.
  b. H6 (chance or runner drift) is the reading if no series of write_epoch_age_st and write_epoch_fresh_st FAILS in
     more seeds than the same series of write_epoch_null_st. It is a reading, not a proof of independence.
  c. A dependence on the contents is the reading only if a series of write_epoch_fresh_st FAILS in at least two seeds
     with the same sign of t while that series of write_epoch_null_st and write_epoch_age_st PASSES there.
  d. One call gives 10 series of 101 tests each, so more exceedances than in the earlier job are expected by chance;
     the control of the same run is the gauge, never the count alone.
  e. A stage is one unbatched interval; a stage whose median is below 50 us (ai/GPU_GUIDE.md §7) is quoted with
     its median and a FAIL or PASS of it is marked as below the rule.
- Not covered by this job: the clock (every failing series so far ran at 585 MHz; the job cannot set it), a second
  GPU model, write_epoch itself per stage (its device series PASSED three times).
Result, session 31 (job 20261012-191630_M08_issue25, runner session 20261012-135251, Kaggle Tesla T4, driver 580.178.04,
N = 100000 per class, threshold 4.5; runs/20261012-135427_M08_dudect_i25_s8, runs/20261012-145303_M08_dudect_i25_s10,
runs/20261012-155223_M08_dudect_i25_s11, runs/20261012-165055_M08_dudect_i25_s12; every max abs(t) recomputed from the raw npz in
runs/20261013-000602_M08_i25_ingest/gates.txt, 249 gates PASS, 0 FAIL). Values are given in the order seed 8, 10, 11, 12.
The issue stays OPEN: the cause is located more narrowly, it is not removed, and the contents are not excluded.
- The runs are valid: full-N control_null PASS in each (2.2810, 1.8856, 2.2996, 1.1958), planted leak detected
  (381.7530, quick, N 10000), 0 mismatches, 9 commands exit 0, git sha and bundle sha match the pack.
- 56 of the 124 series FAIL. This is not the pattern of chance: the same series fail in all four seeds with the same sign.
- The seed-8 finding of the earlier job is not reproduced as such: device_ms of write_epoch_age_st PASSES in all four
  seeds (1.6571, 4.3280, 1.9554, 2.0564) and that of write_epoch_fresh_st in three (2.0867, 4.0613, 1.4242; FAIL 6.8732 at
  seed 12). The sum hides what the stages show.
- Transfers, same contents (write_epoch_null_st, class = batch built first or second): h2d_ms FAILS in 4 of 4 seeds
  (7.3647, 7.7220, 5.1919, 25.6954) and d2h_ms in 4 of 4 (10.0027, 8.2372, 9.6120, 13.9003), t negative every time; core_ms
  PASSES in 4 of 4 (2.7747, 2.5635, 2.7617, 2.0612); device_ms FAILS at seeds 8 and 12 (5.6077, 5.1424). So the control of
  the run is itself separated in the two stages that copy host memory.
- Device stages, same contents (write_epoch_age_st, long-lived ints vs new ints): tags_ms FAILS in 4 of 4 seeds (13.9597,
  8.5119, 9.5266, 9.0150) and compact_ms in 4 of 4 (5.0805, 5.3882, 5.2484, 7.3084), t positive every time, while both
  series PASS in write_epoch_null_st in 4 of 4. The raw means of tags_ms differ by 84 to 180 ns. core_ms PASSES in 4 of 4
  (1.8005, 3.8004, 3.6308, 3.3354). So two stages that run only on the device separate classes whose contents are equal.
- Fixed vs random contents (write_epoch_fresh_st): compact_ms FAILS in 4 of 4 seeds (5.8350, 7.8222, 4.9391, 9.9600), t
  negative at the maximum every time (raw means differ by -82 to +430 ns); h2d_ms FAILS in 4 of 4 (12.2133, 8.1278,
  12.6966, 6.3898; positive, the opposite sign of the null) and d2h_ms in 4 of 4 (7.0672, 5.1914, 6.3207, 6.3779). At seed
  12 core_ms (8.8268, 69 of 101 tests above 4.5), device_ms (6.8732) and tags_ms (4.8655) FAIL as well; core_ms PASSES at
  the other three seeds (2.2959, 4.0678, 2.1933).
- Rule a (H5): supported in the two device_ms FAILs of write_epoch_null_st (h2d and d2h FAIL, core_ms PASSES); not
  supported in the device_ms FAIL of write_epoch_fresh_st at seed 12 (core_ms FAILS).
- Rule b (H6): chance or runner drift is NOT the reading. Series that FAIL in more seeds than in write_epoch_null_st:
  age_st call_ms (4 vs 2), tags_ms (4 vs 0), compact_ms (4 vs 0); fresh_st compact_ms (4 vs 0), core_ms and tags_ms (1 vs 0).
- Rule c (contents): the condition is not met for any series, so by the rule a dependence on the contents is not the
  reading. This is NOT an exclusion: compact_ms of write_epoch_fresh_st FAILS in four seeds with one sign and passes in
  the null; the rule fails only because the same series of write_epoch_age_st FAILS too (with the opposite sign). The
  rules written in session 30 did not foresee a stage that fails in both. Whether the compact_ms FAIL of fresh_st comes
  from the contents or from the host state is not decided by this job.
- Rule d: failing series per target, null / age / fresh: 6 / 5 / 3, 3 / 4 / 4, 5 / 5 / 3, 5 / 5 / 8 (table COUNT in gates.txt).
- Rule e: bucket_ms has a median of about 33 us, below the 50 us rule, in all 12 runs; its two FAILs (null_st, seeds 10
  and 12) are below the rule. All other stages are above it (h2d about 91, tags 100, d2h 141, compact 320 us).
- Clock: all 12 write_epoch targets ran at 585 MHz (LOW), the four controls at 1065 to 1110 MHz (LOW). No write_epoch
  series has been measured at another clock; the control is not at the clock of what it controls.
- Hypotheses now, none tested:
  H7: a stage interval is taken between two CUDA events of the engine's stream, so it holds the time the host needs to
      issue the launches of that stage; the host state (object age, allocation order) would then reach tags_ms and
      compact_ms without any dependence of a kernel on the data.
  H8: the compaction time depends on the contents (the permutation that the tags give).
- Proposed next step (one prep session and one runner session): a kernel-window target for the stages tags and compact,
  as aead_*_kernel did for ISSUE-17: inputs staged on the device in pools of equal size for both classes, outputs
  preallocated, r > 1 launches inside one event pair, fixed vs random contents and a same-contents null beside it. It
  separates H7 from H8. A warm-up that brings the SM clock up before the write_epoch targets, if the runner allows it.
- Evidence: evidence/terminal/M08_issue25_gates.txt, M08_issue25_gpu_run_output.txt; evidence/figures/M08_issue25_s*_dudect_*.png.
Until that is measured, M14 must not write that the device stages of the write path, or the compaction, are
timing-independent of the contents. It may quote these series with their verdicts, the FAILs included.
Update 2026-10-13 session 32 (prep of the LAST job; nothing measured, the issue stays open):
- Read from the code, and pinned by a test: in `write_epoch` the stages tags, sort and compact never receive the
  submissions. Their device inputs come from K_tag, the epoch and n_real, and are byte-identical in both classes of
  all three `*_st` targets (`test_issue25_tags_and_compact_get_the_same_device_input_in_both_classes`, runs/20261013-005353_M08_i25k_prep/pytest_all.txt).
  So H8 is excluded for the session-31 series: compact_ms of write_epoch_fresh_st cannot be a dependence of the
  compaction kernels on the contents, because those kernels got the same bytes. What separates the classes there is
  outside the kernels' data (H7: host launch code inside a stage interval, and what the host did before it). It
  also means the session-31 job never tested tags or compact against THEIR data (the key, the permutation).
- The clock, from the ingested runs (runs/20261013-005353_M08_i25k_prep/clock_facts.txt): all 120 write_epoch series ran at 585 MHz, steady
  (before 585, after 585, relative change 0.0, status LOW, throttle_reasons 0 in every telemetry row); 56 of them
  FAIL and 64 PASS at that same clock. The four controls PASS at 1050 to 1110 MHz. The clock is therefore the same
  for the failing and the passing write_epoch series, and for both classes of each: the PASS/FAIL split does not
  follow the clock split. What the clock does separate is the control (a sort) from the write_epoch targets.
- The interleaving was checked: `dudect.balanced_classes` shuffles the 2N class labels and every measurement takes
  its class from that order (`test_the_class_order_is_a_random_interleaving_not_two_blocks`). control_null is a
  separate target that runs before the others, as a target of its own; it is not one of the two classes of any
  series, so it does not explain a FAIL with equal contents.
- NOT done, a decision for the human: the session request asked to re-label the 56 failing series UNSTABLE in the
  metrics index on the ground of gpu-bench rule 5. The rule is a clock drop of more than 15% during the run; no
  write_epoch target had one, and `timing.clock_check` classed all 12 as LOW, not UNSTABLE. In this index UNSTABLE
  replaces the value, so the label would remove 56 measured values and keep the 64 PASS values taken at the same
  clock. The rows are unchanged. If a label is wanted, the one the data supports covers all 120 series (measured at
  585 MHz, 37% of the maximum, the control at another clock) and keeps the values.
- Built: `bench/run_dudect.py --targets issue25k` (tags_kernel, compact_kernel, tags_kernel_null,
  compact_kernel_null; control_leak_q with the self-test). Kernel-only window: a blocker launch of public size, then
  the start event, the r launches and the end event enqueued while the device is busy, so no host code runs between
  the events; `cudaEventQuery` on the start event flags a measurement that was not queued. Classes differ on the
  device: one fixed key vs random keys, one fixed permutation vs random ones, from device pools of equal size. The
  SM clock is read after every measurement; `--lock-clock` asks `nvidia-smi -lgc max,max` and records the answer;
  without a lock the warm-up waits for 8 polls without a rise (at most 120 s).
- Job 20261013-005946_M08_issue25k (ISSUE-35): self-test, then seeds 8 and 10, each with a full-N control_null.
- Reading rules, written before the results exist (threshold 4.5, N = 100000 per class; the verdict of a series is
  the test on ALL measurements, the test without flagged ones is quoted beside it):
  f. A run is usable only if control_leak_q FAILS (the window has power), control_null PASSES, there are 0
     mismatches, and in each target fewer than 5% of the measurements are flagged (unqueued or off the clock).
  g. Kernel-level result for a kernel: its `_null` PASSES and its target PASSES in both seeds. Wording: no
     dependence detected at this N, on this device; never "constant time".
  h. `_null` FAILS in either seed: the window still separates equal contents, the target of that kernel is not
     readable, the result for it is unusable.
  i. `_null` PASSES and the target FAILS in both seeds with one sign of t: a dependence of the kernel time on its
     data is the reading. It is a finding against P3 and is reported as one; ADR-023 does not cover it.
  j. `_null` PASSES and the target FAILS in one seed only: not decided, reported as measured.
  k. A lock that was refused is not a failure of the run; the modal clock and the flag counts are reported.
- Timebox (human, session 32): this is the only further job. If the result is unusable (rule f or h), no new job:
  the kernel-window series are recorded NOT_MEASURED with the reason (shared cloud GPU, the harness could not
  isolate the kernel), the obliviousness claim rests on the SASS reading, the Nsight branch efficiency and the E3
  trace invariance, and M14 is unblocked. Note for that session: Nsight is NOT_MEASURED today (ISSUE-18), so that
  sentence may only name what was measured. Rule i is a result, not "unusable": it is reported, not timeboxed away.
Update 2026-10-13 session 33 (the human's decision on the session-31 rows; nothing measured, the issue stays open):
- Decided: all 120 write_epoch series are annotated, every value is kept, the 56 are not replaced. Done as ANN-1 at
  the top of state/METRICS_INDEX.md (a note beside the table: the index has no note column, and the table lines are
  unchanged: runs/20261013-010926_M08_i25_annotate/annotation_check.txt, 120 rows covered, 0 table lines changed).
- The annotation gives the reason the human asked for, not the clock: for tags and compact (and sort) the device
  inputs were byte-identical in both classes, so those 36 series could not have shown a dependence on the contents,
  and the kernels were never tested against their own secrets; job 20261013-005946_M08_issue25k is that test. The clock
  (585 MHz, the control at another clock) is recorded as the condition of all 120, not as the cause.
- Still to do at the ingest, because it needs bench/ and the job must not go stale: the same note in the
  generator of section 4.O (`vcloak.bench.report_oblivious`), so the report table carries it.
- Reading rule added by the human before the results exist:
  l. If the lock is accepted (1590 MHz) but the locked runs carry MORE off-clock flagged measurements than a steady
     unlocked 585 MHz run, the unlocked steady clock is preferred: a stable slow clock is better for a t-test than
     a fast one that wobbles.
  What the job can and cannot give for rule l: both seeds ask for the lock, so if Kaggle accepts it the job holds no
  unlocked kernel-window series to prefer, and the session-31 runs have no per-measurement clock (their telemetry
  rows are the only comparison, and not like for like). If Kaggle refuses the lock, both seeds ARE the unlocked
  steady case and rule l is met by construction. In the accepted-and-wobbling case the ingest reports the flag
  counts, applies rule f (5%) and names rule l as not satisfiable without a run that the timebox excludes: that
  choice goes back to the human, it is not made by the agent.
- Fallback (the human, session 33): with ISSUE-18 NOT_MEASURED an unusable result leaves two legs, the SASS reading
  and E3. If ISSUE-18 is cheap, it is to be considered before M14 so the fallback has a second independent
  measurement. See the note of the same date in ISSUE-18: it is not cheap from this repository alone.
Result, session 34 (job 20261013-005946_M08_issue25k, runner session 20261013-021903, Kaggle Tesla T4, driver 580.178.04,
N = 100000 per class, threshold 4.5; runs/20261013-022124_M08_dudect_i25k_s8, runs/20261013-024742_M08_dudect_i25k_s10,
self-test runs/20261013-022000_M08_i25k_selftest_quick; every max abs(t) and every flag count recomputed from the raw npz in
runs/20261013-084838_M08_i25k_ingest/gates.txt, 55 gates PASS, 0 FAIL). Values in the order seed 8, seed 10. CLOSED by this result.
- Integrity: job id, bundle sha and git sha (c510682) match the pack; 0 mismatches; the tests of the targets passed
  on the GPU. One command exited non-zero: clock_reset (`nvidia-smi -rgc`, exit 4), the same refusal as the lock.
- Rule k: the lock was refused in all three runs ("The current user does not have permission to change clocks"),
  although the job ran as root. Not a failure of the run. The per-measurement clock was nevertheless steady: the
  mode is 1590 MHz in all eight kernel-window targets, at least 99.959% of the measurements at it, 0 to 3 off the clock.
- Rule f, as written: control_leak_q FAILS (386.2011, quick), control_null PASSES (2.9446, 2.7444), 0 mismatches,
  flagged 3.09% to 4.12% in the eight kernel-window targets (all unqueued; balanced between the classes). USABLE.
- Rule g, tags (chacha_tags, one fixed key vs random keys, 4096 slots, r 4): null PASS 1.1320, 1.4622; target PASS
  2.1075, 1.9069; without the flagged measurements 0.8310, 1.1041 and 0.1330, 0.2106.
- Rule g, compact (the sort network as gpu_compact runs it, one fixed permutation vs random ones, 4096 slots,
  n_real 1024, r 1): null PASS 0.7532, 2.2966; target PASS 0.9475, 1.9613; without flagged 0.1302, 0.7618 and 0.8438, 0.6893.
  Reading for both kernels: no dependence of the kernel time on its data detected at this N, on this device.
- Rules h, i, j: not met (no null and no target FAILS). Rule l: no locked run exists; both seeds are unlocked runs at
  a steady clock (1590 MHz, not the 585 MHz the rule expected), so the rule's preference is met by construction.
- What weakens the result (recorded as ISSUE-36, none of it foreseen by the rules):
  1. The positive control of the queued window is weak. Only 251 of the 20000 measurements of control_leak_q were
     queued (its blocker was fitted at 585 MHz, the measuring ran at 1590 MHz), so its FAIL is mostly that of an
     open window. The 251 queued ones alone give a raw Welch t of -24.4826 (119 and 132 per class, clocks 585 to
     1590 MHz): the queued window does detect the planted leak, on few measurements and not at the clock of the targets.
     Read strictly ("in each target fewer than 5% flagged", the control included) rule f would NOT hold.
  2. All eight windows are below the 50 us of ai/GPU_GUIDE.md section 7 (medians about 22 us for tags, 41 us for
     compact): r was fitted from the single-launch time before the clock rose (14.8 us x 4, 73.4 us x 1).
  3. Sensitivity, from the measured spread: a raw mean difference of about 200 ns per window (tags, 4 launches) or
     230 ns (compact, 1 launch) would give abs(t) = 4.5; smaller differences are not excluded.
- H7 and H8 (session 31): H8 was excluded in session 32; with the host code out of the window neither kernel
  separates its classes, which is what H7 predicts. H7 is supported, not proven.
- What M14 may write: for the tags kernel (key) and the compaction sort network (permutation), measured in a
  kernel-only window at 4096 slots, N = 100000 per class, two seeds, one T4 session, no timing dependence on the
  data was detected and the same-contents controls pass; with the three limits above and ADR-023 beside it. It must
  not write "constant time", must not extend this to other sizes, to the AEAD kernels (ISSUE-17) or to the whole
  write path, and must keep the 56 FAILs of session 31 in the tables with ANN-1.
- Done with it: ANN-2 in state/METRICS_INDEX.md; section 4.O.7 and the ANN-1 note in the generator
  (`python -m vcloak.bench.report_oblivious --kernel-window ...`, results/oblivious/kernel_window.csv).
- Timebox: this was the last job. No new job is proposed; the decision whether the weak control is acceptable for
  the report is the human's (ISSUE-36), and it does not block M14.

### ISSUE-26 [OPEN] M11: accounts and sessions live in memory; a restart forgets every account and logs every client out
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-12 session 22
`SessionService` keeps the accounts (name, Argon2id hash string), the refresh families, the jti cache and the rate-limit
counters in process memory (ADR-017). After a restart every registration is gone and every token is refused
(`token_mac`, refresh `unknown`). This is enough for the tests and for one demo run, not for M12/M13 use across restarts.
Also open: behind a reverse proxy all clients share one peer address for the per-address limits (no trusted-proxy
setting), and the per-name login limit lets anyone lock a name out for 5 minutes at a time.
Proposed fix: a small account table in the store (name, hash string only: nothing about conversations), in its own
unit after M11; the token state can stay in memory. Decide before M13 whether the demo needs it.

### ISSUE-27 [OPEN] M11 sockets: no bound before the ticket, never run under load, TLS proxy path untested
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-12 session 23
`/v1/ws` accepts a connection before it sees a ticket and holds it for up to 5 s (`WS_AUTH_TIMEOUT_S`); the limits
(4 sockets per login, 1024 per service) count only sockets that presented a valid ticket, so the number of connections
waiting for their first frame is not bounded by the service (uvicorn's `limit_concurrency` is not set). The push has
been run with a handful of sockets only (tests, one smoke client); `--public-origin` is tested in-process, never behind
a real TLS proxy. With `--sessions` on a public address without TLS in front, passwords travel in plain HTTP.
Proposed fix: set a connection limit in `serve`, and measure the push with many sockets in M15 (name the socket count
with the latency). Related: ISSUE-26 (session state in memory).

### ISSUE-28 [OPEN] M12 client: static prekeys from the server, no forward secrecy; what the order check cannot see
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-12 session 24
1. Key agreement is one static X25519 prekey per device (ADR-019): no forward secrecy, no ratchet, no signed prekey.
   The server hands out the prekeys and can replace one; only the manual fingerprint comparison detects it. The report
   must say so wherever it says "end-to-end encrypted" (M20 limitations). `GET /v1/prekeys/{name}` is open and not
   rate-limited; the prekeys are in memory with the accounts (ISSUE-26): after a server restart a client must publish again.
2. A reader cannot detect the loss of a sender's last messages, or of a whole client session it saw nothing of; only
   the sender detects it for its own messages (`verify_delivered`). The order between the two senders is not verifiable.
3. `vcloak-chat` starts `--lookback` windows back without a strict start, so messages older than that are not shown
   and their loss is not detected. It polls every `--poll` seconds instead of following the socket ticks.
4. Not exercised: the SDK over TLS, token expiry and 503/504 against the real service, concurrent senders.
Proposed: keep for the prototype; M13 shows the fingerprint in the chat view; M20 lists points 1 and 2 as limitations.

### ISSUE-29 [OPEN] M13 web app: the CSP still allows style attributes; what the browser client leaves open
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-12 session 25
1. `/app` is served with `style-src-attr 'unsafe-inline'`: the prototype's charts, tiles and attack view write
   `style=` attributes into innerHTML (16 places in web/js/charts.js, dashboard.js, experiments.js). It allows no
   script and no stylesheet, but it is a relaxation of "default-src 'self'". M18 owns those files: replace the
   attributes by classes or CSSOM calls, drop the directive from `service/web.py` and from
   `test_csp_allows_no_inline_script_and_no_other_origin`.
2. The pane accounts are made by the page; their random passwords sit in IndexedDB in readable form (ADR-020 (3)).
3. A pane starts without a strict start: it cannot detect the loss of messages sent before the first one it saw of
   a session (ADR-020 (4)); a reload therefore forgets what it had verified.
4. Not exercised: the CSP against a real injected script; the page in Firefox or Safari (tests run in Chrome
   only); the page behind TLS; token expiry in the browser (only an explicit refresh is tested); 503/504 retries in
   the browser; a tab left open for hours.
5. On a live server the page footer still reads "data: seed" and the strip reads "cpu": both come from the prototype
   and are wired in S6 and M18.
Proposed: point 1 in M18; points 2-4 are limitations to state in docs/DEMO.md and M20; point 5 closes with S6.

### ISSUE-30 [OPEN] M13 server view: `/v1/dump` is open in dev; what the panel does not show or test
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-12 session 26
1. With `--dev` `GET /v1/dump` needs no session. `--dev --sessions --host <not loopback>` is accepted by `serve`,
   and would hand the stored rows to anyone who can reach the port. The rows are what the threat model already gives
   the attacker, and `--dev` uses the public key, but the route should refuse a non-loopback client or `serve` should
   refuse that combination.
2. The baseline dump has `row_id`, `win` and `payload` only: `BaselineStore.dump()` does not return the `ts` and
   `conv` columns the table holds in the clear. S5 needs them for an honest baseline panel and caption.
3. The panel fetches whole payloads (4124 B a row, up to 200 rows) once a second; fine on loopback, not measured.
4. The overlay forgets at a reload and shows "—" for rows of other conversations; it numbers messages in the order
   one pane read them, which is verified per sender only (ISSUE-28 point 2).
5. Not exercised: the panel with `--visible-round epoch` in a browser (the state `epoch` is only reached in code
   review), the `closing` state (it lasts a few epochs; no test waits for it), more than 200 rows, PostgreSQL behind
   the page (the browser tests use SQLite), a window in which the permutation happens to keep the order.
Proposed: points 1 and 2 in S5 (it touches the same routes); 3-5 stay as stated limits in docs/DEMO.md.
Update 2026-10-12 session 27 (M13 S5, ADR-022): point 1 done (`serve` refuses `--dev` on a host that is not loopback,
whatever else is given; tests/unit/test_service_sqlite.py). Point 2 done (`BaselineStore.dump_clear`, `ts` and
`conv_hex` in `/v1/dump`, shown in the panel). Points 3-5 remain as stated limits; the issue stays open for them.

### ISSUE-31 [OPEN] M13: a browser test fails intermittently; what the mode switch leaves open
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-12 session 27
1. `tests/integration/test_web_app.py::test_a_withheld_message_is_flagged_in_the_pane` (S3) fails now and then:
   pane B shows no alert within 20 s. Seen once in 27 repeats of the file on the tree of session 27 and once in 4
   repeats on commit 93ab806, so it is older than the mode switch. One failing run also logged a keep-alive timeout
   on the DevTools socket, which points at the browser or the machine stalling, but the cause is not established.
   A second failure in those 27 repeats was not identified (its output was not kept). Until this is understood, a
   single green run of the file is weak evidence: repeat it before the Review-3 close-out (M17).
2. The mode switch is tested on SQLite only. On PostgreSQL the comparison uses the schemas `public` and `baseline`
   in one database; not run.
3. A client that is not the page (the Python SDK, a second tab) is not told about a switch and can stop with an
   order error, because the two stores can file a message under neighbouring windows. Stated in docs/DEMO.md and
   docs/API.md; not tested. The refusal path of the comparison backend (a full queue reaches neither store) is
   tested with stub backends, not on a running server.
4. The footer of the page reads "data: seed" on a live server too (seen in the S5 screenshots); the "dev" mark of
   the reveal switch is clipped at 1440 px. Both are from the prototype.
Proposed: point 1 in S5b, which builds on the same headless driver; point 4 in S6 or M18; 2-3 stay as stated limits.
Update 2026-10-12 session 28 (M13 S5b): point 1 traced to the test, not the pane. The hook withheld "the first new
payload B is handed"; a pane fetches its windows newest first, so when "the withheld one" and "the one after it" fell
into different windows and B read both in one pass, the hook withheld the LAST message, B showed "the withheld one",
and no alert could come (a missing last message is not detectable until a later one arrives, ISSUE-28).
runs/20261012-181114_M13_evidence_capture_s5b: flake/ (old test, 30 repeats alone: 29 passed, 1 failed with this
symptom), withheld_repro.json (the old hook with the two sends placed across a window boundary, 8 trials: 4 with no
alert and the last message withheld, 4 with the alert). The test now withholds the message by its ciphertext;
flake_fixed/ holds the repeats of the changed test (counts in SESSION_LOG session 28). Not established: that every
earlier failure was this one (the output of the failures of session 27 was not kept, and one of them logged a
DevTools keep-alive timeout). Points 2-4 unchanged; the issue stays open for them and for a repeat of the whole file
before M17.
Update 2026-10-12 session 29 (M13 S6): point 4 done. The footer reads "dashboard data: <source>"; the "dev" mark was
drawn as a second switch track because `.switch span` matched it (now `.switch > span`), seen fixed in the pictures of
runs/20261012-184104_M13_live_strip_s6. Points 2-3 remain as stated limits, and the repeat of the whole browser test
file owed before M17 (point 1) is still owed: it ran five times in this session, all green, which is not many.


### ISSUE-32 [OPEN] M13 capture_evidence.py: what the pictures do not show, and what the script does not do
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-12 session 28
1. Eight of the twelve pictures (dashboard, experiments, logs, architecture) show the prototype's bundled sample data
   on a live server; their rows say `seed`. They illustrate the interface only. M18 must re-capture them once
   `web/data/dashboard.json` is generated; the script then files the old ones under `evidence/superseded/` only if
   the file name changed (another day): on the same day it overwrites, so M18 must not run on a day that already has
   `seed` pictures it wants to keep, or the script needs a data-state part in the file name.
2. The chat pictures show the newest messages of each pane (the panes scroll), not all eight; the footer reads
   "data: seed" and the strip shows no epoch and, in baseline mode, no slot count (ISSUE-31 point 4, S6). The index
   rows say so. Re-capture after S6.
3. Figures (`evidence/figures/`, 300 dpi PDF + PNG) are not exported by the script; `--terminal` is unit-tested and
   used once (session 28), `--views` subsets and a run without `--run` (the script making its own run directory)
   were not run.
4. Chrome headless only; one viewport (1440x900); the single-column layout below 900 px is not photographed.
5. The supersede path (a row whose file name changed) is unit-tested on the index text; the file move itself has not
   happened yet, because no second day exists.
Proposed: 1 in M18, 2 in S6 (re-run the script at the end of that session), 3-5 as they come up in M16/M18.
Update 2026-10-12 session 29 (M13 S6): point 2 done (re-captured with the finished strip; the rows give the epoch
the strip and the server read just before the picture). Point 1 happened one session early and went wrong first: the
re-capture overwrote the twelve pictures of session 28, so the SHA-256 values in that run's record matched no file
(check_secrets flagged them, the full test run failed on it). The pictures were restored from commit c48e7a4; the
script now moves the picture of another run to `evidence/superseded/<name>.<time of its run>.png` before it writes,
and the row says where it is kept (superseded_check.txt: 12 files equal to the recorded hashes). Point 5: the file
move has now happened, for the same-day case; the other-day case is still unit-tested only. Points 3-4 unchanged.
The eight `seed` pictures were re-captured too (the strip and the footer changed); M18 still has to replace them.

### ISSUE-33 [OPEN] M13 live strip: what it does not show, and what was not run
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-12 session 29
1. The CUDA path of the strip has never run: `gpu.util` (an NVML reading taken in the request handler on every
   poll) and `backend: cupy` exist in code only. The service has never run on a CUDA device (STATE notes).
2. `last_write_ms` is the host wall-clock time of the last epoch write as the event loop saw it (it includes the
   wait for the engine thread). It is a timing of the write path, which is not constant time (ISSUE-17), so the
   route gives it with `--dev` only and the page does not show it. It is not a metric and must not become one (M15
   measures the service).
3. On `--compare` in baseline mode the strip shows no epoch although the V-cloak scheduler runs underneath.
4. The strip is within half a round trip of the server's clock. Checked on loopback only (strip_drift.json: 61
   samples in 120 s, at most one epoch behind, no drift); not over a real network, not with a throttled background
   tab, not longer than two minutes. If the server's clock steps back, `epoch` steps back while the scheduler keeps
   counting forward (`_next_boundary`): the strip would then show an epoch below `last_epoch`. Not handled.
5. `runner` is read from the environment (`VCLOAK_RUNNER`, Colab and Kaggle variables); everything else is `local`.
6. Every open page asks once a second, with no back-off. The fill is one reading per second of a queue that empties
   five times a second, so it shows 0 almost always; it is not a load figure.
7. The architecture view is "static + /v1/stats/live" in ai/FRONTEND.md §2; it does not use the route yet (M18).
Proposed: 1 with the first service run on a runner (M15 or later); 4 and 6 stay as stated limits in docs/DEMO.md;
7 in M18.

### ISSUE-34 [CLOSED a9178f8] HUMAN ACTION REQUIRED — GPU JOB READY: ISSUE-25 per-stage dudect of the write_epoch diagnostics (job 20261012-191630_M08_issue25)
BLOCKS: M14   SEVERITY: high   OPENED: 2026-10-12 session 30
Why: ISSUE-25 can only be settled by a measurement on the GPU, and this laptop has none.
GPU JOB READY — 20261012-191630_M08_issue25              (runtime not measured; plan for about 4.5 hours, see the note below)
Use Kaggle for this one (the job is long, and Kaggle sessions do not disconnect when the tab is idle).
File to upload: D:\PJT\vcloak\gpujobs\out\20261012-191630_M08_issue25\job.zip
Notebook:       D:\PJT\vcloak\colab\VCloak_GPU_Runner.ipynb
Do this (Kaggle, as for the earlier jobs):
  1. kaggle.com -> Create -> New Notebook -> File -> Import Notebook -> pick colab\VCloak_GPU_Runner.ipynb.
  2. Settings -> Accelerator -> GPU T4 x2.   (the step everyone forgets)
  3. + Add Input -> Upload -> gpujobs\out\20261012-191630_M08_issue25\job.zip as a dataset. Kaggle unpacks it into a
     folder: that is fine.
  4. Nothing to type in Cell 2: leave KAGGLE_INPUT = "" . The cell finds the job under /kaggle/input and must
     print "Bundle verified".
  5. Run Cell 1. It must print a GPU name (e.g. Tesla T4). If it prints NO GPU, redo step 2.
  6. Run the remaining cells and keep the tab open until the last one finishes. The long cell prints nothing
     while a command runs (the output of each command appears when it ends): that is normal. Do not start anything
     else in that notebook while it runs: the job measures small timing differences.
  7. Download results_20261012-191630_M08_issue25.zip from the Output panel.
  8. Move that file into D:\PJT\vcloak\gpujobs\inbox\   (do not unzip or rename it).
Or use Google Colab: colab.research.google.com -> File -> Upload notebook -> the same .ipynb; Runtime -> Change
  runtime type -> T4 GPU -> Save; run Cell 1 (GPU name), Cell 2 (upload job.zip), Cell 3 (keep the tab open and
  active: a free Colab session can disconnect during a job this long), Cell 4 (downloads the results zip).
Bring back only the results zip, even if a cell reports a failure. Do not commit or edit anything in the repo
  before the next session: a change to src/, kernels/, tests/, bench/ or scripts/ makes the result stale and it
  will be rejected.
No passphrase is needed: the job uses fixed TEST keys.
A dudect FAIL in the output is not an error of yours: FAIL or PASS of each series is the measurement.
Note on the runtime: the job has four measuring runs (seeds 8, 10, 11, 12), each one control_null and three
  write_epoch targets at N = 100000 per class. In job 20261012-113437_M08_issue17 the measuring loop of control_null
  took 291 and 307 s and that of a write_epoch diagnostic 986 to 1148 s (summary.json of the two runs), which gives
  about one hour per run before warm-up and calibration. The new series add no calls. This is a plan, not a measurement.
Confirm by running: ls gpujobs/inbox/      (it must list results_20261012-191630_M08_issue25.zip)
Then type: continue
Closed 2026-10-13 session 31: the human ran the job on Kaggle (session 20261012-135251, Tesla T4) and the results zip
was ingested; all 9 commands exit 0, git sha and bundle sha match (runs/20261013-000602_M08_i25_ingest/gates.txt).

### ISSUE-35 [CLOSED 9a6936f] HUMAN ACTION REQUIRED — GPU JOB READY: ISSUE-25 kernel-only dudect of tags and compact (job 20261013-005946_M08_issue25k)
BLOCKS: M14   SEVERITY: high   OPENED: 2026-10-13 session 32
Why: the kernel-level timing claim can only be measured on the GPU, and this laptop has none. This is the last job
for ISSUE-25 (timebox): whatever comes back, the next session closes the question and M14 starts after it.
GPU JOB READY — 20261013-005946_M08_issue25k              (runtime not measured; plan for 2 to 3 hours, see the note below)
Use Kaggle for this one (the job is long, and it asks for a clock lock that needs root, which Kaggle gives).
File to upload: D:\PJT\vcloak\gpujobs\out\20261013-005946_M08_issue25k\job.zip
Notebook:       D:\PJT\vcloak\colab\VCloak_GPU_Runner.ipynb
Do this (Kaggle, as for the earlier jobs):
  1. kaggle.com -> Create -> New Notebook -> File -> Import Notebook -> pick colab\VCloak_GPU_Runner.ipynb.
  2. Settings -> Accelerator -> GPU T4 x2.   (the step everyone forgets)
  3. + Add Input -> Upload -> gpujobs\out\20261013-005946_M08_issue25k\job.zip as a dataset. Kaggle unpacks it into a
     folder: that is fine.
  4. Nothing to type in Cell 2: leave KAGGLE_INPUT = "" . The cell finds the job under /kaggle/input and must
     print "Bundle verified".
  5. Run Cell 1. It must print a GPU name (e.g. Tesla T4). If it prints NO GPU, redo step 2.
  6. Run the remaining cells and keep the tab open until the last one finishes. The long cell prints nothing
     while a command runs: that is normal. Do not start anything else in that notebook while it runs.
  7. Download results_20261013-005946_M08_issue25k.zip from the Output panel.
  8. Move that file into D:\PJT\vcloak\gpujobs\inbox\   (do not unzip or rename it).
Bring back only the results zip, even if a cell reports a failure. Do not commit or edit anything in the repo
  before the next session: a change to src/, kernels/, tests/, bench/ or scripts/ makes the result stale.
No passphrase is needed: the job uses fixed TEST keys.
The job asks the driver to pin the GPU clock (`nvidia-smi -lgc`) and resets it at the end (`nvidia-smi -rgc`). If
  Kaggle refuses, that is recorded and the job goes on: it is not an error of yours.
A dudect FAIL in the output is not an error of yours either: control_leak and control_leak_q MUST fail.
Note on the runtime: two measuring runs (seeds 8 and 10), each control_null and four kernel-only targets at
  N = 100000 per class. Every measurement now waits for a blocker launch and reads the clock, and the size of the
  blocker is fitted on the runner, so the earlier jobs give no figure for it. 2 to 3 hours is a plan, not a measurement.
Also wanted from you, in the same reply (see ISSUE-25, update of session 32): whether the session-31 rows are to be
  re-labelled, and how. They are unchanged for now.
Update 2026-10-13 session 33: the decision on the session-31 rows was given and applied (ANN-1 in
  state/METRICS_INDEX.md, ISSUE-25 update of session 33). The results zip was NOT in gpujobs/inbox/ in that session,
  so this issue stays OPEN for steps 1 to 8 above. The session changed only state/, runs/ and evidence/: the packed
  job is still valid, do not re-pack it.
Confirm by running: ls gpujobs/inbox/      (it must list results_20261013-005946_M08_issue25k.zip)
Then type: continue
Update 2026-10-13 session 34: the results zip was in gpujobs/inbox/ and is ingested (runs/20261013-084838_M08_i25k_ingest/ingest.txt;
  the bundle is in gpujobs/done/). CLOSED. Nothing further is needed from the human for this job.

### ISSUE-36 [CLOSED session 44] M08 kernel-only window: the positive control was mostly unqueued, and all windows are below 50 us
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-13 session 34
Found at the ingest of job 20261013-005946_M08_issue25k (runs/20261013-084838_M08_i25k_ingest/gates.txt).
1. control_leak_q: 19749 of 20000 measurements unqueued. `run_dudect.py` fits the blocker of a target once, before
   the measuring; the self-test fitted it while the SM clock was 585 MHz and measured at 1590 MHz, where the same
   blocker is too short. The kernel targets were fitted late enough (3.09% to 4.12% unqueued). The power of the
   queued window rests on 251 measurements (raw Welch t -24.4826), not on a full control.
2. r is fitted from the single-launch time at the clock of the calibration; at 1590 MHz the windows of all eight
   kernel targets have medians of 22 us and 41 us, below the 50 us rule of ai/GPU_GUIDE.md section 7.
3. bench/jobs/M08_issue25k.json lists clock_reset as a required command; when the lock is refused it fails too and
   the job reports overall exit 1 although every measuring command passed.
Decision for the human (not made by the agent): accept the kernel-window result with these limits stated (what
section 4.O.7 and ISSUE-25 do today), or record the eight series as NOT_MEASURED under the timebox. The timebox of
session 32 excludes a further job, so no fix job is proposed. If a job is ever allowed again: re-fit the blocker and
r after the warm-up at the measuring clock, re-fit when the unqueued share of a chunk exceeds 5%, and mark
clock_reset optional.
Until decided: M14 and M20 quote the result only together with limits 1 and 2.
Decided session 44 (owner): all eight kernel-only series (tags_kernel, tags_kernel_null, compact_kernel,
compact_kernel_null, seeds 8 and 10) are recorded as NOT_MEASURED. Done: 16 rows of state/METRICS_INDEX.md (max |t|
and max |t| without flagged) carry NOT_MEASURED under ANN-4; section 4.O.7 and results/oblivious/kernel_window.csv are
regenerated with `--kernel-window-not-measured ISSUE-36` (runs/20261013-171026_M16_prefixes/report_command.txt, which replaces
the command of runs/20261013-091541_M08_issue17_table); the generator refuses to withdraw a FAIL. The raw data stay in the run dirs.
Consequence for M16, M20, M22: there is NO dudect timing result for the tags and compaction kernels against their
own data. Never write "no dependence detected" for tags or compact; P3 for these kernels rests on the SASS reading
(ISSUE-19) and on the logical trace, and the report says that the timing test of them is NOT_MEASURED. Point 3
(clock_reset marked required) is moot: no further dudect job (timebox of session 32).

### ISSUE-37 [OPEN] M08 residual of ISSUE-17: the S2 dudect series were never measured again with symmetric staging
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-13 session 36
Opened at the request of the human so that the residual of ISSUE-17 (closed in session 35, commit 44d7ff5) stays
traceable. Nothing is measured or changed by this issue.
ISSUE-17 point 1 named two ways: show the diagnostics beside the S2 rows, or make the symmetric staging the S2
staging and measure again. Session 35 took the first. The second was NOT done:
1. The S2 series of aead_conv and aead_tag in results/oblivious/summary_table.csv are still the asymmetric staging
   and still FAIL. The symmetric-staging result exists only as diagnostic rows (`aead_conv_sym`, `aead_tag_sym`,
   job 20261012-113437_M08_issue17, seeds 8 and 9, N 100000 per class, one T4), never as an S2 run.
2. In that job the staging and the SM clock change together (failing series at 585 MHz, *_sym at 1425 to 1560 MHz),
   so "the FAIL follows the staging, not the contents" is a reading by the rules of ISSUE-17, not a separated result.
Why it is open and not fixed: the timebox of session 32 excludes a further GPU job. If a job is ever allowed: run
S2 with the symmetric staging as the S2 staging, with the clock held or recorded per class, and keep the old FAIL rows.
Until then: M14, M20 and M22 quote the AEAD result only in the wording of the ISSUE-17 closing note and name this
issue; section 4.O.6 points to ISSUE-17 only (generated text, not edited by hand), so the limitations chapter of the
report (M20) must list this issue explicitly.

### ISSUE-38 [CLOSED 6bc85b8] M14 A1 asks for engine=gpu: the service and PostgreSQL have never run on the runner
BLOCKS: M14   SEVERITY: medium   OPENED: 2026-10-13 session 36
M14 S1 ran on the laptop: service API, sim clock, PostgreSQL, numpy simulator behind the engine
(runs/20261013-094044_M14_security_s1, manifest engine "numpy-simulator"). Audit A1 wants mode=vcloak, db=postgres,
engine=gpu in the manifest, and ai/PROTOCOL.md 6b puts the M14 measurements in a GPU job. No job has ever started
the service or a database on Kaggle (STATE: "The service has never run on a CUDA device").
Not decided here; to settle before M14 can be DONE, at the latest when S2 to S6 are written:
1. one GPU job that runs `bench/run_security_eval.py` on the T4 with a store on the runner (PostgreSQL installed in
   the notebook, or sqlite with db recorded as sqlite and A1 met only for the engine), or
2. local runs with the numpy simulator reported as such (tests keep it bit-exact against the references; the
   security numbers depend on the tags, not on timing) and A1 recorded as not met for the engine, with an
   amendment to the module file.
The timebox of session 32 was about further dudect jobs; whether it covers an M14 job is for the human to say.
Until then every M14 number is indexed with backend numpy / runner local and is never called a GPU result.
Decided by the human (session 37, 2026-10-13): way 1. A GPU job for M14 is allowed and wanted, as a full-stack job with
PostgreSQL installed and started in the runner; the M14 numbers must not stay labelled numpy / local. Job 20261013-105517_M14
is packed (ISSUE-39). This issue stays OPEN until that job is ingested and A1 is checked on its manifests.
Closed (session 38, 2026-10-13): the job is ingested. The manifests of runs/20261013-054644_M14_security_s1 and
runs/20261013-054727_M14_security_e0e1 say mode=vcloak, db=postgres, engine=gpu, backend cupy, runner colab, with the
gpu_job block; `vcloak.bench.report_security` refuses any other input. A1 is met for S1 to S5; S6 is ISSUE-40.

### ISSUE-39 [CLOSED 6bc85b8] HUMAN ACTION REQUIRED — GPU JOB READY: M14 on the full stack, and the tests marked gpu (job 20261013-105517_M14)
BLOCKS: M14   SEVERITY: high   OPENED: 2026-10-13 session 37
Why: M14 needs its numbers from the T4 with PostgreSQL behind the service (ISSUE-38), and the 674 tests that skip locally need a run.
Do this:
```
GPU JOB READY — 20261013-105517_M14              (runtime not measured; plan for about 1 hour)

1. Open https://colab.research.google.com  ->  File > Upload notebook
   Pick:  colab/VCloak_GPU_Runner.ipynb
2. Runtime > Change runtime type > T4 GPU > Save        <- easy to miss
3. Run Cell 1. It must print a GPU name (e.g. Tesla T4).
4. Run Cell 2, upload:  gpujobs/out/20261013-105517_M14/job.zip
5. Run Cell 3 (keep the tab open), then Cell 4 to download results_20261013-105517_M14.zip
6. Put that file in:  gpujobs/inbox/
7. New session, type: continue

Use Colab for this job, not Kaggle: command 3 installs PostgreSQL with apt-get and needs the internet, which is
on by default in Colab. (On Kaggle it works only with Settings > Internet switched on; Kaggle unpacks the
uploaded zip into a folder and Cell 2 finds it by itself.)
If Cell 3 shows "stack_up: exit 1", the PostgreSQL install failed: the job still finishes the other commands,
download the results anyway and say so.
Full detail: YOUR_CHECKLIST.md
```
What the job runs: nvidia-smi; `scripts/runner_stack.py up` (pip packages of the service, apt-get postgresql, a private
cluster on 127.0.0.1:54329 with the hygiene settings); check_oblivious; `run_security_eval.py` stages s1, attack
(six layouts, E0 on W60), uniformity, trace, all with `--backend cupy --seed 2026`; `run_gpu_tests.py --expect 674`;
the PostgreSQL settings; nvidia-smi. Every command is `stop_on_fail: false`, so one failure does not hide the rest.
Never run on a device before: the service and its engine thread on CuPy, PostgreSQL in the runner, the whole
`-m gpu` selection in one pytest process (earlier jobs ran files of it). The runtime is an estimate, not a measurement.
Confirm by running: `ls gpujobs/inbox/` shows results_20261013-105517_M14.zip
Then type: continue
Done (session 38, 2026-10-13): the human ran the job on Colab (session 20261013-054610, Tesla T4). Ingested: 11 of 11
commands exit 0 (stack_up too), 5 run dirs, 40 metrics indexed, 674 of 674 tests marked gpu passed in one process
(1519.60 s by pytest's own report: a duration of the test run, not a metric). The bundle is in gpujobs/done/. CLOSED.

### ISSUE-40 [CLOSED d08aa1a] M14 S6 (anonymity set) and S7 (comparison with the oracle) are not written and not in job 20261013-105517_M14
BLOCKS: M14   SEVERITY: medium   OPENED: 2026-10-13 session 37
The human asked for E0 to E3 in the job; S6 and S7 were not part of it and are not written.
1. S7 needs no device: it compares the ingested numbers with the oracle (`seed/`, run locally) in a table.
2. S6 replays traffic for 10, 100 and 1000 users. Audit A1 wants those numbers from the real stack too, so S6 needs
   either a second (small) GPU job or a decision to report S6 from the numpy simulator with A1 recorded as not met
   for S6. The module text does not say how users map to conversations; that has to be fixed and written down first.
3. Seen on the simulator (runs/20261013-103235_M14_security_e0e1/e1_attack.json): at W = 300 the peak bucket-window occupancy is above CAND_K
   (128), so a read at W = 300 would answer `candidate_overflow`. The ablation only dumps that layout; the default
   W = 60 stays below CAND_K. To be re-read on the device numbers and stated with the ablation.
Decision for the human at the ingest: a second job for S6, or S6 on the simulator.
Session 38 (ingest): point 3 is the same on the device (runs/20261013-054727_M14_security_e0e1/e1_attack.json: W300 peak
occupancy 345, mean 132.97, CAND_K 128; W60 peak 91) and is stated in section 4.S.3 of the notes. S6 and S7 are still
not written; the decision for S6 was asked again in the handoff of session 38. S7 can be done without it.
Session 39: S7 is done (runs/20261013-121247_M14_oracle_compare, section 4.S.9 of the notes; its two differing rows are ISSUE-41). What is left
of this issue is S6 only. The decision is still the human's: a second small GPU job (A1 met), or S6 on the numpy
simulator with A1 recorded as not met for S6. The S6 code is needed either way and is the next unit; if no
decision is recorded by then, that session packs a GPU job (the option that meets A1) and stops at its gate.
Session 40: no decision was recorded, so the S6 code was written (users in pairs; Amendments of the module file) and
the GPU job 20261013-125843_M14_s6 was packed (ISSUE-42). This issue closes with the ingest of that job, when S6 is in the notes.
Point 3 has a sibling, seen on the simulator only (runs/20261013-124943_M14_security_anon/s6_anonymity.json): at 1000 users the
fullest bucket-window of the default layout W = 60 holds more real rows than CAND_K (S-ANON-BW-PEAK-U1000, backend
numpy), so a read there would answer `candidate_overflow`. To be re-read on the device numbers at the ingest.
Session 41 (ingest of job 20261013-125843_M14_s6): closed. S6 is measured on the T4 with PostgreSQL (runs/20261013-101309_M14_security_anon)
and is section 4.S.10 of the notes; nothing of M14 is NOT_MEASURED any more. The sibling of point 3 is the same on the
device (S-ANON-BW-PEAK-U1000 172, CAND_K 128): it and the W300 point are carried by ISSUE-43.

### ISSUE-41 [OPEN] M14 S7: the CPU oracle's own chi-square run is outside the acceptance gate (p 0.0026); the device passes
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-13 session 39
What: in the device-against-oracle table (runs/20261013-121247_M14_oracle_compare/oracle_comparison.csv) 2 of 35 rows are DIFFERS, both from
the same chi-square test at n 64 over 20000 epochs. The side that is outside is the oracle: statistic 4222.7766
(S-ORACLE-CHI2) at 3969 degrees of freedom, p 0.0025768 (S-ORACLE-CHI2-P), above the largest of the 200 ideal-sampler
tables of the device run (4209.04) and below the gate p > 0.01. The device values pass (S-CHI2 3854.59, S-CHI2-P 0.9013).
The oracle draws its key for this test from the OS at every run, so the run cannot be repeated with the same key.
Diagnostic (chosen after the table was read, so it changes no verdict): the oracle's chi-square computation repeated
for 10 fresh keys (runs/20261013-122525_M14_oracle_chi2_repeat): statistics from 3735.97 to 4067.95, median 3952.89,
0 of 10 below p 0.01. That is what a tail draw of the main run would look like; 10 tables cannot exclude a small bias.
Also seen, no verdict attached: the oracle's main run lies outside the prediction interval of its own 20 repetitions
for two W60 rows (global tau and tau within a round, one event: they move together), while the device lies inside.
So the interval from 20 repetitions is on the narrow side for W60, or that oracle run is an unusual draw there too.
Not affected: every device gate (61 of 61 PASS) and the 31 EQUAL and WITHIN_NOISE rows.
Options for the human / the owner: (a) keep the two rows as DIFFERS with this issue named beside them (the state of
section 4.S.9 now) and close this issue as a documented tail draw; (b) one more full oracle run with a fixed, recorded
test key for the chi-square, so that the oracle side becomes repeatable (this needs a wrapper: seed/ is read-only).
Until decided, M20 and M22 quote the comparison as "31 of 35 rows agree, 2 are defined differently, 2 differ on the
oracle side (ISSUE-41)", never as "the GPU matches the oracle".

### ISSUE-42 [CLOSED d08aa1a] HUMAN ACTION REQUIRED — GPU JOB READY: M14 S6, the anonymity set on the full stack (job 20261013-125843_M14_s6)
BLOCKS: M14   SEVERITY: high   OPENED: 2026-10-13 session 40
Why: S6 is the last open step of M14, and audit A1 wants its numbers from the T4 with PostgreSQL behind the service
(ISSUE-40). No decision for the simulator was recorded, so the job was packed, as ISSUE-40 said it would be.
Do this:
```
GPU JOB READY — 20261013-125843_M14_s6              (runtime not measured; plan for about 20 minutes)

1. Open https://colab.research.google.com  ->  File > Upload notebook
   Pick:  colab/VCloak_GPU_Runner.ipynb
2. Runtime > Change runtime type > T4 GPU > Save        <- easy to miss
3. Run Cell 1. It must print a GPU name (e.g. Tesla T4).
4. Run Cell 2, upload:  gpujobs/out/20261013-125843_M14_s6/job.zip
5. Run Cell 3 (keep the tab open), then Cell 4 to download results_20261013-125843_M14_s6.zip
6. Put that file in:  gpujobs/inbox/
7. New session, type: continue

Use Colab for this job, not Kaggle: command 3 installs PostgreSQL with apt-get and needs the internet, which is
on by default in Colab. (On Kaggle it works only with Settings > Internet switched on; Kaggle unpacks the
uploaded zip into a folder and Cell 2 finds it by itself.)
If Cell 3 shows "stack_up: exit 1", the PostgreSQL install failed: the job still finishes the other commands,
download the results anyway and say so.
Full detail: YOUR_CHECKLIST.md
```
What the job runs: nvidia-smi; `scripts/runner_stack.py up` (the same stack as job 20261013-105517_M14); check_oblivious;
`run_security_eval.py --stage anonymity --backend cupy --seed 2026` (10, 100 and 1000 users in pairs, 900 simulated
seconds each, layout W = 60, PostgreSQL; the dump is counted and attacked); the PostgreSQL settings; nvidia-smi.
The same command with `--backend numpy` took about 3 minutes on the laptop with PostgreSQL (runs/20261013-124943_M14_security_anon); the
time on the runner is an estimate, most of it the install of the stack.
Alternative, if you do not want to run a job: say "S6 on the simulator". Then the numbers of runs/20261013-124943_M14_security_anon
are reported as simulator values and A1 is recorded as not met for S6.
Confirm by running: `ls gpujobs/inbox/` shows results_20261013-125843_M14_s6.zip
Then type: continue
Session 41: the human ran the job on Colab and put results_20261013-125843_M14_s6.zip into gpujobs/inbox. Ingested: runner
session 20261013-101235, Tesla T4, 7 of 7 commands exit 0, run runs/20261013-101309_M14_security_anon (mode=vcloak, db=postgres,
engine=gpu), 24 rows indexed as cupy / colab. Closed with d08aa1a.

### ISSUE-43 [OPEN] Bucket-window occupancy above CAND_K: the default layout W = 60 at 1000 users, and W = 300 at 200 conversations
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-13 session 41
What: measured on the device (T4 + PostgreSQL). (a) runs/20261013-101309_M14_security_anon/s6_anonymity.json: with 1000 users in 500
conversations (61383 messages in 900 simulated seconds, 64 buckets, W = 60) the fullest bucket-window holds 172 real rows
(S-ANON-BW-PEAK-U1000), the median bucket-window 62, CAND_K is 128. At 10 and 100 users the peaks are 26 and 42.
(b) runs/20261013-054727_M14_security_e0e1/e1_attack.json: layout W300 with 200 conversations, peak 345, mean 132.97 (from ISSUE-40).
Consequence: `fetch_candidates` raises `CandidateOverflow` above K (ADR-014), so a read of such a bucket-window answers
`candidate_overflow`. M14 only dumped and counted these layouts; no read was attempted on them, so the failure of a read
is the contract of ADR-014, not an observation of this run. How many bucket-windows are above CAND_K at 1000 users was not counted.
Not a result of this issue: any capacity claim. The traffic model (rate 0.05, bursts) and one seed give these numbers.
Affects: M15 (a load of 1000 users on the default parameters would hit overflow on reads: say which parameters it runs
with before measuring); M20 and M22 (state as a limitation of the default parameters: the buckets, CAND_K and W have to
be sized to the population). Sections 4.S.3 and 4.S.10 of the notes name this issue.
Options for the owner: (a) document as a sizing limit (the state now); (b) a sizing rule for buckets / CAND_K from the
expected rows per window, as a design note or ADR, checked by one more S6-type run; (c) raise CAND_K or the bucket count
for the 1000-user point in M15 and record the parameters beside every number.

### ISSUE-44 [CLOSED 698dff2] HUMAN ACTION REQUIRED — GPU JOB READY: write_epoch re-measured after the ISSUE-12 fix (job 20261013-163732_M07_issue12)
BLOCKS: M15   SEVERITY: high   OPENED: 2026-10-13 session 42
Why: ISSUE-12 blocks M15. The host path of `write_epoch` was changed (59d622f); only a run on the T4 can say whether
the whole call now fits EPOCH_MS at 65536 slots. M15 does not start before that number is in.
Do this:
```
GPU JOB READY — 20261013-163732_M07_issue12              (runtime not measured; plan for about 20 minutes)

1. Open https://colab.research.google.com  ->  File > Upload notebook
   Pick:  colab/VCloak_GPU_Runner.ipynb
2. Runtime > Change runtime type > T4 GPU > Save        <- easy to miss
3. Run Cell 1. It must print a GPU name (e.g. Tesla T4).
4. Run Cell 2, upload:  gpujobs/out/20261013-163732_M07_issue12/job.zip
5. Run Cell 3 (keep the tab open), then Cell 4 to download results_20261013-163732_M07_issue12.zip
6. Put that file in:  gpujobs/inbox/
7. New session, type: continue

Kaggle works as well (the M07 numbers this job is compared with came from Kaggle): Create > New Notebook >
File > Import Notebook, Settings > Accelerator > GPU T4 x2, add job.zip via "+ Add Input > Upload", run Cell 2 as it
is (Kaggle unpacks the uploaded zip into a folder and Cell 2 finds it by itself), and take the results from the
Output panel. This job needs no internet.
Full detail: YOUR_CHECKLIST.md
```
What the job runs: nvidia-smi; lscpu; the engine tests and the engine-against-oracle sweeps on the device;
`bench/run_pipeline.py --dev --full --seed 7` (the command of runs/20261011-215653_M07_pipeline: write_epoch at 64 to 65536 slots and
read_window at K 64 to 4096, 200 calls each, CUDA events, the real-time gate, cProfile of the host stage at 65536);
nvidia-smi.
Reading the result: the host stage is Python on the CPU of the runner, so the new numbers are comparable with those of
M07 only as far as the two runner CPUs are (lscpu is in both bundles; ISSUE-3 for the images). Both outcomes are
recorded as measured: if the gate still fails at 65536 slots, ISSUE-12 stays a limitation and M15 says so.
Confirm by running: `ls gpujobs/inbox/` shows results_20261013-163732_M07_issue12.zip
Then type: continue
Closed session 43: the human ran the job on Colab (T4, 2 vCPU; session 20261013-111455) and the bundle was ingested
(698dff2): 5 of 5 commands exit 0, run dir runs/20261013-111612_M07_pipeline. The result is in ISSUE-12.

### ISSUE-45 [CLOSED 99987e6] HUMAN ACTION REQUIRED — GPU JOB READY: write_epoch on Kaggle with 4 vCPU, the platform of the M07 measurement (job 20261013-173239_M07_issue12k)
BLOCKS: none (ISSUE-12 waits for it; M15 gives no verdict for 65536 slots before it is ingested)   SEVERITY: high   OPENED: 2026-10-13 session 44
Why: decision of the owner on ISSUE-12 (option a). One job settles whether 65536 slots miss EPOCH_MS on 4 vCPU and
gives an after-measurement on the platform of the before-measurement (ADR-024). It must run on KAGGLE, not Colab:
the job checks this itself and refuses to start on another platform or with another vCPU count.
Internet: NOT needed. Leave the Kaggle internet toggle off; no phone verification is required for this job. It has
no `stack_up` step and installs nothing (runs/20261013-171026_M16_prefixes/kaggle_internet_check.txt).
Do this:
```
GPU JOB READY — 20261013-173239_M07_issue12k              (runtime not measured; plan for about 20 to 30 minutes)

1. Open https://www.kaggle.com  ->  Create > New Notebook > File > Import Notebook
   Pick:  colab/VCloak_GPU_Runner.ipynb
2. Settings > Accelerator > GPU T4 x2                    <- easy to miss
3. + Add Input > Upload, pick:  gpujobs/out/20261013-173239_M07_issue12k/job.zip
4. Run Cell 1. It must print a GPU name (Tesla T4).
5. Run Cell 2 as it is (Kaggle unpacks the upload into a folder; the cell finds the job by itself).
6. Run Cell 3 and keep the tab open.
   If it prints "This job needs 4 vCPU" or "must run on kaggle": nothing was run. Tell me what it printed;
   do not move the job to Colab.
7. Take results_20261013-173239_M07_issue12k.zip from the Output panel and put it in:  gpujobs/inbox/
8. New session, type: continue
```
Known risk, not a defect of the job: Kaggle sessions of this project had 4 vCPU (driver 580.178.04, CUDA 12090) from
M05 to M08 and 2 vCPU (driver 580.82.07, CUDA 13000) for M00, M03 and M04. If Kaggle gives 2 vCPU the job refuses,
and the choice goes back to the owner (accept the limitation, as announced). If the image differs from the M07
session the run is ingested and the difference is stated beside the numbers.
Confirm by running: `ls gpujobs/inbox/` shows results_20261013-173239_M07_issue12k.zip
Then type: continue
Closed session 45: the bundle was in the inbox and is ingested (Kaggle, 4 vCPU, driver 580.178.04, CUDA 12090: the
platform and image of the M07 run; 5 of 5 commands exit 0). Reading: ISSUE-12, update session 45.

### ISSUE-46 [CLOSED c3d4e26] M16 audit A1 is not met as written: 9 macros are traced to a run file, not to a METRIC-ID
BLOCKS: M16   SEVERITY: medium   OPENED: 2026-10-13 session 44
What: A1 of ai/modules/M16 asks that every macro value is traceable to a METRIC-ID. Of the 48 contract macros 31 are
index rows, 7 are public parameters, 1 is pending (resAESus, ADR-003) and 9 are measured values that exist only in
the output file of an ingested run and have no index row: resRestoreN, resTVD, resChiIdeal, resTVDIdeal, resTauSigma,
resTauBand, resTauMean, resTauMaxAbs, and resMeanPerEpoch (messages divided by the epochs passed). The same holds for
tau_hist.dat, trace_table.tex, session_table.tex and the verdict column of dudect_table.tex. Every one of them is
traced in results/paper/macro_map.json to its run dir, file and JSON path (runs/20261013-172550_M16_export/a1_traceability.txt),
so nothing is typed or estimated; what is missing is the ID.
Why the agent did not close it: an index row must be listed in the summary.json of its run (check_metrics rule 5),
and these summaries came out of ingested bundles. Adding the IDs honestly means changing the bench scripts and
running them again on the runner; indexing them under a local run dir would give device values a local backend.
Decision for the owner: (a) accept run dir + file + path as traceability for values that a run wrote but did not
index, and amend A1 (one line under Amendments of the module file; M16 is then DONE at the next `audit M16`);
(b) add the IDs to the M14 bench scripts and take them from the next M14-type job; (c) drop these 9 macros to pending.
Until decided: M16 is AUDIT_FAILED and M19, M20, M22 (which depend on it) do not start.
Decision of the owner (session 45): (a), with two conditions. The amendment is in ai/modules/M16_results_export.md.
1. Narrow scope: only the run dir + file + JSON path of an INGESTED run counts. The exporter enforces it
   (`Exporter.field` raises for a value without an index row whose run has no cupy backend or no job id in its
   manifest; three new tests in tests/unit/test_export_results.py). All 9 macros and the 41 other run-file values
   (tau_hist.dat 24, trace_table.tex 10, the verdict column of dudect_table.tex 7) come from ingested runs.
2. Visible exception: report/TRACEABILITY.md (generated by the exporter) lists the 9 macros first, then the 41, each
   with run dir, job id, file and JSON path.
Correction of this issue's own text: "the same holds for session_table.tex" was wrong. Its 26 observed outcomes come
from runs/20261012-160139_M11_session_matrix, a LOCAL run, so the amended rule does not cover them. They are the single cases
behind the index row SEC-E5-PASS (26/26) of that run; the exporter now names that METRIC-ID for them (it refuses
if the row is missing) and section 3 of report/TRACEABILITY.md lists them. That is A1 as originally written, not the
amendment.
Follow-up (owner: opportunistic, never its own job, blocks nothing): if an M14-type GPU job is run for another
reason, extend the bench scripts so that these 9 values get METRIC-IDs.

### ISSUE-47 [CLOSED 555b4f5] HUMAN ACTION REQUIRED — GPU JOBS READY for the PC runner: the M00 probe, then the ncu job of ISSUE-18 (jobs 20261013-224820_M00 and 20261013-224820_M08_ncu)
BLOCKS: none (M15 may run meanwhile; see "Staleness" below)   SEVERITY: medium   OPENED: 2026-10-13 session 46
Why: decision of the owner (ADR-025). The PC is a third runner under the job protocol; the project stays on the
laptop. Both jobs are packed from commit 072ee8c and are already inside the kit folder.
Do this:
```
GPU JOBS READY — PC runner                 (runtime on that machine not measured)

1. Copy the whole folder  pc_runner/  to the PC (USB stick or any file transfer). About 4 MB.
   It holds SETUP.txt, RUN.txt, the three scripts and jobs/ with the two job zips.
2. On the PC: follow pc_runner/SETUP.txt, steps 1 to 7 (driver check, Python 3.12, CUDA Toolkit 12.x,
   CuPy wheel, GPU counters, check_setup.py). Step 7 must end with:  READY. Continue with RUN.txt.
3. Follow pc_runner/RUN.txt. Two commands, smallest job first:
     python run_job.py jobs/1_probe_20261013-224820_M00.zip
     python run_job.py jobs/2_ncu_20261013-224820_M08_ncu.zip
4. Each command ends with a line  VERDICT: PASS  or  VERDICT: FAIL  and says why.
   Do not leave the machine with a FAIL you can still fix (the usual one: GPU counters refused -> SETUP step 6).
5. Take  pc_runner/results/results_20261013-224820_M00.zip  and
         pc_runner/results/results_20261013-224820_M08_ncu.zip
   and put both in the repository folder:  gpujobs/inbox/
6. New session, type: continue
```
Staleness (a decision for the owner): ingest refuses a result when a bundled path (src, kernels, tests, bench,
scripts, colab/gpu_entry.py) changed after the pack commit. M15 will add code there. Either ingest these two results
before the first M15 commit, or accept an ingest with `--allow-stale` whose session records `git diff 072ee8c HEAD`
for the files the two jobs execute (bench/probe_gpu.py, bench/run_ncu.py, bench/ncu_workload.py, bench/run_dudect.py,
src/vcloak/gpu, src/vcloak/runs.py, kernels, colab/gpu_entry.py) and finds it empty. The agent does not choose.
For the ingest session:
- Ingest the probe first. Its rows have the METRIC-IDs of the Kaggle probe with runner pc-<gpu>: check how
  `_index_metrics` and check_metrics treat an ID that exists for two runners before trusting the index.
- Do not run `scripts/record_env.py` for the PC probe without asking: the `runner` block of STATE.md and docs/ENV.md
  describe the Kaggle T4 (ADR-025 point 4).
- Not verified: the kit has never run on a machine with a GPU. Its Windows and WSL2 paths, the Nsight Compute
  folder search and the counter check of check_setup.py were written from documentation, not from a run
  (runs/20261013-224907_M08_pc_runner_kit holds what could be run here: refusals without a GPU, the verifier on old result zips).
Confirm by running: `ls gpujobs/inbox/` shows both results_20261013-224820_*.zip
Then type: continue
Closed 2026-10-14 session 47: the owner ran both jobs on the PC (runner pc-rtx3050laptopgpu) and brought the kit
folder back; both results zips matched the SHA-256 of pc_runner/HANDOFF.md, were copied to gpujobs/inbox/ by the
agent and ingested, the probe first, without `--allow-stale` (no bundled path changed since 072ee8c). An ID that
exists for two runners is safe: index rows and the exporter are keyed by (METRIC-ID, run dir), check_metrics PASS.
`scripts/record_env.py` was not run for the PC probe. The superseded first attempt of job 2
(pc_runner/results/previous, counters still refused) was not ingested. Deviations of the PC setup from SETUP.txt
(no CUDA Toolkit, header wheels, standalone Nsight Compute extracted from its MSI): pc_runner/HANDOFF.md.

### ISSUE-48 [CLOSED 0856c6e] The ncu result of the PC runner is indexed but appears in no generated table or text; caveats of that result
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-14 session 47
1. Decision for the owner: how the PC ncu result is reported. `scripts/export_results.py` and
   `vcloak.bench.report_oblivious` pin the Kaggle run runs/20261012-040027_M08_ncu, so results/oblivious/
   ncu_divergence.csv, the S5 summary table, the paper table and the obliviousness section of
   docs/REPORT_CH4_NOTES.md still say NOT_MEASURED and "No dynamic divergence measurement". That is correct for the
   T4 and silent about the PC. Options: (a) a separate table and paragraph for runner pc-rtx3050laptopgpu with its
   own provenance, beside the unchanged T4 rows (proposal of the agent; ADR-025 point 3 forbids one figure and
   forbids replacing a T4 value, not a separate statement); (b) one sentence in the limitations only; (c) not
   reported. (a) and (b) need code in scripts/ and src/vcloak/bench; no job is pending, so nothing becomes stale.
2. Decision for the owner: `scripts/record_env.py` for the PC probe (ADR-025 point 4). Not run; the `runner` block
   of STATE.md and docs/ENV.md describe the Kaggle T4. Proposal of the agent: leave it so.
3. Caveats to carry into any text (all from runs/20261014-003929_M08_ncu/summary.json):
   - bitonic_pairs_global: the divergent AND the uniform counter are both 0 over 44 launches, so no branch target
     was counted at all and T-NCU-BRANCHEFF-BITONIC-PAIRS-GLOBAL is NOT_MEASURED. Its 0 divergent is not backed by
     a non-zero uniform count the way the other three are. The cause was not investigated (code without a
     counted branch target is one possible reading, not a finding).
   - The values are sums over launches of the `.avg` aggregate of the sm__sass_branch_targets_threads_* counters;
     the unit `branches` is the label of bench/run_ncu.py. What `.avg` averages over was not checked against the
     Nsight Compute documentation.
   - One run, seed 8, log2n 16, one GPU model. The code profiled is what nvrtc built for cc 8.6, not the T4 code of
     the SASS listing (ISSUE-19). Never write it as a T4 measurement or as proof for other sizes.
4. Low: the optional unit_tests command of job 20261013-224820_M00 exited 2 on the PC at collection (httpx and
   matplotlib are not in the package list of pc_runner/SETUP.txt; gpujobs/out/20261013-224820_M00/logs/03_unit_tests.txt).
   No test ran there. If the PC is used again: add the packages to SETUP.txt or leave the step out of PC jobs.
Resolution (2026-10-14, session 48, 0856c6e; decisions of the owner in the session request):
- Point 1: option (a). `report_oblivious --ncu-second` writes a table and a paragraph of its own for runner
  pc-rtx3050laptopgpu (section 4.O.5, results/oblivious/ncu_divergence_pc-rtx3050laptopgpu.csv,
  results/paper/ncu_second_table.tex); the T4 rows, ncu_divergence.csv and sidechannel_table.tex are unchanged.
  The reporting leads with the positive control (the validated null), in the notes and in docs/RESULTS_ANALYSIS.md.
- Point 2: the environment record stays the Kaggle T4; the PC is named in section 4.O.1 as the second measurement
  platform (ADR-025). record_env.py was not run for it.
- Point 3, bitonic_pairs_global: resolved by a lookup, no new run. The saved SASS listing has branch instructions
  for that kernel (one conditional), so the 0 / 0 is a counter that collected nothing: NOT_MEASURED (ANN-5 of the
  index; runs/20261014-014529_M08_issue48_report/sass_crosscheck.txt). The other three kernels are kept. The other
  caveats of point 3 are carried in the generated text. Why the instrumentation missed that kernel: not
  investigated, and not needed for the report.
- Wording: every generated place that reports ncu now states both platforms (4.O.2, 4.O.5, 4.O.6, 4.S,
  PAPER_UPDATES section 5).
- Point 4: httpx and matplotlib are in the install line of pc_runner/SETUP.txt. Not verified on the PC.

### ISSUE-49 [CLOSED c64ec32] M15 S2: parameters of the cells that the module does not fix, and what the runner still needs
BLOCKS: none (S2 takes the proposals below unless the owner says otherwise)   SEVERITY: medium   OPENED: 2026-10-14 session 49
Decisions for the owner (Divyansh). Each changes what the E6 numbers mean, so none is taken silently:
1. Send rate per user. The module says "Poisson send rate per user" without a value. Proposal: 0.2 messages/s
   (the default of bench/run_e2e.py): 2, 20 and 200 messages/s offered at 10, 100 and 1000 users.
2. SLOTS. The service default is 64 (development); 65536 is excluded (ISSUE-12: M15 gives no verdict for that
   size). At 200 messages/s an epoch of 200 ms receives 40 on average, so 64 slots will overflow in bursts.
   Proposal: one value for all cells and both modes, 256, named beside every number.
3. Reads at 1000 users. With the defaults (WINDOW_S 60, BUCKETS 64, CAND_K 128) a window holds about 12000
   messages at 200 messages/s, about 187 per bucket: above CAND_K, so `POST /v1/read` answers 503
   candidate_overflow (ADR-014, ISSUE-43) and the submit-to-readable latency of that cell would be mostly
   missing. This is arithmetic from the public parameters, not a measurement. Options: (a) keep the defaults
   and report the failed reads as the finding; (b) size BUCKETS or CAND_K for the cell and name the values.
   Proposal: (a) for the default layout plus one sized cell (b) at 1000 users, reported side by side.
4. Poll interval of the readers: 500 ms (default). It quantises submit-to-readable and is itself load: 2 reads
   per user per second, each a GPU open of CAND_K rows in V-cloak mode. Proposal: keep 500 ms, state it.
5. Acknowledgement: `stored` in both modes (default), so submit-to-ack is "durable" in both (ISSUE-23).
What S2 still needs before a job can be packed: a job spec bench/jobs/M15.json with `runner_required` and
`cpu_count_required` (ADR-024); PostgreSQL on the runner (ADR-008; the M14 S6 job has the pattern); the 10 Hz NVML
sampler and CPU utilisation around the cell (psutil is not installed on the laptop and is not in
requirements-gpu.txt); the DB size; the driver over modes x users x 2 repetitions. Not started.
Not verified in S1: the generator at 100 or 1000 users (largest local cell: 10 users); anything on a CUDA device
or on PostgreSQL; whether one generator process can offer 200 messages/s with a DPoP signature per request
without being the bottleneck itself (the summary records `send_lag_ms` for that).
Closed session 50 (the owner's decisions, ADR-027):
- Population: 10, 50 and 200 users, two per conversation, in place of 10, 100 and 1000. No cell at 1000 users, so
  point 3 (reads above CAND_K at 1000 users) does not arise; 1000 users is not measured end to end.
- 1. Rate: 0.15 messages per user per second, not the 0.2 proposed. Found while preparing S2 and put to the owner
  before packing: a conversation's bucket is fixed, 100 conversations in 64 buckets put 5 into each of two
  buckets, and at 0.2 the schedule of seed 15 can put 136 rows into one bucket-window (CAND_K 128), in 104 of
  240 alignments of the window; at 0.15 the bound is 106 and no alignment exceeds it (runs/20261014-062714_M15_s2_checks/bucket_bound.txt:
  arithmetic on the schedule, not a measurement). Offered: 1.5, 7.5 and 30 messages per second.
- 2. SLOTS 256, 4. poll 500 ms, 5. `ack: stored`: the proposals, unchanged (the owner did not object).
- What the runner needed is built: bench/jobs/M15.json (Kaggle, 4 vCPU), PostgreSQL through
  scripts/runner_stack.py, NVML at 10 Hz, CPU utilisation (psutil, added to requirements-gpu.txt), DB size, the
  driver bench/run_e2e_cells.py. The job is ISSUE-50.
- Still not verified, and not verifiable on the laptop: whether one generator process and one engine thread keep
  up with 200 users (400 reads per second asked for). On the numpy backend the 200-user cell acknowledged and
  read back every send but answered far fewer reads than asked (runs/20261014-064033_M15_vcloak_u200_r1_quick:
  a correctness run, no number of it is a result). On the T4 that is what the cell measures; `send_lag_ms`
  and the read count are in every summary so S3 can tell a slow service from a slow generator.

### ISSUE-50 [CLOSED 29a77d7] HUMAN ACTION REQUIRED — GPU JOB READY: the M15 end-to-end cells (job 20261014-065041_M15)
BLOCKS: M15   SEVERITY: high   OPENED: 2026-10-14 session 50
Why: S2 of M15 is the measurement itself: V-cloak and the baseline under load on the T4 with PostgreSQL behind the
service. Nothing of E6 exists until this job is ingested.
Do this:
```
GPU JOB READY — 20261014-065041_M15              (runtime not measured; plan for about 45 to 60 minutes)

1. Open https://www.kaggle.com  ->  Create > New Notebook > File > Import Notebook
   Pick:  colab/VCloak_GPU_Runner.ipynb
2. Settings > Accelerator > GPU T4 x2                    <- easy to miss
3. Settings > Internet > On                              <- this job installs PostgreSQL with apt-get
4. + Add Input > Upload, pick:  gpujobs/out/20261014-065041_M15/job.zip
5. Run Cell 1. It must print a GPU name (Tesla T4).
6. Run Cell 2 as it is (Kaggle unpacks the upload into a folder; the cell finds the job by itself).
7. Run Cell 3 and keep the tab open. It prints one line per cell, 12 cells:
   "cell  1/12  r1 u10  baseline exit 0  OK ..."
   If it prints "This job needs 4 vCPU" or "must run on kaggle": nothing was run. Tell me what it printed;
   do not move the job to Colab.
   If it stops at stack_up: PostgreSQL could not be installed (step 3). Turn the internet on and run Cell 3 again.
8. Take results_20261014-065041_M15.zip from the Output panel and put it in:  gpujobs/inbox/
9. New session, type: continue
```
What it runs: 2 modes x 10, 50 and 200 users x 2 repetitions = 12 cells, each 20 s warm-up + 120 s, 0.15 messages
per user per second, two users per conversation, SLOTS 256, sessions on, `ack: stored`.
Known risks, none a defect of the job:
- Kaggle has given this project 4 vCPU and 2 vCPU sessions. With 2 vCPU the job refuses, and the choice goes back
  to the owner.
- scripts/runner_stack.py has installed PostgreSQL on Colab (M14); it has not run on Kaggle before.
- If a cell fails or cannot keep up, the job records it and runs the next one. Nothing is shrunk or retried:
  bring the bundle back as it is and the reading goes to the owner (ADR-027).
Confirm by running: `ls gpujobs/inbox/` shows results_20261014-065041_M15.zip
Then type: continue

Closed session 51: the bundle came back from Kaggle (T4, 4 vCPU, runner session 20261014-013736) and is ingested;
7 commands exit 0, 12 cells and the driver run under runs/. The reading of the 200-user cells is ISSUE-51.

### ISSUE-51 [CLOSED ff4f587] DECISION OF THE OWNER — the 200-user cells ran with the load generator at its limit: how are they reported?
BLOCKS: none (S3 goes ahead; the default below applies to the 200-user rows until the owner says otherwise)   SEVERITY: high   OPENED: 2026-10-14 session 51
What came back (runs/20261014-074636_M15_s2_ingest_checks/cell_reading.txt; a reading of the ingested cells, none of it is an indexed metric):
- All 12 cells completed with exit 0 and no epoch overflow. At 10 and 50 users both modes sent on time (send lag
  p99 at most 3 ms), every send was acknowledged and read back, and the two repetitions agree within 7 % on every
  p50 and on every V-cloak p99. Only the baseline ack p99 differs between repetitions (a tail of a few ms).
- At 200 users the generator process used about 1.2 cores in BOTH modes (mean 118 to 121 % of one core inside the
  measured interval; 24 % at 10 users, 40 % at 50). The instrument was at its limit, so the 200-user latencies
  contain the generator's own queueing and are not the service's latency alone.
- 200 users, V-cloak: ack p50 of 3.2 s and 4.2 s in the two repetitions (p99 18 s and 30 s), sends late by
  76 / 107 ms at p50, one send lost per repetition (ReadError), the readers made 7387 and 5872 requests where
  the baseline cells made about 40000, one read refused with invalid_dpop_proof in r2, 23 and 19 missed epochs.
  The service process used 32 % and 25 % of a core: the service CPU was not what was saturated. The cause of
  the seconds of ack latency is NOT established (generator event loop, the engine thread, or both).
- 200 users, baseline: also degraded (ack p50 98 / 113 ms against 4.7 ms at 50 users; p99 1.5 s / 2.3 s).
- A3: every 200-user latency except the baseline readable p50 is more than 15 % apart between repetitions.
- `achieved_msgs_s` in the summaries counts acknowledged sends by their SCHEDULED time, so it equals the offered
  rate even when the acks arrive tens of seconds late. It is not a throughput under backlog; S3 must derive
  E2E-TPUT from the completion times in samples.csv and must not index that field at 200 users.
Options (ADR-027: nothing is shrunk, dropped or retried without the owner):
- (a) DEFAULT, applied by S3 unless told otherwise: the 200-user rows are indexed as UNSTABLE with the reason
  "load generator at its limit in both modes"; no added-latency figure and no verdict for 200 users; the
  presenter note on GPU load is answered for 200 users from the telemetry with that caveat. No further job.
- (b) Measure 200 users again with a generator that keeps up (several generator processes): new code, a new
  Kaggle job of the 4 cells, about 15 minutes of runner time. This is a retry in the sense of ADR-027.
- (c) Add a cell between 50 and 200 users (for example 100) to find where the sends stop being on time: a new job.
To choose: tell the agent "ISSUE-51: a", "b" or "c" at the start of a session. Saying nothing means (a).

Closed session 52: the owner chose (a) and fixed the wording (ADR-028). The evaluated scale is 10 and 50 users, both
modes; no 100-user cell, no second run of 200. The 200-user rows are indexed as UNSTABLE with the cause and are in no
table (runs/20261014-081645_M15_e2e_metrics; section 4.E.6 of the notes). The claim, the "not a scaling curve"
sentence and the future work are in the module Amendments, section 4.E.5 and 4.E.7 of docs/REPORT_CH4_NOTES.md and
docs/REFINEMENTS.md. `achieved_msgs_s` now counts the acknowledgements that arrived inside the measured interval.
The lost send (runs/20261014-081739_M15_s3_checks/lost_send.txt): it is neither of the two cases asked about.
- Not a generator timeout: the three failed sends (one in r1, two in r2, one of them in the warm-up) are httpx
  `ReadError`, a connection that broke while the answer was awaited; a timeout would be `ReadTimeout` after 30 s.
  The reads of the same cells show the same error (1 and 3), so it is not particular to the message path.
- Not "accepted and never readable": in all 12 cells no acknowledged send was left unread by its peer. The failed
  sends were never acknowledged, and only `ack: stored` (201) means durable (ADR-016).
- Not known: whether the service stored a send whose answer never arrived. The generator dropped such a payload
  from its watch list, and the rows per closed window bracket the stored rows only to within 114 to 296 sends.
  A local 200-user run (numpy, quick: runs/20261014-080401_M15_vcloak_u200_r1_quick) had no failed send, so the
  error is not reproduced. The generator now keeps watching such a payload (`errors_readable`). Carried by ISSUE-52.
- A reading that came out of the same file: the rows stored before each window boundary sit at the lower end of
  the bracket, so a send entered the service's queue shortly before its answer, not when it was submitted. The
  seconds were spent before the scheduler queue: in the generator, in the connection, or in the HTTP layer of the
  service before `submit()`. The epoch path is not where they went. Which of the three is not separated; the CPU
  figures (generator 118 to 121 % of a core, service 25 to 32 % in the V-cloak cells) are what the owner's cause
  rests on.

### ISSUE-52 [OPEN] Three sends of the 200-user V-cloak cells got no answer (httpx ReadError): cause not found, and whether they were stored is not known
BLOCKS: none (the cells are excluded from every table by ISSUE-51; no valid cell has a failed send or a failed read)   SEVERITY: low   OPENED: 2026-10-14 session 52
What: runs/20261014-015212_M15_vcloak_u200_r1 (user 69, submitted 27.56 s) and runs/20261014-020839_M15_vcloak_u200_r2
(user 193 at 4.41 s, in the warm-up; user 2 at 69.43 s). Each `POST /v1/messages` ended in `ReadError` with no HTTP
status. The same cells have 1 and 3 `ReadError` on reads and one read refused with `invalid_dpop_proof` (r2). The
service log of both cells holds no error line. Evidence: runs/20261014-081739_M15_s3_checks/lost_send.txt.
Not a correctness defect on this evidence: nothing acknowledged was lost. What stays open is (1) why a connection
broke under this load (not reproduced on the laptop), (2) whether such a send is stored without the client
learning it, which would give a duplicate when a client retries, (3) the one `invalid_dpop_proof`.
How to settle it: any later 200-user run with the current generator reports `errors_readable` and `error_ms` for
such a send; that answers (2) in the run that shows the error. No job is asked for: the owner decided that 200
users is not run again (ISSUE-51), so this waits for the multi-process harness of the future work.

### ISSUE-53 [OPEN] HUMAN ACTION: V-cloak is called "a GPU-optimised ORAM" in material outside the repository; say what "grouping" means
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-14 session 53
What was found: the repository never uses the term (runs/20261014-084740_M15_s4_checks/terminology_grep.txt: no
occurrence in tracked files, binaries, untracked files or history). So the wording you saw is in something the
agent cannot open: slides, an abstract, a proposal or a submission form.
What you do (two things, neither blocks the build):
1. In every such document replace the description of our system with: "a GPU-resident oblivious permutation
   layer for message-order privacy". Where ORAM is named, use the sentence of ADR-030 (session 54, your final
   wording; it replaces the "V-cloak is not an ORAM" sentence first given here): "This is a prototype. We
   implement the oblivious shuffle, the component ORAM constructions build on, and apply it to message ordering.
   Full access-pattern hiding is the remaining part of an ORAM and is out of scope for this prototype, because it
   does not fit a 200 ms real-time budget on this hardware." Never "part of ORAM" without naming the component.
   If one of these documents should live in the repository (for M19 or M22), put it under review/ and say so.
2. Answer one question. Your wording says V-cloak conceals "order and grouping". ai/PROJECT_BRIEF.md section 5
   lists partial conversation identity (shared HMAC-style buckets), window ids and the number of real messages per
   window as known leakage. Which grouping do you mean (which messages belong to one conversation, or which were
   stored together), and is it meant as a claim? Until you answer, the paper and the report claim order only
   (ADR-029 item 4).
Closed when: you report 1 as done and answer 2; the answer is recorded as an amendment of ADR-029.
Update 2026-10-14 session 54: the wording of item 1 was replaced by the human's final ORAM wording (ADR-030); the
in-repository page that uses it is review/TOPIC_ALIGNMENT.md. Items 1 (outside documents) and 2 (grouping) are open.

### ISSUE-54 [OPEN] Dashboard: a zero bar is labelled "0.0e+0%", and the GPU framing points are not rendered yet
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-14 session 54
What was found (evidence/screens/M18_dashboard_*_20261014.png, runs/20261014-092058_M18_s1_checks): web/js/charts.js
formats the value 0 of E2E-GPUUTIL-U10 in exponent form on the bar label. dashboard.js does not read the new
`framing`, `groups` and `excluded` fields of dashboard.json, so the GPU-utilisation framing is in the JSON but not on
the page. Neither changes a value.
Closed when: M18 S2 renders the framing above the GPU group and the excluded user counts with their cause, and S3
fixes the label; checked by a new capture in both themes.
Update 2026-10-14 session 55: S2 renders the framing above the GPU group, the group notes, and the excluded 200-user
count with its cause (evidence/screens/M18_dashboard_{light,dark}_20261014.png, runs/20261014-093346_M18_s2_checks). The 0.0e+0% label remains: S3.

### ISSUE-55 [OPEN] Two trace tests of test_eval_security failed once inside the full suite and passed alone and on rerun
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-14 session 55
What was found (runs/20261014-093346_M18_s2_checks/pytest_all_first_jsbug.txt): TestTrace.test_write_epoch_issues_the_same_launches_for_every_batch
reported launch_list_identical_for_every_batch and pair_schedule_identical_for_every_batch False, and the trace stage
of TestCli returned 1. The same full run also had 8 browser failures from a JS syntax error of this session (fixed).
Alone (5 passed) and in the full rerun (runs/20261014-093346_M18_s2_checks/pytest_all.txt, 2198 passed) both pass. Cause not found: a shared state
between tests (an in-process server of the browser tests while the trace hooks record launches) is a guess, not shown.
These are simulator (numpy) gates of E3, not GPU results; no metric changes.
Closed when: the cause is found (e.g. pytest -p no:randomly order, or the browser tests then the trace tests in one
process, repeated) and fixed, or 5 full-suite runs pass with the result recorded.
