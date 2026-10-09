---
name: gpu-bench
description: Procedure for any GPU timing, throughput, telemetry or side-channel measurement in V-cloak. Use whenever a step says "measure", "benchmark", "profile", "dudect", "ncu" or "SASS".
---
Follow `ai/GPU_GUIDE.md §4–§7`. Minimum procedure:

1. Create the run dir `runs/<YYYYMMDD-HHMMSS>_<Mxx>_<name>/` and write `manifest.json` first
   (git sha, command, seed, params, env block from STATE.md, and the start telemetry snapshot).
2. Record an NVML snapshot (SM/mem clock, temperature, power, utilisation, throttle reasons) before and after.
3. Warm up at least 10 launches. Time at least 30 runs (default 50) with `cupy.cuda.Event` pairs on the same stream.
   Report median, p5, p95, mean, CV. Time H2D, kernel and D2H separately where they apply.
4. Save raw per-run timings to `raw.csv` and summary statistics to `summary.json`.
5. If the CV exceeds 10%, or the SM clock dropped more than 15% during the run (thermal throttling):
   repeat once, then record `UNSTABLE` with both runs. Never silently discard runs.
6. Add every reported number to `state/METRICS_INDEX.md` with its run dir.
7. Never compare GPU and CPU numbers taken under different power states. Plug the laptop in and
   record the power state in the manifest.
