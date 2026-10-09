---
name: continue
description: Run one V-cloak build work unit following CLAUDE.md §1. Use when the user types "continue", "continue Mxx", "/continue", or asks to proceed with the next part of the project.
---
Execute the session loop in `CLAUDE.md §1` exactly once.

Arguments: `$ARGUMENTS` may contain a module id (e.g. `M07`) and/or `quick`.

1. Orient: read `state/STATE.md`; `tail -n 40 state/SESSION_LOG.md`; `grep -n "OPEN" state/ISSUES.md | head -20`.
2. If `$ARGUMENTS` names a module, check that its `depends_on` modules are DONE in STATE.md. If not, say which are missing and stop.
3. Read the module file and only its *Required reading*.
4. Execute from `current_step`, checkpointing STATE.md after each passed step.
5. Verify, then audit (use the `audit` skill procedure), then record (use the `session-close` skill), commit and hand off.
6. STOP after the handoff. Do not begin another unit.
