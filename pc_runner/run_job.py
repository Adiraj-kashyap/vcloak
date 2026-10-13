#!/usr/bin/env python3
"""Run one V-cloak job zip on this PC and verify the result.   python run_job.py jobs/<job>.zip

The third runner of the job protocol (ai/GPU_RUNNER.md section 4, ai/DECISIONS.md ADR-025): the same
gpu_entry.py that Colab and Kaggle run, taken from inside the job zip, with VCLOAK_RUNNER=pc-<gpu>.
The results zip appears in results/ beside this file, and verify_result.py prints a VERDICT for it.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import kit_common as kc
from verify_result import verify


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python run_job.py jobs/<job>.zip")
        return 1
    job_zip = Path(argv[0]).resolve()
    if not job_zip.is_file():
        print(f"no such file: {job_zip}")
        return 1
    try:
        runner = kc.runner_name()
    except kc.KitError as e:
        print(f"!! {e}\nNothing was run.")
        return 1

    with zipfile.ZipFile(job_zip) as z:
        job = json.loads(z.read("job.json"))
        work = kc.KIT / "work" / job["job_id"]
        if work.exists():  # a second attempt starts from the packed files, never from a used folder
            shutil.rmtree(work)
        work.mkdir(parents=True)
        z.extractall(work)

    env = dict(os.environ)
    env["VCLOAK_RUNNER"] = runner
    env["PATH"] = kc.path_with_tools()
    env["PYTHONUTF8"] = "1"
    print(f"runner {runner}   job {job['job_id']}   work folder {work}")
    rc = subprocess.run([sys.executable, "gpu_entry.py", "--job", "job.json"], cwd=work, env=env).returncode

    produced = work / f"results_{job['job_id']}.zip"
    if not produced.is_file():
        print(f"\nVERDICT: FAIL - no results zip was written (gpu_entry.py exit {rc}); read the messages above")
        return 1
    out_dir = kc.KIT / "results"
    out_dir.mkdir(exist_ok=True)
    final = out_dir / produced.name
    if final.exists():  # an earlier attempt is kept, not overwritten, and kept out of the folder you copy from
        (out_dir / "previous").mkdir(exist_ok=True)
        final.rename(out_dir / "previous" / f"{_dt.datetime.now():%Y%m%d-%H%M%S}_{final.name}")
    shutil.copy2(produced, final)
    print(f"\nresults zip: {final}\n")
    return verify(final, job_zip)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
