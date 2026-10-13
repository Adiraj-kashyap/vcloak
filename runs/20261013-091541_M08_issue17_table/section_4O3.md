## 4.O.3 dudect findings
3 of the 6 target series FAIL at N = 100000<!--M:T-DUDECT-N-AEAD-CONV--> per class:
- `write_epoch` (whole call): max |t| 8.2776<!--M:T-DUDECT-MAXT-WRITE-EPOCH-CALL-->, largest at crop 64 (below 5.76966254); SM clock 585-585 MHz (LOW); class means, percentiles and the t of every crop are in `results/oblivious/dudect_write_epoch.json`.
- `aead_tag`: max |t| 6.2415<!--M:T-DUDECT-MAXT-AEAD-TAG-->, largest at crop 8 (below 0.164980775); SM clock 585-585 MHz (LOW); class means, percentiles and the t of every crop are in `results/oblivious/dudect_aead_tag.json`.
- `aead_conv`: max |t| 11.6369<!--M:T-DUDECT-MAXT-AEAD-CONV-->, largest at crop 55 (below 0.192015714); SM clock 585-585 MHz (LOW); class means, percentiles and the t of every crop are in `results/oblivious/dudect_aead_conv.json`.

What these results do and do not show:
- The harness has power: the planted leak is detected in quick mode (max |t| 376.9125<!--M:T-DUDECT-MAXT-CONTROL-LEAK-->),
  and the null control stays below the threshold at full N (max |t| 2.0786<!--M:T-DUDECT-MAXT-CONTROL-NULL-->).
- The fused bitonic sort shows no dependence on the tag order at this N, and neither do the device stages of
  write_epoch.
- The FAILs are recorded as findings and are **not explained** by this job. The static evidence (no data-dependent
  branch in `aead_open_seq`, section 4.O.4) does not remove them: a timing difference between the classes was measured.
  This job does not say whether it comes from the device, from host work inside the timed window, or
  from the way the two classes are staged by the harness; the diagnostic job at the end of this
  section (ISSUE-17) measured that, and the FAILs above stay in every table as measured.
- The whole-call series of write_epoch includes the engine's host stage, which is Python code working on the
  submissions; it is not covered by the kernel rules of `ai/CONVENTIONS.md §2`.
- All three failing series, and the device series of write_epoch, were measured with the SM clock at a low
  frequency (column `clock` of `results/oblivious/summary_table.csv`).

### Diagnostics of the failing series (ISSUE-17)
Job `20261012-113437_M08_issue17`, runner session 20261012-061138 (Tesla T4, driver 580.178.04),
run dirs `runs/20261012-061420_M08_dudect_issue17_s8`, `runs/20261012-080629_M08_dudect_issue17_s9`. This is another runner session than the summary
above; values are not pooled. Rows of job `S2` repeat the summary; the rows of the diagnostic job measure the same
targets again and, beside them, the same targets with only the staging or only the contents changed
(`results/oblivious/staging_diagnostics.csv`).

| job | seed | target | what the two classes are | N / class | max \|t\| | verdict | sign of raw t | SM clock MHz | r |
|---|---|---|---|---|---|---|---|---|---|
| diagnostic | 8 | `control_null` | null control: fused bitonic sort, the same fixed input in both classes | 100000 | 1.6126<!--M:T-DUDECT-MAXT-CONTROL-NULL--> | PASS | - | 1095-1080 (LOW) | 1 |
| diagnostic | 9 | `control_null` | null control: fused bitonic sort, the same fixed input in both classes | 100000 | 1.253<!--M:T-DUDECT-MAXT-CONTROL-NULL--> | PASS | - | 960-990 (LOW) | 1 |
| S2 | 8 | `write_epoch` (whole call) | (c) write_epoch: fixed contents vs random contents, n_real fixed | 100000 | 8.2776<!--M:T-DUDECT-MAXT-WRITE-EPOCH-CALL--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `write_epoch` (whole call) | (c) write_epoch: fixed contents vs random contents, n_real fixed | 100000 | 29.6309<!--M:T-DUDECT-MAXT-WRITE-EPOCH-CALL--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 9 | `write_epoch` (whole call) | (c) write_epoch: fixed contents vs random contents, n_real fixed | 100000 | 8.5822<!--M:T-DUDECT-MAXT-WRITE-EPOCH-CALL--> | **FAIL** | + | 585-585 (LOW) | 1 |
| diagnostic | 8 | `write_epoch_null` (whole call) | ISSUE-17 (c) staging only: the same contents in both classes, new objects, built first vs built second | 100000 | 12.7431<!--M:T-DUDECT-MAXT-WRITE-EPOCH-NULL-CALL--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `write_epoch_age` (whole call) | ISSUE-17 (c) staging only: the same contents in both classes, long-lived objects vs new objects | 100000 | 12.1795<!--M:T-DUDECT-MAXT-WRITE-EPOCH-AGE-CALL--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `write_epoch_fresh` (whole call) | ISSUE-17 (c) symmetric staging: fixed contents vs random contents, new objects, one batch built | 100000 | 1.7015<!--M:T-DUDECT-MAXT-WRITE-EPOCH-FRESH-CALL--> | PASS | - | 585-585 (LOW) | 1 |
| diagnostic | 9 | `write_epoch_fresh` (whole call) | ISSUE-17 (c) symmetric staging: fixed contents vs random contents, new objects, one batch built | 100000 | 1.3865<!--M:T-DUDECT-MAXT-WRITE-EPOCH-FRESH-CALL--> | PASS | + | 585-585 (LOW) | 1 |
| S2 | 8 | `write_epoch` (device stages) | (c) write_epoch: fixed contents vs random contents, n_real fixed | 100000 | 2.7559<!--M:T-DUDECT-MAXT-WRITE-EPOCH--> | PASS | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `write_epoch` (device stages) | (c) write_epoch: fixed contents vs random contents, n_real fixed | 100000 | 1.7742<!--M:T-DUDECT-MAXT-WRITE-EPOCH--> | PASS | - | 585-585 (LOW) | 1 |
| diagnostic | 9 | `write_epoch` (device stages) | (c) write_epoch: fixed contents vs random contents, n_real fixed | 100000 | 1.9675<!--M:T-DUDECT-MAXT-WRITE-EPOCH--> | PASS | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `write_epoch_null` (device stages) | ISSUE-17 (c) staging only: the same contents in both classes, new objects, built first vs built second | 100000 | 2.7782<!--M:T-DUDECT-MAXT-WRITE-EPOCH-NULL--> | PASS | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `write_epoch_age` (device stages) | ISSUE-17 (c) staging only: the same contents in both classes, long-lived objects vs new objects | 100000 | 6.3027<!--M:T-DUDECT-MAXT-WRITE-EPOCH-AGE--> | **FAIL** | + | 585-585 (LOW) | 1 |
| diagnostic | 8 | `write_epoch_fresh` (device stages) | ISSUE-17 (c) symmetric staging: fixed contents vs random contents, new objects, one batch built | 100000 | 6.1653<!--M:T-DUDECT-MAXT-WRITE-EPOCH-FRESH--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 9 | `write_epoch_fresh` (device stages) | ISSUE-17 (c) symmetric staging: fixed contents vs random contents, new objects, one batch built | 100000 | 3.094<!--M:T-DUDECT-MAXT-WRITE-EPOCH-FRESH--> | PASS | - | 585-585 (LOW) | 1 |
| S2 | 8 | `aead_tag` | (d) AEAD open: all tags valid vs all tags invalid | 100000 | 6.2415<!--M:T-DUDECT-MAXT-AEAD-TAG--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `aead_tag` | (d) AEAD open: all tags valid vs all tags invalid | 100000 | 51.494<!--M:T-DUDECT-MAXT-AEAD-TAG--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 9 | `aead_tag` | (d) AEAD open: all tags valid vs all tags invalid | 100000 | 35.6716<!--M:T-DUDECT-MAXT-AEAD-TAG--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `aead_tag_null` | ISSUE-17 (d) staging only: all tags valid in both classes, read-only array vs freshly written array | 100000 | 63.0436<!--M:T-DUDECT-MAXT-AEAD-TAG-NULL--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 9 | `aead_tag_null` | ISSUE-17 (d) staging only: all tags valid in both classes, read-only array vs freshly written array | 100000 | 50.8492<!--M:T-DUDECT-MAXT-AEAD-TAG-NULL--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `aead_tag_swap` | ISSUE-17 (d) roles swapped: all tags invalid (fixed array) vs all tags valid (freshly written array) | 100000 | 59.6183<!--M:T-DUDECT-MAXT-AEAD-TAG-SWAP--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 9 | `aead_tag_swap` | ISSUE-17 (d) roles swapped: all tags invalid (fixed array) vs all tags valid (freshly written array) | 100000 | 42.6905<!--M:T-DUDECT-MAXT-AEAD-TAG-SWAP--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `aead_tag_sym` | ISSUE-17 (d) symmetric staging: all tags valid vs all tags invalid, device pools | 100000 | 1.5629<!--M:T-DUDECT-MAXT-AEAD-TAG-SYM--> | PASS | - | 1515-1530 (OK) | 1 |
| diagnostic | 9 | `aead_tag_sym` | ISSUE-17 (d) symmetric staging: all tags valid vs all tags invalid, device pools | 100000 | 3.8937<!--M:T-DUDECT-MAXT-AEAD-TAG-SYM--> | PASS | + | 1530-1560 (OK) | 1 |
| diagnostic | 8 | `aead_tag_kernel` | ISSUE-17 (d) kernel-only window: all tags valid vs all invalid, device pools, preallocated outputs | 100000 | 1.5075<!--M:T-DUDECT-MAXT-AEAD-TAG-KERNEL--> | PASS | + | 1170-1155 (LOW) | 8 |
| diagnostic | 9 | `aead_tag_kernel` | ISSUE-17 (d) kernel-only window: all tags valid vs all invalid, device pools, preallocated outputs | 100000 | 2.3929<!--M:T-DUDECT-MAXT-AEAD-TAG-KERNEL--> | PASS | - | 1170-1215 (LOW) | 8 |
| S2 | 8 | `aead_conv` | (e) AEAD open: every row matches q vs no row matches q | 100000 | 11.6369<!--M:T-DUDECT-MAXT-AEAD-CONV--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `aead_conv` | (e) AEAD open: every row matches q vs no row matches q | 100000 | 30.8131<!--M:T-DUDECT-MAXT-AEAD-CONV--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 9 | `aead_conv` | (e) AEAD open: every row matches q vs no row matches q | 100000 | 28.2772<!--M:T-DUDECT-MAXT-AEAD-CONV--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `aead_conv_null` | ISSUE-17 (e) staging only: every row matches q in both classes, fixed array vs pool | 100000 | 43.1742<!--M:T-DUDECT-MAXT-AEAD-CONV-NULL--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 9 | `aead_conv_null` | ISSUE-17 (e) staging only: every row matches q in both classes, fixed array vs pool | 100000 | 30.1696<!--M:T-DUDECT-MAXT-AEAD-CONV-NULL--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `aead_conv_swap` | ISSUE-17 (e) roles swapped: no row matches q (fixed array) vs every row matches q (pool) | 100000 | 34.4452<!--M:T-DUDECT-MAXT-AEAD-CONV-SWAP--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 9 | `aead_conv_swap` | ISSUE-17 (e) roles swapped: no row matches q (fixed array) vs every row matches q (pool) | 100000 | 28.6825<!--M:T-DUDECT-MAXT-AEAD-CONV-SWAP--> | **FAIL** | - | 585-585 (LOW) | 1 |
| diagnostic | 8 | `aead_conv_sym` | ISSUE-17 (e) symmetric staging: every row matches q vs no row matches q, device pools | 100000 | 2.4044<!--M:T-DUDECT-MAXT-AEAD-CONV-SYM--> | PASS | - | 1545-1530 (OK) | 1 |
| diagnostic | 9 | `aead_conv_sym` | ISSUE-17 (e) symmetric staging: every row matches q vs no row matches q, device pools | 100000 | 1.348<!--M:T-DUDECT-MAXT-AEAD-CONV-SYM--> | PASS | + | 1425-1545 (OK) | 1 |
| diagnostic | 8 | `aead_conv_kernel` | ISSUE-17 (e) kernel-only window: every row matches q vs none, device pools, preallocated outputs | 100000 | 2.9037<!--M:T-DUDECT-MAXT-AEAD-CONV-KERNEL--> | PASS | + | 1245-1140 (LOW) | 8 |
| diagnostic | 9 | `aead_conv_kernel` | ISSUE-17 (e) kernel-only window: every row matches q vs none, device pools, preallocated outputs | 100000 | 1.8673<!--M:T-DUDECT-MAXT-AEAD-CONV-KERNEL--> | PASS | - | 1185-1170 (LOW) | 8 |

Read by the rules written in ISSUE-17 before the job ran (a reading, not a proof); 0 output mismatches:
- `write_epoch` (whole call): the FAIL of S2 is reproduced in 2 of 2 seeds; the controls with the same contents in both classes FAIL in 2 of 2 series (measured at seed 8); the comparison of the contents without that staging PASSES in 2 of 2 series. Reading: the difference follows the staging, not the contents; no dependence on the contents was detected at this N, on this device. SM clock 585 to 585 MHz with the S2 staging and 585 to 585 MHz without it.
- `aead_tag`: the FAIL of S2 is reproduced in 2 of 2 seeds; the controls with the same contents in both classes FAIL in 2 of 2 series (measured at seed 8, 9); with the contents exchanged between the two staging roles the raw t keeps its sign in 2 of 2 seeds; the comparison of the contents without that staging PASSES in 4 of 4 series. Reading: the difference follows the staging, not the contents; no dependence on the contents was detected at this N, on this device. SM clock 585 to 585 MHz with the S2 staging and 1155 to 1560 MHz without it: the staging and the clock change together, and this job does not separate the two.
- `aead_conv`: the FAIL of S2 is reproduced in 2 of 2 seeds; the controls with the same contents in both classes FAIL in 2 of 2 series (measured at seed 8, 9); with the contents exchanged between the two staging roles the raw t keeps its sign in 2 of 2 seeds; the comparison of the contents without that staging PASSES in 4 of 4 series. Reading: the difference follows the staging, not the contents; no dependence on the contents was detected at this N, on this device. SM clock 585 to 585 MHz with the S2 staging and 1140 to 1545 MHz without it: the staging and the clock change together, and this job does not separate the two.
- Diagnostic series that FAIL although their S2 series PASSES: `write_epoch_age` (device stages) at seed 8, `write_epoch_fresh` (device stages) at seed 8. They are findings of their own; section 4.O.7 follows the device stages (ISSUE-25).
- Limits: one GPU model, one runner session for the diagnostics, 2 seeds. dudect can show a dependence,
  not its absence: a PASS without the S2 staging says that none was detected with this many measurements.
  The FAILs of the S2 staging stay in `results/oblivious/summary_table.csv` and in the summary above.

