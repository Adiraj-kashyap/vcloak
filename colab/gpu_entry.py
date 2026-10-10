#!/usr/bin/env python3
"""
V-cloak GPU job runner — executes one job bundle on a free cloud GPU (Colab / Kaggle).

This file ships inside every job bundle produced by `scripts/gpujob.py pack`.
It is deliberately dependency-light: stdlib only, except for what the job itself imports.

Usage (inside the notebook, from the unpacked bundle directory):
    python gpu_entry.py --job job.json
    python gpu_entry.py --job job.json --dry-run      # list the commands, run nothing

It:
  1. records the environment (GPU, driver, CUDA, CuPy, nvcc, ncu),
  2. installs anything in requirements-gpu.txt that is missing,
  3. runs each command from job.json with VCLOAK_BACKEND=cupy, capturing stdout/stderr,
  4. writes result.json (exit codes + env + bundle sha) and zips runs/ + logs/ into
     results_<job_id>.zip next to the bundle.

Exit code is 0 if every command succeeded, 1 otherwise. A non-zero exit still produces
the results zip, because a failed run is evidence too.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _run(cmd, timeout=None, env=None):
    """Run a command, return (exit_code, combined_output). Never raises."""
    try:
        p = subprocess.run(
            cmd, shell=isinstance(cmd, str), capture_output=True, text=True,
            timeout=timeout, cwd=str(HERE), env=env,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s\n{e.stdout or ''}{e.stderr or ''}"
    except Exception as e:  # noqa: BLE001 - the runner must never crash on a probe
        return 127, f"{type(e).__name__}: {e}"


def _probe_env() -> dict:
    """Collect everything a manifest needs to identify this machine and session."""
    env = {
        "collected_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "backend": "cupy",
        "runner": _detect_runner(),
        "session_id": os.environ.get("VCLOAK_SESSION_ID") or _dt.datetime.now().strftime("%Y%m%d-%H%M%S"),
    }

    rc, out = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap",
                    "--format=csv,noheader"], timeout=60)
    if rc == 0 and out.strip():
        parts = [x.strip() for x in out.strip().splitlines()[0].split(",")]
        env["gpu"] = parts[0] if parts else "unknown"
        env["driver"] = parts[1] if len(parts) > 1 else "unknown"
        env["vram_total"] = parts[2] if len(parts) > 2 else "unknown"
        env["compute_capability"] = parts[3] if len(parts) > 3 else "unknown"
    else:
        env["gpu"] = "NONE"
        env["nvidia_smi_error"] = out[:500]

    rc, out = _run(["nvcc", "--version"], timeout=60)
    env["nvcc"] = out.strip().splitlines()[-1].strip() if rc == 0 and out.strip() else "absent"

    rc, out = _run(["ncu", "--version"], timeout=60)
    env["ncu"] = out.strip().splitlines()[0].strip() if rc == 0 and out.strip() else "absent"

    rc, out = _run([sys.executable, "-c",
                    "import cupy;print(cupy.__version__);print(cupy.cuda.runtime.runtimeGetVersion())"],
                   timeout=300)
    if rc == 0:
        lines = out.strip().splitlines()
        env["cupy"] = lines[0] if lines else "unknown"
        env["cuda_runtime"] = lines[1] if len(lines) > 1 else "unknown"
    else:
        env["cupy"] = "absent"
        env["cupy_error"] = out[-500:]

    # CPU identity matters: M07 compares GPU against the *runner's* CPU, not the laptop's.
    rc, out = _run("cat /proc/cpuinfo | grep -m1 'model name'", timeout=30)
    env["cpu"] = out.split(":", 1)[1].strip() if rc == 0 and ":" in out else platform.processor() or "unknown"
    rc, out = _run("nproc", timeout=30)
    env["cpu_count"] = out.strip() if rc == 0 else str(os.cpu_count())
    return env


def _detect_runner() -> str:
    if os.environ.get("VCLOAK_RUNNER"):
        return os.environ["VCLOAK_RUNNER"]
    if "COLAB_GPU" in os.environ or Path("/content").exists():
        return "colab"
    if os.environ.get("KAGGLE_KERNEL_RUN_TYPE") or Path("/kaggle").exists():
        return "kaggle"
    return "unknown"


def _ensure_requirements(log_dir: Path) -> dict:
    """Install only what is missing. Colab/Kaggle already ship CuPy and NumPy."""
    req = HERE / "requirements-gpu.txt"
    report = {"file": req.name, "installed": [], "skipped": [], "failed": []}
    if not req.exists():
        report["file"] = "absent"
        return report
    for raw in req.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        mod = line.split("==")[0].split(">=")[0].split("[")[0].strip()
        import_name = {"cupy-cuda12x": "cupy", "cupy-cuda11x": "cupy",
                       "nvidia-ml-py": "pynvml", "pynvml": "pynvml"}.get(mod, mod.replace("-", "_"))
        rc, _ = _run([sys.executable, "-c", f"import {import_name}"], timeout=300)
        if rc == 0:
            report["skipped"].append(line)
            continue
        rc, out = _run([sys.executable, "-m", "pip", "install", "-q", line], timeout=1800)
        (log_dir / f"pip_{mod}.txt").write_text(out)
        (report["installed"] if rc == 0 else report["failed"]).append(line)
    return report


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="job.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    job = json.loads((HERE / args.job).read_text())
    job_id = job["job_id"]
    log_dir = HERE / "logs"
    log_dir.mkdir(exist_ok=True)
    (HERE / "runs").mkdir(exist_ok=True)

    print(f"=== V-cloak GPU job {job_id} ({job.get('module')}) ===")
    commands = job.get("commands", [])

    if args.dry_run:
        for i, c in enumerate(commands, 1):
            print(f"  [{i}] {c['cmd'] if isinstance(c, dict) else c}")
        return 0

    env_info = _probe_env()
    print(json.dumps({k: env_info.get(k) for k in ("gpu", "driver", "cupy", "nvcc", "ncu", "runner")}, indent=1))
    if env_info.get("gpu") == "NONE":
        print("\n!! No GPU visible. In Colab: Runtime > Change runtime type > T4 GPU."
              "\n   In Kaggle: Settings > Accelerator > GPU. Then re-run this cell.\n")
        return 1

    req_report = _ensure_requirements(log_dir)

    run_env = dict(os.environ)
    run_env["VCLOAK_BACKEND"] = "cupy"
    run_env["VCLOAK_RUNNER"] = env_info["runner"]
    run_env["VCLOAK_SESSION_ID"] = env_info["session_id"]
    run_env["PYTHONPATH"] = str(HERE / "src") + os.pathsep + run_env.get("PYTHONPATH", "")

    results = []
    overall = 0
    for i, c in enumerate(commands, 1):
        spec = c if isinstance(c, dict) else {"cmd": c}
        cmd, name = spec["cmd"], spec.get("name", f"cmd{i}")
        timeout = spec.get("timeout", 3600)
        print(f"\n--- [{i}/{len(commands)}] {name}\n$ {cmd}", flush=True)
        rc, out = _run(cmd, timeout=timeout, env=run_env)
        (log_dir / f"{i:02d}_{name}.txt").write_text(out)
        tail = "\n".join(out.splitlines()[-25:])
        print(tail, flush=True)
        print(f"--- exit {rc}", flush=True)
        results.append({"n": i, "name": name, "cmd": cmd, "exit_code": rc,
                        "log": f"logs/{i:02d}_{name}.txt",
                        "optional": bool(spec.get("optional", False))})
        if rc != 0 and not spec.get("optional", False):
            overall = 1
            if spec.get("stop_on_fail", True):
                print("!! required command failed — stopping; partial results will still be packaged")
                break

    result = {
        "job_id": job_id,
        "module": job.get("module"),
        "step": job.get("step"),
        "quick": job.get("quick", False),
        "packed_from_git_sha": job.get("git_sha"),
        "bundle_sha256": job.get("bundle_sha256"),
        "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "env": env_info,
        "requirements": req_report,
        "commands": results,
        "overall_exit": overall,
    }
    (HERE / "result.json").write_text(json.dumps(result, indent=2))

    out_zip = HERE / f"results_{job_id}.zip"
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(HERE / "result.json", "result.json")
        z.write(HERE / args.job, "job.json")
        for folder in ("runs", "logs"):
            base = HERE / folder
            for p in sorted(base.rglob("*")):
                if p.is_file() and p.stat().st_size < 200 * 1024 * 1024:
                    z.write(p, str(p.relative_to(HERE)))
    print(f"\n=== wrote {out_zip.name} ({out_zip.stat().st_size/1e6:.1f} MB, sha256 {_sha256(out_zip)[:16]}…)")
    print(f"=== overall exit {overall}")
    print("Download it, then drop it into your repo's gpujobs/inbox/ and type: continue")
    return overall


if __name__ == "__main__":
    sys.exit(main())
