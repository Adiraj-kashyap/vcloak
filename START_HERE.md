# START HERE — how to run the V-cloak autonomous build

This folder is a **build kit**. Open it in **Claude Code** and type `continue`. Each session builds one
piece of V-cloak on your laptop's GPU, tests it, audits it, logs it, commits it, and stops.
Open a new session, type `continue`, and it picks up the next piece.

> Why Claude Code and not a normal chat? The agent must run CUDA on *your* GPU, run tests, and write
> files and git commits in this folder. A browser chat cannot reach your GPU. Use the Claude Code
> desktop app, the VS Code extension, or the terminal (`claude`) opened **in this folder**.

---

## 1. Folder structure (keep exactly this)

```
vcloak/                          ← open THIS folder in Claude Code (the project root)
├── CLAUDE.md                    ← auto-loaded every session: the rules + session loop
├── START_HERE.md                ← this file (for humans)
├── .claude/
│   ├── settings.json            ← pre-approved safe commands (fewer permission prompts)
│   └── skills/
│       ├── continue/SKILL.md    ← /continue  : do the next unit
│       ├── status/SKILL.md      ← /status    : show progress, no work
│       ├── audit/SKILL.md       ← /audit Mxx : re-audit a module
│       ├── gpu-bench/SKILL.md   ← GPU measurement procedure (auto-used)
│       └── session-close/SKILL.md ← logging/commit/handoff procedure (auto-used)
├── ai/                          ← specifications (read on demand, never all at once)
│   ├── PROTOCOL.md  PROJECT_BRIEF.md  ARCHITECTURE.md  CONVENTIONS.md
│   ├── GPU_GUIDE.md  SKILLS_MATRIX.md  LOGGING_AND_AUDIT.md  TESTING.md  DECISIONS.md
│   └── modules/M00 … M17        ← one file per work unit
├── state/                       ← live memory between sessions (agent-maintained)
│   ├── STATE.md                 ← where we are; what's next
│   ├── SESSION_LOG.md           ← one entry per session
│   ├── AUDIT_LOG.md             ← audit results per module
│   ├── ISSUES.md                ← blockers and HUMAN ACTION REQUIRED items
│   └── METRICS_INDEX.md         ← every measured number, with its evidence folder
└── seed/
    ├── vcloak_oracle.py         ← existing reference implementation (input, not results)
    └── PAPER_RESULTS_CONTRACT.md ← file/macro names the Overleaf paper expects
```
The agent creates everything else (`src/`, `kernels/`, `tests/`, `bench/`, `runs/`, `results/`, `docs/`).
Do not rename or move the kit files. Do not edit `state/` by hand unless asked by an issue.

## 2. One-time setup (15 minutes)

1. **Hardware:** a laptop or PC with an NVIDIA GPU (GTX 10-series or newer). Keep it **plugged in** for every session.
2. **Install:** the NVIDIA driver, **CUDA Toolkit 12.x** (gives nvcc, cuobjdump, Nsight Compute), Python 3.10–3.12, Git,
   and Docker Desktop (for PostgreSQL, needed from M09 onward). M00 checks all of this and tells you if something's missing.
3. **Install Claude Code** (desktop app or `npm install -g @anthropic-ai/claude-code`) and sign in.
4. Put this folder somewhere without spaces in the path (e.g. `C:\dev\vcloak` or `~/dev/vcloak`).
5. **Team attribution:** before *your* sessions, set your git identity in this folder:
   `git config user.name "Aditya Raj"` and `git config user.email "<you>@vitstudent.ac.in"`.
   Each module has an owner (see `state/STATE.md`); run your own modules so the git history matches the contributions slide.

## 3. Daily use

| You type | What happens |
|---|---|
| `continue` | Does the next unit, then stops with a ≤10-line handoff |
| `continue M07` | Works on M07 specifically (if its dependencies are done) |
| `continue quick` | Same, with small measurement sizes (quick numbers never go into final results) |
| `status` | Progress table, open issues, latest metrics. No changes |
| `audit M05` | Re-checks a finished module |
| `fix ISSUE-4` | Works only on that issue |

**After each handoff: start a new session** (a new tab in the desktop app, or `/clear` in the terminal), then type `continue`.
A fresh session only reads `CLAUDE.md` + `state/STATE.md` + the current module file, which keeps token use low.

**If the handoff says HUMAN ACTION REQUIRED:** open `state/ISSUES.md`, do the listed steps, then type `continue`.

## 4. Plan and expected effort

| Phase | Modules | Sessions (approx.) | Outcome |
|---|---|---|---|
| Foundation | M00–M02 | 3 | Environment, oracle, crypto references |
| **GPU core** | M03–M06 | 7 | CUDA kernels + engine, bit-exact with the oracle |
| **GPU evidence** | M07–M08 | 4 | Performance sweeps, crossover, dudect / ncu / SASS |
| System | M09–M12 | 6 | PostgreSQL, service, session security, client demo |
| Evaluation | M14–M15 | 4 | Security results on the real stack, end-to-end latency |
| Wrap-up | M16–M17 | 2–3 | Paper macros, figures, final audit, demo runbook |
| Optional | M13 | 1 | Browser client |

**Review-3 fast path (~50% of scope with real GPU evidence):** M00 → M08 (about 14 sessions).
If time allows, add M09–M11 so you can demo the live service and the Review-2 session security.

## 5. What makes this reliable

- **No invented numbers.** Every number must come from a command run in this repo, saved under `runs/` with a
  manifest, and listed in `state/METRICS_INDEX.md`. Unmeasurable items are marked `NOT_MEASURED` with a reason.
- **GPU measurement discipline.** CUDA-event timing, warm-up, ≥30 runs, NVML clocks/power/temperature, throttling detection.
- **Bit-exact verification.** Every GPU kernel is checked byte-for-byte against the CPU reference.
- **Audits.** Every module ends with its own checklist plus 10 global checks (tests, evidence, obliviousness, secrets,
  git, state, logs, reproducibility). A failed audit blocks progress until it's fixed.
- **Checkpoints.** STATE.md is updated after every step, so an interrupted session loses at most one step.

## 6. Two design corrections the kit already applies (tell your guide)

1. **ADR-005:** the kernel in the paper's Listing 1 (one thread per element) has a race. The partner thread's `x ^= 0`
   write can overwrite the real swap. The kit uses one thread per compare-exchange pair.
2. **ADR-003:** to keep server keys GPU-only, server-side crypto moves to ChaCha20 / Poly1305 (table-free, GPU-native)
   instead of HKDF/HMAC/AES-GCM on the CPU. Client message encryption is unchanged (X25519 + AES-256-GCM).
   M16 produces `results/PAPER_UPDATES.md` listing the paper text to update.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| The agent starts reading every file | Say: "Follow CLAUDE.md §1: read only STATE.md and the current module." |
| The agent tries to do two modules | Say: "Stop at the handoff (CLAUDE.md rule 5)." |
| `ncu` permission error (M08) | Windows: NVIDIA Control Panel → Desktop → Enable Developer Settings → Developer → Manage GPU Performance Counters → "Allow access to all users". Linux: run with sudo or set `NVreg_RestrictProfilingToAdminUsers=0`. |
| CuPy can't find CUDA | Match `cupy-cuda12x`/`cupy-cuda11x` to the CUDA version shown by `nvidia-smi`; reinstall the toolkit. |
| Numbers vary a lot | Plug in, close games/browsers, then `redo M07 S2`. The kit records UNSTABLE runs instead of hiding them. |
| STATE looks wrong | Type `status`, then `audit Mxx` for the module in doubt. Git history is the source of truth. |
