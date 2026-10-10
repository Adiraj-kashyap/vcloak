# M21 — Integration, validation and Review-4 readiness (criteria 1, 2, 3, 5, 10)
owner: Team · depends_on: M17, M19, M20 · est_sessions: 2–3 · human_gates: paste the Review-3 panel comments; one full rehearsal

## Goal
Prove the thing runs as one system, that every panel comment was acted on, that the test coverage is
defensible, and that all three members can demonstrate and answer for their own work.

## Required reading
- `ai/REVIEW_RUBRICS.md` (Review 4, all) · `state/REVIEW_FEEDBACK.md` · `state/STATE.md`
- `ai/TESTING.md` · `docs/DEMO.md`

## Deliverables
`review/REVIEW4_CHECKLIST.md`, `review/SCOPE_COMPLETION.md`, `docs/TEST_SUMMARY.md`,
`review/DEMO_SCRIPT.md`, `review/QA_BANK.md`, `runs/<ts>_M21_soak/`, `runs/<ts>_M21_e2e_rehearsal/`.

## Steps
- **S1 Close out every panel comment (criterion 1).** If `state/REVIEW_FEEDBACK.md` has no Review-3 entries,
  **stop and ask the human to paste the panel's comments verbatim** — this criterion cannot be inferred and must
  not be invented. Then, for each item: the action taken, the commit, and the evidence. Anything deliberately not
  done gets a stated reason, which is still better than silence. Check: zero OPEN items, or each remaining one
  carries an explicit justification.
- **S2 Scope completion table (criterion 2).** `SCOPE_COMPLETION.md`: every approved deliverable from the
  Review-1 plan → where it lives → DONE / partial / dropped-with-reason. Reconcile against STATE.md; a module
  marked DONE whose deliverables are missing is a defect to fix now. Check: STATE and the table agree.
- **S3 End-to-end integration run (criterion 3).** One scripted run on a clean database: start the service,
  register two users, exchange ≥200 messages across ≥3 windows, confirm window re-shuffle fired, read
  everything back in order, dump the database and run the attack, then show the dashboard reflecting the new
  run. No manual repair steps allowed mid-run. Check: the script exits 0 and the run dir holds its log.
- **S4 Stability soak (criterion 3).** Run the service for ≥30 minutes under steady load; record memory,
  GPU-job cadence where relevant, epoch overflow count, and any error. A crash or unbounded growth is an issue
  to fix, not a footnote. Check: soak run dir with a summary; no unhandled exceptions in the log.
- **S5 Test and validation summary (criterion 5).** `docs/TEST_SUMMARY.md`: counts per layer (unit, golden, gpu,
  integration, security), what each layer guarantees, the golden vectors and their published sources, the
  acceptance gates and their pass/fail, and an honest list of what is *not* covered. Check: the counts match a
  fresh `pytest` run saved in a run dir.
- **S6 Demo script and rehearsal (criterion 10).** `review/DEMO_SCRIPT.md`: an 8–10 minute run with timings,
  exact commands, expected screen state at each beat, who speaks when, and the fallbacks (the `file://` offline
  app; pre-recorded run dirs if the GPU or Wi-Fi fails). Rehearse once end to end with all three members and log
  what broke. Check: a rehearsal entry exists in the session log.
- **S7 Question bank (criterion 10).** `review/QA_BANK.md`: collect every *Presenter notes* question from all
  modules, plus the hard ones — why not an integrated GPU; why cloud GPU numbers are trustworthy and what their
  caveat is; what the system still leaks; what the weakest result is; what you would do with another month.
  Each answer owned by the member who built that part. Check: every module's presenter questions are included.
- **S8 Final readiness scorecard.** Run the `review-check` skill, paste its table into
  `review/REVIEW4_CHECKLIST.md`, and list the remaining actions in priority order with owners and dates.

## Audit checklist
- A1 `state/REVIEW_FEEDBACK.md` has no unexplained OPEN items.
- A2 Scope table reconciles exactly with STATE.md.
- A3 The end-to-end script ran clean on a fresh database, with its log saved.
- A4 The soak run shows no unhandled exception and no unbounded growth.
- A5 Test summary counts match a saved `pytest` run, and the not-covered list is present and honest.
- A6 Rehearsal logged; the fallback path was exercised at least once, not just written down.
- A7 Each member owns answers for the modules they built (cross-check with the contribution annexure).
- G1–G10.

## Presenter notes
Each member: your three hardest questions, answered without notes. The team: what the panel asked last
time and what you changed because of it.

## Next: none — this is the final unit. After it, use `review-check` before each rehearsal.
