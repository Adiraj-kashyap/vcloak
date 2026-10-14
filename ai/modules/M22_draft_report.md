# M22 — Draft report: preliminary pages, Chapters 1–4, citations and similarity (Draft/Report Review, 5 marks)
owner: Team (Abhishek: results chapters · Aditya: GPU chapters · Divyansh: system chapters) · depends_on: M16 · est_sessions: 2–3
human_gates: the institute's report template; the similarity check (Turnitin/Urkund — runs through the guide or department); guide's read-through

## Note on sequencing
The report and the paper are written **last**, from `evidence/INDEX.md` and `results/`. That is the
intended order: this module selects and assembles, it does not go back and re-run experiments. If a
needed figure or proof is missing from `evidence/`, re-run the module that produces it rather than
approximating — see `ai/EVIDENCE.md §5`.

## Goal
A draft report that is complete for this stage, matches what was actually built, is backed by real outputs,
is properly cited and within the similarity limit, and states who did what.

Each of the five criteria is worth one mark, so none is worth skipping and none needs gold-plating.
This is also the dress rehearsal for Review-4 criteria 6–8: everything done here is reused by M20.

## Required reading
- `ai/REVIEW_RUBRICS.md` (Draft / Report Review section) · `ai/DECISIONS.md` (every ADR)
- `docs/REPORT_CH4_NOTES.md` · `state/METRICS_INDEX.md` (skim) · `state/REVIEW_FEEDBACK.md` · `evidence/INDEX.md`

## Deliverables
`report/` (preliminary pages + Chapters 1–4, source and compiled PDF), `report/references.bib`,
`report/TRACEABILITY.md`, `report/CONTRIBUTIONS.md`, `review/similarity/` (the report plus the
submission-ready PDF that was checked), `docs/CITATION_NOTES.md`.

## Steps
- **S1 Get the institute's template (human gate).** Ask for the SCOPE/VIT report template and the current
  similarity limit, as a file or a link. Do **not** invent the preliminary-page set, margins, font or
  certificate wording — those are prescribed and a wrong format costs criterion 1. If the template is not
  available yet, build the chapters in plain markdown and keep formatting separate, so nothing is wasted.
  Check: the template is in `report/template/`, or an issue records that it is pending.
- **S2 Preliminary pages (criterion 1).** Title page, bonafide/completion certificate, declaration, abstract,
  acknowledgement, table of contents, list of figures, list of tables, list of abbreviations — in the
  template's order. The abstract states the measured outcome, not the aspiration. Generate the contents and
  figure/table lists from the document, never by hand. Check: every page in the template's list exists.
- **S3 Chapters 1–4 (criterion 1).** Ch.1 Introduction (problem, objectives, scope) · Ch.2 Literature survey
  with the gap table · Ch.3 Threat model, design, architecture (data-state flow, keys, parameters) ·
  Ch.4 Implementation and interim results. Ch.4 must describe what exists now and mark what does not yet
  exist as pending — an honest "not yet measured" costs nothing here and protects criterion 2.
  Check: no chapter is a stub; no `TODO`/`\\pending` left (grep).
- **S4 Report-vs-implementation consistency (criterion 2).** This is nearly free if done mechanically:
  the ADR list *is* the list of differences from the original plan, so walk it and confirm the report
  describes the **built** system rather than the Review-1 plan: ChaCha20/Poly1305 server crypto (ADR-003), pair-per-thread
  comparator (ADR-005), host-side payload gather (ADR-006), coarse window + re-shuffle (ADR-004), remote GPU
  measurement (ADR-009), integrated GPU rejected (ADR-010). Also confirm parameter values in the text match
  `src/vcloak/config.py`. Write `report/TRACEABILITY.md`: claim → evidence path, one row per numeric claim.
  Check: a scripted comparison of config values against the report text reports no mismatch.
- **S5 Evidence for every claim (criterion 3).** Each result in Ch.4 carries its table or figure, regenerated
  from `results/`, with an interpretation sentence. Anything from the seed oracle rather than this build is
  labelled as such; anything from a cloud GPU carries that caveat. Check: `scripts/check_metrics.py` over
  `report/` passes, and no figure is an image pasted from an older document.
- **S6 Citations and references (criterion 4).** Every claim about prior work cites a real paper, with the
  corrected entries from the kit's bibliography (Snoopy → Stoica; Talek → Cheng et al.; the Lin/Shi/Xie SODA
  paper; Zhu et al. and the sub-7% figure). Verify each entry against its published record — authors, venue,
  year — and fix anything that disagrees. Quote sparingly and attribute inline. Check: no `??` in the compiled
  PDF; every bib entry has a venue and year; the reference list and in-text citations match.
- **S7 Similarity check (human gate, criterion 4).** Produce the submission-ready PDF, then ask the human to
  run it through the institute's tool via the guide or department, and to bring back the report. If the score
  is over the limit, fix the causes rather than the symptoms: rewrite reused passages from your own earlier
  documents in fresh words, cut over-long literature quotes to paraphrase with citation, and leave templated
  certificate/declaration text alone (it is usually excluded — confirm with the guide). Re-check after edits.
  Check: `review/similarity/` holds the report and the final score, and the score is within the stated limit.
- **S8 Contribution and guide feedback (criterion 5).** `report/CONTRIBUTIONS.md` generated from
  `git log --format='%an|%s'` plus the module ownership table, so it matches reality. Then go through
  `state/REVIEW_FEEDBACK.md` and show, item by item, where each earlier correction was incorporated — that is
  the whole of criterion 5. Log the guide's new comments as fresh feedback items.
  Check: zero OPEN feedback items without an explanation; the annexure matches git.

## Audit checklist
- A1 Every preliminary page in the template's list is present, in order.
- A2 Chapters 1–4 complete; no stub, `TODO` or placeholder (grep output saved).
- A3 TRACEABILITY.md covers every numeric claim, and `check_metrics.py` over `report/` passes.
- A4 Each ADR is reflected in the report text (one line each, with the section where it appears).
- A5 Bibliography verified entry by entry; no `??` in the PDF.
- A6 Similarity report archived and within the limit — **or** an open issue recording that the check is
  pending with the department. Never state a score that was not produced by the institute's tool.
- A7 CONTRIBUTIONS.md generated from git; every earlier feedback item shows where it was incorporated.
- G1–G10.

## Pitfalls
- Describing the Review-1 design because it is already written is the single most likely way to lose
  criterion 2 — the implementation deliberately diverged, and the report must say so.
- Self-plagiarism from your own Review-1/2 submissions is the usual cause of a high similarity score.
- The similarity check has a queue. Ask for it a week before the deadline, not the night before.

## Presenter notes
1. Which parts of the report describe something different from the Review-1 plan, and why?
2. Pick a number in Chapter 4 and trace it to the command that produced it.
3. What was your similarity score, and what did you change to get there?

## Next: M19  (publication — start it in parallel; it is calendar-bound)

## Amendments
- 2026-10-14 (session 50, ADR-027): Ch.3 (design) states as declared scope that V-cloak supports two-party
  conversations only, and Ch.1 (scope) agrees with it. Group conversations are named as future work with the
  reason of `docs/REFINEMENTS.md`. Every population quoted from Ch.4 keeps "two users per conversation".
