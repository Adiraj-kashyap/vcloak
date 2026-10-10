---
name: status
description: Show V-cloak build progress without doing any work. Use when the user types "status" or asks where the project stands.
---
Read `state/STATE.md` only, then print:
- A table: module | title | owner | status | sessions used.
- The current unit and step, and the next unit.
- OPEN issues (`grep -n "OPEN" state/ISSUES.md`), human actions first.
- The last 3 metrics added (`tail -n 5 state/METRICS_INDEX.md`).
Do not modify files. Do not commit.
