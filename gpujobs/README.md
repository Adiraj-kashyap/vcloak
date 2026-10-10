# gpujobs/ — the bridge between this laptop and a free cloud GPU

| Folder | What goes here | Who puts it there |
|---|---|---|
| `out/<job-id>/job.zip` | a packed measurement job | Claude (`scripts/gpujob.py pack …`) |
| `inbox/results_<job-id>.zip` | the finished results from Colab/Kaggle | **you**, after downloading them |
| `done/` | bundles already ingested | Claude (`scripts/gpujob.py ingest`) |

Your part, each time Claude says `GPU JOB READY`:
1. Open `colab/VCloak_GPU_Runner.ipynb` in Google Colab (or Kaggle for long jobs).
2. Turn the GPU on: Colab `Runtime → Change runtime type → T4 GPU`; Kaggle `Settings → Accelerator → GPU`.
3. Run the cells; upload `out/<job-id>/job.zip` when asked.
4. Drop the downloaded `results_<job-id>.zip` into `inbox/`.
5. New Claude Code session → type `continue`.

The zips are gitignored; the small `job.json` next to each one is committed, so the evidence trail survives.
