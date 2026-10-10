# ISSUES (format: ai/LOGGING_AND_AUDIT.md §6; human actions use ai/PROTOCOL.md §7)

### ISSUE-1 [CLOSED a45088b] setup/bootstrap.ps1 failed to parse on Windows PowerShell 5.1
BLOCKS: none   SEVERITY: low   OPENED: 2026-10-11 session 1
The kit script was UTF-8 without a BOM; PowerShell 5.1 read it as ANSI, turned the em-dashes into quote
characters and aborted before doing anything ("The term 'tick' is not recognized"). Fixed by adding a UTF-8 BOM
to the file (no other change). It then ran clean: .venv, packages, git init, identity. Teammates get the fix.

### ISSUE-2 [OPEN] HUMAN ACTION REQUIRED — GPU JOB READY: M00 runner probe (job 20261011-014756_M00)
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
