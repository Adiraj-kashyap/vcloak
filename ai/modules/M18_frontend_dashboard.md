# M18 — Frontend part 2: evidence dashboard, experiments and live logs
owner: Abhishek (dashboard) · Divyansh (logs API) · depends_on: M13, M14 (M07/M08 for GPU tiles) · est_sessions: 2 · human_gates: none

## Goal
Make every measured result visible in the app: headline tiles, charts, the attack demo, and the project's
own logs — all generated from evidence, never typed in (ADR-013).

## Required reading
- `ai/FRONTEND.md §4–§6` · `ai/ARCHITECTURE.md §4b` · `ai/LOGGING_AND_AUDIT.md §5` · `state/METRICS_INDEX.md` (skim the IDs)
- `web/js/dashboard.js`, `web/js/charts.js`, `web/data/demo/dashboard.json` (the prototype's shape — keep it)

## Deliverables
`scripts/export_dashboard.py`, `web/data/dashboard.json` (generated, committed), `/v1/dashboard`,
`/v1/logs`, `/v1/eval/attack` (dev), the Dashboard / Experiments / Logs / Architecture views wired to real
data, `tests/unit/test_export_dashboard.py`, `tests/integration/test_logs_api.py`, `docs/DEMO.md` (dashboard section).

## Steps
- **S1 Exporter.** `export_dashboard.py` parses `state/METRICS_INDEX.md` + `runs/**/summary.json` and emits
  `web/data/dashboard.json` to the ARCHITECTURE §4b schema: tiles, charts, provenance, and a `missing` list.
  Rules: no literal values in the script; a metric absent from the index lands in `missing` with the command
  that would produce it; quick-mode metrics are marked and excluded from headline tiles.
  Check: deleting a metric row moves that tile to `missing` on regeneration (test).
- **S2 Tiles.** Headlines: turn-order accuracy (conventional / Review-1 / W=300 s), restoration x/y, χ² p-value,
  dudect max |t|, bitonic ms at 2^16 (GPU), crossover n*, E5 scenarios passed. Each shows its METRIC-ID,
  run dir and `backend`/`runner` on hover or in a provenance line.
- **S3 Charts** (specs in FRONTEND §5): (a) window-ablation bars, measured vs predicted 1−f/2;
  (b) kernel sweep, GPU vs CPU, log–log, with the crossover marked; (c) τ/σ histogram with the ±3σ band;
  (d) pipeline stage breakdown vs the epoch budget; (e) session matrix as a pass/fail grid;
  (f) end-to-end latency CDF, V-cloak vs baseline (when M15 exists).
  Each has a hover tooltip, a reference line, a legend, and a Table toggle. Check: a visual pass in both themes.
- **S4 Experiments view.** A button runs the order-recovery attack on the current database through
  `/v1/eval/attack` (dev) and animates the result: the dump, the attacker's guessed order, and the accuracy
  against chance. Pre-computed results render when the endpoint is unavailable. Check: live run matches the stored number.
- **S5 Logs view.** `/v1/logs?kind=session|audit|metrics|issues&tail=N` serves the `state/*.md` files through the
  log allow-list (never raw file reads; no conv ids, buckets or tokens), rendered with filtering and a tail-follow toggle.
  Check: a redaction test drives traffic and greps the served output for forbidden fields.
- **S6 Architecture view.** The S0→S10 / R1→R5 flow as SVG, with a message animating through it and the
  durable states highlighted; the leakage table is shown beside it, stated honestly.
- **S6b Paper-ready figure export.** Extend `scripts/capture_evidence.py` to export each dashboard chart
  as standalone PDF + PNG at 300 dpi, single-column width, light theme, with readable fonts — into
  `evidence/figures/`, one sidecar JSON each naming the metric ids and run dirs. These are the figures the
  report and paper use directly, so they must not need re-making later.
  Check: every non-pending chart has a PDF and a PNG, and each opens at a legible size.
- **S7 Regeneration hook.** `tasks.py dashboard` regenerates the JSON; the M17 repro script asserts the committed
  JSON matches a fresh regeneration (no stale dashboards).

## Metrics to record
None new. This module *publishes* metrics; it must not create any.

## Audit checklist
- A1 `grep` finds no numeric literal in `web/js/**` that corresponds to a result (all values come from JSON).
- A2 Every tile/chart carries a METRIC-ID that exists in METRICS_INDEX; `check_metrics.py` passes.
- A3 Missing metrics render as `NOT MEASURED`, and quick metrics carry the QUICK chip (test with a doctored index).
- A4 The logs endpoint is redaction-tested; raw file paths are not served.
- A5 Both themes pass a visual check; charts have Table views; no chart has two y-axes.
- G1–G10.

## Presenter notes
1. Open the dashboard and explain where each number came from, down to the run directory.
2. Run the attack live and read the result off the screen.
3. Show the `NOT MEASURED` cards and say what is still pending — this is a strength, not a gap.

## Next: M17
