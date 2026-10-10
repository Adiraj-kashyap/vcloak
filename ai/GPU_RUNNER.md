# GPU RUNNER — running V-cloak's CUDA work without a GPU in the laptop

This project needs an **NVIDIA (CUDA)** GPU. The development laptop has none. This file defines the
free, zero-cost execution path and the exact protocol the agent follows. Nothing about the project's
design changes: the same `.cu` kernels, the same tests, the same metrics — only *where* they execute.

## 1. Why not the laptop's integrated GPU
An Intel/AMD integrated GPU is not a drop-in substitute, for two reasons, and the second is fatal:
1. **No CUDA.** iGPUs run OpenCL/SYCL/DirectML. Porting the kernels would change the project, invalidate
   the SASS/Nsight evidence, and break the comparison with published CUDA work.
2. **It breaks the security claim.** An iGPU has no private VRAM — it shares system RAM with the CPU.
   V-cloak's central claim is that `K_order`/`K_tag` live in device memory that a host-level dump never sees.
   On an iGPU that separation does not exist, so the threat model collapses.
State this in the review if asked: *"a discrete GPU is a requirement of the threat model, not a performance preference."*

## 2. The chosen runners (both free, no credit card)
| | **Google Colab** (primary) | **Kaggle Notebooks** (backup / long runs) |
|---|---|---|
| GPU | typically a T4 (16 GB), not guaranteed | T4 ×2 or P100, selectable |
| Session cap | up to 12 h, idle timeout, access is rationed | up to 12 h per session |
| Quota | unpublished; heavy use gets throttled | a published weekly GPU quota in account settings (commonly ~30 h) |
| Best for | quick kernel iterations (M03–M06) | long sweeps and dudect (M07, M08) |
| Sign-in | Google account | Kaggle account (phone-verify to enable GPU) |
Both give a **discrete NVIDIA GPU with CUDA, nvcc, and Nsight Compute**, which is everything this
project needs. Record which runner produced every number (`env.runner` in each manifest).

**Rule: never compare timings across runners or across sessions.** One figure = one runner = one session.
A sweep that is split across sessions must be re-run whole on one runner before it is reported.

## 3. The two local backends (so work continues without any GPU)
`vcloak.gpu.runtime` picks a backend from `VCLOAK_BACKEND`:
- `cupy` — the real GPU path. Used on the runner.
- `numpy` — the **thread-model simulator**: the same kernel index arithmetic (thread id → pair, mask,
  xor-swap) executed with NumPy arrays over a vector of thread ids. It reproduces kernel *semantics*
  exactly, so correctness tests run on the laptop; it says nothing about speed.
- `auto` (default) — `cupy` if a device is present, else `numpy`.

**Hard rule:** a number produced under the `numpy` backend is **never** a performance result. Timing,
bandwidth, dudect, Nsight and SASS metrics come only from a `cupy` run on a runner. The manifest
records `backend`, and `scripts/check_metrics.py` rejects any performance metric whose run used `numpy`.

## 4. Job protocol (zip shuttle — the default, needs no GitHub)
```
LOCAL (agent)                    HUMAN (2 min)                 RUNNER (Colab/Kaggle)
scripts/gpujob.py pack M07  ──►  upload job.zip          ──►   notebook runs gpu_entry.py
   gpujobs/out/<job>.zip         to the notebook               writes results_<job>.zip
scripts/gpujob.py ingest    ◄──  put it in gpujobs/inbox/ ◄──  download it
   → runs/ + METRICS_INDEX
```
- **pack** builds a self-contained bundle: `src/`, `kernels/`, `tests/`, `bench/`, `requirements-gpu.txt`,
  `job.json` (module, step, command list, params, seed, git sha, quick flag) and `gpu_entry.py`.
  It prints a SHA-256 of the bundle and writes `gpujobs/out/<job>/job.json` locally for later verification.
- **gpu_entry.py** on the runner: prints the GPU/driver/CUDA/CuPy versions, installs nothing it does not
  need, runs each command in `job.json`, captures stdout/stderr per command, collects `runs/**`, and zips
  everything to `results_<job>.zip` with a `result.json` (job id, bundle sha, per-command exit codes, env).
- **ingest** verifies the bundle sha and job id match what was packed, refuses a result whose `git_sha`
  differs from the commit it was packed from (prevents stale evidence), copies run dirs into `runs/`,
  appends metrics, and writes a `GPU-JOB` entry in the SESSION_LOG.

A job is **one module's measurements**, not the whole project. Keep bundles under ~20 MB (no `runs/`, no `.git`).

## 5. Session flow when a module needs the GPU
The agent cannot upload files itself, so a GPU module splits into two sessions:
1. **Prep session.** Write/modify kernels, run all `numpy`-backend correctness tests locally, pack the job,
   then set `status: BLOCKED_HUMAN` with a `GPU JOB READY` issue naming the exact file to upload and the
   notebook to open. Hand off.
2. **Ingest session.** The human has dropped `results_<job>.zip` into `gpujobs/inbox/`. The agent ingests,
   checks the acceptance gates, records metrics, audits and completes the step.
If a result shows a failure, the fix goes in the next prep session — never fake a pass to move on.

## 6. What the human does (every GPU job, ~2 minutes)
1. Open `colab/VCloak_GPU_Runner.ipynb` in Colab (File → Upload notebook) **or** Kaggle (Create → Notebook → Import).
2. Runtime → Change runtime type → **T4 GPU** (Kaggle: Settings → Accelerator → GPU).
3. Run cell 1 (environment), then upload `gpujobs/out/<job>.zip` when cell 2 asks.
4. Run the remaining cells. When it finishes, `results_<job>.zip` downloads automatically.
5. Move that file into the repo's `gpujobs/inbox/` folder, open a new Claude Code session, type `continue`.

## 7. Runner hygiene (affects whether numbers are usable)
- Colab/Kaggle GPUs are **shared and can be throttled**; always capture NVML telemetry and report CV.
- Re-run any sweep whose CV > 10% or whose SM clock moved more than 15%; record both runs, never drop one.
- The runner's CPU is not the laptop's CPU. The GPU-vs-CPU crossover (M07) must take **both** sides from
  the same runner session, and the write-up must say so.
- Record `env.runner`, `env.gpu`, `env.session_id` (the notebook's start timestamp) in every manifest.
