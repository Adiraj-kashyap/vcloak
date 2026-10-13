"""ISSUE-48 point 3: is the 0 divergent / 0 uniform of bitonic_pairs_global on runner pc-rtx3050laptopgpu a reading?
A lookup against evidence already held (the saved SASS listing and the ingested ncu run); nothing is measured
and nothing is typed in.

    python runs/20261014-014529_M08_issue48_report/sass_crosscheck.py

Rule of the owner (session 48): no branch instruction in the listing -> the 0/0 is explained (report the 0 as
corroborated by SASS); a branch instruction in the listing -> the counter failed (NOT_MEASURED).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from vcloak.bench.report_oblivious import HW_BRANCH_INST, SASS_BRANCH_INST, listing_instructions  # noqa: E402

SASS = ROOT / "runs" / "20261012-040020_M08_sass"
NCU = ROOT / "runs" / "20261014-003929_M08_ncu"
BRANCH_OPS = ("BRA", "BRX", "JMP", "JMX", "CALL", "RET", "EXIT", "BREAK", "BSSY", "BSYNC")


def main() -> int:
    sass = json.loads((SASS / "summary.json").read_text(encoding="utf-8"))
    ncu = json.loads((NCU / "summary.json").read_text(encoding="utf-8"))
    man = json.loads((NCU / "manifest.json").read_text(encoding="utf-8"))
    print(f"SASS listings: {SASS.name}/sass_*.txt, arch {sass['log']['arch']}, "
          f"{sass['log']['files']['bitonic.cu']['disassembler']}")
    print(f"ncu run: {NCU.name}, runner {man['env']['runner']}, cc {man['env']['cc']} (nvrtc build: another build "
          "of the same source than the listing)")
    listing: dict[str, dict[str, str]] = {}
    for f in sorted(SASS.glob("sass_*.txt")):  # every kernel listing of the run; the control is not audited
        if not f.name.endswith("_branches.txt") and "control" not in f.name:
            listing.update(listing_instructions(f))
    with (NCU / "ncu_by_kernel.csv").open(newline="", encoding="utf-8") as f:
        counters = {(r["kernel"], r["metric"]): r["sum"] for r in csv.DictReader(f)}
    indexed = {m["id"]: m["value"] for m in sass["metrics"]}
    verdicts = {}
    for k in man["params"]["kernels"]:
        ins = listing.get(k, {})
        branches = {a: i for a, i in ins.items() if any(op in i.replace("@", " ").replace("!", " ").split()[:2]
                                                         for op in BRANCH_OPS)}
        cond = {a: i for a, i in branches.items() if i.startswith("@")}
        d = ncu["per_kernel"][k]
        mid = "T-SASS-BRA-" + k.upper().replace("_", "-")
        print(f"\n{k}: {len(ins)} instructions in the listing, {len(branches)} branch instructions "
              f"({len(cond)} conditional); index {mid} = {indexed.get(mid)}")
        for a, i in sorted(branches.items()):
            print(f"    {a}  {i}")
        print(f"  ncu: divergent {d['divergent']}  uniform {d['uniform']}  launches {d['launches']}")
        print(f"  ncu: {SASS_BRANCH_INST} = {counters.get((k, SASS_BRANCH_INST))}   "
              f"{HW_BRANCH_INST} = {counters.get((k, HW_BRANCH_INST))}")
        if d["divergent"] + d["uniform"] > 0:
            verdicts[k] = "MEASURED (the counter counted branch targets of this kernel)"
        elif not branches:
            verdicts[k] = "0, CORROBORATED BY SASS (no branch instruction in the listing)"
        else:
            verdicts[k] = ("NOT_MEASURED (0/0 although the listing has branch instructions: the counter "
                           "collected nothing)")
        if len(branches) != indexed.get(mid):
            print(f"  note: this opcode scan lists {len(branches)} lines, scripts/sass_check.py indexed "
                  f"{indexed.get(mid)}; both are above zero" if branches and indexed.get(mid)
                  else "  note: the two counts disagree about zero")
            if bool(branches) != bool(indexed.get(mid)):
                return 1
    c = ncu["control"]
    print(f"\ncontrol {c['kernel']}: divergent {c['divergent']}  uniform {c['uniform']}  launches {c['launches']}  "
          f"divergent_seen {c['divergent_seen']}")
    print("\nVERDICT per audited kernel:")
    for k, v in verdicts.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
