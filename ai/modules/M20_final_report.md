# M20 — Final report, results interpretation, refinements and limitations (Review 4, criteria 6, 7, 8)
owner: Team (Abhishek: results · Aditya: GPU chapters · Divyansh: system chapters) · depends_on: M16 · est_sessions: 3 · human_gates: guide's read-through

## Goal
A near-final report that is complete, internally consistent, and an accurate reflection of what was built —
with results that are *interpreted*, not just printed.

## Required reading
- `ai/REVIEW_RUBRICS.md` (criteria 6, 7, 8) · `docs/REPORT_CH4_NOTES.md` · `state/METRICS_INDEX.md`
- `ai/DECISIONS.md` (all ADRs) · each module's *Amendments* sections (`grep -n "## Amendments" ai/modules/*.md`)

## Deliverables
`report/` (chapters as markdown or LaTeX, plus the compiled PDF), `docs/RESULTS_ANALYSIS.md`,
`docs/REFINEMENTS.md`, `docs/LIMITATIONS_AND_FUTURE_WORK.md`, `report/TRACEABILITY.md`.

## Steps
- **S0 Start from the draft, do not restart.** M22 already produced the preliminary pages, Chapters 1–4,
  the bibliography, `TRACEABILITY.md` and `CONTRIBUTIONS.md`, and cleared the similarity check. Extend that
  document; re-run the similarity check at the end only if the new chapters are substantial.
- **S1 Chapter skeleton and ownership.** Ch.1 Introduction · Ch.2 Literature survey and gaps ·
  Ch.3 Threat model, design and architecture · Ch.4 Implementation · Ch.5 Testing, results and analysis ·
  Ch.6 Conclusion, limitations and future work · plus references, appendices (schema, kernel listing, test
  matrix) and the individual-contribution annexure. Assign each chapter an owner. Check: the skeleton exists
  with every section stubbed and owned.
- **S2 Results *interpretation*, not just reporting (criterion 6).** For every headline metric write what it
  means, why it has that value, what it would mean if it were different, and how it compares with the related
  work in Ch.2. Example shape: "turn-order accuracy falls to ~50% at W=300 s because f, the fraction of reply
  pairs inside one window, approaches 1; the residual above 50% is the cross-window order the design
  deliberately keeps." Check: no table or figure in Ch.5 lacks a paragraph reading it.
- **S3 Refinements, with before/after numbers (criterion 7).** `docs/REFINEMENTS.md`: for each of C1–C6 and any
  later ones — the problem, how it was found (which test), the fix, and the measured before/after. The
  Review-1 cross-epoch leak (98.3% → chance) is the strongest item; the kernel race (ADR-005), 128-bit tags,
  oblivious compaction, the corrected χ² statistic and the fixed slot count follow. Check: every entry has evidence paths.
- **S4 Limitations and future work (criterion 7).** State them plainly: passive-dump adversary only; a live
  server compromise is out of scope; window ids and per-window volume remain visible; the newest data is
  exposed at epoch granularity until its window closes; timings come from a shared cloud GPU; an integrated
  GPU cannot host this threat model (ADR-010); anything still `NOT_MEASURED`. Future work: PIR read path,
  hybrid post-quantum handshake, larger anonymity-set study. Check: each limitation names what would remove it.
- **S5 Consistency sweep (criterion 8).** Every number in the report resolves to a METRIC-ID; the design text
  matches the shipped code (not the Review-1 plan); figures are regenerated from `results/`; terminology, symbols
  and parameter values are uniform across chapters; the reference list matches the corrected bibliography.
  Write `report/TRACEABILITY.md`: claim → evidence path, one row per numeric claim.
  Check: `scripts/check_metrics.py` over `report/` passes; a diff of parameter values across chapters is empty.
- **S6 Individual contributions from git, not memory.** Generate per-member module and commit lists from
  `git log --format='%an|%s'` and the module ownership table. Check: the annexure matches git.
- **S7 Guide read-through (human gate).** Send the PDF; log the guide's comments into
  `state/REVIEW_FEEDBACK.md` as new items so criterion 1 keeps working.

## Audit checklist
- A1 Every chapter is complete — no `TODO`, no `\pending`, no placeholder left (grep).
- A2 Every numeric claim appears in `TRACEABILITY.md` with a resolvable evidence path.
- A3 Each Ch.5 table/figure has an interpretation paragraph (criterion 6 is about interpretation).
- A4 Limitations include the honest items listed in S4 — an omitted known limitation is an audit failure.
- A5 The contribution annexure is generated from git, not typed.
- G1–G10.

## Presenter notes
1. Pick any number in Chapter 5 and trace it to the command that produced it.
2. What is the most important thing you changed after measuring, and what did it change?
3. What does your system still not protect, and what would it take to fix?

## Next: M21

## Amendments
- 2026-10-14 (session 50, ADR-027): `docs/REFINEMENTS.md` already exists with one section, "Future work: group
  conversations", written when the owner declared the two-party scope. S3 adds the refinements C1-C* above it
  and keeps that section; `docs/LIMITATIONS_AND_FUTURE_WORK.md` refers to it rather than restating it.
