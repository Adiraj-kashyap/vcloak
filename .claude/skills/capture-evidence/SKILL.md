---
name: capture-evidence
description: Capture screenshots, figures and terminal proofs of the current state into evidence/, with provenance. Use at the end of any session that changed the app, the results or the metrics index, and whenever the user asks for screenshots, proofs or paper figures.
---
Follow `ai/EVIDENCE.md`. The point is to capture the moment that produced the result, because it cannot
be recreated later.

1. Decide what this session produced that is worth showing: new metrics, a changed view, a new run.
   If nothing changed in `web/**`, `results/**` or `state/METRICS_INDEX.md`, say so and stop.
2. Run `python scripts/capture_evidence.py --module <Mxx>` (built in M13, extended in M18). It serves the
   app locally, drives a headless browser, writes PNGs to `evidence/screens/`, exports any new figures to
   `evidence/figures/` as PDF + PNG at 300 dpi, copies relevant `runs/**` output into `evidence/terminal/`
   and `evidence/gpu/`, and appends rows to `evidence/INDEX.md`.
   If the script does not exist yet (before M13), capture terminal and GPU evidence only: copy the
   relevant run output into `evidence/terminal/` or `evidence/gpu/` and append the index rows by hand,
   each naming its run dir.
3. Check the captures: open at least one PNG and confirm it shows what the row claims. A screenshot of a
   stale dashboard is worse than none.
4. Label the data state honestly in each row: `measured` (real run), `seed` (demo data from the oracle),
   `quick` (quick-mode numbers). A `seed` capture may illustrate the interface, never a result.
5. If a capture supersedes an earlier one because the numbers changed, move the old file to
   `evidence/superseded/` and note it in the row. Never delete evidence.

Never crop out a `NOT MEASURED` card, recolour a chart, or paste a value onto an image. If the picture
looks incomplete because the work is incomplete, that is the correct picture for today.
