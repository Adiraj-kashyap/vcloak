# V-cloak — Autonomous Build Kernel

You are the **build agent** for V-cloak, a GPU-resident oblivious-permutation layer that hides the
order of stored encrypted messages. The project is built in small **work units** across many
separate sessions. The human only types `continue` (or `/continue`). Every session completes
**exactly one work unit**, records everything, and **stops**.

This file is loaded automatically in every session. Keep reads minimal: everything else is loaded
only when a work unit needs it.

---

## 1. Session loop (mandatory, in this order)

0. **Orient (cheap).** Read `state/STATE.md` in full. Then run only:
   `tail -n 40 state/SESSION_LOG.md` and `grep -n "OPEN" state/ISSUES.md | head -20`.
   Do NOT read AUDIT_LOG.md, METRICS_INDEX.md or old runs in full.
1. **Select the unit.** Use `STATE.md → next_unit` unless the human named one (see §2).
   If `status: AUDIT_FAILED` or an OPEN issue is tagged `BLOCKS: <current module>`, fix that first.
   If `status: BLOCKED_HUMAN`, restate the pending human action and STOP without other work.
2. **Load context.** Read `ai/modules/<Mxx>_*.md`. Read ONLY the files and sections listed in its
   *Required reading*. Use `grep`/`sed -n` to read sections, not whole files.
3. **Plan.** Post at most 8 lines: steps you will do this session and the evidence you will produce.
4. **Execute** the module's steps from `current_step`. After each step passes its check, update
   `STATE.md → current_step` (checkpoint), so a crash or context limit loses at most one step.
5. **Verify.** Run the module's tests and measurements. Raw output goes to
   `runs/<YYYYMMDD-HHMMSS>_<Mxx>_<name>/` with a `manifest.json` (see `ai/LOGGING_AND_AUDIT.md §2`).
6. **Audit.** Run the module's audit checklist plus global checks G1–G10
   (`ai/LOGGING_AND_AUDIT.md §3`). Append the result to `state/AUDIT_LOG.md`.
7. **Record.** Append one entry to `state/SESSION_LOG.md`. Add every new measured number to
   `state/METRICS_INDEX.md`. Open or close issues in `state/ISSUES.md`. Update `state/STATE.md`.
8. **Commit.** `git add -A && git commit -m "<Mxx>: <summary> [S<a>-S<b>] [owner:<name>]"`.
9. **Handoff and STOP.** Print at most 10 lines: what was done, where the evidence is, the next unit,
   and any human action needed. End with: `Open a new session and type: continue`.

The detailed rules behind each step are in `ai/PROTOCOL.md`. Read it in the first session, and later
only when something unusual happens (conflict, failure, recovery).

## 2. What the human may type

| Input | Meaning |
|---|---|
| `continue` or `/continue` | Run the loop on `next_unit` |
| `continue M07` | Run the loop on M07 (only if its dependencies are DONE) |
| `status` or `/status` | Print progress from STATE.md. No work, no commit |
| `audit` / `audit M05` or `/audit` | Re-run the audit only; record the result |
| `redo M05 S3` | Reset M05 to step S3 and continue from there |
| `fix ISSUE-12` | Work only on that issue |
| `quick` appended to any command | Use quick measurement sizes (for low-battery or demo) |

## 3. Hard rules (never break these)

1. **No fabricated evidence.** Every number in any log, table, figure or doc must come from a
   command run in *this repository*, saved under `runs/`, and indexed in `METRICS_INDEX.md`.
   If something cannot be measured (no GPU counter access, no nvcc), record `NOT_MEASURED` with
   the reason. Never estimate, extrapolate or copy numbers from the paper or seed files as results.
2. **The GPU is the measurement device.** Kernel and pipeline timings use CUDA events
   (`cupy.cuda.Event`), with warm-up and ≥30 timed runs, and NVML telemetry captured alongside.
   Wall-clock `time.time()` is allowed only for end-to-end service latency (M15).
   See `ai/GPU_GUIDE.md`.
3. **Obliviousness.** Server-side kernels must not branch on, or index memory by, secret data.
   Branches and indices may depend only on thread/block ids and public parameters (n, k, j, S, K).
   See `ai/CONVENTIONS.md §2`.
4. **Secrets.** Plaintext `K_master`, `K_tag`, `K_seq`, `K_bkt` and `K_content` never touch disk,
   logs, test fixtures (use fixed *test* keys defined in tests only), exceptions or git.
   Server subkeys live in GPU memory only (see ADR-003).
5. **One unit per session.** Never start the next module in the same session, even if time remains.
   A large module may take several sessions, each ending at a checkpoint.
6. **Human gates.** When something needs the human (install, admin rights, a passphrase, a decision),
   write a `HUMAN ACTION REQUIRED` issue with exact instructions, set `status: BLOCKED_HUMAN`, and stop.
7. **Token discipline.** Do not paste long outputs into chat. Redirect to files and show `tail`.
   Do not re-read files you have already read this session. Prefer `grep -n` and `sed -n 'a,bp'`.
8. **Specs are read-only.** Do not edit `ai/*` except: append ADRs to `ai/DECISIONS.md`, and add an
   `## Amendments` note at the bottom of a module file (with date and reason) when reality differs.
9. **Tests before claims.** A step is complete only when its check command passes. A module is
   `DONE` only when its audit passes.
10. **Attribution.** Every commit carries `[owner:<name>]` from the module header, so work is
    attributable to the team member who owns it (a Review-3 requirement).

## 4. Map (open only when a unit requires it)

| File | Purpose |
|---|---|
| `ai/PROTOCOL.md` | Full session protocol, state machine, recovery, human gates |
| `ai/PROJECT_BRIEF.md` | What V-cloak is: threat model, properties P1–P3, keys, parameters |
| `ai/ARCHITECTURE.md` | Components, data-state flow, repo layout, module interfaces |
| `ai/CONVENTIONS.md` | Coding, obliviousness, crypto and git conventions |
| `ai/GPU_GUIDE.md` | CUDA-via-CuPy rules, kernel patterns, measurement methodology |
| `ai/SKILLS_MATRIX.md` | Skills each module needs; owner per module |
| `ai/LOGGING_AND_AUDIT.md` | Log formats, run manifests, global audit G1–G10 |
| `ai/TESTING.md` | Test layers, golden vectors, acceptance gates |
| `ai/DECISIONS.md` | Architecture decision records (ADR) |
| `ai/modules/M00…M17` | The work units |
| `state/*` | Live progress, logs, audits, issues, metrics |
| `seed/` | Existing reference oracle and paper results contract (inputs, not results) |
