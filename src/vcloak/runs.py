"""Run directories and manifests (ai/LOGGING_AND_AUDIT.md §2).

Lives in the package, not in `scripts/`, because benchmarks executed on the remote runner need it
and a job bundle ships `src/` but not `scripts/`.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any

from vcloak.gpu import telemetry
from vcloak.gpu.runtime import Backend, get_backend

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}_M\d{2}_[A-Za-z0-9_]+$")
REQUIRED = ("run_id", "module", "step", "owner", "git_sha", "dirty", "command", "seed", "quick", "params",
            "env", "telemetry_start", "telemetry_end", "outputs", "status", "notes")
ENV_REQUIRED = ("os", "python", "backend", "runner", "session_id")
GPU_ENV_REQUIRED = ("gpu", "cc", "cuda", "cupy")
STATUSES = ("OK", "UNSTABLE", "NOT_MEASURED", "FAIL")
RUNNERS = ("colab", "kaggle", "local", "unknown")
_SESSION_START = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _git(root: Path, *args: str) -> str | None:
    try:
        p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
        return p.stdout.strip() if p.returncode == 0 else None
    except Exception:  # noqa: BLE001 - no git on this machine
        return None


def _job_json(root: Path) -> dict[str, Any] | None:
    """On the runner the bundle root holds job.json; locally there is none."""
    p = root / "job.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def build_env(backend: Backend) -> dict[str, Any]:
    """The manifest `env` block for the current process."""
    info = backend.device_info()
    env: dict[str, Any] = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "backend": backend.name,
        "runner": os.environ.get("VCLOAK_RUNNER", "local"),
        "session_id": os.environ.get("VCLOAK_SESSION_ID", _SESSION_START),
    }
    if backend.is_gpu:
        env.update({k: info.get(k) for k in GPU_ENV_REQUIRED})
        env["driver"] = telemetry.snapshot().get("driver")
    else:
        env["cpu"] = info.get("cpu")
    return env


def new_run(module: str, name: str, *, step: str, owner: str, command: str, seed: int = 0,
            quick: bool = False, params: dict[str, Any] | None = None, root: str | Path = ".",
            runs_dir: str | Path | None = None, backend: Backend | None = None) -> Path:
    """Create `runs/<YYYYMMDD-HHMMSS>_<Mxx>_<name>[_quick]/` with an initial manifest; return the dir."""
    root = Path(root).resolve()
    backend = backend or get_backend()
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}_{module}_{name}" + ("_quick" if quick else "")
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"bad run id {run_id!r}: module must look like M07, name must be [A-Za-z0-9_]+")
    run_dir = Path(runs_dir).resolve() if runs_dir else root / "runs"
    run_dir = run_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    job = _job_json(root)
    git_sha = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain")
    manifest: dict[str, Any] = {
        "run_id": run_id, "module": module, "step": step, "owner": owner,
        "git_sha": git_sha or (job or {}).get("git_sha") or "unknown",
        "dirty": bool(status) if status is not None else bool((job or {}).get("dirty", False)),
        "command": command, "seed": seed, "quick": quick, "params": params or {},
        "env": build_env(backend),
        "telemetry_start": telemetry.snapshot(), "telemetry_end": None,
        "outputs": [], "status": "NOT_MEASURED", "notes": "run started; not finalised",
    }
    if job:
        manifest["gpu_job"] = {"job_id": job.get("job_id"), "bundle_sha256": job.get("bundle_sha256"),
                               "packed_from_git_sha": job.get("git_sha")}
    write_manifest(run_dir, manifest)
    return run_dir


def read_manifest(run_dir: str | Path) -> dict[str, Any]:
    return json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))


def write_manifest(run_dir: str | Path, manifest: dict[str, Any]) -> None:
    (Path(run_dir) / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def finish_run(run_dir: str | Path, *, status: str, outputs: list[str] | None = None, notes: str = "",
               env_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record the final status, the end telemetry and the output file list."""
    run_dir = Path(run_dir)
    m = read_manifest(run_dir)
    m["telemetry_end"] = telemetry.snapshot()
    m["status"] = status
    m["notes"] = notes
    if env_extra:
        m["env"].update(env_extra)
    m["outputs"] = sorted(outputs if outputs is not None
                          else [p.name for p in run_dir.iterdir() if p.name != "manifest.json"])
    write_manifest(run_dir, m)
    return m


def validate_manifest(run_dir: str | Path) -> list[str]:
    """Return a list of problems; empty means the run dir is valid."""
    run_dir = Path(run_dir)
    path = run_dir / "manifest.json"
    if not path.exists():
        return [f"{run_dir}: manifest.json missing"]
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"{path}: not valid JSON ({e})"]
    errs = [f"missing field: {k}" for k in REQUIRED if k not in m]
    if errs:
        return errs
    if m["run_id"] != run_dir.name:
        errs.append(f"run_id {m['run_id']!r} does not match directory {run_dir.name!r}")
    if not RUN_ID_RE.match(str(m["run_id"])):
        errs.append(f"run_id {m['run_id']!r} is not <YYYYMMDD-HHMMSS>_<Mxx>_<name>")
    if m["status"] not in STATUSES:
        errs.append(f"status {m['status']!r} not in {STATUSES}")
    if bool(m["quick"]) != str(m["run_id"]).endswith("_quick"):
        errs.append("quick flag and the _quick suffix of the run id disagree")
    env = m["env"] if isinstance(m["env"], dict) else {}
    errs += [f"missing env field: {k}" for k in ENV_REQUIRED if k not in env]
    if env.get("backend") not in ("cupy", "numpy"):
        errs.append(f"env.backend {env.get('backend')!r} must be cupy or numpy")
    if env.get("runner") not in RUNNERS:
        errs.append(f"env.runner {env.get('runner')!r} not in {RUNNERS}")
    if env.get("backend") == "cupy":
        errs += [f"backend cupy but env.{k} missing" for k in GPU_ENV_REQUIRED if not env.get(k)]
        if "gpu_job" not in m:
            errs.append("backend cupy but no gpu_job block (GPU runs must come from a packed job)")
    if not m["git_sha"] or m["git_sha"] == "unknown":
        errs.append("git_sha unknown")
    for out in m["outputs"]:
        if not (run_dir / out).exists():
            errs.append(f"listed output missing: {out}")
    return errs
