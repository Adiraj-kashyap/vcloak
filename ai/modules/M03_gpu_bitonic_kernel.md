# M03 — GPU bitonic kernel (branch-free, pair-per-thread, shared-memory fused)
owner: Aditya · depends_on: M01 · est_sessions: 2 · human_gates: none

## Goal
The core CUDA kernels: sort SoA records `(hi, lo, slot, pay)` lexicographically by `(hi, lo, slot)`,
with no data-dependent branch or address, bit-exact with the oracle.

## Required reading
- `ai/GPU_GUIDE.md §2, §3, §8` · `ai/CONVENTIONS.md §2` · `ai/DECISIONS.md ADR-005`
- `src/vcloak/oracle/reference.py`: only `bitonic_pairs` and `bitonic_sort` (use grep for line ranges)

## Deliverables
`kernels/common.cuh` (mask helpers: `mask64(bool)`, `lex_gt3`, `xor_swap64/32`), `kernels/bitonic.cu`
(`bitonic_pairs_global`, `bitonic_shared`), `src/vcloak/gpu/kernels.py` (`gpu_bitonic_sort(d_hi, d_lo, d_slot, d_pay)`),
`scripts/check_oblivious.py` (G3), `tests/gpu/test_bitonic.py`.

## Steps
- **S1 Helpers.** `mask64(c) = (uint64)0 - (uint64)(c != 0)`; `lex_gt3(hi_a,lo_a,s_a, hi_b,lo_b,s_b)` returns a
  mask computed with `&`, `|` and `==` only (no `&&` or `||`); xor-swap helpers. Check: compiles via RawModule.
- **S2 Global pair kernel.** `bitonic_pairs_global(hi, lo, slot, pay, k, j, npairs)`: `t = blockIdx.x*blockDim.x + threadIdx.x;`
  launch exactly npairs = n/2 threads (n ≥ 2*blockDim, a power of two, so no bounds guard is needed; if a guard exists,
  it uses only t and npairs). Pair `i = (t / j) * 2 * j + (t % j)` (use shifts: j is a power of two), `l = i + j`,
  `asc = (i & k) == 0`; `sw = ~(mask64(asc) ^ lex_gt3(...))`; xor-swap all 4 columns. Check: the n = 2^10 result equals the oracle.
- **S3 Shared kernel.** `bitonic_shared(hi, lo, slot, pay, k, j_start, n)`: the block loads a tile of 2*T elements
  (T = 256 default; public) into shared memory, performs stages j = j_start, j_start/2, …, 1 for the given k with
  `__syncthreads()`, and writes back. Provide `bitonic_shared_full` that runs all k ≤ 2T for the tile (the initial
  local sort). Check: tile-local results equal the oracle.
- **S4 Driver.** `gpu_bitonic_sort`: run the local full sort for k ≤ 2T; then for each k > 2T, launch global
  kernels for j > T and one shared launch for j ≤ T. Everything depends only on n and T. Check: bit-exact vs the oracle for
  n ∈ {2^6 (T clamps to n/2), 2^10, 2^16, 2^max_log2n}, seeds {1, 2, 3}, and adversarial inputs.
- **S5 Obliviousness static check.** `check_oblivious.py`: parse kernels/*.cu; flag `if`/`?:`/`while`/`for`/`&&`/`||`
  whose condition mentions a data array (hi, lo, slot, pay, key, ks, tag, …) and array subscripts that are
  not built from {t, i, l, threadIdx, blockIdx, blockDim, k, j, n, T, loop counters}. Check: clean on bitonic.cu;
  flags a planted `if (hi[i] > hi[l])` in a temp copy.
- **S6 Quick timing smoke.** Using the `gpu-bench` skill, time n = 2^16 (quick mode) just to confirm the kernel runs at a
  sane speed. (Real measurements are M07.)

## Audit checklist
- A1 Bit-exact vs the oracle: all sizes × seeds × adversarial inputs (test report saved).
- A2 No element written by two threads per launch (by construction: code review note + a test that runs
  `compute-sanitizer --tool racecheck` if available, else NOT_MEASURED with the reason).
- A3 `check_oblivious.py` is clean; its planted-branch self-test fails as expected.
- A4 The launch configuration depends only on n and T (grep the driver code; note it in the audit).
- G1–G10.

## Pitfalls
- `(uint64)(a > b)` compiles to set-predicate/select, not a branch; keep all comparisons inside mask expressions.
- The last tile when n < 2T: clamp T = n/2.
- Don't swap `pay` separately: it must move with its key columns in the same mask operation.

## Presenter notes
1. Why was the paper's one-thread-per-element kernel racy, and how does pair indexing fix it? (ADR-005)
2. How many rounds and compare-exchanges at 2^16, and which of them run in shared memory?
3. How do you prove there are no data-dependent branches?

## Next: M04
