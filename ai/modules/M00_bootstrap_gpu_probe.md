# M00 — Bootstrap (local, no GPU) and the free GPU runner
owner: Aditya · depends_on: none · est_sessions: 1–2 (one local + one runner round-trip) · human_gates: give your name/email once for commit attribution; open the Colab/Kaggle notebook once

## Goal
A reproducible Python project that runs fully on a GPU-less laptop via the `numpy` thread-model backend,
plus a verified free remote runner and a working pack → upload → ingest loop.

## Required reading
- `ai/PROTOCOL.md` (whole; first session only) · `ai/GPU_RUNNER.md` (whole) · `ai/CONVENTIONS.md §1, §5, §6`
- `ai/GPU_GUIDE.md §1, §2, §8` · `ai/ARCHITECTURE.md §3` (layout only)

## Deliverables
`pyproject.toml`, `requirements.lock`, `requirements-gpu.txt`, `.gitignore`, (`setup/bootstrap.*` already ship with the kit), `tasks.py` (cross-platform task
runner; `make` optional), `src/vcloak/__init__.py`, `config.py`, `src/vcloak/gpu/runtime.py` (backend
selection), `src/vcloak/gpu/sim.py` (simulator registry), `src/vcloak/gpu/telemetry.py`,
`scripts/gpujob.py` (pack/ingest/verify), `scripts/new_run.py`, `scripts/check_metrics.py`,
`colab/gpu_entry.py` (+ the notebook already shipped in `colab/`), `gpujobs/{out,inbox,done}/.gitkeep`,
`tests/unit/test_config.py`, `tests/unit/test_runtime_backend.py`, `tests/conftest.py`, `docs/ENV.md`.

## Steps
- **S1 Local environment — run the bootstrap for the human; do not make them do it by hand.**
  Detect the OS and run `setup/bootstrap.ps1` (Windows) or `setup/bootstrap.sh` (macOS/Linux). It installs
  Python and Git if missing, creates `.venv`, installs the CPU package set, runs `git init`, and sets the
  git identity. Ask the human for their name and email **once** (one `AskUserQuestion`-style prompt, or pass
  them as the script's two arguments if they are already in the conversation) — never leave it unset, because
  commit attribution is a Review-3 requirement.
  If the script reports that it installed Python or Git and exited, tell the human to reopen their terminal
  (Windows PATH refresh) and say `continue`; resume at this same step, which is idempotent.
  Then `pip freeze > requirements.lock`, and write `requirements-gpu.txt` listing what the runner adds
  (`cupy-cuda12x`, `nvidia-ml-py`). CuPy is **not** installed locally — it needs a GPU.
  Check: `.venv` exists, `git config user.name` is non-empty, and `pytest -q -m "not gpu"` collects and passes.
- **S2 Package skeleton + config.** Layout per ARCHITECTURE §3; `config.py` with PROJECT_BRIEF §7 parameters;
  conftest markers `gpu`, `integration`, `slow` and a `backend` fixture. Check: `python -c "import vcloak, vcloak.config"`.
- **S3 Backend selection.** `runtime.py`: `get_backend()` reads `VCLOAK_BACKEND` (`auto|cupy|numpy`), returns a
  namespace with `xp`, `name`, `is_gpu`, and `device_info()` (on numpy: the host CPU, `is_gpu=False`).
  `sim.py`: a registry mapping kernel name → NumPy twin, with `register(name)` used by later modules.
  Check: `VCLOAK_BACKEND=numpy python -c "from vcloak.gpu.runtime import get_backend; print(get_backend().name)"` → numpy;
  `VCLOAK_BACKEND=cupy` on this laptop fails with a clear "no GPU, use the runner" message, not a traceback.
- **S4 Telemetry + run dirs.** `telemetry.py` (NVML snapshot + 10 Hz sampler; a no-op recording
  `available:false` when NVML is absent, so local runs still produce a manifest). `new_run.py` writes the
  manifest from LOGGING_AND_AUDIT §2 including `backend`, `runner`, `session_id`. Check: a dummy run dir validates.
- **S5 Job bridge.** `scripts/gpujob.py`:
  `pack <Mxx> [--quick] [--params k=v]` → `gpujobs/out/<job>/job.zip` (src, kernels, tests, bench, job.json,
  requirements-gpu.txt, gpu_entry.py; excludes .git, runs, web/data, .venv) + prints the bundle SHA-256;
  `ingest [--file …]` → verifies job id, bundle sha and git sha, copies `runs/**` in, prints a summary, moves the
  bundle to `gpujobs/done/`; `verify <zip>` → checks without ingesting.
  Check: pack → unzip into a temp dir → `python gpu_entry.py --job job.json --dry-run` lists the commands;
  a hand-corrupted results zip is **rejected** by ingest.
- **S6 Runner round-trip (human gate).** Pack the M00 probe job: it prints `nvidia-smi`, the device
  properties (name, CC, SMs, VRAM, mem clock, bus width, theoretical peak bandwidth), compiles and runs a
  CuPy vector-add RawKernel, measures D2D copy bandwidth (CUDA events, 256 MiB, 30 runs), and computes
  `max_log2n`. Open the `GPU JOB READY` issue and stop. Next session: ingest and verify the vector-add result is correct.
- **S7 Record env.** Fill `STATE.md → env` for both sides: `local` (os, python, cpu, ram) and `runner`
  (provider, gpu, cc, vram_gb, driver, cuda, cupy, nvcc, ncu, max_log2n, peak_bw_gbs, session_id). Write `docs/ENV.md`.

## Metrics to record
`ENV-PEAK-BW` (theoretical GB/s), `ENV-D2D-BW` (measured median GB/s, backend cupy), `ENV-MAX-LOG2N`, `ENV-VRAM-FREE`.

## Audit checklist
- A1 `pytest -m "not gpu"` passes locally with no GPU present, and `sim.py` is importable.
- A1b `git config user.name` and `user.email` are set in this repository (attribution works).
- A2 `gpujob.py pack` → `ingest` round trip works, and a tampered bundle is rejected (test output saved).
- A3 The ingested probe shows a real NVIDIA GPU; `STATE.env.runner` is filled from it, not typed by hand.
- A4 The measured D2D bandwidth is ≤ the theoretical peak.
- A5 `check_metrics.py` rejects a performance metric recorded with `backend: numpy` (self-test).
- G1–G10.

## Pitfalls
- Colab may hand out a different GPU model between sessions — that is why `session_id` and `gpu` are in every manifest.
- Do not `pip install cupy` locally: it will fail or silently install a CPU-less wheel. The runner has it.
- Keep the bundle small (< ~20 MB); never pack `runs/` or `.venv`.

## Presenter notes
1. Why can't the laptop's integrated GPU run this? (ADR-010 — shared memory breaks the threat model)
2. What does the `numpy` backend prove, and what can it never prove?
3. How does a number get from Colab into the repo without anyone retyping it?

## Next: M01
