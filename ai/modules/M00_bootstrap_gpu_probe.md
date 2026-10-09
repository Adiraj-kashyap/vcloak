# M00 — Bootstrap and GPU probe
owner: Aditya · depends_on: none · est_sessions: 1 · human_gates: CUDA driver/toolkit install (if missing)

## Goal
A reproducible Python project that can see the GPU, compile a CuPy RawKernel, and record the hardware
facts every later measurement depends on.

## Required reading
- `ai/PROTOCOL.md` (whole; first session only) · `ai/CONVENTIONS.md §1, §5, §6` · `ai/GPU_GUIDE.md §1, §2, §8`
- `ai/ARCHITECTURE.md §3` (layout only)

## Deliverables
`pyproject.toml`, `requirements.lock`, `.gitignore`, `Makefile` **or** `tasks.py` (Windows-friendly task runner),
`src/vcloak/__init__.py`, `src/vcloak/config.py`, `src/vcloak/gpu/runtime.py`, `src/vcloak/gpu/telemetry.py`,
`scripts/gpu_probe.py`, `scripts/check_metrics.py`, `scripts/new_run.py` (creates a run dir + manifest),
`tests/unit/test_config.py`, `tests/gpu/test_runtime.py`, `tests/conftest.py`, `docs/ENV.md`.

## Steps
- **S1 Environment detection.** Run `nvidia-smi`, `nvcc --version` (optional), `python --version`, the OS.
  If there is no NVIDIA driver/GPU: open a HUMAN ACTION issue (install the driver + CUDA Toolkit 12.x,
  or 11.x for older GPUs) and stop. Check: `nvidia-smi` exits 0.
- **S2 Virtual env and dependencies.** `python -m venv .venv`; install `numpy scipy cryptography argon2-cffi
  cupy-cuda12x nvidia-ml-py pytest ruff matplotlib pandas fastapi uvicorn httpx websockets "psycopg[binary]"`.
  Then `pip freeze > requirements.lock`. Check: `python -c "import cupy; print(cupy.cuda.runtime.getDeviceCount())"` ≥ 1.
- **S3 Package skeleton.** Create the layout from ARCHITECTURE §3 (empty `__init__.py` files), `config.py`
  with the parameters from PROJECT_BRIEF §7, and conftest markers (`gpu`, `integration`, `slow`). Check: `pytest -q -m "not gpu"` passes.
- **S4 Runtime + telemetry.** `runtime.py`: device properties (name, CC, SM count, VRAM total/free,
  mem clock, bus width, theoretical peak bandwidth), and a `compile(path, names)` helper around `RawModule`.
  `telemetry.py`: an NVML snapshot plus a 10 Hz sampler thread (see GPU_GUIDE §6). Check: `pytest -q tests/gpu/test_runtime.py`.
- **S5 GPU probe run.** `scripts/gpu_probe.py`: compile a vector-add RawKernel and verify its result; measure the device-to-device
  copy bandwidth (CUDA events, 256 MiB, 30 runs); compute `max_log2n` (GPU_GUIDE §8). Save to `runs/<ts>_M00_probe/`.
  Check: manifest.json + summary.json exist, and the vector-add result is correct.
- **S6 Tooling scripts.** `new_run.py` (makes the run dir, writes manifest with git sha/env/telemetry),
  `check_metrics.py` (G2: every METRICS_INDEX row's run dir exists; scans `results/` and `docs/` for numbers
  tagged `<!--M:ID-->` and verifies each ID is in the index). Check: both run without error.
- **S7 Record env.** Fill `STATE.md → env` (os, wsl, python, gpu, cc, vram_gb, driver, cuda, cupy, nvcc yes/no,
  ncu yes/no, max_log2n, peak_bw_gbs). Write `docs/ENV.md`.

## Metrics to record
`ENV-PEAK-BW` (theoretical, GB/s), `ENV-D2D-BW` (measured median, GB/s), `ENV-MAX-LOG2N`, `ENV-VRAM-FREE`.

## Audit checklist
- A1 `cupy` sees the GPU and a RawKernel compiles and runs (test output saved).
- A2 STATE.env is fully filled; unknown fields say `unknown` with a reason.
- A3 The measured D2D bandwidth is ≤ the theoretical peak (sanity check).
- A4 The task runner has targets: `test`, `test-gpu`, `probe`, `lint`.
- G1–G10.

## Pitfalls
- Laptop hybrid graphics: make sure the NVIDIA GPU (not the iGPU) runs Python; record the device name.
- On battery, clocks drop. Plug in and record `power_source` in the manifest.
- `cupy-cuda12x` must match the driver's supported CUDA major version (`nvidia-smi` header).

## Presenter notes
1. Why CuPy RawModule instead of a CMake/pybind build? (ADR-001)
2. What is the theoretical peak bandwidth of your GPU and how was it computed?
3. How does `max_log2n` follow from VRAM?

## Next: M01
