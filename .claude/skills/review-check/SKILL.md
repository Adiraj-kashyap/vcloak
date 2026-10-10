---
name: review-check
description: Score the project against the Review 3 or Review 4 rubric and list exactly what is missing. Use when the user types "review check", "review4", "am I ready for the review", or asks what is left before a review.
---
Read `ai/REVIEW_RUBRICS.md`, `state/STATE.md`, `state/REVIEW_FEEDBACK.md`, and
`tail -n 30 state/METRICS_INDEX.md`. Three rubrics exist: Review 3 (20), Draft/Report Review (5) and
Review 4 (25). Score the one the user names (`review check draft`, `review check 3`); with no argument,
score the next gate that is not yet passed, and say which one you picked.

For each criterion produce one row: **criterion · marks · status (MET / PARTIAL / NOT MET) · the
evidence path that proves it · the single next action if it is not met.**

Rules for judging:
- MET requires an artefact that exists on disk now — a run dir, a DONE module, a committed file.
  A plan, an intention, or a module in progress is PARTIAL at best.
- Criterion 2 is MET only when every module marked required in STATE.md is DONE.
- Criterion 9 is MET only when `review/publication/` holds documentary proof (submission confirmation,
  paper ID or filing receipt). A finished manuscript with no submission proof is NOT MET — say so plainly.
- Criterion 1 is NOT MET if `state/REVIEW_FEEDBACK.md` has any OPEN item, or if it holds no Review-3
  entries at all (then ask the human to paste the panel's comments).
- Draft/Report Review criterion 4 is MET only when `review/similarity/` holds a report produced by the
  institute's tool and its score is within the stated limit. A self-estimated score is NOT MET.
- Draft/Report Review criterion 2 is NOT MET if the report still describes a design the ADRs superseded.
- Never inflate a score to be encouraging. An honest gap list is the point of this command.

Finish with: the total realistic marks, the three highest-value actions in order, and whether anything
is calendar-bound (criterion 9 almost always is). Do no build work and make no commit.
