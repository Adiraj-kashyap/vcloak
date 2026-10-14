#!/usr/bin/env python3
"""Cross-platform task runner (use instead of make).

    python tasks.py test          local tests (no GPU)
    python tasks.py lint          ruff
    python tasks.py check         metrics audit (G2/G2b) and its self-test
    python tasks.py pack M07      pack a GPU job        (extra args are passed through)
    python tasks.py ingest        ingest gpujobs/inbox/*.zip
    python tasks.py dashboard     regenerate web/data/dashboard.json (M18)
    python tasks.py dashboard --check   exit 1 if the committed dashboard.json or its paper figures are stale
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

TASKS: dict[str, list[list[str]]] = {
    "test": [[PY, "-m", "pytest", "-q", "-m", "not gpu and not integration"]],
    "lint": [[PY, "-m", "ruff", "check", "src", "scripts", "tests", "bench", "tasks.py"]],
    "check": [[PY, "scripts/check_metrics.py", "--self-test"], [PY, "scripts/check_metrics.py"]],
    "pack": [[PY, "scripts/gpujob.py", "pack"]],
    "ingest": [[PY, "scripts/gpujob.py", "ingest"]],
    "dashboard": [[PY, "scripts/export_dashboard.py"]],
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in TASKS:
        print(__doc__)
        return 0 if not argv else 2
    for cmd in TASKS[argv[0]]:
        extra = argv[1:] if cmd is TASKS[argv[0]][-1] else []
        rc = subprocess.run(cmd + extra, cwd=ROOT).returncode
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
