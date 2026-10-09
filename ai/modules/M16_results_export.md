# M16 — Results export: paper macros, figures, deck numbers
owner: Abhishek · depends_on: M07, M08, M14 (M15 if done) · est_sessions: 1 · human_gates: none

## Goal
Turn the indexed metrics into paper-ready artifacts, with no manual number copying.

## Required reading
- `seed/PAPER_RESULTS_CONTRACT.md` · `ai/LOGGING_AND_AUDIT.md §5` · `ai/CONVENTIONS.md §7`

## Deliverables
`scripts/export_results.py`, `results/paper/macros.tex`, `results/paper/attack_table.tex`, `trace_table.tex`,
`throughput_table.tex`, `session_table.tex`, `window_ablation.dat`, `tau_hist.dat`, `throughput.dat`,
new GPU tables (`gpu_kernels_table.tex`, `dudect_table.tex`, `e2e_table.tex`), `results/figures/*.pdf|png`,
`results/deck_numbers.md`, `results/PAPER_UPDATES.md`.

## Steps
- **S1 Exporter.** Reads METRICS_INDEX + run summaries (never raw guesses) and writes every macro/table named in the
  contract, in the same format as the existing Overleaf project (so the files can be dropped into `results/` there).
- **S2 New GPU tables.** Kernel sweep (GPU vs CPU, including the crossover), pipeline stage breakdown, dudect/ncu/SASS summary,
  E2E latency. Replace every `\pending` in the paper with a real macro, or explicitly keep it `\pending` with the reason.
- **S3 PAPER_UPDATES.md.** A list of the paper passages that must change: the crypto profile (ADR-003: Sec. IV, Table 3,
  Algorithm 1), the Listing 1 race fix (ADR-005), payload gather (ADR-006), K_master at boot (ADR-007), and any number
  whose sign or conclusion changed vs the interim oracle results.
- **S4 Deck numbers.** `deck_numbers.md`: one line per slide number that must be updated in the Review-3 deck.

## Audit checklist
- A1 Every macro value is traceable to a METRIC-ID (the exporter writes a mapping file) and `check_metrics.py` passes.
- A2 No quick-tagged metric is used in the paper outputs. A3 The files compile inside the Overleaf project (test: copy into
  `paper/` if the human has placed the project there; otherwise run a LaTeX syntax check on the snippets). G1–G10.

## Next: M17
