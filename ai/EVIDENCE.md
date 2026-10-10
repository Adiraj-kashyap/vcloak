# EVIDENCE — capture it while the work happens, not at the end

The report and the research paper are written **last**, but the material they need is only available
**while each module runs**. A screenshot of a dashboard that has since been regenerated, or a terminal
output from a run that has since been overwritten, cannot be recreated later without redoing the work.
So every session captures its evidence as it goes, into `evidence/`, indexed, with provenance.

This is cheap when done per session and expensive when deferred. Treat it as part of the work, not admin.

## 1. Layout
```
evidence/
├── INDEX.md                  # one row per artefact: id · what it shows · module · date · source run · where it is used
├── screens/                  # PNGs of the app, auto-captured (M13/M18 onward)
│   └── <Mxx>_<view>_<light|dark>_<YYYYMMDD>.png
├── figures/                  # charts exported from results/ as PDF+PNG (paper-ready, 300 dpi)
├── terminal/                 # command + output captures worth showing (test runs, audits, attacks)
│   └── <Mxx>_<what>_<YYYYMMDD>.txt
├── gpu/                      # proof the GPU work really ran: nvidia-smi, device probe, ncu/SASS extracts
└── demo/                     # short screen recordings or frame sequences of the live demo
```
Nothing here is hand-made. Everything is produced by a script or copied from a `runs/` directory, and
every entry in `INDEX.md` names the run it came from.

## 2. What to capture, and when
| Capture | When | Serves |
|---|---|---|
| `nvidia-smi` + device properties from the ingested probe | M00 ingest | proof the GPU is real; paper's setup section |
| Kernel sweep plot (PDF+PNG) + the numbers table | M07 ingest | results chapter; paper Fig. "GPU vs CPU" |
| dudect t-curve, Nsight branch metrics, SASS extract | M08 ingest | obliviousness claims |
| Attack table + window-ablation figure | M14 | the headline security result |
| Chat view, both modes, with the server-view panel | M13 | "what the server stores" — the most convincing demo image |
| Dashboard, light **and** dark, full page | M18 | implementation + results evidence |
| Experiments view mid-run | M18 | shows the attack running, not just its number |
| Logs view | M18 | audit trail, individual contribution |
| Architecture / data-state flow | M18 | design chapter figure |
| `pytest` summary output | every module | testing and validation criterion |
| Audit table output | every module | technical accuracy criterion |
| End-to-end run + soak summary | M21 | integration criterion |

## 3. Rules
1. **Capture at the moment of truth.** The screenshot of a result is taken in the session that produced
   the result, from the data that produced it — never re-staged later from different numbers.
2. **Provenance travels with the image.** Every `INDEX.md` row carries the run dir and the git sha. A figure
   whose underlying metric later changes is **re-captured**, and the old one is moved to
   `evidence/superseded/` rather than deleted, so a reviewer can see what changed.
3. **No cosmetic editing.** No cropping that hides a `NOT MEASURED` card, no recolouring, no pasting a
   number onto an image. If a screenshot is unflattering because the work is incomplete, that is the
   correct screenshot for today.
4. **Paper-ready from the start.** Figures export at 300 dpi, PDF (vector where possible) plus PNG, with
   readable fonts at single-column width. Saves a re-export at paper time.
5. **Light mode for print.** Capture both themes for the dashboard; the report and paper use the light one.
6. **Seed vs measured.** A screenshot taken while the app is showing `SEED DATA` is labelled as such in
   `INDEX.md`. It can illustrate the interface; it can never illustrate a result.

## 4. How
`scripts/capture_evidence.py` (built in M13; extended in M18) drives a headless browser over the local app
and writes the `screens/` set plus `INDEX.md` rows. It runs:
- automatically at the end of any session that changed `web/**`, `results/**` or `state/METRICS_INDEX.md`;
- on demand through the `capture-evidence` skill.

Terminal and GPU evidence is copied from the relevant `runs/` directory by the same script — never retyped.

## 5. At paper and report time
`M22` (draft report) and `M19` (paper) **do not generate new evidence**; they select from `evidence/INDEX.md`.
If something needed is missing, that is a signal to re-run the module that produces it, not to approximate it.
