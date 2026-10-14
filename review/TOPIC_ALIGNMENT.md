# Topic alignment: how V-cloak relates to ORAM

What V-cloak is called: **a GPU-resident oblivious permutation layer for message-order privacy** (ADR-029 item 1).
How it relates to ORAM (ADR-030, the team's final wording):

> This is a prototype. We implement the oblivious shuffle, the component ORAM constructions build on, and apply it
> to message ordering. Full access-pattern hiding is the remaining part of an ORAM and is out of scope for this
> prototype, because it does not fit a 200 ms real-time budget on this hardware.

Use that sentence as written wherever ORAM comes up: this page, related work, the presenter notes. Always name the
component (the oblivious shuffle). Never write "part of ORAM", "ORAM-based" or "an ORAM" on their own.

## 1. Which ORAM component, and what we do with it

Square-root and hierarchical ORAM constructions (Goldreich and Ostrovsky) keep their data in an order that the
server cannot link to the logical order. They rebuild that order with an **oblivious shuffle**: a permutation whose
memory accesses do not depend on the data or on the permutation chosen. Tree-based ORAMs such as Path ORAM do not
shuffle, so related work names the family whenever it cites.

V-cloak takes this one component and applies it to the order of stored messages:

| ORAM-style element | In V-cloak | Status | Evidence (METRIC-ID → run) |
|---|---|---|---|
| Oblivious shuffle | Bitonic sorting network over 128-bit ChaCha20 tags, run on the GPU per epoch and on each window re-shuffle | **built** | `K-BITONIC-FUSED-MS-2^16` (runs/20261011-213207_M07_kernel_sweep, Kaggle T4); `S-TRACE-DISTINCT-DEVICE` = 1 trace over 5 inputs vs `S-TRACE-DISTINCT-MERGESORT` = 4 (runs/20261013-055444_M14_security_e3) |
| Uniform permutation | Tags from a keyed PRF (`K_tag`, GPU memory only) | **built** | `S-CHI2-P` (runs/20261013-055417_M14_security_e2, n 64, 20000 epochs) |
| Hidden logical position | `seq_enc` = ChaCha20-Poly1305 over (conv_id, seq) under `K_seq`; only the reader restores order | **built** | `S-E0-RESTORE` = 60 of 60 conversations (runs/20261013-054727_M14_security_e0e1) |
| Fixed-size batches | Each epoch is padded with dummies to SLOTS | **built** | `E2E-OVERFLOW-U10`, `E2E-OVERFLOW-U50` = 0 (runs/20261014-081645_M15_e2e_metrics) |
| Effect on the order an attacker recovers | Order-recovery attack on a dump, by visible window | **measured** | `S-TURNACC-BASELINE` 1.0 → `S-TURNACC-W300` 0.507, chance 0.5 (runs/20261013-054727_M14_security_e0e1) |
| Hiding which records a read touches (full access-pattern hiding) | A read fetches the CAND_K candidate rows of one bucket-window, so the server sees which bucket-window was read | **out of scope** | none: not built, not measured |
| Position map, stash, eviction | none | **out of scope** | none |

## 2. Why the GPU (the topic's "GPU" part)

- The shuffle and the keys sit in GPU memory: `K_tag`, `K_seq` and `K_bkt` never leave it (ADR-003). That is what
  "GPU-resident" means here.
- Kernel times and the end-to-end cells come from the free cloud T4 (Kaggle or Colab, shared). The provenance line of
  every number names the runner.
- **How to read GPU utilisation.** At 10 and 50 users (two per conversation) the median NVML utilisation during the
  measured interval is `E2E-GPUUTIL-U10` and `E2E-GPUUTIL-U50`, both 0 to 1 %
  (runs/20261014-081645_M15_e2e_metrics). That number describes this load, not a capacity. The GPU works in a
  short burst once per 200 ms epoch, and NVML counts the share of its sample periods in which a kernel was running.
  The added acknowledgement latency (`E2E-ADDED-P50-U10`, `E2E-ADDED-P50-U50`, about 100 ms) comes from waiting for
  the epoch to close, not from GPU compute (docs/REPORT_CH4_NOTES.md section 4.E.3). Low utilisation is **not**
  evidence of headroom or of how the system scales. Scaling is untested (ADR-028).

## 3. What is not claimed

- No ORAM: no construction, leakage bound or overhead analysis for full access-pattern hiding.
- That full access-pattern hiding "does not fit a 200 ms budget" is a judgement about scope. It is not a
  measurement: no ORAM was built or timed in this repository.
- No "grouping" claim. The claim is order only, inside a window, until ISSUE-53 is answered (ADR-029 item 4).
- Known leakage that stays: window ids, the number of real messages per window, epoch-level order of the newest data
  until its window closes, partial conversation identity through shared buckets (ai/PROJECT_BRIEF.md section 5).
- P3 (data-oblivious execution) is claimed for the kernels only. Host timing is a limitation (ADR-023). Never
  "constant time".

## 4. Presenter notes

1. When the topic title or a panel member says ORAM, read the standard sentence above as written. Then point to row 1
   of the table (the oblivious shuffle, built) and row 6 (full access-pattern hiding, out of scope).
2. If asked "is this an ORAM?": "No. It is the oblivious shuffle that ORAM constructions build on, applied to message
   ordering; the access-pattern part is not built."
3. **Likely follow-up: "What would it take to complete the ORAM?"**
   Answer: "Reads would have to stop revealing which bucket-window they touch, for example by keeping a position map
   over the window layout so that every read fetches a fixed set of rows unrelated to the conversation and then
   re-shuffles what it read. That turns every read into a re-encrypt-and-re-permute write, over a set that grows with
   the store instead of staying at CAND_K rows. We have not designed or measured it, and our judgement is that it
   does not fit the 200 ms epoch on a T4."
4. If asked for the overhead of that direction: there is no number. Say so, and say that it is future work.
