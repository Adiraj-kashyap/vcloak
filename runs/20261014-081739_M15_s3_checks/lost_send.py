"""ISSUE-51 / ISSUE-52: what the ingested 200-user V-cloak cells say about the sends that got no answer.

Reads samples.csv, summary.json and server_log.txt of the two cells; writes no metric. Run from the repository root:

    python runs/20261014-081739_M15_s3_checks/lost_send.py

Question: was the lost send a timeout of the generator, or a send the service accepted that was never readable?
What can be read from the files:
1. the error class of every failed send, and whether any ACKNOWLEDGED send was not read back by its peer;
2. the rows the service wrote per closed window (`window_closed rows=N` in its log) against the sends of the
   generator. A row belongs to the window in which the service queued it. For every window boundary B the rows
   stored before B must lie between the acknowledged sends whose answer arrived before B (they were stored) and
   the acknowledged sends submitted before B (nothing submitted later can be in). A stored-but-unacknowledged
   send would add one row: the bracket shows whether the files can see one row.
"""
from __future__ import annotations

import csv
import json
import re

CELLS = ("runs/20261014-015212_M15_vcloak_u200_r1", "runs/20261014-020839_M15_vcloak_u200_r2")
ALL = "runs/20261014-0[12]*_M15_*_u*_r[12]"


def main() -> None:
    import glob
    print("1. every cell of the job: failed sends, and acknowledged sends the peer never read")
    for d in sorted(glob.glob(ALL)):
        s = json.load(open(d + "/summary.json"))
        rows = list(csv.DictReader(open(d + "/samples.csv")))
        failed = [r for r in rows if r["error"]]
        unread = [r for r in rows if not r["error"] and r["ack_ms"] and not r["readable_ms"]]
        print(f"   u{s['users']:<4}{s['mode']:<9}r{s['rep']} sends {len(rows):5} failed {len(failed)} "
              f"{sorted({r['error'] for r in failed}) or ''} acknowledged and never read {len(unread)} "
              f"read errors {s['reads']['errors'] or ''}")
    print("2. the two cells with failed sends: rows per closed window against the sends")
    for d in CELLS:
        s = json.load(open(d + "/summary.json"))
        t0 = s["t0_unix"]
        rows = list(csv.DictReader(open(d + "/samples.csv")))
        ok = [r for r in rows if not r["error"]]
        print(f"   {d}  (request timeout of the generator: 30 s; httpx reports a timeout as ReadTimeout)")
        for r in rows:
            if r["error"]:
                print(f"     failed: user {r['user']} scheduled {float(r['t_sched_s']):.2f} s submitted "
                      f"{float(r['t_submit_s']):.2f} s error {r['error']} status {r['status']} counted {r['counted']}")
        cum = 0
        log = open(d + "/server_log.txt", encoding="utf-8").read()
        for m in re.finditer(r"window_closed rows=(\d+) win=(\d+)", log):
            n, win = int(m.group(1)), int(m.group(2))
            cum += n
            b = (win + 1) * s["service"]["windows"]["window_s"] - t0
            lo = sum(float(r["t_submit_s"]) + float(r["ack_ms"]) / 1e3 < b for r in ok)
            hi = sum(float(r["t_submit_s"]) < b for r in ok)
            lost = sum(float(r["t_submit_s"]) < b for r in rows if r["error"])
            print(f"     window {win} closes at {b:7.2f} s: rows stored so far {cum}; acknowledged sends answered "
                  f"before it {lo}, submitted before it {hi} (bracket {hi - lo} wide); failed sends before it {lost}")
        print("     -> the rows sit just above the lower end of the bracket: a send entered the service's queue "
              "shortly before its answer, not when the generator submitted it.")
        print("     -> the bracket is far wider than one row: these files cannot say whether a failed send was stored.")


if __name__ == "__main__":
    main()
