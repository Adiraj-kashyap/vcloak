# M19 — Research publication or IP submission (Review 4, criterion 9)
owner: Abhishek (manuscript) · Aditya (GPU results) · Divyansh (system results) · Guide: Dr. Mary Shamala L
depends_on: M16 (real results exported) · est_sessions: 2–3 · human_gates: guide's approval; the actual submission (only a human can press submit); venue account

## Why this module is scheduled early
Criterion 9 is worth 2 marks and awards **nothing without documentary proof** of submission. It is the only
criterion that depends on an outside party and a calendar: conference deadlines are fixed, and journal
acknowledgement emails arrive when they arrive. Start it the moment M16 produces real results; everything
else in the project can be polished later, this cannot be rushed at the end.

## Goal
A submitted manuscript (or filed IP), with the proof archived in the repository.

## Required reading
- `ai/REVIEW_RUBRICS.md` (Review 4, criterion 9) · `seed/PAPER_RESULTS_CONTRACT.md`
- `results/PAPER_UPDATES.md` (written by M16) · `state/METRICS_INDEX.md` (skim the IDs) · `evidence/INDEX.md`
- `ai/EVIDENCE.md §5` — figures come from `evidence/figures/`; this module makes no new evidence

## Deliverables
`review/publication/manuscript/` (the paper source and the compiled PDF),
`review/publication/venue_shortlist.md`, `review/publication/submission_proof/` (confirmation email as PDF,
submission/paper ID, portal screenshot, timestamp), `review/publication/SUBMISSION.md` (one page: venue,
track, date, ID, authors in order, status), `docs/RESULTS_ANALYSIS.md` (shared with M20).

## Steps
- **S1 Decide the route.** Prepare a short comparison for the humans to choose from, and ask them:
  (a) an international conference with a dated CFP, (b) a peer-reviewed journal, (c) a patent/IP filing
  through the institute's cell. Note for each: deadline, fee, page limit, template, typical turnaround,
  and whether a submission receipt is issued immediately (criterion 9 needs that receipt).
  Research the current CFPs with web search; **verify every deadline on the venue's own site** and record
  the URL and the date checked. Do not rely on aggregator listings. Check: `venue_shortlist.md` exists with
  at least three dated options and their sources.
- **S2 Fit the manuscript to the venue.** Apply the chosen template and page limit. Fold in everything from
  `results/PAPER_UPDATES.md`: the ChaCha20/Poly1305 server-crypto profile (ADR-003), the pair-per-thread
  kernel fix (ADR-005), host-side payload gather (ADR-006), the remote-GPU measurement setup (ADR-009) and
  the integrated-GPU argument (ADR-010). Every number comes from `results/` macros — none retyped.
  Check: the PDF builds, is inside the page limit, and `scripts/check_metrics.py` passes over the manuscript.
- **S3 Honesty pass before submission.** Confirm the claims the paper makes are the claims the evidence
  supports: per-window order indistinguishability (not absolute), the leakage table present, cloud-shared-GPU
  caveat on timings, `NOT_MEASURED` items stated as such, and the threat model's exclusion of a live-server
  compromise. Any overclaim found here is a defect, not a presentation choice. Check: a written claim-by-claim
  table in `SUBMISSION.md` mapping each claim to its evidence path.
- **S4 Author order, affiliations, guide approval (human gate).** Prepare the final author block and send the
  PDF to the guide. Open a HUMAN ACTION issue: guide's approval is required before submission. Stop.
- **S5 Submit (human gate).** The human submits. The agent cannot and must not: it has no venue account, and
  a submission is an irreversible external act. Issue text must state exactly what to do and what to bring back:
  the confirmation email (saved as PDF), the submission/paper ID, and a screenshot of the portal's submitted state.
- **S6 Archive the proof.** File everything in `review/publication/submission_proof/`, write `SUBMISSION.md`,
  and add a line to `state/REVIEW_FEEDBACK.md` under criterion 9. Check: the proof files exist and `SUBMISSION.md`
  names the venue, date and ID.

## Audit checklist
- A1 `venue_shortlist.md` has ≥3 options, each with a deadline and the source URL plus the date verified.
- A2 Every number in the manuscript traces to a METRIC-ID (check_metrics.py over the source).
- A3 The claim-by-claim honesty table exists and no claim lacks an evidence path.
- A4 Guide approval recorded before submission (issue closed with their reply referenced).
- A5 **Documentary proof present**: confirmation PDF + ID + screenshot. Without all three, this module is NOT DONE,
  and the audit says so rather than passing it as "submitted".
- G1–G10 (G2 applies to the manuscript too).

## Pitfalls
- A manuscript that is finished but unsubmitted scores **zero** on criterion 9. Submission is the deliverable.
- Student-authored papers usually need the guide as corresponding author — confirm before, not after.
- Keep the arXiv/preprint question separate: a preprint is not peer-reviewed submission proof on its own.

## Presenter notes
1. Which venue, which track, when did you submit, and what is the paper ID?
2. Which claims in the paper are measured, and which are explicitly marked not yet measured?
3. What did you change in the paper after the implementation contradicted the Review-1 design?

## Next: M20
