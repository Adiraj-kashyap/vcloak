---
name: gpu-job
description: Pack a CUDA measurement job for the free Colab/Kaggle runner, or ingest a finished result bundle. Use whenever a step needs real GPU execution, timings, dudect, Nsight or SASS, and whenever the user says results are ready or mentions gpujobs/inbox.
---
There is no GPU on this machine. Follow `ai/GPU_RUNNER.md`.

**Which half am I in?**
Run `ls gpujobs/inbox/`. If a `results_*.zip` is there → INGEST. Otherwise → PACK.

**PACK (end of a prep session)**
1. Confirm the local work is finished and `VCLOAK_BACKEND=numpy pytest -q -m "not gpu"` passes.
2. Commit first (the bundle records the git sha): `git add -A && git commit -m "<Mxx>: ... [S..] [owner:..]"`.
3. `python scripts/gpujob.py pack <Mxx> [--quick] [--params ...]` → `gpujobs/out/<job>/job.zip`.
4. Open an issue `GPU JOB READY — <job>` AND print the same thing in the handoff. It must be
   **self-contained** — the human should never have to open another file to act on it. Use this shape,
   filling in the real job id, runner choice and expected runtime:

   ```
   GPU JOB READY — <job-id>              (~<n> min on the runner)

   1. Open https://colab.research.google.com  ->  File > Upload notebook
      Pick:  colab/VCloak_GPU_Runner.ipynb
   2. Runtime > Change runtime type > T4 GPU > Save        <- easy to miss
   3. Run Cell 1. It must print a GPU name (e.g. Tesla T4).
   4. Run Cell 2, upload:  gpujobs/out/<job-id>/job.zip
   5. Run Cell 3 (keep the tab open), then Cell 4 to download results_<job-id>.zip
   6. Put that file in:  gpujobs/inbox/
   7. New session, type: continue

   Long job? Use Kaggle instead: Create > New Notebook > File > Import Notebook,
   Settings > Accelerator > GPU T4 x2, add job.zip via "+ Add Input > Upload",
   run Cell 2 as it is (Kaggle unpacks the uploaded zip into a folder; Cell 2 finds the job under
   /kaggle/input by itself, so never tell the human to type a path to job.zip), and take the results
   from the Output panel.
   Full detail: YOUR_CHECKLIST.md
   ```
   First GPU job of the project? Add one line: "if you have never used Colab, a Google account is all
   you need — there is nothing to install."
5. Set `status: BLOCKED_HUMAN`, record the session, commit, hand off. Do NOT invent placeholder numbers.

**INGEST (start of the next session)**
1. `python scripts/gpujob.py ingest` — it verifies the job id, the bundle sha and the git sha, then copies
   run dirs into `runs/` and prints a summary. If verification fails, stop and report; never hand-edit a manifest.
2. Check each command's exit code in `result.json`. A non-zero exit is a real failure: open an issue and fix
   it in the next prep session.
3. Apply the module's acceptance gates to the ingested numbers (CV, clock stability, bit-exactness vs the
   simulator, dudect |t| thresholds).
4. Append to `state/METRICS_INDEX.md` with `backend: cupy`, the runner and the run dir; then audit and close the session.

Never record a GPU metric that is not in an ingested bundle, and never let a `numpy` number stand in for one.
