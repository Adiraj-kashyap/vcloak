# CONVENTIONS

## 1. Python
- Python ≥ 3.10; package in `src/vcloak`; type hints on all public functions; `ruff` for linting.
- No global mutable state except `config.py` constants. Randomness comes from explicit seeds in
  tests/benchmarks, and from `secrets`/`os.urandom` in production paths.
- Hot paths never import `vcloak.oracle` (it is a reference used by tests and evaluation only).
- Every CLI entry point takes `--seed`, `--quick` and `--out <run_dir>`.

## 2. Obliviousness rules (server-side kernels) — audited by G3
1. **No secret-dependent branches.** `if`, `?:`, `&&`/`||` short-circuit, `switch` and loop bounds may
   use only thread/block ids and kernel parameters that are public (n, k, j, S, K, B).
2. **No secret-dependent addressing.** Array indices are computed from ids and public parameters only.
   Payload gather by permutation happens on the host after D2H (ADR-006).
3. **Swap by mask.** Compute `m = 0 - (cond)` as a 64-bit mask, then `t = (a ^ b) & m; a ^= t; b ^= t;`.
4. **One thread per compare-exchange pair.** Never let two threads write the same element
   in the same launch (ADR-005: the paper's Listing 1 has this race).
5. **Constant-time comparisons** of authentication tags: OR-accumulate XOR differences, no early exit.
6. **No fast-math**; compile with `-std=c++17` and no `--use_fast_math`.
7. Host code may branch on public values only (n_real is public at the DB level; content is not).

## 3. Crypto rules
- Use the constructions in `ai/ARCHITECTURE.md §5` exactly; any change needs an ADR.
- CPU reference implementations (in `vcloak.crypto.*_ref`) use `cryptography` primitives where they
  exist, and are the ground truth for GPU bit-exact tests.
- Test keys are fixed constants defined inside `tests/` (e.g. `bytes(range(32))`) and never reused
  outside tests.
- Nonces: `seq_enc` uses a random 96-bit nonce per row (`os.urandom(12)` on the host is acceptable:
  it is public data). Tag nonces are derived from the epoch/window number and must never repeat
  under one K_tag.

## 4. Logging in application code
- Use `vcloak.service.logsafe.get_logger()`, which applies an allow-list of fields.
- Forbidden in any log line: conv_id, bucket, seq, row_id, fine timestamps below 1 s,
  key material, tokens, DPoP proofs, payload bytes. A unit test enforces this (M11).

## 5. Git
- Commit message: `<Mxx>: <summary> [S<a>-S<b>] [owner:<name>]`; WIP commits `wip(<Mxx>): S<n> …`;
  chores `chore: …`. One module per tag: `<Mxx>-done`.
- Commit `runs/**/manifest.json` and `runs/**/summary.json`; ignore raw large files (`*.npy`, `raw.csv` > 5 MB).

## 6. .gitignore (create in the first session)
```
.venv/
__pycache__/
*.pyc
.env
secrets/
runs/**/raw*.csv
runs/**/*.npy
runs/**/*.ncu-rep
*.cubin
.pytest_cache/
node_modules/
```

## 7. Documentation
- `docs/API.md` (M10/M11), `docs/DEMO.md` (M17), `docs/REPORT_CH4_NOTES.md` (updated by M07, M08, M14, M15, M16).
- Every figure in `results/` has a sidecar `.json` naming the run dirs it was drawn from.
