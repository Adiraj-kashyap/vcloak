---
name: session-close
description: Record, commit and hand off at the end of a V-cloak session. Use at steps 7-9 of every session.
---
1. Append one SESSION_LOG entry (template in `ai/LOGGING_AND_AUDIT.md §1`). Keep it under 25 lines.
2. Append METRICS_INDEX rows for every new number (template in §5 of the same file).
3. Update ISSUES.md: close resolved items with the commit hash; open new ones with severity and a BLOCKS tag.
4. Update STATE.md: module status, current_step, sessions_used, next_unit, last_session number and date.
5. Commit: `git add -A && git commit -m "<Mxx>: <summary> [S<a>-S<b>] [owner:<name>]"`.
   Write the commit hash into the SESSION_LOG entry with a second small commit (`chore(log): hash`).
6. Print the handoff (≤10 lines) and STOP.
