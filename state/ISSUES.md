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

### ISSUE-7 [OPEN] Telemetry during a timed section: 1 sample, taken at idle
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

### ISSUE-11 [OPEN] M06 smoke timings are UNSTABLE / taken at a low SM clock
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

### ISSUE-12 [OPEN] write_epoch is dominated by host work; at SLOTS 65536 the smoke median is above EPOCH_MS
BLOCKS: none   SEVERITY: medium   OPENED: 2026-10-11 session 12
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

### ISSUE-13 [OPEN] HUMAN ACTION REQUIRED — GPU JOB READY: M07 performance sweeps (job 20261011-224124_M07)
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
