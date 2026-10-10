# M17 — Final audit, reproducibility, demo runbook
owner: Team · depends_on: all required modules (M13 optional) · est_sessions: 1–2 · human_gates: a rehearsal with the team

## Goal
Prove the project is reproducible from a clean clone, every module audit still passes, and the Review demo is scripted.

## Required reading
- `ai/LOGGING_AND_AUDIT.md §3` · `state/STATE.md` · each module's *Audit checklist* (one at a time, while re-auditing)

## Deliverables
`scripts/repro_quick.(sh|ps1)`, `docs/DEMO.md`, `docs/REPORT_CH4_NOTES.md` (final), `state/FINAL_AUDIT.md`.

## Steps
- **S1 Clean-clone quick repro.** Clone to a temp dir; venv; install from requirements.lock; run
  `VCLOAK_BACKEND=numpy pytest -m "not slow and not gpu"`, the security eval in quick mode, the two-user demo, and
  `tasks.py dashboard` (asserting the committed `web/data/dashboard.json` matches a fresh regeneration).
  Then pack one quick GPU job, have the human run it, and ingest it — proving the whole bridge still works end to end.
  All pass; save the run dir.
- **S2 Re-audit.** Re-run every module's audit (quick where allowed). Record the results in FINAL_AUDIT.md as a single table.
- **S3 Demo runbook.** A 6-minute live demo, all inside the app at `/app`: (1) `vcloak serve --dev`, open Chat;
  (2) two users exchange messages; (3) the server view shows the stored rows shuffled — flip to baseline mode and
  show the order reappear; (4) Experiments tab: run the order-recovery attack live, baseline ≈100% vs V-cloak ≈ chance;
  (5) Dashboard: GPU kernel sweep, crossover and dudect verdicts, with provenance (which GPU, which runner);
  (6) Logs tab: the audit trail; (7) DPoP stolen-token rejection. Include exact commands and expected outputs from
  real runs, plus the offline fallback: `web/index.html` opened from `file://` serves the last exported data.
- **S4 Report notes.** Finalise REPORT_CH4_NOTES: implementation summary, results with `<!--M:ID-->` tags, and individual contributions
  (generated from `git log --format='%an %s' | grep owner:` counts per owner, plus the module ownership table).

## Audit checklist
- A1 The clean clone passes. A2 All module audits PASS (or documented N/A). A3 The demo was rehearsed once by the human (confirmation issue closed).
- A4 Contribution stats come from git, not typed by hand. G1–G10.

## Presenter notes
Each member rehearses the demo segment for the modules they own.

## Next: M22  (then M19 — start the publication in parallel, it is calendar-bound)
