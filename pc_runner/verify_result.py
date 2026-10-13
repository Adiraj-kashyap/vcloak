#!/usr/bin/env python3
"""Proof that a job worked, before you leave the machine.   python verify_result.py results/results_<job>.zip

run_job.py calls this by itself after every job. It reads the results zip only and prints a VERDICT:
  PASS  exit 0   the zip is complete and is what the laptop will accept; take it home
  FAIL  exit 1   something required is missing or wrong; the lines above the verdict say what
A measurement that ended NOT_MEASURED (for example refused GPU counters) is a FAIL here: the zip is still
valid evidence of the refusal, but the job did not do what you came for, and you can still fix it now.
The laptop checks more at ingest (the commit the job was packed from); this cannot be checked here.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import kit_common as kc


def verify(results_zip: Path, job_zip: Path | None = None) -> int:
    problems: list[str] = []
    with zipfile.ZipFile(results_zip) as z:
        names = set(z.namelist())
        missing = {"result.json", "job.json"} - names
        if missing:
            print(f"VERDICT: FAIL - {results_zip.name} has no {sorted(missing)}")
            return 1
        result, job = json.loads(z.read("result.json")), json.loads(z.read("job.json"))
        manifests = {n: json.loads(z.read(n)) for n in sorted(names)
                     if n.startswith("runs/") and n.endswith("/manifest.json")}
        summaries = {n: json.loads(z.read(n)) for n in sorted(names)
                     if n.startswith("runs/") and n.endswith("_M08_ncu/summary.json")}
    env = result.get("env", {})
    print(f"job        {result.get('job_id')}  ({job.get('title', '')[:70]})")
    print(f"machine    runner {env.get('runner')}, gpu {env.get('gpu')}, driver {env.get('driver')}, "
          f"cupy {env.get('cupy')}, ncu {str(env.get('ncu'))[:40]}, {env.get('cpu_count')} cpu")

    if result.get("job_id") != job.get("job_id") or result.get("bundle_sha256") != job.get("bundle_sha256"):
        problems.append("result.json and job.json name different jobs")
    if job_zip is not None:
        with zipfile.ZipFile(job_zip) as z:
            packed = json.loads(z.read("job.json"))
        if packed.get("bundle_sha256") != result.get("bundle_sha256") or packed.get("job_id") != result.get("job_id"):
            problems.append(f"this result does not belong to {job_zip.name}")
    if not kc.PC_RUNNER_RE.match(str(env.get("runner"))):
        problems.append(f"runner is {env.get('runner')!r}, not pc-<gpu>")
    if env.get("gpu") in (None, "NONE", "unknown"):
        problems.append("no GPU was seen")
    if env.get("cupy") in (None, "absent"):
        problems.append("CuPy was not importable: " + str(env.get("cupy_error", ""))[-200:])
    commands = result.get("commands", [])
    if len(commands) < len(job.get("commands", [])):
        problems.append(f"only {len(commands)} of {len(job['commands'])} commands ran (a required one failed)")
    for c in commands:
        state = "ok" if c["exit_code"] == 0 else "FAILED (optional)" if c.get("optional") else "FAILED"
        print(f"command    {c['name']:<18} exit {c['exit_code']:<4} {state}")
        if c["exit_code"] != 0 and not c.get("optional"):
            problems.append(f"command {c['name']} ended with exit {c['exit_code']} (see {c['log']} in the zip)")
    if not manifests:
        problems.append("the zip holds no run directory")
    for m in manifests.values():
        menv = m.get("env", {})
        print(f"run        {m.get('run_id'):<34} status {m.get('status')}  backend {menv.get('backend')}  "
              f"runner {menv.get('runner')}")
        if menv.get("backend") != "cupy":
            problems.append(f"{m.get('run_id')}: backend {menv.get('backend')}, the GPU was not used")
        if menv.get("runner") != env.get("runner"):
            problems.append(f"{m.get('run_id')}: runner {menv.get('runner')} differs from {env.get('runner')}")
        if m.get("status") == "UNSTABLE":  # a valid outcome on a busy machine; the laptop decides what it is worth
            print(f"           note: UNSTABLE ({m.get('notes')}). Close other programs and run it again if you can.")
        elif m.get("status") != "OK":
            problems.append(f"{m.get('run_id')}: status {m.get('status')}: {m.get('notes')}")
    for s in summaries.values():
        measured = [x for x in s.get("metrics", []) if x.get("value") != "NOT_MEASURED"]
        seen = s.get("control", {}).get("divergent_seen")
        print(f"ncu        {len(measured)} of {len(s.get('metrics', []))} counters carry a value, {s.get('rows')} "
              f"csv rows; planted-leak control shows divergence: {seen}")
        if s.get("reason"):
            problems.append("ncu measured nothing: " + s["reason"] + "  -> SETUP.txt step 6, then run job 2 again")
        elif seen is not True:
            problems.append("ncu: the positive control is not confirmed (the planted-leak kernel must show divergent "
                            "branches); bring the zip home anyway and say so")
    if job.get("module") == "M08_ncu" and not summaries:
        problems.append("the ncu run wrote no summary.json")

    if problems:
        print("\nVERDICT: FAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print(f"\nVERDICT: PASS - copy {results_zip.name} into gpujobs/inbox/ on the laptop")
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: python verify_result.py results/results_<job>.zip [jobs/<job>.zip]")
    sys.exit(verify(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) == 3 else None))
