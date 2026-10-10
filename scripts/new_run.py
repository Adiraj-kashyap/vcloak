#!/usr/bin/env python3
"""Create or validate a run directory (ai/LOGGING_AND_AUDIT.md §2).

    python scripts/new_run.py M00 local_checks --step S4 --owner Aditya --command "pytest -q"
    python scripts/new_run.py --finish runs/<dir> --status OK --notes "..."
    python scripts/new_run.py --validate runs/<dir>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vcloak import runs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("module", nargs="?", help="e.g. M07")
    ap.add_argument("name", nargs="?", help="short run name, [A-Za-z0-9_]+")
    ap.add_argument("--step", default="S1")
    ap.add_argument("--owner", default="unknown")
    ap.add_argument("--command", default="")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=None, help="parent directory for the run dir (default: runs/)")
    ap.add_argument("--validate", metavar="RUN_DIR")
    ap.add_argument("--finish", metavar="RUN_DIR")
    ap.add_argument("--status", default="OK", choices=runs.STATUSES)
    ap.add_argument("--notes", default="")
    a = ap.parse_args(argv)

    if a.validate:
        errs = runs.validate_manifest(a.validate)
        for e in errs:
            print("INVALID:", e)
        print(f"{a.validate}: {'INVALID' if errs else 'valid'}")
        return 1 if errs else 0
    if a.finish:
        m = runs.finish_run(a.finish, status=a.status, notes=a.notes)
        print(f"{a.finish}: status {m['status']}, {len(m['outputs'])} outputs")
        return 0
    if not (a.module and a.name):
        ap.error("module and name are required")
    d = runs.new_run(a.module, a.name, step=a.step, owner=a.owner, command=a.command, seed=a.seed,
                     quick=a.quick, root=ROOT, runs_dir=a.out)
    print(d.relative_to(ROOT).as_posix() if d.is_relative_to(ROOT) else d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
