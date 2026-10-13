# V-cloak PC Runner Handoff

As of 2026-10-14. Runner: `pc-rtx3050laptopgpu`.

Both GPU jobs finished with **VERDICT: PASS**. No CUDA Toolkit was installed on this
machine and none is needed.

## 1. Outcome — the files to carry

| Zip | Job | Size | Verdict |
|---|---|---|---|
| `results_20261013-224820_M00.zip` | 1, probe (M00) | 7.4 KB | PASS |
| `results_20261013-224820_M08_ncu.zip` | 2, ncu branch counters (M08, ISSUE-18) | 76 KB | PASS |

Both in `D:\vclock\pc_runner\results\`. SHA-256, to verify the copy after transfer:

```
2c4678b9bc4a1b17a5c3bb77b2630985bb4d1b870ad2252f22603970add6f757  results_20261013-224820_M00.zip
fe81ccd49269acff0f14a3c6ff43672546bee0290f20238fcc9e742bdbe3527b  results_20261013-224820_M08_ncu.zip
```

`results\previous\20261014-003959_results_...M08_ncu.zip` (6 KB) is job 2's first attempt,
which recorded NOT_MEASURED before the GPU counters were permitted. Superseded, not
deleted. **Do not copy it into the inbox.**

## 2. Next steps

1. Copy the two zips above onto the transfer medium. Only those two.
2. Re-check both SHA-256 values after the transfer. A corrupted zip fails ingest with a
   bundle-hash error, which looks like a job failure rather than a copy failure.
3. Drop both into `gpujobs/inbox/` in the repo folder on the laptop.
4. Open a new Claude Code session there and type `continue`.

Never edit a zip, never rename one, never type a number off a screen into the project.
Everything in this file is for reading only; ingest reads the zips directly.

Nothing else from this PC needs to travel. The zips already carry the runner name, the
environment record, the logs and the measurements.

**The laptop has no NVIDIA GPU, and it does not need one.** It never runs a job, it ingests
one. Nothing in the sections below has to be installed there: no CUDA, no CuPy, no `ncu`, no
GPU Python environment. In the project's own terms that laptop is the runner called `local`,
and `scripts/check_metrics.py` refuses every GPU metric carrying that name — which is
precisely why these measurements had to be produced on a GPU machine and carried over as
zips.

Put this summary anywhere except `gpujobs/inbox/`. That folder takes the two zips and
nothing else.

## 3. The machine as built

| Item | Value |
|---|---|
| Runner name | `pc-rtx3050laptopgpu` (derived from the GPU; never set by hand) |
| GPU | NVIDIA GeForce RTX 3050 Laptop GPU, 4 GB VRAM, compute capability 8.6 |
| Driver | 610.88, CUDA UMD 13.3 |
| OS | Windows 11 Home Single Language 10.0.26300, native (not WSL2) |
| Python | 3.12.10 via `winget install Python.Python.3.12` |
| venv | `D:\vclock\pc_runner\.venv` (594 MB) |
| CuPy | `cupy-cuda12x` 14.2.0 |
| CUDA headers / NVRTC | pip wheels: `nvidia-cuda-nvrtc-cu12` 12.9.86, `nvidia-cuda-runtime-cu12` 12.9.79, `nvidia-cuda-cccl-cu12` 12.9.27 |
| Other packages | numpy 2.5.4, scipy 1.18.1, nvidia-ml-py 13.615.71, cryptography 50.0.2, pytest 9.1.1, cuda-pathfinder 1.8.3 |
| `ncu` | Nsight Compute 2026.3.1.0, standalone, extracted to `D:\vclock\nsight\...\target\windows-desktop-win7-x64\` (1.3 GB) |
| `nvcc` | absent, not needed |
| GPU counters | allowed to all users (NVIDIA Control Panel); machine-level, persistent |

Disk at the end: C: 3.1 GB free of 171 GB; D: 587 GB free of 782 GB. Everything this
project installed is on D: except Python 3.12 itself.

## 4. What was installed, against SETUP.txt

**Headline deviation: step 3, the CUDA Toolkit, was skipped entirely.** Job 1 passes with
`nvcc: absent`, and job 2's `bench/run_ncu.py` only shells out to `ncu`. The 6 GB toolkit
was replaced by ~1.5 GB of pip wheels plus a standalone `ncu`, all on D:. That is what made
a machine with a full C: drive and no elevation usable.

| Step | SETUP.txt asks | What was done |
|---|---|---|
| 1 driver | `nvidia-smi` shows CUDA 12.x+ | Passed unchanged: 610.88 / CUDA 13.3 |
| 2 Python 3.12 | winget install | Done; machine had only 3.13 (Store) and 3.14, both outside the supported 3.10–3.12 range |
| 3 CUDA Toolkit | install 12.4 for `nvcc` + `ncu` | **Skipped**; replaced by header wheels + standalone Nsight Compute |
| 4 toolkit check | `nvcc --version` | N/A, `nvcc` absent and unused |
| 5 venv + CuPy | venv + 6 packages | Done as written, plus 3 header wheels CuPy 14 requires |
| 6 GPU counters | Control Panel, allow all users | Done by the owner, after job 2's first attempt recorded the refusal |
| 7 check_setup.py | every line `[OK]` | Reached `READY FOR JOB 1 ONLY`, then full readiness once counters were on |

Two details worth keeping:

- CuPy 14 does not bundle CUDA headers and fails kernel compilation without them. The
  documented fix, `pip install cupy-cuda12x[ctk]`, pulls ~2.5 GB including a 553 MB cuBLAS
  wheel. Only three of those are needed here: `nvidia-cuda-nvrtc-cu12`,
  `nvidia-cuda-runtime-cu12`, `nvidia-cuda-cccl-cu12` — about 200 MB together.
- `ncu` has **no pip distribution under any name**. It came from the standalone Nsight
  Compute MSI, extracted rather than installed: no admin, nothing on C:.

## 5. Problems hit, and the fixes

| Problem | How it showed up | Fix |
|---|---|---|
| No suitable Python | only 3.13 (Store) and 3.14; no CuPy wheels for 3.14 | `winget install Python.Python.3.12`, venv from it |
| CuPy could not compile | `RuntimeError: Failed to find CUDA headers` | the three NVRTC/header wheels, not the full `[ctk]` extra |
| C: drive full | pip `[Errno 28] No space left on device`; C: had 1.6 GB free of 171 GB | purged pip's own 1.7 GB cache; pointed `TMP`/`TEMP`/`PIP_CACHE_DIR` at D: |
| Flaky network | repeated `Connection interrupted`, DNS `getaddrinfo failed` on a 553 MB wheel | avoided that wheel; `curl -C - --retry 30`, pip `--retries 20` |
| No `ncu` | `nvidia-nsight-compute-cu12` + variants: no matching distribution on PyPI | standalone MSI + `msiexec /a` extraction |
| Counters refused | `ncu --query-metrics` returned only `ERR_NVGPUCTRPERM`; job 2 recorded NOT_MEASURED | owner enabled counter access in NVIDIA Control Panel; immediate, no reboot |

### Docker was investigated and rejected

Docker Desktop 29.6.1 is installed here, so it looked like a way around the full C: drive.
It is not:

- The counter refusal is enforced by the **host driver**, not the container. A container
  cannot grant itself access the driver denies; it needs host-side permission plus
  `--cap-add=SYS_ADMIN`. The kit's own `run_ncu.py` notes a refusal is usual inside a
  shared container.
- On Windows, Docker Desktop runs Linux containers through **WSL2**, which SETUP.txt step 6
  calls out as the path where no counter switch exists and job 2 cannot be trusted. It
  would trade a documented-working native path for an unsupported one.

Docker also holds ~24 GB on C:, a large part of why that drive is full. Pruning unused
images is the cheapest way to reclaim space on this machine.

## 6. What the zips recorded

For eyeball sanity-checking only. **Do not type these into the project.**

### Job 1, the probe

| Metric | Value |
|---|---|
| `ENV-PEAK-BW` | 192.032 GB/s (theoretical, from memory clock and bus width) |
| `ENV-D2D-BW` | 185.788 GB/s measured — 96.7% of theoretical |
| `ENV-MAX-LOG2N` | 24 (the kit's hard cap) |
| `ENV-VRAM-FREE` | 3.466 GB at probe start |
| vector-add RawKernel | n = 1048576, 0 mismatches, compiled through NVRTC |

GPU was idle during the run (no other processes holding it), so the bandwidth figure is
clean. `max_log2n` is `floor(log2(0.5 x free VRAM / 48 B))` capped at 24; 3.47 GB free
computes above the cap, so 4 GB of VRAM was not a limiting factor.

### Job 2, Nsight Compute branch counters

15 branch metrics queried, 3080 CSV rows, 7 of 8 counters carrying values.

| Kernel | Divergent branches | Branch efficiency | Launches |
|---|---|---|---|
| `bitonic_pairs_global` | 0.0 | not reported | 44 |
| `bitonic_shared` | 0.0 | 100.0% | 7 |
| `bitonic_shared_full` | 0.0 | 100.0% | 1 |
| `aead_open_seq` | 0.0 | 100.0% | 1 |
| `planted_leak` (control) | 128.0 | 98.55% | 1 |

This is the shape a valid measurement must have: all four real kernels show zero divergent
branches, while the deliberately leaky control registers 128. The control proves the
counters were genuinely reading divergence, so the zeros are a real finding and not an
artifact of a dead instrument. `verify_result.py` requires exactly that before it issues a
PASS.

## 7. Recipe for a future GPU runner PC

Not needed for the laptop — this section is only for the next machine that has to *run*
jobs. Windows PC, NVIDIA GPU, full or protected C:, no admin except one Control Panel
visit. Replace `D:` with whatever drive has room.

1. **Driver:** `nvidia-smi` must report CUDA 12.0+. Note the GPU name; the runner will be
   `pc-<gpu>`.
2. **Python 3.12** if 3.10–3.12 is absent:
   `winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements`
3. **venv on the roomy drive**, with temp and cache redirected so a full C: cannot stop it:

   ```
   $env:TMP = "D:\vclock\pc_runner\.piptmp"; $env:TEMP = $env:TMP
   $env:PIP_CACHE_DIR = "D:\vclock\pc_runner\.pipcache"
   & $py -m venv D:\vclock\pc_runner\.venv
   & D:\vclock\pc_runner\.venv\Scripts\python.exe -m pip install --retries 20 cupy-cuda12x numpy scipy nvidia-ml-py cryptography pytest nvidia-cuda-nvrtc-cu12 nvidia-cuda-runtime-cu12 nvidia-cuda-cccl-cu12
   ```

4. **`ncu` without admin.** `winget show Nvidia.Nsight.Compute -e --source winget --disable-interactivity`
   prints the MSI URL and its SHA-256. Download with `curl -L -C - --retry 30`, verify the
   hash, then extract instead of installing:

   ```
   msiexec /a D:\vclock\nsight_dl\nsight_compute.msi /qn TARGETDIR=D:\vclock\nsight
   ```

   `ncu.exe` lands under
   `<target>\ProgramFiles64Folder\NVIDIA Corporation\Nsight Compute <ver>\target\windows-desktop-win7-x64\`.
5. **Enable the counters.** NVIDIA Control Panel → Desktop menu → tick *Enable Developer
   Settings* → Developer → *Manage GPU Performance Counters* → "Allow access to all users"
   → Apply. Needs admin once, no reboot. Verify with `ncu --query-metrics`, which should
   print thousands of lines rather than a single `ERR_NVGPUCTRPERM`.
6. **Prove it and run**, with the `ncu` folder prepended to `PATH`:

   ```
   $env:PATH = "<the ncu folder>;" + $env:PATH
   & .venv\Scripts\python.exe check_setup.py
   & .venv\Scripts\python.exe run_job.py jobs\1_probe_...zip
   & .venv\Scripts\python.exe run_job.py jobs\2_ncu_...zip
   ```

No file in the kit needs editing. `kit_common.path_with_tools()` only falls back to its
hardcoded `C:\Program Files\NVIDIA Corporation\Nsight Compute*` search when `ncu` is not
already on `PATH`, so prepending the folder is enough.

## 8. Gaps and caveats

- **`unit_tests` fails on collection, and it is not the GPU.** Job 1's third command exited
  2 because `tests/unit` imports `httpx` and `matplotlib`, neither of which SETUP.txt step 5
  installs. Eight modules error at import, one skips. The command is `optional`, so the
  verdict is unaffected — but the kit's package list is incomplete. Adding `httpx` and
  `matplotlib` to step 5 would close it.
- **`nvcc` is absent.** Nothing in these two jobs needs it, but a job that compiles with the
  toolkit directly (e.g. `scripts/sass_check.py` for SASS) would need step 3 after all.
- **The counter permission is machine-level and does not travel.** A new PC starts refused;
  job 2 there records NOT_MEASURED until someone enables it locally.
- **A CuPy warning appears in every run:** `CUDA path could not be detected. Set CUDA_PATH
  environment variable if CuPy fails to load.` Expected, because the headers come from pip
  wheels rather than a toolkit install. Harmless — both jobs passed with it present.
- **The extracted `ncu` is not registered with Windows.** It works only via its full path or
  `PATH`; no Start-menu entry, and nothing that looks in `C:\Program Files` will find it.
  Deliberate.
- **Deletable leftovers here:** `D:\vclock\nsight_dl\nsight_compute.msi` (480 MB),
  `D:\vclock\pc_runner\work\` (14 MB), `.pipcache`, `.piptmp`. Keep `D:\vclock\nsight` and
  `.venv` if more jobs may run on this PC — with those in place, a future job needs no setup.
