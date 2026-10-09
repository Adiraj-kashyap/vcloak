# PAPER RESULTS CONTRACT

The Overleaf paper (`main.tex`) reads its numbers from `results/`. M16 must regenerate **these exact file
names and macro names**, so the new files can replace the old ones in the Overleaf project without editing `main.tex`.

The values below are the **interim CPU-oracle values** already in the paper. They are shown only to identify
each macro's meaning and format. They are NOT results of this build and must never be copied into `results/`.

## Files
| File | Content |
|---|---|
| `macros.tex` | `\newcommand{\<name>}{<value>}` lines, listed below |
| `attack_table.tex` | `\newcommand{\attackrows}{% ... }`, rows: layout & τ global & τ in round & turn acc. & same-round % \\ |
| `trace_table.tex` | `\newcommand{\tracerows}{...}`, rows: input class & bitonic hash & merge-sort hash \\ |
| `throughput_table.tex` | `\newcommand{\throughputrows}{...}`, rows: $2^{k}$ & rounds & CPU ms & CPU keys/s (10^3) & CUDA ms \\ |
| `session_table.tex` | `\newcommand{\sessionrows}{...}`, rows: scenario & expected & observed (reason) \\ |
| `window_ablation.dat` | whitespace table, header `W tauglobal tauwithin turnacc samefrac` |
| `tau_hist.dat` | header `z count`; bin centres of τ/σ over [−4, 4], 24 bins |
| `throughput.dat` | header `log2n rounds ms kps` |

In `throughput_table.tex`, the CUDA column replaces `\pending` with the measured GPU median (ms), including transfers.

## New files M16 adds (the paper will need small edits to use them; list those edits in PAPER_UPDATES.md)
`gpu_kernels_table.tex` (\gpukernelrows), `dudect_table.tex` (\dudectrows), `e2e_table.tex` (\etoerows), `pipeline_breakdown.dat`.

## Macro names and their interim values (meaning reference only)
| Macro | Interim value |
|---|---|
| `\resMsgs` | 24191 |
| `\resConvs` | 200 |
| `\resDuration` | 900 |
| `\resMeanPerEpoch` | 5.38 |
| `\resTauConvGlobal` | 1.000 |
| `\resTauConvWithin` | 1.000 |
| `\resTauEpochGlobal` | 1.000 |
| `\resTauEpochWithin` | 0.004 |
| `\resRestoreOK` | 60 |
| `\resRestoreN` | 60 |
| `\resChiSq` | 4060.6 |
| `\resChiDof` | 3969 |
| `\resChiP` | 0.152 |
| `\resTVD` | 0.0224 |
| `\resChiIdeal` | 4084.6 |
| `\resChiPIdeal` | 0.098 |
| `\resTVDIdeal` | 0.0228 |
| `\resUnifEpochs` | 20000 |
| `\resTauN` | 65536 |
| `\resTauEpochs` | 1000 |
| `\resTauSigma` | 0.00260 |
| `\resTauBand` | 0.0078 |
| `\resTauMean` | -5.90e-06 |
| `\resTauStd` | 0.00261 |
| `\resTauMaxAbs` | 0.0084 |
| `\resTauInBand` | 99.6 |
| `\resAESus` | 2.4 |
| `\resCandK` | 128 |
| `\resMaxOcc` | 101 |
| `\resMeanOcc` | 25.4 |
| `\resBuckets` | 64 |
| `\resBitonicTraces` | 1 |
| `\resMergeTraces` | 4 |
| `\resTurnConv` | 100.0 |
| `\resSameConv` | 15.7 |
| `\resTauGConv` | 1.000 |
| `\resTurnEpoch` | 98.3 |
| `\resSameEpoch` | 3.7 |
| `\resTauGEpoch` | 1.000 |
| `\resTurnWTen` | 68.5 |
| `\resSameWTen` | 63.0 |
| `\resTauGWTen` | 0.989 |
| `\resTurnWSixty` | 56.0 |
| `\resSameWSixty` | 88.8 |
| `\resTauGWSixty` | 0.934 |
| `\resTurnWThreeHundred` | 50.7 |
| `\resSameWThreeHundred` | 98.3 |
| `\resTauGWThreeHundred` | 0.668 |
