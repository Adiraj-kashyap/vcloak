"""ISSUE-25: what the ingested job 20261012-191630_M08_issue25 says about the SM clock and the verdicts.
Reads the four ingested run dirs; measures nothing. Usage: python clock_facts.py <out.txt>"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

RUNS = ("20261012-135427_M08_dudect_i25_s8", "20261012-145303_M08_dudect_i25_s10",
        "20261012-155223_M08_dudect_i25_s11", "20261012-165055_M08_dudect_i25_s12")
TARGETS = ("control_null", "write_epoch_null_st", "write_epoch_age_st", "write_epoch_fresh_st")
out: list[str] = []
tally: Counter[tuple[str, str]] = Counter()
by_series: Counter[tuple[str, str]] = Counter()
for run in RUNS:
    d = Path("runs") / run
    rows = list(csv.DictReader((d / "telemetry.csv").open(encoding="utf-8")))
    clocks = [int(float(r["sm_clock_mhz"])) for r in rows]
    throttle = Counter(r["throttle_reasons"] for r in rows)
    out.append(f"{run}: {len(rows)} telemetry rows; throttle_reasons {dict(throttle)}")
    out.append(f"  SM clock histogram (MHz: rows) {dict(sorted(Counter(clocks).items()))}")
    for t in TARGETS:
        j = json.loads((d / f"dudect_{t}.json").read_text(encoding="utf-8"))
        c = j["clock"]
        kind = "control" if t == "control_null" else "write_epoch"
        out.append(f"  {t}: clock before {c['before_mhz']} after {c['after_mhz']} MHz, relative change "
                   f"{c['relative_change']:.4f}, status {c['status']}, warm-up clocks {j['warmup']['clocks_mhz']}")
        for name, s in j["series"].items():
            tally[(f"{kind} at {c['before_mhz']}-{c['after_mhz']} MHz", s["verdict"])] += 1
            tally[(kind, s["verdict"])] += 1
            if kind == "write_epoch":
                by_series[(f"{t}/{name}", s["verdict"])] += 1
out.append("")
out.append("series by kind and verdict (the pass/fail split against the clock split):")
for (k, v), n in sorted(tally.items()):
    if " at " not in k:
        out.append(f"  {k:<12} {v:<5} {n}")
out.append("series by clock of the target and verdict:")
for (k, v), n in sorted(tally.items()):
    if " at " in k:
        out.append(f"  {k:<34} {v:<5} {n}")
out.append("write_epoch series, seeds with PASS / FAIL (all four seeds at 585 MHz):")
for key in sorted({k for k, _ in by_series}):
    out.append(f"  {key:<34} PASS {by_series[(key, 'PASS')]}  FAIL {by_series[(key, 'FAIL')]}")
Path(sys.argv[1]).write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out[-48:]))
