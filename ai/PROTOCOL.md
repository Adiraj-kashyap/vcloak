# PROTOCOL — how every session works

## 1. Unit of work
- A **module** (M00–M17) is a vertical slice with deliverables, tests, metrics and an audit.
- A **step** (S1, S2, …) is the checkpoint granularity inside a module. Each step ends with a check command.
- A **session** is one chat started by the human with `continue`. It completes at least one step and at
  most one module. Modules marked `est_sessions: 2+` are expected to span several sessions.

## 2. State machine (per module, stored in `state/STATE.md`)

```
NOT_STARTED ──start──▶ IN_PROGRESS ──all steps pass──▶ AUDIT_PENDING ──audit PASS──▶ DONE
                          │    ▲                            │
                          │    └────── fix ─────────────────┤ audit FAIL
                          │                                 ▼
                          ├──needs human──▶ BLOCKED_HUMAN   AUDIT_FAILED
                          └──unrecoverable──▶ BLOCKED_TECH (issue with options; human decides)
```
Only one module may be `IN_PROGRESS` at a time. `next_unit` always points to the first module **in the
order of the STATE.md table** (which is the intended build order, not strictly numeric: M18 sits between M16 and M17, and M22 then M19–M21 follow M17)
that is not DONE and whose dependencies are DONE, unless the human overrode it.
Modules marked `optional: yes` in STATE.md are skipped by `next_unit` until every required module is DONE
(the human can still run them explicitly with `continue Mxx`).

## 3. First session (STATE shows `last_session: 0`)
1. Read this file and `ai/PROJECT_BRIEF.md` (skim §1–§4).
2. Run the setup script for the human — do not hand them a list of installs:
   `setup/bootstrap.ps1` on Windows, `setup/bootstrap.sh` on macOS/Linux. It installs Python and Git if
   needed, creates `.venv`, installs packages, runs `git init`, and sets the git identity. Ask once for
   their name and email and pass them as the script's arguments so it runs without prompting.
   If the script says it installed Python or Git and exited, tell them to reopen the terminal and say
   `continue`; the script is idempotent, so just run it again.
3. Write `.gitignore` from `ai/CONVENTIONS.md §6`, then commit the kit as `chore: import build kit [owner:team]`.
4. Proceed with M00.

## 4. Checkpointing
After each step's check passes:
- Update `STATE.md → current_step` to the next step, and set `last_checkpoint` to the date and step.
- If the step created code, make a small commit: `wip(<Mxx>): S<n> <what>`.
If a session ends unexpectedly, the next session resumes at `current_step`. It first runs that step's
check command: if the check already passes, it advances without redoing the work.

## 5. Context budget heuristics (keep sessions cheap)
- Read only what the module's *Required reading* lists. Use `grep -n` to find sections.
- Never `cat` files over ~200 lines. Use `sed -n 'a,bp'` on the relevant range.
- Keep command output out of chat: `cmd > runs/.../out.txt 2>&1; tail -n 20 runs/.../out.txt`.
- If you have finished at least one step and the module still has several large steps left,
  prefer stopping cleanly at a checkpoint over squeezing everything into one session.
- The handoff must be ≤10 lines; the SESSION_LOG entry ≤25 lines.

## 6. Failure handling
| Situation | Action |
|---|---|
| A test fails and you understand the cause | Fix it within the step; re-run the check |
| The same check fails 3 times | Stop fixing. Open an ISSUE with what was tried, set `BLOCKED_TECH`, hand off |
| The spec is wrong or impossible on this hardware | Add an ADR proposal to `ai/DECISIONS.md` (status: PROPOSED), an `## Amendments` note in the module, and ask the human in the handoff |
| A GPU feature is unavailable (ncu counters, nvcc) | Record `NOT_MEASURED` with the reason, open an issue, continue with the rest |
| A dependency module is found to be broken | Open an ISSUE `BLOCKS: <current>`, set that module to `AUDIT_FAILED`, fix it first in the next session |

## 6b. GPU jobs (modules M03–M08, M14–M15 measurements)
The laptop has no GPU, so a module that needs CUDA splits into a **prep session** and an **ingest session**
(`ai/GPU_RUNNER.md §5`). In the prep session: finish all local work, pass every `numpy`-backend test, run
`python scripts/gpujob.py pack <Mxx>`, open a `GPU JOB READY` issue naming the zip and the notebook, set
`status: BLOCKED_HUMAN`, and hand off. In the ingest session: run `python scripts/gpujob.py ingest`, check
the gates, record metrics, audit, continue. Never record a GPU metric that did not come from an ingested
result bundle, and never let a `numpy`-backend number stand in for one.

## 7. Human gates
Format in ISSUES.md:
```
### ISSUE-<n> [OPEN] HUMAN ACTION REQUIRED — <short title>
BLOCKS: <Mxx>   SEVERITY: high
Why: <one line>
Do this:
  1. <exact step, with OS-specific variants if needed>
  2. ...
Confirm by running: <command whose output proves it's done>
Then type: continue
```
In the next session, run the confirm command first. If it passes, close the issue and resume.

**Write the issue so it can be acted on without opening anything else**: real paths, real URLs, the exact
menu clicks, and what to bring back. The human is in the IDE and should not have to go hunting through the
documentation. `YOUR_CHECKLIST.md` is the reference for the wording and the level of detail; a gate that
says "see the docs" is a badly written gate. Print the same text in the handoff, not only in ISSUES.md.

**Nothing is required of the human in advance.** Each gate is announced when the work reaches it — that is
the whole point of stopping. The only exception worth mentioning once, in the very first handoff, is that
the first GPU job (M00 S6) needs a Google or Kaggle account, so they can create one while other work continues.

## 8. Conflict and recovery rules
- **Source of truth:** git history and `runs/` manifests outrank STATE.md, which outranks chat memory.
- If STATE.md claims DONE but the module's tag `<Mxx>-done` is missing, re-run its audit.
- If the working tree is dirty at session start, run `git status` and `git diff --stat`, then either
  commit it as `wip(recovered)` (if it matches the current step) or stash it with a note in ISSUES.
- Never rewrite published history (no force-push, no rebase of tagged commits).

## 9. Definition of done (module)
1. All steps' checks pass in a fresh process.
2. Module tests pass: `pytest -q <module test path>` (outputs saved under runs/).
3. Required metrics are measured and indexed, or explicitly `NOT_MEASURED` with a reason.
4. The module audit and G1–G10 all PASS (or N/A with justification).
5. Docs updated: the module's deliverables exist, and `docs/` pages the module owns are current.
6. Committed and tagged `<Mxx>-done`; STATE advanced.

## 10. Quick mode
When the human appends `quick`, use the module's *quick* parameters (smaller n, fewer repetitions).
Tag the run dirs `_quick`. Quick numbers must never be reported as final results in `results/`.
