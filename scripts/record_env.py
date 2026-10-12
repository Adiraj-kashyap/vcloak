#!/usr/bin/env python3
"""M00 S7: fill `STATE.md -> local/runner` and write `docs/ENV.md` from the ingested probe.

Nothing here is typed by hand: the runner side is read from the job's `result.json` and the probe run
dir whose manifest carries the same `session_id`; the local side is read from this machine.

    python scripts/record_env.py <job-id>
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _powershell(cmd: str) -> str:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                             timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _ram_gb() -> float | str:
    if os.name == "nt":
        class _MemStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong) for n in ("total", "avail", "tpage", "apage", "tvirt", "avirt", "ext")]
        m = _MemStatus()
        m.length = ctypes.sizeof(_MemStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.total / 2**30, 1)
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError):
        return "unknown"


def _postgres() -> str:
    psql = shutil.which("psql")
    if psql:
        out = subprocess.run([psql, "--version"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or "psql on PATH"
    if os.name == "nt":
        svc = _powershell("Get-Service *postgres* | ForEach-Object { $_.Name + ' (' + $_.Status + ')' }")
        if svc:
            return "service " + ", ".join(svc.splitlines()) + "; psql not on PATH"
    return "not found"


def local_env() -> dict[str, object]:
    cpu = _powershell("(Get-CimInstance Win32_Processor).Name") if os.name == "nt" else ""
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": f"{cpu or platform.processor() or 'unknown'} ({os.cpu_count()} logical)",
        "ram_gb": _ram_gb(),
        "postgres": _postgres(),
        "default_backend": "numpy",
    }


def runner_env(job_id: str, root: Path = ROOT) -> tuple[dict[str, object], dict]:
    result = json.loads((root / "gpujobs" / "out" / job_id / "result.json").read_text(encoding="utf-8"))
    env = result["env"]
    runs = []
    for mf in sorted((root / "runs").glob("*/manifest.json")):
        m = json.loads(mf.read_text(encoding="utf-8"))
        if m.get("gpu_job", {}).get("job_id") == job_id and (mf.parent / "device.json").exists():
            runs.append((mf.parent, m))
    if not runs:
        raise SystemExit(f"no ingested probe run for job {job_id}")
    # The job's result.json describes one notebook session; that session's run is the canonical one.
    canon = [r for r in runs if r[1]["env"]["session_id"] == env["session_id"]]
    if len(canon) != 1:
        raise SystemExit(f"expected one run for session {env['session_id']}, found {len(canon)}")
    run_dir, manifest = canon[0]
    dev = json.loads((run_dir / "device.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if not (dev["is_gpu"] and summary["vector_add"]["correct"] and summary["vector_add"]["mismatches"] == 0):
        raise SystemExit("probe did not run a correct vector-add on a GPU; refusing to record the runner")
    runner = {
        "provider": env["runner"],
        "gpu": dev["gpu"],
        "compute_capability": dev["cc"],
        "vram_gb": round(dev["vram_total_bytes"] / 1e9, 2),  # decimal GB, the unit ENV-VRAM-FREE uses
        "driver": env["driver"],
        "cuda": dev["cuda"],
        "cupy": dev["cupy"],
        "nvcc": env.get("nvcc", "unknown"),
        "ncu": env.get("ncu", "unknown"),
        "ncu_counters_permitted": "unknown",  # not probed in M00; a counter run is needed to know
        "max_log2n": dev["max_log2n"],
        "peak_bw_gbs": dev["peak_bw_gbs"],
        "last_session_id": env["session_id"],
    }
    detail = {"run_dir": run_dir.relative_to(root).as_posix(), "manifest": manifest, "device": dev,
              "summary": summary, "result": result,
              "all_runs": [(d.relative_to(root).as_posix(), m["env"]["session_id"]) for d, m in runs]}
    return runner, detail


def update_state(state_path: Path, local: dict, runner: dict, job_id: str) -> None:
    lines = state_path.read_text(encoding="utf-8").splitlines()
    block, values = None, {"local": local, "runner": runner}
    for i, line in enumerate(lines):
        top = re.match(r"^(\w+):", line)
        if top:
            block = top.group(1)
        m = re.match(r"^  (\w+): (\S.*?)(\s+#.*)?$", line)
        if not m:
            continue
        key, comment = m.group(1), m.group(3) or ""
        if block in values and key in values[block]:
            v = values[block][key]
            lines[i] = f"  {key}: {json.dumps(v) if isinstance(v, str) else v}{comment}"
        elif block == "gpu_job" and key == "pending":
            lines[i] = f"  pending: null{comment}"
        elif block == "gpu_job" and key == "last_ingested":
            lines[i] = f"  last_ingested: {job_id}"
    state_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


_KEPT = re.compile(r"<!-- BEGIN ([A-Z0-9 ]+) -->.*?<!-- END \1 -->", re.S)


def keep_sections(path: Path, text: str) -> str:
    """`text` followed by the marked sections other tools wrote into the file (scripts/pgdev.py doc)."""
    if not path.is_file():
        return text
    kept = [m.group(0) for m in _KEPT.finditer(path.read_text(encoding="utf-8"))]
    return text if not kept else text.rstrip("\n") + "\n\n" + "\n\n".join(kept) + "\n"


def write_env_md(path: Path, local: dict, runner: dict, detail: dict, job_id: str) -> None:
    d2d, tel = detail["summary"]["d2d_copy"], detail["manifest"]["telemetry_start"]
    metrics = {m["id"]: m for m in detail["summary"]["metrics"]}
    cmds = detail["result"]["commands"]
    req = detail["result"]["requirements"]
    out = [
        "# Environment",
        "",
        "Generated by `python scripts/record_env.py " + job_id + "` — do not edit by hand. Every runner value",
        f"below is read from the ingested job `{job_id}` (`gpujobs/out/{job_id}/result.json`) and its probe run",
        f"`{detail['run_dir']}`.",
        "",
        "## Local machine (no GPU; `numpy` thread-model backend, correctness only)",
        "",
        "| Field | Value |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in local.items()],
        "",
        "A number produced here is never a performance result (CLAUDE.md hard rule 2).",
        "",
        "## Remote GPU runner",
        "",
        "| Field | Value |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in runner.items()],
        f"| sm_count | {detail['device']['sm_count']} |",
        f"| mem_clock_khz | {detail['device']['mem_clock_khz']} |",
        f"| mem_bus_width_bits | {detail['device']['mem_bus_width_bits']} |",
        f"| runner os / python | {detail['device']['os']} / {detail['device']['python']} |",
        f"| runner cpu | {detail['result']['env'].get('cpu', 'unknown')} "
        f"x{detail['result']['env'].get('cpu_count', '?')} |",
        f"| clocks | {tel.get('clocks', 'unknown')} (power limit {tel.get('power_limit_w')} W) |",
        "",
        "The free runner may hand out a different GPU next session; `gpu` and `session_id` are in every manifest.",
        "",
        "## Probe result",
        "",
        "| Metric | Value | Unit | Stat | Note |", "|---|---|---|---|---|",
        *[f"| {m['id']} | {m['value']} | {m['unit']} | {m['stat']} | {m['note']} |" for m in metrics.values()],
        "",
        f"- Vector-add RawKernel: n={detail['summary']['vector_add']['n']}, "
        f"mismatches={detail['summary']['vector_add']['mismatches']} "
        f"({detail['summary']['vector_add']['executed_by']}).",
        f"- D2D copy: {d2d['bytes']} bytes, warm-up {d2d['warmup']}, {d2d['runs']} runs, timer `{d2d['timer']}`; "
        f"median {d2d['median_ms']:.4f} ms, p5 {d2d['p5_ms']:.4f} ms, p95 {d2d['p95_ms']:.4f} ms, "
        f"CV {d2d['cv']:.4f}; telemetry samples during the loop: {d2d['telemetry_samples']}.",
        "- Job commands: " + "; ".join(
            f"{c['name']} exit {c['exit_code']}" + (" (optional)" if c["optional"] else "") for c in cmds) + ".",
        f"- `requirements-gpu.txt` on the runner: installed {req['installed']}, skipped {req['skipped']}, "
        f"failed {req['failed']}.",
        "- Probe runs in this bundle (run dir, session): " + "; ".join(f"`{d}` ({s})" for d, s in detail["all_runs"])
        + ". The run whose session matches `result.json` is the one recorded above.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(keep_sections(path, "\n".join(out)), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job_id")
    args = ap.parse_args(argv)
    local = local_env()
    runner, detail = runner_env(args.job_id)
    update_state(ROOT / "state" / "STATE.md", local, runner, args.job_id)
    write_env_md(ROOT / "docs" / "ENV.md", local, runner, detail, args.job_id)
    print(f"recorded local + runner env from {detail['run_dir']} -> state/STATE.md, docs/ENV.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
