"""Shared by check_setup.py, run_job.py and verify_result.py. Standard library only.

The runner name of this machine is `pc-<gpu>` (ai/DECISIONS.md ADR-025). It is derived from the GPU that
nvidia-smi reports and is never "local": "local" means the GPU-less laptop, and `scripts/check_metrics.py`
refuses every GPU metric that carries it.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
# the same pattern as vcloak.runs.PC_RUNNER_RE: a manifest with another name does not validate at ingest
PC_RUNNER_RE = re.compile(r"^pc-[a-z0-9]+(?:-[a-z0-9]+)*$")
PERM_ERRORS = ("ERR_NVGPUCTRPERM", "permission to access NVIDIA GPU Performance Counters")
NCU_DIRS = (r"C:\Program Files\NVIDIA Corporation\Nsight Compute*", "/usr/local/cuda/bin", "/usr/local/cuda-*/bin",
            "/opt/nvidia/nsight-compute/*")


class KitError(Exception):
    """This machine or this file is not usable as it is; the message says what to do."""


def run(cmd: list[str], timeout: int = 120, env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, f"{type(e).__name__}: {e}"


def gpu_name() -> str:
    rc, out = run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    if rc != 0 or not out.strip():
        raise KitError("nvidia-smi does not answer: no NVIDIA driver, or no NVIDIA GPU (SETUP.txt step 1).\n"
                       + out.strip()[:400])
    return out.strip().splitlines()[0].strip()


def runner_name() -> str:
    """`pc-<gpu>`: VCLOAK_RUNNER when it is already such a name, otherwise from the GPU name."""
    given = os.environ.get("VCLOAK_RUNNER", "").strip()
    if given:
        if not PC_RUNNER_RE.match(given):
            raise KitError(f"VCLOAK_RUNNER is {given!r}. On this machine it must be pc-<gpu> (lower case, for example "
                           "pc-rtx3060) and never 'local'. Unset it and the kit names the runner after the GPU.")
        return given
    slug = re.sub(r"[^a-z0-9]", "", re.sub(r"nvidia|geforce", "", gpu_name().lower()))
    if not slug:
        raise KitError("could not make a runner name from the GPU name; set VCLOAK_RUNNER=pc-<gpu> yourself")
    return f"pc-{slug}"


def path_with_tools() -> str:
    """PATH with this Python first (the jobs call `python`) and, when `ncu` is not on it, the Nsight Compute folder."""
    parts = [str(Path(sys.executable).parent)]
    if shutil.which("ncu") is None:
        for pattern in NCU_DIRS:
            for d in sorted(glob.glob(pattern), reverse=True):
                if any((Path(d) / n).is_file() for n in ("ncu", "ncu.bat", "ncu.exe")):
                    parts.append(d)
                    break
            if len(parts) > 1:
                break
    return os.pathsep.join([*parts, os.environ.get("PATH", "")])
