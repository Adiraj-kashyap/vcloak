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

### ISSUE-12 [OPEN] write_epoch is dominated by host work; at SLOTS 65536 the p99 is above EPOCH_MS
BLOCKS: M15   SEVERITY: high   OPENED: 2026-10-11 session 12
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

### ISSUE-17 [OPEN] M08 dudect: three target series FAIL at N = 100000 (aead_conv, write_epoch whole call, aead_tag)
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
3. ISSUE-25.
What M14 may write until then: with symmetric staging no timing difference between the classes was detected for AEAD
open at N = 100000 per class in two seeds, and the FAILs of the S2 staging are reproduced with identical contents. It
must not write that AEAD open is constant time, and nothing about the write path beyond the measured series.

### ISSUE-18 [OPEN] M08 ncu: the runner refuses the GPU performance counters (ERR_NVGPUCTRPERM); divergence is NOT_MEASURED
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

### ISSUE-25 [OPEN] M08 dudect: two device-stage series of the write_epoch diagnostics FAIL at seed 8 (write_epoch_age, write_epoch_fresh)
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
