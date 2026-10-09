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
  `pytest -m "not slow"`, the GPU probe, the kernel sweep in quick mode, the security eval in quick mode, and the two-user demo.
  All pass; save the run dir.
- **S2 Re-audit.** Re-run every module's audit (quick where allowed). Record the results in FINAL_AUDIT.md as a single table.
- **S3 Demo runbook.** A 6-minute live demo: (1) `vcloak serve`, (2) two-user chat, (3) show the shuffled DB dump next to the baseline,
  (4) run the attack live: baseline 100% vs V-cloak ≈ chance, (5) show the GPU kernel sweep plot and dudect verdicts,
  (6) show the DPoP stolen-token rejection. Include exact commands and expected outputs (from real runs), plus
  fallbacks if Wi-Fi or GPU drivers fail (pre-recorded run dirs).
- **S4 Report notes.** Finalise REPORT_CH4_NOTES: implementation summary, results with `<!--M:ID-->` tags, and individual contributions
  (generated from `git log --format='%an %s' | grep owner:` counts per owner, plus the module ownership table).

## Audit checklist
- A1 The clean clone passes. A2 All module audits PASS (or documented N/A). A3 The demo was rehearsed once by the human (confirmation issue closed).
- A4 Contribution stats come from git, not typed by hand. G1–G10.

## Presenter notes
Each member rehearses the demo segment for the modules they own.
