"""M18 A1 (module audit): no numeric literal in web/js/** equals a value the dashboard shows.

Collects every number of web/data/dashboard.json that sits under a value-like key (tiles, chart series,
framing, experiments, architecture evidence), then every numeric literal of web/js/**/*.js (demo-data.js
included), and lists the literals that equal a shown value. Integers below 100 and round layout numbers are
reported separately for reading, never silently dropped.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
dash = json.loads((ROOT / "web/data/dashboard.json").read_text(encoding="utf-8"))
SKIP_KEYS = {"generated_at", "git_sha", "index_sha256", "line", "date", "session_id"}


def walk(o, key=""):
    if isinstance(o, bool):
        return
    if isinstance(o, (int, float)) and key not in SKIP_KEYS:
        yield float(o)
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, k)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v, key)
    elif isinstance(o, str) and key in ("raw", "value"):
        try:
            yield float(o)
        except ValueError:
            pass


shown = {v for v in walk({k: dash[k] for k in ("tiles", "charts", "framing", "experiments", "architecture")})}
num = re.compile(r"(?<![\w.#])(\d+\.\d+|\d+)(?![\w])")
hits, small = [], 0
for f in sorted((ROOT / "web/js").rglob("*.js")):
    for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        s = ln.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        for m in num.finditer(ln):
            v = float(m.group(1))
            if v in shown:
                if v.is_integer() and v < 100:
                    small += 1
                    print(f"SMALL-INT {f.relative_to(ROOT).as_posix()}:{i}: {m.group(1)}  | {s[:100]}")
                else:
                    hits.append(f"{f.relative_to(ROOT).as_posix()}:{i}: {m.group(1)}  | {s[:100]}")
print(f"{len(shown)} distinct shown values; {small} small integers listed above for reading")
for h in hits:
    print("HIT", h)
print(f"A1: {len(hits)} literal(s) equal a shown result value (non-small) -> {'PASS' if not hits else 'READ EACH'}")
