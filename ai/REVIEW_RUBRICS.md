# REVIEW RUBRICS — what the panel actually marks

The build exists to satisfy these. Every module's deliverables map to a criterion below. When planning
a session, prefer the work that closes an unmet criterion over work that polishes a met one.

---

## Review 3 — 20 marks (interim)

| # | Criterion | Marks | Assessment focus | Where it comes from |
|---|---|---|---|---|
| 1 | Implementation | 5 | Working modules ≈ half the approved scope; evidence **executable and attributable to the team** | M00–M08 run live; `runs/`; git history with `[owner:…]` |
| 2 | Technical accuracy | 5 | Correct methods, algorithms, parameters, practices consistent with the approved design | `ai/DECISIONS.md`, design-rationale table, bit-exactness tests |
| 3 | Results obtained so far | 5 | Interim metrics, tables, graphs, with sound interpretation and comparison | `state/METRICS_INDEX.md`, the Dashboard view |
| 4 | Presentation and clarity | 5 | Logical explanation, justified decisions, accurate answers to the panel | the app demo + each module's *Presenter notes* |

---

## Draft / Report Review — 5 marks (between Review 3 and Review 4)

One mark each, so each criterion is cheap to earn and cheap to lose. The marker reads the **report**,
not the code — so the job is making the report an accurate, well-evidenced mirror of the work.

| # | Criterion | Marks | Assessment focus | Where it comes from | Module |
|---|---|---|---|---|---|
| 1 | Completeness of chapters for the current stage | 1 | Preliminary pages **and Chapters 1–4** present at the expected stage | `report/` front matter + Ch.1–4 | M22 |
| 2 | Technical consistency between report and implementation | 1 | Methodology, design, implementation and results in the report match the **actual** work | `report/TRACEABILITY.md`; a code-vs-report diff | M22 |
| 3 | Quality of analysis, results and supporting evidence | 1 | Claims supported by real outputs, metrics, tables, graphs or observations | `state/METRICS_INDEX.md` → figures in Ch.4 | M22 |
| 4 | Citations, referencing and **similarity compliance** | 1 | Proper citations and references; meets the institute's similarity limit | `report/references.bib`, `review/similarity/` report | M22 |
| 5 | Individual contribution and incorporation of guide feedback | 1 | Contribution clearly stated; earlier corrections actually incorporated | contribution annexure (from git) + `state/REVIEW_FEEDBACK.md` | M22 |

**Preliminary pages** usually means: title page, bonafide/completion certificate, declaration, abstract,
acknowledgement, table of contents, list of figures, list of tables, list of abbreviations. The exact set and
order are set by the institute's template — the human must supply it; the agent must not guess a format.

**Criterion 4 is the one that fails late.** A similarity check needs the institute's tool (Turnitin, Urkund or
whatever SCOPE prescribes), which a student account usually cannot run on demand — it goes through the guide
or the department. Generate the submission-ready PDF early, get the check run, and keep the report. Self-
plagiarism from your own Review-1/2 documents and over-quoting the literature survey are the usual causes
of a high score; both are fixable by rewriting in your own words, not by shuffling sentences.

**Criterion 2 is where this project is unusually strong — and unusually exposed.** The implementation
deliberately departs from the Review-1 design (ADR-003 crypto profile, ADR-005 kernel fix, ADR-006 host-side
gather, ADR-009 remote GPU, ADR-010 no integrated GPU). If the report still describes the Review-1 design,
criterion 2 is lost even though the work is good. Every ADR must be reflected in the report text.

---

## Review 4 — 25 marks (final)

| # | Criterion | Marks | Assessment focus | Where it comes from | Module |
|---|---|---|---|---|---|
| 1 | Action taken on previous review comments | 2 | Evidence that Review-3 and draft-report observations were **addressed** | `state/REVIEW_FEEDBACK.md` — every item resolved, each with a commit/run reference | M21 |
| 2 | Completion of the approved project scope | 3 | Approved modules and deliverables **complete**, per the objectives | STATE.md: every required module DONE; scope table in M21 | all |
| 3 | Functionality and integration of modules | 3 | End-to-end functioning, proper integration, **stable operation** | M12/M13 round trip, soak test, integration suite | M21 |
| 4 | Technical accuracy and quality of implementation | 3 | Correctness of methods, algorithms, design choices, tools, practices | audits, ADRs, bit-exactness, obliviousness checks | M03–M08 |
| 5 | Testing and validation | 3 | Adequacy of test cases, experiments, validation procedures, supporting evidence | `ai/TESTING.md` layers, coverage summary, golden vectors, E0–E6 | M21 |
| 6 | Results analysis and **interpretation** | 2 | Meaningful presentation *and interpretation* of final results | Dashboard + `docs/RESULTS_ANALYSIS.md` (what each number means, not just the number) | M16, M20 |
| 7 | Technical refinement, limitations, future scope | 2 | Improvements/optimisation carried out; limitations and future work clearly identified | `docs/REFINEMENTS.md` (C1–C*, before/after numbers), limitations section | M20 |
| 8 | Completeness and technical quality of the final report | 2 | Near-final report, complete, technically consistent, accurately reflecting the work | the report, Chapters 1–6 | M20 |
| 9 | **Research publication or IP submission** | 2 | Valid **documentary proof** of submission to a peer-reviewed journal / international conference, or a patent filing. **No marks without proof.** | `review/publication/` — manuscript, submission confirmation, IDs | M19 |
| 10 | Demonstration, individual contribution, readiness | 3 | Demo quality, clear individual contribution, guide feedback incorporated, panel-ready | demo runbook, per-member contribution evidence from git | M21 |

### What changes between Review 3 and Review 4
- **Scope**: half → **complete**. Everything marked required in `state/STATE.md` must be DONE.
- **Integration**: individual modules → **one system that runs end to end without hand-holding**.
- **Results**: numbers → **numbers plus interpretation**. A table with no reading of it loses marks.
- **Report**: chapter drafts → **near-final, internally consistent** with the measured results.
- **New, and easy to lose**: criterion 9 needs *documentary proof*. Start it early (M19) — conference
  deadlines and journal acknowledgement emails do not arrive on demand.

### The sequence
`Review 3` (interim, 20) → `Draft / Report Review` (5) → `Review 4` (final, 25). The draft review is a
rehearsal for Review-4 criteria 6–8: anything the draft marker flags becomes a `state/REVIEW_FEEDBACK.md`
item, and fixing it is worth marks twice — once at the draft review, once at Review 4 criterion 1.

### Rule for the agent
Criterion 9 is the only one that depends on an external party and a calendar. From the moment M16 has
real results, treat M19 as the highest-priority non-blocked unit, ahead of polish work. Criterion 1 is the
cheapest to lose: if `state/REVIEW_FEEDBACK.md` is empty, ask the human to paste the panel's Review-3
comments before planning Review-4 work.
